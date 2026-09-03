# Web UI Phase 1 — Storage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the pipeline's four stage checkpoints out of `output/<run-id>/*.json` and into SQLite, add the run bookkeeping tables the web UI needs, and delete the CLI.

**Architecture:** SQLite becomes the source of truth for everything except rendered images. The four stage artifacts become JSON payloads in a `checkpoints` table; run records, stage records, renders and a flattened `run_topics` table sit alongside them. Rendered PNGs and 96px thumbnails stay on disk under `output/<run-id>/renders/`. No HTTP in this phase — the deliverable is `scripts/run_pipeline.py` persisting a complete run entirely through the store.

**Tech Stack:** Python 3.14, pydantic 2, pydantic-settings, sqlite3 (stdlib), Pillow, pytest, ruff, ty, uv.

## Global Constraints

Copied from `docs/superpowers/specs/2026-09-02-web-ui-design.md`. Every task's requirements implicitly include this section.

- **Definition of Done, run before claiming any task complete:** `uv run ruff check .`, `uv run ruff format --check .`, `uv run ty check`, `uv run pytest`. All four must pass. The frontend commands do **not** exist yet and must not be added in this phase.
- **No migrations.** `SCHEMA_VERSION` goes to 3; a mismatched database raises `StoreSchemaError` telling the user to delete it. Write no migration code.
- **Optionality expresses a real state, never a migration concession.** A field is `| None` only where the pipeline genuinely has no value for it. Runs already on disk are discarded, so no field is optional to accommodate them.
- **Python 3.14: use PEP 695 generics** (`def f[T: Bound](...)`), never `typing.TypeVar`.
- **`model_config = STRICT`** (`ConfigDict(extra="forbid")`, already in `zeitgeist/models.py`) on every new pydantic model.
- **ruff:** line length 88, rules `E, F, I, UP, B, SIM`. `docs/` is excluded.
- **ty:** fix type errors at the root cause. No blanket `# type: ignore`; a narrow suppression needs a comment explaining why.
- **Tests are hermetic.** No network. Every LLM call goes through `FakeLLMProvider`. `tests/conftest.py` strips every environment variable `Settings` reads — if you add a `Settings` field that reads the environment, add its variable to `_SETTINGS_ENV_VARS`.
- **Fixtures are built through the real models,** never hand-written dicts. See `tests/template_factory.py` for the established pattern.
- **No DEBUG or INFO log line may carry reply text, post bodies, or `author_key`.** This phase adds no logging, but do not add any that does.
- **Only these seven fields are writable through the settings table:** `trend_limit`, `posts_per_trend`, `bluesky_fetch_concurrency`, `meme_potential_weight`, `phrase_min_authors`, `distil_char_budget`, `distil_concurrency`. Note the first three are named `bluesky_trend_limit`, `bluesky_posts_per_trend` and `bluesky_fetch_concurrency` on `Settings`; the settings keys use the `Settings` field names verbatim.

## File Structure

**Created:**

| File | Responsibility |
| --- | --- |
| `zeitgeist/records.py` | Run bookkeeping models — `RunConfig`, `RunError`, `StageRecord`, `RenderRecord` and its `Origin` union. Separate from `models.py` because that file is the pipeline domain (`Item`, `Topic`, `Dossier`) and is already 342 lines. |
| `zeitgeist/schema.py` | The DDL and `SCHEMA_VERSION`. Keeps ~90 lines of SQL out of `store.py`. |
| `zeitgeist/projection.py` | One pure function flattening the analyse and evaluate payloads into `run_topics` rows. No I/O, no store. |
| `zeitgeist/settings_source.py` | The `pydantic-settings` source that reads the `settings` table. |
| `scripts/run_pipeline.py` | Dev harness. Replaces the CLI as the way to produce a run until phase 3. |
| `scripts/validate_templates.py` | Where `zeitgeist validate-templates` goes. |
| `tests/run_factory.py` | Model builders for run bookkeeping, mirroring `tests/template_factory.py`. |
| `tests/test_records.py`, `tests/test_projection.py`, `tests/test_settings_source.py` | Tests for the new modules. |

**Modified:** `zeitgeist/models.py` (`Topic.trend_status`), `zeitgeist/analysis/distil.py` (populate it), `zeitgeist/store.py` (v3 schema, all new accessors), `zeitgeist/pipeline.py` (persist through the store), `zeitgeist/media/render.py` (thumbnails), `zeitgeist/config.py` (settings source), `pyproject.toml` (drop `[project.scripts]`), `README.md`, and the existing test modules.

**Deleted:** `zeitgeist/cli.py`, `tests/test_cli.py`.

**Deliberately not built in this phase.** The `log_lines` table is created by the schema so phase 3 needs no second version bump, but **no accessor for it is written here** — phase 3 owns that. Likewise `renders` gets insert and read accessors because the pipeline writes renders, but **no delete accessor** — phase 4 owns that.

---

### Task 1: `Topic.trend_status`

The UI filters and sorts on trend status everywhere. `Topic` has no such field; the status lives on `TrendInfo.status` in the ingest evidence. Add it as a required field and populate it where the `TrendEvidence` is already in hand.

**Files:**
- Modify: `zeitgeist/models.py` (the `Topic` class, around line 300)
- Modify: `zeitgeist/analysis/distil.py:164-175` (the `Topic(...)` construction)
- Test: `tests/test_models.py`, `tests/test_analysis_distil.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `Topic.trend_status: TrendStatus` — required, no default. `TrendStatus` is the existing `Literal["trending", "saturating", "cooling", "stale"]` already exported from `zeitgeist/models.py`. Every later task that constructs a `Topic` or `ScoredTopic` must pass it.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_models.py`:

```python
def test_topic_requires_a_trend_status():
    """Every TrendEvidence carries a status, so a topic without one is a bug
    rather than a state. A default would let one through silently."""
    with pytest.raises(ValidationError):
        Topic(id="t", label="T", summary="s", item_ids=["x"])


def test_topic_keeps_the_trend_status_it_was_given():
    topic = Topic(
        id="t", label="T", summary="s", item_ids=["x"], trend_status="saturating"
    )

    assert topic.trend_status == "saturating"
```

`tests/test_models.py` already imports `pytest` and `Topic`; add `ValidationError` from `pydantic` to its imports if it is not there.

Add to `tests/test_analysis_distil.py`:

```python
def test_distil_carries_the_trend_status_onto_the_topic():
    """The status is Bluesky's own read on the trend's movement. It reaches
    the topic here or not at all — no later stage sees the evidence."""
    evidence = _evidence(status="cooling")
    provider = FakeLLMProvider(responses=[_draft()])

    [topic] = distil_topics([evidence], provider, Settings(_env_file=None))

    assert topic.trend_status == "cooling"
```

Read the top of `tests/test_analysis_distil.py` and reuse whatever helper it already has for building a `TrendEvidence`. If that helper does not accept a `status`, add the keyword with a default matching whatever it currently hardcodes, rather than writing a second helper.

Note that `tests/test_pipeline.py`'s own `_evidence` helper builds its `TrendInfo` with `status="stale"`, so any pipeline test asserting on `trend_status` sees `"stale"` unless it says otherwise.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_models.py -k trend_status tests/test_analysis_distil.py -k trend_status -v`

Expected: FAIL. The `test_models.py` cases fail because `Topic` currently accepts the omission and rejects the extra key (`extra="forbid"`); the distil case fails with `AttributeError` or a validation error.

- [ ] **Step 3: Add the field**

In `zeitgeist/models.py`, inside `class Topic`, after `item_ids`:

```python
    # Bluesky's own read on the trend's movement, carried from TrendInfo at
    # distillation. Required: every TrendEvidence has one, so a topic without
    # it is a bug. The UI filters and ranks on this in five places.
    trend_status: TrendStatus
```

- [ ] **Step 4: Populate it in distil**

In `zeitgeist/analysis/distil.py`, in the `Topic(...)` construction inside `distil_topics`, add after `item_ids=...`:

```python
                trend_status=entry.trend.status,
```

- [ ] **Step 5: Fix every other construction site**

Run: `uv run pytest 2>&1 | tail -40`

Every test that builds a `Topic` or `ScoredTopic` without `trend_status` now fails. Add `trend_status="trending"` to each unless the test is about status, in which case use the status it is about. Check at minimum: `tests/test_analysis_score.py`, `tests/test_analysis_sentiment.py`, `tests/test_media_brief.py`, `tests/test_pipeline.py`, `tests/test_store.py`.

- [ ] **Step 6: Run the full gate**

Run: `uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest`

Expected: all four pass.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "Carry the trend status onto Topic

The UI filters and ranks on trend_status in five places and Topic had no
such field - it lived only on TrendInfo in the ingest evidence, which no
stage after analyse reads. Required rather than optional because every
TrendEvidence carries one, so a topic without it is a bug, not a state.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: Run bookkeeping models

The records the design needs and the pipeline has never written: a run's frozen config, its per-stage timings, its failure, and a record per render.

**Files:**
- Create: `zeitgeist/records.py`
- Test: `tests/test_records.py`

**Interfaces:**
- Consumes: `Stage` from `zeitgeist.pipeline`, `STRICT` from `zeitgeist.models`.
- Produces:
  - `RunStatus = Literal["running", "ok", "failed", "aborted", "interrupted"]`
  - `StageStatus = Literal["queued", "running", "ok", "failed", "skipped"]`
  - `RunConfig` — fields `sources: list[str]`, `trend_limit: int`, `posts_per_trend: int`, `top_count: int`, `meme_potential_weight: float`, `phrase_min_authors: int`, `distil_char_budget: int`, `distil_concurrency: int`, `llm_provider: str`, `llm_model: str`, `template_ids: list[str] | None`; plus `classmethod freeze(settings: Settings, template_ids: list[str] | None) -> RunConfig`
  - `RunError` — `kind: str`, `message: str`, `stage: Stage`
  - `StageRecord` — `stage: Stage`, `status: StageStatus`, `started_at: datetime | None`, `finished_at: datetime | None`, `payload_bytes: int | None`, `summary: str`
  - `AutoOrigin` (`provenance: Literal["auto"]`, `rationale: str`), `ManualOrigin` (`provenance: Literal["manual"]`), `Origin` (discriminated union)
  - `RenderRecord` — `id: str`, `run_id: str`, `topic_id: str`, `template_id: str`, `caption_slots: dict[str, str]`, `origin: Origin`, `status: Literal["generating", "ready", "failed"]`, `error: str | None`, `created_at: datetime`

**Import-cycle note:** `zeitgeist/pipeline.py` imports from `zeitgeist/store.py`, and `store.py` will import `records.py`. So `records.py` must not import `pipeline.py` at runtime. `Stage` currently lives in `pipeline.py`. **Move `Stage` and `ORDER` into `zeitgeist/records.py`** and re-export them from `pipeline.py` (`from zeitgeist.records import ORDER, Stage`) so existing imports keep working.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_records.py`:

```python
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from zeitgeist.config import Settings
from zeitgeist.records import (
    AutoOrigin,
    ManualOrigin,
    RenderRecord,
    RunConfig,
    Stage,
    StageRecord,
)


def test_freeze_copies_the_settings_a_run_detail_config_line_shows():
    settings = Settings(_env_file=None, llm_model="claude-sonnet-5", topic_count=5)

    frozen = RunConfig.freeze(settings, template_ids=None)

    assert frozen.top_count == 5
    assert frozen.llm_model == "claude-sonnet-5"
    assert frozen.trend_limit == settings.bluesky_trend_limit
    assert frozen.template_ids is None


def test_freeze_is_a_copy_not_a_view():
    """The config line must show what the run used, not what .env says now."""
    settings = Settings(_env_file=None, topic_count=5)
    frozen = RunConfig.freeze(settings, template_ids=None)

    settings.topic_count = 9

    assert frozen.top_count == 5


def test_a_manual_render_has_no_rationale_field_at_all():
    """Not an empty string - a hand-written render has no template choice to
    justify, so the field should not be reachable."""
    origin = ManualOrigin()

    assert not hasattr(origin, "rationale")


def test_a_render_deserialises_back_to_its_concrete_origin_class():
    """Discriminated on provenance, so a row round-trips to the right class
    rather than to whichever union member happens to validate."""
    record = RenderRecord(
        id="abc",
        run_id="r1",
        topic_id="t1",
        template_id="drake",
        caption_slots={"rejected": "a", "preferred": "b"},
        origin=AutoOrigin(rationale="it fits"),
        status="ready",
        error=None,
        created_at=datetime(2026, 9, 1, tzinfo=UTC),
    )

    restored = RenderRecord.model_validate_json(record.model_dump_json())

    assert isinstance(restored.origin, AutoOrigin)
    assert restored.origin.rationale == "it fits"


def test_a_manual_render_round_trips_without_gaining_a_rationale():
    record = RenderRecord(
        id="abc",
        run_id="r1",
        topic_id="t1",
        template_id="drake",
        caption_slots={"rejected": "a", "preferred": "b"},
        origin=ManualOrigin(),
        status="ready",
        error=None,
        created_at=datetime(2026, 9, 1, tzinfo=UTC),
    )

    restored = RenderRecord.model_validate_json(record.model_dump_json())

    assert isinstance(restored.origin, ManualOrigin)


def test_a_queued_stage_has_no_timings():
    """Optionality here describes a real state, not a missing migration."""
    record = StageRecord(
        stage=Stage.INGEST,
        status="queued",
        started_at=None,
        finished_at=None,
        payload_bytes=None,
        summary="queued",
    )

    assert record.started_at is None


