# Bluesky Source and Per-Platform Score Weights Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Bluesky as a third platform — content-bearing like Lemmy but with a far wider audience — and split the flat `ScoreWeights` model into per-platform weights so each scorer reads only what it uses.

**Architecture:** Four tasks in dependency order. Tasks 1 and 2 are pure refactors of existing scoring code that must leave Lemmy and Wikipedia output bit-identical; the existing scorer tests are the proof and must pass unedited except where noted. Task 3 adds the Bluesky metrics model, weights and scorer. Task 4 adds the source that produces those metrics, plus registries, config and docs.

**Tech Stack:** Python 3.14, pydantic v2, httpx, pytest, uv, ruff, ty.

**Design spec:** `docs/superpowers/specs/2026-08-23-bluesky-source-design.md`. Read it before starting — particularly "How a trend becomes a list of posts", which explains the two-step Bluesky fetch.

## Global Constraints

- **Definition of Done.** No task is complete until all four pass: `uv run ruff check .`, `uv run ruff format --check .`, `uv run ty check`, `uv run pytest`. A Stop hook enforces this and CI runs the same four.
- **Python 3.14 with PEP 695 generics.** Write `def f[T: Bound](...)`, never `typing.TypeVar`.
- **Line length 88.** Ruff rules `E, F, I, UP, B, SIM`.
- **No blanket `# type: ignore`.** Fix type errors at the root cause; a narrow suppression needs a comment explaining why.
- **No `author`, `username`, or any personal identifier** on any model. `tests/test_models.py` actively guards this. Bluesky payloads carry an `author` block — do not map it.
- **Transport failure is tolerated; contract breaks crash.** Catch `httpx.HTTPError` and log; let `KeyError` from a changed payload propagate. Both existing sources follow this and Bluesky must too.
- **Bluesky needs no credentials.** If you find yourself adding a token, password or app password setting, you have gone wrong.
- **Base URL is `https://api.bsky.app`.** Not `public.api.bsky.app`, which returns 403 on parts of the API.

---

## File Structure

**Created:**

| File | Responsibility |
|---|---|
| `zeitgeist/sources/bluesky.py` | Fetch trends, resolve each to its feed, map posts to `Item`s |
| `zeitgeist/analysis/scorers/bluesky.py` | Score Bluesky topics from like/reply/repost velocity and trend status |
| `tests/test_scorers_base.py` | The shared blend helpers and `ScoreWeights.for_platform` |
| `tests/test_sources_bluesky.py` | `BlueskySource` fetch, filtering, mapping, failure behaviour |
| `tests/test_scorers_bluesky.py` | `BlueskyScorer` ranking behaviour |

**Modified:**

| File | Change |
|---|---|
| `zeitgeist/analysis/scorers/base.py` | Add `historical_delta`, `blend`, `PlatformWeights` + subclasses, rewrite `ScoreWeights` |
| `zeitgeist/analysis/scorers/lemmy.py` | Use the shared helpers and `LemmyWeights` |
| `zeitgeist/analysis/scorers/wikipedia.py` | Use the shared helpers and `WikipediaWeights` |
| `zeitgeist/analysis/scorers/__init__.py` | Register `BlueskyScorer` |
| `zeitgeist/models.py` | Add `BlueskyMetrics` to the `Metrics` union |
| `zeitgeist/sources/__init__.py` | Register `BlueskySource.from_settings` |
| `zeitgeist/config.py` | `KNOWN_SOURCES` gains `bluesky`; add `bluesky_api_base` |
| `tests/test_scorers_lemmy.py` | One test constructs `ScoreWeights` with field kwargs (line 153) |
| `tests/test_models.py` | Add `BlueskyMetrics` to the parametrised field-set guard |
| `README.md`, `.env.example` | Document the new source |

