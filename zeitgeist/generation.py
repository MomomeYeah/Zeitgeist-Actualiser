"""On-demand meme generation: what topic detail's two panels drive.

Separate from `RunService` deliberately. The design shows tiles generating
on topic detail while a run is in flight, so the two cannot share a worker.
That means two concurrent callers of the LLM provider — free on Anthropic,
contended on local Ollama, where inference serialises on one GPU.
Documented rather than solved with a global lock.

Imports nothing from `zeitgeist.api`, for the same reason `runner.py` does
not: generation is a pipeline concern the API drives, not the reverse. The
request models live here rather than in `api/schemas.py` on that same rule,
exactly as `RunRequest` does.
"""

import logging
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from zeitgeist.config import Settings
from zeitgeist.llm.base import LLMProvider
from zeitgeist.llm.factory import build_provider
from zeitgeist.media.brief import BriefError, check_slots, generate_brief
from zeitgeist.media.render import RenderError, render_meme, write_thumbnail
from zeitgeist.media.templates import TemplateManifest, load_templates
from zeitgeist.models import STRICT, MediaBrief, Topic
from zeitgeist.records import AutoOrigin, ManualOrigin, Origin, RenderRecord, Stage
from zeitgeist.renders import render_paths
from zeitgeist.runner import resolve_settings
from zeitgeist.store import Store

log = logging.getLogger(__name__)

MAX_RENDERS = 4
"""Renders per request. The design's grid is 4-up, and the panel offers a
count rather than an unbounded field: `count=50` is fifty model calls on a
single click, on a provider that may be one local GPU."""


class LLMGeneration(BaseModel):
    """Ask the model to write `count` briefs against one named template.

    The template is named rather than chosen, because the panel already
    made that choice. The model writes captions for it and explains them.
    """

    model_config = STRICT

    mode: Literal["llm"] = "llm"
    template_id: str
    count: Annotated[int, Field(ge=1, le=MAX_RENDERS)] = 1


class ManualGeneration(BaseModel):
    """Render captions a person typed.

    No `count`: the captions describe exactly one meme, and a count beside
    them would be a representable state with no meaning. No model call, so
    nothing to explain either — the row's `ManualOrigin` has no rationale
    field at all.
    """

    model_config = STRICT

    mode: Literal["manual"] = "manual"
    template_id: str
    caption_slots: dict[str, str]


GenerationRequest = LLMGeneration | ManualGeneration
"""The two panels. Discriminated on `mode` where it crosses the wire — see
`api/generate.py`, which is the only place that needs the discriminator;
inside this module the union is narrowed with `isinstance`."""


@dataclass(frozen=True)
class GenerationJob:
    """Everything a worker needs, resolved on the request thread.

    Resolved up front rather than looked up in the worker, so an unknown
    template, a missing topic or an unusable provider is a 4xx before any
    row exists — not a failed tile the user has to read to find out their
    request was malformed.
    """

    settings: Settings
    request: GenerationRequest
    topic: Topic
    templates: dict[str, TemplateManifest]
    # Already inserted, already `generating`. The worker fills them in.
    records: list[RenderRecord]
    # None for a manual job, which makes no model call. A real state, not
    # a placeholder: building a provider for a hand-written render would
    # refuse a request that needs no API key at all.
    provider: LLMProvider | None


GenerateFn = Callable[[GenerationJob, Store], None]


def generate_renders(job: GenerationJob, store: Store) -> None:
    """Fill in every seeded record. One render's failure is one row.

    Injectable through `GenerationService(generate=...)` so an API test can
    drive the endpoint without Pillow or a model, the same seam
    `RunService` gives `_execute`.
    """
    for record in job.records:
        try:
            brief = _brief_for(job)
        except BriefError as exc:
            log.warning("Could not brief %s: %s", record.topic_id, exc)
            store.update_render(
                record.model_copy(update={"status": "failed", "error": str(exc)})
            )
            continue
        _draw(job, store, record, brief)