def test_records_reject_unknown_fields():
    with pytest.raises(ValidationError):
        StageRecord(
            stage=Stage.INGEST,
            status="queued",
            started_at=None,
            finished_at=None,
            payload_bytes=None,
            summary="queued",
            duration=3,
        )
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_records.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'zeitgeist.records'`.

- [ ] **Step 3: Write the module**

Create `zeitgeist/records.py`:

```python
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
    def freeze(
        cls, settings: Settings, template_ids: list[str] | None
    ) -> "RunConfig":
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
```

- [ ] **Step 4: Re-export `Stage` from `pipeline.py`**

In `zeitgeist/pipeline.py`, delete the `class Stage(StrEnum)` block and the `ORDER = [...]` line, remove the now-unused `from enum import StrEnum` import, and add:

```python
from zeitgeist.records import ORDER, Stage
```

Keeping the names importable from `pipeline` means no other module changes.

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_records.py -v`

Expected: PASS, 7 tests.

- [ ] **Step 6: Run the full gate**

Run: `uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest`

Expected: all four pass. `ty` will flag `Stage` re-exported but unused in `pipeline.py` if `pipeline.py` no longer references it — it does (`ORDER.index(start_at)`), so this should be clean.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "Add the run bookkeeping models

RunConfig, RunError, StageRecord and RenderRecord - the records the design
needs and the pipeline has never written. In their own module rather than
models.py, which is the pipeline domain and already 342 lines; these are
records about a run rather than data flowing through one.

Moves Stage and ORDER here from pipeline.py, since store.py needs Stage and
pipeline.py imports store.py. Both are re-exported from pipeline so no other
import changes.

Holds rationale on an AutoOrigin variant rather than on RenderRecord, so a
manual render carrying one is unrepresentable rather than merely discouraged
- the shape Metrics already uses in models.py.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: Run fixture factory

Model builders so later tests state only the values they assert on. Mirrors `tests/template_factory.py` exactly — no store, no I/O, just the real models.

**Files:**
- Create: `tests/run_factory.py`

**Interfaces:**
- Consumes: everything from Task 2.
- Produces: `make_run_config(**overrides) -> RunConfig`, `make_stage_record(stage=Stage.INGEST, **overrides) -> StageRecord`, `make_render_record(rid="rnd1", **overrides) -> RenderRecord`, `make_topic(tid="airport-cat", **overrides) -> Topic`, `make_scored_topic(tid="airport-cat", rank=1, **overrides) -> ScoredTopic`.

- [ ] **Step 1: Write the file**

There is no failing test to write first — this is test infrastructure, and Task 4 is its first consumer. Create `tests/run_factory.py`:

```python
"""Builders for run bookkeeping records and the topics tests store.

Built through the real models for the same reason `template_factory` is: a
change to `RunConfig` or `RenderRecord` surfaces as a type error at one site
rather than as a ValidationError raised from inside dozens of unrelated
tests. Passing these as plain dicts would defeat that — pydantic coerces
them at runtime and ty never checks them.

Defaults exist so a test states only what it asserts on. A test that cares
about a topic's sentiment passes one; the rest say nothing and get something
valid.
"""

from datetime import UTC, datetime

from zeitgeist.models import (
    Dossier,
    Phrase,
    Register,
    ScoredTopic,
    Sentiment,
    Topic,
    TrendStatus,
)
from zeitgeist.records import (
    AutoOrigin,
    Origin,
    RenderRecord,
    RunConfig,
    Stage,
    StageRecord,
    StageStatus,
)

FIXED_TIME = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


def make_run_config(
    *,
    sources: list[str] | None = None,
    trend_limit: int = 25,
    posts_per_trend: int = 10,
    top_count: int = 5,
    meme_potential_weight: float = 0.3,
    phrase_min_authors: int = 3,
    distil_char_budget: int = 24000,
    distil_concurrency: int = 4,
    llm_provider: str = "anthropic",
    llm_model: str = "claude-sonnet-5",
    template_ids: list[str] | None = None,
) -> RunConfig:
    return RunConfig(
        sources=sources if sources is not None else ["bluesky"],
        trend_limit=trend_limit,
        posts_per_trend=posts_per_trend,
        top_count=top_count,
        meme_potential_weight=meme_potential_weight,
        phrase_min_authors=phrase_min_authors,
        distil_char_budget=distil_char_budget,
        distil_concurrency=distil_concurrency,
        llm_provider=llm_provider,
        llm_model=llm_model,
        template_ids=template_ids,
    )


def make_stage_record(
    stage: Stage = Stage.INGEST,
    *,
    status: StageStatus = "ok",
    started_at: datetime | None = FIXED_TIME,
    finished_at: datetime | None = FIXED_TIME,
    payload_bytes: int | None = 1024,
    summary: str = "25 trends",
) -> StageRecord:
    return StageRecord(
        stage=stage,
        status=status,
        started_at=started_at,
        finished_at=finished_at,
        payload_bytes=payload_bytes,
        summary=summary,
    )


def make_render_record(
    rid: str = "rnd1",
    *,
    run_id: str = "20260901T120000Z",
    topic_id: str = "airport-cat",
    template_id: str = "drake",
    caption_slots: dict[str, str] | None = None,
    origin: Origin | None = None,
    status: str = "ready",
    error: str | None = None,
    created_at: datetime = FIXED_TIME,
) -> RenderRecord:
    return RenderRecord(
        id=rid,
        run_id=run_id,
        topic_id=topic_id,
        template_id=template_id,
        caption_slots=(
            caption_slots
            if caption_slots is not None
            else {"rejected": "a", "preferred": "b"}
        ),
        origin=origin if origin is not None else AutoOrigin(rationale="it fits"),
        status=status,
        error=error,
        created_at=created_at,
    )


def make_dossier(
    *,
    event_sentiment: Sentiment = Sentiment.FUNNY,
    conversation_register: Register = Register.RIFFING,
    meme_potential: float | None = 0.86,
    phrases: list[Phrase] | None = None,
) -> Dossier:
    return Dossier(
        what_happened="A cat got into an airport.",
        key_entities=["Heathrow"],
        conversation_summary="Everyone is delighted.",
        conversation_register=conversation_register,
        event_sentiment=event_sentiment,
        meme_potential=meme_potential,
        recurring_phrases=(
            phrases
            if phrases is not None
            else [Phrase(text="airport cat", occurrences=48, distinct_authors=31)]
        ),
    )


def make_topic(
    tid: str = "airport-cat",
    *,
    label: str | None = None,
    trend_status: TrendStatus = "trending",
    trend_score: float = 0.91,
    item_ids: list[str] | None = None,
    dossier: Dossier | None = None,
    score_components: dict[str, float] | None = None,
) -> Topic:
    return Topic(
        id=tid,
        label=label if label is not None else tid.replace("-", " ").title(),
        summary="A cat got into an airport.",
        item_ids=item_ids if item_ids is not None else ["at://post/1"],
        trend_status=trend_status,
        trend_score=trend_score,
        score_components=(
            score_components
            if score_components is not None
            else {"bluesky": 0.91, "corroboration": 1.0}
        ),
        dossier=dossier if dossier is not None else make_dossier(),
    )


def make_scored_topic(
    tid: str = "airport-cat", *, rank: int = 1, **kwargs
) -> ScoredTopic:
    """A ScoredTopic with the same defaults as `make_topic`, plus a rank."""
    return ScoredTopic(**make_topic(tid, **kwargs).model_dump(), final_rank=rank)
```

- [ ] **Step 2: Verify it imports and builds valid models**

Run: `uv run python -c "import sys; sys.path.insert(0, '.'); from tests.run_factory import make_topic, make_render_record, make_run_config; print(make_topic().trend_status, make_render_record().origin.provenance, make_run_config().top_count)"`

Expected: `trending auto 5`

- [ ] **Step 3: Run the full gate**

Run: `uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest`

Expected: all four pass. If `ty` objects that `make_scored_topic`'s `**kwargs` is untyped, give it `**kwargs: object` and cast at the call, or spell the parameters out — do not suppress it.

- [ ] **Step 4: Commit**

```bash
git add tests/run_factory.py
git commit -m "Add run fixture builders

Mirrors template_factory: every fixture built through the real models, so a
change to RunConfig or RenderRecord surfaces as one type error rather than
as ValidationErrors from inside unrelated tests.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: Schema version 3

All the tables at once, in their own module. `runs` and `topics` are absorbed rather than kept alongside the new ones.

**Files:**
- Create: `zeitgeist/schema.py`
- Modify: `zeitgeist/store.py` (imports, `SCHEMA_VERSION`, `init_schema`, `__init__`)
- Test: `tests/test_store.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `zeitgeist.schema.SCHEMA` (str), `zeitgeist.schema.SCHEMA_VERSION` (int, 3). `Store` continues to expose `SCHEMA_VERSION` by re-export so `tests/test_store.py` and any later import keep working.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_store.py`:

```python
def test_schema_creates_every_table_the_ui_reads(tmp_path):
    store = Store(tmp_path / "z.db")
    store.init_schema()

    names = {
        row[0]
        for row in store._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }

    assert {
        "checkpoints",
        "run_records",
        "run_stages",
        "run_topics",
        "renders",
        "log_lines",
        "settings",
        "topic_scores",
    } <= names


def test_the_absorbed_tables_are_gone(tmp_path):
    """runs is a strict subset of run_records and topics of run_topics.
    Keeping either pair would mean two tables to write and keep agreeing."""
    store = Store(tmp_path / "z.db")
    store.init_schema()

    names = {
        row[0]
        for row in store._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }

    assert "runs" not in names
    assert "topics" not in names


def test_the_connection_is_in_wal_mode(tmp_path):
    """The worker writes while the API reads. Without WAL those reads block
    behind the writes, which surfaces as the in-flight poll hitching every
    time a stage checkpoints."""
    store = Store(tmp_path / "z.db")
    store.init_schema()

    [(mode,)] = store._conn.execute("PRAGMA journal_mode").fetchall()

    assert mode.lower() == "wal"


def test_a_database_from_an_older_schema_is_refused(tmp_path):
    path = tmp_path / "z.db"
    store = Store(path)
    store.init_schema()
    store._conn.execute("PRAGMA user_version = 2")
    store._conn.commit()
    store.close()

    with pytest.raises(StoreSchemaError, match="version 2"):
        Store(path).init_schema()
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_store.py -k "schema or absorbed or wal or older" -v`

Expected: FAIL — the new tables do not exist, `runs` and `topics` do, and the journal mode is `delete`.

- [ ] **Step 3: Write the schema module**

Create `zeitgeist/schema.py`:

```python
"""The database's shape.

Lives apart from `store.py` so ninety lines of DDL do not sit in the middle
of the accessors that use it.

There is no migration path and none is written: the project is in active
development and data loss is acceptable, so `StoreSchemaError` refusing to
open a mismatched database *is* the strategy. Bumping SCHEMA_VERSION means
deleting the file.
"""

SCHEMA_VERSION = 3

SCHEMA = """
-- The four stage artifacts, held whole rather than normalised. Nothing
-- queries inside a payload except topic detail's replies, and a blob
-- round-trips through model_validate_json exactly, which is what resuming a
-- run depends on.
CREATE TABLE IF NOT EXISTS checkpoints (
    run_id      TEXT NOT NULL,
    stage       TEXT NOT NULL,
    payload     TEXT NOT NULL,
    written_at  TEXT NOT NULL,
    PRIMARY KEY (run_id, stage)
);

CREATE TABLE IF NOT EXISTS run_records (
    run_id        TEXT PRIMARY KEY,
    status        TEXT NOT NULL,
    started_at    TEXT NOT NULL,
    finished_at   TEXT,
    config        TEXT NOT NULL,
    error         TEXT,
    item_count    INTEGER,
    trends_found  INTEGER,
    topics_kept   INTEGER,
    phrases_found INTEGER
);

CREATE TABLE IF NOT EXISTS run_stages (
    run_id        TEXT NOT NULL,
    stage         TEXT NOT NULL,
    status        TEXT NOT NULL,
    started_at    TEXT,
    finished_at   TEXT,
    payload_bytes INTEGER,
    summary       TEXT NOT NULL,
    PRIMARY KEY (run_id, stage)
);

-- The analyse and evaluate payloads flattened into columns you can filter,
-- sort and join on. Written in the same transaction as the checkpoint it
-- flattens, so the two cannot disagree.
--
-- No render_count column: meme counts are COUNT(*) over renders at query
-- time. Denormalising it would mean keeping it correct on every render
-- insert, failure and delete, including from the on-demand executor, to save
-- a join over a table holding single digits per run.
CREATE TABLE IF NOT EXISTS run_topics (
    run_id                TEXT NOT NULL,
    topic_id              TEXT NOT NULL,
    label                 TEXT NOT NULL,
    label_slug            TEXT NOT NULL,
    trend_status          TEXT NOT NULL,
    event_sentiment       TEXT,
    conversation_register TEXT,
    meme_potential        REAL,
    trend_score           REAL NOT NULL,
    final_score           REAL NOT NULL,
    final_rank            INTEGER NOT NULL,
    post_count            INTEGER NOT NULL,
    top_phrase            TEXT,
    top_phrase_authors    INTEGER,
    PRIMARY KEY (run_id, topic_id)
);

CREATE TABLE IF NOT EXISTS renders (
    id            TEXT PRIMARY KEY,
    run_id        TEXT NOT NULL,
    topic_id      TEXT NOT NULL,
    template_id   TEXT NOT NULL,
    caption_slots TEXT NOT NULL,
    origin        TEXT NOT NULL,
    status        TEXT NOT NULL,
    error         TEXT,
    created_at    TEXT NOT NULL
);

-- Created here so phase 3 needs no second version bump. Nothing writes to it
-- in phase 1 and no accessor for it exists yet.
CREATE TABLE IF NOT EXISTS log_lines (
    run_id    TEXT NOT NULL,
    seq       INTEGER NOT NULL,
    logged_at TEXT NOT NULL,
    level     TEXT NOT NULL,
    logger    TEXT NOT NULL,
    message   TEXT NOT NULL,
    PRIMARY KEY (run_id, seq)
);

-- One row per tuning field the settings screen has overridden. Absent means
-- fall through to .env.
CREATE TABLE IF NOT EXISTS settings (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Survives from schema 2 unchanged. Per-platform sub-scores have no home in
-- run_topics, and previous_sub_scores is the one query that needs them.
CREATE TABLE IF NOT EXISTS topic_scores (
    run_id    TEXT NOT NULL,
    label     TEXT NOT NULL,
    platform  TEXT NOT NULL,
    sub_score REAL NOT NULL,
    PRIMARY KEY (run_id, label, platform)
);

CREATE INDEX IF NOT EXISTS idx_run_topics_slug ON run_topics (label_slug);
CREATE INDEX IF NOT EXISTS idx_run_topics_status ON run_topics (trend_status);
CREATE INDEX IF NOT EXISTS idx_renders_run_topic ON renders (run_id, topic_id);
CREATE INDEX IF NOT EXISTS idx_topic_scores_label ON topic_scores (label);
CREATE INDEX IF NOT EXISTS idx_run_records_started ON run_records (started_at);
"""
```

- [ ] **Step 4: Rewire `store.py`**

In `zeitgeist/store.py`: delete the local `SCHEMA_VERSION` and `SCHEMA` definitions and import them instead. Change the sentinel table `init_schema` probes for, and enable WAL in `__init__`:

```python
from zeitgeist.schema import SCHEMA, SCHEMA_VERSION