**Deliberately unchanged:** `zeitgeist/analysis/score.py` (the coordinator's own logic is untouched — only the type of what it passes through changes), `zeitgeist/pipeline.py`, `zeitgeist/store.py`, and every media and LLM module.

---

## Task 1: Shared blend helpers

Both existing scorers carry the same eight-line delta block and the same four-line comment, character for character. That duplication is the evidence that the rank-delta blend is structural rather than platform-specific. Hoist it before adding a third platform, or you will write a third copy of a block that is about to be deleted.

**Files:**
- Modify: `zeitgeist/analysis/scorers/base.py`
- Modify: `zeitgeist/analysis/scorers/lemmy.py:44-62`
- Modify: `zeitgeist/analysis/scorers/wikipedia.py:20-42`
- Test: `tests/test_scorers_base.py` (create)

**Interfaces:**
- Consumes: `normalise(values: list[float]) -> list[float]`, already in `base.py`.
- Produces: `historical_delta(bases: list[float], previous: list[float | None]) -> list[float]` and `blend(bases: list[float], deltas: list[float], weight: float) -> list[float]`, both in `zeitgeist.analysis.scorers.base`. Tasks 2 and 3 use `blend`; Task 3 does **not** use `historical_delta`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_scorers_base.py`:

```python
"""The blend helpers shared by every scorer.

Extracted from lemmy.py and wikipedia.py, which carried the same delta block
verbatim. These tests pin the behaviour that duplication encoded, so a future
edit to one scorer cannot quietly change the other.
"""

from zeitgeist.analysis.scorers.base import blend, historical_delta


def test_historical_delta_defaults_an_unseen_topic_to_its_own_base():
    """The tempting `previous[i] or 0.0` would read an unseen topic as having
    risen from nothing, handing every first-run topic full marks. Both topics
    here are flat, so a correct implementation returns a degenerate range and
    `normalise` yields zeros. Under `or 0.0` the second topic's raw delta
    becomes 1.0 and the two separate.
    """
    assert historical_delta([0.5, 1.0], [0.5, None]) == [0.0, 0.0]


def test_historical_delta_ranks_a_riser_above_a_faller():
    """Sign and direction: subtracting in the wrong order would invert this."""
    deltas = historical_delta([1.0, 0.0], [0.0, 1.0])

    assert deltas[0] > deltas[1]


def test_historical_delta_normalises_to_the_unit_interval():
    """Every sub-score the coordinator averages must share one scale."""
    deltas = historical_delta([0.9, 0.5, 0.1], [0.1, 0.5, 0.9])

    assert min(deltas) == 0.0
    assert max(deltas) == 1.0


def test_blend_weights_base_against_delta():
    """Asserting exact values, not an ordering: a swapped pair of arguments
    still produces a plausible ordering but the wrong numbers.
    """
    assert blend([1.0, 0.0], [0.0, 1.0], 0.25) == [0.75, 0.25]


def test_blend_at_zero_weight_returns_the_bases_untouched():
    assert blend([0.3, 0.7], [1.0, 1.0], 0.0) == [0.3, 0.7]


def test_blend_at_full_weight_returns_the_deltas_untouched():
    assert blend([0.3, 0.7], [1.0, 0.0], 1.0) == [1.0, 0.0]
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/test_scorers_base.py -v
```

Expected: FAIL — `ImportError: cannot import name 'blend' from 'zeitgeist.analysis.scorers.base'`.

- [ ] **Step 3: Add the helpers to `base.py`**

Append to `zeitgeist/analysis/scorers/base.py`, after `normalise`:

```python
def historical_delta(bases: list[float], previous: list[float | None]) -> list[float]:
    """Normalised movement of each topic against its own prior sub-score.

    Defaulting to the topic's own base, not 0.0: an unseen topic has not
    risen, so its delta must be zero rather than full marks.

    `prior` is bound to a local so ty can narrow away the `None` in the
    `is not None` branch — narrowing does not carry across repeated subscript
    expressions like `previous[i]`.
    """
    raw = []
    for i in range(len(bases)):
        prior = previous[i]
        raw.append(bases[i] - (prior if prior is not None else bases[i]))
    return normalise(raw)


def blend(bases: list[float], deltas: list[float], weight: float) -> list[float]:
    """`(1 - weight) * base + weight * delta`, elementwise."""
    return [
        (1.0 - weight) * bases[i] + weight * deltas[i] for i in range(len(bases))
    ]
```

- [ ] **Step 4: Rewrite `LemmyScorer.score` to use them**

In `zeitgeist/analysis/scorers/lemmy.py`, change the import line to:

```python
from zeitgeist.analysis.scorers.base import ScoreWeights, blend, historical_delta, normalise
```

Then replace everything from the `# Defaulting to the topic's own base` comment to the end of `score` (currently lines 44-62) with:

```python
        deltas = historical_delta(bases, previous)
        return blend(bases, deltas, weights.rank_delta)
```

Leave the `raw_uv` / `raw_cv` / `raw_cs` and `bases` computation above it exactly as it is.

- [ ] **Step 5: Rewrite `WikipediaScorer.score` to use them**

In `zeitgeist/analysis/scorers/wikipedia.py`, change the import line to:

```python
from zeitgeist.analysis.scorers.base import ScoreWeights, blend, historical_delta, normalise
```

Then replace everything from the `# Defaulting to the topic's own base` comment to the end of `score` with:

```python
        deltas = historical_delta(bases, previous)
        return blend(bases, deltas, self._weights.rank_delta)
```

Leave the `raw` / `bases` computation and its comment as they are.

- [ ] **Step 6: Run the full suite**

```bash
uv run pytest -q
```

Expected: PASS, 278 tests (272 existing + 6 new). **Every pre-existing test must pass unedited.** This refactor changes no behaviour, so if `tests/test_scorers_lemmy.py` or `tests/test_scorers_wikipedia.py` fails, the extraction is wrong — fix the helper, do not edit the test.

- [ ] **Step 7: Run the full gate**

```bash
uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest
```

Expected: all four pass.

- [ ] **Step 8: Commit**

```bash
git add zeitgeist/analysis/scorers/base.py zeitgeist/analysis/scorers/lemmy.py zeitgeist/analysis/scorers/wikipedia.py tests/test_scorers_base.py
git commit -m "Hoist the shared rank-delta blend into scorers/base.py"
```

---

## Task 2: Per-platform weights union

`ScoreWeights` is one flat model that every scorer receives whole. `WikipediaScorer` uses one field of it and silently ignores three. A third platform that reads a metric no other has, and skips two that Lemmy uses, makes that structural. Replace it with a discriminated union mirroring the `Metrics` union in `models.py`.

**Files:**
- Modify: `zeitgeist/analysis/scorers/base.py:13-20`
- Modify: `zeitgeist/analysis/scorers/lemmy.py`
- Modify: `zeitgeist/analysis/scorers/wikipedia.py`
- Modify: `tests/test_scorers_lemmy.py:150-172`
- Test: `tests/test_scorers_base.py` (append)

**Interfaces:**
- Consumes: `blend`, `historical_delta` from Task 1.
- Produces, all in `zeitgeist.analysis.scorers.base`:
  - `PlatformWeights` — base model, field `rank_delta: float = 0.25`
  - `LemmyWeights(PlatformWeights)` — `platform: Literal["lemmy"]`, `upvote_velocity`, `comment_velocity`, `channel_spread`
  - `WikipediaWeights(PlatformWeights)` — `platform: Literal["wikipedia"]`, no other fields
  - `PlatformWeightsUnion` — `Annotated[LemmyWeights | WikipediaWeights, Field(discriminator="platform")]`
  - `ScoreWeights` — `corroboration_bonus: float = 0.25`, `platforms: dict[str, PlatformWeightsUnion]`, and `for_platform[W: PlatformWeights](self, platform: str, expected: type[W]) -> W`
- Task 3 extends `PlatformWeightsUnion` with `BlueskyWeights`.

- [ ] **Step 1: Write the failing tests**

First **replace the import block at the top of `tests/test_scorers_base.py`** with the following. Do not append imports below the Task 1 functions — ruff's `E402` rejects a module-level import after code:

```python
import pytest
from pydantic import ValidationError

from zeitgeist.analysis.scorers.base import (
    LemmyWeights,
    ScoreWeights,
    WikipediaWeights,
    blend,
    historical_delta,
)
```

Then append these tests to the end of the file:

```python
def test_for_platform_returns_the_narrowed_subclass():
    assert isinstance(ScoreWeights().for_platform("lemmy", LemmyWeights), LemmyWeights)


def test_for_platform_rejects_a_mismatched_pairing():
    """A registry-drift guard: reaching this means SCORERS and `platforms`
    disagree about what a platform is, which is a bug in this package rather
    than bad input.
    """
    with pytest.raises(TypeError):
        ScoreWeights().for_platform("lemmy", WikipediaWeights)


def test_for_platform_raises_for_an_unregistered_platform():
    """Matches build_scorer, so both halves of the same drift bug fail alike."""
    with pytest.raises(KeyError):
        ScoreWeights().for_platform("myspace", LemmyWeights)


def test_platforms_are_weighted_independently():
    """The point of the split. One platform's rank_delta must be settable
    without touching another's — impossible under the flat model, where the
    two shared one field.
    """
    weights = ScoreWeights(
        platforms={
            "lemmy": LemmyWeights(rank_delta=0.9),
            "wikipedia": WikipediaWeights(rank_delta=0.1),
        }
    )

    assert weights.for_platform("lemmy", LemmyWeights).rank_delta == 0.9
    assert weights.for_platform("wikipedia", WikipediaWeights).rank_delta == 0.1


def test_platform_weights_reject_a_weight_belonging_to_another_platform():
    """STRICT on the weights models. Without extra="forbid", `upvote_velocity`
    mistyped under wikipedia would be dropped in silence and the run would
    score with defaults nobody chose.
    """
    with pytest.raises(ValidationError):
        WikipediaWeights(upvote_velocity=0.5)


def test_score_weights_reject_the_per_platform_fields_they_used_to_carry():
    """The migration hazard this split creates. `upvote_velocity` and its three
    neighbours moved off ScoreWeights onto LemmyWeights; without extra="forbid"
    a call site left on the old flat shape is accepted, its value dropped in
    silence, and the run scores with defaults nobody chose.
    """
    with pytest.raises(ValidationError):
        ScoreWeights(upvote_velocity=0.0)


def test_the_default_mapping_covers_every_registered_scorer():
    """A platform with a scorer but no default weights is a KeyError partway
    through a run, after the fetch has already been paid for.
    """
    from zeitgeist.analysis.scorers import SCORERS

    assert set(SCORERS) <= set(ScoreWeights().platforms)
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/test_scorers_base.py -v
```

Expected: FAIL — `ImportError: cannot import name 'LemmyWeights'`.

- [ ] **Step 3: Replace `ScoreWeights` in `base.py`**

In `zeitgeist/analysis/scorers/base.py`, replace the existing `ScoreWeights` class (lines 13-20) with the following. Update the imports at the top of the file to include `Literal`, `Annotated`, `Field` and `STRICT`:

```python
from typing import Annotated, Literal, Protocol

from pydantic import BaseModel, Field

from zeitgeist.models import STRICT


class PlatformWeights(BaseModel):
    """Weights every scorer has, because every scorer blends the same way.

    `rank_delta` sits here rather than on each subclass because it is
    structural: a scorer computes a base from its own metrics, then blends
    that base against a movement term. The duplication this replaced is the
    evidence.

    STRICT (`extra="forbid"`) is deliberate. Once weights arrive as a nested
    mapping, a key typed against the wrong platform — `upvote_velocity` under
    `wikipedia` — would otherwise be dropped in silence.
    """

    model_config = STRICT

    rank_delta: float = 0.25


class LemmyWeights(PlatformWeights):
    platform: Literal["lemmy"] = "lemmy"

    upvote_velocity: float = 0.4
    comment_velocity: float = 0.3
    channel_spread: float = 0.3


class WikipediaWeights(PlatformWeights):
    """No fields of its own. Pageviews carry no velocity and no spread, so
    position and movement are the whole signal — which the base already
    covers.
    """

    platform: Literal["wikipedia"] = "wikipedia"


PlatformWeightsUnion = Annotated[
    LemmyWeights | WikipediaWeights,
    Field(discriminator="platform"),
]


class ScoreWeights(BaseModel):
    model_config = STRICT

    # The one weight the coordinator itself reads. Not a platform's opinion,
    # so it does not belong in the per-platform mapping.
    corroboration_bonus: float = 0.25
    platforms: dict[str, PlatformWeightsUnion] = Field(
        default_factory=lambda: {
            "lemmy": LemmyWeights(),
            "wikipedia": WikipediaWeights(),
        }
    )

    def for_platform[W: PlatformWeights](self, platform: str, expected: type[W]) -> W:
        """This platform's weights, narrowed to the type its scorer needs.

        Scorers take the whole ScoreWeights and narrow here rather than
        declaring a narrowed parameter type: SCORERS holds builders of one
        uniform Callable type, and narrowing a parameter is a contravariance
        violation that ty rejects on assignment into that dict.

        The isinstance check is a registry-drift guard, not a cast. Reaching
        it means SCORERS and `platforms` disagree about what a platform is,
        which is a bug in this package rather than bad input — same spirit as
        build_scorer's KeyError, which the subscript below raises for a
        platform that has no entry at all.
        """
        weights = self.platforms[platform]
        if not isinstance(weights, expected):
            raise TypeError(
                f"{platform} weights are {type(weights).__name__}, "
                f"expected {expected.__name__}"
            )
        return weights
```

Note: `zeitgeist/models.py` imports nothing from `zeitgeist.analysis`, so importing `STRICT` from it here is not a cycle.

- [ ] **Step 4: Switch both scorers to their own weights**

In `zeitgeist/analysis/scorers/lemmy.py`, change the import and `__init__`:

```python
from zeitgeist.analysis.scorers.base import (
    LemmyWeights,
    ScoreWeights,
    blend,
    historical_delta,
    normalise,
)


class LemmyScorer:
    platform = "lemmy"

    def __init__(self, weights: ScoreWeights, now: datetime) -> None:
        self._weights = weights.for_platform("lemmy", LemmyWeights)
        self._now = now
```

The body of `score` needs **no edit at all**. It opens with `weights = self._weights` and reads `weights.upvote_velocity`, `weights.comment_velocity`, `weights.channel_spread` and `weights.rank_delta`; `LemmyWeights` carries all four field names unchanged, so every one of those reads still resolves.

In `zeitgeist/analysis/scorers/wikipedia.py`:

```python
from zeitgeist.analysis.scorers.base import (
    ScoreWeights,
    WikipediaWeights,
    blend,
    historical_delta,
    normalise,
)


class WikipediaScorer:
    platform = "wikipedia"

    def __init__(self, weights: ScoreWeights, now: datetime) -> None:
        self._weights = weights.for_platform("wikipedia", WikipediaWeights)
```

- [ ] **Step 5: Update the one test that constructs weights by field**

`tests/test_scorers_lemmy.py:150-172` is the only place in the codebase that passes weight fields to `ScoreWeights`. Every other call site uses the bare `ScoreWeights()` default and needs no change. Replace the weights construction inside `test_weights_redirect_the_score_between_the_terms_they_name`:

```python
    weights = ScoreWeights(
        platforms={
            "lemmy": LemmyWeights(
                upvote_velocity=0.0,
                comment_velocity=1.0,
                channel_spread=0.0,
                rank_delta=0.0,
            )
        }
    )
```

and add `LemmyWeights` to that file's import from `zeitgeist.analysis.scorers.base`. The test's assertion and docstring stay exactly as they are.

- [ ] **Step 6: Run the full suite**

```bash
uv run pytest -q
```

Expected: PASS. Apart from the one edited construction, **every pre-existing test must pass unedited** — this task changes no scoring behaviour. If `test_scorers_wikipedia.py` or `test_analysis_score.py` fails, the refactor is wrong.

- [ ] **Step 7: Run the full gate**

```bash
uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest
```

- [ ] **Step 8: Commit**

```bash
git add zeitgeist/analysis/scorers/ tests/test_scorers_base.py tests/test_scorers_lemmy.py
git commit -m "Split ScoreWeights into a per-platform discriminated union"
```

---

## Task 3: Bluesky metrics, weights and scorer

Metrics and scorer land together because `tests/test_scorers_registry.py::test_every_metrics_platform_has_a_scorer` asserts the `Metrics` union and `SCORERS` hold the same platform set. Adding one without the other fails that guard. The source arrives separately in Task 4, which the same file's `test_every_source_has_a_scorer` explicitly permits — it asserts `set(BUILDERS) <= set(SCORERS)`.

**Files:**
- Create: `zeitgeist/analysis/scorers/bluesky.py`
- Modify: `zeitgeist/models.py` (add `BlueskyMetrics`, extend `Metrics`)
- Modify: `zeitgeist/analysis/scorers/base.py` (add `BlueskyWeights`, extend the union and the default mapping)
- Modify: `zeitgeist/analysis/scorers/__init__.py`
- Modify: `tests/test_models.py:120-140`
- Test: `tests/test_scorers_bluesky.py` (create)

**Interfaces:**
- Consumes: `blend` from Task 1; `ScoreWeights.for_platform` from Task 2.
- Produces:
  - `zeitgeist.models.BlueskyMetrics` — fields `platform`, `like_count: int`, `reply_count: int`, `repost_count: int`, `trend: str`, `status: Literal["trending", "cooling", "stale"]`, `created_at: datetime`; `content_bearing: ClassVar[bool] = True`; `context` property returning `self.trend`
  - `zeitgeist.analysis.scorers.base.BlueskyWeights` — `platform`, `like_velocity=0.35`, `reply_velocity=0.30`, `repost_velocity=0.35`, inherited `rank_delta=0.25`
  - `zeitgeist.analysis.scorers.bluesky.BlueskyScorer` — `platform = "bluesky"`, `__init__(weights: ScoreWeights, now: datetime)`, `score(per_topic, previous) -> list[float]`
  - `zeitgeist.analysis.scorers.bluesky.STATUS_MOVEMENT` — `{"trending": 1.0, "cooling": 0.5, "stale": 0.0}`
- Task 4's `BlueskySource` constructs `BlueskyMetrics`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_scorers_bluesky.py`:

```python
from datetime import UTC, datetime
from typing import Literal

import pytest
from pydantic import ValidationError

from zeitgeist.analysis.score import score_topics
from zeitgeist.analysis.scorers import build_scorer
from zeitgeist.analysis.scorers.base import BlueskyWeights, ScoreWeights
from zeitgeist.models import BlueskyMetrics, Item, Topic

NOW = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)

# Aliased because `status: str` does not type-check against the model's
# Literal field, and ty covers tests/ as part of the definition of done.
Status = Literal["trending", "cooling", "stale"]


def _m(
    *,
    likes: int = 100,
    replies: int = 10,
    reposts: int = 20,
    age_hours: float = 2.0,
    trend: str = "a trend",
    status: Status = "trending",
) -> BlueskyMetrics:
    return BlueskyMetrics(
        like_count=likes,
        reply_count=replies,
        repost_count=reposts,
        trend=trend,
        status=status,
        created_at=datetime.fromtimestamp(NOW.timestamp() - age_hours * 3600, tz=UTC),
    )


def _score(per_topic, previous=None):
    scorer = build_scorer("bluesky", ScoreWeights(), NOW)
    return scorer.score(
        per_topic=per_topic, previous=previous or [None] * len(per_topic)
    )


def test_faster_like_velocity_scores_higher():
    """One axis at a time: replies, reposts, age and status are all equal."""
    scores = _score([[_m(likes=10000)], [_m(likes=10)]])

    assert scores[0] > scores[1]


def test_faster_reply_velocity_scores_higher():
    scores = _score([[_m(replies=10000)], [_m(replies=10)]])

    assert scores[0] > scores[1]


def test_faster_repost_velocity_scores_higher():
    """Reposts are Bluesky's spread signal, replacing Lemmy's channel_spread.
    Without a repost term this pair is indistinguishable.
    """
    scores = _score([[_m(reposts=10000)], [_m(reposts=10)]])

    assert scores[0] > scores[1]


def test_velocity_is_per_hour_rather_than_absolute():
    """The older topic has twice the raw engagement and a fifth the rate.
    Summing raw counts would invert this.
    """
    scores = _score(
        [
            [_m(likes=100, replies=100, reposts=100, age_hours=10)],
            [_m(likes=50, replies=50, reposts=50, age_hours=1)],
        ]
    )

    assert scores[1] > scores[0]


def test_a_topic_averages_its_posts_rather_than_summing_them():
    """Summing would let a topic climb on post count alone: five ordinary
    posts would outrank one genuinely fast-moving post.
    """
    scores = _score(
        [
            [_m(likes=100, replies=10, reposts=20, age_hours=1) for _ in range(5)],
            [_m(likes=400, replies=40, reposts=80, age_hours=1)],
        ]
    )

    assert scores[1] > scores[0]


@pytest.mark.parametrize(
    "higher,lower",
    [("trending", "cooling"), ("cooling", "stale"), ("trending", "stale")],
)
def test_status_orders_topics_with_an_identical_base(higher, lower):
    """Every engagement figure is equal, so the status term is the only thing
    that can separate these.
    """
    scores = _score([[_m(status=higher)], [_m(status=lower)]])

    assert scores[0] > scores[1]


def test_a_topic_spanning_trending_and_stale_scores_as_trending():
    """Max, not mean. Under mean, topic 0 averages to 0.5 and ties with the
    two cooling posts, so this pair is exactly what discriminates them.
    """
    scores = _score(
        [
            [_m(status="trending", trend="x"), _m(status="stale", trend="y")],
            [_m(status="cooling", trend="p"), _m(status="cooling", trend="q")],
        ]
    )

    assert scores[0] > scores[1]


def test_a_uniformly_trending_run_outscores_a_uniformly_stale_one():
    """The regression test for NOT normalising the status term.

    Min-max over a list where every entry is equal returns zeros by design,
    so under normalisation these two runs would produce identical scores and
    the axis would fall silent exactly when every trend agrees. Ranking cannot
    catch this — only the values can.
    """
    trending = _score([[_m(likes=100)], [_m(likes=50)]])
    stale = _score([[_m(likes=100, status="stale")], [_m(likes=50, status="stale")]])

    assert trending[0] > stale[0]
    assert trending[1] > stale[1]


def test_previous_sub_scores_are_ignored():
    """Bluesky reports its own movement, so history is redundant. Passing
    wildly different histories must not move the output at all.
    """
    per_topic = [[_m(likes=100)], [_m(likes=50)]]

    assert _score(per_topic, previous=[None, None]) == _score(
        per_topic, previous=[0.0, 1.0]
    )


def test_scores_stay_within_the_unit_interval():
    """The whole cross-platform comparison rests on this range."""
    scores = _score(
        [
            [_m(likes=500000, replies=90000, reposts=90000, age_hours=0.1)],
            [_m(likes=1, replies=0, reposts=0, age_hours=500, status="stale")],
            [_m(likes=50, replies=5, reposts=5, age_hours=10, status="cooling")],
        ]
    )

    assert all(0.0 <= s <= 1.0 for s in scores)


def test_the_age_floor_stops_a_minutes_old_post_dominating():
    """Without MIN_AGE_HOURS a post seconds old divides by nearly zero and
    swamps the run purely for being new. Three topics, so normalisation has a
    real range and the assertion cannot pass on all-zeros.
    """
    scores = _score(
        [
            [_m(likes=100, replies=10, reposts=20, age_hours=0.01)],
            [_m(likes=100, replies=10, reposts=20, age_hours=0.5)],
            [_m(likes=1000, replies=100, reposts=200, age_hours=1)],
        ]
    )

    assert scores[0] == scores[1]
    assert scores[2] > scores[0]


def test_weights_redirect_the_score_between_the_terms_they_name():
    """The defaults sum to 1.0, which makes the rescale a no-op and lets a
    swapped pair of weight fields go unnoticed. Zeroing likes and reposts
    means the heavily replied topic must win despite having neither.
    """
    weights = ScoreWeights(
        platforms={
            "bluesky": BlueskyWeights(
                like_velocity=0.0,
                reply_velocity=1.0,
                repost_velocity=0.0,
                rank_delta=0.0,
            )
        }
    )
    scorer = build_scorer("bluesky", weights, NOW)

    scores = scorer.score(
        per_topic=[
            [_m(likes=10000, replies=1, reposts=10000)],
            [_m(likes=1, replies=10000, reposts=1)],
        ],
        previous=[None, None],
    )

    assert scores == [0.0, 1.0]


@pytest.mark.parametrize(
    "like_w,reply_w,repost_w,want",
    [
        # Sum 3.0: without the rescale the winning topic's base is 3.0 and
        # blend carries the score straight out of the unit interval.
        (1.0, 1.0, 1.0, [1.0, 0.0]),
        # Sum 0.0: the `if base_total else 0.0` guard, otherwise a
        # ZeroDivisionError the moment all three velocities are zeroed.
        (0.0, 0.0, 0.0, [0.0, 0.0]),
    ],
)
def test_the_base_is_rescaled_by_the_weights_it_was_built_from(
    like_w, reply_w, repost_w, want
):
    """Every other weighting test uses weights summing to 1.0, which makes the
    rescale an exact no-op. These do not.
    """
    weights = ScoreWeights(
        platforms={
            "bluesky": BlueskyWeights(
                like_velocity=like_w,
                reply_velocity=reply_w,
                repost_velocity=repost_w,
                rank_delta=0.0,
            )
        }
    )
    scorer = build_scorer("bluesky", weights, NOW)

    scores = scorer.score(
        per_topic=[
            [_m(likes=1000, replies=1000, reposts=1000, age_hours=1)],
            [_m(likes=1, replies=1, reposts=1, age_hours=1)],
        ],
        previous=[None, None],
    )

    assert scores == want


def test_metrics_context_is_the_trend_name():
    """extract.py puts `context` in its prompt, and a Bluesky post is often
    incomprehensible without the trend that gives it its referent.
    """
    assert _m(trend="US-Canada trade talks collapse").context == (
        "US-Canada trade talks collapse"
    )


def test_a_bluesky_only_topic_survives_the_content_bearing_filter():
    """Unlike Wikipedia, a Bluesky post carries text a caption can be written
    from, so it must be able to originate a topic rather than only corroborate.
    Asserting the ClassVar restates the declaration one line below where it is
    written; this is the behaviour that depends on it — score_topics drops any
    topic no content-bearing platform saw.
    """
    items = [
        Item(
            source_id=f"at://did:plc:x/app.bsky.feed.post/{n}",
            title=f"post {n}",
            permalink=f"https://bsky.app/profile/did:plc:x/post/{n}",
            fetched_at=NOW,
            metrics=_m(likes=100 * (n + 1)),
        )
        for n in range(2)
    ]
    topics = [
        Topic(id=f"t{n}", label=f"T{n}", summary="", item_ids=[items[n].source_id])
        for n in range(2)
    ]

    scored = score_topics(topics, items, NOW, previous={})

    assert [topic.id for topic in scored] == ["t0", "t1"]


def test_metrics_reject_an_unknown_status():
    """`status` indexes STATUS_MOVEMENT directly, so a fourth value Bluesky
    starts sending must fail at the boundary rather than as a KeyError in the
    middle of a scoring run. model_validate rather than the constructor
    because ty rejects a bad Literal before pydantic ever sees it.
    """
    with pytest.raises(ValidationError):
        BlueskyMetrics.model_validate(
            {
                "platform": "bluesky",
                "like_count": 100,
                "reply_count": 10,
                "repost_count": 20,
                "trend": "a trend",
                "status": "smouldering",
                "created_at": "2026-08-23T10:00:00Z",
            }
        )
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/test_scorers_bluesky.py -v
```

Expected: FAIL — `ImportError: cannot import name 'BlueskyMetrics' from 'zeitgeist.models'`.

- [ ] **Step 3: Add `BlueskyMetrics` to `models.py`**

Insert after `WikipediaMetrics`, before the `Metrics` union:

```python
class BlueskyMetrics(BaseModel):
    """Engagement as Bluesky reports it, plus the trend the post came from."""

    model_config = STRICT

    platform: Literal["bluesky"] = "bluesky"
    # A post carries its own text, so Bluesky can originate topics.
    content_bearing: ClassVar[bool] = True

    like_count: int
    reply_count: int
    repost_count: int
    # Trend-level, duplicated onto every post from that trend — as Lemmy's
    # `channel` is community-level. `trend` gives the extraction prompt the
    # referent a short post usually omits; `status` is the scorer's movement
    # term, reported by Bluesky rather than inferred from our own history.
    trend: str
    status: Literal["trending", "cooling", "stale"]
    # From the payload's `indexedAt`, never `record.createdAt`: the latter is
    # client-supplied, and the scorer divides engagement by age.
    created_at: datetime

    @property
    def context(self) -> str:
        return self.trend
```

Then extend the union:

```python
Metrics = Annotated[
    LemmyMetrics | WikipediaMetrics | BlueskyMetrics,
    Field(discriminator="platform"),
]
```

- [ ] **Step 4: Add `BlueskyMetrics` to the model field-set guard**

In `tests/test_models.py`, add `BlueskyMetrics` to the import from `zeitgeist.models`, and add this entry to the `@pytest.mark.parametrize` list in `test_models_carry_exactly_the_specified_fields`:

```python
        (
            BlueskyMetrics,
            {
                "platform",
                "like_count",
                "reply_count",
                "repost_count",
                "trend",
                "status",
                "created_at",
            },
        ),
```

- [ ] **Step 5: Add `BlueskyWeights` to `base.py`**

Add the class after `WikipediaWeights`:

```python
class BlueskyWeights(PlatformWeights):
    """No spread term. Bluesky caps at 25 trends and has already clustered
    posts into them, so distinct-trend counts would be near-constant and
    `normalise` would silently zero the axis. Repost velocity measures the
    same property — travel beyond the origin audience — directly.
    """

    platform: Literal["bluesky"] = "bluesky"

    like_velocity: float = 0.35
    reply_velocity: float = 0.30
    repost_velocity: float = 0.35
```

Extend the union and the default mapping:

```python
PlatformWeightsUnion = Annotated[
    LemmyWeights | WikipediaWeights | BlueskyWeights,
    Field(discriminator="platform"),
]
```

```python
    platforms: dict[str, PlatformWeightsUnion] = Field(
        default_factory=lambda: {
            "lemmy": LemmyWeights(),
            "wikipedia": WikipediaWeights(),
            "bluesky": BlueskyWeights(),
        }
    )
```

- [ ] **Step 6: Write `BlueskyScorer`**

Create `zeitgeist/analysis/scorers/bluesky.py`:

```python
"""Bluesky trend scoring: engagement velocity, and the platform's own status.

Pure Python on purpose: reproducible and unit-testable, which an LLM's
numeric judgment is not.
"""

from datetime import datetime

from zeitgeist.analysis.scorers.base import (
    BlueskyWeights,
    ScoreWeights,
    blend,
    normalise,
)
from zeitgeist.models import BlueskyMetrics

MIN_AGE_HOURS = 0.5

# Bluesky reports movement directly, so unlike the other scorers this one
# never consults the previous run.
STATUS_MOVEMENT = {"trending": 1.0, "cooling": 0.5, "stale": 0.0}


class BlueskyScorer:
    platform = "bluesky"

    def __init__(self, weights: ScoreWeights, now: datetime) -> None:
        self._weights = weights.for_platform("bluesky", BlueskyWeights)
        self._now = now

    def score(
        self, per_topic: list[list[BlueskyMetrics]], previous: list[float | None]
    ) -> list[float]:
        """`previous` is unused: Bluesky supplies its own movement term, which
        is better informed than a diff of our normalised scores and works on a
        first run when there is no history. WikipediaScorer likewise ignores
        `now`; the protocol offers both to every scorer and using them is
        optional.
        """
        weights = self._weights

        lv = normalise([self._mean_velocity(g, "like_count") for g in per_topic])
        rv = normalise([self._mean_velocity(g, "reply_count") for g in per_topic])
        pv = normalise([self._mean_velocity(g, "repost_count") for g in per_topic])

        base_total = (
            weights.like_velocity + weights.reply_velocity + weights.repost_velocity
        )
        bases = [
            (
                weights.like_velocity * lv[i]
                + weights.reply_velocity * rv[i]
                + weights.repost_velocity * pv[i]
            )
            / base_total
            if base_total
            else 0.0
            for i in range(len(per_topic))
        ]

        # Max rather than mean: a topic appearing in one trending and one
        # stale trend is trending.
        #
        # Deliberately NOT normalised, unlike every other movement term here.
        # 0.0/0.5/1.0 mean fixed things, and all 25 trends can share a status
        # — in which case min-max returns zeros and the axis falls silent
        # exactly when it has the most to say.
        movement = [max(STATUS_MOVEMENT[m.status] for m in g) for g in per_topic]

        return blend(bases, movement, weights.rank_delta)

    def _mean_velocity(self, group: list[BlueskyMetrics], attribute: str) -> float:
        values = []
        for metrics in group:
            hours = (self._now - metrics.created_at).total_seconds() / 3600.0
            values.append(getattr(metrics, attribute) / max(hours, MIN_AGE_HOURS))
        return sum(values) / len(values)
```

- [ ] **Step 7: Register the scorer**

In `zeitgeist/analysis/scorers/__init__.py`, add the import and the entry:

```python
from zeitgeist.analysis.scorers.bluesky import BlueskyScorer
```

```python
SCORERS: dict[str, ScorerBuilder] = {
    "lemmy": LemmyScorer,
    "wikipedia": WikipediaScorer,
    "bluesky": BlueskyScorer,
}
```

- [ ] **Step 8: Run the tests to verify they pass**

```bash
uv run pytest tests/test_scorers_bluesky.py tests/test_scorers_registry.py tests/test_models.py -v
```

Expected: PASS. `test_every_metrics_platform_has_a_scorer` is the one that would catch a half-landed platform.

- [ ] **Step 9: Run the full gate**

```bash
uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest
```

- [ ] **Step 10: Commit**

```bash
git add zeitgeist/models.py zeitgeist/analysis/scorers/ tests/test_scorers_bluesky.py tests/test_models.py
git commit -m "Add BlueskyMetrics, BlueskyWeights and BlueskyScorer"
```

---

## Task 4: `BlueskySource`

The two-step fetch. `getTrends` returns 25 trends, each carrying a `link` that is a **web UI path**; converting it to an `at://` **record address** is what lets `getFeed` return that trend's posts. Read the spec's "How a trend becomes a list of posts" before starting — the conversion is the only non-obvious part of this task.

**Files:**
- Create: `zeitgeist/sources/bluesky.py`
- Modify: `zeitgeist/sources/__init__.py`
- Modify: `zeitgeist/config.py:16` (`KNOWN_SOURCES`) and the `Settings` body
- Modify: `tests/conftest.py` (`_SETTINGS_ENV_VARS`)
- Modify: `README.md:24-46` (Sources section), `.env.example`
- Test: `tests/test_sources_bluesky.py` (create)

**Interfaces:**
- Consumes: `zeitgeist.models.BlueskyMetrics` from Task 3; `Item`, `SourceError`, `Settings`.
- Produces: `BlueskySource` with `name = "bluesky"`, `__init__(api_base: str = "https://api.bsky.app", client: Any = None)`, `from_settings(cls, settings) -> BlueskySource`, and `fetch(limit: int) -> list[Item]`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_sources_bluesky.py`:

```python
"""BlueskySource fetches in two steps: getTrends, then getFeed per trend.

The fake client routes on endpoint rather than replaying a queue, because the
two endpoints return different shapes and the source calls one of them 25
times.
"""

from datetime import UTC, datetime

import httpx
import pytest

from zeitgeist.config import Settings
from zeitgeist.sources.base import SourceError
from zeitgeist.sources.bluesky import BlueskySource

TREND_DID = "did:plc:trendingservice"
AUTHOR_DID = "did:plc:someauthor"


def _trend(rkey: str, name: str, status: str = "trending") -> dict:
    return {
        "topic": rkey,
        "displayName": name,
        "description": "a description",
        "link": f"/profile/{TREND_DID}/feed/{rkey}",
        "startedAt": "2026-08-23T04:00:00.000Z",
        "postCount": 100,
        "status": status,
        "category": "politics",
        "actors": [],
    }


def _post(
    rkey: str,
    text: str = "something happened",
    *,
    likes: int = 10,
    replies: int = 2,
    reposts: int = 3,
    indexed: str = "2026-08-23T10:00:00.000Z",
    created: str = "2026-08-23T09:59:59.000Z",
    langs: list[str] | None = None,
    labels: list[dict] | None = None,
    did: str = AUTHOR_DID,
) -> dict:
    record: dict = {
        "$type": "app.bsky.feed.post",
        "text": text,
        "createdAt": created,
    }
    if langs is not None:
        record["langs"] = langs
    return {
        "post": {
            "uri": f"at://{did}/app.bsky.feed.post/{rkey}",
            "cid": "bafyreiexample",
            # Present because the real postView always carries it, and
            # deliberately never read: no model in this project holds an
            # author, and tests/test_models.py guards that. Trimming a fixture
            # to what the code reads today lets a later change reference a
            # field that was never in the test data.
            "author": {
                "did": did,
                "handle": "someone.bsky.social",
                "displayName": "Someone",
                "avatar": "https://cdn.bsky.app/img/avatar/plain/abc@jpeg",
                "createdAt": "2024-01-01T00:00:00.000Z",
                "labels": [],
                "viewer": {"muted": False, "blockedBy": False},
            },
            "record": record,
            "likeCount": likes,
            "replyCount": replies,
            "repostCount": reposts,
            "quoteCount": 0,
            "bookmarkCount": 0,
            "indexedAt": indexed,
            "viewer": {"threadMuted": False, "embeddingDisabled": False},
            "labels": labels or [],
        }
    }


class _Response:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class _FakeClient:
    """`trends` is a payload or an Exception. `feeds` maps rkey to either."""

    def __init__(
        self, trends: dict | Exception, feeds: dict[str, dict | Exception]
    ) -> None:
        self._trends = trends
        self._feeds = feeds
        self.calls: list[tuple[str, dict]] = []

    def get(self, url: str, params: dict | None = None, **kwargs: object) -> _Response:
        params = params or {}
        self.calls.append((url, params))
        if "getTrends" in url:
            # Bound to a local so ty can narrow away the Exception arm;
            # narrowing does not carry across repeated attribute reads.
            trends = self._trends
            if isinstance(trends, Exception):
                raise trends
            return _Response(trends)
        if "getFeed" in url:
            rkey = str(params["feed"]).rsplit("/", 1)[-1]
            result = self._feeds[rkey]
            if isinstance(result, Exception):
                raise result
            return _Response(result)
        raise AssertionError(f"unexpected URL {url}")


def _source(
    trends: dict | Exception, feeds: dict[str, dict | Exception]
) -> BlueskySource:
    return BlueskySource(client=_FakeClient(trends, feeds))


def _one_trend_one_post(**post_kwargs) -> BlueskySource:
    return _source(
        {"trends": [_trend("t1", "A trend")]},
        {"t1": {"feed": [_post("p1", **post_kwargs)]}},
    )


def test_a_post_becomes_an_item_carrying_its_trend():
    """`trend` is what extract.py reads as `context`, and a short Bluesky post
    is often incomprehensible without it.
    """
    items = _one_trend_one_post().fetch(limit=10)

    assert len(items) == 1
    assert items[0].title == "something happened"
    assert items[0].metrics.trend == "A trend"
    assert items[0].context == "A trend"


def test_engagement_counts_are_carried_through():
    items = _one_trend_one_post(likes=41, replies=7, reposts=13).fetch(limit=10)

    assert items[0].metrics.like_count == 41
    assert items[0].metrics.reply_count == 7
    assert items[0].metrics.repost_count == 13


def test_the_trend_status_is_carried_onto_every_post():
    source = _source(
        {"trends": [_trend("t1", "A cooling trend", status="cooling")]},
        {"t1": {"feed": [_post("p1"), _post("p2")]}},
    )

    items = source.fetch(limit=10)

    assert [item.metrics.status for item in items] == ["cooling", "cooling"]


def test_created_at_comes_from_indexed_at_not_the_client_clock():
    """record.createdAt is client-supplied and unverified; the scorer divides
    engagement by age, so a back-dated post would report a false velocity.
    The two values are a year and a half apart here, so a source reading the
    wrong field cannot pass by coincidence.
    """
    items = _one_trend_one_post(
        indexed="2026-08-23T10:00:00.000Z",
        created="2025-01-01T00:00:00.000Z",
    ).fetch(limit=10)

    assert items[0].metrics.created_at == datetime(2026, 8, 23, 10, 0, tzinfo=UTC)


def test_permalink_is_built_from_the_at_uri():
    """An at:// URI is an identifier, not an address, so unlike Lemmy's ap_id
    it cannot be used as the permalink directly.
    """
    items = _one_trend_one_post().fetch(limit=10)

    assert items[0].source_id == f"at://{AUTHOR_DID}/app.bsky.feed.post/p1"
    assert items[0].permalink == f"https://bsky.app/profile/{AUTHOR_DID}/post/p1"


def test_the_feed_is_requested_by_at_uri_built_from_the_trend_link():
    """The link is a web UI path; getFeed needs a record address. The `feed`
    segment of the path becomes the lexicon name.
    """
    source = _source(
        {"trends": [_trend("t1", "A trend")]},
        {"t1": {"feed": [_post("p1")]}},
    )

    source.fetch(limit=10)

    feed_calls = [p for url, p in source._client.calls if "getFeed" in url]
    assert feed_calls[0]["feed"] == (
        f"at://{TREND_DID}/app.bsky.feed.generator/t1"
    )


def test_non_english_posts_are_dropped():
    source = _source(
        {"trends": [_trend("t1", "A trend")]},
        {
            "t1": {
                "feed": [
                    _post("p1", "in English", langs=["en"]),
                    _post("p2", "auf Deutsch", langs=["de"]),
                ]
            }
        },
    )

    items = source.fetch(limit=10)

    assert [item.title for item in items] == ["in English"]


def test_a_post_declaring_no_language_is_kept():
    """`langs` is optional and client-set, so absence means unknown rather
    than non-English. Dropping these would discard 7% of a real fetch.
    """
    items = _one_trend_one_post(text="no langs field", langs=None).fetch(limit=10)

    assert [item.title for item in items] == ["no langs field"]


def test_a_multilingual_post_including_english_is_kept():
    items = _one_trend_one_post(text="bilingual", langs=["de", "en"]).fetch(limit=10)

    assert [item.title for item in items] == ["bilingual"]


def test_labelled_posts_are_dropped():
    """Trend feeds appear to filter already, so this changes nothing today and
    exists so a change upstream cannot put graphic content into a meme.
    """
    source = _source(
        {"trends": [_trend("t1", "A trend")]},
        {
            "t1": {
                "feed": [
                    _post("p1", "clean"),
                    _post("p2", "graphic", labels=[{"val": "porn"}]),
                ]
            }
        },
    )

    items = source.fetch(limit=10)

    assert [item.title for item in items] == ["clean"]


def test_empty_text_posts_are_dropped():
    """Item.title would be blank and the extraction prompt would have nothing
    to label.
    """
    source = _source(
        {"trends": [_trend("t1", "A trend")]},
        {"t1": {"feed": [_post("p1", "   "), _post("p2", "real text")]}},
    )

    items = source.fetch(limit=10)

    assert [item.title for item in items] == ["real text"]


def test_a_post_in_two_trends_yields_one_item_keeping_the_first_trend():
    source = _source(
        {"trends": [_trend("t1", "First trend"), _trend("t2", "Second trend")]},
        {
            "t1": {"feed": [_post("shared")]},
            "t2": {"feed": [_post("shared")]},
        },
    )

    items = source.fetch(limit=10)

    assert len(items) == 1
    assert items[0].metrics.trend == "First trend"


def test_a_malformed_trend_link_skips_only_that_trend():
    """`link` is a UI path, not a documented contract, so a future variant
    must cost one trend rather than the run.
    """
    broken = _trend("t1", "Broken")
    broken["link"] = "/some/unexpected/shape"
    source = _source(
        {"trends": [broken, _trend("t2", "Fine")]},
        {"t2": {"feed": [_post("p2", "survivor")]}},
    )

    items = source.fetch(limit=10)

    assert [item.title for item in items] == ["survivor"]


def test_one_failing_feed_skips_only_that_trend():
    source = _source(
        {"trends": [_trend("t1", "Broken"), _trend("t2", "Fine")]},
        {
            "t1": httpx.ConnectError("boom"),
            "t2": {"feed": [_post("p2", "survivor")]},
        },
    )

    items = source.fetch(limit=10)

    assert [item.title for item in items] == ["survivor"]


def test_a_failing_trends_call_raises_source_error():
    """Without trends there is no way into the content, so there is no partial
    result to salvage.
    """
    with pytest.raises(SourceError):
        _source(httpx.ConnectError("boom"), {}).fetch(limit=10)


def test_no_trends_raises_source_error():
    with pytest.raises(SourceError):
        _source({"trends": []}, {}).fetch(limit=10)


def test_every_feed_failing_raises_source_error():
    source = _source(
        {"trends": [_trend("t1", "One"), _trend("t2", "Two")]},
        {"t1": httpx.ConnectError("boom"), "t2": httpx.ConnectError("boom")},
    )

    with pytest.raises(SourceError):
        source.fetch(limit=10)


def test_every_post_being_filtered_out_raises_source_error():
    source = _source(
        {"trends": [_trend("t1", "A trend")]},
        {"t1": {"feed": [_post("p1", "auf Deutsch", langs=["de"])]}},
    )

    with pytest.raises(SourceError):
        source.fetch(limit=10)


def test_a_changed_payload_shape_propagates_rather_than_being_swallowed():
    """A missing key is a contract break, not an outage, so it must crash
    rather than look like an empty platform.
    """
    trend = _trend("t1", "A trend")
    del trend["status"]
    source = _source({"trends": [trend]}, {"t1": {"feed": [_post("p1")]}})

    with pytest.raises(KeyError):
        source.fetch(limit=10)


def test_the_budget_splits_across_trends():
    """Four trends and a budget of 8 means 2 posts asked of each, rather than
    the first trend swallowing the run.
    """
    trends = [_trend(f"t{i}", f"Trend {i}") for i in range(4)]
    feeds = {f"t{i}": {"feed": [_post(f"p{i}")]} for i in range(4)}
    source = _source({"trends": trends}, feeds)

    source.fetch(limit=8)

    feed_calls = [p for url, p in source._client.calls if "getFeed" in url]
    assert len(feed_calls) == 4
    assert all(call["limit"] == 2 for call in feed_calls)


def test_limit_is_an_upper_bound_on_items_returned():
    trends = [_trend("t1", "One"), _trend("t2", "Two")]
    feeds = {
        "t1": {"feed": [_post(f"a{i}") for i in range(5)]},
        "t2": {"feed": [_post(f"b{i}") for i in range(5)]},
    }
    source = _source({"trends": trends}, feeds)

    assert len(source.fetch(limit=3)) == 3


def test_the_trend_listing_is_requested_at_the_api_cap():
    """getTrends returns 400 above 25, so the source always asks for exactly
    the maximum.
    """
    source = _one_trend_one_post()

    source.fetch(limit=10)

    trend_calls = [p for url, p in source._client.calls if "getTrends" in url]
    assert trend_calls[0]["limit"] == 25


def test_feed_requests_never_exceed_the_api_page_cap():
    """getFeed rejects a limit above 100. ceil(limit / len(trends)) overshoots
    whenever few trends come back — the default post_limit of 500 split across
    two trends asks for 250 — and every feed call 400s, so the whole run looks
    like an outage.
    """
    source = _source(
        {"trends": [_trend("t1", "One"), _trend("t2", "Two")]},
        {"t1": {"feed": [_post("a1")]}, "t2": {"feed": [_post("b1")]}},
    )

    source.fetch(limit=500)

    feed_calls = [p for url, p in source._client.calls if "getFeed" in url]
    assert [call["limit"] for call in feed_calls] == [100, 100]


def test_requests_go_to_the_configured_api_base():
    """The base URL is the one setting that decides which host is scraped,
    and __init__ strips a trailing slash off it. Neither fact shows up until
    a request is made: reading `_api_base` back passes even if the URL
    builders interpolate the module default and ignore it.
    """
    source = BlueskySource(
        api_base="https://mirror.example/",
        client=_FakeClient(
            {"trends": [_trend("t1", "A trend")]},
            {"t1": {"feed": [_post("p1")]}},
        ),
    )

    source.fetch(limit=10)

    assert [url for url, _ in source._client.calls] == [
        "https://mirror.example/xrpc/app.bsky.unspecced.getTrends",
        "https://mirror.example/xrpc/app.bsky.feed.getFeed",
    ]


def test_from_settings_wires_the_api_base_into_the_request():
    """from_settings is plumbing, so it fails silently: a mis-assigned base
    only shows up in the request it produces.
    """
    settings = Settings(_env_file=None, bluesky_api_base="https://mirror.example")
    source = BlueskySource.from_settings(settings)
    source._client = _FakeClient(
        {"trends": [_trend("t1", "A trend")]},
        {"t1": {"feed": [_post("p1")]}},
    )

    source.fetch(limit=10)

    assert source._client.calls[0][0] == (
        "https://mirror.example/xrpc/app.bsky.unspecced.getTrends"
    )


def test_bluesky_is_a_known_source():
    """Settings rejects unknown names, so without this SOURCES=bluesky fails
    at startup.
    """
    assert Settings(_env_file=None, sources="bluesky").sources == ["bluesky"]
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/test_sources_bluesky.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'zeitgeist.sources.bluesky'`.

- [ ] **Step 3: Write the source**

Create `zeitgeist/sources/bluesky.py`:

```python
"""Bluesky ingestion via the public AT Protocol AppView.

Needs no credentials: these endpoints accept unauthenticated requests. Fetches
in two steps. `getTrends` returns what is trending; each trend carries a `link`
which is a *web UI path*, and Bluesky maintains a live feed generator behind
it. Converting that path to an `at://` *record address* is what lets `getFeed`
return the trend's posts.

    link  /profile/{did}/feed/{rkey}
    uri   at://{did}/app.bsky.feed.generator/{rkey}

So the source never selects or ranks posts for a topic — Bluesky already has,
and this reads the result.
"""

import logging
import math
import re
from datetime import UTC, datetime
from typing import Any

import httpx

from zeitgeist.config import Settings
from zeitgeist.models import BlueskyMetrics, Item
from zeitgeist.sources.base import SourceError

log = logging.getLogger(__name__)

DEFAULT_API_BASE = "https://api.bsky.app"
TIMEOUT_SECONDS = 30.0
# getTrends returns 400 above 25, so this is a ceiling rather than a tuning
# parameter: the source can never see more than 25 topics per run.
TREND_LIMIT = 25
# getFeed's own maximum.
MAX_FEED_PAGE = 100
USER_AGENT = "zeitgeist-actualiser/0.1"

# `/profile/{did}/feed/{rkey}`. Not a documented contract — it is the path the
# web app renders — so a link that does not match costs one trend, not the run.
LINK_PATTERN = re.compile(r"^/profile/(?P<did>[^/]+)/feed/(?P<rkey>[^/]+)$")

LANGUAGE = "en"


class BlueskySource:
    name = "bluesky"

    def __init__(self, api_base: str = DEFAULT_API_BASE, client: Any = None) -> None:
        self._api_base = api_base.rstrip("/")
        self._client = client or httpx.Client(
            timeout=TIMEOUT_SECONDS, headers={"User-Agent": USER_AGENT}
        )

    @classmethod
    def from_settings(cls, settings: Settings) -> BlueskySource:
        return cls(api_base=settings.bluesky_api_base)

    def fetch(self, limit: int) -> list[Item]:
        fetched_at = datetime.now(UTC)

        # Only transport failure is tolerated. A KeyError from a changed
        # payload propagates: that is a contract break, not an outage.
        try:
            trends = self._fetch_trends()
        except httpx.HTTPError as exc:
            raise SourceError(f"Bluesky trends unavailable: {exc}") from exc

        if not trends:
            raise SourceError("Bluesky returned no trends")

        per_trend = min(MAX_FEED_PAGE, max(1, math.ceil(limit / len(trends))))

        seen: dict[str, Item] = {}
        for trend in trends:
            match = LINK_PATTERN.match(trend["link"])
            if match is None:
                log.warning("Skipping Bluesky trend with link %r", trend["link"])
                continue

            uri = (
                f"at://{match['did']}/app.bsky.feed.generator/{match['rkey']}"
            )
            try:
                views = self._fetch_feed(uri, per_trend)
            except httpx.HTTPError as exc:
                log.warning("Skipping Bluesky trend %s: %s", trend["topic"], exc)
                continue

            # Mapping is pure: a bug here must crash, not look like an
            # unreachable trend.
            for view in views:
                post = view["post"]
                if not _is_usable(post):
                    continue
                # First trend wins, mirroring LemmySource's dedup.
                if post["uri"] in seen:
                    continue
                seen[post["uri"]] = _to_item(post, trend, fetched_at)
                if len(seen) >= limit:
                    return list(seen.values())

        if not seen:
            raise SourceError("Bluesky returned no usable posts")
        return list(seen.values())

    def _fetch_trends(self) -> list[dict[str, Any]]:
        response = self._client.get(
            f"{self._api_base}/xrpc/app.bsky.unspecced.getTrends",
            params={"limit": TREND_LIMIT},
        )
        response.raise_for_status()
        return response.json()["trends"]

    def _fetch_feed(self, uri: str, limit: int) -> list[dict[str, Any]]:
        response = self._client.get(
            f"{self._api_base}/xrpc/app.bsky.feed.getFeed",
            params={"feed": uri, "limit": limit},
        )
        response.raise_for_status()
        return response.json()["feed"]


def _is_usable(post: dict[str, Any]) -> bool:
    if post["labels"]:
        return False
    if not post["record"]["text"].strip():
        return False
    # `langs` is optional and client-set, so absence means unknown rather than
    # non-English. Dropping those would discard a real share of every fetch.
    langs = post["record"].get("langs")
    return langs is None or LANGUAGE in langs


def _to_item(
    post: dict[str, Any], trend: dict[str, Any], fetched_at: datetime
) -> Item:
    did, rkey = _split_uri(post["uri"])
    return Item(
        source_id=post["uri"],
        # Posts cap at 300 graphemes, so the text fits a title without
        # truncation and there is no separate body to excerpt.
        title=post["record"]["text"].strip(),
        body_excerpt=None,
        # Built, not copied: an at:// URI is an identifier, not an address.
        permalink=f"https://bsky.app/profile/{did}/post/{rkey}",
        fetched_at=fetched_at,
        metrics=BlueskyMetrics(
            like_count=post["likeCount"],
            reply_count=post["replyCount"],
            repost_count=post["repostCount"],
            trend=trend["displayName"],
            status=trend["status"],
            # `indexedAt`, assigned by the relay, never `record.createdAt`,
            # which the posting client supplies and can back- or future-date.
            # The scorer divides engagement by age, so a future date would
            # yield a negative denominator.
            created_at=_parse_timestamp(post["indexedAt"]),
        ),
    )


def _split_uri(uri: str) -> tuple[str, str]:
    """`at://{did}/{collection}/{rkey}` -> (did, rkey)."""
    parts = uri.removeprefix("at://").split("/")
    return parts[0], parts[-1]


def _parse_timestamp(raw: str) -> datetime:
    """The scorer subtracts this from an aware `now`, so a naive value would
    raise three stages later rather than here.
    """
    parsed = datetime.fromisoformat(raw)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
```

- [ ] **Step 4: Wire up config and the source registry**

In `zeitgeist/config.py`, extend `KNOWN_SOURCES` and add the setting beside the Wikipedia ones:

```python
KNOWN_SOURCES: tuple[str, ...] = ("lemmy", "wikipedia", "bluesky")
```

```python
    # Exists so the host can be pointed at a mirror or a test double, not
    # because anyone is expected to change it. `public.api.bsky.app` is NOT a
    # valid substitute: it returns 403 on parts of the API.
    bluesky_api_base: str = "https://api.bsky.app"
```

In `zeitgeist/sources/__init__.py`, add the import and the entry:

```python
from zeitgeist.sources.bluesky import BlueskySource
```

```python
BUILDERS: dict[str, Callable[[Settings], Source]] = {
    "lemmy": LemmySource.from_settings,
    "wikipedia": WikipediaSource.from_settings,
    "bluesky": BlueskySource.from_settings,
}
```

In `tests/conftest.py`, add `"BLUESKY_API_BASE"` to `_SETTINGS_ENV_VARS`. That tuple's stated invariant is that it names every environment variable `Settings` reads, and the autouse fixture strips them so a result never depends on who is running the suite. The tests in this task pass the value explicitly and so are immune, but the invariant breaks silently for the next test that does not — and this repo has already deleted one test for failing against a developer's modified `.env`.

- [ ] **Step 5: Run the tests to verify they pass**

```bash
uv run pytest tests/test_sources_bluesky.py tests/test_sources_composite.py -v
```

Expected: PASS. `test_every_known_source_has_a_builder` in the composite test file is the registry-drift guard.

- [ ] **Step 6: Document the source**

In `.env.example`, add after the Wikipedia block:

```
BLUESKY_API_BASE=https://api.bsky.app
```

and change the first line to `SOURCES=lemmy,wikipedia,bluesky`.

In `README.md`, add to the Sources section after the Wikipedia paragraphs:

```markdown
`bluesky` adds Bluesky posts and needs no credentials — the AT Protocol
AppView answers these endpoints unauthenticated. It fetches in two steps: the
25 current trends, then the posts behind each one. Bluesky maintains a live
feed for every trend, so the ranking within a topic is the platform's own
rather than ours.

Like Lemmy it is content-bearing, so it can originate topics rather than only
corroborate them. Unlike Lemmy its audience is general rather than technical,
which is the reason it is here. Two caveats worth knowing: trending skews
heavily toward US politics, which the sentiment weights push back against
rather than the source filtering out; and trend discovery uses an endpoint in
Bluesky's `unspecced` namespace, which is explicitly not a stable API. Reading
the posts themselves uses stable endpoints.

`BLUESKY_API_BASE` exists to point at a mirror and should not normally be
changed. Note that `public.api.bsky.app` is not a valid substitute — it
returns 403 on parts of the API.
```

- [ ] **Step 7: Run the full gate**

```bash
uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest
```

Expected: all four pass.

- [ ] **Step 8: Verify against the live API**

The tests use fakes, so run once against the real thing before calling this done:

```bash
uv run python -c "from zeitgeist.sources.bluesky import BlueskySource; items = BlueskySource().fetch(limit=20); print(len(items)); print(items[0].title[:80]); print(items[0].context); print(items[0].permalink)"
```

Expected: 20 items, a real post title, a real trend name as context, and a `https://bsky.app/profile/...` permalink. If this fails while the tests pass, the fake payloads have drifted from the real shape — fix the fakes, not just the source.

- [ ] **Step 9: Commit**

```bash
git add zeitgeist/sources/ zeitgeist/config.py tests/test_sources_bluesky.py tests/conftest.py README.md .env.example
git commit -m "Add BlueskySource fetching trends and the posts behind them"
```

---

## Self-Review

**Spec coverage.** Walked each spec section against the tasks:

| Spec section | Task |
|---|---|
| Weights model, `PlatformWeights` + subclasses | 2 (Bluesky's subclass in 3) |
| Keeping the registry uniform / `for_platform` | 2 |
| Shared blend helpers | 1 |
| `BlueskySource`, two-step fetch | 4 |
| How a trend becomes a list of posts | 4, step 3 docstring |
| Filtering (language, labels, dedup) | 4 |
| Item mapping, permalink construction | 4 |
| `BlueskyMetrics`, `indexedAt` | 3 (model), 4 (population + test) |
| `BlueskyScorer`, status not normalised | 3 |
| Dropped trend spread | 3, `BlueskyWeights` docstring |
| Failure behaviour | 4 |
| Configuration | 4 |
| Testing | every task |
| Implementation sequence | task order |

Two spec items are correctly absent: wiring weights to `Settings` and category filtering are both listed under "Deferred" and "Out of scope".

**Deviation from the spec's phasing.** The spec's phase 3 lumps metrics, scorer and source into one. This plan splits it at the metrics/scorer boundary because `test_every_metrics_platform_has_a_scorer` forces model and scorer to land together, while `test_every_source_has_a_scorer` explicitly permits the source to arrive later. Four tasks, same order, same commit boundaries.

**Placeholder scan.** No TBD, TODO, "handle edge cases", or "similar to Task N". Every code step carries real code; every test step carries real tests.

**Type consistency.** Checked across tasks: `historical_delta` / `blend` signatures match their call sites in Tasks 1-3; `for_platform` is defined in Task 2 and called in Tasks 2 and 3; `BlueskyMetrics` field names in Task 3's model match Task 4's construction (`like_count`/`reply_count`/`repost_count`/`trend`/`status`/`created_at`); `BlueskyWeights` field names match `BlueskyScorer`'s reads (`like_velocity`/`reply_velocity`/`repost_velocity`/`rank_delta`); `_api_base` is the attribute name in both Task 4's `__init__` and its `from_settings` test.

**One known coupling.** `tests/test_sources_bluesky.py` reads `source._client.calls`, a private attribute, in six tests. That is deliberate — asserting the `at://` conversion, the budget split, the page cap and the API base all require seeing the requests — and matches how `tests/test_sources_lemmy.py` and `tests/test_sources_wikipedia.py` assert on URLs recorded by their own fakes.

## Test Audit

`reviewing-plan-tests` was run over all four tasks and returned 12 findings, all applied. Four were verified empirically against this checkout before applying, because they claimed the plan would fail its own Definition of Done:

| Claim | Verified |
|---|---|
| `pytest.raises(Exception)` fails ruff `B017` | Yes — reproduced, `B` is in the enabled rule set |
| `status: str` fails `ty` against the model's `Literal` field | Yes — `Expected Literal["trending", "cooling", "stale"], found str` |
| `_FakeClient`'s `object`-typed payloads fail `ty` | Yes — `Expected dict[Unknown, Unknown], found ~Exception` |
| `Settings(...)` in tests passes `_env_file=None` | Yes — all ten existing call sites do |

Findings 7 and 8 would each have blocked an entire task at the gate.

Three change detectors were removed or replaced: `test_wikipedia_weights_carry_only_the_shared_field` and `test_platform_weights_is_not_itself_a_union_member` deleted outright, and `test_bluesky_is_content_bearing` — which restated a `ClassVar` one line below its declaration — replaced with `test_a_bluesky_only_topic_survives_the_content_bearing_filter`, which exercises the behaviour that actually depends on the flag.

Four gaps in coverage were filled: the `getFeed` page cap (a real production failure — `post_limit=500` across two trends asks for 250, which the API rejects with a 400, making the whole run look like an outage), the `/ base_total` rescale and its zero guard, `ScoreWeights`' `extra="forbid"`, and the API base actually reaching a URL.

Two items outside the test code were folded in: `BLUESKY_API_BASE` must join `_SETTINGS_ENV_VARS` in `tests/conftest.py`, and the Task 2 test block's imports belong at the top of the file rather than appended after Task 1's functions, which ruff rejects with `E402`.

**Change-detector pass.** The skill records that its reviewer reliably misses this category, so the remaining tests were walked again asking only *if this failed, would it mean a bug or a changed mind?* Three survive scrutiny that look like candidates: `test_the_trend_listing_is_requested_at_the_api_cap` asserts `limit=25`, which is an API-imposed ceiling rather than a preference — above it Bluesky returns 400; `test_the_budget_splits_across_trends` asserts `limit=2`, which is derived arithmetic rather than a chosen constant; and `test_wikipedia_weights`' replacement asserts rejection behaviour rather than a field list. No further deletions.
