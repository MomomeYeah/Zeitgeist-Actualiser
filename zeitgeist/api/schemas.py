"""Response models for endpoints whose shape is a composition.

Storage models are returned directly wherever they suffice — `TopicRow`,
`StageRecord` and `RenderRecord` are already the shape the UI reads. These
exist only where an endpoint joins several sources into one body.

Enveloping is inconsistent across the nine endpoints on purpose, not by
accident: `/api/runs` and `/api/topics` return an object carrying aggregates
(`RunPage`'s `next_cursor`, `TopicIndex`'s totals) alongside the list, while
`/api/settings`, `/api/runs/{id}/topics` and `/api/runs/{id}/log` return a
bare array because there is nothing beyond the list to carry. The rule is:
an envelope only where there are aggregates to carry. Phase 5 generates a
TypeScript client against all nine at once, so a later phase changing this
should be a deliberate decision to uphold or overturn the rule above, not
a drift nobody wrote down.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from zeitgeist.models import STRICT, Dossier
from zeitgeist.projection import TopicRow
from zeitgeist.records import RenderRecord, RunRecordRow, Stage, StageRecord

# Four layers, though the settings screen draws three chips. A shell
# variable outranks the settings table, so `environment` is a real answer
# and the screen consuming this needs a fourth chip or a deliberate
# decision to fold it into one of the three.
SettingSource = Literal["settings", "environment", "dotenv", "default"]


class SettingField(BaseModel):
    """One tunable field, its effective value, and which layer supplied it."""

    model_config = STRICT

    key: str
    value: float | int
    source: SettingSource


class StartRunBody(BaseModel):
    """What `POST /api/runs` accepts.

    `overrides` is `str`-valued because the values come from a form and are
    validated by `Settings` when the worker freezes the run's config — the
    one place that knows each field's real type.
    """

    model_config = STRICT

    template_ids: list[str] | None = None
    overrides: dict[str, str] = {}


class ResumeBody(BaseModel):
    """`stage` omitted means the computed resume point — the button posts no
    stage. `template_ids` narrows the library for this resume only, which is
    the tuning loop: edit a manifest, re-render the same frozen topics.
    """

    model_config = STRICT

    stage: Stage | None = None
    template_ids: list[str] | None = None


class RunSummary(BaseModel):
    """One row of the Runs list.

    `topic_labels` and `render_ids` are joins the row needs and the run
    record does not carry: column two is the titles, column four the
    thumbnails.
    """

    model_config = STRICT

    run: RunRecordRow
    topic_labels: list[str]
    render_ids: list[str]


class RunPage(BaseModel):
    """One page of runs. `next_cursor` is None on the last page."""

    model_config = STRICT

    runs: list[RunSummary]
    next_cursor: str | None


class RunDetail(BaseModel):
    """One run's header: what it was configured with, how its stages went,
    and where a resume would start.
    """

    model_config = STRICT

    run: RunRecordRow
    stages: list[StageRecord]
    # None when nothing was written at all, which is what a source outage
    # looks like. The UI must not offer a resume it cannot honour.
    resume_stage: Stage | None


class RankedTopic(BaseModel):
    """One row of the ranking list.

    `above_cut` is computed from the run's frozen `top_count` rather than
    left to the client: the screen draws rows below the cut dashed and
    dimmed with a generate link, so the rule is load-bearing.
    """

    model_config = STRICT

    topic: TopicRow
    render_count: int
    above_cut: bool


class ReplyOut(BaseModel):
    """One reply, as the dossier shows it.

    No author, handle or avatar. `Reply.author_key` exists only to count the
    distinct accounts behind a repeated phrase; the project stores no
    personal data and an API that returned it would undo that.
    """

    model_config = STRICT

    text: str
    like_count: int
    created_at: datetime


class TopicRecurrence(BaseModel):
    """How often this topic has been seen, keyed on its label slug.

    A floor rather than a total: the slug fixes case and punctuation drift
    across runs but not wording drift, so a relabelled topic reads as new.
    """

    model_config = STRICT

    run_count: int
    first_seen_run_id: str | None


class TopicDetail(BaseModel):
    """One topic's dossier: the row, the prose, what people said, and what
    was rendered from it.
    """

    model_config = STRICT

    topic: TopicRow
    # None on the dormant path and on a stale checkpoint. The topic was
    # still ranked, so the row still exists.
    dossier: Dossier | None
    # {} on the same two paths as dossier=None: an empty breakdown and an
    # unknown one are the same thing to the screen, so this mirrors dossier
    # rather than being optional in its own right.
    score_components: dict[str, float]
    replies: list[ReplyOut]
    renders: list[RenderRecord]
    recurrence: TopicRecurrence


class IndexedTopic(BaseModel):
    """One card in the topics index.

    `run_count` is how many runs in the window carried this topic, keyed on
    its label slug — `SEEN IN 3 RUNS` on the card, or `NEW THIS RUN` at one.
    """

    model_config = STRICT

    topic: TopicRow
    run_count: int
    render_count: int


class TopicIndex(BaseModel):
    """The topics index and the aggregates drawn beside it.

    `status_totals` counts the whole window rather than the filtered list,
    because the filter chips show every bucket's total while one of them is
    active. `previous_sentiment_totals` is the run before the window, which
    is what the mood line's "versus the previous run" compares against.
    """

    model_config = STRICT

    topics: list[IndexedTopic]
    status_totals: dict[str, int]
    sentiment_totals: dict[str, int]
    previous_sentiment_totals: dict[str, int]