__all__ = ["SCHEMA_VERSION", "Store", "StoreSchemaError"]
```

```python
    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._path)
        # The worker thread writes while the API reads. Without WAL a reader
        # blocks behind every checkpoint write, which the UI feels as the
        # in-flight poll hitching.
        self._conn.execute("PRAGMA journal_mode = WAL")
```

In `init_schema`, change the probe from `name='runs'` to `name='run_records'`. The rest of the method is unchanged.

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_store.py -k "schema or absorbed or wal or older" -v`

Expected: PASS. Other tests in `test_store.py` now fail — `start_run`, `finish_run`, `record_topics` and `previous_sub_scores` still reference `runs` and `topics`. Task 5 fixes them; leave them failing for now and do **not** commit yet.

- [ ] **Step 6: Commit is deferred**

This task leaves the suite red on purpose — the schema and its accessors are one reviewable change split across two tasks for readability. Commit at the end of Task 5.

---

### Task 5: Run records, replacing `runs`

`start_run` gains the frozen config, `finish_run` records counts, failure gets recorded at all, and `previous_sub_scores` joins `run_records`.

**Files:**
- Modify: `zeitgeist/store.py`
- Test: `tests/test_store.py`

**Interfaces:**
- Consumes: `RunConfig`, `RunError`, `RunStatus` from Task 2; the schema from Task 4.
- Produces on `Store`:
  - `start_run(run_id: str, config: RunConfig) -> None`
  - `finish_run(run_id: str, *, status: RunStatus, item_count: int, trends_found: int, topics_kept: int, phrases_found: int) -> None`
  - `fail_run(run_id: str, error: RunError) -> None`
  - `get_run(run_id: str) -> RunRecordRow | None` where `RunRecordRow` is a pydantic model defined in `zeitgeist/records.py` with fields `run_id: str`, `status: RunStatus`, `started_at: datetime`, `finished_at: datetime | None`, `config: RunConfig`, `error: RunError | None`, `item_count: int | None`, `trends_found: int | None`, `topics_kept: int | None`, `phrases_found: int | None`

- [ ] **Step 1: Add `RunRecordRow` to `zeitgeist/records.py`**

```python
class RunRecordRow(BaseModel):
    """A row of `run_records`, read back.

    The counts are `| None` because they are written when the run finishes;
    a run still in flight has not counted anything yet.
    """

    model_config = STRICT

    run_id: str
    status: RunStatus
    started_at: datetime
    finished_at: datetime | None
    config: RunConfig
    error: RunError | None
    item_count: int | None
    trends_found: int | None
    topics_kept: int | None
    phrases_found: int | None
```

- [ ] **Step 2: Write the failing tests**

Replace the body of `tests/test_store.py` that uses the old signatures. Add:

```python
def test_a_started_run_records_the_config_it_froze(tmp_path):
    """Run detail's config line and Re-run config both need what the run
    used, which a since-edited .env cannot supply."""
    store = _store(tmp_path)
    config = make_run_config(top_count=9, llm_model="qwen3.5")

    store.start_run("r1", config)

    record = store.get_run("r1")
    assert record is not None
    assert record.status == "running"
    assert record.config.top_count == 9
    assert record.config.llm_model == "qwen3.5"
    assert record.finished_at is None


def test_finishing_a_run_records_the_counts_the_runs_list_shows(tmp_path):
    store = _store(tmp_path)
    store.start_run("r1", make_run_config())

    store.finish_run(
        "r1",
        status="ok",
        item_count=214,
        trends_found=25,
        topics_kept=5,
        phrases_found=31,
    )

    record = store.get_run("r1")
    assert record is not None
    assert record.status == "ok"
    # All four, not a sample: they are four ints bound positionally in one
    # UPDATE, which is exactly the shape a swap hides in.
    assert (
        record.item_count,
        record.trends_found,
        record.topics_kept,
        record.phrases_found,
    ) == (214, 25, 5, 31)
    assert record.finished_at is not None


def test_a_failed_run_records_the_error_and_the_stage(tmp_path):
    """Today a failure leaves a NULL status and the reason is only printed.
    The Runs screen renders the class, the stage and the message."""
    store = _store(tmp_path)
    store.start_run("r1", make_run_config())

    store.fail_run(
        "r1",
        RunError(kind="SourceError", message="no trends returned", stage=Stage.INGEST),
    )

    record = store.get_run("r1")
    assert record is not None
    assert record.status == "failed"
    assert record.error is not None
    assert record.error.kind == "SourceError"
    assert record.error.stage is Stage.INGEST


def test_get_run_returns_none_for_a_run_that_does_not_exist(tmp_path):
    assert _store(tmp_path).get_run("nope") is None
```

Update the existing `previous_sub_scores` tests to pass a config to `start_run` — for example `store.start_run("r1", make_run_config())`. Import `make_run_config` from `tests.run_factory` and `RunError`, `Stage` from `zeitgeist.records`.

- [ ] **Step 3: Run to verify they fail**

Run: `uv run pytest tests/test_store.py -v`

Expected: FAIL — `start_run() takes 2 positional arguments but 3 were given`, and no `get_run`/`fail_run`.

- [ ] **Step 4: Rewrite the run methods in `store.py`**

Replace `start_run`, `finish_run` and `run_summary` with:

```python
    def start_run(self, run_id: str, config: RunConfig) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO run_records "
            "(run_id, status, started_at, config) VALUES (?, ?, ?, ?)",
            (run_id, "running", _now(), config.model_dump_json()),
        )
        self._conn.commit()

    def finish_run(
        self,
        run_id: str,
        *,
        status: RunStatus,
        item_count: int,
        trends_found: int,
        topics_kept: int,
        phrases_found: int,
    ) -> None:
        self._conn.execute(
            "UPDATE run_records SET status = ?, finished_at = ?, item_count = ?, "
            "trends_found = ?, topics_kept = ?, phrases_found = ? WHERE run_id = ?",
            (
                status,
                _now(),
                item_count,
                trends_found,
                topics_kept,
                phrases_found,
                run_id,
            ),
        )
        self._conn.commit()

    def fail_run(self, run_id: str, error: RunError) -> None:
        """Record why a run failed.

        Separate from finish_run rather than a status argument to it, because
        a failure has no counts to record and an error to record instead.
        """
        self._conn.execute(
            "UPDATE run_records SET status = ?, finished_at = ?, error = ? "
            "WHERE run_id = ?",
            ("failed", _now(), error.model_dump_json(), run_id),
        )
        self._conn.commit()

    def get_run(self, run_id: str) -> RunRecordRow | None:
        row = self._conn.execute(
            "SELECT run_id, status, started_at, finished_at, config, error, "
            "item_count, trends_found, topics_kept, phrases_found "
            "FROM run_records WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if row is None:
            return None
        return RunRecordRow(
            run_id=row[0],
            status=row[1],
            started_at=datetime.fromisoformat(row[2]),
            finished_at=datetime.fromisoformat(row[3]) if row[3] else None,
            config=RunConfig.model_validate_json(row[4]),
            error=RunError.model_validate_json(row[5]) if row[5] else None,
            item_count=row[6],
            trends_found=row[7],
            topics_kept=row[8],
            phrases_found=row[9],
        )
```

Add the imports at the top of `store.py`:

```python
from zeitgeist.records import RunConfig, RunError, RunRecordRow, RunStatus
```

- [ ] **Step 5: Rejoin `previous_sub_scores` to `run_records`**

In `previous_sub_scores`, the two `JOIN runs r ON r.run_id = s.run_id` clauses become `JOIN run_records r ON r.run_id = s.run_id`, and `run_records r2` likewise. `r.started_at` is unchanged — the column has the same name.

- [ ] **Step 6: Point `record_topics` at `topic_scores` only**

`record_topics` currently writes both `topics` and `topic_scores`. Delete the first `executemany` (the one inserting into `topics`); `run_topics` replaces it and is written by Task 8. Keep the second, and keep the docstring's explanation of why the key is `slugify(label)`.

- [ ] **Step 7: Run the tests**

Run: `uv run pytest tests/test_store.py -v`

Expected: PASS.

- [ ] **Step 8: Run the full gate**

Run: `uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest`

Expected: `pytest` still fails in `tests/test_pipeline.py`, which calls `store.finish_run` with the old signature. That is Task 14's job. Everything else passes.

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "Schema version 3, and run records replacing runs

Every table the UI reads, created in one version bump so phase 3 needs no
second one - log_lines included, though nothing writes to it yet and no
accessor for it exists.

runs and topics are absorbed rather than kept alongside: runs is a strict
subset of run_records and topics of run_topics, and keeping either pair
would mean two tables to write and two to keep agreeing. topic_scores
survives unchanged, rejoined to run_records.

start_run now freezes the config the run used, since a since-edited .env
cannot supply it afterwards. Failure is recorded at all for the first time -
previously a failed run left a NULL status and the reason was only printed.

Opens the connection in WAL mode: the worker writes while the API reads, and
without it those reads block behind every checkpoint write.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 6: Checkpoint read and write

The heart of the phase. `pipeline._write`/`_read` become store calls.

**Files:**
- Modify: `zeitgeist/store.py`
- Test: `tests/test_store.py`

**Interfaces:**
- Consumes: the schema from Task 4.
- Produces on `Store`:
  - `write_checkpoint(run_id: str, stage: Stage, models: Sequence[BaseModel]) -> int` — returns the payload's byte length, which `StageRecord.payload_bytes` needs
  - `read_checkpoint[T: BaseModel](run_id: str, stage: Stage, schema: type[T]) -> list[T]`
  - `MissingCheckpoint(Exception)` — raised by `read_checkpoint` when there is no row
- Note the PEP 695 generic syntax on `read_checkpoint`. Do not use `typing.TypeVar`.

- [ ] **Step 1: Write the failing tests**

```python
def test_a_checkpoint_round_trips_through_its_model(tmp_path):
    """This is what resuming a run depends on. A payload that does not round
    trip breaks resume silently rather than loudly."""
    store = _store(tmp_path)
    topics = [make_topic("airport-cat"), make_topic("stadium-rat")]

    store.write_checkpoint("r1", Stage.ANALYSE, topics)
    restored = store.read_checkpoint("r1", Stage.ANALYSE, Topic)

    assert restored == topics


def test_a_checkpoint_round_trips_a_discriminated_union(tmp_path):
    """Metrics is discriminated on platform. A payload that deserialises to
    the wrong union member would score the topic with the wrong scorer."""
    store = _store(tmp_path)
    evidence = [_trend_evidence()]

    store.write_checkpoint("r1", Stage.INGEST, evidence)
    [restored] = store.read_checkpoint("r1", Stage.INGEST, TrendEvidence)

    assert isinstance(restored.posts[0].item.metrics, BlueskyMetrics)


def test_writing_a_checkpoint_twice_replaces_it(tmp_path):
    """Resuming rewrites the stages it re-runs."""
    store = _store(tmp_path)
    store.write_checkpoint("r1", Stage.ANALYSE, [make_topic("first")])

    store.write_checkpoint("r1", Stage.ANALYSE, [make_topic("second")])

    [topic] = store.read_checkpoint("r1", Stage.ANALYSE, Topic)
    assert topic.id == "second"


def test_write_checkpoint_reports_the_payload_size(tmp_path):
    """The stage card shows this number, so it has to be the size of what
    was actually written - not merely some positive number. Returning
    len(models) would satisfy `> 0` and be wrong by three orders."""
    store = _store(tmp_path)

    size = store.write_checkpoint("r1", Stage.ANALYSE, [make_topic()])

    [(stored_bytes,)] = store._conn.execute(
        "SELECT LENGTH(CAST(payload AS BLOB)) FROM checkpoints "
        "WHERE run_id = ? AND stage = ?",
        ("r1", Stage.ANALYSE.value),
    ).fetchall()
    assert size == stored_bytes


def test_reading_a_checkpoint_that_was_never_written_raises(tmp_path):
    """Resuming from a stage whose predecessor never ran must say so, not
    return an empty list that looks like a run with no topics."""
    store = _store(tmp_path)

    with pytest.raises(MissingCheckpoint, match="analyse"):
        store.read_checkpoint("r1", Stage.ANALYSE, Topic)


def test_an_empty_checkpoint_is_not_a_missing_one(tmp_path):
    """A generate stage that briefed nothing wrote an empty list. That is a
    result, and resuming past it must not raise."""
    store = _store(tmp_path)
    store.write_checkpoint("r1", Stage.GENERATE, [])

    assert store.read_checkpoint("r1", Stage.GENERATE, MediaBrief) == []
```