def _brief_for(job: GenerationJob) -> MediaBrief:
    """The captions to draw, however they were arrived at."""
    request = job.request
    if isinstance(request, ManualGeneration):
        # A transport object for the renderer, not a record of provenance:
        # the row's ManualOrigin carries that, and it has no rationale
        # field. Empty here rather than invented copy.
        return MediaBrief(
            topic_id=job.topic.id,
            template_id=request.template_id,
            caption_slots=dict(request.caption_slots),
            rationale="",
        )
    if job.provider is None:
        raise BriefError("An llm generation job was built with no provider")
    # Narrowed to the one template the panel named. `generate_brief`
    # validates the model's answer against this library, so a model that
    # names anything else is retried and then fails, rather than rendering
    # onto a template nobody asked for.
    return generate_brief(
        job.topic,
        {request.template_id: job.templates[request.template_id]},
        job.provider,
    )


def _draw(
    job: GenerationJob, store: Store, record: RenderRecord, brief: MediaBrief
) -> None:
    """Composite the brief, write both files, and finish the row.

    `update_render` rather than `add_render`: a render deleted while this
    job was running must stay deleted, and an UPDATE against a missing row
    is a no-op. The PNG written just above is then orphaned, which is
    invisible and reclaimed with the run directory.
    """
    paths = render_paths(job.settings.output_dir, record.run_id, record.id)
    error: str | None = None
    try:
        render_meme(
            brief,
            job.templates[brief.template_id],
            job.settings.templates_dir,
            paths.full,
            job.settings.font_path,
        )
        write_thumbnail(paths.full, paths.thumb)
    except RenderError as exc:
        log.warning("Could not render %s: %s", record.topic_id, exc)
        error = str(exc)

    store.update_render(
        record.model_copy(
            update={
                "template_id": brief.template_id,
                "caption_slots": dict(brief.caption_slots),
                "origin": _origin(job.request, brief),
                "status": "failed" if error else "ready",
                "error": error,
            }
        )
    )


def _origin(request: GenerationRequest, brief: MediaBrief) -> Origin:
    """Fixed by which panel asked. A hand-written render has no template
    choice to justify — the person made it."""
    if isinstance(request, ManualGeneration):
        return ManualOrigin()
    return AutoOrigin(rationale=brief.rationale)


class UnknownTopic(LookupError):
    """No topic with that id in the run's `analyse` checkpoint.

    A `LookupError` rather than a `ValueError` so the endpoint can map it
    to 404 ahead of the 400 that `GenerationRefused` and `build_provider`
    both raise: a topic that is not there is a different story from a
    request that is malformed.
    """


class GenerationRefused(ValueError):
    """The request named a template that is not in the library, or captions
    that do not fit the template's slots.

    A `ValueError` subclass so an endpoint catching `ValueError` — which is
    also what `build_provider` raises for a missing API key — gives all of
    them the 400 they deserve.
    """


