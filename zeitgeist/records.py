"""Run bookkeeping: what a run was configured with, how its stages went, and
what it rendered.

Separate from `models.py`, which is the pipeline's domain — items, topics,
dossiers, the things the stages pass between them. These are records *about*
a run rather than data flowing *through* one, and the UI reads them where it
never reads an `Item`.

`Stage` lives here rather than in `pipeline.py` because `store.py` needs it
and `pipeline.py` imports `store.py`; keeping it there would be a cycle.
"""

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from zeitgeist.config import Settings
from zeitgeist.models import STRICT


class Stage(StrEnum):
    INGEST = "ingest"
    ANALYSE = "analyse"
    EVALUATE = "evaluate"
    GENERATE = "generate"


ORDER = [Stage.INGEST, Stage.ANALYSE, Stage.EVALUATE, Stage.GENERATE]

# `interrupted` is set on startup for a run left `running` by a process that
# died. Phase 3 does the reconciling; the value exists here so the schema and
# the model agree from the start.
RunStatus = Literal["running", "ok", "failed", "aborted", "interrupted"]
StageStatus = Literal["queued", "running", "ok", "failed", "skipped"]


class RunConfig(BaseModel):
    """The settings a run used, frozen at its start.

    A copy rather than a reference: run detail's config line and the "Re-run
    config" action must show what the run actually used, which is not
    recoverable from a `.env` that has since been edited.
    """

    model_config = STRICT

    sources: list[str]
    trend_limit: int
    posts_per_trend: int
    top_count: int
    meme_potential_weight: float
    phrase_min_authors: int
    distil_char_budget: int
    distil_concurrency: int
    llm_provider: str
    llm_model: str
    # None means the whole library, matching the pipeline's own convention.
    template_ids: list[str] | None

    @classmethod
    def freeze(cls, settings: Settings, template_ids: list[str] | None) -> RunConfig:
        return cls(
            sources=list(settings.sources),
            trend_limit=settings.bluesky_trend_limit,
            posts_per_trend=settings.bluesky_posts_per_trend,
            top_count=settings.topic_count,
            meme_potential_weight=settings.meme_potential_weight,
            phrase_min_authors=settings.phrase_min_authors,
            distil_char_budget=settings.distil_char_budget,
            distil_concurrency=settings.distil_concurrency,
            llm_provider=settings.llm_provider,
            llm_model=settings.llm_model,
            template_ids=list(template_ids) if template_ids is not None else None,
        )


class RunError(BaseModel):
    """Why a run failed, and where.

    `kind` is the exception class name rather than the instance, because the
    Runs screen renders it as a label — "RenderError in generate".
    """

    model_config = STRICT

    kind: str
    message: str
    stage: Stage


class StageRecord(BaseModel):
    """One stage of one run.

    Every `| None` here is a real state: a queued stage has not started, a
    running one has not finished, and a failed or skipped one wrote no
    checkpoint.
    """

    model_config = STRICT

    stage: Stage
    status: StageStatus
    started_at: datetime | None
    finished_at: datetime | None
    payload_bytes: int | None
    summary: str


class AutoOrigin(BaseModel):
    """A render the model briefed: it chose the template and said why."""

    model_config = STRICT

    provenance: Literal["auto"] = "auto"
    rationale: str


class ManualOrigin(BaseModel):
    """A render written by hand. No model call, so no choice to explain."""

    model_config = STRICT

    provenance: Literal["manual"] = "manual"


# Discriminated so a stored row deserialises back to the concrete class rather
# than to whichever member happens to validate — the same reason `Metrics` is
# discriminated in models.py. Holding `rationale` on the union member rather
# than on RenderRecord is what makes a manual render with a rationale
# unrepresentable instead of merely discouraged.
Origin = Annotated[AutoOrigin | ManualOrigin, Field(discriminator="provenance")]


class RenderRecord(BaseModel):
    """One rendered meme. The database is authoritative for whether it exists;
    the PNG and its thumbnail live at `output/<run_id>/renders/<id>.png`.
    """

    model_config = STRICT

    id: str
    run_id: str
    topic_id: str
    template_id: str
    caption_slots: dict[str, str]
    origin: Origin
    status: Literal["generating", "ready", "failed"]
    error: str | None
    created_at: datetime