Add a `_trend_evidence()` helper to `tests/test_store.py` building a `TrendEvidence` with one `PostEvidence` carrying `BlueskyMetrics`, or import one from `tests/test_sources_bluesky.py` if a suitable builder already exists there. Import `Topic`, `TrendEvidence`, `BlueskyMetrics`, `MediaBrief` from `zeitgeist.models`, `Stage` from `zeitgeist.records`, `MissingCheckpoint` from `zeitgeist.store`, and `make_topic` from `tests.run_factory`.

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_store.py -k checkpoint -v`

Expected: FAIL with `ImportError: cannot import name 'MissingCheckpoint'`.

- [ ] **Step 3: Implement**

Add to `zeitgeist/store.py`:

```python
class MissingCheckpoint(Exception):
    """A stage was resumed from, but its predecessor never wrote anything.

    Distinct from an empty checkpoint, which is a result: a generate stage
    that briefed nothing wrote `[]`, and resuming past it is legitimate.
    """
```

and on `Store`:

```python
    def write_checkpoint(
        self, run_id: str, stage: Stage, models: Sequence[BaseModel]
    ) -> int:
        """Persist a stage's output. Returns the payload's size in bytes,
        which is what the stage card displays.

        Sequence rather than list: list is invariant, so a list[Topic] is not
        a list[BaseModel] and every call site would be rejected.
        """
        payload = json.dumps([model.model_dump(mode="json") for model in models])
        self._conn.execute(
            "INSERT OR REPLACE INTO checkpoints "
            "(run_id, stage, payload, written_at) VALUES (?, ?, ?, ?)",
            (run_id, stage.value, payload, _now()),
        )
        self._conn.commit()
        return len(payload.encode("utf-8"))

    def read_checkpoint[T: BaseModel](
        self, run_id: str, stage: Stage, schema: type[T]
    ) -> list[T]:
        row = self._conn.execute(
            "SELECT payload FROM checkpoints WHERE run_id = ? AND stage = ?",
            (run_id, stage.value),
        ).fetchone()
        if row is None:
            raise MissingCheckpoint(
                f"Run {run_id!r} has no {stage.value} checkpoint"
            )
        return [schema.model_validate(entry) for entry in json.loads(row[0])]
```

Add `import json`, `from collections.abc import Sequence`, `from pydantic import BaseModel` and `from zeitgeist.records import Stage` to the imports.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_store.py -k checkpoint -v`

Expected: PASS, 6 tests.

- [ ] **Step 5: Run the full gate**

Run: `uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest`

Expected: `test_pipeline.py` still fails (Task 14). Everything else passes.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "Store the stage checkpoints in SQLite

write_checkpoint and read_checkpoint, holding each stage's output as the
same JSON _write produces today. Whole documents rather than normalised
tables: evidence is TrendEvidence to PostEvidence to Item with a
discriminated Metrics union, nothing queries inside it, and a payload round
trips through model_validate_json exactly - which is what resuming depends
on, so it has a test of its own.

MissingCheckpoint is distinct from an empty checkpoint. A generate stage
that briefed nothing wrote an empty list, and resuming past that is
legitimate; resuming from a stage whose predecessor never ran is not.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 7: Stage records

**Files:**
- Modify: `zeitgeist/store.py`
- Test: `tests/test_store.py`

**Interfaces:**
- Consumes: `StageRecord` from Task 2.
- Produces on `Store`: `record_stage(run_id: str, record: StageRecord) -> None`, `stages_for_run(run_id: str) -> list[StageRecord]` returning pipeline order, not insertion order.

- [ ] **Step 1: Write the failing tests**

```python
def test_stages_come_back_in_pipeline_order(tmp_path):
    """The four stage cards are drawn left to right in the order they run,
    not the order rows happened to be written."""
    store = _store(tmp_path)
    store.record_stage("r1", make_stage_record(Stage.GENERATE))
    store.record_stage("r1", make_stage_record(Stage.INGEST))
    store.record_stage("r1", make_stage_record(Stage.EVALUATE))
    store.record_stage("r1", make_stage_record(Stage.ANALYSE))

    stages = store.stages_for_run("r1")

    assert [s.stage for s in stages] == [
        Stage.INGEST,
        Stage.ANALYSE,
        Stage.EVALUATE,
        Stage.GENERATE,
    ]


def test_recording_a_stage_twice_replaces_it(tmp_path):
    """A stage moves queued to running to ok, rewriting its row each time."""
    store = _store(tmp_path)
    store.record_stage(
        "r1", make_stage_record(Stage.INGEST, status="running", finished_at=None)
    )

    store.record_stage("r1", make_stage_record(Stage.INGEST, status="ok"))

    [stage] = store.stages_for_run("r1")
    assert stage.status == "ok"
    assert stage.finished_at is not None


def test_a_queued_stage_round_trips_its_absent_timings(tmp_path):
    store = _store(tmp_path)
    store.record_stage(
        "r1",
        make_stage_record(
            Stage.GENERATE,
            status="queued",
            started_at=None,
            finished_at=None,
            payload_bytes=None,
            summary="queued",
        ),
    )

    [stage] = store.stages_for_run("r1")

    assert (stage.started_at, stage.finished_at, stage.payload_bytes) == (
        None,
        None,
        None,
    )
```

Import `make_stage_record` from `tests.run_factory`.

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_store.py -k stage -v`

Expected: FAIL with `AttributeError: 'Store' object has no attribute 'record_stage'`.

- [ ] **Step 3: Implement**

```python
    def record_stage(self, run_id: str, record: StageRecord) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO run_stages (run_id, stage, status, "
            "started_at, finished_at, payload_bytes, summary) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                run_id,
                record.stage.value,
                record.status,
                record.started_at.isoformat() if record.started_at else None,
                record.finished_at.isoformat() if record.finished_at else None,
                record.payload_bytes,
                record.summary,
            ),
        )
        self._conn.commit()

    def stages_for_run(self, run_id: str) -> list[StageRecord]:
        """In pipeline order. The four stage cards are drawn in the order the
        stages run, which is not the order their rows were written.
        """
        rows = self._conn.execute(
            "SELECT stage, status, started_at, finished_at, payload_bytes, summary "
            "FROM run_stages WHERE run_id = ?",
            (run_id,),
        ).fetchall()
        records = [
            StageRecord(
                stage=Stage(row[0]),
                status=row[1],
                started_at=datetime.fromisoformat(row[2]) if row[2] else None,
                finished_at=datetime.fromisoformat(row[3]) if row[3] else None,
                payload_bytes=row[4],
                summary=row[5],
            )
            for row in rows
        ]
        return sorted(records, key=lambda record: ORDER.index(record.stage))
```

Extend the records import to `from zeitgeist.records import ORDER, RunConfig, RunError, RunRecordRow, RunStatus, Stage, StageRecord`.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_store.py -k stage -v`

Expected: PASS, 3 tests.

- [ ] **Step 5: Run the full gate**

Run: `uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest`

Expected: `test_pipeline.py` still fails. Everything else passes.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "Record each stage's status and timings

The four stage cards want a name, a duration, a summary and a payload size,
and nothing recorded stage boundaries at all, so durations did not exist to
be read. stages_for_run returns pipeline order rather than insertion order,
since the cards are drawn in the order the stages run.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 8: Flattening topics into `run_topics`

A pure function, and the accessor that writes what it returns.

**Files:**
- Create: `zeitgeist/projection.py`
- Create: `tests/test_projection.py`
- Modify: `zeitgeist/store.py`
- Test: `tests/test_store.py`

**Interfaces:**
- Consumes: `Topic`, `ScoredTopic` from `zeitgeist.models`; `rank_score` from `zeitgeist.analysis.sentiment`.
- Produces:
  - `zeitgeist.projection.TopicRow` — pydantic model with `run_id`, `topic_id`, `label`, `label_slug`, `trend_status`, `event_sentiment: str | None`, `conversation_register: str | None`, `meme_potential: float | None`, `trend_score: float`, `final_score: float`, `final_rank: int`, `post_count: int`, `top_phrase: str | None`, `top_phrase_authors: int | None`
  - `zeitgeist.projection.flatten(run_id: str, topics: list[Topic], meme_potential_weight: float) -> list[TopicRow]`
  - `Store.write_run_topics(rows: Sequence[TopicRow]) -> None`

**Why the whole list, not just the kept ones:** the ranking screen draws below-the-cut rows with ranks and scores before dimming them. The evaluate checkpoint holds only the top `top_count`, so `flatten` ranks *every* topic in the analyse payload using `sentiment.rank_score` — the same function `select()` ranks with, so the first `top_count` rows agree with the evaluate checkpoint by construction. Do not write a second implementation of the blend.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_projection.py`:

```python
from zeitgeist.models import Register, Sentiment
from zeitgeist.projection import flatten

from tests.run_factory import make_dossier, make_topic


def test_every_topic_is_ranked_not_just_the_kept_ones():
    """The ranking screen draws below-the-cut rows with ranks and scores
    before dimming them, and the evaluate checkpoint holds only the top N."""
    topics = [
        make_topic("low", trend_score=0.1),
        make_topic("high", trend_score=0.9),
        make_topic("mid", trend_score=0.5),
    ]

    rows = flatten("r1", topics, meme_potential_weight=0.0)

    assert [row.topic_id for row in rows] == ["high", "mid", "low"]
    assert [row.final_rank for row in rows] == [1, 2, 3]


def test_ranking_uses_the_same_blend_the_pipeline_selects_with():
    """A second implementation of trend-versus-meme would drift silently, so
    the first top_count rows must agree with what select() chose."""
    dull_but_loud = make_topic(
        "loud", trend_score=1.0, dossier=make_dossier(meme_potential=0.0)
    )
    funny_but_quiet = make_topic(
        "funny", trend_score=0.0, dossier=make_dossier(meme_potential=1.0)
    )

    rows = flatten("r1", [dull_but_loud, funny_but_quiet], meme_potential_weight=0.9)

    assert rows[0].topic_id == "funny"


def test_a_topic_with_no_dossier_flattens_without_one():
    """dossier is None on the dormant path and on a stale checkpoint. The row
    still has to exist - the topic was ranked."""
    rows = flatten("r1", [make_topic("bare", dossier=None)], meme_potential_weight=0.3)

    [row] = rows
    assert row.event_sentiment is None
    assert row.meme_potential is None
    assert row.top_phrase is None


def test_the_top_phrase_is_the_one_with_the_most_distinct_authors():
    """Forty uses from three accounts is a dogpile; the ranking subline shows
    the phrase the most separate people reached for."""
    from zeitgeist.models import Phrase

    dossier = make_dossier(
        phrases=[
            Phrase(text="rare", occurrences=99, distinct_authors=2),
            Phrase(text="common", occurrences=10, distinct_authors=31),
        ]
    )

    [row] = flatten("r1", [make_topic(dossier=dossier)], meme_potential_weight=0.3)

    assert row.top_phrase == "common"
    assert row.top_phrase_authors == 31


def test_the_dossier_fields_land_in_their_matching_columns():
    """event_sentiment, conversation_register and meme_potential come from
    three different Dossier fields through the same
    `None if dossier is None else dossier.X` shape. Swapping two of those
    assignments would still read plausibly, so all three are pinned.

    Also covers the enum flattening: SQLite has no enum type and the API
    serialises these as strings.
    """
    dossier = make_dossier(
        event_sentiment=Sentiment.SCHADENFREUDE,
        conversation_register=Register.DUNKING,
        meme_potential=0.42,
    )

    [row] = flatten("r1", [make_topic(dossier=dossier)], meme_potential_weight=0.3)

    assert row.event_sentiment == "schadenfreude"
    assert row.conversation_register == "dunking"
    assert row.meme_potential == 0.42


def test_post_count_is_the_number_of_items_behind_the_topic():
    [row] = flatten(
        "r1",
        [make_topic(item_ids=["a", "b", "c"])],
        meme_potential_weight=0.3,
    )

    assert row.post_count == 3
```

Add to `tests/test_store.py`:

```python
def test_run_topics_round_trip_through_the_store(tmp_path):
    store = _store(tmp_path)
    rows = flatten("r1", [make_topic("airport-cat")], meme_potential_weight=0.3)

    store.write_run_topics(rows)

    stored = store.run_topics("r1")
    assert [row.topic_id for row in stored] == ["airport-cat"]
    assert stored[0].label_slug == "airport-cat"
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_projection.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'zeitgeist.projection'`.

- [ ] **Step 3: Write the module**

Create `zeitgeist/projection.py`:

```python
"""The analyse and evaluate payloads, flattened into columns.

`run_topics` holds nothing that is not already in those payloads — it is
them, in a shape you can filter, sort and join on. A view over
`json_each(payload)` would always agree with its source and never need
rewriting, but the cross-run queries would then parse every run's analyse
payload on every request: at a thousand runs, a hundred megabytes of JSON
per page load.

Pure. No store, no I/O. It is written in the same transaction as the
checkpoint it flattens, which is what keeps the two from disagreeing.
"""

