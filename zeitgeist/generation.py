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
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from zeitgeist.config import Settings, resolve_settings
from zeitgeist.llm.base import LLMProvider
from zeitgeist.llm.factory import build_provider
from zeitgeist.media.brief import BriefError, check_slots, generate_brief
from zeitgeist.media.render import RenderError, render_meme, write_thumbnail
from zeitgeist.media.templates import TemplateManifest, load_templates
from zeitgeist.models import STRICT, MediaBrief, Topic
from zeitgeist.records import AutoOrigin, ManualOrigin, Origin, RenderRecord, Stage
from zeitgeist.renders import render_paths
from zeitgeist.store import Store, UnknownRun

log = logging.getLogger(__name__)

MAX_RENDERS = 4
"""Renders per request. The design's grid is 4-up, and the panel offers a
count rather than an unbounded field: `count=50` is fifty model calls on a
single click, on a provider that may be one local GPU."""


class LLMGeneration(BaseModel):
    """Ask the model to write `count` briefs.

    `template_id` is a template the panel picked as an override. None — the
    panel's default, "Let the LLM choose" — offers the model the whole
    library and lets it pick per brief, exactly as the generate stage does.
    The below-the-cut `generate` link posts None too: a ranking row has no
    room to ask which template.
    """

    model_config = STRICT

    mode: Literal["llm"] = "llm"
    template_id: str | None = None
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
    # A named template narrows the library to that one, so the model writes
    # captions rather than picking; None offers it the whole library, which
    # is "Let the LLM choose". Either way `generate_brief` validates the
    # answer against the library it was given, so a model that names
    # anything else is retried and then fails, rather than rendering onto a
    # template nobody offered it.
    # Bound to a local so the narrowing below is on a name, which every
    # type checker follows, rather than on an attribute access.
    template_id = request.template_id
    library = (
        job.templates
        if template_id is None
        else {template_id: job.templates[template_id]}
    )
    return generate_brief(job.topic, library, job.provider)


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


class GenerationUnavailable(RuntimeError):
    """The service is shut down, or was shut down mid-`submit`.

    Its own type rather than the bare `RuntimeError` both paths used to
    raise, so the endpoint can answer 503 without also catching a
    `RuntimeError` that means something else entirely. A `RuntimeError`
    subclass because that is what `ThreadPoolExecutor.submit` raises when
    it refuses, and the one path that re-raises it is re-raising exactly
    that.
    """


class GenerationRefused(ValueError):
    """The request named a template that is not in the library, or captions
    that do not fit the template's slots.

    A `ValueError` subclass so an endpoint catching `ValueError` — which is
    also what `build_provider` raises for a missing API key — gives all of
    them the 400 they deserve.
    """


class RunBusy(RuntimeError):
    """A generation job for the run is still in flight, so the run cannot
    be deleted yet. The endpoint answers 409: nothing is wrong with the
    request, it has only come too early."""


