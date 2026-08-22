# Wikimedia Source and Per-Platform Scoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Wikimedia pageviews as a second working platform, replacing the single shared trend scorer with per-platform scoring strategies that normalise within their own platform before combination.

**Architecture:** `Post` becomes `Item`, an envelope carrying a Pydantic discriminated union of platform-specific metrics, so no field has to mean two different things across platforms. Trend scoring moves out of `analysis/score.py` into a registry of per-platform scorers under `analysis/scorers/`, each returning `[0, 1]` normalised within its own platform; `score.py` shrinks to a coordinator that dispatches, filters, and combines with a corroboration bonus.

**Tech Stack:** Python 3.14, Pydantic v2, pydantic-settings, httpx, SQLite, pytest, ruff, ty, uv.

## Global Constraints

- **Definition of Done** — every task ends with all four passing: `uv run ruff check .`, `uv run ruff format --check .`, `uv run ty check`, `uv run pytest`.
- **Python 3.14** — use PEP 695 generics (`def f[T: Bound](...)`, `class C[M: Bound]`), never `typing.TypeVar`.
- **Line length 88.** Ruff rules `E, F, I, UP, B, SIM`.
- **No blanket `# type: ignore`.** A narrow suppression needs a comment explaining why. Fix type errors at the root cause.
- **Tests are hermetic** — no test touches the network. Sources take an injected client; LLM calls go through `FakeLLMProvider`.
- **`STRICT = ConfigDict(extra="forbid")`** stays on every domain model. Unknown keys are an error.
- **Commit after every task.** Do not open a PR until all four commands pass.
- **Spec:** `docs/superpowers/specs/2026-08-22-wikimedia-source-design.md`.

## File Structure

**Phase 1 — `Post` → `Item`**
| File | Responsibility |
|---|---|
| `zeitgeist/models.py` | `Item`, the `Metrics` union, `Topic.item_ids` |
| `zeitgeist/sources/lemmy.py` | emit `Item` with `LemmyMetrics` |
| `zeitgeist/sources/reddit.py` | emit `Item` with `RedditMetrics` |
| `zeitgeist/sources/{base,composite}.py` | type updates only |
| `zeitgeist/analysis/extract.py` | prompt uses `item.context`, not `post.channel` |
| `zeitgeist/analysis/consolidate.py` | build `Topic(item_ids=...)` |
| `zeitgeist/analysis/sentiment.py` | prompt reads `len(topic.item_ids)` |
| `zeitgeist/{pipeline,store,cli}.py` | `items.json`, `item_count`, `"N items"` |

**Phase 2 — scorer registry**
| File | Responsibility |
|---|---|
| `zeitgeist/analysis/scorers/base.py` | `TrendScorer` protocol, `ScoreWeights`, `normalise` |
| `zeitgeist/analysis/scorers/lemmy.py` | velocity + spread + delta maths (moved) |
| `zeitgeist/analysis/scorers/reddit.py` | same maths over `RedditMetrics` |
| `zeitgeist/analysis/scorers/__init__.py` | `SCORERS` registry, `build_scorer` |
| `zeitgeist/analysis/score.py` | coordinator: group, dispatch, filter, combine |

**Phase 3 — persistence**
| File | Responsibility |
|---|---|
| `zeitgeist/store.py` | `topic_scores`, `previous_sub_scores`, schema guard |

**Phase 4 — Wikimedia**
| File | Responsibility |
|---|---|
| `zeitgeist/sources/wikipedia.py` | pageviews fetch, day walk-back, structural filtering |
| `zeitgeist/analysis/scorers/wikipedia.py` | rank + delta scoring |
| `zeitgeist/config.py`, `.env.example`, `README.md` | configuration and docs |

---

## Phase 1 — `Post` becomes `Item`

Behaviour-preserving throughout. At the end of Phase 1 the pipeline produces identical output to before, through a new model.

### Task 1: The `Item` model and metrics union

**Files:**
- Modify: `zeitgeist/models.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `Item`, `LemmyMetrics`, `RedditMetrics`, `Metrics`, `Topic.item_ids`. `Item.platform -> str`, `Item.context -> str`, `Item.content_bearing -> bool`. Metrics models expose `.platform: str`, `.context: str`, and `.content_bearing: ClassVar[bool]`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_models.py`:

```python
import pytest
from pydantic import ValidationError

from zeitgeist.models import Item, LemmyMetrics, RedditMetrics, Topic


def _lemmy_item(**overrides) -> Item:
    metrics = LemmyMetrics(
        score=10,
        comment_count=2,
        channel="technology@lemmy.world",
        created_at=datetime(2026, 8, 16, 9, 0, tzinfo=UTC),
    )
    fields = {
        "source_id": "abc123",
        "title": "A post",
        "permalink": "https://lemmy.world/post/1",
        "fetched_at": datetime(2026, 8, 16, 12, 0, tzinfo=UTC),
        "metrics": metrics,
    }
    return Item(**{**fields, **overrides})


def test_item_platform_reads_through_to_metrics():
    assert _lemmy_item().platform == "lemmy"


def test_item_context_is_the_channel_for_lemmy():
    """The extraction prompt uses `context` where it used to use `channel`.
    Asserting the value, not just that it exists, is what stops a future
    edit silently emptying the hint the model reads.
    """
    assert _lemmy_item().context == "technology@lemmy.world"


def test_metrics_union_dispatches_on_platform_discriminator():
    """A raw dict must deserialise to the right concrete metrics class.
    This is what makes the JSON checkpoints round-trip."""
    item = Item.model_validate(
        {
            "source_id": "t3_x",
            "title": "A post",
            "permalink": "https://reddit.com/r/x/1",
            "fetched_at": "2026-08-16T12:00:00Z",
            "metrics": {
                "platform": "reddit",
                "score": 99,
                "comment_count": 5,
                "channel": "r/technology",
                "created_at": "2026-08-16T09:00:00Z",
            },
        }
    )
    assert isinstance(item.metrics, RedditMetrics)
    assert item.metrics.score == 99


def test_metrics_union_rejects_an_unknown_platform():
    with pytest.raises(ValidationError):
        Item.model_validate(
            {
                "source_id": "x",
                "title": "A post",
                "permalink": "https://example.com/1",
                "fetched_at": "2026-08-16T12:00:00Z",
                "metrics": {"platform": "myspace", "score": 1},
            }
        )


def test_lemmy_metrics_reject_an_unknown_field():
    """STRICT must survive the move into the union — a field a future
    platform slips in should fail at the boundary, not vanish."""
    with pytest.raises(ValidationError):
        LemmyMetrics.model_validate(
            {
                "platform": "lemmy",
                "score": 1,
                "comment_count": 1,
                "channel": "c@h",
                "created_at": "2026-08-16T09:00:00Z",
                "author": "someone",
            }
        )


# The complete specified field set of each model, written out by hand rather
# than derived from the model, so that a change to a model fails this test.
# Catches two breaks at once: a PII field such as `author` creeping in, and a
# field the checkpoint format depends on quietly disappearing. `metrics` now
# carries the platform-specific half, so it needs the same guard as `Item`.
# Replaces the old POST_FIELDS / test_post_carries_exactly_the_specified_fields.
_ENGAGEMENT_FIELDS = {"platform", "score", "comment_count", "channel", "created_at"}


@pytest.mark.parametrize(
    "model,want",
    [
        (
            Item,
            {
                "source_id",
                "title",
                "body_excerpt",
                "permalink",
                "fetched_at",
                "metrics",
            },
        ),
        (LemmyMetrics, _ENGAGEMENT_FIELDS),
        (RedditMetrics, _ENGAGEMENT_FIELDS),
    ],
)
def test_models_carry_exactly_the_specified_fields(model, want):
    assert set(model.model_fields) == want


@pytest.mark.parametrize("field", ["author", "username", "user_id", "titel"])
def test_item_rejects_undeclared_fields(field):
    """Without extra="forbid", Pydantic silently drops unknown keys — so a
    typo'd field name or an author slipped in by a new source would pass
    unnoticed rather than failing loudly.
    """
    with pytest.raises(ValidationError):
        _lemmy_item(**{field: "somebody"})


def test_topic_rejects_the_old_post_ids_field():
    """extra='forbid' means a stale checkpoint fails loudly rather than
    silently losing its item list. Named in the spec as intended behaviour."""
    with pytest.raises(ValidationError):
        Topic.model_validate(
            {"id": "cats", "label": "Cats", "summary": "", "post_ids": ["abc123"]}
        )
```

Delete `POST_FIELDS` and `test_post_carries_exactly_the_specified_fields` — the parametrized guard above replaces them, covering three models rather than one. Update the remaining tests in `tests/test_models.py` that construct `Post(...)` or `Topic(post_ids=...)` to use the new shape; `_lemmy_item(...)` covers most of them.

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_models.py -v
```

Expected: FAIL with `ImportError: cannot import name 'Item' from 'zeitgeist.models'`.

- [ ] **Step 3: Write the implementation**

Replace the `Post` class in `zeitgeist/models.py`:

```python
from datetime import datetime
from enum import StrEnum
from typing import Annotated, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field

STRICT = ConfigDict(extra="forbid")


class LemmyMetrics(BaseModel):
    """Engagement as Lemmy reports it."""

    model_config = STRICT

    platform: Literal["lemmy"] = "lemmy"
    # Whether this platform supplies text a caption can be written from.
    # Attention-measuring platforms set False and cannot originate topics.
    content_bearing: ClassVar[bool] = True

    score: int
    comment_count: int
    channel: str
    created_at: datetime

    @property
    def context(self) -> str:
        """One-line hint for the extraction prompt, meaningful per platform."""
        return self.channel


class RedditMetrics(BaseModel):
    """Engagement as Reddit reports it."""

    model_config = STRICT

    platform: Literal["reddit"] = "reddit"
    content_bearing: ClassVar[bool] = True

    score: int
    comment_count: int
    channel: str
    created_at: datetime

    @property
    def context(self) -> str:
        return self.channel


# Discriminated on `platform`, so a checkpoint dict deserialises back to the
# concrete class rather than to whichever union member happens to validate.
Metrics = Annotated[
    LemmyMetrics | RedditMetrics,
    Field(discriminator="platform"),
]


class Item(BaseModel):
    """A single normalised observation from any platform.

    Deliberately carries no author or username: no downstream stage needs it,
    and omitting it keeps the project clear of storing personal data.

    Everything that differs between platforms lives in `metrics`, so no field
    on this envelope has to mean two different things depending on where it
    came from.
    """

    model_config = STRICT

    source_id: str
    title: str
    body_excerpt: str | None = None
    permalink: str
    fetched_at: datetime
    metrics: Metrics

    @property
    def platform(self) -> str:
        return self.metrics.platform

    @property
    def context(self) -> str:
        return self.metrics.context

    @property
    def content_bearing(self) -> bool:
        return self.metrics.content_bearing
```

Rename the field on `Topic`:

```python
class Topic(BaseModel):
    """A cluster of items about the same thing."""

    model_config = STRICT

    id: str
    label: str
    summary: str
    item_ids: list[str]
    trend_score: float = 0.0
    score_components: dict[str, float] = Field(default_factory=dict)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_models.py -v
```

Expected: PASS. Other test files will still fail — that is Task 2 onward.

- [ ] **Step 5: Commit**

```bash
git add zeitgeist/models.py tests/test_models.py
git commit -m "Replace Post with Item carrying a discriminated metrics union"
```

---

### Task 2: Sources emit `Item`

**Files:**
- Modify: `zeitgeist/sources/base.py`, `zeitgeist/sources/lemmy.py`, `zeitgeist/sources/reddit.py`, `zeitgeist/sources/composite.py`
- Test: `tests/test_sources_lemmy.py`, `tests/test_sources_reddit.py`, `tests/test_sources_composite.py`

**Interfaces:**
- Consumes: `Item`, `LemmyMetrics`, `RedditMetrics` from Task 1.
- Produces: `Source.fetch(limit: int) -> list[Item]`. `CompositeSource.fetch` dedups on `(item.platform, item.source_id)`.

- [ ] **Step 1: Write the failing tests**

This task adds **no new tests**. The existing suites already pin every behaviour that changes here; what they need is re-pointing through `metrics`. Adding parallel tests would duplicate them under new names.

In `tests/test_sources_lemmy.py`, re-point the existing assertions:

- `test_maps_views_onto_posts` — change `post.score` to `post.metrics.score`, `post.comment_count` to `post.metrics.comment_count`, `post.created_at` to `post.metrics.created_at`, and drop the `post.platform == "lemmy"` assertion only if it now reads through the property (it still works). This test already pins the mapping with hand-derived literals; it is the guard against a swapped `score`/`comment_count`.
- `test_channel_is_qualified_by_instance_host` — change to `post.metrics.channel`. This remains the guard on `_channel`.
- `test_created_at_is_timezone_aware_when_the_instance_omits_the_zone` — change to `post.metrics.created_at`.

Keep the file's existing helpers (`_view(ap_id, title, ...)`, `StubClient` keyed on `(sort, page)`, `_source(pages)`) exactly as they are — they need no changes.

In `tests/test_sources_composite.py`, convert the `_post` helper into `_item`, which every test in the file then uses unchanged:

```python
def _item(platform: str, source_id: str, channel: str = "cats") -> Item:
    """Dispatches on platform so each item carries its own metrics class.
    Every test in this file builds items through here, so the union is
    exercised by the whole file rather than by one dedicated test.
    """
    metrics_class = {"lemmy": LemmyMetrics, "reddit": RedditMetrics}[platform]
    return Item(
        source_id=source_id,
        title=f"Post {source_id}",
        permalink=f"https://example.com/{source_id}",
        fetched_at=datetime(2026, 8, 16, 12, 0, tzinfo=UTC),
        metrics=metrics_class(
            score=10,
            comment_count=2,
            channel=channel,
            created_at=datetime(2026, 8, 16, 9, 0, tzinfo=UTC),
        ),
    )