from pydantic import BaseModel

from zeitgeist.analysis.sentiment import rank_score
from zeitgeist.analysis.slug import slugify
from zeitgeist.models import STRICT, Topic, TrendStatus


class TopicRow(BaseModel):
    """One row of `run_topics`."""

    model_config = STRICT

    run_id: str
    topic_id: str
    label: str
    label_slug: str
    trend_status: TrendStatus
    # None where the topic has no dossier — the dormant path, or a stale
    # checkpoint. The topic was still ranked, so the row still exists.
    event_sentiment: str | None
    conversation_register: str | None
    meme_potential: float | None
    trend_score: float
    final_score: float
    final_rank: int
    post_count: int
    top_phrase: str | None
    top_phrase_authors: int | None


def flatten(
    run_id: str, topics: list[Topic], meme_potential_weight: float
) -> list[TopicRow]:
    """Rank every topic and flatten it.

    Every topic, not just the kept ones: the ranking screen draws
    below-the-cut rows with their ranks and scores before dimming them, and
    the evaluate checkpoint holds only the top `top_count`.

    Ranks with `sentiment.rank_score`, which is the same function `select()`
    ranks with, so the first `top_count` rows agree with the evaluate
    checkpoint by construction. A second implementation of the blend here
    would drift from it silently.
    """
    ranked = sorted(
        topics,
        key=lambda topic: rank_score(topic, meme_potential_weight),
        reverse=True,
    )
    return [
        _row(run_id, topic, position, meme_potential_weight)
        for position, topic in enumerate(ranked, start=1)
    ]


def _row(
    run_id: str, topic: Topic, rank: int, meme_potential_weight: float
) -> TopicRow:
    dossier = topic.dossier
    # The phrase the most separate people reached for, not the most repeated:
    # forty uses from three accounts is a dogpile, not a zeitgeist.
    top = (
        max(dossier.recurring_phrases, key=lambda p: p.distinct_authors)
        if dossier is not None and dossier.recurring_phrases
        else None
    )
    return TopicRow(
        run_id=run_id,
        topic_id=topic.id,
        label=topic.label,
        # The cross-run key, normalised the same way topic_scores keys its
        # rows, so recurrence finds a match across runs.
        label_slug=slugify(topic.label),
        trend_status=topic.trend_status,
        event_sentiment=None if dossier is None else dossier.event_sentiment.value,
        conversation_register=(
            None if dossier is None else dossier.conversation_register.value
        ),
        meme_potential=None if dossier is None else dossier.meme_potential,
        trend_score=topic.trend_score,
        final_score=rank_score(topic, meme_potential_weight),
        final_rank=rank,
        post_count=len(topic.item_ids),
        top_phrase=None if top is None else top.text,
        top_phrase_authors=None if top is None else top.distinct_authors,
    )
```

- [ ] **Step 4: Add the store accessors**

```python
    def write_run_topics(self, rows: Sequence[TopicRow]) -> None:
        self._conn.executemany(
            "INSERT OR REPLACE INTO run_topics (run_id, topic_id, label, "
            "label_slug, trend_status, event_sentiment, conversation_register, "
            "meme_potential, trend_score, final_score, final_rank, post_count, "
            "top_phrase, top_phrase_authors) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    row.run_id,
                    row.topic_id,
                    row.label,
                    row.label_slug,
                    row.trend_status,
                    row.event_sentiment,
                    row.conversation_register,
                    row.meme_potential,
                    row.trend_score,
                    row.final_score,
                    row.final_rank,
                    row.post_count,
                    row.top_phrase,
                    row.top_phrase_authors,
                )
                for row in rows
            ],
        )
        self._conn.commit()

    def run_topics(self, run_id: str) -> list[TopicRow]:
        rows = self._conn.execute(
            "SELECT run_id, topic_id, label, label_slug, trend_status, "
            "event_sentiment, conversation_register, meme_potential, trend_score, "
            "final_score, final_rank, post_count, top_phrase, top_phrase_authors "
            "FROM run_topics WHERE run_id = ? ORDER BY final_rank",
            (run_id,),
        ).fetchall()
        return [
            TopicRow(
                run_id=row[0],
                topic_id=row[1],
                label=row[2],
                label_slug=row[3],
                trend_status=row[4],
                event_sentiment=row[5],
                conversation_register=row[6],
                meme_potential=row[7],
                trend_score=row[8],
                final_score=row[9],
                final_rank=row[10],
                post_count=row[11],
                top_phrase=row[12],
                top_phrase_authors=row[13],
            )
            for row in rows
        ]
```

Add `from zeitgeist.projection import TopicRow` to `store.py`.

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_projection.py tests/test_store.py -k "projection or run_topics or flatten" -v`

Expected: PASS.

- [ ] **Step 6: Run the full gate**

Run: `uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest`

Expected: `test_pipeline.py` still fails. Everything else passes.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "Flatten the analyse payload into run_topics

A pure function turning topics into the columns the topics index and
ranking lists filter and sort on, plus the accessor that writes them.

Ranks every topic rather than the kept ones, because the ranking screen
draws below-the-cut rows with their ranks and scores before dimming them
and the evaluate checkpoint holds only the top N. Ranks with
sentiment.rank_score, the same function select() ranks with, so the first
top_count rows agree with that checkpoint by construction - a second
implementation of the blend would drift from it silently.

The top phrase is the one with the most distinct authors rather than the
most occurrences: forty uses from three accounts is a dogpile.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 9: Render records

Insert and read only. Deletion is phase 4's.

**Files:**
- Modify: `zeitgeist/store.py`
- Test: `tests/test_store.py`

**Interfaces:**
- Consumes: `RenderRecord`, `AutoOrigin`, `ManualOrigin` from Task 2.
- Produces on `Store`: `add_render(record: RenderRecord) -> None`, `get_render(render_id: str) -> RenderRecord | None`, `renders_for_run(run_id: str) -> list[RenderRecord]`.

- [ ] **Step 1: Write the failing tests**

```python
def test_a_render_round_trips_with_its_origin_intact(tmp_path):
    store = _store(tmp_path)
    record = make_render_record("rnd1", origin=AutoOrigin(rationale="it fits"))

    store.add_render(record)

    restored = store.get_render("rnd1")
    assert restored == record
    assert isinstance(restored.origin, AutoOrigin)


def test_a_hand_written_render_comes_back_manual(tmp_path):
    """The union is what makes 'was this written by a person' a type check
    rather than a string comparison."""
    store = _store(tmp_path)
    store.add_render(make_render_record("rnd2", origin=ManualOrigin()))

    restored = store.get_render("rnd2")

    assert isinstance(restored.origin, ManualOrigin)


def test_a_failed_render_keeps_its_error(tmp_path):
    """The renderer fails per meme, so a partial failure is real. The tile
    shows the message rather than vanishing."""
    store = _store(tmp_path)
    store.add_render(
        make_render_record("rnd3", status="failed", error="caption does not fit")
    )

    restored = store.get_render("rnd3")

    assert restored.status == "failed"
    assert restored.error == "caption does not fit"


def test_renders_for_a_run_come_back_oldest_first(tmp_path):
    store = _store(tmp_path)
    store.add_render(
        make_render_record("second", created_at=datetime(2026, 9, 1, 13, tzinfo=UTC))
    )
    store.add_render(
        make_render_record("first", created_at=datetime(2026, 9, 1, 12, tzinfo=UTC))
    )

    ids = [r.id for r in store.renders_for_run("20260901T120000Z")]

    assert ids == ["first", "second"]


def test_get_render_returns_none_for_an_unknown_id(tmp_path):
    assert _store(tmp_path).get_render("nope") is None
```

Import `make_render_record` from `tests.run_factory` and `AutoOrigin`, `ManualOrigin` from `zeitgeist.records`.

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_store.py -k render -v`

Expected: FAIL with `AttributeError: 'Store' object has no attribute 'add_render'`.

- [ ] **Step 3: Implement**

```python
    def add_render(self, record: RenderRecord) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO renders (id, run_id, topic_id, template_id, "
            "caption_slots, origin, status, error, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                record.id,
                record.run_id,
                record.topic_id,
                record.template_id,
                json.dumps(record.caption_slots),
                record.origin.model_dump_json(),
                record.status,
                record.error,
                record.created_at.isoformat(),
            ),
        )
        self._conn.commit()

    def get_render(self, render_id: str) -> RenderRecord | None:
        row = self._conn.execute(
            "SELECT id, run_id, topic_id, template_id, caption_slots, origin, "
            "status, error, created_at FROM renders WHERE id = ?",
            (render_id,),
        ).fetchone()
        return None if row is None else _render(row)

    def renders_for_run(self, run_id: str) -> list[RenderRecord]:
        rows = self._conn.execute(
            "SELECT id, run_id, topic_id, template_id, caption_slots, origin, "
            "status, error, created_at FROM renders WHERE run_id = ? "
            "ORDER BY created_at, id",
            (run_id,),
        ).fetchall()
        return [_render(row) for row in rows]
```

and a module-level helper beside `_now`:

```python
def _render(row: tuple) -> RenderRecord:
    """Rebuild a RenderRecord from a row.

    `origin` goes back through the model rather than being reconstructed by
    hand, so the discriminator picks the concrete class and a manual render
    cannot come back carrying a rationale.
    """
    return RenderRecord(
        id=row[0],
        run_id=row[1],
        topic_id=row[2],
        template_id=row[3],
        caption_slots=json.loads(row[4]),
        origin=json.loads(row[5]),
        status=row[6],
        error=row[7],
        created_at=datetime.fromisoformat(row[8]),
    )
```

Extend the records import with `RenderRecord`.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_store.py -k render -v`

Expected: PASS, 5 tests.

- [ ] **Step 5: Run the full gate**

Run: `uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest`

Expected: `test_pipeline.py` still fails. Everything else passes.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "Persist a record per render

Insert and read only; deletion belongs to the phase that adds on-demand
generation. Origin goes back through the model rather than being rebuilt by
hand, so the discriminator picks the concrete class and a manual render
cannot come back carrying a rationale.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 10: The settings table and its source

**Files:**
- Create: `zeitgeist/settings_source.py`
- Create: `tests/test_settings_source.py`
- Modify: `zeitgeist/store.py`, `zeitgeist/config.py`, `tests/conftest.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: the schema from Task 4.
- Produces:
  - `Store.get_settings() -> dict[str, str]`, `Store.set_setting(key: str, value: str) -> None`, `Store.clear_setting(key: str) -> None`
  - `zeitgeist.settings_source.WRITABLE_KEYS: frozenset[str]` — exactly the seven from Global Constraints
  - `zeitgeist.settings_source.SettingsTableSource(PydanticBaseSettingsSource)`
  - `Settings.settings_customise_sources` classmethod placing the new source between env and dotenv

**Precedence, highest first:** constructor arguments, environment variables, the `settings` table, `.env`, field defaults. A shell `TREND_LIMIT=10` beats the UI because it is the more explicit act; the UI beats `.env` because it is the more recent one.

**The circularity trap:** the source cannot read `Settings.db_path`, because that is the object being constructed. It reads `DB_PATH` from the environment, falling back to `data/zeitgeist.db` — the same default `Settings` declares. Do not try to thread the resolved path in.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_settings_source.py`:

