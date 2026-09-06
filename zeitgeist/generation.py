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
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from zeitgeist.config import Settings
from zeitgeist.llm.base import LLMProvider
from zeitgeist.media.brief import BriefError, generate_brief
from zeitgeist.media.render import RenderError, render_meme, write_thumbnail
from zeitgeist.media.templates import TemplateManifest
from zeitgeist.models import STRICT, MediaBrief, Topic
from zeitgeist.records import AutoOrigin, ManualOrigin, Origin, RenderRecord
from zeitgeist.renders import render_paths
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