class GenerationService:
    """The on-demand executor and everything it validates first.

    One worker, deliberately. The run worker is the other concurrent caller
    of the LLM provider, and a second generation thread would make three
    against a local Ollama that serialises on one GPU. "Small" is the
    spec's word for it.

    No `start()`, unlike `RunService`. A run worker has to be running
    before any request arrives because it drains a queue; a generation pool
    has nothing to do until a request arrives, so the pool is created on
    first use and `ThreadPoolExecutor` spawns no thread before then. An app
    that is built and never entered therefore leaves no thread behind,
    which is the same property `RunService.start` living in the lifespan
    buys.
    """

    def __init__(
        self,
        settings: Settings,
        store: Store,
        *,
        generate: GenerateFn | None = None,
    ) -> None:
        self._settings = settings
        self._store = store
        self._generate = generate or generate_renders
        self._pool: ThreadPoolExecutor | None = None
        self._closed = False
        self._lock = threading.Lock()

    def _ensure_pool(self) -> ThreadPoolExecutor:
        """Build the pool on first use, or hand back the one already built.

        Raises once `shutdown()` has run. Without this check, `shutdown()`
        setting `self._pool` back to `None` is indistinguishable from "never
        built yet", so a `submit` arriving after the app's lifespan has
        closed the service would read `None`, build a fresh non-daemon
        pool, and the process would then block on exit waiting for a job
        running against a `Store` the lifespan already closed. `self._closed`
        is the flag that makes "closed" and "not yet built" different
        states, checked under the same lock that guards pool creation so
        the two can never race each other.
        """
        with self._lock:
            if self._closed:
                raise RuntimeError("GenerationService is shut down")
            if self._pool is None:
                self._pool = ThreadPoolExecutor(
                    max_workers=1, thread_name_prefix="zeitgeist-generate"
                )
            return self._pool

    def shutdown(self, *, wait: bool = True) -> None:
        """Close the pool, waiting for what is in flight, and mark the
        service closed for good. Called from the app's lifespan, and from
        tests that need a job to have finished without sleeping for it.

        Final rather than resettable: a `GenerationService` is a
        lifespan-scoped object, and a `submit` arriving after shutdown must
        be refused, not quietly given a second pool built against settings
        and a `Store` the app has already torn down.
        """
        with self._lock:
            pool, self._pool = self._pool, None
            self._closed = True
        if pool is not None:
            pool.shutdown(wait=wait)

    def submit(
        self, run_id: str, topic_id: str, request: GenerationRequest
    ) -> list[RenderRecord]:
        """Validate, write the `generating` rows, and queue the work.

        Everything that can be refused is refused here, on the request
        thread, before a single row exists: the topic, the template, the
        captions and the provider. A request that gets past this line has
        rows the client can draw, and any failure after it is a per-render
        outcome the row itself carries.

        `MissingCheckpoint` propagates: a run that never analysed has
        nothing to brief from, which is a different answer from "no such
        topic".
        """
        # Before anything else, including the checkpoint read below: a
        # closed service must refuse on the request thread before a single
        # row is written, not after `_seed` has already committed them.
        # `_ensure_pool` raises `RuntimeError` here if `shutdown()` has run;
        # the pool it returns is not used until the very end of this
        # method, but obtaining it early is what makes the refusal happen
        # early.
        pool = self._ensure_pool()

        settings = resolve_settings(self._settings, {})

        # The analyse checkpoint holds *every* topic, not just the kept
        # ones, which is exactly what the below-the-cut `generate` link
        # needs — evaluate's payload would 404 a topic that was ranked and
        # not selected.
        topics = self._store.read_checkpoint(run_id, Stage.ANALYSE, Topic)
        topic = next((t for t in topics if t.id == topic_id), None)
        if topic is None:
            raise UnknownTopic(f"No such topic in {run_id}: {topic_id}")

        templates = load_templates(settings.templates_dir)
        if request.template_id not in templates:
            raise GenerationRefused(
                f"template_id {request.template_id!r} is not in the library; "
                f"choose one of: {', '.join(sorted(templates))}"
            )

        provider: LLMProvider | None = None
        if isinstance(request, ManualGeneration):
            # The same rule the model's answer is held to. Refusing here
            # turns a bad request into a 400 rather than a failed tile the
            # user has to open to understand.
            problem = check_slots(request.template_id, request.caption_slots, templates)
            if problem is not None:
                raise GenerationRefused(problem)
        else:
            # On the request thread so a missing ANTHROPIC_API_KEY is a
            # 400 with a message, not a row that silently fails a second
            # later. Both providers hold thread-safe clients — `distil.py`
            # already shares one across a thread pool.
            provider = build_provider(settings)

        records = self._seed(run_id, topic_id, request)
        job = GenerationJob(
            settings=settings,
            request=request,
            topic=topic,
            templates=templates,
            records=records,
            provider=provider,
        )
        log.info(
            "Queued %d %s render(s) for %s/%s on template %s",
            len(records),
            request.mode,
            run_id,
            topic_id,
            request.template_id,
        )
        try:
            pool.submit(self._run, job)
        except RuntimeError as exc:
            # The closed-flag check in `_ensure_pool`, above, now catches
            # the common case: a request arriving after `shutdown()` has
            # already run. This handler is not dead code even so — it
            # remains for the genuine interleaving this comment originally
            # described: `_ensure_pool` releases `self._lock` before
            # handing back the pool reference, so another thread's
            # `shutdown()` can swap `self._pool` to `None` and shut the
            # very pool we just got, in the gap between that return and
            # this `.submit()`. The executor then refuses with
            # `RuntimeError: cannot schedule new futures after shutdown` —
            # but `_seed` has already committed the rows above, so without
            # this handler they would sit in `"generating"` forever,
            # indistinguishable from real in-flight work. Routing them
            # through the same `_fail_unfinished` a raised job uses gives
            # them the honest outcome. `self._store` is correct here, not a
            # fresh `Store`: `submit` runs on the request thread, and
            # `self._store` is that thread's connection — the same one
            # `_seed` just wrote the rows through. Re-raising is still
            # correct: a 202 for work that will never run would be a lie,
            # and a 500 during a shutdown race is the honest answer.
            self._fail_unfinished(self._store, job, exc)
            raise
        return records

    def _seed(
        self, run_id: str, topic_id: str, request: GenerationRequest
    ) -> list[RenderRecord]:
        """Insert one `generating` row per requested render.

        Written before `submit` returns, not when the job finishes: the
        database is authoritative for whether a render exists, so a tile
        with no row behind it would vanish on the next reload.

        For an `llm` request the brief does not exist yet, so the row
        carries `caption_slots={}` and an empty rationale, both filled in
        by `_draw`. The record's *kind* is still fixed at creation, which
        is the invariant the origin union protects; what changes is
        `status`. A `generating` record's captions and rationale must not
        be read.

        This *appends*. A re-run of the generate stage clears a topic's
        prior auto renders (see `zeitgeist.renders.clear_auto_renders`),
        but an on-demand request is an additive action somebody took, and
        clearing here would delete the render they asked for this one to
        be compared against.

        Written with `Store.add_renders` — one transaction for the whole
        batch — rather than one `add_render` call per record. A `count=4`
        seed as four independent commits means a failure on the third
        (a lock the busy timeout could not outlast, a disk-full `OSError`)
        would propagate out of `submit` with two rows already committed as
        `"generating"`, and nothing left that will ever finish them.
        All-or-nothing means a failure here leaves nothing behind to clean
        up.
        """
        count = 1 if isinstance(request, ManualGeneration) else request.count
        captions = (
            dict(request.caption_slots) if isinstance(request, ManualGeneration) else {}
        )
        origin: Origin = (
            ManualOrigin()
            if isinstance(request, ManualGeneration)
            else AutoOrigin(rationale="")
        )

        records = [
            RenderRecord(
                id=uuid4().hex,
                run_id=run_id,
                topic_id=topic_id,
                template_id=request.template_id,
                caption_slots=captions,
                origin=origin,
                status="generating",
                error=None,
                created_at=datetime.now(UTC),
            )
            for _ in range(count)
        ]
        self._store.add_renders(records)
        return records

    def _run(self, job: GenerationJob) -> None:
        """The worker side. Opens and closes its own `Store`.

        A connection per job rather than one per pool thread: `sqlite3`
        connections are thread-bound, `ThreadPoolExecutor` gives no hook to
        open one when it spawns a thread, and a job takes seconds to
        minutes while opening a connection takes milliseconds. Thread-local
        storage would buy nothing and would hold a connection open for the
        process's lifetime.

        `job.settings` rather than `self._settings`: the job carries the
        settings this work was resolved under, and reaching past it to the
        service's base snapshot would be a second, quieter source of truth
        for the same value.
        """
        store = Store(job.settings.db_path)
        try:
            self._generate(job, store)
        except Exception as exc:  # noqa: BLE001 - one job's failure is a row
            log.exception("Generation job for topic %s failed", job.topic.id)
            self._fail_unfinished(store, job, exc)
        finally:
            store.close()

    def _fail_unfinished(
        self, store: Store, job: GenerationJob, exc: Exception
    ) -> None:
        """Backstop for a job that raised out of `generate_renders`.

        Reads each row back rather than trusting the in-memory records: the
        job may have finished some of them before it fell over, and a row
        somebody deleted meanwhile must stay deleted. Without this a
        crashed job leaves tiles spinning forever, with nothing to
        distinguish them from work still in progress.
        """
        for record in job.records:
            current = store.get_render(record.id)
            if current is None or current.status != "generating":
                continue
            store.update_render(
                current.model_copy(
                    update={
                        "status": "failed",
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
            )