```python
import pytest

from zeitgeist.config import Settings
from zeitgeist.settings_source import WRITABLE_KEYS
from zeitgeist.store import Store


def _store_with(tmp_path, **values) -> Store:
    store = Store(tmp_path / "zeitgeist.db")
    store.init_schema()
    for key, value in values.items():
        store.set_setting(key, str(value))
    store.close()
    return store


def test_a_stored_setting_is_used_when_the_environment_is_silent(
    tmp_path, monkeypatch
):
    _store_with(tmp_path, bluesky_trend_limit=11)
    monkeypatch.setenv("DB_PATH", str(tmp_path / "zeitgeist.db"))

    settings = Settings(_env_file=None)

    assert settings.bluesky_trend_limit == 11


def test_an_environment_variable_beats_a_stored_setting(tmp_path, monkeypatch):
    """An explicit BLUESKY_TREND_LIMIT=10 in front of a command is the more
    deliberate act, so it wins over what the UI last saved."""
    _store_with(tmp_path, bluesky_trend_limit=11)
    monkeypatch.setenv("DB_PATH", str(tmp_path / "zeitgeist.db"))
    monkeypatch.setenv("BLUESKY_TREND_LIMIT", "10")

    settings = Settings(_env_file=None)

    assert settings.bluesky_trend_limit == 10


def test_clearing_a_setting_falls_back_to_the_default(tmp_path, monkeypatch):
    store = _store_with(tmp_path, bluesky_trend_limit=11)
    monkeypatch.setenv("DB_PATH", str(tmp_path / "zeitgeist.db"))

    store = Store(tmp_path / "zeitgeist.db")
    store.clear_setting("bluesky_trend_limit")
    store.close()

    assert Settings(_env_file=None).bluesky_trend_limit == 25


def test_a_stored_setting_beats_a_dotenv_value(tmp_path, monkeypatch):
    """The whole point of this source is *where* it sits. Every other test
    here passes _env_file=None, so dotenv never participates and the
    ordering bug the source exists to avoid - sitting after dotenv rather
    than before it - would pass all of them."""
    env_file = tmp_path / ".env"
    env_file.write_text("BLUESKY_TREND_LIMIT=7\n", encoding="utf-8")
    _store_with(tmp_path, bluesky_trend_limit=11)
    monkeypatch.setenv("DB_PATH", str(tmp_path / "zeitgeist.db"))

    settings = Settings(_env_file=env_file)

    assert settings.bluesky_trend_limit == 11


def test_a_dotenv_value_applies_once_the_override_is_cleared(tmp_path, monkeypatch):
    """The other half of the same ordering: Reset to .env has to reveal the
    file's value, not the field default."""
    env_file = tmp_path / ".env"
    env_file.write_text("BLUESKY_TREND_LIMIT=7\n", encoding="utf-8")
    _store_with(tmp_path, bluesky_trend_limit=11)
    monkeypatch.setenv("DB_PATH", str(tmp_path / "zeitgeist.db"))

    store = Store(tmp_path / "zeitgeist.db")
    store.clear_setting("bluesky_trend_limit")
    store.close()

    assert Settings(_env_file=env_file).bluesky_trend_limit == 7


def test_a_missing_database_is_not_an_error(tmp_path, monkeypatch):
    """Settings must load before anything has created the database - the
    harness builds Settings in order to find out where the database goes."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "absent.db"))

    assert Settings(_env_file=None).bluesky_trend_limit == 25


def test_only_the_tuning_fields_are_writable():
    """A UI that can rewrite where the database lives, or store an API key in
    a table, is a different and worse thing than a tuning screen."""
    assert "anthropic_api_key" not in WRITABLE_KEYS
    assert "db_path" not in WRITABLE_KEYS
    assert "output_dir" not in WRITABLE_KEYS
    assert WRITABLE_KEYS == {
        "bluesky_trend_limit",
        "bluesky_posts_per_trend",
        "bluesky_fetch_concurrency",
        "meme_potential_weight",
        "phrase_min_authors",
        "distil_char_budget",
        "distil_concurrency",
    }


def test_a_key_outside_the_writable_set_is_ignored_by_the_source(
    tmp_path, monkeypatch
):
    """Defence in depth: the endpoint rejects these, and the source refuses
    to honour one that reached the table another way."""
    _store_with(tmp_path, anthropic_api_key="leaked")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "zeitgeist.db"))

    assert Settings(_env_file=None).anthropic_api_key == ""
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_settings_source.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'zeitgeist.settings_source'`.

- [ ] **Step 3: Add the store accessors**

```python
    def get_settings(self) -> dict[str, str]:
        return {
            row[0]: row[1]
            for row in self._conn.execute("SELECT key, value FROM settings")
        }

    def set_setting(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO settings (key, value, updated_at) "
            "VALUES (?, ?, ?)",
            (key, value, _now()),
        )
        self._conn.commit()

    def clear_setting(self, key: str) -> None:
        """Delete the override so the .env value, or the field default, applies
        again. This is what the settings screen's "Reset to .env" does.
        """
        self._conn.execute("DELETE FROM settings WHERE key = ?", (key,))
        self._conn.commit()
```

- [ ] **Step 4: Write the source**

Create `zeitgeist/settings_source.py`:

```python
"""A pydantic-settings source backed by the `settings` table.

Precedence, highest first: constructor arguments, environment variables,
this table, `.env`, field defaults. A shell `BLUESKY_TREND_LIMIT=10` in
front of a command beats the UI because it is the more explicit act; the UI
beats `.env` because it is the more recent one.
"""

import sqlite3
from pathlib import Path
from typing import Any

from pydantic.fields import FieldInfo
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource

# Exactly the fields the settings screen exposes. Everything else is refused
# here as well as at the endpoint: a UI that can rewrite where the database
# lives, or store an API key in a table, is a different and worse thing than
# a tuning screen.
WRITABLE_KEYS = frozenset(
    {
        "bluesky_trend_limit",
        "bluesky_posts_per_trend",
        "bluesky_fetch_concurrency",
        "meme_potential_weight",
        "phrase_min_authors",
        "distil_char_budget",
        "distil_concurrency",
    }
)

DEFAULT_DB_PATH = Path("data") / "zeitgeist.db"


class SettingsTableSource(PydanticBaseSettingsSource):
    """Reads overrides the settings screen wrote.

    Deliberately does not read `Settings.db_path`: that is the object being
    constructed, so resolving the database's location from it is circular.
    The path comes from the environment, defaulting to the same value
    `Settings` declares.
    """

    def __init__(self, settings_cls: type[BaseSettings]) -> None:
        super().__init__(settings_cls)
        self._values = self._load()

    def _load(self) -> dict[str, str]:
        import os

        path = Path(os.environ.get("DB_PATH", DEFAULT_DB_PATH))
        if not path.is_file():
            # Settings has to load before anything has created the database —
            # the harness builds Settings in order to find out where it goes.
            return {}
        try:
            with sqlite3.connect(path) as conn:
                rows = conn.execute("SELECT key, value FROM settings").fetchall()
        except sqlite3.Error:
            # A database from another schema version, or mid-write. Settings
            # failing to load would be a worse outcome than ignoring overrides.
            return {}
        return {key: value for key, value in rows if key in WRITABLE_KEYS}

    def get_field_value(
        self, field: FieldInfo, field_name: str
    ) -> tuple[Any, str, bool]:
        return self._values.get(field_name), field_name, False

    def __call__(self) -> dict[str, Any]:
        return {
            name: value
            for name, value in self._values.items()
            if name in self.settings_cls.model_fields
        }
```

- [ ] **Step 5: Wire it into `Settings`**

Add to `zeitgeist/config.py`, inside `class Settings`:

```python
    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Slot the settings table between the environment and `.env`.

        Order is precedence, highest first.
        """
        return (
            init_settings,
            env_settings,
            SettingsTableSource(settings_cls),
            dotenv_settings,
            file_secret_settings,
        )
```

with imports `from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict` and `from zeitgeist.settings_source import SettingsTableSource`.

**Import cycle check:** `settings_source.py` must not import `config.py`. It does not — it takes `settings_cls` as an argument.

- [ ] **Step 6: Add `DB_PATH` to the test environment strip**

`Settings` reads `DB_PATH`, and now so does the source, so a developer's ambient value would change results. Add `"DB_PATH"` to `_SETTINGS_ENV_VARS` in `tests/conftest.py`.

- [ ] **Step 7: Run the tests**

Run: `uv run pytest tests/test_settings_source.py tests/test_config.py -v`

Expected: PASS. If a `test_config.py` case now picks up a stray database, it means the strip is missing — fix `conftest.py`, not the test.

- [ ] **Step 8: Run the full gate**

Run: `uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest`

Expected: `test_pipeline.py` still fails. Everything else passes.

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "Layer a settings table over .env

A pydantic-settings source reading overrides the settings screen will write,
slotted between the environment and .env: a shell variable in front of a
command is the more explicit act and wins, the UI is the more recent one and
beats the file.

Two traps recorded in the code. The source cannot read Settings.db_path
without circularity, so it reads DB_PATH from the environment with the same
default Settings declares. And only the seven tuning fields are honoured -
refused here as well as at the endpoint, because a UI that can rewrite where
the database lives, or store an API key in a table, is a different and worse
thing than a tuning screen.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 11: Thumbnails

The Runs list draws renders at 34px and the PNGs are 300–800KB.