```

Rename every `_post(` call site in that file to `_item(`. The existing `test_same_id_on_different_platforms_is_not_a_duplicate` already covers cross-platform dedup and needs no replacement.

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_sources_lemmy.py tests/test_sources_composite.py -v
```

Expected: FAIL — `LemmySource` still returns `Post`.

- [ ] **Step 3: Write the implementation**

In `zeitgeist/sources/base.py`:

```python
"""The extension point. A new platform is a new file implementing this."""

from typing import Protocol

from zeitgeist.models import Item


class SourceError(Exception):
    """Raised when a platform cannot be reached or returns nothing usable."""


class Source(Protocol):
    name: str

    def fetch(self, limit: int) -> list[Item]: ...
```

In `zeitgeist/sources/lemmy.py`, replace `_to_post` and update the `fetch` annotations:

```python
def _to_item(view: dict[str, Any], fetched_at: datetime) -> Item:
    post = view["post"]
    counts = view["counts"]
    body = (post.get("body") or "").strip()
    return Item(
        source_id=post["ap_id"],
        title=post["name"],
        body_excerpt=body[:BODY_EXCERPT_CHARS] or None,
        # ap_id is the canonical URL of the post on its home instance.
        permalink=post["ap_id"],
        fetched_at=fetched_at,
        metrics=LemmyMetrics(
            score=counts["score"],
            comment_count=counts["comments"],
            channel=_channel(view["community"]),
            created_at=_parse_published(post["published"]),
        ),
    )
```

Change `fetch`'s signature to `-> list[Item]`, its `seen: dict[str, Item]`, and its call from `_to_post(...)` to `_to_item(...)`. Import `Item, LemmyMetrics` from `zeitgeist.models`.

In `zeitgeist/sources/reddit.py`, apply the same shape:

```python
def _to_item(submission: Any, fetched_at: datetime) -> Item:
    body = (getattr(submission, "selftext", "") or "").strip()
    return Item(
        source_id=submission.id,
        title=submission.title,
        body_excerpt=body[:BODY_EXCERPT_CHARS] or None,
        permalink=f"https://reddit.com{submission.permalink}",
        fetched_at=fetched_at,
        metrics=RedditMetrics(
            score=submission.score,
            comment_count=submission.num_comments,
            channel=f"r/{submission.subreddit.display_name}",
            created_at=datetime.fromtimestamp(submission.created_utc, tz=UTC),
        ),
    )
```

Match the existing `reddit.py` mapping exactly — read it before editing and preserve whatever field names it already uses; only the destination changes.

In `zeitgeist/sources/composite.py`, change the `Post` import to `Item`, `fetch` to `-> list[Item]`, and `seen: dict[tuple[str, str], Item]`. The dedup key `(post.platform, post.source_id)` still works via the `Item.platform` property — rename the loop variable to `item` for clarity.

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_sources_lemmy.py tests/test_sources_reddit.py tests/test_sources_composite.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add zeitgeist/sources tests/test_sources_lemmy.py tests/test_sources_reddit.py tests/test_sources_composite.py
git commit -m "Emit Item from every source"
```

---

### Task 3: Analysis stages read `Item` and `item_ids`

**Files:**
- Modify: `zeitgeist/analysis/extract.py`, `zeitgeist/analysis/consolidate.py`, `zeitgeist/analysis/sentiment.py`, `zeitgeist/analysis/score.py`
- Test: `tests/test_analysis_extract.py`, `tests/test_analysis_consolidate.py`, `tests/test_analysis_sentiment.py`, `tests/test_analysis_score.py`

**Interfaces:**
- Consumes: `Item`, `Topic.item_ids` from Task 1.
- Produces: `extract_tags(items: list[Item], provider, *, batch_size=BATCH_SIZE) -> dict[str, list[str]]`; `consolidate(...) -> list[Topic]` with `item_ids`; `score_topics(topics, items: list[Item], now, previous_scores, weights=None)` — signature otherwise unchanged this task.

- [ ] **Step 1: Write the failing tests**

In `tests/test_analysis_extract.py`:

```python
def test_prompt_renders_the_id_context_and_title_on_one_line():
    """The prompt previously carried post.channel. Wikipedia has no channel,
    so it carries item.context — which for Lemmy is still the channel. The
    expected line is written out by hand rather than built from
    `item.context`: deriving it would let an emptied context satisfy both
    sides of the assertion, which is the break this test exists to catch.
    """
    item = Item(
        source_id="p999",
        title="Test Lemmy post",
        permalink="https://lemmy.world/post/999",
        fetched_at=datetime(2026, 8, 16, 12, 0, tzinfo=UTC),
        metrics=LemmyMetrics(
            score=100,
            comment_count=5,
            channel="memes@lemmy.world",
            created_at=datetime(2026, 8, 16, 9, 0, tzinfo=UTC),
        ),
    )

    prompt = _build_prompt([item])

    assert "- id=p999 | memes@lemmy.world | Test Lemmy post" in prompt
```

In `tests/test_analysis_consolidate.py`, change `topics[0].post_ids` to `topics[0].item_ids` in all four assertions.

In `tests/test_analysis_sentiment.py`:

```python
def test_prompt_reports_the_item_count():
    """Phase 1 keeps prompt semantics identical apart from the noun, so this
    asserts 'items' and NOT a platform count — that arrives in Phase 2."""
    topic = Topic(id="t", label="T", summary="S", item_ids=["a", "b", "c"])

    prompt = _build_prompt(topic)

    assert "Appears in 3 items." in prompt
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_analysis_extract.py tests/test_analysis_consolidate.py tests/test_analysis_sentiment.py -v
```

Expected: FAIL — `sample_items` fixture missing, `item_ids` unknown.

- [ ] **Step 3: Write the implementation**

`zeitgeist/analysis/extract.py` — rename the parameter and use `context`:

```python
from zeitgeist.models import Item


class ItemTags(BaseModel):
    """Topic tags for one item."""

    item_id: str
    tags: list[str]


class TagExtraction(BaseModel):
    """Tags for every item in one batch."""

    assignments: list[ItemTags]


def extract_tags(
    items: list[Item], provider: LLMProvider, *, batch_size: int = BATCH_SIZE
) -> dict[str, list[str]]:
    """Map every item to its topic tags. Failed batches are skipped."""
    known_ids = {item.source_id for item in items}
    tags: dict[str, list[str]] = {}

    for start in range(0, len(items), batch_size):
        batch = items[start : start + batch_size]
        # Built outside the try: a bug here must crash loudly, not be
        # misreported as a failed batch and silently skipped.
        prompt = _build_prompt(batch)
        try:
            extraction = provider.complete(prompt, TagExtraction, system=EXTRACT_SYSTEM)
        except Exception as exc:
            log.warning(
                "Tag extraction failed for batch starting at %d: %s", start, exc
            )
            continue

        for assignment in extraction.assignments:
            if assignment.item_id not in known_ids:
                continue
            tags[assignment.item_id] = _clean(assignment.tags)

    return tags


def _build_prompt(batch: list[Item]) -> str:
    lines = [f"- id={item.source_id} | {item.context} | {item.title}" for item in batch]
    listing = "\n".join(lines)
    return (
        "Label each of these items with its topics.\n\n"
        f"{listing}\n\n"
        "Return one entry per item, using the exact id given."
    )
```

Update `EXTRACT_SYSTEM` wording from "social media posts" to "social media items" and "Give each post" to "Give each item".

`zeitgeist/analysis/consolidate.py` — rename the local and the field:

```python
    for entry in consolidation.topics:
        wanted = {tag.strip().lower() for tag in entry.tags}
        item_ids = sorted(
            item_id
            for item_id, tags in tags_by_item.items()
            if wanted & {t.strip().lower() for t in tags}
        )
        if not item_ids:
            log.debug("Dropping topic %r: no items matched its tags", entry.label)
            continue

        topics.append(
            Topic(
                id=_unique_slug(entry.label, used_ids),
                label=entry.label,
                summary=entry.summary,
                item_ids=item_ids,
            )
        )
```

Rename the `consolidate` parameter `tags_by_post` to `tags_by_item`, and update `_build_prompt`'s line to `f"- {tag} ({count} items)"`.

`zeitgeist/analysis/sentiment.py`:

```python
def _build_prompt(topic: Topic) -> str:
    return (
        f"Topic: {topic.label}\n"
        f"Summary: {topic.summary}\n"
        f"Appears in {len(topic.item_ids)} items.\n\n"
        "Judge this topic's sentiment and meme potential."
    )
```

`zeitgeist/analysis/score.py` — mechanical only this task. Change the `Post` import to `Item`, rename the `posts` parameter to `items`, and read engagement through `metrics`:

```python
def _mean_velocity(items: list[Item], now: datetime, attribute: str) -> float:
    values = []
    for item in items:
        hours = (now - item.metrics.created_at).total_seconds() / 3600.0
        values.append(getattr(item.metrics, attribute) / max(hours, MIN_AGE_HOURS))
    return sum(values) / len(values)
```

and `raw_cs = [float(len({item.metrics.channel for item in group})) for _, group in live]`, and `matched = [by_id[iid] for iid in topic.item_ids if iid in by_id]`.

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_analysis_extract.py tests/test_analysis_consolidate.py tests/test_analysis_sentiment.py tests/test_analysis_score.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add zeitgeist/analysis tests/test_analysis_*.py
git commit -m "Read Item and item_ids through the analysis stages"
```

---

### Task 4: Wire the pipeline, store, CLI and fixtures

**Files:**
- Modify: `zeitgeist/pipeline.py`, `zeitgeist/store.py`, `zeitgeist/cli.py`, `tests/conftest.py`
- Rename: `tests/fixtures/posts.json` → `tests/fixtures/items.json`
- Test: `tests/test_pipeline.py`, `tests/test_store.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: everything from Tasks 1–3.
- Produces: ingest checkpoint at `items.json`; `Store.finish_run(run_id, status, item_count)`; `conftest.sample_items` fixture returning `list[Item]`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_pipeline.py`:

Read the existing `tests/test_pipeline.py` first and reuse its helpers — it already builds a `Settings`, a stub `Source`, a `FakeLLMProvider` and a `Store`. Adapt the call below to whatever those helpers are actually named.

The existing `test_writes_every_checkpoint` already guards the checkpoint filenames; this task re-points it from `posts.json` to `items.json` rather than adding a parallel test. Add only the round-trip, which nothing currently covers:

```python
def test_the_ingest_checkpoint_round_trips_through_item(settings, sample_items):
    """Checkpoint JSON must deserialise back to the concrete metrics class
    with its values intact, or --resume-from silently produces
    differently-shaped items than the run that wrote them.
    """
    items = sample_items[:3]
    run_dir = run_pipeline(
        settings, StubSource(items), _provider(items), _store(settings), "run1"
    )

    raw = json.loads((run_dir / "items.json").read_text(encoding="utf-8"))
    restored = [Item.model_validate(entry) for entry in raw]

    assert [i.source_id for i in restored] == ["p01", "p02", "p03"]
    assert all(isinstance(i.metrics, RedditMetrics) for i in restored)
    assert restored[0].metrics.channel == "cats"
    assert restored[0].metrics.score == 48200
```

In `tests/test_store.py`:

```python
def test_finish_run_records_the_item_count(tmp_path):
    store = Store(tmp_path / "z.db")
    store.init_schema()
    store.start_run("r1")

    store.finish_run("r1", status="ok", item_count=7)

    assert store.run_summary("r1")["item_count"] == 7
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_pipeline.py tests/test_store.py -v
```

Expected: FAIL — `posts.json` still written, `finish_run` takes `post_count`.

- [ ] **Step 3: Write the implementation**

Rename the fixture file and update `tests/conftest.py`:

```python
from zeitgeist.models import Item


@pytest.fixture
def sample_items() -> list[Item]:
    raw = json.loads((FIXTURES / "items.json").read_text(encoding="utf-8"))
    return [Item.model_validate(entry) for entry in raw]
```

Restructure every entry in `tests/fixtures/items.json` into the new shape — move `score`, `comment_count`, `channel` and `created_at` under a `metrics` object, moving the existing `platform` key inside it.

**Keep `"platform": "reddit"`.** All ten entries are real Reddit data — `reddit.com/r/...` permalinks, bare subreddit channels like `cats` and `aww`, scores in the tens of thousands. Relabelling them `lemmy` would produce a payload no platform could ever emit: a Lemmy item with a Reddit URL and a channel that is not instance-qualified, contradicting `test_channel_is_qualified_by_instance_host`. A fixture that mirrors nothing real proves nothing.

```json
{
  "source_id": "p01",
  "title": "My cat learned to open the fridge",
  "body_excerpt": null,
  "permalink": "https://www.reddit.com/r/cats/comments/p01/",
  "fetched_at": "2026-08-16T12:00:00Z",
  "metrics": {
    "platform": "reddit",
    "score": 48200,
    "comment_count": 1420,
    "channel": "cats",
    "created_at": "2026-08-16T09:00:00Z"
  }
}
```

Take the real values for each of the ten entries from the existing `tests/fixtures/posts.json` — only the nesting changes, never a value.

Rename every `sample_posts` usage across the suite to `sample_items`.

In `zeitgeist/pipeline.py`: change the `Post` import to `Item`, `posts: list[Item] = []` to `items: list[Item] = []`, both `posts.json` paths to `items.json`, `_read(run_dir / "items.json", Item)`, and `store.finish_run(run_id, status="ok", item_count=len(items))`.

In `zeitgeist/store.py`, change the `runs` DDL column `post_count INTEGER` to `item_count INTEGER`, and:

```python
    def finish_run(self, run_id: str, status: str, item_count: int) -> None:
        self._conn.execute(
            "UPDATE runs SET finished_at = ?, status = ?, item_count = ? "
            "WHERE run_id = ?",
            (_now(), status, item_count, run_id),
        )
        self._conn.commit()
```

and in `run_summary`, `SELECT status, item_count, finished_at` returning `{"status": row[0], "item_count": row[1], "finished_at": row[2]}`.

In `zeitgeist/cli.py:101-102`:

```python
    items = (summary or {}).get("item_count", 0)
    print(f"Run complete: {run_dir} ({items} items, {memes} memes)")
```

- [ ] **Step 4: Run the whole suite**

```bash
uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest
```

Expected: all four PASS. Phase 1 is complete and behaviour-preserving.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "Wire pipeline, store and CLI onto Item"
```

---

## Phase 2 — Per-platform scorer registry

### Task 5: Scorer protocol, shared helpers, and the Lemmy/Reddit scorers

**Files:**
- Create: `zeitgeist/analysis/scorers/__init__.py`, `zeitgeist/analysis/scorers/base.py`, `zeitgeist/analysis/scorers/lemmy.py`, `zeitgeist/analysis/scorers/reddit.py`
- Test: `tests/test_scorers_lemmy.py`, `tests/test_scorers_reddit.py`

**Interfaces:**
- Consumes: `LemmyMetrics`, `RedditMetrics` from Task 1.
- Produces:
  - `base.ScoreWeights` — fields `upvote_velocity=0.4`, `comment_velocity=0.3`, `channel_spread=0.3`, `rank_delta=0.25`, `corroboration_bonus=0.25`.
  - `base.normalise(values: list[float]) -> list[float]` — min-max; zero range yields zeros.
  - `base.TrendScorer[M]` protocol with `platform: str` and `score(self, per_topic: list[list[M]], previous: list[float | None]) -> list[float]`.
  - `scorers.build_scorer(platform: str, weights: ScoreWeights, now: datetime) -> TrendScorer`.
  - `scorers.SCORERS: dict[str, ScorerBuilder]`.
  - **Contract:** the coordinator passes only topics where that platform is present, so no group in `per_topic` is ever empty, and `previous[i]` is `None` when the topic has no history for this platform.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_scorers_lemmy.py`:

```python
from datetime import UTC, datetime

from zeitgeist.analysis.scorers import build_scorer
from zeitgeist.analysis.scorers.base import ScoreWeights, normalise
from zeitgeist.models import LemmyMetrics

NOW = datetime(2026, 8, 16, 12, 0, tzinfo=UTC)


def _m(score: int, comments: int, channel: str, age_hours: float) -> LemmyMetrics:
    return LemmyMetrics(
        score=score,
        comment_count=comments,
        channel=channel,
        created_at=datetime.fromtimestamp(
            NOW.timestamp() - age_hours * 3600, tz=UTC
        ),
    )


def test_normalise_maps_min_to_zero_and_max_to_one():
    assert normalise([2.0, 4.0, 6.0]) == [0.0, 0.5, 1.0]


def test_normalise_returns_zeros_for_a_flat_range():
    """Never a division error, and never NaN reaching the ranking."""
    assert normalise([3.0, 3.0]) == [0.0, 0.0]


def test_faster_upvote_velocity_scores_higher():
    """Two topics, same age and comments; only score differs."""
    scorer = build_scorer("lemmy", ScoreWeights(), NOW)

    scores = scorer.score(
        per_topic=[
            [_m(score=1000, comments=10, channel="a@h", age_hours=2)],
            [_m(score=10, comments=10, channel="b@h", age_hours=2)],
        ],
        previous=[None, None],
    )

    assert scores[0] > scores[1]


def test_wider_channel_spread_scores_higher():
    """Same velocity in both topics; only the number of distinct channels
    differs. Discriminates channel_spread from a count of items."""
    scorer = build_scorer("lemmy", ScoreWeights(), NOW)

    scores = scorer.score(
        per_topic=[
            [
                _m(score=100, comments=10, channel="a@h", age_hours=2),
                _m(score=100, comments=10, channel="b@h", age_hours=2),
            ],
            [
                _m(score=100, comments=10, channel="c@h", age_hours=2),
                _m(score=100, comments=10, channel="c@h", age_hours=2),
            ],
        ],
        previous=[None, None],
    )

    assert scores[0] > scores[1]


def test_a_topic_with_no_history_is_not_treated_as_maximally_rising():
    """previous=None must default to the topic's own base, giving a delta of
    zero. Discriminates that from the tempting `previous or 0.0`, which would
    hand every first-run topic a full-marks rise."""
    scorer = build_scorer("lemmy", ScoreWeights(), NOW)

    risen = scorer.score(
        per_topic=[
            [_m(score=100, comments=10, channel="a@h", age_hours=2)],
            [_m(score=50, comments=10, channel="b@h", age_hours=2)],
        ],
        previous=[0.0, None],
    )
    fresh = scorer.score(
        per_topic=[
            [_m(score=100, comments=10, channel="a@h", age_hours=2)],
            [_m(score=50, comments=10, channel="b@h", age_hours=2)],
        ],
        previous=[None, None],
    )

    assert risen[0] > fresh[0]


def test_scores_stay_within_the_unit_interval():
    """The whole cross-platform comparison rests on this range."""
    scorer = build_scorer("lemmy", ScoreWeights(), NOW)

    scores = scorer.score(
        per_topic=[
            [_m(score=100000, comments=9000, channel="a@h", age_hours=0.1)],
            [_m(score=1, comments=0, channel="b@h", age_hours=500)],
            [_m(score=50, comments=5, channel="c@h", age_hours=10)],
        ],
        previous=[None, None, None],
    )

    assert all(0.0 <= s <= 1.0 for s in scores)


def test_the_age_floor_stops_a_minutes_old_item_dominating():
    """Ported from test_analysis_score.py, which Task 6 rewrites. Without
    MIN_AGE_HOURS an item seconds old divides by nearly zero and swamps the
    run purely for being new. Three topics, so normalisation has a real range
    and the assertion cannot pass on all-zeros: with the floor the first two
    are indistinguishable, without it the first takes the top of the range
    away from the genuinely busy topic.
    """
    scorer = build_scorer("lemmy", ScoreWeights(), NOW)

    scores = scorer.score(
        per_topic=[
            [_m(score=100, comments=10, channel="a@h", age_hours=0.01)],
            [_m(score=100, comments=10, channel="b@h", age_hours=0.5)],
            [_m(score=1000, comments=100, channel="c@h", age_hours=1)],
        ],
        previous=[None, None, None],
    )

    assert scores[0] == scores[1]
    assert scores[2] > scores[0]


def test_a_topic_averages_its_items_rather_than_summing_them():
    """Ported from test_analysis_score.py. Summing would let a topic climb on
    item count alone: five ordinary items would outrank one genuinely
    fast-moving item.
    """
    scorer = build_scorer("lemmy", ScoreWeights(), NOW)

    scores = scorer.score(
        per_topic=[
            [
                _m(score=100, comments=10, channel="a@h", age_hours=1)
                for _ in range(5)
            ],
            [_m(score=400, comments=40, channel="b@h", age_hours=1)],
        ],
        previous=[None, None],
    )

    assert scores[1] > scores[0]


def test_weights_redirect_the_score_between_the_terms_they_name():
    """Ported from test_weights_are_configurable. Each weight must multiply
    the term it is named after. The defaults sum to 1.0, which makes
    `/ base_total` a no-op and lets a swapped pair of weight fields go
    unnoticed — so this run zeroes the upvote weight, and the heavily
    discussed topic must win despite having none of the upvotes.
    """
    weights = ScoreWeights(
        upvote_velocity=0.0,
        comment_velocity=1.0,
        channel_spread=0.0,
        rank_delta=0.0,
    )
    scorer = build_scorer("lemmy", weights, NOW)

    scores = scorer.score(
        per_topic=[
            [_m(score=10000, comments=1, channel="a@h", age_hours=1)],
            [_m(score=1, comments=10000, channel="b@h", age_hours=1)],
        ],
        previous=[None, None],
    )

    assert scores == [0.0, 1.0]


def test_registry_rejects_an_unregistered_platform():
    import pytest

    with pytest.raises(KeyError):
        build_scorer("myspace", ScoreWeights(), NOW)
```

`scorers/reddit.py` is a hand-copied second implementation of the same algorithm, so the two can drift apart silently. Create `tests/test_scorers_reddit.py`:

```python
"""RedditScorer is a second copy of the Lemmy algorithm over RedditMetrics.
Nothing else in the suite exercises it: the registry guard checks only that
the key exists, and the coordinator tests use Lemmy and Wikipedia.
"""

from datetime import UTC, datetime

from zeitgeist.analysis.scorers import build_scorer
from zeitgeist.analysis.scorers.base import ScoreWeights
from zeitgeist.models import RedditMetrics

NOW = datetime(2026, 8, 16, 12, 0, tzinfo=UTC)


def _m(score: int, comments: int, channel: str, age_hours: float) -> RedditMetrics:
    return RedditMetrics(
        score=score,
        comment_count=comments,
        channel=channel,
        created_at=datetime.fromtimestamp(NOW.timestamp() - age_hours * 3600, tz=UTC),
    )


def test_faster_upvote_velocity_scores_higher():
    """Two topics, same age and comments; only score differs."""
    scorer = build_scorer("reddit", ScoreWeights(), NOW)

    scores = scorer.score(
        per_topic=[
            [_m(score=1000, comments=10, channel="r/a", age_hours=2)],
            [_m(score=10, comments=10, channel="r/b", age_hours=2)],
        ],
        previous=[None, None],
    )

    assert scores[0] > scores[1]


def test_wider_channel_spread_scores_higher():
    """Same velocity in both topics and the same item count; only the number
    of distinct subreddits differs.
    """
    scorer = build_scorer("reddit", ScoreWeights(), NOW)

    scores = scorer.score(
        per_topic=[
            [
                _m(score=100, comments=10, channel="r/a", age_hours=2),
                _m(score=100, comments=10, channel="r/b", age_hours=2),
            ],
            [
                _m(score=100, comments=10, channel="r/c", age_hours=2),
                _m(score=100, comments=10, channel="r/c", age_hours=2),
            ],
        ],
        previous=[None, None],
    )

    assert scores[0] > scores[1]


def test_a_topic_with_no_history_is_not_treated_as_maximally_rising():
    """previous=None must default to the topic's own base, giving a delta of
    zero — not the tempting `previous or 0.0`, which hands every first-run
    topic a full-marks rise.
    """
    scorer = build_scorer("reddit", ScoreWeights(), NOW)
    groups = [
        [_m(score=100, comments=10, channel="r/a", age_hours=2)],
        [_m(score=50, comments=10, channel="r/b", age_hours=2)],
    ]

    risen = scorer.score(per_topic=groups, previous=[0.0, None])
    fresh = scorer.score(per_topic=groups, previous=[None, None])

    assert risen[0] > fresh[0]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_scorers_lemmy.py tests/test_scorers_reddit.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'zeitgeist.analysis.scorers'`.

- [ ] **Step 3: Write the implementation**

Create `zeitgeist/analysis/scorers/base.py`:

```python
"""Shared scoring vocabulary.

`ScoreWeights` lives here rather than in `score.py` because every scorer
needs it and `score.py` imports the scorers — the other direction would be a
cycle.
"""

from typing import Protocol

from pydantic import BaseModel


class ScoreWeights(BaseModel):
    # Within-platform weights, read by the individual scorers.
    upvote_velocity: float = 0.4
    comment_velocity: float = 0.3
    channel_spread: float = 0.3
    rank_delta: float = 0.25
    # Cross-platform weight, read only by the coordinator in score.py.
    corroboration_bonus: float = 0.25


def normalise(values: list[float]) -> list[float]:
    """Min-max normalise. A zero range yields zeros, never a division error."""
    low, high = min(values), max(values)
    if high - low == 0:
        return [0.0] * len(values)
    return [(value - low) / (high - low) for value in values]


class TrendScorer[M: BaseModel](Protocol):
    """One platform's opinion of how much each topic is trending.

    `per_topic[i]` holds that platform's metrics within topic `i`, and is
    never empty: the coordinator passes only topics where this platform is
    present. `previous[i]` is the same topic's sub-score from the most recent
    prior run, or None if it has no history for this platform.

    The return value is normalised **within this platform** across the topics
    given, which is what makes different platforms' scores comparable.
    """

    platform: str

    def score(
        self, per_topic: list[list[M]], previous: list[float | None]
    ) -> list[float]: ...
```

Create `zeitgeist/analysis/scorers/lemmy.py`:

```python
"""Lemmy trend scoring: velocity, spread, and movement against last run.

Pure Python on purpose: reproducible and unit-testable, which an LLM's
numeric judgment is not.
"""

from datetime import datetime

from zeitgeist.analysis.scorers.base import ScoreWeights, normalise
from zeitgeist.models import LemmyMetrics

MIN_AGE_HOURS = 0.5


class LemmyScorer:
    platform = "lemmy"

    def __init__(self, weights: ScoreWeights, now: datetime) -> None:
        self._weights = weights
        self._now = now

    def score(
        self, per_topic: list[list[LemmyMetrics]], previous: list[float | None]
    ) -> list[float]:
        weights = self._weights

        raw_uv = [self._mean_velocity(g, "score") for g in per_topic]
        raw_cv = [self._mean_velocity(g, "comment_count") for g in per_topic]
        raw_cs = [float(len({m.channel for m in g})) for g in per_topic]

        uv, cv, cs = normalise(raw_uv), normalise(raw_cv), normalise(raw_cs)

        base_total = (
            weights.upvote_velocity + weights.comment_velocity + weights.channel_spread
        )
        bases = [
            (
                weights.upvote_velocity * uv[i]
                + weights.comment_velocity * cv[i]
                + weights.channel_spread * cs[i]
            )
            / base_total
            if base_total
            else 0.0
            for i in range(len(per_topic))
        ]

        # Defaulting to the topic's own base, not 0.0: an unseen topic has
        # not risen, so its delta must be zero rather than full marks.
        raw_delta = [
            bases[i] - (previous[i] if previous[i] is not None else bases[i])
            for i in range(len(per_topic))
        ]
        delta = normalise(raw_delta)

        w = weights.rank_delta
        return [(1.0 - w) * bases[i] + w * delta[i] for i in range(len(per_topic))]

    def _mean_velocity(self, group: list[LemmyMetrics], attribute: str) -> float:
        values = []
        for metrics in group:
            hours = (self._now - metrics.created_at).total_seconds() / 3600.0
            values.append(getattr(metrics, attribute) / max(hours, MIN_AGE_HOURS))
        return sum(values) / len(values)
```

Create `zeitgeist/analysis/scorers/reddit.py` with the identical algorithm over `RedditMetrics` — same imports, `platform = "reddit"`, `class RedditScorer`, and the same `score` and `_mean_velocity` bodies with `RedditMetrics` in the annotations.

Create `zeitgeist/analysis/scorers/__init__.py`:

```python
"""Scorer registry. A new platform is a new file plus one entry here.

Parallel to `sources/__init__.py`'s BUILDERS: a platform needs an entry in
both, and `tests/test_scorers_registry.py` guards them against drifting.
"""

from collections.abc import Callable
from datetime import datetime

from zeitgeist.analysis.scorers.base import ScoreWeights, TrendScorer
from zeitgeist.analysis.scorers.lemmy import LemmyScorer
from zeitgeist.analysis.scorers.reddit import RedditScorer

ScorerBuilder = Callable[[ScoreWeights, datetime], TrendScorer]

SCORERS: dict[str, ScorerBuilder] = {
    "lemmy": LemmyScorer,
    "reddit": RedditScorer,
}


def build_scorer(
    platform: str, weights: ScoreWeights, now: datetime
) -> TrendScorer:
    """Raises KeyError for an unregistered platform — a drift bug, not input."""
    return SCORERS[platform](weights, now)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_scorers_lemmy.py tests/test_scorers_reddit.py -v && uv run ty check
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add zeitgeist/analysis/scorers tests/test_scorers_lemmy.py tests/test_scorers_reddit.py
git commit -m "Add per-platform scorer registry with Lemmy and Reddit"
```

---

### Task 6: `score.py` becomes the coordinator

**Files:**
- Modify: `zeitgeist/analysis/score.py`, `zeitgeist/analysis/sentiment.py`, `zeitgeist/config.py`
- Test: `tests/test_analysis_score.py`, `tests/test_analysis_sentiment.py`

**Interfaces:**
- Consumes: `build_scorer`, `ScoreWeights`, `normalise` from Task 5.
- Produces: `score_topics(topics: list[Topic], items: list[Item], now: datetime, previous: dict[str, dict[str, float]], weights: ScoreWeights | None = None) -> list[Topic]`. `previous` is keyed `platform -> slugify(label) -> sub_score`. `score_components` carries one entry per contributing platform plus `"corroboration"`.
- `sentiment._build_prompt` now reports the platform count.

- [ ] **Step 1: Write the failing tests**

Rewrite `tests/test_analysis_score.py`:

```python
def test_corroboration_makes_two_platforms_beat_one_stronger_platform():
    """`solo` outscores `corroborated` on the mean of their sub-scores
    (0.75 vs 0.72375); only the two-platform multiplier reverses that. Both
    values are hand-derived in the builder's docstring, so zeroing the bonus
    or dropping the `* bonus` from trend_score fails here.
    """
    topics, items = _two_topics_one_corroborated()

    scored = score_topics(topics, items, NOW, previous={}, weights=ScoreWeights())

    by_id = {t.id: t for t in scored}
    assert by_id["solo"].trend_score == pytest.approx(0.75)
    assert by_id["corroborated"].trend_score == pytest.approx(0.9046875)
    assert by_id["corroborated"].trend_score > by_id["solo"].trend_score


def test_history_is_looked_up_by_platform_then_label_slug():
    """Hand-derived: bases are [0.7, 0.63, 0.0]. `steady`'s history equals
    its own base, so it has not risen (raw delta 0.0); `rising` climbed from
    0.0 (raw delta 0.63). Normalised deltas are [0.0, 1.0, 0.0] and the
    scores are 0.525 / 0.7225 / 0.0, so `rising` overtakes `steady`.

    This is the only test joining Store.previous_sub_scores to the scorers'
    `previous` list. A lookup keyed on the raw label, on topic.id, or without
    the platform level finds nothing: every delta is then zero and `steady`
    stays ahead at 0.525 against 0.4725.
    """
    topics, items = _history_case()
    previous = {"lemmy": {"steady-eddie": 0.7, "rising-star": 0.0}}

    scored = {
        t.id: t
        for t in score_topics(topics, items, NOW, previous, weights=ScoreWeights())
    }

    assert scored["rising"].trend_score == pytest.approx(0.7225)
    assert scored["steady"].trend_score == pytest.approx(0.525)
    assert scored["rising"].trend_score > scored["steady"].trend_score


def test_scoring_precedes_the_content_bearing_filter():
    """A corroboration-only platform sees six topics, five of which are
    dropped for having no content-bearing source. The survivor's sub-score
    must be computed against all six, not against itself alone.

    Written to fail against the reversed ordering: filtering first leaves the
    scorer a single value, and min-max over one value is 0.0, so the
    corroborating platform would drag the topic DOWN instead of lifting it.
    """
    topics, items = _one_survivor_among_six()

    scored = score_topics(topics, items, NOW, previous={}, weights=ScoreWeights())

    assert len(scored) == 1
    assert scored[0].score_components["wikipedia"] > 0.0


def test_topics_with_no_content_bearing_platform_are_dropped():
    topics, items = _wikipedia_only_topic()

    scored = score_topics(topics, items, NOW, previous={}, weights=ScoreWeights())

    assert scored == []


def test_a_platform_seen_in_one_topic_is_excluded_from_the_mean():
    """Its min-max carries no information, so it must not enter the average —
    but it still counts toward the corroboration multiplier."""
    topics, items = _single_contribution_case()

    scored = score_topics(topics, items, NOW, previous={}, weights=ScoreWeights())

    target = next(t for t in scored if t.id == "solo-corroborated")
    assert "wikipedia" not in target.score_components
    assert target.score_components["corroboration"] == 1.25


def test_score_components_name_every_contributing_platform():
    """Store.record_topics turns these keys into topic_scores rows, so a
    platform missing here loses its cross-run history and its rank-delta
    goes inert. Exact set, not a superset: dropping the corroborating
    platform is the mutation that matters, and a superset check would let
    it through.
    """
    topics, items = _two_topics_one_corroborated()

    scored = score_topics(topics, items, NOW, previous={}, weights=ScoreWeights())

    corroborated = next(t for t in scored if t.id == "corroborated")
    assert set(corroborated.score_components) == {
        "lemmy",
        "wikipedia",
        "corroboration",
    }


def test_single_platform_run_matches_phase_one_ranking():
    """Equivalence gate: with one content-bearing source and no corroboration,
    the coordinator must rank identically to the pre-refactor scorer. Compares
    ORDER, not absolute values, since the bonus multiplies uniformly by 1.0."""
    topics, items = _lemmy_only_run()

    scored = score_topics(topics, items, NOW, previous={}, weights=ScoreWeights())

    order = [t.id for t in sorted(scored, key=lambda t: -t.trend_score)]
    assert order == ["fast", "medium", "slow"]
```

**This task changes the sentiment prompt, which breaks the test Task 3 added.** `test_prompt_reports_the_item_count` asserts `"Appears in 3 items."`, and the new prompt renders `"Appears in 3 items across 1 platform(s)."` — the substring with the full stop no longer occurs. Replace it in `tests/test_analysis_sentiment.py`:

```python
def test_prompt_reports_the_item_and_platform_counts():
    """The platform count comes from score_components minus the
    corroboration multiplier, which is not a platform: counting it would
    report three platforms for a two-platform topic.
    """
    topic = Topic(
        id="t",
        label="T",
        summary="S",
        item_ids=["a", "b", "c"],
        score_components={"lemmy": 0.5, "wikipedia": 0.4, "corroboration": 1.25},
    )

    prompt = _build_prompt(topic)

    assert "Appears in 3 items across 2 platform(s)." in prompt


def test_an_unscored_topic_reports_one_platform_rather_than_zero():
    """judge_topics is reachable with empty score_components, and
    "across 0 platform(s)" would be nonsense to the model.
    """
    topic = Topic(id="t", label="T", summary="S", item_ids=["a"])

    assert "Appears in 1 items across 1 platform(s)." in _build_prompt(topic)
```

The five builders, as module-level helpers. Each constructs real `Item`s with real metrics — no mocks:

```python
import pytest
from datetime import UTC, date, datetime

from zeitgeist.analysis.score import score_topics
from zeitgeist.analysis.scorers.base import ScoreWeights
from zeitgeist.models import Item, LemmyMetrics, Topic, WikipediaMetrics

NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)
DAY = date(2026, 8, 20)


def _lemmy(source_id: str, score: int, channel: str, age_hours: float) -> Item:
    return Item(
        source_id=source_id,
        title=f"Post {source_id}",
        permalink=f"https://lemmy.world/post/{source_id}",
        fetched_at=NOW,
        metrics=LemmyMetrics(
            score=score,
            comment_count=score // 10,
            channel=channel,
            created_at=datetime.fromtimestamp(
                NOW.timestamp() - age_hours * 3600, tz=UTC
            ),
        ),
    )


def _wiki(source_id: str, rank: int) -> Item:
    return Item(
        source_id=source_id,
        title=f"Article {source_id}",
        permalink=f"https://en.wikipedia.org/wiki/{source_id}",
        fetched_at=NOW,
        metrics=WikipediaMetrics(views=100_000 - rank, rank=rank, measured_on=DAY),
    )


def _topic(topic_id: str, item_ids: list[str]) -> Topic:
    return Topic(
        id=topic_id, label=topic_id.title(), summary="", item_ids=item_ids
    )


def _two_topics_one_corroborated() -> tuple[list[Topic], list[Item]]:
    """Hand-derived so the corroboration bonus is load-bearing.

    Lemmy velocities normalise to [1.0, 0.9, 0.0] and the two leading topics
    each span two channels, so bases are [1.0, 0.93, 0.0] and — with no
    history, so the delta term contributes nothing — the lemmy sub-scores
    are 0.75 * base:
        solo          0.75
        corroborated  0.6975
    Wikipedia ranks 3 and 800 normalise to [1.0, 0.0], so corroborated's
    wikipedia sub-score is 0.75 and its mean is 0.72375 — BELOW solo's 0.75.
    Only the x1.25 bonus (0.9046875) puts it ahead, which is what makes a
    zeroed bonus fail rather than merely shrink the gap.
    """
    items = [
        _lemmy("s1", score=1000, channel="a@h", age_hours=2),
        _lemmy("s2", score=1000, channel="b@h", age_hours=2),
        _lemmy("c1", score=910, channel="c@h", age_hours=2),
        _lemmy("c2", score=910, channel="d@h", age_hours=2),
        _lemmy("f1", score=100, channel="e@h", age_hours=2),
        _wiki("w1", rank=3),
        _wiki("w2", rank=800),
    ]
    topics = [
        _topic("solo", ["s1", "s2"]),
        _topic("corroborated", ["c1", "c2", "w1"]),
        _topic("filler", ["f1", "w2"]),
    ]
    return topics, items


def _history_case() -> tuple[list[Topic], list[Item]]:
    """Three Lemmy-only topics whose velocities normalise to [1.0, 0.9, 0.0],
    so bases are [0.7, 0.63, 0.0]. Labels are two words on purpose: the
    lookup key slugify("Rising Star") == "rising-star" differs from both the
    raw label and the topic id, so a lookup on either finds nothing.
    """
    items = [
        _lemmy("a", score=1000, channel="a@h", age_hours=2),
        _lemmy("b", score=910, channel="b@h", age_hours=2),
        _lemmy("c", score=100, channel="c@h", age_hours=2),
    ]
    topics = [
        Topic(id="steady", label="Steady Eddie", summary="", item_ids=["a"]),
        Topic(id="rising", label="Rising Star", summary="", item_ids=["b"]),
        Topic(id="quiet", label="Quiet One", summary="", item_ids=["c"]),
    ]
    return topics, items


def _one_survivor_among_six() -> tuple[list[Topic], list[Item]]:
    """One content-bearing topic that Wikipedia also saw, plus five
    Wikipedia-only topics that the filter drops. The survivor's Wikipedia
    sub-score must be computed against all six.
    """
    items = [_lemmy("L", score=500, channel="a@h", age_hours=2), _wiki("w0", rank=2)]
    topics = [_topic("survivor", ["L", "w0"])]
    for n in range(1, 6):
        items.append(_wiki(f"w{n}", rank=100 * n))
        topics.append(_topic(f"dropped-{n}", [f"w{n}"]))
    return topics, items


def _wikipedia_only_topic() -> tuple[list[Topic], list[Item]]:
    items = [_wiki("w1", rank=1), _wiki("w2", rank=2)]
    return [_topic("wiki-a", ["w1"]), _topic("wiki-b", ["w2"])], items


def _single_contribution_case() -> tuple[list[Topic], list[Item]]:
    """Wikipedia appears in exactly one topic, so it cannot be min-max
    normalised — but its presence must still earn the corroboration bonus.
    """
    items = [
        _lemmy("l1", score=700, channel="a@h", age_hours=2),
        _lemmy("l2", score=300, channel="b@h", age_hours=2),
        _wiki("w1", rank=5),
    ]
    topics = [
        _topic("solo-corroborated", ["l1", "w1"]),
        _topic("plain", ["l2"]),
    ]
    return topics, items


def _lemmy_only_run() -> tuple[list[Topic], list[Item]]:
    items = [
        _lemmy("fast", score=1000, channel="a@h", age_hours=1),
        _lemmy("medium", score=300, channel="b@h", age_hours=3),
        _lemmy("slow", score=20, channel="c@h", age_hours=20),
    ]
    topics = [
        _topic("fast", ["fast"]),
        _topic("medium", ["medium"]),
        _topic("slow", ["slow"]),
    ]
    return topics, items
```

Note `_wiki` references `WikipediaMetrics`, which does not exist until Task 9. Mark the five tests that use it with `@pytest.mark.xfail(reason="WikipediaMetrics arrives in Task 9", strict=True)` — `strict=True` so they fail loudly if they start passing early — and remove those markers in Task 9. `test_single_platform_run_matches_phase_one_ranking` needs no marker.

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_analysis_score.py -v
```

Expected: FAIL — `score_topics` still takes a flat `previous_scores` dict.

- [ ] **Step 3: Write the implementation**

Replace `zeitgeist/analysis/score.py` entirely:

```python
"""Trend scoring coordinator.

Each platform scores its own contribution to a topic, normalised within that
platform; this module dispatches to those scorers and combines what they
return. Keeping the arithmetic here pure — no I/O, no LLM — is deliberate:
it is reproducible and unit-testable, which an LLM's numeric judgment is not.
"""

from datetime import datetime

from zeitgeist.analysis.consolidate import slugify
from zeitgeist.analysis.scorers import build_scorer
from zeitgeist.analysis.scorers.base import ScoreWeights
from zeitgeist.models import Item, Topic

__all__ = ["ScoreWeights", "score_topics"]

# A platform contributing to fewer topics than this cannot be min-max
# normalised: the range is degenerate. Its presence still counts toward
# corroboration, but it contributes no number to the mean.
MIN_TOPICS_TO_RANK = 2


def score_topics(
    topics: list[Topic],
    items: list[Item],
    now: datetime,
    previous: dict[str, dict[str, float]],
    weights: ScoreWeights | None = None,
) -> list[Topic]:
    """Attach a trend score and its component breakdown to each topic.

    `previous` is keyed platform -> slugify(label) -> sub-score (see
    ``Store.previous_sub_scores``), not the raw label, so a topic relabelled
    with different case or punctuation across runs still finds its history.
    """
    weights = weights or ScoreWeights()
    by_id = {item.source_id: item for item in items}

    live: list[tuple[Topic, list[Item]]] = []
    for topic in topics:
        matched = [by_id[iid] for iid in topic.item_ids if iid in by_id]
        if matched:
            live.append((topic, matched))

    if not live:
        return []

    platforms = sorted({item.platform for _, group in live for item in group})

    # Step 2 of the spec's ordering: score across ALL live topics, before the
    # content-bearing filter runs. Filtering first would hand a scorer a single
    # value, and min-max over one value is 0.0 — so a corroborating platform
    # would penalise the topic it is meant to lift.
    presence: dict[str, list[bool]] = {}
    scores: dict[str, list[float | None]] = {}

    for platform in platforms:
        groups = [
            [item.metrics for item in group if item.platform == platform]
            for _, group in live
        ]
        presence[platform] = [bool(g) for g in groups]
        scores[platform] = [None] * len(live)

        present = [i for i, g in enumerate(groups) if g]
        if len(present) < MIN_TOPICS_TO_RANK:
            continue

        scorer = build_scorer(platform, weights, now)
        values = scorer.score(
            per_topic=[groups[i] for i in present],
            previous=[
                previous.get(platform, {}).get(slugify(live[i][0].label))
                for i in present
            ],
        )
        for position, index in enumerate(present):
            scores[platform][index] = values[position]

    scored: list[Topic] = []
    for index, (topic, group) in enumerate(live):
        if not any(item.content_bearing for item in group):
            continue

        contributing = [p for p in platforms if presence[p][index]]
        ranked = {
            p: scores[p][index]
            for p in contributing
            if scores[p][index] is not None
        }
        mean = sum(ranked.values()) / len(ranked) if ranked else 0.0
        bonus = 1.0 + weights.corroboration_bonus * (len(contributing) - 1)

        components: dict[str, float] = dict(ranked)
        components["corroboration"] = bonus

        scored.append(
            topic.model_copy(
                update={"trend_score": mean * bonus, "score_components": components}
            )
        )

    return scored
```

In `zeitgeist/analysis/sentiment.py`, extend the prompt. `judge_topics` must pass the platform count through — read `score_components` for platform keys:

```python
def _build_prompt(topic: Topic) -> str:
    platforms = [key for key in topic.score_components if key != "corroboration"]
    return (
        f"Topic: {topic.label}\n"
        f"Summary: {topic.summary}\n"
        f"Appears in {len(topic.item_ids)} items across "
        f"{max(len(platforms), 1)} platform(s).\n\n"
        "Judge this topic's sentiment and meme potential."
    )
```

In `zeitgeist/config.py`, change the `ScoreWeights` import path if it is imported there; otherwise no change.

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_analysis_score.py -v
```

Expected: PASS, with five `xfail` entries pending Task 9.

- [ ] **Step 5: Commit**

```bash
git add zeitgeist/analysis tests/test_analysis_score.py
git commit -m "Reduce score.py to a per-platform scoring coordinator"
```

---

### Task 7: Registry drift guard

**Files:**
- Create: `tests/test_scorers_registry.py`

**Interfaces:**
- Consumes: `SCORERS` from Task 5, `BUILDERS` and `KNOWN_SOURCES` from the existing source registry.

- [ ] **Step 1: Write the failing test**

```python
"""Two registries can fall out of step. This is the guard, mirroring the
existing BUILDERS/KNOWN_SOURCES check in tests/test_sources_composite.py.
"""

from typing import get_args

from zeitgeist.analysis.scorers import SCORERS
from zeitgeist.config import KNOWN_SOURCES
from zeitgeist.models import Metrics
from zeitgeist.sources import BUILDERS


def _union_platforms() -> set[str]:
    """Every `platform` literal in the Metrics discriminated union."""
    # Metrics is Annotated[A | B | ..., Field(...)]; get_args()[0] is the union.
    union = get_args(Metrics)[0]
    return {
        get_args(member.model_fields["platform"].annotation)[0]
        for member in get_args(union)
    }


def test_every_metrics_platform_has_a_scorer():
    assert _union_platforms() == set(SCORERS)


def test_every_source_has_a_scorer():
    assert set(BUILDERS) <= set(SCORERS)


def test_known_sources_matches_the_source_registry():
    assert set(KNOWN_SOURCES) == set(BUILDERS)
```

- [ ] **Step 2: Run test to verify it passes**

```bash
uv run pytest tests/test_scorers_registry.py -v
```

Expected: PASS. If `_union_platforms` raises, adjust the introspection to match the actual `Metrics` definition from Task 1 rather than weakening the assertion.

- [ ] **Step 3: Run the whole gate**

```bash
uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest
```

Expected: all four PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/test_scorers_registry.py
git commit -m "Guard the scorer and source registries against drift"
```

---

## Phase 3 — Per-platform score history

### Task 8: `topic_scores` table and the schema guard

**Files:**
- Modify: `zeitgeist/store.py`, `zeitgeist/pipeline.py`
- Test: `tests/test_store.py`

**Interfaces:**
- Consumes: `score_topics`'s `previous` shape from Task 6.
- Produces: `Store.record_topics(run_id, topics)` also writing `topic_scores`; `Store.previous_sub_scores(exclude_run_id: str) -> dict[str, dict[str, float]]`; `StoreSchemaError`; `SCHEMA_VERSION = 2`. `Store.previous_scores` is **deleted**.

- [ ] **Step 1: Write the failing tests**

```python
import pytest

from zeitgeist.store import SCHEMA_VERSION, Store, StoreSchemaError


def test_previous_sub_scores_are_keyed_by_platform_then_label_slug(tmp_path):
    store = Store(tmp_path / "z.db")
    store.init_schema()
    store.start_run("r1")
    store.record_topics("r1", [_topic("Shelter Dog Adoption", {"lemmy": 0.7})])
    store.finish_run("r1", status="ok", item_count=1)
    store.start_run("r2")

    previous = store.previous_sub_scores("r2")

    assert previous == {"lemmy": {"shelter-dog-adoption": 0.7}}


def test_sub_scores_from_different_platforms_do_not_collide(tmp_path):
    """Both platforms saw the same topic; each must keep its own number.
    A schema keyed only on (run_id, label) would silently lose one."""
    store = Store(tmp_path / "z.db")
    store.init_schema()
    store.start_run("r1")
    store.record_topics("r1", [_topic("Cats", {"lemmy": 0.4, "wikipedia": 0.9})])
    store.finish_run("r1", status="ok", item_count=1)
    store.start_run("r2")

    previous = store.previous_sub_scores("r2")

    assert previous["lemmy"]["cats"] == 0.4
    assert previous["wikipedia"]["cats"] == 0.9


def test_corroboration_is_not_persisted_as_a_platform(tmp_path):
    """score_components carries a 'corroboration' key that is a multiplier,
    not a platform sub-score. Persisting it would make the next run's
    rank-delta compare a score against a multiplier."""
    store = Store(tmp_path / "z.db")
    store.init_schema()
    store.start_run("r1")
    store.record_topics(
        "r1", [_topic("Cats", {"lemmy": 0.4, "corroboration": 1.25})]
    )
    store.finish_run("r1", status="ok", item_count=1)
    store.start_run("r2")

    previous = store.previous_sub_scores("r2")

    assert "corroboration" not in previous


def test_a_stale_database_is_rejected_with_an_actionable_message(tmp_path):
    """CREATE TABLE IF NOT EXISTS accepts an old schema silently and fails
    later with something cryptic. This turns it into a startup failure."""
    path = tmp_path / "z.db"
    import sqlite3

    conn = sqlite3.connect(path)
    conn.executescript("CREATE TABLE runs (run_id TEXT PRIMARY KEY);")
    conn.execute("PRAGMA user_version = 1")
    conn.commit()
    conn.close()

    with pytest.raises(StoreSchemaError, match="Delete it and re-run"):
        Store(path).init_schema()


def test_a_fresh_database_is_stamped_with_the_current_version(tmp_path):
    store = Store(tmp_path / "z.db")
    store.init_schema()

    version = store._conn.execute("PRAGMA user_version").fetchone()[0]
    assert version == SCHEMA_VERSION
```

Write `_topic(label, components)` as a module-level helper building a `Topic` with `item_ids=["x"]` and the given `score_components`.

Deleting `previous_scores` orphans five existing tests in this file — `test_previous_scores_is_empty_on_first_run`, `test_most_recent_prior_run_wins`, `test_each_label_tracks_its_own_history`, `test_current_run_is_excluded_from_its_own_history` and `test_previous_scores_ignores_the_excluded_runs_own_history_in_the_max`. They cover the correlated `MAX(started_at)` subquery, which `previous_sub_scores` inherits and extends with a second correlation on `platform`. **Port them rather than dropping them** — every test above uses a single prior run, so without these the subquery has no coverage at all and dropping `MAX(...)`, dropping `s2.platform = s.platform`, or dropping the inner `s2.run_id != ?` all pass:

```python
def test_previous_sub_scores_is_empty_on_the_first_run(tmp_path):
    store = Store(tmp_path / "z.db")
    store.init_schema()

    assert store.previous_sub_scores("r1") == {}


def test_the_most_recent_prior_run_wins(tmp_path):
    """Guards MAX(started_at): without it the lookup returns whichever row
    SQLite happened to visit first, so rank-delta compares against an
    arbitrarily old score.
    """
    store = Store(tmp_path / "z.db")
    store.init_schema()
    for run_id, sub_score in [("r1", 0.2), ("r2", 0.5), ("r3", 0.9)]:
        store.start_run(run_id)
        store.record_topics(run_id, [_topic("Cats", {"lemmy": sub_score})])
        store.finish_run(run_id, status="ok", item_count=1)

    assert store.previous_sub_scores("r4") == {"lemmy": {"cats": 0.9}}


def test_each_label_and_platform_tracks_its_own_history(tmp_path):
    """Guards both correlations: a naive MAX over all runs would give every
    label the newest run's score, and dropping `s2.platform = s.platform`
    would let one platform's newer row hide another platform's older one.
    """
    store = Store(tmp_path / "z.db")
    store.init_schema()
    store.start_run("r1")
    store.record_topics(
        "r1",
        [
            _topic("Cats", {"lemmy": 0.2, "wikipedia": 0.6}),
            _topic("Dogs", {"lemmy": 0.9}),
        ],
    )
    store.finish_run("r1", status="ok", item_count=2)

    store.start_run("r2")
    store.record_topics("r2", [_topic("Cats", {"lemmy": 0.7})])
    store.finish_run("r2", status="ok", item_count=1)

    assert store.previous_sub_scores("r3") == {
        "lemmy": {"cats": 0.7, "dogs": 0.9},
        "wikipedia": {"cats": 0.6},
    }


def test_the_excluded_runs_own_rows_do_not_hide_the_older_run(tmp_path):
    """Guards the subquery's own `s2.run_id != ?`. Without it the excluded
    run — the newest for this label and platform — sets MAX(started_at) to a
    timestamp no included row can match, dropping the label from the result
    entirely instead of falling back to the older run's score.
    """
    store = Store(tmp_path / "z.db")
    store.init_schema()
    store.start_run("r1")
    store.record_topics("r1", [_topic("Cats", {"lemmy": 0.2})])
    store.finish_run("r1", status="ok", item_count=1)

    store.start_run("r2")
    store.record_topics("r2", [_topic("Cats", {"lemmy": 0.99})])
    store.finish_run("r2", status="ok", item_count=1)

    assert store.previous_sub_scores("r2") == {"lemmy": {"cats": 0.2}}
```

Also port `test_relabelled_topic_is_still_matched_across_runs` — it pins the `slugify` normalisation that `previous_sub_scores` still depends on. Change its assertion to read through the platform level.

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_store.py -v
```

Expected: FAIL with `ImportError: cannot import name 'StoreSchemaError'`.

- [ ] **Step 3: Write the implementation**

In `zeitgeist/store.py`:

```python
SCHEMA_VERSION = 2

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id      TEXT PRIMARY KEY,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    status      TEXT,
    item_count  INTEGER
);

CREATE TABLE IF NOT EXISTS topics (
    run_id      TEXT NOT NULL,
    label       TEXT NOT NULL,
    trend_score REAL NOT NULL,
    created_at  TEXT NOT NULL,
    PRIMARY KEY (run_id, label)
);

CREATE TABLE IF NOT EXISTS topic_scores (
    run_id    TEXT NOT NULL,
    label     TEXT NOT NULL,
    platform  TEXT NOT NULL,
    sub_score REAL NOT NULL,
    PRIMARY KEY (run_id, label, platform)
);

CREATE INDEX IF NOT EXISTS idx_topics_label ON topics (label);
CREATE INDEX IF NOT EXISTS idx_topic_scores_label ON topic_scores (label);
"""

# score_components carries this alongside the real platform sub-scores. It is
# a multiplier, not a platform's opinion, so it must never reach topic_scores.
NON_PLATFORM_COMPONENTS = frozenset({"corroboration"})


class StoreSchemaError(RuntimeError):
    """The database on disk was written by a different schema version."""


class Store:
    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._path)

    def init_schema(self) -> None:
        existing = self._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='runs'"
        ).fetchone()
        if existing is None:
            self._conn.executescript(SCHEMA)
            self._conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            self._conn.commit()
            return

        version = self._conn.execute("PRAGMA user_version").fetchone()[0]
        if version != SCHEMA_VERSION:
            raise StoreSchemaError(
                f"{self._path} was written by schema version {version}; this "
                f"build expects {SCHEMA_VERSION}. Delete it and re-run — "
                "cross-run trend history will be lost, nothing else."
            )
```

Extend `record_topics` and replace `previous_scores`:

```python
    def record_topics(self, run_id: str, topics: list[Topic]) -> None:
        # Keyed on slugify(label), not the raw label: labels are free text
        # the model regenerates every run, so "Shelter Dog Adoption" and
        # "shelter dog adoption" must be treated as the same topic across
        # runs or rank_delta never finds a match against real data. This
        # fixes case and punctuation drift only, not wording drift — a
        # genuinely reworded label ("Rescue Dog Adoptions") still misses.
        self._conn.executemany(
            "INSERT OR REPLACE INTO topics "
            "(run_id, label, trend_score, created_at) VALUES (?, ?, ?, ?)",
            [(run_id, slugify(t.label), t.trend_score, _now()) for t in topics],
        )
        self._conn.executemany(
            "INSERT OR REPLACE INTO topic_scores "
            "(run_id, label, platform, sub_score) VALUES (?, ?, ?, ?)",
            [
                (run_id, slugify(topic.label), platform, value)
                for topic in topics
                for platform, value in topic.score_components.items()
                if platform not in NON_PLATFORM_COMPONENTS
            ],
        )
        self._conn.commit()

    def previous_sub_scores(self, exclude_run_id: str) -> dict[str, dict[str, float]]:
        """Each platform's sub-score per label-slug, from the most recent
        prior run containing that platform/label pair. Keys are
        slugify(label) (see record_topics); callers must look up with the
        same normalisation, which score_topics does.
        """
        rows = self._conn.execute(
            """
            SELECT s.platform, s.label, s.sub_score
            FROM topic_scores s
            JOIN runs r ON r.run_id = s.run_id
            WHERE s.run_id != ?
              AND r.started_at = (
                  SELECT MAX(r2.started_at)
                  FROM topic_scores s2
                  JOIN runs r2 ON r2.run_id = s2.run_id
                  WHERE s2.label = s.label
                    AND s2.platform = s.platform
                    AND s2.run_id != ?
              )
            """,
            (exclude_run_id, exclude_run_id),
        ).fetchall()

        previous: dict[str, dict[str, float]] = {}
        for platform, label, sub_score in rows:
            previous.setdefault(platform, {})[label] = sub_score
        return previous
```

Delete the old `previous_scores` method entirely.

In `zeitgeist/pipeline.py:73-75`:

```python
        topics = score_topics(
            topics, items, datetime.now(UTC), store.previous_sub_scores(run_id)
        )
```

- [ ] **Step 4: Run the whole gate**

```bash
uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest
```

Expected: all four PASS.

- [ ] **Step 5: Commit**

```bash
git add zeitgeist/store.py zeitgeist/pipeline.py tests/test_store.py
git commit -m "Persist per-platform sub-scores and guard the schema version"
```

---

## Phase 4 — Wikimedia

### Task 9: `WikipediaMetrics` and the Wikipedia scorer

**Files:**
- Modify: `zeitgeist/models.py`, `zeitgeist/analysis/scorers/__init__.py`
- Create: `zeitgeist/analysis/scorers/wikipedia.py`
- Test: `tests/test_scorers_wikipedia.py`, `tests/test_analysis_score.py` (remove xfail markers)

**Interfaces:**
- Consumes: `ScoreWeights`, `normalise`, `TrendScorer` from Task 5.
- Produces: `WikipediaMetrics` with `views: int`, `rank: int`, `date: datetime.date`, `platform: Literal["wikipedia"]`, `content_bearing: ClassVar[bool] = False`, `context` returning `f"{views:,} views"`. `WikipediaScorer` registered under `"wikipedia"`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_scorers_wikipedia.py`:

```python
from datetime import UTC, date, datetime

from zeitgeist.analysis.scorers import build_scorer
from zeitgeist.analysis.scorers.base import ScoreWeights
from zeitgeist.models import WikipediaMetrics

NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)
DAY = date(2026, 8, 20)


def _m(rank: int, views: int = 1000) -> WikipediaMetrics:
    return WikipediaMetrics(views=views, rank=rank, measured_on=DAY)


def test_a_better_rank_scores_higher():
    """Rank 1 beats rank 500. Discriminates the negation from forgetting it,
    which would invert the entire ranking."""
    scorer = build_scorer("wikipedia", ScoreWeights(), NOW)

    scores = scorer.score(per_topic=[[_m(rank=1)], [_m(rank=500)]], previous=[None, None])

    assert scores[0] > scores[1]


def test_a_topic_uses_its_best_ranked_article():
    """min(), not mean or first: a topic containing one rank-2 article and
    one rank-900 article is trending on the strength of the rank-2 one."""
    scorer = build_scorer("wikipedia", ScoreWeights(), NOW)

    scores = scorer.score(
        per_topic=[[_m(rank=900), _m(rank=2)], [_m(rank=400)]],
        previous=[None, None],
    )

    assert scores[0] > scores[1]


def test_a_perennial_topic_does_not_score_as_rising():
    """Two topics at identical ranks; one held that position last run, the
    other is new. This is what neutralises pages like Google that sit in the
    top ten every day, so the source does not need to denylist them."""
    scorer = build_scorer("wikipedia", ScoreWeights(), NOW)

    scores = scorer.score(
        per_topic=[[_m(rank=5)], [_m(rank=5)]],
        previous=[1.0, None],
    )

    assert scores[1] > scores[0]


def test_scores_stay_within_the_unit_interval():
    scorer = build_scorer("wikipedia", ScoreWeights(), NOW)

    scores = scorer.score(
        per_topic=[[_m(rank=1)], [_m(rank=1000)], [_m(rank=37)]],
        previous=[0.9, None, 0.1],
    )

    assert all(0.0 <= s <= 1.0 for s in scores)


def test_context_reports_views():
    assert _m(rank=4, views=411486).context == "411,486 views"
```

Extend the field-set guard added in Task 1 with the third model — `tests/test_models.py`'s parametrize list gains:

```python
        (WikipediaMetrics, {"platform", "views", "rank", "measured_on"}),
```

`content_bearing` needs no dedicated assertion: Task 6's `test_topics_with_no_content_bearing_platform_are_dropped` and `test_scoring_precedes_the_content_bearing_filter` both fail immediately if the flag flips, and they test the behaviour rather than the constant.

Then remove the five `pytest.mark.xfail` markers added in Task 6.

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_scorers_wikipedia.py -v
```

Expected: FAIL with `ImportError: cannot import name 'WikipediaMetrics'`.

- [ ] **Step 3: Write the implementation**

In `zeitgeist/models.py`, add `date` to the datetime import and add:

```python
class WikipediaMetrics(BaseModel):
    """Attention as Wikimedia pageviews report it.

    No comments, no communities, and no per-item creation date — an article
    is years old while its spike is one day. `date` is the day the measurement
    covers, which is the only temporal fact this platform actually supplies.
    """

    model_config = STRICT

    platform: Literal["wikipedia"] = "wikipedia"
    # No body text, so a Wikipedia-only topic gives the sentiment stage
    # nothing to judge. The coordinator drops such topics.
    content_bearing: ClassVar[bool] = False

    views: int
    rank: int
    measured_on: date

    @property
    def context(self) -> str:
        return f"{self.views:,} views"
```

Extend the union:

```python
Metrics = Annotated[
    LemmyMetrics | RedditMetrics | WikipediaMetrics,
    Field(discriminator="platform"),
]
```

Create `zeitgeist/analysis/scorers/wikipedia.py`:

```python
"""Wikipedia trend scoring: position, and movement against last run.

Pageviews carry no comments, no channel, and no per-item age, so velocity is
undefined here. Position and delta are the whole signal.
"""

from datetime import datetime

from zeitgeist.analysis.scorers.base import ScoreWeights, normalise
from zeitgeist.models import WikipediaMetrics


class WikipediaScorer:
    platform = "wikipedia"

    def __init__(self, weights: ScoreWeights, now: datetime) -> None:
        self._weights = weights

    def score(
        self, per_topic: list[list[WikipediaMetrics]], previous: list[float | None]
    ) -> list[float]:
        # Negated rather than scaled against a total: normalise establishes
        # the range from what is present, so the maths does not depend on how
        # many articles the run kept or how many filtering removed.
        raw = [-float(min(m.rank for m in group)) for group in per_topic]
        bases = normalise(raw)

        # Defaulting to the topic's own base, not 0.0: an unseen topic has
        # not risen, so its delta must be zero rather than full marks.
        raw_delta = [
            bases[i] - (previous[i] if previous[i] is not None else bases[i])
            for i in range(len(per_topic))
        ]
        delta = normalise(raw_delta)

        w = self._weights.rank_delta
        return [(1.0 - w) * bases[i] + w * delta[i] for i in range(len(per_topic))]
```

Register it in `zeitgeist/analysis/scorers/__init__.py`:

```python
from zeitgeist.analysis.scorers.wikipedia import WikipediaScorer

SCORERS: dict[str, ScorerBuilder] = {
    "lemmy": LemmyScorer,
    "reddit": RedditScorer,
    "wikipedia": WikipediaScorer,
}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_scorers_wikipedia.py tests/test_analysis_score.py -v
```

Expected: PASS, with no remaining xfails. `tests/test_scorers_registry.py` will now fail — `wikipedia` is in the union and `SCORERS` but not in `BUILDERS`; Task 11 fixes that. Leave it failing.

- [ ] **Step 5: Commit**

```bash
git add zeitgeist/models.py zeitgeist/analysis/scorers tests/test_scorers_wikipedia.py tests/test_analysis_score.py
git commit -m "Add WikipediaMetrics and the Wikipedia trend scorer"
```

---

### Task 10: `WikipediaSource`

**Files:**
- Create: `zeitgeist/sources/wikipedia.py`, `tests/fixtures/wikipedia_top.json`
- Test: `tests/test_sources_wikipedia.py`

**Interfaces:**
- Consumes: `Item`, `WikipediaMetrics` from Tasks 1 and 9; `SourceError` from `sources/base.py`.
- Produces: `WikipediaSource(project: str = "en.wikipedia", contact: str = DEFAULT_CONTACT, client: Any = None)`, `WikipediaSource.from_settings(settings) -> WikipediaSource`, `name = "wikipedia"`, `fetch(limit: int) -> list[Item]`. Module constants `MAX_DAY_ATTEMPTS = 5`, `STRUCTURAL_PREFIXES`, `DEATHS_PATTERN`.

- [ ] **Step 1: Write the failing tests**

Create `tests/fixtures/wikipedia_top.json` holding a trimmed but *real* payload — these titles, ranks and view counts were captured from the live API on 2026-08-22:

```json
{
  "items": [
    {
      "project": "en.wikipedia",
      "access": "all-access",
      "year": "2026", "month": "08", "day": "20",
      "articles": [
        {"article": "Main_Page", "views": 6613484, "rank": 1},
        {"article": "Special:Search", "views": 881082, "rank": 2},
        {"article": "Wikipedia:Featured_pictures", "views": 745322, "rank": 3},
        {"article": "Hayden_Panettiere", "views": 411486, "rank": 4},
        {"article": "Natalie_Harp", "views": 241798, "rank": 5},
        {"article": "Spider-Man:_Brand_New_Day", "views": 162483, "rank": 6},
        {"article": "Deaths_in_2026", "views": 132211, "rank": 7},
        {"article": "The_Odyssey_(2026_film)", "views": 129470, "rank": 8},
        {"article": "Google", "views": 126126, "rank": 10}
      ]
    }
  ]
}
```

Create `tests/test_sources_wikipedia.py`:

```python
import json
from datetime import date, timedelta
from pathlib import Path

import httpx
import pytest

from zeitgeist.config import Settings
from zeitgeist.models import WikipediaMetrics
from zeitgeist.sources.base import SourceError
from zeitgeist.sources.wikipedia import MAX_DAY_ATTEMPTS, WikipediaSource

FIXTURES = Path(__file__).parent / "fixtures"


def _payload() -> dict:
    return json.loads((FIXTURES / "wikipedia_top.json").read_text(encoding="utf-8"))


class _FakeClient:
    """Returns a queued response per call, recording the URLs requested."""

    def __init__(self, responses: list[object]) -> None:
        self._responses = list(responses)
        self.urls: list[str] = []

    def get(self, url: str, **kwargs) -> object:
        self.urls.append(url)
        result = self._responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class _Response:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


def test_structural_pages_are_filtered_out():
    """Main_Page alone draws sixteen times the first real article, so left in
    it would set the entire min-max range and flatten everything genuine."""
    source = WikipediaSource(client=_FakeClient([_Response(_payload())]))

    items = source.fetch(limit=50)

    titles = {item.title for item in items}
    assert "Main Page" not in titles
    assert "Special:Search" not in titles
    assert "Wikipedia:Featured pictures" not in titles
    assert "Deaths in 2026" not in titles


def test_real_articles_survive_filtering():
    source = WikipediaSource(client=_FakeClient([_Response(_payload())]))

    items = source.fetch(limit=50)

    assert "Hayden Panettiere" in {item.title for item in items}


def test_perennial_pages_are_not_filtered():
    """Google is merely popular, not structural. Neutralising it is the
    scorer's job via rank-delta; filtering here would be a guessing game."""
    source = WikipediaSource(client=_FakeClient([_Response(_payload())]))

    items = source.fetch(limit=50)

    assert "Google" in {item.title for item in items}


def test_metrics_carry_rank_views_and_the_measurement_day():
    source = WikipediaSource(client=_FakeClient([_Response(_payload())]))

    items = source.fetch(limit=50)

    hayden = next(i for i in items if i.title == "Hayden Panettiere")
    assert isinstance(hayden.metrics, WikipediaMetrics)
    assert hayden.metrics.rank == 4
    assert hayden.metrics.views == 411486
    assert hayden.metrics.measured_on == date(2026, 8, 20)


def test_source_id_includes_the_day_so_runs_do_not_collide():
    """The same article on two days is two measurements, not one."""
    source = WikipediaSource(client=_FakeClient([_Response(_payload())]))

    items = source.fetch(limit=50)

    hayden = next(i for i in items if i.title == "Hayden Panettiere")
    assert hayden.source_id == "en.wikipedia:Hayden_Panettiere:2026-08-20"


def test_permalink_points_at_the_article():
    source = WikipediaSource(client=_FakeClient([_Response(_payload())]))

    items = source.fetch(limit=50)

    hayden = next(i for i in items if i.title == "Hayden Panettiere")
    assert hayden.permalink == "https://en.wikipedia.org/wiki/Hayden_Panettiere"


def _day_from_url(url: str) -> date:
    """The trailing /YYYY/MM/DD of a pageviews URL."""
    year, month, day = url.rsplit("/", 3)[-3:]
    return date(int(year), int(month), int(day))


def test_a_missing_day_falls_back_to_exactly_one_day_earlier():
    """Pageviews data is not published immediately for the current day, and
    how far it lags is not something this source should need to know. The
    step must be one day backwards: forwards finds a day that will never
    have data, and two days silently skips a day that does.

    The URLs are compared to each other rather than to a literal because
    fetch() derives the first day from datetime.now(UTC), and the suite must
    not depend on the wall clock.
    """
    client = _FakeClient([httpx.HTTPError("not ready"), _Response(_payload())])
    source = WikipediaSource(client=client)

    items = source.fetch(limit=50)

    assert items
    assert len(client.urls) == 2
    first, second = (_day_from_url(url) for url in client.urls)
    assert second == first - timedelta(days=1)


def test_exhausting_every_attempt_raises_source_error():
    client = _FakeClient([httpx.HTTPError("down")] * MAX_DAY_ATTEMPTS)
    source = WikipediaSource(client=client)

    with pytest.raises(SourceError):
        source.fetch(limit=50)

    assert len(client.urls) == MAX_DAY_ATTEMPTS


def test_a_payload_with_only_structural_pages_raises_source_error():
    """An empty result after filtering is an outage-shaped condition, so it
    becomes SourceError and CompositeSource degrades to a Lemmy-only run."""
    payload = _payload()
    payload["items"][0]["articles"] = [
        {"article": "Main_Page", "views": 1, "rank": 1}
    ]
    client = _FakeClient([_Response(payload)] * MAX_DAY_ATTEMPTS)
    source = WikipediaSource(client=client)

    with pytest.raises(SourceError):
        source.fetch(limit=50)


def test_a_changed_payload_shape_crashes_rather_than_looking_like_an_outage():
    """A missing 'articles' key is a contract break, not an unreachable host.
    It must not be swallowed into SourceError."""
    client = _FakeClient([_Response({"items": [{"year": "2026"}]})])
    source = WikipediaSource(client=client)

    with pytest.raises(KeyError):
        source.fetch(limit=50)


def test_limit_is_applied_after_filtering():
    """The budget buys real articles, not Main_Page and friends."""
    source = WikipediaSource(client=_FakeClient([_Response(_payload())]))

    items = source.fetch(limit=2)

    assert len(items) == 2
    assert {i.title for i in items} == {"Hayden Panettiere", "Natalie Harp"}


def test_the_configured_contact_reaches_the_request_headers():
    """Wikimedia's API policy warns that generic agents may be rate-limited
    or blocked outright, so what matters is the header the client will send,
    not the string the source happens to store. Asserting the attribute
    would stay green if the headers= argument were dropped from the client.
    """
    source = WikipediaSource(contact="https://example.org/bot")

    # Substring, not equality: the version prefix is free to change, and
    # pinning it would fail on a release bump that broke nothing. What must
    # hold is that the header exists at all and carries the contact — the
    # KeyError if headers= were dropped is the break worth catching.
    assert "https://example.org/bot" in source._client.headers["User-Agent"]


def test_a_non_default_project_reaches_the_url_the_id_and_the_permalink():
    """`project` decides which wiki is measured and is threaded through three
    places. Only the URL is obvious when it is dropped: a hardcoded
    en.wikipedia.org permalink sends every reader of a de.wikipedia run to
    the wrong article, and a project-less source_id makes the same article
    on two wikis look like one item to CompositeSource.
    """
    client = _FakeClient([_Response(_payload())])
    source = WikipediaSource(project="de.wikipedia", client=client)

    items = source.fetch(limit=50)

    hayden = next(i for i in items if i.title == "Hayden Panettiere")
    assert "/de.wikipedia/all-access/" in client.urls[0]
    assert hayden.source_id == "de.wikipedia:Hayden_Panettiere:2026-08-20"
    assert hayden.permalink == "https://de.wikipedia.org/wiki/Hayden_Panettiere"


def test_from_settings_wires_the_project_and_contact_through():
    """from_settings is plumbing, so it fails silently: a dropped project or
    contact only shows up in the request that goes out.
    """
    settings = Settings(
        _env_file=None,
        sources=["wikipedia"],
        wikipedia_project="fr.wikipedia",
        wikipedia_contact="https://example.org/bot",
    )

    source = WikipediaSource.from_settings(settings)
    source._client = _FakeClient([_Response(_payload())])
    source.fetch(limit=1)

    assert "/fr.wikipedia/all-access/" in source._client.urls[0]
    assert "https://example.org/bot" in source.user_agent
```

Note `test_from_settings_wires_the_project_and_contact_through` depends on the config keys added in Task 11; mark it `@pytest.mark.xfail(reason="Settings keys arrive in Task 11", strict=True)` here and remove the marker in Task 11.

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_sources_wikipedia.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'zeitgeist.sources.wikipedia'`.

- [ ] **Step 3: Write the implementation**

Create `zeitgeist/sources/wikipedia.py`:

```python
"""Wikimedia pageviews ingestion via the public REST metrics API.

Needs no credentials. Unlike the forum sources this measures *attention*
rather than conversation: there are no comments and no communities, so it
cannot originate topics — it corroborates topics another platform found.
"""

import logging
import re
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx

from zeitgeist.config import Settings
from zeitgeist.models import Item, WikipediaMetrics
from zeitgeist.sources.base import SourceError

log = logging.getLogger(__name__)

BASE_URL = "https://wikimedia.org/api/rest_v1/metrics/pageviews/top"
TIMEOUT_SECONDS = 30.0
# Pageviews for a given day are not published immediately. Rather than pin a
# lag figure that could change, walk back until a day exists.
MAX_DAY_ATTEMPTS = 5

DEFAULT_CONTACT = "https://github.com/MomomeYeah/Zeitgeist-Actualiser"

# Namespace and maintenance pages. These occupy the very top of the listing —
# Main_Page alone draws sixteen times the first real article — so left in they
# would set the whole min-max range and flatten everything genuine to zero.
STRUCTURAL_PREFIXES = (
    "Special:",
    "Wikipedia:",
    "Portal:",
    "Help:",
    "Category:",
    "Template:",
    "File:",
    "Talk:",
)
STRUCTURAL_EXACT = frozenset({"Main_Page"})
DEATHS_PATTERN = re.compile(r"^Deaths_in_\d{4}$")


class WikipediaSource:
    name = "wikipedia"

    def __init__(
        self,
        project: str = "en.wikipedia",
        contact: str = DEFAULT_CONTACT,
        client: Any = None,
    ) -> None:
        self._project = project
        # Wikimedia's API policy requires contact information in the agent and
        # warns that generic agents may be rate-limited or blocked outright.
        self.user_agent = f"zeitgeist-actualiser/0.1 ({contact})"
        self._client = client or httpx.Client(
            timeout=TIMEOUT_SECONDS, headers={"User-Agent": self.user_agent}
        )

    @classmethod
    def from_settings(cls, settings: Settings) -> "WikipediaSource":
        return cls(
            project=settings.wikipedia_project,
            contact=settings.wikipedia_contact,
        )

    def fetch(self, limit: int) -> list[Item]:
        fetched_at = datetime.now(UTC)
        day = fetched_at.date()

        for _ in range(MAX_DAY_ATTEMPTS):
            # Only transport failure is tolerated. A KeyError from a changed
            # payload propagates: that is a contract break, not an outage.
            try:
                articles, measured = self._fetch_day(day)
            except httpx.HTTPError as exc:
                log.warning("Skipping Wikipedia pageviews for %s: %s", day, exc)
                day -= timedelta(days=1)
                continue

            # Mapping is pure: a bug here must crash, not look like a
            # missing day.
            items = [
                _to_item(entry, measured, self._project, fetched_at)
                for entry in articles
                if not _is_structural(entry["article"])
            ]
            if items:
                # Truncated after filtering, so the budget buys real articles
                # rather than being spent on namespace pages.
                return items[:limit]

            log.warning("Wikipedia pageviews for %s held no usable articles", day)
            day -= timedelta(days=1)

        raise SourceError(
            f"Wikipedia returned no usable articles in {MAX_DAY_ATTEMPTS} days"
        )

    def _fetch_day(self, day: date) -> tuple[list[dict[str, Any]], date]:
        url = (
            f"{BASE_URL}/{self._project}/all-access/"
            f"{day.year:04d}/{day.month:02d}/{day.day:02d}"
        )
        response = self._client.get(url)
        response.raise_for_status()
        payload = response.json()
        entry = payload["items"][0]
        measured = date(int(entry["year"]), int(entry["month"]), int(entry["day"]))
        return entry["articles"], measured


def _is_structural(article: str) -> bool:
    return (
        article in STRUCTURAL_EXACT
        or article.startswith(STRUCTURAL_PREFIXES)
        or DEATHS_PATTERN.match(article) is not None
    )


def _to_item(
    entry: dict[str, Any], measured: date, project: str, fetched_at: datetime
) -> Item:
    article = entry["article"]
    return Item(
        # The day is part of the identity: the same article on two days is
        # two measurements, not a duplicate.
        source_id=f"{project}:{article}:{measured.isoformat()}",
        title=article.replace("_", " "),
        body_excerpt=None,
        # Built from `project`, not hardcoded: a de.wikipedia run measures
        # German pageviews, so linking to the English article would send
        # every reader somewhere the numbers did not come from.
        permalink=f"https://{project}.org/wiki/{article}",
        fetched_at=fetched_at,
        metrics=WikipediaMetrics(
            views=entry["views"],
            rank=entry["rank"],
            measured_on=measured,
        ),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_sources_wikipedia.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add zeitgeist/sources/wikipedia.py tests/test_sources_wikipedia.py tests/fixtures/wikipedia_top.json
git commit -m "Add WikipediaSource over the Wikimedia pageviews API"
```

---

### Task 11: Configuration, registry, and documentation

**Files:**
- Modify: `zeitgeist/config.py`, `zeitgeist/sources/__init__.py`, `.env.example`, `README.md`
- Test: `tests/test_config.py`, `tests/test_scorers_registry.py`

**Interfaces:**
- Consumes: `WikipediaSource.from_settings` from Task 10.
- Produces: `Settings.wikipedia_project: str = "en.wikipedia"`, `Settings.wikipedia_contact: str = DEFAULT_CONTACT`; `"wikipedia"` in `KNOWN_SOURCES` and `BUILDERS`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_config.py`:

```python
def test_wikipedia_needs_no_credentials():
    """Unlike Reddit, enabling it must not raise at startup — this is the
    property that keeps the project runnable out of the box. Fails if
    _check_sources ever grows a credential branch for wikipedia.
    """
    settings = Settings(_env_file=None, sources=["lemmy", "wikipedia"])

    assert settings.sources == ["lemmy", "wikipedia"]
```

There is deliberately **no** `test_wikipedia_project_defaults_to_english`. Asserting `settings.wikipedia_project == "en.wikipedia"` restates the default back at itself: the only change that fails it is someone deciding the default should be a different wiki, which is a decision they are entitled to make, not a bug. Task 10's `test_a_non_default_project_reaches_the_url_the_id_and_the_permalink` covers the part that can actually break — the value being threaded through rather than ignored.

Add `"WIKIPEDIA_PROJECT"` and `"WIKIPEDIA_CONTACT"` to `_SETTINGS_ENV_VARS` in `tests/conftest.py` — without this the suite's result depends on the developer's shell, which the fixture exists to prevent.

Remove the `xfail` marker from `test_from_settings_wires_the_project_and_contact_through` in `tests/test_sources_wikipedia.py`; the Settings keys it needs land in this task.

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_config.py tests/test_scorers_registry.py -v
```

Expected: FAIL — `wikipedia` is not in `KNOWN_SOURCES`, and the registry guard from Task 7 fails because `BUILDERS` lacks it.

- [ ] **Step 3: Write the implementation**

In `zeitgeist/config.py`:

```python
KNOWN_SOURCES: tuple[str, ...] = ("lemmy", "reddit", "wikipedia")
```

and add to `Settings`:

```python
    wikipedia_project: str = "en.wikipedia"
    wikipedia_contact: str = "https://github.com/MomomeYeah/Zeitgeist-Actualiser"
```

In `zeitgeist/sources/__init__.py`:

```python
from zeitgeist.sources.wikipedia import WikipediaSource

BUILDERS: dict[str, Callable[[Settings], Source]] = {
    "lemmy": LemmySource.from_settings,
    "reddit": RedditSource.from_settings,
    "wikipedia": WikipediaSource.from_settings,
}
```

Add to `.env.example`:

```
SOURCES=lemmy,wikipedia
WIKIPEDIA_PROJECT=en.wikipedia
WIKIPEDIA_CONTACT=https://github.com/MomomeYeah/Zeitgeist-Actualiser
```

In `README.md`, extend the Sources section:

```markdown
`wikipedia` adds Wikimedia pageviews — the top 1000 most-viewed articles for
the most recent day with data. It needs no credentials. Unlike Lemmy and
Reddit it measures *attention* rather than conversation: articles carry no
comments and no body text, so a topic Wikipedia alone found is dropped rather
than ranked. Its role is corroboration — a topic trending on Lemmy *and*
spiking on Wikipedia outranks one trending on Lemmy alone.

`WIKIPEDIA_CONTACT` is interpolated into the User-Agent. Wikimedia's API
policy asks for contact information and may rate-limit or block generic
agents, so set it to your own repository or contact URL if you fork this.
```

Replace the README paragraph beginning "Trend scoring does not yet normalise scores across platforms" — that limitation no longer applies:

```markdown
Each platform scores its own contribution to a topic, normalised within that
platform, before the results are combined. So a busy platform no longer
swamps a quiet one, and mixing sources is expected rather than experimental.
```

- [ ] **Step 4: Run the whole gate**

```bash
uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest
```

Expected: all four PASS, including `tests/test_scorers_registry.py`.

- [ ] **Step 5: Verify against the live API**

This is the one step that touches the network, run manually, not in the suite:

```bash
uv run python -c "from zeitgeist.sources.wikipedia import WikipediaSource; items = WikipediaSource().fetch(limit=10); print(f'{len(items)} items, measured {items[0].metrics.measured_on}'); [print(f'  {i.metrics.rank:>4} {i.title}') for i in items[:5]]"
```

Expected: ten items with plausible titles, no namespace pages. **Record the gap between the measured date and today** — this is the lag figure the spec could not verify, and the "Unverified lag" risk depends on it.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "Register the Wikipedia source and document it"
```

---

## Post-implementation

- [ ] Run a full pipeline against both sources: `uv run zeitgeist run`
- [ ] Check `output/<run-id>/topics.json` — how many topics carry a `wikipedia` entry in `score_components`? The spec's "thin overlap" risk predicts this may be low. Record the figure.
- [ ] If overlap is zero across several runs, that is worth reporting before adding a third platform: it would mean corroboration is untested against real data.