def _uncount(counts: dict[str, int], run_id: str) -> None:
    """Take one off `run_id`'s count, dropping the key at zero so a run with
    nothing left counted reads the same as one never counted at all.
    Callers hold `GenerationService._lock`."""
    remaining = counts.get(run_id, 0) - 1
    if remaining > 0:
        counts[run_id] = remaining
    else:
        counts.pop(run_id, None)


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
        # Jobs submitted and not yet finished, per run, and deletes of each
        # run in progress right now — both counts, both under `_lock`. The
        # stored `generating` status cannot stand in for the first: nothing
        # reconciles those rows after a restart, so a run whose server died
        # mid-job would hold them forever and could never be deleted. The
        # second is a count rather than a set because two tabs can delete
        # the same run at once, and the first to finish must not reopen it
        # to generation while the second is still inside `excluding`.
        self._in_flight: dict[str, int] = {}
        self._deleting: dict[str, int] = {}

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
                raise GenerationUnavailable("GenerationService is shut down")
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

    def _claim(self, run_id: str) -> None:
        """Count a job against `run_id`, unless the run is being deleted."""
        with self._lock:
            if run_id in self._deleting:
                raise UnknownRun(f"No such run: {run_id}")
            self._in_flight[run_id] = self._in_flight.get(run_id, 0) + 1

    def _release(self, run_id: str) -> None:
        """Uncount a finished job, so `excluding` stops refusing the run."""
        with self._lock:
            _uncount(self._in_flight, run_id)

    @contextmanager
    def excluding(self, run_id: str) -> Iterator[None]:
        """Hold off new jobs for `run_id` while it is deleted.

        Refuses with `RunBusy` if a job is already in flight: it would
        write PNGs under the run's directory after the delete removed it.
        Otherwise `submit` refuses the run until this exits. With
        `submit`'s claim-then-check, every interleaving is covered: its
        claim lands first and this refuses; this lands first and the claim
        is refused; or the delete finishes first and `submit` finds no row.
        """
        with self._lock:
            if self._in_flight.get(run_id, 0):
                raise RunBusy(
                    f"Memes are still generating for run {run_id}; wait for "
                    "them to finish before deleting it."
                )
            self._deleting[run_id] = self._deleting.get(run_id, 0) + 1
        try:
            yield
        finally:
            with self._lock:
                _uncount(self._deleting, run_id)

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
        topic". `UnknownRun` means the run is being deleted, or already
        has been.
        """
        # Before anything else, including the checkpoint read below: a
        # closed service must refuse on the request thread before a single
        # row is written, not after `_seed` has already committed them.
        # `_ensure_pool` raises `RuntimeError` here if `shutdown()` has run;
        # the pool it returns is not used until the very end of this
        # method, but obtaining it early is what makes the refusal happen
        # early.
        pool = self._ensure_pool()
        # Claimed before anything is read, so a delete arriving from here
        # on is refused rather than removing the run under this request.
        self._claim(run_id)
        handed_off = False
        try:
            if self._store.get_run(run_id) is None:
                raise UnknownRun(f"No such run: {run_id}")

            settings = resolve_settings(self._store, self._settings, {})

            # The analyse checkpoint holds *every* topic, not just the kept
            # ones, which is exactly what the below-the-cut `generate` link
            # needs — evaluate's payload would 404 a topic that was ranked
            # and not selected.
            topics = self._store.read_checkpoint(run_id, Stage.ANALYSE, Topic)
            topic = next((t for t in topics if t.id == topic_id), None)
            if topic is None:
                raise UnknownTopic(f"No such topic in {run_id}: {topic_id}")

            templates = load_templates(settings.templates_dir)
            # None is "let the model choose", which names nothing to check.
            if request.template_id is not None and request.template_id not in templates:
                raise GenerationRefused(
                    f"template_id {request.template_id!r} is not in the library; "
                    f"choose one of: {', '.join(sorted(templates))}"
                )

            provider: LLMProvider | None = None
            if isinstance(request, ManualGeneration):
                # The same rule the model's answer is held to. Refusing here
                # turns a bad request into a 400 rather than a failed tile
                # the user has to open to understand.
                problem = check_slots(
                    request.template_id, request.caption_slots, templates
                )
                if problem is not None:
                    raise GenerationRefused(problem)
            else:
                # On the request thread so a missing ANTHROPIC_API_KEY is a
                # 400 with a message, not a row that silently fails a second
                # later. Both providers hold thread-safe clients —
                # `distil.py` already shares one across a thread pool.
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
                request.template_id or "(the model's choice)",
            )
            try:
                pool.submit(self._run, run_id, job)
            except RuntimeError as exc:
                # The closed-flag check in `_ensure_pool`, above, now
                # catches the common case: a request arriving after
                # `shutdown()` has already run. This handler is not dead
                # code even so — it remains for the genuine interleaving
                # this comment originally described: `_ensure_pool`
                # releases `self._lock` before handing back the pool
                # reference, so another thread's `shutdown()` can swap
                # `self._pool` to `None` and shut the very pool we just
                # got, in the gap between that return and this `.submit()`.
                # The executor then refuses with `RuntimeError: cannot
                # schedule new futures after shutdown` — but `_seed` has
                # already committed the rows above, so without this
                # handler they would sit in `"generating"` forever,
                # indistinguishable from real in-flight work. Routing them
                # through the same `_fail_unfinished` a raised job uses
                # gives them the honest outcome. `self._store` is correct
                # here, not a fresh `Store`: `submit` runs on the request
                # thread, and `self._store` is that thread's connection —
                # the same one `_seed` just wrote the rows through.
                # Re-raising is still correct — a 202 for work that will
                # never run would be a lie — but as `GenerationUnavailable`,
                # so this comes out of the endpoint as the 503 it is rather
                # than a 500 that reads as a broken server.
                self._fail_unfinished(self._store, job, exc)
                raise GenerationUnavailable(str(exc)) from exc
            handed_off = True
            return records
        finally:
            # Once the pool has the job, `_run` releases it when the job
            # ends. Every other way out of here must release it now.
            if not handed_off:
                self._release(run_id)

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

        `template_id` is the request's own, which is None when the model is
        choosing. `_draw` writes the one it chose. A brief that fails before
        the model chose leaves it None, which is the truth about that row.

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

    def _run(self, run_id: str, job: GenerationJob) -> None:
        """The worker side. Opens and closes its own `Store`.

        A connection per job rather than one per pool thread: `sqlite3`
        connections are thread-bound, `ThreadPoolExecutor` gives no hook to
        open one when it spawns a thread, and a job takes seconds to
        minutes while opening a connection takes milliseconds. Thread-local
        storage would buy nothing and would hold a connection open for the
        process's lifetime.

        The job's own `settings` still governs everything tunable — that is
        what `resolve_settings` resolved it for — but the database is the
        same file for every job in this service, so its location comes from
        `self._store` rather than from `job.settings`, which no longer
        carries one. Releases the run's claim when the job ends, however it
        ends, so `excluding` stops refusing its deletion — including if
        opening `store` itself raises, or if `store.close()` does: the
        outer `finally` covers the whole body, not just the generation
        call, so no failure here can leave a run permanently excluded.

        Nothing reads the `Future` this runs in, so a `Store(...)` failure
        that isn't logged here vanishes with no trace anywhere. The seeded
        rows are then failed through the service's own `self._store`, which
        is already open and safe to share across threads — the same store
        `submit` fails them through when the pool refuses a job. Left
        `generating`, they would spin on topic detail forever.
        """
        try:
            try:
                store = Store(self._store.path)
            except Exception as exc:  # noqa: BLE001 - one job's failure is a row
                log.exception(
                    "Generation job for topic %s failed to open its Store",
                    job.topic.id,
                )
                self._fail_unfinished(self._store, job, exc)
                return
            try:
                self._generate(job, store)
            except Exception as exc:  # noqa: BLE001 - one job's failure is a row
                log.exception("Generation job for topic %s failed", job.topic.id)
                self._fail_unfinished(store, job, exc)
            finally:
                store.close()
        finally:
            self._release(run_id)

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