**Files:**
- Modify: `zeitgeist/media/render.py`
- Test: `tests/test_media_render.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `zeitgeist.media.render.THUMBNAIL_PX = 96`, `write_thumbnail(source: Path, out_path: Path) -> Path`.

- [ ] **Step 1: Write the failing tests**

```python
def test_a_thumbnail_fits_inside_the_box_and_keeps_its_aspect(tmp_path):
    source = tmp_path / "meme.png"
    Image.new("RGB", (1180, 590), "white").save(source)

    out = write_thumbnail(source, tmp_path / "meme.thumb.png")

    with Image.open(out) as image:
        # Derived from the constant rather than pinned at 96, so raising
        # THUMBNAIL_PX stays a decision rather than a test failure. What is
        # asserted is the 2:1 source keeping its shape.
        assert image.size == (THUMBNAIL_PX, THUMBNAIL_PX // 2)


def test_a_thumbnail_of_a_tall_image_is_bounded_by_its_height(tmp_path):
    source = tmp_path / "tall.png"
    Image.new("RGB", (300, 1200), "white").save(source)

    out = write_thumbnail(source, tmp_path / "tall.thumb.png")

    with Image.open(out) as image:
        assert image.size == (THUMBNAIL_PX // 4, THUMBNAIL_PX)


def test_a_thumbnail_is_never_larger_than_its_source(tmp_path):
    """A 34px tile has nothing to gain from an upscaled 40px meme."""
    source = tmp_path / "small.png"
    Image.new("RGB", (40, 20), "white").save(source)

    out = write_thumbnail(source, tmp_path / "small.thumb.png")

    with Image.open(out) as image:
        assert image.size == (40, 20)
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_media_render.py -k thumbnail -v`

Expected: FAIL with `ImportError: cannot import name 'write_thumbnail'`.

- [ ] **Step 3: Implement**

Add to `zeitgeist/media/render.py`:

```python
# The Runs list draws renders at 34px and topic detail at 42. 96 covers both
# on a 2x display without shipping 800KB per tile.
THUMBNAIL_PX = 96


def write_thumbnail(source: Path, out_path: Path) -> Path:
    """Write a bounded-box copy of `source` beside the render.

    `Image.thumbnail` preserves aspect ratio and never upscales, which is
    what we want on both counts: a stretched meme looks broken, and a 34px
    tile gains nothing from an enlarged small source.
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as image:
        copy = image.convert("RGB")
        copy.thumbnail((THUMBNAIL_PX, THUMBNAIL_PX))
        copy.save(out_path, format="PNG")
    return out_path
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_media_render.py -k thumbnail -v`

Expected: PASS, 3 tests.

- [ ] **Step 5: Run the full gate**

Run: `uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest`

Expected: `test_pipeline.py` still fails. Everything else passes.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "Write a 96px thumbnail beside each render

The Runs list draws renders at 34px and topic detail at 42, and the PNGs are
300-800KB. Image.thumbnail preserves aspect and never upscales, which is
right on both counts: a stretched meme looks broken and a 34px tile gains
nothing from an enlarged small source.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 12: The pipeline persists through the store

`_write` and `_read` go. `run_pipeline` returns a run id rather than a path.

**Files:**
- Modify: `zeitgeist/pipeline.py`
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: `Store.write_checkpoint`, `Store.read_checkpoint`, `MissingCheckpoint` from Task 6.
- Produces: `run_pipeline(...) -> str` returning the run id. The `settings`, `source`, `provider`, `store`, `run_id`, `start_at` and `template_ids` parameters are unchanged.

**Why the return type changes:** the run directory now holds only images, so returning it as though it were the run's output would be misleading. The run id is what every caller actually wants — the harness prints it, and phase 2's API looks records up by it.

- [ ] **Step 1: Rewrite the affected tests**

In `tests/test_pipeline.py`, every test that reads a JSON file from `run_dir` reads a checkpoint instead. Replace the file assertions:

```python
def test_ingest_writes_evidence_and_analyse_reads_it(tmp_path):
    """The expensive fetch lands before the analyse checkpoint, so brief
    tuning re-runs in seconds."""
    store = _store(tmp_path)
    run_id = run_pipeline(
        settings=_settings(tmp_path),
        source=_FakeTrendSource([_evidence()]),
        provider=FakeLLMProvider(responses=[_draft(), _choice()]),
        store=store,
        run_id="r1",
    )

    evidence = store.read_checkpoint(run_id, Stage.INGEST, TrendEvidence)

    assert evidence[0].trend.display_name == "A trend"
    assert evidence[0].posts[0].replies[0].text == "what a mess"


def test_the_analyse_checkpoint_carries_the_dossier(tmp_path):
    store = _store(tmp_path)
    run_id = run_pipeline(
        settings=_settings(tmp_path),
        source=_FakeTrendSource([_evidence()]),
        provider=FakeLLMProvider(responses=[_draft(), _choice()]),
        store=store,
        run_id="r1",
    )

    [topic] = store.read_checkpoint(run_id, Stage.ANALYSE, Topic)

    assert topic.dossier is not None
    assert topic.dossier.event_sentiment is Sentiment.SCHADENFREUDE


def test_the_evaluate_checkpoint_is_what_resume_reads_back(tmp_path):
    """A break in this round trip breaks resuming silently."""
    store = _store(tmp_path)
    run_id = run_pipeline(
        settings=_settings(tmp_path),
        source=_FakeTrendSource([_evidence()]),
        provider=FakeLLMProvider(responses=[_draft(), _choice()]),
        store=store,
        run_id="r1",
    )

    [topic] = store.read_checkpoint(run_id, Stage.EVALUATE, ScoredTopic)

    assert topic.dossier is not None
    assert topic.final_rank == 1


def test_resuming_without_a_checkpoint_raises(tmp_path):
    """Resuming from a stage whose predecessor never ran must say so, not
    behave like a run with no topics."""
    store = _store(tmp_path)

    with pytest.raises(MissingCheckpoint):
        run_pipeline(
            settings=_settings(tmp_path),
            source=_FakeTrendSource([]),
            provider=FakeLLMProvider(responses=[]),
            store=store,
            run_id="never-ran",
            start_at=Stage.GENERATE,
        )
```

Delete `test_an_unknown_template_id_leaves_no_run_directory_behind` — the run directory is now created lazily by the renderer, so the behaviour it asserted no longer has a mechanism. Replace it with:

```python
def test_an_unknown_template_id_writes_no_run_record(tmp_path):
    """Template ids are validated before the run row is inserted, so a typo
    leaves nothing behind rather than a run stuck in 'running'."""
    store = _store(tmp_path)

    with pytest.raises(TemplateError):
        run_pipeline(
            settings=_settings(tmp_path),
            source=_FakeTrendSource([_evidence()]),
            provider=FakeLLMProvider(responses=[]),
            store=store,
            run_id="r1",
            template_ids=["nope"],
        )

    assert store.get_run("r1") is None
```

Add to `tests/test_pipeline.py`'s imports, which currently have none of these:

```python
from zeitgeist.models import ScoredTopic, Topic
from zeitgeist.store import MissingCheckpoint, Store
```

`json` and `Path` become unused once the file assertions go; remove them or ruff's `F401` will fail the gate.

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_pipeline.py -v`

Expected: FAIL — `run_pipeline` still returns a `Path` and still writes files.

- [ ] **Step 3: Rewrite `run_pipeline`**

In `zeitgeist/pipeline.py`: delete `_write` and `_read` entirely, delete the `json` and `Sequence` imports if nothing else uses them, and replace each file operation with its store call. `run_dir` stays only for renders:

```python
def run_pipeline(
    settings: Settings,
    source: TrendSource,
    provider: LLMProvider,
    store: Store,
    run_id: str,
    start_at: Stage = Stage.INGEST,
    template_ids: list[str] | None = None,
) -> str:
    """Run the pipeline, returning the run id.

    Returns the id rather than the run directory because the directory now
    holds only rendered images; everything else lives in the store, and the
    id is what every caller looks records up by.
    """
    # Before the run row exists and before anything is fetched: a mistyped
    # template id then costs nothing and leaves nothing behind.
    templates = load_templates(settings.templates_dir)
    if template_ids is not None:
        templates = select_templates(templates, template_ids)

    resuming = ORDER.index(start_at)
    store.start_run(run_id, RunConfig.freeze(settings, template_ids))

    if resuming <= ORDER.index(Stage.INGEST):
        evidence = source.fetch_evidence(settings)
        log.info("Fetched %d trends", len(evidence))
        store.write_checkpoint(run_id, Stage.INGEST, evidence)
    else:
        evidence = store.read_checkpoint(run_id, Stage.INGEST, TrendEvidence)

    items: list[Item] = [post.item for entry in evidence for post in entry.posts]

    if resuming <= ORDER.index(Stage.ANALYSE):
        topics = distil_topics(evidence, provider, settings)
        topics = score_topics(
            topics, items, datetime.now(UTC), store.previous_sub_scores(run_id)
        )
        log.info("Distilled %d topics", len(topics))
        store.record_topics(run_id, topics)
        store.write_checkpoint(run_id, Stage.ANALYSE, topics)

    if resuming <= ORDER.index(Stage.EVALUATE):
        topics = store.read_checkpoint(run_id, Stage.ANALYSE, Topic)
        ranked = select(topics, settings.topic_count, settings.meme_potential_weight)
        log.info("Selected %d topics", len(ranked))
        store.write_checkpoint(run_id, Stage.EVALUATE, ranked)

    ranked = store.read_checkpoint(run_id, Stage.EVALUATE, ScoredTopic)
    briefs = generate_briefs(ranked, templates, provider)
    store.write_checkpoint(run_id, Stage.GENERATE, briefs)

    run_dir = Path(settings.output_dir) / run_id
    rendered = _render_all(briefs, templates, settings, run_dir, run_id, store)
    log.info("Rendered %d memes into %s", rendered, run_dir)

    store.finish_run(
        run_id,
        status="ok",
        item_count=len(items),
        trends_found=len(evidence),
        topics_kept=len(ranked),
        phrases_found=sum(
            len(t.dossier.recurring_phrases) if t.dossier else 0 for t in ranked
        ),
    )
    return run_id
```

`_render_all` gains `run_id` and `store` parameters; Task 13 fills in what it does with them. For now, change its signature and pass the arguments through without using them, so this task's tests pass and Task 13 is a contained change.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_pipeline.py -v`

Expected: PASS.

- [ ] **Step 5: Run the full gate**

Run: `uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest`

Expected: all four pass except `tests/test_cli.py`, which calls `run_pipeline` through the CLI and expects a path. Task 15 deletes it. If it blocks you, delete it now and note that in Task 15.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "Persist the pipeline's checkpoints through the store

_write and _read are gone; each stage's output is a row rather than a file.
run_pipeline returns the run id instead of the run directory, because the
directory now holds only rendered images and returning it would suggest
otherwise - the id is what every caller looks records up by.

start_run now freezes the config before anything is fetched, and finish_run
records the counts the Runs list shows.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 13: Renders on disk and in the store

Renders move to `output/<run-id>/renders/<render_id>.png`, gain thumbnails, and get a row each — including the ones that fail.

**Files:**
- Modify: `zeitgeist/pipeline.py`
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: `write_thumbnail`, `THUMBNAIL_PX` from Task 11; `Store.add_render` from Task 9; `RenderRecord`, `AutoOrigin` from Task 2.
- Produces: `_render_all(briefs, templates, settings, run_dir, run_id, store) -> int` writing one `RenderRecord` per brief.

**Why failed renders get a row:** `_render_all` catches `RenderError` per brief and logs a warning, so a run can finish `ok` having rendered three of five. The design shows that partial state, and it needs the failures recorded — a tile with an error message rather than a meme that silently never existed.

- [ ] **Step 1: Write the failing tests**

```python
def test_a_render_lands_in_the_renders_subdirectory_with_a_thumbnail(tmp_path):
    store = _store(tmp_path)
    run_id = run_pipeline(
        settings=_settings(tmp_path),
        source=_FakeTrendSource([_evidence()]),
        provider=FakeLLMProvider(responses=[_draft(), _choice()]),
        store=store,
        run_id="r1",
    )

    [record] = store.renders_for_run(run_id)
    renders = tmp_path / "output" / run_id / "renders"

    assert (renders / f"{record.id}.png").is_file()
    assert (renders / f"{record.id}.thumb.png").is_file()


def test_a_render_record_carries_the_brief_that_produced_it(tmp_path):
    """The full-size view shows the slot text and the rationale, so they have
    to be on the record rather than only in the generate checkpoint."""
    store = _store(tmp_path)
    run_id = run_pipeline(
        settings=_settings(tmp_path),
        source=_FakeTrendSource([_evidence()]),
        provider=FakeLLMProvider(responses=[_draft(), _choice()]),
        store=store,
        run_id="r1",
    )

    [record] = store.renders_for_run(run_id)

    assert record.template_id == TEMPLATE_A
    assert record.caption_slots == {"rejected": "Dogs", "preferred": "Cats"}
    assert isinstance(record.origin, AutoOrigin)
    assert record.origin.rationale == "Fits."


def test_a_render_that_fails_keeps_a_row_with_its_error(tmp_path):
    """The renderer fails per meme, so three of five is a real outcome. A
    failure that left no row would show as a meme that never existed."""
    store = _store(tmp_path)
    # 400 characters cannot fit a 180x80 box even at the 12px floor, which is
    # the one RenderError the renderer raises for a caption rather than a
    # missing file.
    unrenderable = _choice(caption_slots={"rejected": "x" * 400, "preferred": "y"})
    run_id = run_pipeline(
        settings=_settings(tmp_path),
        source=_FakeTrendSource([_evidence()]),
        provider=FakeLLMProvider(responses=[_draft(), unrenderable]),
        store=store,
        run_id="r1",
    )

    [record] = store.renders_for_run(run_id)

    assert record.status == "failed"
    assert record.error is not None
    assert not (tmp_path / "output" / run_id / "renders" / f"{record.id}.png").exists()
```

Add `from zeitgeist.records import AutoOrigin` to `tests/test_pipeline.py`.

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_pipeline.py -k render -v`

Expected: FAIL — renders are still written as `{position:02d}-{topic_id}.png` at the run directory's root and no rows exist.

- [ ] **Step 3: Implement**

```python
def _render_all(
    briefs: list[MediaBrief],
    templates: dict[str, TemplateManifest],
    settings: Settings,
    run_dir: Path,
    run_id: str,
    store: Store,
) -> int:
    """Render every brief, recording each outcome.

    A brief that cannot be drawn keeps a row carrying its error rather than
    vanishing: the renderer fails per meme, so three of five is a real
    outcome the UI has to be able to show.
    """
    renders_dir = run_dir / "renders"
    count = 0
    for brief in briefs:
        render_id = uuid4().hex
        out_path = renders_dir / f"{render_id}.png"
        error: str | None = None
        try:
            render_meme(
                brief,
                templates[brief.template_id],
                settings.templates_dir,
                out_path,
                settings.font_path,
            )
            write_thumbnail(out_path, renders_dir / f"{render_id}.thumb.png")
            count += 1
        except RenderError as exc:
            log.warning("Could not render %r: %s", brief.topic_id, exc)
            error = str(exc)

        store.add_render(
            RenderRecord(
                id=render_id,
                run_id=run_id,
                topic_id=brief.topic_id,
                template_id=brief.template_id,
                caption_slots=dict(brief.caption_slots),
                origin=AutoOrigin(rationale=brief.rationale),
                status="failed" if error else "ready",
                error=error,
                created_at=datetime.now(UTC),
            )
        )
    return count
```

Add `from uuid import uuid4`, `from zeitgeist.media.render import RenderError, render_meme, write_thumbnail` and `from zeitgeist.records import AutoOrigin, RenderRecord, RunConfig` to the imports.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_pipeline.py -v`

Expected: PASS. Any surviving test asserting `run_dir.glob("*.png")` must be updated to look in `renders/`.

- [ ] **Step 5: Run the full gate**

Run: `uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest`

Expected: all four pass, `tests/test_cli.py` aside.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "Give every render an id, a thumbnail and a row

Renders move to output/<run-id>/renders/<render_id>.png with a 96px
thumbnail beside each. The old {position}-{topic_id}.png naming collides the
moment two memes are generated for one topic, which on-demand generation
will do routinely.

A brief that cannot be drawn keeps a row carrying its error rather than
vanishing. The renderer fails per meme, so three of five is a real outcome,
and a failure that left no row would show as a meme that never existed.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 14: Stage records and `run_topics`, written as the run goes

The last of the pipeline's persistence. `run_topics` is written in the same transaction as the checkpoint it flattens.

**Files:**
- Modify: `zeitgeist/pipeline.py`, `zeitgeist/store.py`
- Test: `tests/test_pipeline.py`, `tests/test_store.py`

**Interfaces:**
- Consumes: `Store.record_stage`, `Store.write_run_topics`, `flatten`.
- Produces: `Store.write_analyse_checkpoint(run_id: str, topics: Sequence[Topic], meme_potential_weight: float) -> int` — writes the checkpoint and its flattened rows in one transaction.

**Why a combined method:** the spec's claim that the two cannot disagree only holds if they commit together. Two separate calls, each committing, leaves a window where a crash strands one without the other.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_store.py`:

```python
def test_the_analyse_checkpoint_and_its_rows_commit_together(tmp_path):
    store = _store(tmp_path)

    store.write_analyse_checkpoint(
        "r1", [make_topic("airport-cat")], meme_potential_weight=0.3
    )

    assert len(store.read_checkpoint("r1", Stage.ANALYSE, Topic)) == 1
    assert len(store.run_topics("r1")) == 1


def test_a_failure_partway_leaves_neither_the_payload_nor_the_rows(
    tmp_path, monkeypatch
):
    """The whole 'they cannot disagree' claim rests on one transaction. Two
    separate commits would leave a window where a crash strands one."""
    store = _store(tmp_path)

    def boom(*args, **kwargs):
        raise RuntimeError("interrupted")

    monkeypatch.setattr(store, "_insert_run_topics", boom)

    with pytest.raises(RuntimeError):
        store.write_analyse_checkpoint(
            "r1", [make_topic()], meme_potential_weight=0.3
        )

    assert store._conn.execute("SELECT COUNT(*) FROM checkpoints").fetchone()[0] == 0
    assert store._conn.execute("SELECT COUNT(*) FROM run_topics").fetchone()[0] == 0
```

Add to `tests/test_pipeline.py`:

```python
def test_every_stage_is_recorded_with_a_duration(tmp_path):
    store = _store(tmp_path)
    run_id = run_pipeline(
        settings=_settings(tmp_path),
        source=_FakeTrendSource([_evidence()]),
        provider=FakeLLMProvider(responses=[_draft(), _choice()]),
        store=store,
        run_id="r1",
    )

    stages = store.stages_for_run(run_id)

    assert [s.stage for s in stages] == [
        Stage.INGEST,
        Stage.ANALYSE,
        Stage.EVALUATE,
        Stage.GENERATE,
    ]
    assert all(s.status == "ok" for s in stages)
    assert all(s.started_at is not None and s.finished_at is not None for s in stages)


def test_a_skipped_stage_is_recorded_as_skipped(tmp_path):
    """Resuming from generate leaves three stages that did not run this time.
    The cards show them as skipped, not as never having existed."""
    store = _store(tmp_path)
    settings = _settings(tmp_path)
    run_id = run_pipeline(
        settings=settings,
        source=_FakeTrendSource([_evidence()]),
        provider=FakeLLMProvider(responses=[_draft(), _choice()]),
        store=store,
        run_id="r1",
    )

    run_pipeline(
        settings=settings,
        source=_FakeTrendSource([]),
        provider=FakeLLMProvider(responses=[_choice()]),
        store=store,
        run_id=run_id,
        start_at=Stage.GENERATE,
    )

    stages = {s.stage: s.status for s in store.stages_for_run(run_id)}

    assert stages[Stage.INGEST] == "skipped"
    assert stages[Stage.GENERATE] == "ok"


def test_stage_summaries_report_what_each_stage_did(tmp_path):
    """The stage cards render this line verbatim, and nothing else asserts
    it - a stage handed another stage's summary, or a miscounted one, would
    show as plausible-looking noise on every run."""
    store = _store(tmp_path)
    run_id = run_pipeline(
        settings=_settings(tmp_path),
        source=_FakeTrendSource([_evidence()]),
        provider=FakeLLMProvider(responses=[_draft(), _choice()]),
        store=store,
        run_id="r1",
    )

    summaries = {s.stage: s.summary for s in store.stages_for_run(run_id)}

    assert summaries[Stage.INGEST] == "1 trend, 1 post"
    assert summaries[Stage.ANALYSE] == "1 topic distilled"
    assert summaries[Stage.EVALUATE] == "1 of 1 kept"
    assert summaries[Stage.GENERATE] == "1 of 1 rendered"


def test_run_topics_covers_every_topic_not_just_the_kept_ones(tmp_path):
    """The ranking screen draws below-the-cut rows, so they need rows."""
    store = _store(tmp_path)
    # _settings defaults to topic_count=1, so the second topic falls below the
    # cut and appears in run_topics but not in the evaluate checkpoint.
    run_id = run_pipeline(
        settings=_settings(tmp_path),
        source=_FakeTrendSource([_evidence("A trend"), _evidence("B trend")]),
        provider=FakeLLMProvider(responses=[_draft(), _draft(), _choice()]),
        store=store,
        run_id="r1",
    )

    assert len(store.read_checkpoint(run_id, Stage.EVALUATE, ScoredTopic)) == 1
    assert len(store.run_topics(run_id)) == 2
    # Two trends, so this run is also the plural branch of _count.
    summaries = {s.stage: s.summary for s in store.stages_for_run(run_id)}
    assert summaries[Stage.INGEST] == "2 trends, 2 posts"
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_pipeline.py -k "stage or run_topics" tests/test_store.py -k analyse -v`

Expected: FAIL — no `write_analyse_checkpoint`, and `stages_for_run` returns `[]`.

- [ ] **Step 3: Add the combined store method**

Refactor `write_checkpoint` and `write_run_topics` so the SQL is reusable without committing, then:

```python
    def write_analyse_checkpoint(
        self, run_id: str, topics: Sequence[Topic], meme_potential_weight: float
    ) -> int:
        """Write the analyse payload and its flattened rows in one transaction.

        Together, or not at all. `run_topics` is derived from this payload,
        and the claim that the two cannot disagree only holds if a crash
        between them leaves neither.
        """
        payload = json.dumps([topic.model_dump(mode="json") for topic in topics])
        rows = flatten(run_id, list(topics), meme_potential_weight)
        with self._conn:
            self._insert_checkpoint(run_id, Stage.ANALYSE, payload)
            self._insert_run_topics(rows)
        return len(payload.encode("utf-8"))
```

`with self._conn:` is sqlite3's transaction context manager — it commits on success and rolls back on any exception. `_insert_checkpoint(run_id, stage, payload)` and `_insert_run_topics(rows)` are the bodies of the existing methods with their `commit()` calls removed; `write_checkpoint` and `write_run_topics` become thin wrappers that call them inside `with self._conn:`. Import `flatten` from `zeitgeist.projection`.

- [ ] **Step 4: Record stages from the pipeline**

Add a small helper to `pipeline.py` and call it around each stage:

```python
def _stage(
    store: Store, run_id: str, stage: Stage, started: datetime, summary: str, size: int | None
) -> None:
    store.record_stage(
        run_id,
        StageRecord(
            stage=stage,
            status="ok",
            started_at=started,
            finished_at=datetime.now(UTC),
            payload_bytes=size,
            summary=summary,
        ),
    )
```

In `run_pipeline`, record every stage in `ORDER`. A stage below `resuming` is `skipped` with no timings and the summary `"skipped"`; a stage that runs is timed with `datetime.now(UTC)` taken immediately before it starts. Use `store.write_analyse_checkpoint` in place of `store.write_checkpoint` for `Stage.ANALYSE`. Summaries go through a pluralisation helper, because `"1 trends, 1 posts"` is what a naive f-string produces and the stage card renders this text verbatim:

```python
def _count(n: int, noun: str) -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"
```

Ingest `f"{_count(len(evidence), 'trend')}, {_count(len(items), 'post')}"`, analyse `f"{_count(len(topics), 'topic')} distilled"`, evaluate `f"{len(ranked)} of {len(topics)} kept"`, generate `f"{rendered} of {len(briefs)} rendered"`. The last two need no helper — "of" carries the count.

Add `StageRecord` to the records import.

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_pipeline.py tests/test_store.py -v`

Expected: PASS.

- [ ] **Step 6: Run the full gate**

Run: `uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest`

Expected: all four pass, `tests/test_cli.py` aside.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "Record stages, and flatten topics in the checkpoint's transaction

Every stage gets a row with its status, timings, payload size and a one-line
summary, including the ones a resume skipped - the cards show those as
skipped rather than as never having existed.

write_analyse_checkpoint writes the payload and its run_topics rows inside
one transaction. The claim that a checkpoint and its flattened rows cannot
disagree only holds if a crash between them leaves neither, so there is a
test that asserts exactly that.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 15: Delete the CLI, add the scripts, update the docs

**Files:**
- Delete: `zeitgeist/cli.py`, `tests/test_cli.py`
- Create: `scripts/run_pipeline.py`, `scripts/validate_templates.py`
- Modify: `pyproject.toml`, `README.md`

**Interfaces:**
- Consumes: everything above.
- Produces: nothing importable. `scripts/run_pipeline.py` is the deliverable for this phase.

**Order matters:** `pyproject.toml` names `zeitgeist.cli:main`. Deleting the module while that entry stands fails `uv sync --locked`, which is CI's first step, so everything behind it fails too. Remove the entry in the same commit.

- [ ] **Step 1: Delete the CLI and its tests**

```bash
git rm zeitgeist/cli.py tests/test_cli.py
```

- [ ] **Step 2: Remove the console entry point**

In `pyproject.toml`, delete these three lines:

```toml
[project.scripts]
zeitgeist = "zeitgeist.cli:main"
```

The package has no console entry point until phase 2 restores it pointing at the server.

- [ ] **Step 3: Write the dev harness**

Create `scripts/run_pipeline.py`:

```python
"""Run the pipeline once, for development.

Not a CLI. A CLI is a product surface — installed, documented, tested as a
contract — and the web UI is that now. This is fifteen lines that call
`run_pipeline` so a run can be produced before the API can start one, and it
stays afterwards because scripted and repeated runs during development are
useful.

    uv run python scripts/run_pipeline.py
"""

import logging
import sys

from zeitgeist.config import Settings
from zeitgeist.llm.factory import build_provider
from zeitgeist.pipeline import new_run_id, run_pipeline
from zeitgeist.sources import build_trend_source
from zeitgeist.store import Store


def main() -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )
    settings = Settings()
    store = Store(settings.db_path)
    try:
        store.init_schema()
        run_id = run_pipeline(
            settings=settings,
            source=build_trend_source(settings),
            provider=build_provider(settings),
            store=store,
            run_id=new_run_id(),
        )
        record = store.get_run(run_id)
    finally:
        store.close()
    print(f"Run complete: {run_id} ({record.item_count if record else 0} items)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Move `validate-templates` to a script**

Create `scripts/validate_templates.py`:

```python
"""Check every template manifest against its image.

Deliberately builds no Settings: checking the shipped templates should work
before anyone has written a .env.

    uv run python scripts/validate_templates.py [directory]
"""

import sys
from pathlib import Path

from zeitgeist.config import PACKAGE_ROOT
from zeitgeist.media.templates import validate_templates


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    directory = Path(args[0]) if args else PACKAGE_ROOT / "media" / "templates"
    problems = validate_templates(directory)
    if not problems:
        print(f"All templates in {directory} are valid.")
        return 0
    for problem in problems:
        print(problem)
    return 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Update the README**

Replace the `## Running` section's `uv run zeitgeist run` invocations with `uv run python scripts/run_pipeline.py`, and the `zeitgeist validate-templates` invocation with `uv run python scripts/validate_templates.py`. Rewrite the paragraph beginning "Output lands in `output/<run-id>/`" to:

> Stage checkpoints are written to SQLite at `data/zeitgeist.db`; rendered
> memes land in `output/<run-id>/renders/`, one PNG and one 96px thumbnail
> per meme. Read a checkpoint back with:
>
> ```bash
> sqlite3 data/zeitgeist.db "select payload from checkpoints where run_id='...' and stage='analyse'" | jq
> ```

Delete the two paragraphs documenting `--run-id`, `--resume-from` and `--templates` as flags, and note that resuming is not available from the harness — it arrives with the API in phase 3. Add a line under a new `## Web UI` heading pointing at `docs/superpowers/specs/2026-09-02-web-ui-design.md`.

- [ ] **Step 6: Verify the harness runs end to end against fakes**

There is no test for `scripts/`, and there should not be — it is a fifteen-line harness whose parts are all tested. Verify it manually against Ollama, or confirm the import graph is sound:

Run: `uv run python -c "import runpy; runpy.run_path('scripts/validate_templates.py', run_name='not_main')" && uv run python scripts/validate_templates.py`

Expected: `All templates in ...\media\templates are valid.`

Run: `uv run python -c "import ast,sys; ast.parse(open('scripts/run_pipeline.py').read())" && echo parsed`

Expected: `parsed`

- [ ] **Step 7: Confirm the package still installs**

Run: `uv sync --locked`

Expected: succeeds. This is the check that catches a stale `[project.scripts]`.

- [ ] **Step 8: Run the full gate**

Run: `uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest`

Expected: all four pass. This is the first point in the plan where the whole suite is green.

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "Delete the CLI; add the dev harness and the template validator

The web UI is the interface, and a second product surface for the same
pipeline is not maintained. pyproject's [project.scripts] entry goes in the
same commit as the module it names - leaving it pointing at a deleted module
fails uv sync --locked, which is CI's first step, so everything behind it
fails too. Phase 2 restores the entry point pointing at the server.

scripts/run_pipeline.py replaces it as the way to produce a run until the API
can start one, and stays afterwards. validate-templates moves to scripts/
beside the three dev scripts already there; the validator itself does not
move, only its entry point.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Verification

After Task 15, confirm the phase's stated end condition — `scripts/run_pipeline.py` persisting a complete run entirely through the store, and `data/zeitgeist.db` and `output/` cleared of everything that came before.

- [ ] **Clear what came before**

```bash
rm -rf output data
```

Runs written before this work are discarded rather than migrated. This is the point that happens.

- [ ] **Produce a real run**

With `LLM_PROVIDER=ollama` and `LLM_MODEL=qwen3.5` in `.env`:

```bash
uv run python scripts/run_pipeline.py
```

- [ ] **Confirm what landed**

```bash
sqlite3 data/zeitgeist.db "select stage, length(payload) from checkpoints"
sqlite3 data/zeitgeist.db "select stage, status, summary from run_stages"
sqlite3 data/zeitgeist.db "select final_rank, topic_id, trend_status, meme_potential from run_topics order by final_rank"
sqlite3 data/zeitgeist.db "select id, status, error from renders"
ls output/*/renders/
```

Expected: four checkpoint rows; four stage rows all `ok` with summaries; one `run_topics` row per distilled topic with rank 1 upward, **more rows than the evaluate checkpoint holds**; one `renders` row per brief; and a `.png` plus a `.thumb.png` per successful render.

- [ ] **Confirm nothing writes JSON to the run directory**

```bash
ls output/*/
```

Expected: only `renders/`. No `evidence.json`, `topics.json`, `ranked.json` or `briefs.json`.

---

## Notes for the executor

**Where the suite is red on purpose.** Tasks 4 and 5 are one reviewable change split for readability; the suite is red between them and Task 4 has no commit. From Task 5 through Task 14, `tests/test_pipeline.py` fails because the pipeline has not been rewired yet — that is expected and called out in each task's gate step. The suite is green again at Task 12 except for `tests/test_cli.py`, and fully green at Task 15.

**Do not add the frontend gate commands.** `CLAUDE.md`'s Definition of Done stays at four commands. `web/` does not exist until phase 5, and adding `npm --prefix web run lint` now turns every PR red for a directory that is not supposed to exist yet.

**Do not write accessors nothing calls.** `log_lines` has a table and no methods; `renders` has insert and read but no delete. Both are deliberate — phases 3 and 4 own them.

**If a test in this plan seems wrong, say so rather than weakening it.** Several assert properties the spec argues for at length: that a checkpoint round-trips exactly (resume depends on it), that a checkpoint and its `run_topics` rows commit together (the "cannot disagree" claim rests on it), that every topic is ranked and not just the kept ones (the ranking screen draws below-the-cut rows), and that only the seven tuning fields are writable. Changing one of those to make it pass would remove the thing it exists to protect.
