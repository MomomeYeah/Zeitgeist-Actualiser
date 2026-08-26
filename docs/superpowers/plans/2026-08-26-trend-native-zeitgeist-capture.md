# Trend-Native Zeitgeist Capture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Bluesky trend the unit of analysis, ingest reply threads as evidence, and distil each trend into a dossier carrying what happened, what people are saying, and the posture they are taking — so captions are written from facts instead of from a bag of tags.

**Architecture:** `BlueskySource` grows a `fetch_evidence` method returning `TrendEvidence` (trend metadata + posts + verbatim replies), gathered by a three-level concurrent `asyncio` fan-out behind a synchronous call. A new `analysis/phrases.py` mines recurring phrases deterministically, counted by distinct author. A new `analysis/distil.py` makes one LLM call per trend, producing a `Dossier` that becomes the topic's summary, sentiment and register. `extract.py` and `consolidate.py` leave the pipeline; Lemmy and Wikipedia go dormant but keep their code and tests.

**Tech Stack:** Python 3.14, pydantic v2, pydantic-settings, httpx (sync + async), pytest, uv, ruff, ty.

## Global Constraints

- Python 3.14. Use PEP 695 generics (`def f[T: Bound](...)`), never `typing.TypeVar`.
- ruff rules `E, F, I, UP, B, SIM`, line length 88, configured in `pyproject.toml`.
- All new pydantic models use `model_config = STRICT` (`extra="forbid"`) from `zeitgeist/models.py`.
- Fix type errors at the root cause. No blanket `# type: ignore`; a narrow suppression needs a comment explaining why.
- Tests are hermetic. `tests/conftest.py` strips every environment variable `Settings` reads; add any new one to `_SETTINGS_ENV_VARS`.
- Definition of Done, run after every task before committing:

```bash
uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest
```

- Never import from `zeitgeist/analysis/consolidate.py` or `zeitgeist/analysis/extract.py` in live-path code. They become dormant in this plan.
- No model may carry an author handle, display name or DID. `tests/test_models.py` guards this. `Reply.author_key` is a truncated one-way hash and is the sole exception, existing only to count distinct accounts.

---

## File Structure

**Created:**
- `zeitgeist/analysis/slug.py` — label-to-identifier helpers, shared by live and dormant paths.
- `zeitgeist/analysis/phrases.py` — deterministic recurring-phrase mining. Pure, no I/O.
- `zeitgeist/analysis/distil.py` — evidence to `Topic` + `Dossier`, one LLM call per trend.
- `scripts/capture_bluesky_fixtures.py` — captures real API payloads into `tests/fixtures/bluesky/`.
- `tests/test_analysis_slug.py`, `tests/test_analysis_phrases.py`, `tests/test_analysis_distil.py`.

**Modified:**
- `zeitgeist/models.py` — evidence models, register taxonomy, dossier; `Topic.dossier`; `ScoredTopic` slimmed.
- `zeitgeist/sources/base.py` — `TrendSource` protocol alongside `Source`.
- `zeitgeist/sources/bluesky.py` — async fan-out, returns evidence.
- `zeitgeist/sources/__init__.py` — registry split into item-sources and trend-sources.
- `zeitgeist/config.py` — six new settings; `sentiment_weights` removed; dormancy error.
- `zeitgeist/analysis/score.py`, `zeitgeist/analysis/consolidate.py` — import slug helpers from their new home.
- `zeitgeist/analysis/sentiment.py` — `judge_topics` deleted, `select` simplified.
- `zeitgeist/media/brief.py` — prompt built from the dossier.
- `zeitgeist/pipeline.py` — evidence checkpoint, distillation stage.
- `zeitgeist/cli.py` — builds a trend source.
- `README.md`, `.env.example`.

---

### Task 1: Extract slug helpers into their own module

`score.py` (live path) currently imports `slugify` from `consolidate.py` (about to be dormant). Move the helpers first so nothing later has to import from a dead module.

**Files:**
- Create: `zeitgeist/analysis/slug.py`
- Modify: `zeitgeist/analysis/consolidate.py`, `zeitgeist/analysis/score.py`
- Test: `tests/test_analysis_slug.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `slugify(label: str) -> str`, `unique_slug(label: str, used: set[str]) -> str`. `unique_slug` mutates `used`, adding the slug it returns.

- [ ] **Step 1: Write the failing test**

Create `tests/test_analysis_slug.py`:

```python
"""Slug helpers, shared by the live distillation path and dormant consolidation."""

from zeitgeist.analysis.slug import slugify, unique_slug


def test_slugify_lowercases_and_hyphenates():
    assert slugify("Canada Announces Retaliatory Tariffs") == (
        "canada-announces-retaliatory-tariffs"
    )


def test_slugify_collapses_runs_of_punctuation_to_one_hyphen():
    assert slugify("Trump: 'renaming' Lake Ontario!!") == (
        "trump-renaming-lake-ontario"
    )


def test_slugify_falls_back_when_nothing_survives():
    assert slugify("!!! ???") == "topic"


def test_unique_slug_suffixes_collisions_and_records_them():
    used: set[str] = set()
    assert unique_slug("A Trend", used) == "a-trend"
    assert unique_slug("A Trend", used) == "a-trend-2"
    assert unique_slug("A Trend", used) == "a-trend-3"
    assert used == {"a-trend", "a-trend-2", "a-trend-3"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_analysis_slug.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'zeitgeist.analysis.slug'`

- [ ] **Step 3: Create the module**

Create `zeitgeist/analysis/slug.py`:

```python
"""Label-to-identifier helpers.

Lives in its own module because both the live distillation path and the
dormant consolidation path need it, and the live path must not import from
a module that no longer runs.
"""

import re


def slugify(label: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", label.strip().lower()).strip("-")
    return slug or "topic"


def unique_slug(label: str, used: set[str]) -> str:
    """Slugify `label`, suffixing until unique. Records the result in `used`."""
    base = slugify(label)
    candidate = base
    suffix = 2
    while candidate in used:
        candidate = f"{base}-{suffix}"
        suffix += 1
    used.add(candidate)
    return candidate
```

- [ ] **Step 4: Point the existing modules at it**

In `zeitgeist/analysis/consolidate.py`, delete the `slugify` and `_unique_slug` function definitions at the bottom of the file and the now-unused `import re`, then add to the imports:

```python
from zeitgeist.analysis.slug import slugify, unique_slug
```

Change the one call site inside `consolidate()` from `_unique_slug(entry.label, used_ids)` to `unique_slug(entry.label, used_ids)`.

In `zeitgeist/analysis/score.py`, change:

```python
from zeitgeist.analysis.consolidate import slugify
```

to:

```python
from zeitgeist.analysis.slug import slugify
```

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS. `tests/test_analysis_consolidate.py` exercises `consolidate()` and must still pass unchanged — if it imported `slugify` from `consolidate`, update that import to `zeitgeist.analysis.slug`.

- [ ] **Step 6: Definition of Done, then commit**

```bash
uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest
```

```bash
git add zeitgeist/analysis/slug.py zeitgeist/analysis/consolidate.py zeitgeist/analysis/score.py tests/test_analysis_slug.py
git commit -m "refactor: move slug helpers out of consolidate"
```

---

### Task 2: Evidence models

Purely additive — nothing consumes these yet, so the suite stays green.

**Files:**
- Modify: `zeitgeist/models.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Consumes: `Item`, `TrendStatus`, `STRICT` from `zeitgeist/models.py`.
- Produces: `TrendInfo`, `Reply`, `PostEvidence`, `TrendEvidence`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_models.py`:

```python
def test_trend_info_defaults_description_and_category_to_empty():
    """getTrends is an unspecced endpoint: absent fields degrade, not crash."""
    trend = TrendInfo(
        topic_id="14d072d9",
        display_name="Canada announces retaliatory tariffs",
        post_count=4298,
        started_at=datetime(2026, 8, 26, tzinfo=UTC),
        status="stale",
    )
    assert trend.description == ""
    assert trend.category == ""


def test_trend_evidence_round_trips_through_json(sample_items):
    evidence = TrendEvidence(
        trend=TrendInfo(
            topic_id="t1",
            display_name="A trend",
            description="what happened",
            category="politics",
            post_count=10,
            started_at=datetime(2026, 8, 26, tzinfo=UTC),
            status="trending",
        ),
        posts=[
            PostEvidence(
                item=sample_items[0],
                replies=[
                    Reply(
                        text="what a mess",
                        like_count=4,
                        created_at=datetime(2026, 8, 26, tzinfo=UTC),
                        author_key="ab12cd34",
                    )
                ],
            )
        ],
    )
    restored = TrendEvidence.model_validate_json(evidence.model_dump_json())
    assert restored == evidence


def test_post_evidence_defaults_to_no_replies(sample_items):
    """A post whose thread fetch failed is kept, without replies."""
    assert PostEvidence(item=sample_items[0]).replies == []


@pytest.mark.parametrize("field", ["author", "handle", "did", "display_name"])
def test_reply_rejects_identifying_fields(field):
    """author_key is a one-way hash and the only identity-adjacent field
    allowed. A raw handle or DID creeping in must fail loudly.
    """
    with pytest.raises(ValidationError):
        Reply(
            text="hi",
            like_count=0,
            created_at=datetime(2026, 8, 26, tzinfo=UTC),
            author_key="ab12cd34",
            **{field: "someone.bsky.social"},
        )
```

Add `TrendInfo`, `Reply`, `PostEvidence`, `TrendEvidence` to the existing `from zeitgeist.models import ...` line in that file. Confirm `datetime`, `UTC`, `pytest` and `ValidationError` are already imported there; add whichever are missing.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_models.py -v -k "trend or reply or post_evidence"`
Expected: FAIL — `ImportError: cannot import name 'TrendInfo'`

- [ ] **Step 3: Add the models**

In `zeitgeist/models.py`, insert after the `Item` class and before `NON_PLATFORM_COMPONENTS`:

```python
class TrendInfo(BaseModel):
    """Bluesky's own cluster, kept whole.

    The current source keeps `displayName` and `status` and discards the
    rest — including `description`, which states the specific event in one
    sentence and is the single most useful field the API returns.

    `description` and `category` default to empty rather than raising:
    getTrends lives under `app.bsky.unspecced`, so nothing it returns is a
    contract. Same reasoning as `_normalise_status` in sources/bluesky.py —
    degrade with a warning, do not kill the run.
    """

    model_config = STRICT

    # Bluesky's own `topic` uuid, stable while the trend lives. Kept for
    # cross-run identification; NOT used as Topic.id, which needs to be
    # readable because render output filenames are built from it.
    topic_id: str
    display_name: str
    description: str = ""
    category: str = ""
    post_count: int = 0
    started_at: datetime
    status: TrendStatus


class Reply(BaseModel):
    """One reply beneath a post. The conversation, as opposed to the news.

    `author_key` is a truncated one-way hash of the poster's DID and exists
    for exactly one purpose: counting how many distinct accounts are behind
    a repeated phrase. Forty uses from three accounts is a dogpile, not a
    zeitgeist. The handle itself has no downstream use and is never stored.
    """

    model_config = STRICT

    text: str
    like_count: int
    created_at: datetime
    author_key: str


class PostEvidence(BaseModel):
    """A post together with what people said underneath it."""

    model_config = STRICT

    item: Item
    # Empty when the thread fetch failed. A post without replies is still
    # evidence of what was posted, so it is kept rather than dropped.
    replies: list[Reply] = Field(default_factory=list)


class TrendEvidence(BaseModel):
    """Everything one trend contributed to a run.

    This is the ingest checkpoint's unit, replacing the flat `Item` list.
    """

    model_config = STRICT

    trend: TrendInfo
    posts: list[PostEvidence] = Field(default_factory=list)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_models.py -v`
Expected: PASS

- [ ] **Step 5: Definition of Done, then commit**

```bash
uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest
```

```bash
git add zeitgeist/models.py tests/test_models.py
git commit -m "feat: add trend evidence models"
```

---

### Task 3: Register taxonomy and dossier models

Still additive. `Topic.dossier` defaults to `None`, so the dormant path is unaffected.

**Files:**
- Modify: `zeitgeist/models.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Consumes: `Sentiment`, `STRICT`, `Topic` from `zeitgeist/models.py`.
- Produces: `Register` (StrEnum), `Phrase`, `Dossier`, and `Topic.dossier: Dossier | None`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_models.py`:

```python
def _dossier(**overrides) -> Dossier:
    base = {
        "what_happened": "Canada imposed retaliatory tariffs on $30B of US goods.",
        "key_entities": ["Canada", "Mark Carney"],
        "conversation_summary": "People are treating it as overdue.",
        "register": Register.DUNKING,
        "secondary_registers": [Register.RESIGNATION],
        "event_sentiment": Sentiment.SCHADENFREUDE,
        "valence": -0.2,
        "meme_potential": 0.8,
        "recurring_phrases": [],
    }
    return Dossier(**(base | overrides))


def test_register_is_a_string_enum_that_round_trips():
    assert Register.DELIGHT.value == "delight"
    assert Register("delight") is Register.DELIGHT


def test_topic_dossier_defaults_to_none():
    """The dormant path produces topics with no dossier."""
    topic = Topic(id="t", label="A trend", summary="s", item_ids=["i1"])
    assert topic.dossier is None


def test_topic_carries_a_dossier_through_json():
    topic = Topic(
        id="t",
        label="A trend",
        summary="s",
        item_ids=["i1"],
        dossier=_dossier(
            recurring_phrases=[
                Phrase(text="elbows up", occurrences=41, distinct_authors=33)
            ]
        ),
    )
    restored = Topic.model_validate_json(topic.model_dump_json())
    assert restored.dossier is not None
    assert restored.dossier.recurring_phrases[0].text == "elbows up"
    assert restored.dossier.register is Register.DUNKING


def test_dossier_rejects_valence_outside_the_scale():
    with pytest.raises(ValidationError):
        _dossier(valence=-1.5)


def test_dossier_rejects_meme_potential_outside_the_scale():
    with pytest.raises(ValidationError):
        _dossier(meme_potential=1.5)
```

Add `Dossier`, `Phrase`, `Register` to the `from zeitgeist.models import ...` line.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_models.py -v -k "register or dossier"`
Expected: FAIL — `ImportError: cannot import name 'Register'`

- [ ] **Step 3: Add the taxonomy and models**

In `zeitgeist/models.py`, add after the `Sentiment` class:

```python
class Register(StrEnum):
    """The posture people are taking, distinct from how the event feels.

    `Sentiment` answers "how does this event feel"; `Register` answers "what
    is the room doing about it". The two can point in opposite directions,
    and the gap is the signal: a grim event discussed in GALLOWS yields a
    very particular meme, while the same event in MOURNING means do not make
    a joke at all.

    The three warm registers are easily confused, so they are defined
    against each other. DELIGHT is a cat knocking something off a table, or
    an overlooked person finally getting their due: broad, warm, no side to
    take. AWE is impressive rather than endearing. TRIBUTE is appreciation
    prompted by loss or a milestone.
    """

    TRIBUTE = "tribute"
    MOURNING = "mourning"
    DELIGHT = "delight"
    OUTRAGE = "outrage"
    DUNKING = "dunking"
    GALLOWS = "gallows"
    RIFFING = "riffing"
    AWE = "awe"
    ALARM = "alarm"
    DEBATE = "debate"
    RESIGNATION = "resignation"
```

Then add, immediately before the `Topic` class:

```python
class Phrase(BaseModel):
    """Text that several people independently converged on.

    Mined deterministically, never model-generated. Asked for catchphrases a
    model returns plausible ones; the point of this field is that its counts
    are true, because that is what licenses quoting it in a caption.
    """

    model_config = STRICT

    text: str
    occurrences: int
    distinct_authors: int


class Dossier(BaseModel):
    """What a trend is actually about, and what the room is doing about it.

    Replaces the label-and-summary pair that every caption used to be
    written from. `summary` on the old path was written by a model that had
    seen a tag vocabulary and no sentences; `what_happened` here is written
    from the trend description, the posts and the replies.
    """

    model_config = STRICT

    what_happened: str
    key_entities: list[str] = Field(default_factory=list)
    conversation_summary: str
    register: Register
    secondary_registers: list[Register] = Field(default_factory=list)
    event_sentiment: Sentiment
    valence: float = Field(ge=-1.0, le=1.0)
    # Recorded for inspection, deliberately NOT applied to ranking. It was
    # suppressing topics before there was evidence that suppression helps.
    meme_potential: float = Field(ge=0.0, le=1.0)
    # Attached after the model call, not returned by it.
    recurring_phrases: list[Phrase] = Field(default_factory=list)
```

Add the field to `Topic`:

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
    # None on the dormant path, which has no evidence to distil.
    dossier: Dossier | None = None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_models.py -v`
Expected: PASS

- [ ] **Step 5: Definition of Done, then commit**

```bash
uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest
```

```bash
git add zeitgeist/models.py tests/test_models.py
git commit -m "feat: add register taxonomy and dossier model"
```

---

### Task 4: Recurring-phrase mining

Pure function, no I/O, no LLM. The two tests that carry the design are the spam-ring exclusion and substring collapse.

**Files:**
- Create: `zeitgeist/analysis/phrases.py`
- Modify: `zeitgeist/config.py`, `tests/conftest.py`
- Test: `tests/test_analysis_phrases.py`

**Interfaces:**
- Consumes: `Phrase`, `Reply`, `TrendInfo` from `zeitgeist/models.py`.
- Produces: `mine_phrases(replies: list[Reply], trend: TrendInfo, *, min_authors: int, top: int = TOP_PHRASES) -> list[Phrase]`, and the constants `MIN_N`, `MAX_N`, `TOP_PHRASES`, `COLLAPSE_RATIO`.
- Produces: `Settings.phrase_min_authors: int = 3`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_analysis_phrases.py`:

```python
"""Recurring-phrase mining.

Deterministic on purpose. A model asked for catchphrases invents plausible
ones; the counts here are what license quoting a phrase in a caption, so
they have to be measured.
"""

from datetime import UTC, datetime

from zeitgeist.analysis.phrases import mine_phrases
from zeitgeist.models import Reply, TrendInfo

TREND = TrendInfo(
    topic_id="t1",
    display_name="Canada announces retaliatory tariffs",
    description="Canada hits back after trade talks collapsed.",
    category="business",
    post_count=4298,
    started_at=datetime(2026, 8, 26, tzinfo=UTC),
    status="stale",
)


def _replies(*pairs: tuple[str, str]) -> list[Reply]:
    """Each pair is (author_key, text)."""
    return [
        Reply(
            text=text,
            like_count=0,
            created_at=datetime(2026, 8, 26, tzinfo=UTC),
            author_key=author,
        )
        for author, text in pairs
    ]


def _texts(phrases) -> list[str]:
    return [phrase.text for phrase in phrases]


def test_a_phrase_many_people_use_is_mined():
    replies = _replies(
        ("a", "elbows up everyone"),
        ("b", "elbows up"),
        ("c", "time for elbows up"),
        ("d", "elbows up finally"),
    )
    result = mine_phrases(replies, TREND, min_authors=3)
    assert "elbows up" in _texts(result)


def test_counts_report_occurrences_and_distinct_authors_separately():
    replies = _replies(
        ("a", "elbows up"),
        ("b", "elbows up"),
        ("c", "elbows up"),
    )
    [phrase] = [p for p in mine_phrases(replies, TREND, min_authors=3)
                if p.text == "elbows up"]
    assert phrase.occurrences == 3
    assert phrase.distinct_authors == 3


def test_a_phrase_repeated_by_few_accounts_is_excluded():
    """Forty uses from three accounts is a dogpile, not a zeitgeist. This is
    the test the whole distinct-author count exists for.
    """
    replies = _replies(*[(f"a{i % 3}", "buy my coin now") for i in range(40)])
    result = mine_phrases(replies, TREND, min_authors=4)
    assert "buy my coin" not in _texts(result)


def test_one_person_repeating_a_phrase_counts_once():
    replies = _replies(
        ("a", "elbows up elbows up elbows up elbows up"),
        ("b", "elbows up"),
        ("c", "elbows up"),
    )
    [phrase] = [p for p in mine_phrases(replies, TREND, min_authors=3)
                if p.text == "elbows up"]
    assert phrase.occurrences == 3
    assert phrase.distinct_authors == 3


def test_substring_collapse_keeps_the_longer_phrase():
    """Almost everyone who said the short form said the long form, so the
    long form is the phrase.
    """
    replies = _replies(
        ("a", "support the imagination library"),
        ("b", "the imagination library forever"),
        ("c", "donate to the imagination library"),
        ("d", "the imagination library is her legacy"),
    )
    result = _texts(mine_phrases(replies, TREND, min_authors=3))
    assert "the imagination library" in result
    assert "imagination library" not in result


def test_substring_collapse_keeps_the_shorter_when_the_longer_is_a_variant():
    """Only a minority attached the longer form, so the short phrase is the
    widely-used one and the long form is one sub-community's variant.

    Both must survive. Five accounts said "elbows up"; three of those added
    "canada". 3 < 0.8 * 5, so the short form is not absorbed.
    """
    replies = _replies(
        ("a", "elbows up canada"),
        ("b", "elbows up canada"),
        ("c", "elbows up canada"),
        ("d", "elbows up"),
        ("e", "elbows up"),
    )
    result = _texts(mine_phrases(replies, TREND, min_authors=3))
    assert "elbows up" in result
    assert "elbows up canada" in result


def test_the_subject_of_the_trend_is_not_a_catchphrase():
    """"retaliatory tariffs" in two hundred replies is what the trend is
    about, not something people coined.
    """
    replies = _replies(
        ("a", "retaliatory tariffs at last"),
        ("b", "retaliatory tariffs were overdue"),
        ("c", "about time for retaliatory tariffs"),
    )
    assert "retaliatory tariffs" not in _texts(
        mine_phrases(replies, TREND, min_authors=3)
    )


def test_phrases_from_the_trend_description_are_also_excluded():
    replies = _replies(
        ("a", "trade talks collapsed again"),
        ("b", "trade talks collapsed"),
        ("c", "so the trade talks collapsed"),
    )
    assert "trade talks collapsed" not in _texts(
        mine_phrases(replies, TREND, min_authors=3)
    )


def test_all_stopword_phrases_are_excluded():
    replies = _replies(
        ("a", "this is the one"),
        ("b", "this is the one"),
        ("c", "this is the one"),
    )
    assert "is the" not in _texts(mine_phrases(replies, TREND, min_authors=3))


def test_urls_and_mentions_are_stripped_before_mining():
    replies = _replies(
        ("a", "@someone.bsky.social elbows up https://example.com/a"),
        ("b", "@other.bsky.social elbows up https://example.com/b"),
        ("c", "elbows up"),
    )
    result = _texts(mine_phrases(replies, TREND, min_authors=3))
    assert "elbows up" in result
    assert not any("http" in text or "@" in text for text in result)


def test_no_replies_yields_no_phrases():
    assert mine_phrases([], TREND, min_authors=3) == []


def test_results_are_ranked_by_distinct_authors():
    replies = _replies(
        ("a", "elbows up"),
        ("b", "elbows up"),
        ("c", "elbows up"),
        ("d", "elbows up"),
        ("a", "maple syrup diplomacy"),
        ("b", "maple syrup diplomacy"),
        ("c", "maple syrup diplomacy"),
    )
    result = mine_phrases(replies, TREND, min_authors=3)
    assert result == sorted(result, key=lambda p: -p.distinct_authors)


def test_top_limits_the_result_size():
    replies = _replies(
        *[
            (author, f"phrase number {index} here")
            for index in range(20)
            for author in ("a", "b", "c")
        ]
    )
    assert len(mine_phrases(replies, TREND, min_authors=3, top=5)) == 5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_analysis_phrases.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'zeitgeist.analysis.phrases'`

- [ ] **Step 3: Write the implementation**

Create `zeitgeist/analysis/phrases.py`:

```python
"""Recurring-phrase mining across a trend's replies.

Pure Python for the reason already recorded in scorers/bluesky.py:
reproducible and unit-testable, which a model's judgement is not. That
matters more here than elsewhere. A phrase one person wrote is that person's
joke; a phrase fifty people converged on independently is the zeitgeist, and
only a real count can tell those apart. Asked to do this itself, a model
would return plausible-sounding phrases with invented frequencies, and the
caption stage would quote them as though they were evidence.
"""

import re
from collections import Counter, defaultdict
from collections.abc import Sequence

from zeitgeist.models import Phrase, Reply, TrendInfo

MIN_N = 2
MAX_N = 6
TOP_PHRASES = 15

# Drop the shorter phrase when the longer one retains at least this share of
# its distinct authors. If almost everyone who said the short form said the
# long form, the long form is the phrase; if most did not, the short form is
# genuinely more widely used and the longer is one sub-community's variant.
COLLAPSE_RATIO = 0.8

STOPWORDS = frozenset(
    """
    a about all also am an and any are as at be because been but by can could
    did do does doing don for from get got had has have he her hers him his
    how i if in into is it its just like me more most my no not now of off on
    once only or other our out over own re same she should so some such than
    that the their them then there these they this those through to too up us
    very was we were what when where which while who whom why will with would
    you your
    """.split()
)

_URL = re.compile(r"https?://\S+|\bwww\.\S+")
_MENTION = re.compile(r"@[\w.\-]+")
_NON_WORD = re.compile(r"[^a-z0-9' ]+")
_SPACE = re.compile(r"\s+")


def normalise(text: str) -> list[str]:
    """Lowercase, strip URLs, mentions and punctuation, split to tokens."""
    lowered = text.lower()
    lowered = _URL.sub(" ", lowered)
    lowered = _MENTION.sub(" ", lowered)
    lowered = _NON_WORD.sub(" ", lowered)
    return _SPACE.sub(" ", lowered).strip().split()


def mine_phrases(
    replies: list[Reply],
    trend: TrendInfo,
    *,
    min_authors: int,
    top: int = TOP_PHRASES,
) -> list[Phrase]:
    """Rank the phrases a trend's repliers actually converged on."""
    occurrences: Counter[tuple[str, ...]] = Counter()
    authors: defaultdict[tuple[str, ...], set[str]] = defaultdict(set)

    for reply in replies:
        # Deduplicated within a reply, so one person repeating a phrase four
        # times contributes one occurrence rather than four.
        for gram in _grams(normalise(reply.text)):
            occurrences[gram] += 1
            authors[gram].add(reply.author_key)

    subject = normalise(f"{trend.display_name} {trend.description}")

    candidates = [
        Phrase(
            text=" ".join(gram),
            occurrences=count,
            distinct_authors=len(authors[gram]),
        )
        for gram, count in occurrences.items()
        if len(authors[gram]) >= min_authors
        and not _contains(subject, gram)
        and not all(token in STOPWORDS for token in gram)
    ]

    kept = _collapse_substrings(candidates)
    kept.sort(key=lambda phrase: (-phrase.distinct_authors, -len(phrase.text)))
    return kept[:top]


def _grams(tokens: list[str]) -> set[tuple[str, ...]]:
    return {
        tuple(tokens[start : start + size])
        for size in range(MIN_N, MAX_N + 1)
        for start in range(len(tokens) - size + 1)
    }


def _contains(haystack: Sequence[str], needle: tuple[str, ...]) -> bool:
    """True when `needle` appears as a contiguous run inside `haystack`."""
    size = len(needle)
    return any(
        tuple(haystack[start : start + size]) == needle
        for start in range(len(haystack) - size + 1)
    )


def _collapse_substrings(phrases: list[Phrase]) -> list[Phrase]:
    """Drop a phrase wholly contained in a longer one that most of its
    authors also used. Without this, "imagination library" and "the
    imagination library" both surface and dilute the list.
    """
    tokens = {phrase.text: tuple(phrase.text.split()) for phrase in phrases}
    dropped: set[str] = set()

    for short in phrases:
        for long in phrases:
            if long.text == short.text:
                continue
            if len(tokens[long.text]) <= len(tokens[short.text]):
                continue
            if not _contains(tokens[long.text], tokens[short.text]):
                continue
            if long.distinct_authors >= COLLAPSE_RATIO * short.distinct_authors:
                dropped.add(short.text)
                break

    return [phrase for phrase in phrases if phrase.text not in dropped]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_analysis_phrases.py -v`
Expected: PASS — all fourteen.

- [ ] **Step 5: Add the setting**

In `zeitgeist/config.py`, add to `Settings` beside `topic_count`:

```python
    # Distinct accounts a phrase needs before it counts as recurring. Below
    # this, a repeated phrase is one person or a small ring, not a zeitgeist.
    phrase_min_authors: int = 3
```

In `tests/conftest.py`, add `"PHRASE_MIN_AUTHORS"` to `_SETTINGS_ENV_VARS`.

- [ ] **Step 6: Definition of Done, then commit**

```bash
uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest
```

```bash
git add zeitgeist/analysis/phrases.py zeitgeist/config.py tests/conftest.py tests/test_analysis_phrases.py
git commit -m "feat: mine recurring phrases by distinct author"
```

---

### Task 5: Concurrent evidence gathering in BlueskySource

The largest task. Replaces `BlueskySource.fetch` with `fetch_evidence`, adds a third fan-out level for reply threads, and moves the whole thing onto `asyncio`.

**Files:**
- Modify: `zeitgeist/sources/base.py`, `zeitgeist/sources/bluesky.py`, `zeitgeist/sources/__init__.py`, `zeitgeist/config.py`, `tests/conftest.py`
- Test: `tests/test_sources_bluesky.py`, `tests/test_sources_composite.py`

**Interfaces:**
- Consumes: `TrendEvidence`, `PostEvidence`, `Reply`, `TrendInfo`, `Item`, `BlueskyMetrics` from `zeitgeist/models.py`; `Settings`.
- Produces: `TrendSource` protocol with `fetch_evidence(self, settings: Settings) -> list[TrendEvidence]`; `BlueskySource(api_base: str = DEFAULT_API_BASE, client_factory: Any = None)` implementing it; `build_trend_source(settings: Settings) -> TrendSource`; module constant `RETRY_BASE_DELAY: float`.
- Produces settings: `bluesky_trend_limit: int = 25`, `bluesky_posts_per_trend: int = 10`, `bluesky_fetch_concurrency: int = 8`.

- [ ] **Step 1: Add the settings and the protocol**

In `zeitgeist/config.py`, add to `Settings` beside `bluesky_api_base`:

```python
    # 25 is the API's ceiling, not a tuning parameter: getTrends returns 400
    # above it. The other two are the real fan-out budget, which is why
    # fetch_evidence takes no single `limit` argument — one integer cannot
    # express trends-by-posts.
    bluesky_trend_limit: int = 25
    bluesky_posts_per_trend: int = 10
    bluesky_fetch_concurrency: int = 8
```

In `tests/conftest.py`, add `"BLUESKY_TREND_LIMIT"`, `"BLUESKY_POSTS_PER_TREND"` and `"BLUESKY_FETCH_CONCURRENCY"` to `_SETTINGS_ENV_VARS`.

In `zeitgeist/sources/base.py`, add below the existing `Source` protocol:

```python
class TrendSource(Protocol):
    """A platform that clusters posts into trends itself.

    Returns evidence rather than a flat item list, so `Source` cannot
    describe it. There is no `limit`: the fan-out is bounded by
    `bluesky_trend_limit` and `bluesky_posts_per_trend`, a two-dimensional
    budget a single integer cannot express.
    """

    name: str

    def fetch_evidence(self, settings: Settings) -> list[TrendEvidence]: ...
```

Add the imports this needs at the top of `base.py`:

```python
from zeitgeist.config import Settings
from zeitgeist.models import Item, TrendEvidence
```

> If importing `Settings` into `sources/base.py` creates a cycle (`config.py` must not import from `sources`), verify: `config.py` imports only from `zeitgeist.models`, so this direction is safe. Do not add a `sources` import to `config.py`.

- [ ] **Step 2: Write the failing tests**

Replace the `_FakeClient` and `_source` helpers in `tests/test_sources_bluesky.py` with async equivalents, and add a thread fixture builder. Keep `_trend` and `_post` as they are.

```python
import asyncio

from zeitgeist.config import Settings
from zeitgeist.models import TrendEvidence

THREAD_VIEW = "app.bsky.feed.defs#threadViewPost"


def _reply_node(
    text: str,
    *,
    did: str = "did:plc:replier",
    likes: int = 1,
    indexed: str = "2026-08-23T11:00:00.000Z",
    labels: list[dict] | None = None,
    children: list[dict] | None = None,
    node_type: str = THREAD_VIEW,
) -> dict:
    return {
        "$type": node_type,
        "post": {
            "uri": f"at://{did}/app.bsky.feed.post/r-{abs(hash(text)) % 10**6}",
            "cid": "bafyreiexample",
            "author": {"did": did, "handle": "replier.bsky.social"},
            "record": {"$type": "app.bsky.feed.post", "text": text},
            "likeCount": likes,
            "replyCount": len(children or []),
            "repostCount": 0,
            "indexedAt": indexed,
            "labels": labels or [],
        },
        "replies": children or [],
    }


def _thread(*nodes: dict) -> dict:
    return {"thread": {"$type": THREAD_VIEW, "post": {}, "replies": list(nodes)}}


class _Response:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        # Plain HTTPError rather than HTTPStatusError: the latter requires
        # real Request and Response objects, and the source only ever
        # catches the base class.
        if self.status_code >= 400:
            raise httpx.HTTPError(f"status {self.status_code}")

    def json(self) -> dict:
        return self._payload


class _FakeAsyncClient:
    """Routes on endpoint. Each mapping value is a payload, an Exception to
    raise, or a list of payloads/Exceptions consumed one per call (used to
    exercise retry).
    """

    def __init__(
        self,
        trends: dict | Exception,
        feeds: Mapping[str, object],
        threads: Mapping[str, object] | None = None,
    ) -> None:
        self._trends = trends
        self._feeds = feeds
        self._threads = threads or {}
        self.calls: list[tuple[str, dict]] = []
        self.closed = False
        self.in_flight = 0
        self.max_in_flight = 0

    async def get(self, url: str, params: dict | None = None) -> _Response:
        params = params or {}
        self.calls.append((url, params))
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            # Yields control so overlapping requests actually overlap, which
            # is what makes max_in_flight meaningful.
            await asyncio.sleep(0)
            if "getTrends" in url:
                return _resolve(self._trends)
            if "getFeed" in url:
                rkey = str(params["feed"]).rsplit("/", 1)[-1]
                return _resolve(self._feeds[rkey])
            if "getPostThread" in url:
                rkey = str(params["uri"]).rsplit("/", 1)[-1]
                return _resolve(self._threads.get(rkey, _thread()))
            raise AssertionError(f"unexpected URL {url}")
        finally:
            self.in_flight -= 1

    async def aclose(self) -> None:
        self.closed = True


def _resolve(entry: object) -> _Response:
    """A mapping value may be a payload dict, an Exception, a prebuilt
    _Response (for status codes such as 429), or a list of those consumed
    one per call.
    """
    if isinstance(entry, list):
        entry = entry.pop(0)
    if isinstance(entry, Exception):
        raise entry
    if isinstance(entry, _Response):
        return entry
    assert isinstance(entry, dict)
    return _Response(entry)


def _settings(**overrides) -> Settings:
    base = {
        "sources": ["bluesky"],
        "bluesky_trend_limit": 25,
        "bluesky_posts_per_trend": 10,
        "bluesky_fetch_concurrency": 8,
    }
    return Settings(**(base | overrides))


def _source(
    trends: dict | Exception,
    feeds: Mapping[str, object],
    threads: Mapping[str, object] | None = None,
) -> tuple[BlueskySource, _FakeAsyncClient]:
    client = _FakeAsyncClient(trends, feeds, threads)
    return BlueskySource(client_factory=lambda: client), client
```

Now the tests. Existing tests in this file that call `source.fetch(limit=...)` and assert on `list[Item]` must be rewritten to call `fetch_evidence` and read `evidence[0].posts[0].item` — the mapping assertions themselves (permalink construction, `indexedAt` over `createdAt`, language filter, label filter, malformed URI) are still valid and must be kept, not deleted.

```python
def test_a_trend_keeps_every_field_the_api_returns():
    """The whole point of this change: `description` states the specific
    event and the old source discarded it.
    """
    source, _ = _source(
        {"trends": [_trend("t1", "Canada announces retaliatory tariffs")]},
        {"t1": {"feed": [_post("p1")]}},
    )
    [evidence] = source.fetch_evidence(_settings())
    assert evidence.trend.display_name == "Canada announces retaliatory tariffs"
    assert evidence.trend.description == "a description"
    assert evidence.trend.category == "politics"
    assert evidence.trend.post_count == 100
    assert evidence.trend.topic_id == "t1"


def test_replies_are_attached_to_their_post():
    source, _ = _source(
        {"trends": [_trend("t1", "A trend")]},
        {"t1": {"feed": [_post("p1")]}},
        {"p1": _thread(_reply_node("what a mess"), _reply_node("about time"))},
    )
    [evidence] = source.fetch_evidence(_settings())
    assert [reply.text for reply in evidence.posts[0].replies] == [
        "what a mess",
        "about time",
    ]


def test_nested_replies_are_flattened():
    source, _ = _source(
        {"trends": [_trend("t1", "A trend")]},
        {"t1": {"feed": [_post("p1")]}},
        {"p1": _thread(_reply_node("top", children=[_reply_node("nested")]))},
    )
    [evidence] = source.fetch_evidence(_settings())
    assert {reply.text for reply in evidence.posts[0].replies} == {"top", "nested"}


def test_blocked_and_missing_reply_nodes_are_skipped():
    """`replies` is a union: notFoundPost and blockedPost have no record."""
    source, _ = _source(
        {"trends": [_trend("t1", "A trend")]},
        {"t1": {"feed": [_post("p1")]}},
        {
            "p1": _thread(
                _reply_node("real"),
                {"$type": "app.bsky.feed.defs#blockedPost", "uri": "at://x/y/z"},
                {"$type": "app.bsky.feed.defs#notFoundPost", "uri": "at://x/y/w"},
            )
        },
    )
    [evidence] = source.fetch_evidence(_settings())
    assert [reply.text for reply in evidence.posts[0].replies] == ["real"]


def test_labelled_replies_are_dropped():
    source, _ = _source(
        {"trends": [_trend("t1", "A trend")]},
        {"t1": {"feed": [_post("p1")]}},
        {
            "p1": _thread(
                _reply_node("fine"),
                _reply_node("nasty", labels=[{"val": "porn"}]),
            )
        },
    )
    [evidence] = source.fetch_evidence(_settings())
    assert [reply.text for reply in evidence.posts[0].replies] == ["fine"]


def test_the_same_author_yields_the_same_key_and_a_different_one_differs():
    source, _ = _source(
        {"trends": [_trend("t1", "A trend")]},
        {"t1": {"feed": [_post("p1")]}},
        {
            "p1": _thread(
                _reply_node("one", did="did:plc:aaa"),
                _reply_node("two", did="did:plc:aaa"),
                _reply_node("three", did="did:plc:bbb"),
            )
        },
    )
    [evidence] = source.fetch_evidence(_settings())
    first, second, third = evidence.posts[0].replies
    assert first.author_key == second.author_key
    assert first.author_key != third.author_key


def test_the_author_key_is_not_the_did():
    """It is a hash. A raw DID on disk would be an identifier we have no use
    for; the count of distinct accounts is the only thing needed.
    """
    source, _ = _source(
        {"trends": [_trend("t1", "A trend")]},
        {"t1": {"feed": [_post("p1")]}},
        {"p1": _thread(_reply_node("hi", did="did:plc:aaa"))},
    )
    [evidence] = source.fetch_evidence(_settings())
    assert "did:plc:aaa" not in evidence.posts[0].replies[0].author_key


def test_a_failing_thread_leaves_the_post_without_replies():
    source, _ = _source(
        {"trends": [_trend("t1", "A trend")]},
        {"t1": {"feed": [_post("p1")]}},
        {"p1": httpx.ConnectError("boom")},
    )
    [evidence] = source.fetch_evidence(_settings())
    assert evidence.posts[0].replies == []
    assert evidence.posts[0].item.source_id.endswith("p1")


def test_a_failing_feed_skips_only_that_trend():
    source, _ = _source(
        {"trends": [_trend("t1", "First"), _trend("t2", "Second")]},
        {"t1": httpx.ConnectError("boom"), "t2": {"feed": [_post("p2")]}},
    )
    evidence = source.fetch_evidence(_settings())
    assert [e.trend.display_name for e in evidence] == ["Second"]


def test_a_trend_with_no_usable_posts_is_skipped():
    source, _ = _source(
        {"trends": [_trend("t1", "First"), _trend("t2", "Second")]},
        {"t1": {"feed": [_post("p1", text="   ")]}, "t2": {"feed": [_post("p2")]}},
    )
    evidence = source.fetch_evidence(_settings())
    assert [e.trend.display_name for e in evidence] == ["Second"]


def test_unreachable_trends_endpoint_is_fatal():
    source, _ = _source(httpx.ConnectError("boom"), {})
    with pytest.raises(SourceError, match="trends unavailable"):
        source.fetch_evidence(_settings())


def test_no_usable_trends_at_all_is_fatal():
    source, _ = _source(
        {"trends": [_trend("t1", "First")]},
        {"t1": httpx.ConnectError("boom")},
    )
    with pytest.raises(SourceError, match="no usable"):
        source.fetch_evidence(_settings())


def test_a_rate_limited_request_is_retried(monkeypatch):
    monkeypatch.setattr("zeitgeist.sources.bluesky.RETRY_BASE_DELAY", 0)
    source, client = _source(
        {"trends": [_trend("t1", "A trend")]},
        {"t1": [_Response({}, status_code=429), {"feed": [_post("p1")]}]},
    )
    [evidence] = source.fetch_evidence(_settings())
    assert len(evidence.posts) == 1
    assert sum(1 for url, _ in client.calls if "getFeed" in url) == 2


def test_concurrency_never_exceeds_the_configured_bound():
    trends = [_trend(f"t{i}", f"Trend {i}") for i in range(10)]
    feeds = {
        f"t{i}": {"feed": [_post(f"p{i}-{j}") for j in range(5)]} for i in range(10)
    }
    source, client = _source({"trends": trends}, feeds)
    source.fetch_evidence(_settings(bluesky_fetch_concurrency=3))
    assert client.max_in_flight <= 3


def test_posts_per_trend_bounds_the_feed_request():
    source, client = _source(
        {"trends": [_trend("t1", "A trend")]},
        {"t1": {"feed": [_post("p1")]}},
    )
    source.fetch_evidence(_settings(bluesky_posts_per_trend=4))
    feed_calls = [params for url, params in client.calls if "getFeed" in url]
    assert feed_calls[0]["limit"] == 4


def test_the_client_is_closed_even_when_the_run_fails():
    source, client = _source(httpx.ConnectError("boom"), {})
    with pytest.raises(SourceError):
        source.fetch_evidence(_settings())
    assert client.closed


def test_evidence_survives_a_json_round_trip():
    """It is the ingest checkpoint, so it has to serialise."""
    source, _ = _source(
        {"trends": [_trend("t1", "A trend")]},
        {"t1": {"feed": [_post("p1")]}},
        {"p1": _thread(_reply_node("what a mess"))},
    )
    [evidence] = source.fetch_evidence(_settings())
    assert TrendEvidence.model_validate_json(evidence.model_dump_json()) == evidence
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_sources_bluesky.py -v`
Expected: FAIL — `AttributeError: 'BlueskySource' object has no attribute 'fetch_evidence'`

- [ ] **Step 4: Rewrite the source**

Replace `zeitgeist/sources/bluesky.py` with the following. `_is_usable`, `_split_uri`, `_parse_timestamp`, `_normalise_status`, `LINK_PATTERN` and `STATUS_MAP` are unchanged from the current file — keep their existing docstrings and comments verbatim.

```python
"""Bluesky ingestion via the public AT Protocol AppView.

Needs no credentials: these endpoints accept unauthenticated requests.
Fetches in three steps, each fanning out from the last.

    getTrends       what is trending, with a description of each event
    getFeed         the posts behind one trend
    getPostThread   what people said underneath one post

`getTrends` carries a `link` which is a *web UI path*, and Bluesky maintains
a live feed generator behind it. Converting that path to an `at://` *record
address* is what lets `getFeed` return the trend's posts.

    link  /profile/{did}/feed/{rkey}
    uri   at://{did}/app.bsky.feed.generator/{rkey}

So the source never selects or ranks posts for a topic — Bluesky already has,
and this reads the result, including the trend description that names the
specific event.

The third step is why this module is async. Roughly 275 requests per run
serialised would take minutes; under a semaphore they take about one. The
async boundary stops at `fetch_evidence`, which is an ordinary synchronous
method, so no stage above this one becomes a coroutine.
"""

import asyncio
import hashlib
import logging
import re
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import httpx

from zeitgeist.config import Settings
from zeitgeist.models import (
    BlueskyMetrics,
    Item,
    PostEvidence,
    Reply,
    TrendEvidence,
    TrendInfo,
    TrendStatus,
)
from zeitgeist.sources.base import SourceError

log = logging.getLogger(__name__)

DEFAULT_API_BASE = "https://api.bsky.app"
TIMEOUT_SECONDS = 30.0
MAX_FEED_PAGE = 100
USER_AGENT = "zeitgeist-actualiser/0.1"

# Replies are fetched two levels deep: a reply-to-a-reply is still people
# talking about the trend, and it costs nothing extra — depth is a parameter
# of the same single request.
THREAD_DEPTH = 2

MAX_ATTEMPTS = 3
# Module-level so tests can zero it. Real runs rarely reach it: ~275 requests
# is well inside Bluesky's public limits.
RETRY_BASE_DELAY = 0.5

LINK_PATTERN = re.compile(r"^/profile/(?P<did>[^/]+)/feed/(?P<rkey>[^/]+)$")

LANGUAGE = "en"

# Union members of `getPostThread`'s reply list. Anything that is not a
# threadViewPost — a blocked or deleted post — carries no record to read.
THREAD_VIEW = "app.bsky.feed.defs#threadViewPost"

STATUS_MAP: dict[str, TrendStatus] = {
    "hot": "trending",
    "trending": "trending",
    "saturating": "saturating",
    "cooling": "cooling",
    "stale": "stale",
}


def _default_client() -> Any:
    return httpx.AsyncClient(
        timeout=TIMEOUT_SECONDS, headers={"User-Agent": USER_AGENT}
    )


class BlueskySource:
    name = "bluesky"

    def __init__(
        self, api_base: str = DEFAULT_API_BASE, client_factory: Any = None
    ) -> None:
        self._api_base = api_base.rstrip("/")
        # A factory rather than a client: the client must be created inside
        # the event loop `fetch_evidence` starts, and a real AsyncClient
        # bound to a closed loop is unusable on the next call.
        self._client_factory: Any = client_factory or _default_client

    @classmethod
    def from_settings(cls, settings: Settings) -> BlueskySource:
        return cls(api_base=settings.bluesky_api_base)

    def fetch_evidence(self, settings: Settings) -> list[TrendEvidence]:
        """Gather every trend's posts and replies. Synchronous by design."""
        return asyncio.run(self._gather(settings))

    async def _gather(self, settings: Settings) -> list[TrendEvidence]:
        client = self._client_factory()
        semaphore = asyncio.Semaphore(settings.bluesky_fetch_concurrency)
        fetched_at = datetime.now(UTC)
        try:
            # Only transport failure is tolerated. A KeyError from a changed
            # payload propagates: that is a contract break, not an outage.
            try:
                payload = await self._get(
                    client,
                    semaphore,
                    "app.bsky.unspecced.getTrends",
                    {"limit": settings.bluesky_trend_limit},
                )
            except httpx.HTTPError as exc:
                raise SourceError(f"Bluesky trends unavailable: {exc}") from exc

            trends = payload["trends"]
            if not trends:
                raise SourceError("Bluesky returned no trends")

            gathered = await asyncio.gather(
                *(
                    self._trend_evidence(
                        client, semaphore, trend, settings, fetched_at
                    )
                    for trend in trends
                )
            )
        finally:
            await client.aclose()

        evidence = [entry for entry in gathered if entry is not None]
        if not evidence:
            raise SourceError("Bluesky returned no usable trends")
        return evidence

    async def _trend_evidence(
        self,
        client: Any,
        semaphore: asyncio.Semaphore,
        trend: dict[str, Any],
        settings: Settings,
        fetched_at: datetime,
    ) -> TrendEvidence | None:
        match = LINK_PATTERN.match(trend["link"])
        if match is None:
            log.warning("Skipping Bluesky trend with link %r", trend["link"])
            return None

        uri = f"at://{match['did']}/app.bsky.feed.generator/{match['rkey']}"
        try:
            payload = await self._get(
                client,
                semaphore,
                "app.bsky.feed.getFeed",
                {
                    "feed": uri,
                    "limit": min(MAX_FEED_PAGE, settings.bluesky_posts_per_trend),
                },
            )
        except httpx.HTTPError as exc:
            log.warning("Skipping Bluesky trend %s: %s", trend["displayName"], exc)
            return None

        # Mapping is pure: a bug here must crash, not look like an
        # unreachable trend.
        items: list[Item] = []
        for view in payload["feed"]:
            post = view["post"]
            if not _is_usable(post):
                continue
            item = _to_item(post, trend, fetched_at)
            if item is not None:
                items.append(item)

        if not items:
            log.warning("Skipping Bluesky trend %s: no usable posts", trend["topic"])
            return None

        replies = await asyncio.gather(
            *(self._replies(client, semaphore, item) for item in items)
        )
        return TrendEvidence(
            trend=_to_trend_info(trend),
            posts=[
                PostEvidence(item=item, replies=group)
                for item, group in zip(items, replies, strict=True)
            ],
        )

    async def _replies(
        self, client: Any, semaphore: asyncio.Semaphore, item: Item
    ) -> list[Reply]:
        try:
            payload = await self._get(
                client,
                semaphore,
                "app.bsky.feed.getPostThread",
                {"uri": item.source_id, "depth": THREAD_DEPTH},
            )
        except httpx.HTTPError as exc:
            # A post without its replies is still evidence of what was
            # posted, so it is kept rather than dropped.
            log.warning("No replies for %s: %s", item.permalink, exc)
            return []
        return list(_walk_replies((payload.get("thread") or {}).get("replies") or []))

    async def _get(
        self,
        client: Any,
        semaphore: asyncio.Semaphore,
        endpoint: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        url = f"{self._api_base}/xrpc/{endpoint}"
        delay = RETRY_BASE_DELAY
        for attempt in range(MAX_ATTEMPTS):
            async with semaphore:
                response = await client.get(url, params=params)
            if response.status_code == 429 and attempt < MAX_ATTEMPTS - 1:
                await asyncio.sleep(delay)
                delay *= 2
                continue
            # On the final attempt a 429 raises here, which the per-trend and
            # per-post guards treat as any other transport failure.
            response.raise_for_status()
            return response.json()
        raise AssertionError("unreachable: the loop always returns or raises")


def _to_trend_info(trend: dict[str, Any]) -> TrendInfo:
    return TrendInfo(
        topic_id=trend["topic"],
        display_name=trend["displayName"],
        # Optional in practice: unspecced endpoints promise nothing.
        description=trend.get("description") or "",
        category=trend.get("category") or "",
        post_count=trend.get("postCount", 0),
        started_at=_parse_timestamp(trend["startedAt"]),
        status=_normalise_status(trend.get("status")),
    )


def _walk_replies(nodes: list[dict[str, Any]]) -> Iterator[Reply]:
    """Flatten the reply tree. Nesting is a fact about who answered whom,
    which no downstream stage reads — the distillation prompt wants the
    conversation, not its shape.
    """
    for node in nodes:
        if node.get("$type") != THREAD_VIEW:
            continue
        post = node.get("post")
        if not post:
            continue
        text = post["record"]["text"].strip()
        if text and not post.get("labels", []):
            yield Reply(
                text=text,
                like_count=post.get("likeCount", 0),
                created_at=_parse_timestamp(post["indexedAt"]),
                author_key=_author_key(post["author"]["did"]),
            )
        yield from _walk_replies(node.get("replies") or [])


def _author_key(did: str) -> str:
    """One-way and truncated. Distinct-account counting is the only thing
    downstream needs; the handle itself has no use and is never stored.
    """
    return hashlib.sha256(did.encode("utf-8")).hexdigest()[:16]
```

Keep `_is_usable`, `_to_item`, `_normalise_status`, `_split_uri` and `_parse_timestamp` exactly as they are in the current file, with their existing comments. `_to_item` still takes `trend: dict[str, Any]` and reads `trend["displayName"]` for `BlueskyMetrics.trend`.

Delete the old `fetch`, `_fetch_trends` and `_fetch_feed` methods and the now-unused `math` and `TREND_LIMIT` (the limit is a setting now).

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_sources_bluesky.py -v`
Expected: PASS

- [ ] **Step 6: Split the source registry**

`BlueskySource` no longer implements `Source`, so leaving it in `BUILDERS` fails type checking, and simply deleting it from `KNOWN_SOURCES` would break the parity guard in `tests/test_sources_composite.py`. Split the registry instead.

In `zeitgeist/config.py`, replace `KNOWN_SOURCES` with:

```python
# Platforms that yield a flat item list and need clustering downstream.
# Dormant: no live pipeline stage consumes them (see the 2026-08-26 spec).
ITEM_SOURCES: tuple[str, ...] = ("lemmy", "wikipedia")
# Platforms that cluster posts into trends themselves and yield evidence.
TREND_SOURCES: tuple[str, ...] = ("bluesky",)
KNOWN_SOURCES: tuple[str, ...] = ITEM_SOURCES + TREND_SOURCES
```

In `zeitgeist/sources/__init__.py`:

```python
"""Source registry. A new platform is a new file plus one entry here."""

from collections.abc import Callable

from zeitgeist.config import Settings
from zeitgeist.sources.base import Source, TrendSource
from zeitgeist.sources.bluesky import BlueskySource
from zeitgeist.sources.composite import CompositeSource
from zeitgeist.sources.lemmy import LemmySource
from zeitgeist.sources.wikipedia import WikipediaSource

# Dormant. Kept wired so the platforms stay buildable and their tests keep
# running; no live pipeline stage calls build_source.
BUILDERS: dict[str, Callable[[Settings], Source]] = {
    "lemmy": LemmySource.from_settings,
    "wikipedia": WikipediaSource.from_settings,
}

TREND_BUILDERS: dict[str, Callable[[Settings], TrendSource]] = {
    "bluesky": BlueskySource.from_settings,
}


def build_source(settings: Settings) -> Source:
    """Build every enabled item source and wrap them in one Source."""
    return CompositeSource([BUILDERS[name](settings) for name in settings.sources])


def build_trend_source(settings: Settings) -> TrendSource:
    """Build the single enabled trend source.

    Settings has already rejected anything else, so a KeyError here would
    mean TREND_BUILDERS and TREND_SOURCES had drifted apart.
    """
    return TREND_BUILDERS[settings.sources[0]](settings)
```

In `tests/test_sources_composite.py`, update the drift guard so it still tests something real:

```python
def test_every_known_source_has_exactly_one_builder():
    """The guard exists because a platform can be namable in config and
    unbuildable, which fails at runtime rather than at import.
    """
    assert set(BUILDERS) == set(ITEM_SOURCES)
    assert set(TREND_BUILDERS) == set(TREND_SOURCES)
    assert set(BUILDERS) | set(TREND_BUILDERS) == set(KNOWN_SOURCES)
```

Import `ITEM_SOURCES`, `TREND_SOURCES`, `KNOWN_SOURCES` from `zeitgeist.config` and `BUILDERS`, `TREND_BUILDERS` from `zeitgeist.sources` in that test file.

- [ ] **Step 7: Definition of Done, then commit**

```bash
uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest
```

```bash
git add zeitgeist/sources zeitgeist/config.py tests/conftest.py tests/test_sources_bluesky.py tests/test_sources_composite.py
git commit -m "feat: gather trend evidence concurrently, replies included"
```

---

### Task 6: Distillation

One LLM call per trend, producing a `Topic` carrying its `Dossier`.

**Files:**
- Create: `zeitgeist/analysis/distil.py`
- Modify: `zeitgeist/config.py`, `tests/conftest.py`
- Test: `tests/test_analysis_distil.py`

**Interfaces:**
- Consumes: `mine_phrases` from `zeitgeist/analysis/phrases.py`; `unique_slug` from `zeitgeist/analysis/slug.py`; `LLMProvider` from `zeitgeist/llm/base.py`; `Dossier`, `Register`, `Sentiment`, `Topic`, `TrendEvidence` from `zeitgeist/models.py`.
- Produces: `distil_topics(evidence: list[TrendEvidence], provider: LLMProvider, settings: Settings) -> list[Topic]`, `DossierDraft` (the model's response schema), `DISTIL_SYSTEM`.
- Produces settings: `distil_char_budget: int = 24000`, `distil_concurrency: int = 4`.

- [ ] **Step 1: Add the settings**

In `zeitgeist/config.py`, beside `phrase_min_authors`:

```python
    # Reply characters sent per distillation call. A single trend can yield
    # six hundred replies; a 32k-context local model truncates silently well
    # before that, so the budget is explicit rather than discovered.
    distil_char_budget: int = 24000
    # Parallel distillation calls. Local Ollama serialises on one GPU, so 1-2
    # is right there; a hosted provider benefits from the default.
    distil_concurrency: int = 4
```

In `tests/conftest.py`, add `"DISTIL_CHAR_BUDGET"` and `"DISTIL_CONCURRENCY"` to `_SETTINGS_ENV_VARS`.

- [ ] **Step 2: Write the failing test**

Create `tests/test_analysis_distil.py`:

```python
"""Distillation: one LLM call per trend, producing a topic and its dossier."""

from datetime import UTC, datetime

import pytest

from zeitgeist.analysis.distil import DossierDraft, distil_topics
from zeitgeist.config import Settings
from zeitgeist.llm.base import FakeLLMProvider, LLMError
from zeitgeist.models import (
    BlueskyMetrics,
    Item,
    PostEvidence,
    Register,
    Reply,
    Sentiment,
    TrendEvidence,
    TrendInfo,
)

NOW = datetime(2026, 8, 26, tzinfo=UTC)


def _settings(**overrides) -> Settings:
    base = {"sources": ["bluesky"], "distil_concurrency": 1, "phrase_min_authors": 3}
    return Settings(**(base | overrides))


def _item(source_id: str, text: str = "something happened") -> Item:
    return Item(
        source_id=source_id,
        title=text,
        permalink=f"https://bsky.app/profile/x/post/{source_id}",
        fetched_at=NOW,
        metrics=BlueskyMetrics(
            like_count=10,
            reply_count=2,
            repost_count=1,
            trend="A trend",
            status="trending",
            created_at=NOW,
        ),
    )


def _reply(text: str, author: str = "a", likes: int = 1) -> Reply:
    return Reply(text=text, like_count=likes, created_at=NOW, author_key=author)


def _evidence(
    name: str = "Canada announces retaliatory tariffs",
    *,
    replies: list[Reply] | None = None,
    posts: int = 1,
) -> TrendEvidence:
    return TrendEvidence(
        trend=TrendInfo(
            topic_id=f"id-{name}",
            display_name=name,
            description="Canada hits back after trade talks collapsed.",
            category="business",
            post_count=4298,
            started_at=NOW,
            status="stale",
        ),
        posts=[
            PostEvidence(item=_item(f"p{i}"), replies=replies or [])
            for i in range(posts)
        ],
    )


def _draft(**overrides) -> DossierDraft:
    base = {
        "what_happened": "Canada imposed tariffs on $30B of US goods.",
        "key_entities": ["Canada"],
        "conversation_summary": "People treat it as overdue.",
        "register": Register.DUNKING,
        "secondary_registers": [],
        "event_sentiment": Sentiment.SCHADENFREUDE,
        "valence": -0.2,
        "meme_potential": 0.8,
    }
    return DossierDraft(**(base | overrides))


def test_a_trend_becomes_a_topic_carrying_its_dossier():
    provider = FakeLLMProvider(responses=[_draft()])
    [topic] = distil_topics([_evidence()], provider, _settings())

    assert topic.label == "Canada announces retaliatory tariffs"
    assert topic.id == "canada-announces-retaliatory-tariffs"
    assert topic.item_ids == ["p0"]
    assert topic.dossier is not None
    assert topic.dossier.register is Register.DUNKING


def test_the_summary_is_what_happened_not_a_tag_confabulation():
    """The whole point: `summary` used to be written from a bag of tags."""
    provider = FakeLLMProvider(responses=[_draft()])
    [topic] = distil_topics([_evidence()], provider, _settings())
    assert topic.summary == "Canada imposed tariffs on $30B of US goods."


def test_mined_phrases_are_attached_rather_than_taken_from_the_model():
    replies = [_reply("elbows up", author=a) for a in ("a", "b", "c", "d")]
    provider = FakeLLMProvider(responses=[_draft()])
    [topic] = distil_topics([_evidence(replies=replies)], provider, _settings())

    assert topic.dossier is not None
    assert [p.text for p in topic.dossier.recurring_phrases] == ["elbows up"]
    assert topic.dossier.recurring_phrases[0].distinct_authors == 4


def test_the_prompt_carries_the_trend_description_and_the_replies():
    replies = [_reply("what a mess", author=a) for a in ("a", "b", "c")]
    provider = FakeLLMProvider(responses=[_draft()])
    distil_topics([_evidence(replies=replies)], provider, _settings())

    prompt = provider.calls[0].prompt
    assert "Canada hits back after trade talks collapsed." in prompt
    assert "what a mess" in prompt


def test_the_prompt_states_how_many_people_used_each_phrase():
    """The counts are what license quoting, so they must reach the model.

    Asserted on the full phrase, not the bare number: "4" also appears in
    the post count, so a substring check would pass without the counts ever
    being rendered.
    """
    replies = [_reply("elbows up", author=a) for a in ("a", "b", "c", "d")]
    provider = FakeLLMProvider(responses=[_draft()])
    distil_topics([_evidence(replies=replies)], provider, _settings())

    assert "4 distinct accounts" in provider.calls[0].prompt


def test_replies_are_truncated_to_the_character_budget():
    """Exactly two 500-character replies fit in a 1000-character budget. An
    upper bound alone would pass even if no replies were included at all.
    """
    replies = [_reply("x" * 500, author=f"a{i}") for i in range(50)]
    provider = FakeLLMProvider(responses=[_draft()])
    distil_topics(
        [_evidence(replies=replies)], provider, _settings(distil_char_budget=1000)
    )
    assert provider.calls[0].prompt.count("x" * 500) == 2


def test_the_most_liked_replies_are_the_ones_kept():
    replies = [
        _reply("unpopular take", author="a", likes=1),
        _reply("the one everyone saw", author="b", likes=900),
    ]
    provider = FakeLLMProvider(responses=[_draft()])
    distil_topics(
        [_evidence(replies=replies)], provider, _settings(distil_char_budget=30)
    )
    prompt = provider.calls[0].prompt
    assert "the one everyone saw" in prompt
    assert "unpopular take" not in prompt


def test_a_failing_trend_is_dropped_and_the_rest_survive():
    provider = FakeLLMProvider(responses=[LLMError("boom"), _draft()])
    topics = distil_topics(
        [_evidence("First"), _evidence("Second")], provider, _settings()
    )
    assert [topic.label for topic in topics] == ["Second"]


def test_every_trend_failing_yields_no_topics():
    provider = FakeLLMProvider(responses=[LLMError("boom")])
    assert distil_topics([_evidence()], provider, _settings()) == []


def test_topic_ids_are_unique_when_two_trends_share_a_label():
    provider = FakeLLMProvider(responses=[_draft(), _draft()])
    topics = distil_topics(
        [_evidence("A trend"), _evidence("A trend")], provider, _settings()
    )
    assert {topic.id for topic in topics} == {"a-trend", "a-trend-2"}


def test_a_trend_with_no_replies_still_produces_a_topic():
    provider = FakeLLMProvider(responses=[_draft()])
    [topic] = distil_topics([_evidence(replies=[])], provider, _settings())
    assert topic.dossier is not None
    assert topic.dossier.recurring_phrases == []


def test_item_ids_cover_every_post_under_the_trend():
    provider = FakeLLMProvider(responses=[_draft()])
    [topic] = distil_topics([_evidence(posts=3)], provider, _settings())
    assert topic.item_ids == ["p0", "p1", "p2"]


def test_no_evidence_means_no_calls():
    provider = FakeLLMProvider(responses=[])
    assert distil_topics([], provider, _settings()) == []
    assert provider.calls == []
```

> `FakeLLMProvider` pops from a shared list, so `distil_concurrency` is pinned to 1 in `_settings` to keep response ordering deterministic. The parallel path is exercised by the real pipeline, not asserted on here.

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_analysis_distil.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'zeitgeist.analysis.distil'`

- [ ] **Step 4: Write the implementation**

Create `zeitgeist/analysis/distil.py`:

```python
"""Evidence to topic: one LLM call per trend.

Replaces the extract-then-consolidate pair. Those two stages spent LLM calls
reconstructing a clustering Bluesky had already done, and lost every specific
fact on the way — consolidation never saw a sentence, only a tag vocabulary,
so the summaries it wrote were confabulations about word clusters.

This stage does the opposite. It sees the trend's own description of the
event, the posts, and what people said underneath them, and its output is the
first thing in the pipeline that knows what actually happened.
"""

import logging
from concurrent.futures import ThreadPoolExecutor

from pydantic import BaseModel, Field

from zeitgeist.analysis.phrases import mine_phrases
from zeitgeist.analysis.slug import unique_slug
from zeitgeist.config import Settings
from zeitgeist.llm.base import LLMProvider
from zeitgeist.models import (
    Dossier,
    Phrase,
    Register,
    Reply,
    Sentiment,
    Topic,
    TrendEvidence,
)

log = logging.getLogger(__name__)

DISTIL_SYSTEM = (
    "You analyse a trending conversation on social media and report what is "
    "actually going on in it.\n\n"
    "You are given a trend, the posts driving it, and replies to those "
    "posts. The posts are often links or headlines; the replies are what "
    "people think. Both matter, and they are not the same thing.\n\n"
    "Report two judgements separately and do not let one contaminate the "
    "other. `event_sentiment` is how the event itself feels. `register` is "
    "the posture people are taking toward it. These frequently disagree, and "
    "the disagreement is the most useful thing you can tell us: a death met "
    "with warm tribute is not the same conversation as a death met with "
    "grief, and neither is the same as one met with jokes.\n\n"
    "Be specific. Name the people, places and organisations involved. "
    "'US politics' is not an answer; 'Canada imposed retaliatory tariffs "
    "after trade talks collapsed' is. If you cannot say concretely what "
    "happened, say what the replies suggest happened rather than retreating "
    "to the category the story belongs to."
)

_PHRASE_GUIDANCE = (
    "These phrases were each used by the stated number of DISTINCT accounts, "
    "counted mechanically. They are the vocabulary this conversation has "
    "converged on. Use them to judge the register, and let them inform how "
    "you write — but your summary must stand on its own. Restating a phrase "
    "is not a summary."
)


class DossierDraft(BaseModel):
    """What the model returns. `recurring_phrases` is not here on purpose:
    it is measured, and a model asked for catchphrases invents them.
    """

    what_happened: str
    key_entities: list[str] = Field(default_factory=list)
    conversation_summary: str
    register: Register
    secondary_registers: list[Register] = Field(default_factory=list)
    event_sentiment: Sentiment
    valence: float = Field(ge=-1.0, le=1.0)
    meme_potential: float = Field(ge=0.0, le=1.0)


def distil_topics(
    evidence: list[TrendEvidence], provider: LLMProvider, settings: Settings
) -> list[Topic]:
    """Distil every trend. A trend whose call fails is dropped, not fatal."""
    if not evidence:
        return []

    with ThreadPoolExecutor(max_workers=settings.distil_concurrency) as pool:
        drafts = list(
            pool.map(lambda one: _distil_one(one, provider, settings), evidence)
        )

    topics: list[Topic] = []
    used_ids: set[str] = set()
    for entry, result in zip(evidence, drafts, strict=True):
        if result is None:
            continue
        draft, phrases = result
        topics.append(
            Topic(
                id=unique_slug(entry.trend.display_name, used_ids),
                label=entry.trend.display_name,
                summary=draft.what_happened,
                item_ids=[post.item.source_id for post in entry.posts],
                dossier=Dossier(
                    **draft.model_dump(),
                    recurring_phrases=phrases,
                ),
            )
        )
    return topics


def _distil_one(
    entry: TrendEvidence, provider: LLMProvider, settings: Settings
) -> tuple[DossierDraft, list[Phrase]] | None:
    replies = [reply for post in entry.posts for reply in post.replies]
    phrases = mine_phrases(
        replies, entry.trend, min_authors=settings.phrase_min_authors
    )
    # Built outside the try: a bug here must crash loudly, not be misreported
    # as a failed trend and silently skipped.
    prompt = _build_prompt(entry, replies, phrases, settings.distil_char_budget)
    try:
        return provider.complete(prompt, DossierDraft, system=DISTIL_SYSTEM), phrases
    except Exception as exc:
        log.warning(
            "Distillation failed for %r; dropping: %s",
            entry.trend.display_name,
            exc,
        )
        return None


def _build_prompt(
    entry: TrendEvidence,
    replies: list[Reply],
    phrases: list[Phrase],
    budget: int,
) -> str:
    trend = entry.trend
    posts = "\n".join(
        f"- [{post.item.metrics.context}] {post.item.title}" for post in entry.posts
    )
    sample = "\n".join(f"- {reply.text}" for reply in _sample(replies, budget))
    phrase_lines = "\n".join(
        f"- {phrase.text!r} — {phrase.distinct_authors} distinct accounts, "
        f"{phrase.occurrences} uses"
        for phrase in phrases
    )

    # None marks a section this trend has nothing for; "" is a deliberate
    # blank line. Only the Nones are dropped.
    sections: list[str | None] = [
        f"Trend: {trend.display_name}",
        f"Description: {trend.description}" if trend.description else None,
        f"Category: {trend.category}" if trend.category else None,
        f"Volume: {trend.post_count} posts, currently {trend.status}",
        "",
        f"Posts driving it:\n{posts}",
        "",
        f"Replies:\n{sample}" if sample else "Replies: none available.",
    ]
    if phrase_lines:
        sections += ["", f"Recurring phrases:\n{phrase_lines}", "", _PHRASE_GUIDANCE]
    sections += [
        "",
        "Report what happened, what people are saying, the event's sentiment "
        "and the conversation's register.",
    ]
    return "\n".join(section for section in sections if section is not None)


def _sample(replies: list[Reply], budget: int) -> list[Reply]:
    """Most-liked first, up to the character budget.

    Sorting by likes biases toward the loudest replies. That is the intended
    bias: what resonated is the question being asked.
    """
    kept: list[Reply] = []
    spent = 0
    for reply in sorted(replies, key=lambda one: -one.like_count):
        if spent + len(reply.text) > budget:
            break
        kept.append(reply)
        spent += len(reply.text)
    return kept
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_analysis_distil.py -v`
Expected: PASS

- [ ] **Step 6: Definition of Done, then commit**

```bash
uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest
```

```bash
git add zeitgeist/analysis/distil.py zeitgeist/config.py tests/conftest.py tests/test_analysis_distil.py
git commit -m "feat: distil trend evidence into dossiers"
```

---

### Task 7: Move sentiment onto the dossier and rewire the brief

The breaking change, done once everything it depends on exists.

**Files:**
- Modify: `zeitgeist/models.py`, `zeitgeist/analysis/sentiment.py`, `zeitgeist/media/brief.py`, `zeitgeist/config.py`, `tests/conftest.py`
- Test: `tests/test_analysis_sentiment.py`, `tests/test_media_brief.py`, `tests/test_config.py`, `tests/test_models.py`

**Interfaces:**
- Consumes: `Dossier`, `Register`, `Topic` from `zeitgeist/models.py`.
- Produces: `ScoredTopic` with only `final_rank` added to `Topic`; `select(scored: list[Topic], top_n: int) -> list[ScoredTopic]`.
- Removes: `judge_topics`, `SentimentJudgement`, `SENTIMENT_SYSTEM`, `Settings.sentiment_weights`, `Settings.weight_for`, `DEFAULT_SENTIMENT_WEIGHTS`.

- [ ] **Step 1: Write the failing test**

Replace `tests/test_analysis_sentiment.py` with:

```python
"""Selection. Sentiment judgement now happens during distillation, where it
has the replies in front of it instead of a label.
"""

from zeitgeist.analysis.sentiment import select
from zeitgeist.models import Dossier, Register, Sentiment, Topic


def _topic(topic_id: str, score: float) -> Topic:
    return Topic(
        id=topic_id, label=topic_id, summary="s", item_ids=["i"], trend_score=score
    )


def _dossier() -> Dossier:
    return Dossier(
        what_happened="Canada imposed tariffs on $30B of US goods.",
        key_entities=["Canada"],
        conversation_summary="People treat it as overdue.",
        register=Register.DUNKING,
        event_sentiment=Sentiment.SCHADENFREUDE,
        valence=-0.2,
        meme_potential=0.8,
    )


def test_topics_are_ranked_by_trend_score():
    ranked = select([_topic("low", 0.2), _topic("high", 0.9)], top_n=2)
    assert [topic.id for topic in ranked] == ["high", "low"]


def test_final_rank_is_one_based_and_in_order():
    ranked = select([_topic("a", 0.9), _topic("b", 0.5), _topic("c", 0.1)], top_n=3)
    assert [topic.final_rank for topic in ranked] == [1, 2, 3]


def test_only_the_top_n_survive():
    ranked = select([_topic("a", 0.9), _topic("b", 0.5), _topic("c", 0.1)], top_n=2)
    assert [topic.id for topic in ranked] == ["a", "b"]


def test_nothing_is_suppressed_by_sentiment():
    """Weights are deliberately gone. A grim topic with a strong trend score
    outranks a cheerful one, which is the point: the tool measures the
    zeitgeist rather than a preferred half of it.
    """
    grim = _topic("grim", 0.9)
    cheerful = _topic("cheerful", 0.3)
    assert [t.id for t in select([cheerful, grim], top_n=2)] == ["grim", "cheerful"]


def test_the_dossier_survives_selection():
    """Compared by value, not identity: `select` rebuilds each topic as a
    ScoredTopic, so the dossier is revalidated rather than passed through.
    An identity check would also pass vacuously when both are None.
    """
    topic = _topic("a", 0.9)
    topic = topic.model_copy(update={"dossier": _dossier()})
    [ranked] = select([topic], top_n=1)
    assert ranked.dossier == topic.dossier
    assert ranked.dossier is not None


def test_no_topics_yields_no_selection():
    assert select([], top_n=5) == []
```

In `tests/test_media_brief.py`, the `ScoredTopic` construction helper must stop passing sentiment fields and start passing a dossier. Add these tests:

```python
def test_the_prompt_carries_what_happened_not_just_the_label():
    """The failure this whole change exists to fix: the caption stage used
    to see a label and a confabulated summary.
    """
    topic = _scored_topic()
    generate_brief(topic, _templates(), FakeLLMProvider(responses=[_choice()]))
    prompt = _last_prompt()
    assert "Canada imposed tariffs on $30B of US goods." in prompt


def test_the_prompt_carries_the_register_and_the_event_sentiment():
    topic = _scored_topic()
    generate_brief(topic, _templates(), FakeLLMProvider(responses=[_choice()]))
    prompt = _last_prompt()
    assert "dunking" in prompt
    assert "schadenfreude" in prompt


def test_the_prompt_offers_recurring_phrases_with_their_counts():
    topic = _scored_topic(
        phrases=[Phrase(text="elbows up", occurrences=41, distinct_authors=33)]
    )
    generate_brief(topic, _templates(), FakeLLMProvider(responses=[_choice()]))
    prompt = _last_prompt()
    assert "elbows up" in prompt
    assert "33" in prompt


def test_a_topic_without_a_dossier_still_produces_a_prompt():
    """The dormant path leaves `dossier` None. Briefing must degrade rather
    than raise, so a stale checkpoint is diagnosable.
    """
    topic = ScoredTopic(id="t", label="A trend", summary="s", item_ids=["i"])
    brief = generate_brief(topic, _templates(), FakeLLMProvider(responses=[_choice()]))
    assert brief.topic_id == "t"
```

Write `_scored_topic`, `_templates`, `_choice` and `_last_prompt` as local helpers in that file, following its existing style; `_scored_topic(phrases=...)` builds a `ScoredTopic` whose `dossier` is a `Dossier` with `what_happened="Canada imposed tariffs on $30B of US goods."`, `register=Register.DUNKING`, `event_sentiment=Sentiment.SCHADENFREUDE` and the given phrases.

In `tests/test_config.py`, delete any test referencing `sentiment_weights` or `weight_for`.

In `tests/test_models.py`, delete assertions that `ScoredTopic` carries `primary_sentiment`, `valence` or `meme_potential`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_analysis_sentiment.py tests/test_media_brief.py -v`
Expected: FAIL — `TypeError: select() got an unexpected keyword argument 'top_n'` / missing dossier fields on the prompt.

- [ ] **Step 3: Slim ScoredTopic**

In `zeitgeist/models.py`:

```python
class ScoredTopic(Topic):
    """A topic with its final ranking attached.

    Sentiment used to live here. It now lives on `Topic.dossier`, judged
    with the replies in front of it rather than from a label, so there is
    one source of truth and no projection to drift.
    """

    final_rank: int = 0
```

- [ ] **Step 4: Rewrite sentiment.py**

Replace `zeitgeist/analysis/sentiment.py` entirely:

```python
"""Final selection.

Ranking is on trend score alone. Sentiment weighting used to sit here,
favouring cheerful topics, and `meme_potential` multiplied on top of it. Both
suppressed topics before there was any evidence that suppression helps, and
both operated on a judgement made from a label rather than from what people
said. `meme_potential` is still recorded on the dossier for inspection; it is
deliberately not applied.
"""

from zeitgeist.models import ScoredTopic, Topic


def select(scored: list[Topic], top_n: int) -> list[ScoredTopic]:
    """Rank by trend score and keep the top N."""
    ranked = sorted(scored, key=lambda topic: topic.trend_score, reverse=True)
    return [
        ScoredTopic(**topic.model_dump(), final_rank=position)
        for position, topic in enumerate(ranked[:top_n], start=1)
    ]
```

- [ ] **Step 5: Drop the weights from config**

In `zeitgeist/config.py`, delete `DEFAULT_SENTIMENT_WEIGHTS`, the `sentiment_weights` field, the `weight_for` method, and the now-unused `Sentiment` import. Remove `"SENTIMENT_WEIGHTS"` from `_SETTINGS_ENV_VARS` in `tests/conftest.py`.

- [ ] **Step 6: Rewire the brief prompt**

In `zeitgeist/media/brief.py`, replace `_build_prompt`:

```python
def _build_prompt(topic: ScoredTopic, templates: dict[str, TemplateManifest]) -> str:
    library = "\n".join(
        f"- id={manifest.id} | shape: {manifest.shape} | "
        "slots: "
        + ", ".join(
            f"{slot.name} (max {slot.max_chars} chars)" for slot in manifest.slots
        )
        for manifest in templates.values()
    )
    return (
        f"Topic: {topic.label}\n\n"
        f"{_context(topic)}\n\n"
        f"Template library:\n{library}\n\n"
        "Pick the best-fitting template and write its captions."
    )


def _context(topic: ScoredTopic) -> str:
    """What the caption is actually about.

    A topic with no dossier comes from the dormant path or a stale
    checkpoint. Degrading to the summary keeps that diagnosable rather than
    raising three stages from the cause.
    """
    dossier = topic.dossier
    if dossier is None:
        return f"Summary: {topic.summary}"

    lines = [
        f"What happened: {dossier.what_happened}",
        f"What people are saying: {dossier.conversation_summary}",
        f"How the event feels: {dossier.event_sentiment.value}",
        f"How people are responding: {dossier.register.value}",
    ]
    if dossier.key_entities:
        lines.append(f"People and organisations: {', '.join(dossier.key_entities)}")
    if dossier.recurring_phrases:
        phrases = "\n".join(
            f"  - {phrase.text!r} ({phrase.distinct_authors} distinct accounts)"
            for phrase in dossier.recurring_phrases
        )
        lines.append(
            "Phrases this conversation has converged on:\n"
            f"{phrases}\n"
            "  A phrase many distinct people independently used IS the "
            "zeitgeist, so quoting one is fair. A caption that only quotes "
            "is not — the joke still has to be yours."
        )
    return "\n".join(lines)
```

Add `Phrase` to the imports in the test file as needed. `BRIEF_SYSTEM` is unchanged; improving it is separate work.

- [ ] **Step 7: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS. `tests/test_pipeline.py` will still fail if it constructs `ScoredTopic` with sentiment fields — update those constructions to drop them; the pipeline itself is rewired in Task 8.

- [ ] **Step 8: Definition of Done, then commit**

```bash
uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest
```

```bash
git add zeitgeist tests
git commit -m "refactor: move sentiment onto the dossier, flatten selection"
```

---

### Task 8: Wire the pipeline

**Files:**
- Modify: `zeitgeist/pipeline.py`, `zeitgeist/cli.py`, `zeitgeist/config.py`
- Test: `tests/test_pipeline.py`, `tests/test_cli.py`, `tests/test_config.py`

**Interfaces:**
- Consumes: `build_trend_source`, `distil_topics`, `select`, `score_topics`.
- Produces: `run_pipeline(settings, source: TrendSource, provider, store, run_id, start_at)` writing `evidence.json`, `topics.json`, `ranked.json`, `briefs.json`.

- [ ] **Step 1: Write the failing test**

In `tests/test_pipeline.py`, add:

```python
def test_ingest_writes_evidence_and_analyse_reads_it(tmp_path):
    """The checkpoint boundary the whole design turns on: everything
    expensive lands before topics.json, so brief tuning re-runs in seconds.
    """
    settings = _settings(tmp_path)
    run_dir = run_pipeline(
        settings=settings,
        source=_FakeTrendSource([_evidence()]),
        provider=FakeLLMProvider(responses=[_draft(), _choice()]),
        store=_store(tmp_path),
        run_id="r1",
    )
    payload = json.loads((run_dir / "evidence.json").read_text(encoding="utf-8"))
    assert payload[0]["trend"]["display_name"] == "A trend"
    assert payload[0]["posts"][0]["replies"][0]["text"] == "what a mess"


def test_topics_json_carries_the_dossier(tmp_path):
    run_dir = run_pipeline(
        settings=_settings(tmp_path),
        source=_FakeTrendSource([_evidence()]),
        provider=FakeLLMProvider(responses=[_draft(), _choice()]),
        store=_store(tmp_path),
        run_id="r1",
    )
    [topic] = json.loads((run_dir / "topics.json").read_text(encoding="utf-8"))
    assert topic["dossier"]["register"] == "dunking"
    assert topic["summary"] == "Canada imposed tariffs on $30B of US goods."


def test_resuming_from_analyse_does_not_refetch(tmp_path):
    settings = _settings(tmp_path)
    source = _FakeTrendSource([_evidence()])
    run_pipeline(
        settings=settings,
        source=source,
        provider=FakeLLMProvider(responses=[_draft(), _choice()]),
        store=_store(tmp_path),
        run_id="r1",
    )
    assert source.calls == 1

    run_pipeline(
        settings=settings,
        source=source,
        provider=FakeLLMProvider(responses=[_draft(), _choice()]),
        store=_store(tmp_path),
        run_id="r1",
        start_at=Stage.ANALYSE,
    )
    assert source.calls == 1


def test_item_count_reflects_the_posts_under_every_trend(tmp_path):
    store = _store(tmp_path)
    run_pipeline(
        settings=_settings(tmp_path),
        source=_FakeTrendSource([_evidence(posts=3)]),
        provider=FakeLLMProvider(responses=[_draft(), _choice()]),
        store=store,
        run_id="r1",
    )
    assert (store.run_summary("r1") or {})["item_count"] == 3
```

Add a fake trend source to that file:

```python
class _FakeTrendSource:
    name = "bluesky"

    def __init__(self, evidence: list[TrendEvidence]) -> None:
        self._evidence = evidence
        self.calls = 0

    def fetch_evidence(self, settings: Settings) -> list[TrendEvidence]:
        self.calls += 1
        return list(self._evidence)
```

Copy `_evidence` and `_draft` from `tests/test_analysis_distil.py` into this file rather than importing them — tests do not import from one another. Give the evidence one reply, `"what a mess"`.

Two existing helpers in this file need updating:

- `_settings(tmp_path)` must now pass `sources=["bluesky"]` and `distil_concurrency=1`; the old default of `["lemmy"]` is rejected at construction after Step 4.
- `_choice()` is the existing `BriefChoice` the fake provider returns for the caption call. Each pipeline run queues two responses in order: the `DossierDraft` for distillation, then the `BriefChoice` for the brief.

In `tests/test_config.py`, add:

```python
def test_selecting_a_dormant_source_fails_at_startup():
    """Better than producing garbage three stages later."""
    with pytest.raises(ValidationError, match="dormant"):
        Settings(sources=["lemmy"])


def test_selecting_more_than_one_source_fails():
    with pytest.raises(ValidationError, match="exactly one"):
        Settings(sources=["bluesky", "lemmy"])


def test_bluesky_is_accepted():
    assert Settings(sources=["bluesky"]).sources == ["bluesky"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_pipeline.py tests/test_config.py -v`
Expected: FAIL — `run_pipeline` still calls `source.fetch`.

- [ ] **Step 3: Rewrite the pipeline stages**

In `zeitgeist/pipeline.py`, change the imports:

```python
from zeitgeist.analysis.distil import distil_topics
from zeitgeist.analysis.score import score_topics
from zeitgeist.analysis.sentiment import select
from zeitgeist.models import Item, MediaBrief, ScoredTopic, Topic, TrendEvidence
from zeitgeist.sources.base import TrendSource
```

Delete the `extract_tags`, `consolidate` and `judge_topics` imports. Replace the stage body:

```python
def run_pipeline(
    settings: Settings,
    source: TrendSource,
    provider: LLMProvider,
    store: Store,
    run_id: str,
    start_at: Stage = Stage.INGEST,
) -> Path:
    run_dir = Path(settings.output_dir) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    resuming = ORDER.index(start_at)

    store.start_run(run_id)

    # Stage A — fatal on failure: with no evidence there is nothing to
    # analyse. Everything expensive happens here and in ANALYSE, so a brief
    # or template change re-runs from GENERATE against frozen dossiers.
    if resuming <= ORDER.index(Stage.INGEST):
        evidence = source.fetch_evidence(settings)
        log.info("Fetched %d trends", len(evidence))
        _write(run_dir / "evidence.json", evidence)
    else:
        evidence = _read(run_dir / "evidence.json", TrendEvidence)

    items: list[Item] = [post.item for entry in evidence for post in entry.posts]

    if resuming <= ORDER.index(Stage.ANALYSE):
        topics = distil_topics(evidence, provider, settings)
        topics = score_topics(
            topics, items, datetime.now(UTC), store.previous_sub_scores(run_id)
        )
        log.info("Distilled %d topics", len(topics))
        store.record_topics(run_id, topics)
        _write(run_dir / "topics.json", topics)

    if resuming <= ORDER.index(Stage.EVALUATE):
        topics = _read(run_dir / "topics.json", Topic)
        ranked = select(topics, settings.topic_count)
        log.info("Selected %d topics", len(ranked))
        _write(run_dir / "ranked.json", ranked)

    ranked = _read(run_dir / "ranked.json", ScoredTopic)
    templates = load_templates(settings.templates_dir)
    briefs = generate_briefs(ranked, templates, provider)
    _write(run_dir / "briefs.json", briefs)

    rendered = _render_all(briefs, templates, settings, run_dir)
    log.info("Rendered %d memes into %s", rendered, run_dir)

    store.finish_run(run_id, status="ok", item_count=len(items))
    return run_dir
```

- [ ] **Step 4: Enforce dormancy in config**

In `zeitgeist/config.py`, replace `_check_sources`:

```python
    @model_validator(mode="after")
    def _check_sources(self) -> Settings:
        """Reject an unusable source selection at startup rather than after
        the pipeline has already created a run directory.

        Only trend sources feed the live pipeline. Lemmy and Wikipedia are
        dormant: their code and tests remain, but nothing consumes a flat
        item list until a consolidation phase exists to build dossiers from
        one. See docs/superpowers/specs/2026-08-26-trend-native-zeitgeist-
        capture-design.md, "Dormant platforms".
        """
        self.sources = [name.lower() for name in self.sources]
        valid = ", ".join(TREND_SOURCES)

        if len(self.sources) != 1:
            raise ValueError(f"SOURCES must name exactly one of: {valid}")

        name = self.sources[0]
        if name in ITEM_SOURCES:
            raise ValueError(
                f"Source {name!r} is dormant: it has no trend clustering, so "
                f"it cannot produce dossiers. Use one of: {valid}"
            )
        if name not in TREND_SOURCES:
            raise ValueError(f"Unknown source: {name!r}. Valid: {valid}")

        return self
```

Change the `sources` default to `["bluesky"]`.

- [ ] **Step 5: Point the CLI at the trend source**

In `zeitgeist/cli.py`, change the import `from zeitgeist.sources import build_source` to `build_trend_source`, and the call `source=build_source(settings)` to `source=build_trend_source(settings)`.

- [ ] **Step 6: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS. `tests/test_cli.py` may assert on the default source list; update it to `bluesky`.

- [ ] **Step 7: Definition of Done, then commit**

```bash
uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest
```

```bash
git add zeitgeist tests
git commit -m "feat: run the pipeline on trend evidence"
```

---

### Task 9: Fixture capture script and documentation

**Files:**
- Create: `scripts/capture_bluesky_fixtures.py`
- Modify: `README.md`, `.env.example`

**Interfaces:**
- Consumes: nothing from earlier tasks at runtime; writes `tests/fixtures/bluesky/{trends,feed,thread}.json`.
- Produces: no importable interface.

- [ ] **Step 1: Write the capture script**

Create `scripts/capture_bluesky_fixtures.py`:

```python
"""Captures real Bluesky payloads into tests/fixtures/bluesky/.

Run when the API's shapes are in question. The fixtures in
tests/test_sources_bluesky.py are hand-built and deliberately minimal; these
are the full article, for checking that a hand-built fixture has not drifted
from what the endpoint actually returns.

    uv run python scripts/capture_bluesky_fixtures.py

Hits the network, so it is a script rather than a test.
"""

import json
from pathlib import Path
from urllib.parse import quote

import httpx

API_BASE = "https://api.bsky.app"
OUT = Path("tests/fixtures/bluesky")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with httpx.Client(
        timeout=30.0, headers={"User-Agent": "zeitgeist-actualiser/0.1"}
    ) as client:
        trends = _get(client, "app.bsky.unspecced.getTrends", {"limit": 25})
        _dump("trends.json", trends)

        trend = trends["trends"][0]
        did, rkey = trend["link"].split("/")[2], trend["link"].split("/")[4]
        uri = f"at://{did}/app.bsky.feed.generator/{rkey}"

        feed = _get(
            client, "app.bsky.feed.getFeed", {"feed": quote(uri, safe=""), "limit": 10}
        )
        _dump("feed.json", feed)

        post = max(feed["feed"], key=lambda v: v["post"].get("replyCount", 0))["post"]
        thread = _get(
            client,
            "app.bsky.feed.getPostThread",
            {"uri": quote(post["uri"], safe=""), "depth": 2},
        )
        _dump("thread.json", thread)

    print(f"Captured trends, feed and thread into {OUT}")


def _get(client: httpx.Client, endpoint: str, params: dict) -> dict:
    response = client.get(f"{API_BASE}/xrpc/{endpoint}", params=params)
    response.raise_for_status()
    return response.json()


def _dump(name: str, payload: dict) -> None:
    (OUT / name).write_text(json.dumps(payload, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run it once to confirm it works**

Run: `uv run python scripts/capture_bluesky_fixtures.py`
Expected: prints the output path; three JSON files exist under `tests/fixtures/bluesky/`.

> These captures contain real posts. Add `tests/fixtures/bluesky/` to `.gitignore` rather than committing them — they are a debugging aid, and the suite's own fixtures are hand-built and hermetic.

- [ ] **Step 3: Update `.env.example`**

Remove any `SENTIMENT_WEIGHTS` line. Change the `SOURCES` line to `SOURCES=bluesky` and add:

```bash
# Only trend sources feed the pipeline. lemmy and wikipedia are dormant.
SOURCES=bluesky

# Fan-out budget. 25 is the getTrends ceiling, not a preference.
BLUESKY_TREND_LIMIT=25
BLUESKY_POSTS_PER_TREND=10
BLUESKY_FETCH_CONCURRENCY=8

# Reply characters per distillation call. Lower this for local models with
# small context windows; raise it for a hosted provider.
DISTIL_CHAR_BUDGET=24000
# Local Ollama serialises on one GPU, so 1-2 is right there.
DISTIL_CONCURRENCY=4

# Distinct accounts a phrase needs before it counts as recurring.
PHRASE_MIN_AUTHORS=3
```

- [ ] **Step 4: Update `README.md`**

Update the pipeline description to the four stages as they now work: ingest writes `evidence.json` (trends, posts, replies); analyse distils one dossier per trend and scores; evaluate ranks on trend score; generate writes briefs and renders. Document the new settings in whatever table or list the README already uses, remove `SENTIMENT_WEIGHTS` and `POST_LIMIT` from the Bluesky path's documentation, and state that `lemmy` and `wikipedia` are dormant with a pointer to the spec's "Dormant platforms" section for the contract to rejoin.

Add a note that `--resume-from generate` re-runs caption writing against a frozen `ranked.json`, which is the loop for tuning template shapes and the brief prompt.

- [ ] **Step 5: Definition of Done, then commit**

```bash
uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest
```

```bash
git add scripts/capture_bluesky_fixtures.py README.md .env.example .gitignore
git commit -m "docs: document the trend-native pipeline and its settings"
```

---

## Verification

After Task 9, confirm end to end against the real API:

```bash
uv run zeitgeist run --verbose
```

Expect: roughly 25 trends fetched in about a minute, one distillation call per trend, and rendered PNGs in `output/<run-id>/`. Then inspect `output/<run-id>/topics.json` and check the thing this plan exists to fix — that `summary` names a specific event rather than a category, and that `dossier.recurring_phrases` contains phrases you recognise from the conversation.

Re-run the tail alone to confirm the checkpoint boundary works:

```bash
uv run zeitgeist run --run-id <run-id> --resume-from generate
```

Expect: seconds, no network calls to Bluesky, new PNGs.
