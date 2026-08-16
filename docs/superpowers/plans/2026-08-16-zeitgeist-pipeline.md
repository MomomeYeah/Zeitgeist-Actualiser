# Zeitgeist Actualiser Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a one-off CLI that scrapes Reddit, identifies trending topics via an LLM map-reduce, ranks them by sentiment, and renders image memes.

**Architecture:** Four sequential stages (ingest → analyse → evaluate → generate), each taking typed Pydantic input, returning typed output, and checkpointing that output as JSON into a per-run directory. All LLM access goes through a single-method `LLMProvider` protocol so backends swap via config. Numeric trend scoring is pure Python, deliberately outside the LLM.

**Tech Stack:** Python 3.14, uv (environment, dependency, and interpreter management), ruff (lint + format), pytest, Pydantic v2, pydantic-settings, PRAW (Reddit), anthropic SDK, httpx (Ollama), Pillow (rendering).

## Global Constraints

### Tooling

- **uv manages everything.** Never invoke `pip`, `python -m venv`, `virtualenv`, or a bare `python`/`pytest`. Dependencies are added with `uv add`, the environment is created by `uv sync`, and commands run through `uv run`.
- **Every command in this plan runs under `uv run`.** Where a step says `uv run pytest ...`, that is the literal command — do not substitute a bare `pytest`, which will resolve against whatever interpreter happens to be on PATH.
- **uv owns the interpreter.** `.python-version` pins the minor series (`3.14`); `uv python install` fetches the current patch release. Do not hard-code a patch version anywhere — it goes stale, and uv keeps it current for free.
- **`uv.lock` is committed.** This is an application, not a library: the lockfile is what makes a run reproducible.
- **ruff is the only linter and the only formatter.** No black, no isort, no flake8.
- **pytest is the only test runner.** No unittest, no nose.

### Code

- **Python 3.14.** `datetime.UTC`, `X | Y` unions, and modern generics are used throughout.
- **All datetimes are timezone-aware UTC.** Never use `datetime.utcnow()`; use `datetime.now(UTC)`.
- **No network access in any test.** Every test uses `FakeLLMProvider` and committed fixtures.
- **`Post` must never carry an author or username field.** Not needed downstream; avoids collecting personal data.
- **Every LLM-facing schema is a Pydantic `BaseModel`.** Providers validate against it and retry once before raising.
- **Stage A failure is fatal; all later stage failures degrade.** A run producing fewer memes than requested is a success.
- **Line length 88.** `uv run ruff format .` and `uv run ruff check --fix .` must both be clean before every commit.
- **Commit after every task.** Conventional commit prefixes (`feat:`, `test:`, `chore:`).

## File Structure

| File | Responsibility |
|---|---|
| `pyproject.toml` | Package metadata, dependencies, pytest/ruff config |
| `zeitgeist/models.py` | Domain models: `Sentiment`, `Post`, `Topic`, `ScoredTopic`, `MediaBrief` |
| `zeitgeist/config.py` | `Settings` via pydantic-settings |
| `zeitgeist/store.py` | SQLite persistence for cross-run history |
| `zeitgeist/cli.py` | Argument parsing, run orchestration, checkpointing |
| `zeitgeist/sources/base.py` | `Source` protocol |
| `zeitgeist/sources/reddit.py` | `RedditSource` via PRAW |
| `zeitgeist/llm/base.py` | `LLMProvider` protocol, `FakeLLMProvider`, `LLMError` |
| `zeitgeist/llm/anthropic.py` | `AnthropicProvider` (tool use) |
| `zeitgeist/llm/ollama.py` | `OllamaProvider` (JSON schema format) |
| `zeitgeist/analysis/extract.py` | Map stage: posts → tags |
| `zeitgeist/analysis/consolidate.py` | Reduce stage: tags → canonical topics |
| `zeitgeist/analysis/score.py` | Pure trend scoring |
| `zeitgeist/analysis/sentiment.py` | Sentiment judgement + weighted selection |
| `zeitgeist/media/templates.py` | Manifest models, loader, validator |
| `zeitgeist/media/brief.py` | Topic → template choice + captions |
| `zeitgeist/media/render.py` | Pillow compositing |
| `zeitgeist/media/templates/` | 24 template images + JSON manifests |
| `zeitgeist/media/fonts/` | Vendored DejaVuSans-Bold.ttf |

---

### Task 1: Project scaffold and domain models

**Files:**
- Create: `pyproject.toml`, `.python-version`, `uv.lock`, `.gitignore`, `zeitgeist/__init__.py`, `zeitgeist/models.py`, `tests/__init__.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Consumes: nothing
- Produces: `Sentiment` (str enum), `Post`, `Topic`, `ScoredTopic`, `MediaBrief` — all Pydantic `BaseModel`. Field names exactly as written below; every later task depends on them.

- [ ] **Step 1: Install uv**

Check first — it may already be present:

```bash
uv --version
```

If that fails, install it (Windows, PowerShell):

```bash
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Then reopen the shell and confirm `uv --version` prints a version. Everything after this point goes through uv.

- [ ] **Step 2: Pin the interpreter and let uv fetch it**

```bash
uv python install 3.14
```

Then create `.python-version` containing exactly:

```
3.14
```

Pinning the minor series rather than a patch is deliberate: uv resolves it to the newest 3.14.x available and keeps doing so, where a hard-coded patch would be stale within weeks.

- [ ] **Step 3: Create `pyproject.toml`**

```toml
[project]
name = "zeitgeist"
version = "0.1.0"
description = "Finds what the internet is talking about and makes memes about it."
requires-python = ">=3.14"
dependencies = [
    "pydantic>=2.12",
    "pydantic-settings>=2.6",
    "praw>=7.8",
    "anthropic>=0.40",
    "httpx>=0.28",
    "pillow>=11.3",
]

[project.scripts]
zeitgeist = "zeitgeist.cli:main"

[dependency-groups]
dev = ["pytest>=8.3", "ruff>=0.8"]

[build-system]
requires = ["uv_build>=0.9"]
build-backend = "uv_build"

[tool.uv.build-backend]
module-name = "zeitgeist"
# uv_build assumes a src/ layout by default; this project is flat, so the
# module root is the project root. Omitting this fails the build with
# "expected module at src/zeitgeist".
module-root = ""

[tool.pytest.ini_options]
testpaths = ["tests"]

[tool.ruff]
line-length = 88
target-version = "py314"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM"]
```

Dev tooling goes in `[dependency-groups]` (PEP 735) rather than `[project.optional-dependencies]`, because `uv sync` installs it by default and it never leaks into what a consumer of the package would install.

Lower bounds are floors, not pins — uv resolves the newest compatible release and records the exact versions in `uv.lock`.

- [ ] **Step 4: Create the environment**

```bash
uv sync
```

Expected: uv creates `.venv/`, resolves every dependency, and writes `uv.lock`.

If resolution fails because a dependency has no 3.14 wheel yet, do not silently downgrade the project. Report which package failed, then change `.python-version` and `requires-python` to `3.13` as a fallback and note it — the rest of the plan is unaffected.

- [ ] **Step 5: Create `.gitignore`**

```
__pycache__/
*.py[cod]
.venv/
venv/
.env
output/
data/
.pytest_cache/
*.egg-info/
```

- [ ] **Step 6: Create empty `zeitgeist/__init__.py` and `tests/__init__.py`**

Both files are empty. Create them so the package and test suite are importable.

- [ ] **Step 7: Write the failing test**

Create `tests/test_models.py`:

```python
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from zeitgeist.models import MediaBrief, Post, ScoredTopic, Sentiment, Topic

# The complete specified field set. Written out by hand rather than derived
# from the model, so that a change to the model fails this test.
POST_FIELDS = {
    "platform",
    "source_id",
    "title",
    "body_excerpt",
    "permalink",
    "score",
    "comment_count",
    "created_at",
    "fetched_at",
    "channel",
}


def _post(**overrides) -> Post:
    defaults = dict(
        platform="reddit",
        source_id="abc123",
        title="Cat learns to open door",
        body_excerpt=None,
        permalink="https://reddit.com/r/cats/abc123",
        score=4200,
        comment_count=311,
        created_at=datetime(2026, 8, 16, 9, 0, tzinfo=UTC),
        fetched_at=datetime(2026, 8, 16, 12, 0, tzinfo=UTC),
        channel="cats",
    )
    return Post(**{**defaults, **overrides})


def _scored(**overrides) -> ScoredTopic:
    defaults = dict(
        id="cats",
        label="Cats",
        summary="Cat things.",
        post_ids=["abc123"],
        primary_sentiment=Sentiment.CUTE,
        valence=0.5,
        meme_potential=0.5,
    )
    return ScoredTopic(**{**defaults, **overrides})


def test_post_carries_exactly_the_specified_fields():
    """Catches two breaks at once: a PII field such as `author` creeping in,
    and a field the checkpoint format depends on quietly disappearing.
    """
    assert set(Post.model_fields) == POST_FIELDS


@pytest.mark.parametrize("field", ["author", "username", "user_id", "titel"])
def test_post_rejects_undeclared_fields(field):
    """Without extra="forbid", Pydantic silently drops unknown keys — so a
    typo'd field name or an author slipped in by a new source would pass
    unnoticed rather than failing loudly.
    """
    with pytest.raises(ValidationError):
        _post(**{field: "somebody"})


@pytest.mark.parametrize("valence", [-1.01, 1.01, 5.0, -5.0])
def test_valence_outside_minus_one_to_one_is_rejected(valence):
    with pytest.raises(ValidationError):
        _scored(valence=valence)


@pytest.mark.parametrize("valence", [-1.0, 0.0, 1.0])
def test_valence_accepts_its_boundaries(valence):
    assert _scored(valence=valence).valence == valence


@pytest.mark.parametrize("meme_potential", [-0.01, 1.01])
def test_meme_potential_outside_zero_to_one_is_rejected(meme_potential):
    with pytest.raises(ValidationError):
        _scored(meme_potential=meme_potential)


@pytest.mark.parametrize("meme_potential", [0.0, 1.0])
def test_meme_potential_accepts_its_boundaries(meme_potential):
    assert _scored(meme_potential=meme_potential).meme_potential == meme_potential


def test_topic_defaults_leave_room_for_the_scoring_stage():
    """score_topics fills these in later; the defaults are what let a topic
    exist between consolidation and scoring.
    """
    topic = Topic(id="cats", label="Cats", summary="Cat things.", post_ids=["abc123"])
    assert topic.trend_score == 0.0
    assert topic.score_components == {}


def test_scored_topic_defaults_leave_room_for_the_selection_stage():
    scored = _scored()
    assert scored.secondary_sentiments == []
    assert scored.final_rank == 0


def test_scored_topic_accepts_every_field_of_a_scored_topic():
    """judge_topics constructs ScoredTopic(**topic.model_dump(), ...). If the
    two models drift apart, that call breaks — here rather than mid-run.
    """
    topic = Topic(
        id="cats",
        label="Cats",
        summary="Cat things.",
        post_ids=["abc123"],
        trend_score=0.7,
        score_components={"base": 0.7},
    )
    scored = ScoredTopic(
        **topic.model_dump(),
        primary_sentiment=Sentiment.CUTE,
        valence=0.5,
        meme_potential=0.5,
    )
    assert scored.trend_score == 0.7
    assert scored.score_components == {"base": 0.7}


def test_media_brief_rejects_undeclared_fields():
    with pytest.raises(ValidationError):
        MediaBrief(
            topic_id="cats",
            template_id="drake",
            caption_slots={"rejected": "Dogs"},
            rationale="",
            image_url="http://example.com/not-a-real-field",
        )
```

- [ ] **Step 8: Run test to verify it fails**

Run: `uv run pytest tests/test_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'zeitgeist.models'`

- [ ] **Step 9: Write `zeitgeist/models.py`**

```python
"""Domain models shared across every pipeline stage."""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

# Unknown keys are an error, not something to drop quietly. A misspelled field
# in a new Source, or an `author` slipped in by a future platform, should fail
# loudly at the boundary rather than vanish.
STRICT = ConfigDict(extra="forbid")


class Sentiment(str, Enum):
    """Fixed taxonomy so results are comparable across runs."""

    CUTE = "cute"
    HEARTWARMING = "heartwarming"
    FUNNY = "funny"
    AWE = "awe"
    SCHADENFREUDE = "schadenfreude"
    OUTRAGE = "outrage"
    SAD = "sad"
    SCARY = "scary"
    GROSS = "gross"
    CRINGE = "cringe"
    MUNDANE = "mundane"


class Post(BaseModel):
    """A single normalised item from any platform.

    Deliberately carries no author or username: no downstream stage needs it,
    and omitting it keeps the project clear of storing personal data.
    """

    model_config = STRICT

    platform: str
    source_id: str
    title: str
    body_excerpt: str | None = None
    permalink: str
    score: int
    comment_count: int
    created_at: datetime
    fetched_at: datetime
    channel: str


class Topic(BaseModel):
    """A cluster of posts about the same thing."""

    model_config = STRICT

    id: str
    label: str
    summary: str
    post_ids: list[str]
    trend_score: float = 0.0
    score_components: dict[str, float] = Field(default_factory=dict)


class ScoredTopic(Topic):
    """A topic with its sentiment judgement and final ranking attached."""

    primary_sentiment: Sentiment
    secondary_sentiments: list[Sentiment] = Field(default_factory=list)
    valence: float = Field(ge=-1.0, le=1.0)
    meme_potential: float = Field(ge=0.0, le=1.0)
    final_rank: int = 0


class MediaBrief(BaseModel):
    """Instructions for rendering one piece of media."""

    model_config = STRICT

    topic_id: str
    template_id: str
    caption_slots: dict[str, str]
    rationale: str
```

- [ ] **Step 10: Run tests to verify they pass**

Run: `uv run pytest tests/test_models.py -v`
Expected: PASS, 20 tests

- [ ] **Step 11: Format and lint**

```bash
uv run ruff format . && uv run ruff check --fix .
```

Expected: both clean. Run this before every commit from here on — later tasks say "format and lint" and mean exactly this command.

- [ ] **Step 12: Commit**

```bash
git add pyproject.toml .python-version uv.lock .gitignore zeitgeist tests
git commit -m "feat: add uv project scaffold and domain models"
```

---

### Task 2: Settings

**Files:**
- Create: `zeitgeist/config.py`, `.env.example`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: `Sentiment` from Task 1
- Produces: `Settings` (pydantic-settings `BaseSettings`) with fields `reddit_client_id`, `reddit_client_secret`, `reddit_user_agent`, `anthropic_api_key`, `llm_provider`, `llm_model`, `ollama_host`, `subreddits` (`list[str]`), `post_limit`, `topic_count`, `sentiment_weights` (`dict[Sentiment, float]`), `font_path`, `output_dir`, `db_path`. Also `Settings.weight_for(sentiment) -> float`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_config.py`:

```python
import pytest

from zeitgeist.config import DEFAULT_SENTIMENT_WEIGHTS, Settings
from zeitgeist.models import Sentiment


def _settings(**overrides) -> Settings:
    defaults = dict(
        reddit_client_id="id",
        reddit_client_secret="secret",
        anthropic_api_key="key",
    )
    return Settings(**{**defaults, **overrides})


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("cats,aww", ["cats", "aww"]),
        ("cats, aww ,mildlyinteresting", ["cats", "aww", "mildlyinteresting"]),
        ("cats,,aww,", ["cats", "aww"]),
        ("  ", []),
        ("", []),
        (["cats", "aww"], ["cats", "aww"]),
    ],
)
def test_subreddits_parse_from_env_strings(raw, expected):
    """Env vars arrive as strings; the validator has to survive the messy
    ways a human writes a list into a .env file.
    """
    assert _settings(subreddits=raw).subreddits == expected


def test_every_sentiment_has_a_default_weight():
    """A sentiment added to the enum without a weight would silently score
    as neutral, quietly defeating the preference for positive topics.
    """
    assert set(DEFAULT_SENTIMENT_WEIGHTS) == set(Sentiment)


def test_weight_for_falls_back_to_neutral_when_unconfigured():
    """A user who overrides SENTIMENT_WEIGHTS with a partial map must not
    crash the run on the sentiments they left out.
    """
    settings = _settings(sentiment_weights={Sentiment.CUTE: 2.0})
    assert settings.weight_for(Sentiment.CUTE) == 2.0
    assert settings.weight_for(Sentiment.SAD) == 1.0
```

`test_defaults_are_populated` and `test_positive_sentiments_outweigh_negative_ones` are deliberately **not** here. The first asserts constants back at themselves — it fails on every intentional retune and catches no bug. The second states a design decision as a comparison of two numbers; the behaviour it actually protects is tested for real in `test_analysis_sentiment.py`, where a positive topic is shown to outrank a negative one at equal trend.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'zeitgeist.config'`

- [ ] **Step 3: Write `zeitgeist/config.py`**

```python
"""Runtime configuration, loaded from environment and `.env`."""

from pathlib import Path
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from zeitgeist.models import Sentiment

PACKAGE_ROOT = Path(__file__).parent

# Favours positive output without excluding anything. The spread is moderate
# on purpose: a negative topic needs roughly double the combined trend and
# meme-potential score to outrank a positive one, which is a thumb on the
# scale rather than a veto.
DEFAULT_SENTIMENT_WEIGHTS: dict[Sentiment, float] = {
    Sentiment.HEARTWARMING: 1.30,
    Sentiment.CUTE: 1.25,
    Sentiment.FUNNY: 1.25,
    Sentiment.AWE: 1.20,
    Sentiment.SCHADENFREUDE: 1.00,
    Sentiment.CRINGE: 0.90,
    Sentiment.MUNDANE: 0.70,
    Sentiment.GROSS: 0.70,
    Sentiment.SAD: 0.60,
    Sentiment.SCARY: 0.60,
    Sentiment.OUTRAGE: 0.60,
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    reddit_client_id: str
    reddit_client_secret: str
    reddit_user_agent: str = "zeitgeist-actualiser/0.1 (by u/anonymous)"

    anthropic_api_key: str = ""
    llm_provider: Literal["anthropic", "ollama"] = "anthropic"
    llm_model: str = "claude-sonnet-5"
    ollama_host: str = "http://localhost:11434"

    subreddits: list[str] = []
    post_limit: int = 500
    topic_count: int = 5

    sentiment_weights: dict[Sentiment, float] = DEFAULT_SENTIMENT_WEIGHTS

    font_path: Path = PACKAGE_ROOT / "media" / "fonts" / "DejaVuSans-Bold.ttf"
    templates_dir: Path = PACKAGE_ROOT / "media" / "templates"
    output_dir: Path = Path("output")
    db_path: Path = Path("data") / "zeitgeist.db"

    @field_validator("subreddits", mode="before")
    @classmethod
    def _split_subreddits(cls, value: object) -> object:
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return value

    def weight_for(self, sentiment: Sentiment) -> float:
        """Weight for a sentiment, defaulting to neutral when unconfigured."""
        return self.sentiment_weights.get(sentiment, 1.0)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_config.py -v`
Expected: PASS, 8 tests

- [ ] **Step 5: Create `.env.example`**

```
REDDIT_CLIENT_ID=your_client_id
REDDIT_CLIENT_SECRET=your_client_secret
REDDIT_USER_AGENT=zeitgeist-actualiser/0.1 (by u/yourname)

ANTHROPIC_API_KEY=sk-ant-...

LLM_PROVIDER=anthropic
LLM_MODEL=claude-sonnet-5
OLLAMA_HOST=http://localhost:11434

SUBREDDITS=aww,mildlyinteresting,nextfuckinglevel
POST_LIMIT=500
TOPIC_COUNT=5
```

- [ ] **Step 6: Commit**

```bash
git add zeitgeist/config.py .env.example tests/test_config.py
git commit -m "feat: add settings with default sentiment weights"
```

---

### Task 3: LLM provider protocol and fake

**Files:**
- Create: `zeitgeist/llm/__init__.py`, `zeitgeist/llm/base.py`
- Test: `tests/test_llm_base.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `LLMError(Exception)`
  - `LLMProvider` protocol: `name: str` and `complete(prompt: str, schema: type[M], *, system: str | None = None) -> M` where `M` is bound to `BaseModel`
  - `FakeLLMProvider` with `__init__(responses=None)`, `queue(response)`, `calls: list[LLMCall]`, and `complete(...)`. A queued `Exception` instance is raised instead of returned — this is how later tasks test degradation.
  - `LLMCall` dataclass with `prompt: str`, `system: str | None`, `schema: type[BaseModel]`

`FakeLLMProvider` is built before any stage that depends on it, because it is what makes the pipeline testable at all.

- [ ] **Step 1: Write the failing test**

Create `tests/test_llm_base.py`:

```python
import pytest
from pydantic import BaseModel

from zeitgeist.llm.base import FakeLLMProvider, LLMError


class Answer(BaseModel):
    value: str


class Other(BaseModel):
    number: int


def test_returns_queued_responses_in_order():
    provider = FakeLLMProvider([Answer(value="first"), Answer(value="second")])
    assert provider.complete("p1", Answer).value == "first"
    assert provider.complete("p2", Answer).value == "second"


def test_records_each_call():
    provider = FakeLLMProvider([Answer(value="x")])
    provider.complete("the prompt", Answer, system="the system")
    assert len(provider.calls) == 1
    assert provider.calls[0].prompt == "the prompt"
    assert provider.calls[0].system == "the system"
    assert provider.calls[0].schema is Answer


def test_raises_when_queue_is_empty():
    provider = FakeLLMProvider()
    with pytest.raises(AssertionError, match="no queued response"):
        provider.complete("p", Answer)


def test_raises_when_queued_response_has_wrong_schema():
    provider = FakeLLMProvider([Other(number=1)])
    with pytest.raises(AssertionError, match="expected Answer"):
        provider.complete("p", Answer)


def test_queued_exception_is_raised():
    provider = FakeLLMProvider([LLMError("model exploded")])
    with pytest.raises(LLMError, match="model exploded"):
        provider.complete("p", Answer)
```

Every test here guards something other tests rely on. The double is what keeps roughly forty other tests honest, so its own failure modes matter: silently returning the wrong schema, or silently succeeding when a test forgot to queue a response, would turn real assertions elsewhere into tautologies. That is the break these five catch.

`queue()` is deliberately absent from the double — no test needs it, and an unused method on a test utility is just more surface to maintain.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_llm_base.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'zeitgeist.llm'`

- [ ] **Step 3: Create empty `zeitgeist/llm/__init__.py`**

Empty file.

- [ ] **Step 4: Write `zeitgeist/llm/base.py`**

```python
"""The single narrow interface every pipeline stage uses to reach a model."""

from dataclasses import dataclass, field
from typing import Protocol, TypeVar

from pydantic import BaseModel

M = TypeVar("M", bound=BaseModel)


class LLMError(Exception):
    """Raised when a provider cannot return a valid structured response."""


class LLMProvider(Protocol):
    """Every stage needs the same thing: a validated structured object.

    Keeping this to one method is what makes the local-versus-cloud
    comparison honest — swapping backends changes one config value and
    nothing else.
    """

    name: str

    def complete(
        self, prompt: str, schema: type[M], *, system: str | None = None
    ) -> M: ...


@dataclass
class LLMCall:
    prompt: str
    system: str | None
    schema: type[BaseModel]


@dataclass
class FakeLLMProvider:
    """Test double returning queued responses and recording prompts.

    A queued ``Exception`` is raised rather than returned, so tests can
    exercise the degradation paths every stage is required to have.
    """

    responses: list[BaseModel | Exception] = field(default_factory=list)
    name: str = "fake"
    calls: list[LLMCall] = field(default_factory=list)

    def complete(
        self, prompt: str, schema: type[M], *, system: str | None = None
    ) -> M:
        self.calls.append(LLMCall(prompt=prompt, system=system, schema=schema))
        if not self.responses:
            raise AssertionError(
                f"FakeLLMProvider: no queued response for {schema.__name__}"
            )
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        if not isinstance(response, schema):
            raise AssertionError(
                f"FakeLLMProvider: expected {schema.__name__}, "
                f"got {type(response).__name__}"
            )
        return response
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_llm_base.py -v`
Expected: PASS, 5 tests

- [ ] **Step 6: Commit**

```bash
git add zeitgeist/llm tests/test_llm_base.py
git commit -m "feat: add LLM provider protocol and test double"
```

---

### Task 4: Anthropic provider

**Files:**
- Create: `zeitgeist/llm/anthropic.py`
- Test: `tests/test_llm_anthropic.py`

**Interfaces:**
- Consumes: `LLMError`, `LLMProvider` from Task 3
- Produces: `AnthropicProvider(api_key: str, model: str, client=None)` implementing `LLMProvider`. Uses tool use with the Pydantic JSON schema as the tool input schema, and retries once with the validation error appended before raising `LLMError`.

The `client` parameter exists solely so tests can inject a stub. No test touches the network.

- [ ] **Step 1: Write the failing test**

Create `tests/test_llm_anthropic.py`:

```python
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from zeitgeist.llm.anthropic import AnthropicProvider
from zeitgeist.llm.base import LLMError


class Answer(BaseModel):
    value: str


def _tool_response(payload: dict) -> SimpleNamespace:
    block = SimpleNamespace(type="tool_use", name="respond", input=payload)
    return SimpleNamespace(content=[block])


class StubClient:
    """Stands in for anthropic.Anthropic; records kwargs, replays responses."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.requests = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.requests.append(kwargs)
        return self._responses.pop(0)


def _provider(client) -> AnthropicProvider:
    return AnthropicProvider(api_key="k", model="claude-test", client=client)


def test_returns_validated_model():
    provider = _provider(StubClient([_tool_response({"value": "hello"})]))
    assert provider.complete("prompt", Answer).value == "hello"


def test_sends_the_schema_as_the_tool_contract():
    """The request payload is our contract with the API. A wrong tool name,
    a missing tool_choice, or a schema that is not the one asked for all
    produce unstructured replies at runtime and nothing else catches them.
    """
    client = StubClient([_tool_response({"value": "hello"})])
    _provider(client).complete("prompt", Answer, system="be terse")

    request = client.requests[0]
    assert request["model"] == "claude-test"
    assert request["system"] == "be terse"
    assert request["messages"] == [{"role": "user", "content": "prompt"}]
    assert request["tool_choice"] == {"type": "tool", "name": "respond"}
    assert request["tools"][0]["name"] == "respond"
    assert request["tools"][0]["input_schema"] == Answer.model_json_schema()


def test_system_key_is_absent_when_no_system_prompt_is_given():
    """Sending system=None is an API error, so the key must be omitted
    entirely rather than passed as null.
    """
    client = StubClient([_tool_response({"value": "hello"})])
    _provider(client).complete("prompt", Answer)
    assert "system" not in client.requests[0]


def test_retries_once_with_the_validation_error_appended():
    client = StubClient(
        [_tool_response({"wrong": 1}), _tool_response({"value": "recovered"})]
    )
    assert _provider(client).complete("prompt", Answer).value == "recovered"

    retry_prompt = client.requests[1]["messages"][0]["content"]
    assert "prompt" in retry_prompt
    assert "value" in retry_prompt, "the retry must tell the model what was wrong"


def test_gives_up_after_exactly_two_attempts():
    """Bounds the retry: an unbounded loop against a model that always
    returns garbage would spend money until the process is killed.
    """
    client = StubClient(
        [
            _tool_response({"wrong": 1}),
            _tool_response({"bad": 2}),
            _tool_response({"value": "never reached"}),
        ]
    )
    provider = _provider(client)
    with pytest.raises(LLMError, match="Answer"):
        provider.complete("prompt", Answer)
    assert len(client.requests) == 2


def test_raises_when_no_tool_use_block_returned():
    """A text-only reply must not be mistaken for a valid empty result."""
    client = StubClient([SimpleNamespace(content=[]), SimpleNamespace(content=[])])
    with pytest.raises(LLMError):
        _provider(client).complete("prompt", Answer)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_llm_anthropic.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'zeitgeist.llm.anthropic'`

- [ ] **Step 3: Write `zeitgeist/llm/anthropic.py`**

```python
"""Anthropic backend. Uses tool use, the most reliable structured-output path."""

from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from zeitgeist.llm.base import LLMError

M = TypeVar("M", bound=BaseModel)

TOOL_NAME = "respond"
MAX_TOKENS = 4096


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, api_key: str, model: str, client: Any = None) -> None:
        if client is None:
            from anthropic import Anthropic

            client = Anthropic(api_key=api_key)
        self._client = client
        # Public: the factory wires these from Settings, and tests assert it.
        self.model = model

    def complete(
        self, prompt: str, schema: type[M], *, system: str | None = None
    ) -> M:
        tool = {
            "name": TOOL_NAME,
            "description": schema.__doc__ or f"Return a {schema.__name__}.",
            "input_schema": schema.model_json_schema(),
        }
        attempt_prompt = prompt
        last_error: str | None = None

        for _ in range(2):
            kwargs: dict[str, Any] = {
                "model": self.model,
                "max_tokens": MAX_TOKENS,
                "tools": [tool],
                "tool_choice": {"type": "tool", "name": TOOL_NAME},
                "messages": [{"role": "user", "content": attempt_prompt}],
            }
            if system is not None:
                kwargs["system"] = system

            response = self._client.messages.create(**kwargs)
            payload = _extract_tool_input(response)

            if payload is None:
                last_error = "no tool_use block in response"
            else:
                try:
                    return schema.model_validate(payload)
                except ValidationError as exc:
                    last_error = str(exc)

            attempt_prompt = (
                f"{prompt}\n\nYour previous response failed validation:\n"
                f"{last_error}\n\nReturn a corrected response."
            )

        raise LLMError(
            f"Anthropic did not return a valid {schema.__name__}: {last_error}"
        )


def _extract_tool_input(response: Any) -> dict | None:
    for block in getattr(response, "content", []):
        if getattr(block, "type", None) == "tool_use":
            return block.input
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_llm_anthropic.py -v`
Expected: PASS, 6 tests

- [ ] **Step 5: Commit**

```bash
git add zeitgeist/llm/anthropic.py tests/test_llm_anthropic.py
git commit -m "feat: add Anthropic provider using tool use"
```

---

### Task 5: Ollama provider and provider factory

**Files:**
- Create: `zeitgeist/llm/ollama.py`, `zeitgeist/llm/factory.py`
- Test: `tests/test_llm_ollama.py`, `tests/test_llm_factory.py`

**Interfaces:**
- Consumes: `LLMError` from Task 3, `AnthropicProvider` from Task 4, `Settings` from Task 2
- Produces:
  - `OllamaProvider(host: str, model: str, client=None)` implementing `LLMProvider`, using Ollama's `/api/chat` with `format` set to the Pydantic JSON schema
  - `build_provider(settings: Settings) -> LLMProvider`

- [ ] **Step 1: Write the failing test for Ollama**

Create `tests/test_llm_ollama.py`:

```python
import json

import pytest
from pydantic import BaseModel

from zeitgeist.llm.base import LLMError
from zeitgeist.llm.ollama import OllamaProvider


class Answer(BaseModel):
    value: str


class StubResponse:
    """Ollama replies with the model's text in message.content."""

    def __init__(self, content: str, error: Exception | None = None):
        self._content = content
        self._error = error

    def raise_for_status(self):
        if self._error is not None:
            raise self._error

    def json(self):
        return {"message": {"content": self._content}}


class StubClient:
    """Replays raw response bodies so malformed output is as easy to stage
    as valid output — no subclassing needed per case.
    """

    def __init__(self, responses: list[StubResponse]):
        self._responses = list(responses)
        self.requests = []

    def post(self, url, json=None, timeout=None):
        self.requests.append((url, json, timeout))
        return self._responses.pop(0)


def _ok(payload: dict) -> StubResponse:
    return StubResponse(json.dumps(payload))


def _provider(client) -> OllamaProvider:
    return OllamaProvider(host="http://h", model="qwen-test", client=client)


def test_returns_validated_model():
    assert _provider(StubClient([_ok({"value": "hello"})])).complete(
        "prompt", Answer
    ).value == "hello"


def test_sends_the_schema_as_the_format_constraint():
    """Ollama only constrains output when `format` carries the JSON schema
    and streaming is off. Losing either silently returns prose.
    """
    client = StubClient([_ok({"value": "hello"})])
    _provider(client).complete("prompt", Answer, system="be terse")

    url, body, timeout = client.requests[0]
    assert url == "http://h/api/chat"
    assert body["model"] == "qwen-test"
    assert body["format"] == Answer.model_json_schema()
    assert body["stream"] is False
    assert body["messages"] == [
        {"role": "system", "content": "be terse"},
        {"role": "user", "content": "prompt"},
    ]
    assert timeout is not None, "a local model can take minutes; never unbounded"


def test_omits_the_system_message_when_none_is_given():
    client = StubClient([_ok({"value": "hello"})])
    _provider(client).complete("prompt", Answer)
    assert client.requests[0][1]["messages"] == [
        {"role": "user", "content": "prompt"}
    ]


def test_trailing_slash_on_host_does_not_double_up():
    client = StubClient([_ok({"value": "hello"})])
    OllamaProvider(host="http://h/", model="m", client=client).complete(
        "prompt", Answer
    )
    assert client.requests[0][0] == "http://h/api/chat"


def test_retries_once_with_the_validation_error_appended():
    client = StubClient([_ok({"wrong": 1}), _ok({"value": "recovered"})])
    assert _provider(client).complete("prompt", Answer).value == "recovered"
    assert "value" in client.requests[1][1]["messages"][0]["content"]


def test_malformed_json_is_treated_as_a_validation_failure():
    """Small local models emit prose around their JSON often enough that
    this must be a retry, not a crash.
    """
    client = StubClient([StubResponse("not json at all"), _ok({"value": "ok"})])
    assert _provider(client).complete("prompt", Answer).value == "ok"


def test_gives_up_after_exactly_two_attempts():
    client = StubClient(
        [_ok({"wrong": 1}), _ok({"bad": 2}), _ok({"value": "never reached"})]
    )
    client_provider = _provider(client)
    with pytest.raises(LLMError, match="Answer"):
        client_provider.complete("prompt", Answer)
    assert len(client.requests) == 2


def test_http_errors_are_not_swallowed_as_validation_failures():
    """A stopped Ollama server should surface as a connection problem, not
    be retried once and reported as a schema failure.
    """
    boom = RuntimeError("connection refused")
    client = StubClient([StubResponse("", error=boom)])
    with pytest.raises(RuntimeError, match="connection refused"):
        _provider(client).complete("prompt", Answer)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_llm_ollama.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'zeitgeist.llm.ollama'`

- [ ] **Step 3: Write `zeitgeist/llm/ollama.py`**

```python
"""Local backend via Ollama's JSON-schema constrained output."""

import json
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from zeitgeist.llm.base import LLMError

M = TypeVar("M", bound=BaseModel)

TIMEOUT_SECONDS = 300.0


class OllamaProvider:
    name = "ollama"

    def __init__(self, host: str, model: str, client: Any = None) -> None:
        if client is None:
            import httpx

            client = httpx.Client()
        self._client = client
        # Public: the factory wires these from Settings, and tests assert it.
        self.host = host.rstrip("/")
        self.model = model

    def complete(
        self, prompt: str, schema: type[M], *, system: str | None = None
    ) -> M:
        attempt_prompt = prompt
        last_error: str | None = None

        for _ in range(2):
            messages: list[dict[str, str]] = []
            if system is not None:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": attempt_prompt})

            response = self._client.post(
                f"{self.host}/api/chat",
                json={
                    "model": self.model,
                    "messages": messages,
                    "format": schema.model_json_schema(),
                    "stream": False,
                },
                timeout=TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            content = response.json()["message"]["content"]

            try:
                return schema.model_validate(json.loads(content))
            except (json.JSONDecodeError, ValidationError) as exc:
                last_error = str(exc)

            attempt_prompt = (
                f"{prompt}\n\nYour previous response failed validation:\n"
                f"{last_error}\n\nReturn a corrected response."
            )

        raise LLMError(
            f"Ollama did not return a valid {schema.__name__}: {last_error}"
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_llm_ollama.py -v`
Expected: PASS, 8 tests

- [ ] **Step 5: Write the failing test for the factory**

Create `tests/test_llm_factory.py`:

```python
import pytest

from zeitgeist.config import Settings
from zeitgeist.llm.anthropic import AnthropicProvider
from zeitgeist.llm.factory import build_provider
from zeitgeist.llm.ollama import OllamaProvider


def _settings(**overrides) -> Settings:
    defaults = dict(
        reddit_client_id="id",
        reddit_client_secret="secret",
        anthropic_api_key="key",
    )
    return Settings(**{**defaults, **overrides})


def test_builds_anthropic_by_default_wired_to_the_configured_model():
    provider = build_provider(_settings(llm_model="claude-configured"))
    assert isinstance(provider, AnthropicProvider)
    assert provider.model == "claude-configured"


def test_builds_ollama_wired_to_the_configured_host_and_model():
    """Catches the classic factory bug: constructing the right class with
    arguments crossed or defaulted, which only shows up as a live API call
    against the wrong model.
    """
    settings = _settings(
        llm_provider="ollama",
        llm_model="qwen2.5:14b",
        ollama_host="http://gpu-box:11434",
    )
    provider = build_provider(settings)
    assert isinstance(provider, OllamaProvider)
    assert provider.model == "qwen2.5:14b"
    assert provider.host == "http://gpu-box:11434"


def test_anthropic_without_api_key_fails_before_any_request():
    """Without this the failure surfaces as a 401 partway through a run,
    after the scrape has already been paid for.
    """
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        build_provider(_settings(anthropic_api_key=""))


def test_ollama_needs_no_anthropic_key():
    provider = build_provider(_settings(llm_provider="ollama", anthropic_api_key=""))
    assert isinstance(provider, OllamaProvider)
```

- [ ] **Step 6: Run test to verify it fails**

Run: `uv run pytest tests/test_llm_factory.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'zeitgeist.llm.factory'`

- [ ] **Step 7: Write `zeitgeist/llm/factory.py`**

```python
"""Chooses a provider from configuration."""

from zeitgeist.config import Settings
from zeitgeist.llm.anthropic import AnthropicProvider
from zeitgeist.llm.base import LLMProvider
from zeitgeist.llm.ollama import OllamaProvider


def build_provider(settings: Settings) -> LLMProvider:
    if settings.llm_provider == "ollama":
        return OllamaProvider(host=settings.ollama_host, model=settings.llm_model)
    if not settings.anthropic_api_key:
        raise ValueError("ANTHROPIC_API_KEY is required for the anthropic provider")
    return AnthropicProvider(
        api_key=settings.anthropic_api_key, model=settings.llm_model
    )
```

- [ ] **Step 8: Run all tests**

Run: `uv run pytest -v`
Expected: PASS, all tests

- [ ] **Step 9: Commit**

```bash
git add zeitgeist/llm tests/test_llm_ollama.py tests/test_llm_factory.py
git commit -m "feat: add Ollama provider and provider factory"
```

---

### Task 6: SQLite store

**Files:**
- Create: `zeitgeist/store.py`
- Test: `tests/test_store.py`

**Interfaces:**
- Consumes: `Topic` from Task 1
- Produces: `Store(path: Path)` with `init_schema()`, `start_run(run_id)`, `finish_run(run_id, status, post_count)`, `record_topics(run_id, topics)`, `previous_scores(exclude_run_id) -> dict[str, float]`, `close()`.

`previous_scores` returns, for every label ever recorded, the `trend_score` from the **most recent prior run** containing that label — the definition the spec pins down. Returning the whole map in one query avoids N queries during scoring.

- [ ] **Step 1: Write the failing test**

Create `tests/test_store.py`:

```python
from zeitgeist.models import Topic
from zeitgeist.store import Store


def _topic(label: str, score: float) -> Topic:
    return Topic(
        id=label.lower(),
        label=label,
        summary=f"About {label}.",
        post_ids=["p1"],
        trend_score=score,
    )


def _store(tmp_path) -> Store:
    store = Store(tmp_path / "test.db")
    store.init_schema()
    return store


def test_previous_scores_is_empty_on_first_run(tmp_path):
    store = _store(tmp_path)
    assert store.previous_scores(exclude_run_id="run1") == {}


def test_records_and_reads_back_topic_scores(tmp_path):
    store = _store(tmp_path)
    store.start_run("run1")
    store.record_topics("run1", [_topic("Cats", 0.8)])
    store.finish_run("run1", status="ok", post_count=10)

    assert store.previous_scores(exclude_run_id="run2") == {"Cats": 0.8}


def test_current_run_is_excluded_from_its_own_history(tmp_path):
    store = _store(tmp_path)
    store.start_run("run1")
    store.record_topics("run1", [_topic("Cats", 0.8)])

    assert store.previous_scores(exclude_run_id="run1") == {}


def test_most_recent_prior_run_wins(tmp_path):
    store = _store(tmp_path)
    for run_id, score in [("run1", 0.2), ("run2", 0.5), ("run3", 0.9)]:
        store.start_run(run_id)
        store.record_topics(run_id, [_topic("Cats", score)])
        store.finish_run(run_id, status="ok", post_count=10)

    assert store.previous_scores(exclude_run_id="run4") == {"Cats": 0.9}


def test_each_label_tracks_its_own_history(tmp_path):
    """Guards the correlated subquery: a naive MAX over all runs would give
    every label the newest run's score.
    """
    store = _store(tmp_path)
    store.start_run("run1")
    store.record_topics("run1", [_topic("Cats", 0.2), _topic("Dogs", 0.9)])
    store.finish_run("run1", status="ok", post_count=10)

    store.start_run("run2")
    store.record_topics("run2", [_topic("Cats", 0.7)])
    store.finish_run("run2", status="ok", post_count=10)

    assert store.previous_scores(exclude_run_id="run3") == {"Cats": 0.7, "Dogs": 0.9}


def test_finish_run_records_the_outcome(tmp_path):
    """Without this, deleting the body of finish_run breaks no test, and the
    CLI's closing summary silently reports nothing.
    """
    store = _store(tmp_path)
    store.start_run("run1")
    assert store.run_summary("run1") == {
        "status": None,
        "post_count": None,
        "finished_at": None,
    }

    store.finish_run("run1", status="ok", post_count=42)
    summary = store.run_summary("run1")
    assert summary["status"] == "ok"
    assert summary["post_count"] == 42
    assert summary["finished_at"] is not None


def test_run_summary_is_none_for_an_unknown_run(tmp_path):
    assert _store(tmp_path).run_summary("never-happened") is None


def test_init_schema_is_idempotent(tmp_path):
    """The CLI calls init_schema on every run, so a bare CREATE TABLE would
    fail the second time anyone used the tool.
    """
    store = Store(tmp_path / "test.db")
    store.init_schema()
    store.init_schema()
    assert store.previous_scores(exclude_run_id="x") == {}


def test_creates_parent_directory(tmp_path):
    """data/ is gitignored, so it does not exist on a fresh clone."""
    store = Store(tmp_path / "nested" / "dir" / "test.db")
    store.init_schema()
    assert (tmp_path / "nested" / "dir" / "test.db").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_store.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'zeitgeist.store'`

- [ ] **Step 3: Write `zeitgeist/store.py`**

```python
"""Cross-run history. The minimum needed to detect topics rising and falling."""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from zeitgeist.models import Topic

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id      TEXT PRIMARY KEY,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    status      TEXT,
    post_count  INTEGER
);

CREATE TABLE IF NOT EXISTS topics (
    run_id      TEXT NOT NULL,
    label       TEXT NOT NULL,
    trend_score REAL NOT NULL,
    created_at  TEXT NOT NULL,
    PRIMARY KEY (run_id, label)
);

CREATE INDEX IF NOT EXISTS idx_topics_label ON topics (label);
"""


class Store:
    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._path)

    def init_schema(self) -> None:
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def start_run(self, run_id: str) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO runs (run_id, started_at) VALUES (?, ?)",
            (run_id, _now()),
        )
        self._conn.commit()

    def finish_run(self, run_id: str, status: str, post_count: int) -> None:
        self._conn.execute(
            "UPDATE runs SET finished_at = ?, status = ?, post_count = ? "
            "WHERE run_id = ?",
            (_now(), status, post_count, run_id),
        )
        self._conn.commit()

    def record_topics(self, run_id: str, topics: list[Topic]) -> None:
        self._conn.executemany(
            "INSERT OR REPLACE INTO topics "
            "(run_id, label, trend_score, created_at) VALUES (?, ?, ?, ?)",
            [(run_id, t.label, t.trend_score, _now()) for t in topics],
        )
        self._conn.commit()

    def previous_scores(self, exclude_run_id: str) -> dict[str, float]:
        """Each label's score from the most recent prior run containing it."""
        rows = self._conn.execute(
            """
            SELECT t.label, t.trend_score
            FROM topics t
            JOIN runs r ON r.run_id = t.run_id
            WHERE t.run_id != ?
              AND r.started_at = (
                  SELECT MAX(r2.started_at)
                  FROM topics t2
                  JOIN runs r2 ON r2.run_id = t2.run_id
                  WHERE t2.label = t.label AND t2.run_id != ?
              )
            """,
            (exclude_run_id, exclude_run_id),
        ).fetchall()
        return {label: score for label, score in rows}

    def run_summary(self, run_id: str) -> dict | None:
        """Outcome of a run, or None if there is no such run. Used by the CLI
        to report what a run actually did.
        """
        row = self._conn.execute(
            "SELECT status, post_count, finished_at FROM runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if row is None:
            return None
        return {"status": row[0], "post_count": row[1], "finished_at": row[2]}

    def close(self) -> None:
        self._conn.close()


def _now() -> str:
    return datetime.now(UTC).isoformat()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_store.py -v`
Expected: PASS, 9 tests

- [ ] **Step 5: Commit**

```bash
git add zeitgeist/store.py tests/test_store.py
git commit -m "feat: add SQLite store for cross-run topic history"
```

---

### Task 7: Source protocol, Reddit source, and post fixture

**Files:**
- Create: `zeitgeist/sources/__init__.py`, `zeitgeist/sources/base.py`, `zeitgeist/sources/reddit.py`, `tests/fixtures/posts.json`, `tests/conftest.py`
- Test: `tests/test_sources_reddit.py`

**Interfaces:**
- Consumes: `Post` from Task 1, `Settings` from Task 2
- Produces:
  - `Source` protocol: `name: str`, `fetch(limit: int) -> list[Post]`
  - `SourceError(Exception)`
  - `RedditSource(client_id, client_secret, user_agent, subreddits, reddit=None)` implementing `Source`
  - `RedditSource.from_settings(settings) -> RedditSource`
  - pytest fixture `sample_posts` returning `list[Post]` loaded from `tests/fixtures/posts.json`

The `reddit` parameter exists solely for test injection. Reddit is queried in read-only mode: client ID and secret only, no user login.

- [ ] **Step 1: Create empty `zeitgeist/sources/__init__.py`**

Empty file.

- [ ] **Step 2: Write `zeitgeist/sources/base.py`**

```python
"""The extension point. A new platform is a new file implementing this."""

from typing import Protocol

from zeitgeist.models import Post


class SourceError(Exception):
    """Raised when a platform cannot be reached or returns nothing usable."""


class Source(Protocol):
    name: str

    def fetch(self, limit: int) -> list[Post]: ...
```

- [ ] **Step 3: Write the failing test**

Create `tests/test_sources_reddit.py`:

```python
from datetime import UTC, datetime

import pytest

from zeitgeist.sources.base import SourceError
from zeitgeist.sources.reddit import RedditSource


class StubSubmission:
    def __init__(self, sid, title, score=100, comments=10, sub="cats", selftext=""):
        self.id = sid
        self.title = title
        self.score = score
        self.num_comments = comments
        self.selftext = selftext
        self.permalink = f"/r/{sub}/comments/{sid}/"
        self.created_utc = datetime(2026, 8, 16, 9, 0, tzinfo=UTC).timestamp()
        self.subreddit = type("S", (), {"display_name": sub})()


class StubListing:
    def __init__(self, submissions):
        self._submissions = submissions

    def hot(self, limit=None):
        return iter(self._submissions[:limit])

    def rising(self, limit=None):
        return iter(self._submissions[:limit])


class StubReddit:
    def __init__(self, by_name):
        self._by_name = by_name
        self.requested = []

    def subreddit(self, name):
        self.requested.append(name)
        return self._by_name[name]


def _source(by_name, subreddits=()):
    return RedditSource(
        client_id="id",
        client_secret="secret",
        user_agent="ua",
        subreddits=list(subreddits),
        reddit=StubReddit(by_name),
    )


def test_maps_submissions_onto_posts():
    """Every downstream stage reads these fields. A crossed assignment —
    comment_count into score, or fetched_at into created_at — would skew
    every velocity calculation while breaking nothing visibly.
    """
    listing = StubListing(
        [StubSubmission("a1", "Cat opens door", score=1234, comments=56)]
    )
    post = _source({"all": listing}).fetch(limit=10)[0]

    assert post.platform == "reddit"
    assert post.source_id == "a1"
    assert post.title == "Cat opens door"
    assert post.channel == "cats"
    assert post.score == 1234
    assert post.comment_count == 56
    assert post.permalink == "https://www.reddit.com/r/cats/comments/a1/"
    assert post.created_at == datetime(2026, 8, 16, 9, 0, tzinfo=UTC)
    assert post.fetched_at > post.created_at


def test_deduplicates_across_hot_and_rising():
    listing = StubListing([StubSubmission("a1", "Same post")])
    posts = _source({"all": listing}).fetch(limit=10)
    assert len(posts) == 1


def test_includes_configured_subreddits():
    all_listing = StubListing([StubSubmission("a1", "From all")])
    cats_listing = StubListing([StubSubmission("c1", "From cats", sub="cats")])
    source = _source({"all": all_listing, "cats": cats_listing}, subreddits=["cats"])
    ids = {post.source_id for post in source.fetch(limit=10)}
    assert ids == {"a1", "c1"}


def test_respects_the_limit():
    submissions = [StubSubmission(f"id{n}", f"Title {n}") for n in range(50)]
    posts = _source({"all": StubListing(submissions)}).fetch(limit=5)
    assert len(posts) == 5


def test_truncates_long_body_to_the_leading_excerpt():
    """Keeps prompt size bounded. Asserting the content, not just the
    length, catches a slice taken from the wrong end.
    """
    body = "".join(str(n % 10) for n in range(900))
    listing = StubListing([StubSubmission("a1", "T", selftext=body)])
    posts = _source({"all": listing}).fetch(limit=10)
    assert posts[0].body_excerpt == body[:500]


@pytest.mark.parametrize("selftext", ["", "   ", "\n\t "])
def test_blank_body_becomes_none_rather_than_empty_string(selftext):
    """Link posts have no selftext. An empty string would put a pointless
    'Body:' line into every extraction prompt.
    """
    listing = StubListing([StubSubmission("a1", "T", selftext=selftext)])
    posts = _source({"all": listing}).fetch(limit=10)
    assert posts[0].body_excerpt is None


def test_no_posts_raises_source_error():
    with pytest.raises(SourceError, match="no posts"):
        _source({"all": StubListing([])}).fetch(limit=10)
```

- [ ] **Step 4: Run test to verify it fails**

Run: `uv run pytest tests/test_sources_reddit.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'zeitgeist.sources.reddit'`

- [ ] **Step 5: Write `zeitgeist/sources/reddit.py`**

```python
"""Reddit ingestion via PRAW in read-only mode.

Pulls `hot` (what is currently large) and `rising` (Reddit's own early
signal), so the scorer sees things that have not already peaked.
"""

import math
from datetime import UTC, datetime
from typing import Any

from zeitgeist.config import Settings
from zeitgeist.models import Post
from zeitgeist.sources.base import SourceError

BODY_EXCERPT_CHARS = 500


class RedditSource:
    name = "reddit"

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        user_agent: str,
        subreddits: list[str] | None = None,
        reddit: Any = None,
    ) -> None:
        if reddit is None:
            import praw

            reddit = praw.Reddit(
                client_id=client_id,
                client_secret=client_secret,
                user_agent=user_agent,
            )
            reddit.read_only = True
        self._reddit = reddit
        self._subreddits = list(subreddits or [])

    @classmethod
    def from_settings(cls, settings: Settings) -> "RedditSource":
        return cls(
            client_id=settings.reddit_client_id,
            client_secret=settings.reddit_client_secret,
            user_agent=settings.reddit_user_agent,
            subreddits=settings.subreddits,
        )

    def fetch(self, limit: int) -> list[Post]:
        names = ["all", *self._subreddits]
        # Divide the budget across listings, not across listing *pairs*: hot
        # and rising overlap heavily, so halving again would undersample.
        per_listing = max(1, math.ceil(limit / len(names)))
        fetched_at = datetime.now(UTC)

        seen: dict[str, Post] = {}
        for name in names:
            listing = self._reddit.subreddit(name)
            for stream in (listing.hot, listing.rising):
                for submission in stream(limit=per_listing):
                    if submission.id in seen:
                        continue
                    seen[submission.id] = _to_post(submission, fetched_at)
                    if len(seen) >= limit:
                        return list(seen.values())

        if not seen:
            raise SourceError("Reddit returned no posts")
        return list(seen.values())


def _to_post(submission: Any, fetched_at: datetime) -> Post:
    body = (submission.selftext or "").strip()
    return Post(
        platform="reddit",
        source_id=submission.id,
        title=submission.title,
        body_excerpt=body[:BODY_EXCERPT_CHARS] or None,
        permalink=f"https://www.reddit.com{submission.permalink}",
        score=submission.score,
        comment_count=submission.num_comments,
        created_at=datetime.fromtimestamp(submission.created_utc, tz=UTC),
        fetched_at=fetched_at,
        channel=submission.subreddit.display_name,
    )
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_sources_reddit.py -v`
Expected: PASS, 9 tests

- [ ] **Step 7: Create the shared post fixture**

Create `tests/fixtures/posts.json` with exactly the 10 entries below. They span 7 subreddits and 4 subject clusters (pets, space, baking, a tech product launch), which is what the later analysis tests need.

Adding more entries later is fine and harmless — keep the same shape, keep every timestamp within 24 hours of `fetched_at`, and the existing tests continue to hold. Nothing in the plan requires more than these 10.

```json
[
  {"platform": "reddit", "source_id": "p01", "title": "My rescue cat finally learned to open the bedroom door", "body_excerpt": null, "permalink": "https://www.reddit.com/r/cats/comments/p01/", "score": 48200, "comment_count": 1620, "created_at": "2026-08-16T09:00:00Z", "fetched_at": "2026-08-16T12:00:00Z", "channel": "cats"},
  {"platform": "reddit", "source_id": "p02", "title": "Shelter dog meets the family that adopted him", "body_excerpt": null, "permalink": "https://www.reddit.com/r/aww/comments/p02/", "score": 39100, "comment_count": 980, "created_at": "2026-08-16T10:30:00Z", "fetched_at": "2026-08-16T12:00:00Z", "channel": "aww"},
  {"platform": "reddit", "source_id": "p03", "title": "Kitten discovers its reflection for the first time", "body_excerpt": null, "permalink": "https://www.reddit.com/r/aww/comments/p03/", "score": 21400, "comment_count": 430, "created_at": "2026-08-16T11:00:00Z", "fetched_at": "2026-08-16T12:00:00Z", "channel": "aww"},
  {"platform": "reddit", "source_id": "p04", "title": "New telescope image shows a galaxy nobody expected", "body_excerpt": "The survey team says the structure is far older than models predicted.", "permalink": "https://www.reddit.com/r/space/comments/p04/", "score": 33000, "comment_count": 1240, "created_at": "2026-08-16T08:00:00Z", "fetched_at": "2026-08-16T12:00:00Z", "channel": "space"},
  {"platform": "reddit", "source_id": "p05", "title": "Astronomers confirm the unexpected galaxy finding", "body_excerpt": null, "permalink": "https://www.reddit.com/r/science/comments/p05/", "score": 12800, "comment_count": 610, "created_at": "2026-08-16T11:15:00Z", "fetched_at": "2026-08-16T12:00:00Z", "channel": "science"},
  {"platform": "reddit", "source_id": "p06", "title": "My sourdough finally worked after eleven failures", "body_excerpt": "Eleven. I counted.", "permalink": "https://www.reddit.com/r/baking/comments/p06/", "score": 9400, "comment_count": 300, "created_at": "2026-08-16T07:00:00Z", "fetched_at": "2026-08-16T12:00:00Z", "channel": "baking"},
  {"platform": "reddit", "source_id": "p07", "title": "Bread bakers of Reddit, what is your worst loaf?", "body_excerpt": null, "permalink": "https://www.reddit.com/r/baking/comments/p07/", "score": 3100, "comment_count": 890, "created_at": "2026-08-16T11:45:00Z", "fetched_at": "2026-08-16T12:00:00Z", "channel": "baking"},
  {"platform": "reddit", "source_id": "p08", "title": "This new phone launch has gone about as well as expected", "body_excerpt": null, "permalink": "https://www.reddit.com/r/technology/comments/p08/", "score": 27600, "comment_count": 4200, "created_at": "2026-08-16T06:00:00Z", "fetched_at": "2026-08-16T12:00:00Z", "channel": "technology"},
  {"platform": "reddit", "source_id": "p09", "title": "Company walks back the phone launch pricing after backlash", "body_excerpt": null, "permalink": "https://www.reddit.com/r/technology/comments/p09/", "score": 18900, "comment_count": 2100, "created_at": "2026-08-16T11:30:00Z", "fetched_at": "2026-08-16T12:00:00Z", "channel": "technology"},
  {"platform": "reddit", "source_id": "p10", "title": "Mildly interesting: my coffee formed a perfect spiral", "body_excerpt": null, "permalink": "https://www.reddit.com/r/mildlyinteresting/comments/p10/", "score": 800, "comment_count": 40, "created_at": "2026-08-16T05:00:00Z", "fetched_at": "2026-08-16T12:00:00Z", "channel": "mildlyinteresting"}
]
```

- [ ] **Step 8: Create `tests/conftest.py`**

```python
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from zeitgeist.models import Post

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def sample_posts() -> list[Post]:
    raw = json.loads((FIXTURES / "posts.json").read_text(encoding="utf-8"))
    return [Post.model_validate(entry) for entry in raw]


@pytest.fixture
def fixture_now() -> datetime:
    """The `fetched_at` shared by every fixture post."""
    return datetime(2026, 8, 16, 12, 0, tzinfo=UTC)
```

- [ ] **Step 9: Write a test that the fixture loads**

Append to `tests/test_sources_reddit.py`:

```python
def test_fixture_meets_the_preconditions_later_tests_assume(sample_posts):
    """Not a test of production code — a guard on the shared fixture. The
    analysis tests are only meaningful if the fixture spans several channels
    and subject areas, so trimming posts.json must fail loudly here rather
    than quietly weakening clustering tests three files away.
    """
    assert len(sample_posts) >= 10
    assert len({post.channel for post in sample_posts}) >= 5
    assert all(post.created_at.tzinfo is not None for post in sample_posts)
    assert len({post.source_id for post in sample_posts}) == len(sample_posts)
```

- [ ] **Step 10: Run tests to verify they pass**

Run: `uv run pytest tests/test_sources_reddit.py -v`
Expected: PASS, 10 tests

- [ ] **Step 11: Commit**

```bash
git add zeitgeist/sources tests/test_sources_reddit.py tests/conftest.py tests/fixtures
git commit -m "feat: add Source protocol, Reddit source, and post fixtures"
```

---

### Task 8: Map stage — extract topic tags

**Files:**
- Create: `zeitgeist/analysis/__init__.py`, `zeitgeist/analysis/extract.py`
- Test: `tests/test_analysis_extract.py`

**Interfaces:**
- Consumes: `Post` (Task 1), `LLMProvider`, `LLMError` (Task 3)
- Produces:
  - `PostTags(BaseModel)` with `post_id: str`, `tags: list[str]`
  - `TagExtraction(BaseModel)` with `assignments: list[PostTags]`
  - `extract_tags(posts, provider, *, batch_size=40) -> dict[str, list[str]]` mapping `post_id` to its tags
  - `BATCH_SIZE = 40`, `EXTRACT_SYSTEM: str`

A failed batch is logged and skipped, never fatal.

- [ ] **Step 1: Create empty `zeitgeist/analysis/__init__.py`**

Empty file.

- [ ] **Step 2: Write the failing test**

Create `tests/test_analysis_extract.py`:

```python
from zeitgeist.analysis.extract import PostTags, TagExtraction, extract_tags
from zeitgeist.llm.base import FakeLLMProvider, LLMError


def test_returns_tags_keyed_by_post_id(sample_posts):
    posts = sample_posts[:2]
    provider = FakeLLMProvider(
        [
            TagExtraction(
                assignments=[
                    PostTags(post_id=posts[0].source_id, tags=["cats", "pets"]),
                    PostTags(post_id=posts[1].source_id, tags=["dogs"]),
                ]
            )
        ]
    )
    tags = extract_tags(posts, provider, batch_size=40)
    assert tags[posts[0].source_id] == ["cats", "pets"]
    assert tags[posts[1].source_id] == ["dogs"]


def test_splits_into_batches(sample_posts):
    provider = FakeLLMProvider(
        [TagExtraction(assignments=[]), TagExtraction(assignments=[])]
    )
    extract_tags(sample_posts[:6], provider, batch_size=3)
    assert len(provider.calls) == 2


def test_prompt_carries_the_title_and_the_id_the_model_must_echo(sample_posts):
    """The model keys its answers by post id, so dropping the id from the
    prompt makes every assignment unmatchable and silently yields no tags.
    """
    post = sample_posts[0]
    provider = FakeLLMProvider([TagExtraction(assignments=[])])
    extract_tags([post], provider, batch_size=40)

    prompt = provider.calls[0].prompt
    assert post.title in prompt
    assert post.source_id in prompt
    assert post.channel in prompt


def test_caps_tags_per_post(sample_posts):
    """Bounds the vocabulary handed to the reduce stage; an uncapped model
    response would inflate the consolidation prompt without limit.
    """
    posts = sample_posts[:1]
    provider = FakeLLMProvider(
        [
            TagExtraction(
                assignments=[
                    PostTags(
                        post_id=posts[0].source_id,
                        tags=["one", "two", "three", "four", "five"],
                    )
                ]
            )
        ]
    )
    assert extract_tags(posts, provider, batch_size=40) == {
        posts[0].source_id: ["one", "two", "three"]
    }


def test_failed_batch_is_skipped_not_fatal(sample_posts):
    posts = sample_posts[:6]
    provider = FakeLLMProvider(
        [
            LLMError("batch one exploded"),
            TagExtraction(
                assignments=[PostTags(post_id=posts[3].source_id, tags=["kept"])]
            ),
        ]
    )
    tags = extract_tags(posts, provider, batch_size=3)
    assert tags == {posts[3].source_id: ["kept"]}


def test_unknown_post_ids_from_model_are_discarded(sample_posts):
    posts = sample_posts[:1]
    provider = FakeLLMProvider(
        [
            TagExtraction(
                assignments=[
                    PostTags(post_id=posts[0].source_id, tags=["real"]),
                    PostTags(post_id="hallucinated", tags=["fake"]),
                ]
            )
        ]
    )
    tags = extract_tags(posts, provider, batch_size=40)
    assert tags == {posts[0].source_id: ["real"]}


def test_tags_are_lowercased_and_deduplicated(sample_posts):
    posts = sample_posts[:1]
    provider = FakeLLMProvider(
        [
            TagExtraction(
                assignments=[
                    PostTags(post_id=posts[0].source_id, tags=["Cats", "cats", "PETS"])
                ]
            )
        ]
    )
    assert extract_tags(posts, provider, batch_size=40) == {
        posts[0].source_id: ["cats", "pets"]
    }


def test_empty_input_makes_no_calls():
    provider = FakeLLMProvider()
    assert extract_tags([], provider) == {}
    assert provider.calls == []
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_analysis_extract.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'zeitgeist.analysis.extract'`

- [ ] **Step 4: Write `zeitgeist/analysis/extract.py`**

```python
"""Map stage: each batch of posts becomes a set of topic tags.

Batches are independent, so a failure loses one batch rather than the run.
"""

import logging

from pydantic import BaseModel

from zeitgeist.llm.base import LLMProvider
from zeitgeist.models import Post

log = logging.getLogger(__name__)

BATCH_SIZE = 40
MAX_TAGS_PER_POST = 3

EXTRACT_SYSTEM = (
    "You label social media posts with the topics they are about. "
    "Topic tags are short noun phrases in lower case, two or three words at "
    "most, describing the subject rather than the reaction to it. Prefer "
    "specific tags over generic ones: 'shelter dog adoption' beats 'animals'. "
    f"Give each post at most {MAX_TAGS_PER_POST} tags."
)


class PostTags(BaseModel):
    """Topic tags for one post."""

    post_id: str
    tags: list[str]


class TagExtraction(BaseModel):
    """Tags for every post in one batch."""

    assignments: list[PostTags]


def extract_tags(
    posts: list[Post], provider: LLMProvider, *, batch_size: int = BATCH_SIZE
) -> dict[str, list[str]]:
    """Map every post to its topic tags. Failed batches are skipped."""
    known_ids = {post.source_id for post in posts}
    tags: dict[str, list[str]] = {}

    for start in range(0, len(posts), batch_size):
        batch = posts[start : start + batch_size]
        try:
            extraction = provider.complete(
                _build_prompt(batch), TagExtraction, system=EXTRACT_SYSTEM
            )
        except Exception:
            log.warning(
                "Tag extraction failed for batch starting at %d; skipping", start
            )
            continue

        for assignment in extraction.assignments:
            if assignment.post_id not in known_ids:
                continue
            tags[assignment.post_id] = _clean(assignment.tags)

    return tags


def _build_prompt(batch: list[Post]) -> str:
    lines = [
        f"- id={post.source_id} | r/{post.channel} | {post.title}" for post in batch
    ]
    listing = "\n".join(lines)
    return (
        "Label each of these posts with its topics.\n\n"
        f"{listing}\n\n"
        "Return one entry per post, using the exact id given."
    )


def _clean(tags: list[str]) -> list[str]:
    seen: list[str] = []
    for tag in tags:
        normalised = tag.strip().lower()
        if normalised and normalised not in seen:
            seen.append(normalised)
    return seen[:MAX_TAGS_PER_POST]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_analysis_extract.py -v`
Expected: PASS, 8 tests

- [ ] **Step 6: Commit**

```bash
git add zeitgeist/analysis tests/test_analysis_extract.py
git commit -m "feat: add map stage extracting topic tags from posts"
```

---

### Task 9: Reduce stage — consolidate tags into topics

**Files:**
- Create: `zeitgeist/analysis/consolidate.py`
- Test: `tests/test_analysis_consolidate.py`

**Interfaces:**
- Consumes: `Topic` (Task 1), `LLMProvider` (Task 3), tag map from `extract_tags` (Task 8)
- Produces:
  - `ConsolidatedTopic(BaseModel)` with `label: str`, `summary: str`, `tags: list[str]`
  - `Consolidation(BaseModel)` with `topics: list[ConsolidatedTopic]`
  - `consolidate(tags_by_post, provider) -> list[Topic]`
  - `slugify(label: str) -> str`
  - `CONSOLIDATE_SYSTEM: str`

Only the tag vocabulary is sent to the model, never the posts. That is what keeps this pass small enough for a local model with a limited context window.

- [ ] **Step 1: Write the failing test**

Create `tests/test_analysis_consolidate.py`:

```python
import pytest

from zeitgeist.analysis.consolidate import (
    ConsolidatedTopic,
    Consolidation,
    consolidate,
    slugify,
)
from zeitgeist.llm.base import FakeLLMProvider, LLMError


@pytest.mark.parametrize(
    "label,expected",
    [
        ("Shelter Dog Adoption", "shelter-dog-adoption"),
        ("  Spaced   Out  ", "spaced-out"),
        ("Punctuation! Everywhere?", "punctuation-everywhere"),
        ("", "topic"),
    ],
)
def test_slugify(label, expected):
    assert slugify(label) == expected


def test_groups_posts_by_their_tags():
    tags_by_post = {"p1": ["cats"], "p2": ["kittens"], "p3": ["telescope"]}
    provider = FakeLLMProvider(
        [
            Consolidation(
                topics=[
                    ConsolidatedTopic(
                        label="Cats", summary="Cat things.", tags=["cats", "kittens"]
                    ),
                    ConsolidatedTopic(
                        label="Space", summary="Space things.", tags=["telescope"]
                    ),
                ]
            )
        ]
    )
    topics = consolidate(tags_by_post, provider)

    assert [t.label for t in topics] == ["Cats", "Space"]
    assert sorted(topics[0].post_ids) == ["p1", "p2"]
    assert topics[1].post_ids == ["p3"]


def test_assigns_slug_ids():
    provider = FakeLLMProvider(
        [
            Consolidation(
                topics=[
                    ConsolidatedTopic(label="Shelter Dogs", summary="", tags=["dogs"])
                ]
            )
        ]
    )
    topics = consolidate({"p1": ["dogs"]}, provider)
    assert topics[0].id == "shelter-dogs"


def test_duplicate_slugs_get_numeric_suffixes():
    provider = FakeLLMProvider(
        [
            Consolidation(
                topics=[
                    ConsolidatedTopic(label="Cats", summary="", tags=["a"]),
                    ConsolidatedTopic(label="cats", summary="", tags=["b"]),
                ]
            )
        ]
    )
    topics = consolidate({"p1": ["a"], "p2": ["b"]}, provider)
    assert [t.id for t in topics] == ["cats", "cats-2"]


def test_topics_with_no_matching_posts_are_dropped():
    provider = FakeLLMProvider(
        [
            Consolidation(
                topics=[
                    ConsolidatedTopic(label="Real", summary="", tags=["cats"]),
                    ConsolidatedTopic(label="Phantom", summary="", tags=["nothing"]),
                ]
            )
        ]
    )
    topics = consolidate({"p1": ["cats"]}, provider)
    assert [t.label for t in topics] == ["Real"]


def test_prompt_carries_the_vocabulary_and_not_the_posts():
    """Sending only the tag vocabulary is what keeps this pass inside a small
    local model's context. Leaking post ids back in would defeat that, so the
    ids here are distinctive enough that a substring match cannot pass by luck.
    """
    provider = FakeLLMProvider([Consolidation(topics=[])])
    consolidate(
        {"zzqq-alpha": ["cats"], "zzqq-beta": ["telescope"]}, provider
    )
    prompt = provider.calls[0].prompt
    assert "cats" in prompt
    assert "telescope" in prompt
    assert "zzqq" not in prompt


def test_matches_returned_tags_case_insensitively():
    """Models routinely title-case their echo of an input tag. Matching
    exactly would drop every post from the topic and the topic with it.
    """
    provider = FakeLLMProvider(
        [
            Consolidation(
                topics=[
                    ConsolidatedTopic(label="Cats", summary="", tags=["Cats", " CATS "])
                ]
            )
        ]
    )
    topics = consolidate({"p1": ["cats"]}, provider)
    assert topics[0].post_ids == ["p1"]


def test_failure_returns_empty_list():
    provider = FakeLLMProvider([LLMError("reduce failed")])
    assert consolidate({"p1": ["cats"]}, provider) == []


def test_empty_input_makes_no_calls():
    provider = FakeLLMProvider()
    assert consolidate({}, provider) == []
    assert provider.calls == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_analysis_consolidate.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'zeitgeist.analysis.consolidate'`

- [ ] **Step 3: Write `zeitgeist/analysis/consolidate.py`**

```python
"""Reduce stage: merge the tag vocabulary into canonical topics.

Only the vocabulary goes to the model, never the posts themselves. That is
what keeps this pass inside a small local model's context window.
"""

import logging
import re
from collections import Counter

from pydantic import BaseModel

from zeitgeist.llm.base import LLMProvider
from zeitgeist.models import Topic

log = logging.getLogger(__name__)

CONSOLIDATE_SYSTEM = (
    "You merge a messy vocabulary of topic tags into a clean set of canonical "
    "topics. Fold synonyms, near-duplicates, plurals, and differing "
    "specificity into a single topic. Every canonical topic must list the "
    "exact input tags that folded into it, copied verbatim. Do not invent "
    "tags that were not given to you. Aim for topics that are specific enough "
    "to be interesting but broad enough to gather several tags."
)


class ConsolidatedTopic(BaseModel):
    """One canonical topic and the input tags it absorbed."""

    label: str
    summary: str
    tags: list[str]


class Consolidation(BaseModel):
    """The full canonical topic set."""

    topics: list[ConsolidatedTopic]


def consolidate(
    tags_by_post: dict[str, list[str]], provider: LLMProvider
) -> list[Topic]:
    """Turn a post-to-tags map into canonical topics carrying post ids."""
    if not tags_by_post:
        return []

    vocabulary = Counter(tag for tags in tags_by_post.values() for tag in tags)

    try:
        consolidation = provider.complete(
            _build_prompt(vocabulary), Consolidation, system=CONSOLIDATE_SYSTEM
        )
    except Exception:
        log.warning("Tag consolidation failed; no topics produced")
        return []

    topics: list[Topic] = []
    used_ids: set[str] = set()

    for entry in consolidation.topics:
        wanted = {tag.strip().lower() for tag in entry.tags}
        post_ids = sorted(
            post_id
            for post_id, tags in tags_by_post.items()
            if wanted & set(tags)
        )
        if not post_ids:
            log.debug("Dropping topic %r: no posts matched its tags", entry.label)
            continue

        topics.append(
            Topic(
                id=_unique_slug(entry.label, used_ids),
                label=entry.label,
                summary=entry.summary,
                post_ids=post_ids,
            )
        )

    return topics


def _build_prompt(vocabulary: Counter) -> str:
    lines = [
        f"- {tag} ({count} posts)" for tag, count in vocabulary.most_common()
    ]
    listing = "\n".join(lines)
    return (
        "Merge this tag vocabulary into canonical topics.\n\n"
        f"{listing}\n\n"
        "Return each canonical topic with a short label, a one or two "
        "sentence summary, and the exact input tags it absorbed."
    )


def slugify(label: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", label.strip().lower()).strip("-")
    return slug or "topic"


def _unique_slug(label: str, used: set[str]) -> str:
    base = slugify(label)
    candidate = base
    suffix = 2
    while candidate in used:
        candidate = f"{base}-{suffix}"
        suffix += 1
    used.add(candidate)
    return candidate
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_analysis_consolidate.py -v`
Expected: PASS, 12 tests

- [ ] **Step 5: Commit**

```bash
git add zeitgeist/analysis/consolidate.py tests/test_analysis_consolidate.py
git commit -m "feat: add reduce stage consolidating tags into topics"
```

---

### Task 10: Pure trend scoring

**Files:**
- Create: `zeitgeist/analysis/score.py`
- Test: `tests/test_analysis_score.py`

**Interfaces:**
- Consumes: `Post`, `Topic` (Task 1)
- Produces:
  - `ScoreWeights(BaseModel)` with `upvote_velocity=0.4`, `comment_velocity=0.3`, `channel_spread=0.3`, `rank_delta=0.25`
  - `score_topics(topics, posts, now, previous_scores, weights=None) -> list[Topic]`

**Scoring definition** — this is deliberately outside the LLM, because a numeric judgment a model makes is neither reproducible nor testable.

1. For each topic compute three raw intra-run components from its posts:
   - `upvote_velocity` = mean of `score / max(hours_since_post, 0.5)`
   - `comment_velocity` = mean of `comment_count / max(hours_since_post, 0.5)`
   - `channel_spread` = count of distinct `channel` values
2. Min-max normalise each across all topics in the run. **Where every topic shares a value, all normalised values are 0.0** — never undefined.
3. `base = (0.4·uv + 0.3·cv + 0.3·cs) / 1.0` using the first three weights renormalised to sum to 1.
4. `delta_raw = base − previous_scores[label]`, or `0.0` when the label has no history. Min-max normalise `delta_raw` across topics under the same zero-range rule.
5. `trend_score = (1 − w_delta)·base + w_delta·delta_norm`

The floor of 0.5 hours prevents a minutes-old post producing an unbounded velocity. Every component is stored in `score_components` so a surprising result traces to the term that caused it.

- [ ] **Step 1: Write the failing test**

Create `tests/test_analysis_score.py`:

```python
from datetime import UTC, datetime, timedelta

from zeitgeist.analysis.score import ScoreWeights, score_topics
from zeitgeist.models import Post, Topic

NOW = datetime(2026, 8, 16, 12, 0, tzinfo=UTC)


def _post(pid: str, score: int, comments: int, channel: str, hours: float) -> Post:
    return Post(
        platform="reddit",
        source_id=pid,
        title=f"Post {pid}",
        permalink=f"https://reddit.com/{pid}",
        score=score,
        comment_count=comments,
        created_at=NOW - timedelta(hours=hours),
        fetched_at=NOW,
        channel=channel,
    )


def _topic(tid: str, post_ids: list[str]) -> Topic:
    return Topic(id=tid, label=tid.title(), summary="", post_ids=post_ids)


def test_faster_topic_scores_higher():
    posts = [
        _post("a", 1000, 100, "cats", hours=1),
        _post("b", 1000, 100, "dogs", hours=20),
    ]
    topics = [_topic("fast", ["a"]), _topic("slow", ["b"])]
    scored = {t.id: t for t in score_topics(topics, posts, NOW, {})}
    assert scored["fast"].trend_score > scored["slow"].trend_score


def test_components_are_recorded():
    posts = [_post("a", 100, 10, "cats", hours=2)]
    scored = score_topics([_topic("t", ["a"])], posts, NOW, {})
    assert set(scored[0].score_components) == {
        "upvote_velocity",
        "comment_velocity",
        "channel_spread",
        "rank_delta",
        "base",
    }


def test_identical_topics_normalise_to_zero_not_nan():
    posts = [
        _post("a", 100, 10, "cats", hours=2),
        _post("b", 100, 10, "cats", hours=2),
    ]
    scored = score_topics([_topic("x", ["a"]), _topic("y", ["b"])], posts, NOW, {})
    for topic in scored:
        assert topic.score_components["upvote_velocity"] == 0.0
        assert topic.trend_score == 0.0


def test_no_history_gives_zero_rank_delta():
    posts = [_post("a", 100, 10, "cats", hours=2)]
    scored = score_topics([_topic("t", ["a"])], posts, NOW, previous_scores={})
    assert scored[0].score_components["rank_delta"] == 0.0


def test_rising_topic_beats_falling_topic_with_equal_base():
    posts = [
        _post("a", 100, 10, "cats", hours=2),
        _post("b", 100, 10, "dogs", hours=2),
    ]
    topics = [_topic("riser", ["a"]), _topic("faller", ["b"])]
    previous = {"Riser": 0.0, "Faller": 1.0}
    scored = {t.id: t for t in score_topics(topics, posts, NOW, previous)}
    assert scored["riser"].trend_score > scored["faller"].trend_score


def test_wider_channel_spread_scores_higher():
    posts = [
        _post("a", 100, 10, "cats", hours=2),
        _post("b", 100, 10, "dogs", hours=2),
        _post("c", 100, 10, "aww", hours=2),
    ]
    topics = [_topic("wide", ["a", "b"]), _topic("narrow", ["c"])]
    scored = {t.id: t for t in score_topics(topics, posts, NOW, {})}
    assert scored["wide"].trend_score > scored["narrow"].trend_score


def test_age_floor_stops_a_minutes_old_post_dominating():
    """Without MIN_AGE_HOURS a post seconds old divides by nearly zero and
    swamps the run purely for being new. Three topics, so normalisation has
    a real range and the assertion cannot pass on all-zeros.
    """
    posts = [
        _post("a", 100, 10, "cats", hours=0.01),
        _post("b", 100, 10, "cats", hours=0.5),
        _post("c", 1000, 100, "cats", hours=1),
    ]
    topics = [
        _topic("brandnew", ["a"]),
        _topic("halfhour", ["b"]),
        _topic("big", ["c"]),
    ]
    scored = {t.id: t for t in score_topics(topics, posts, NOW, {})}

    assert scored["brandnew"].trend_score == scored["halfhour"].trend_score
    assert scored["big"].trend_score > scored["brandnew"].trend_score


def test_a_topic_averages_its_posts_rather_than_summing_them():
    """Summing would let a topic climb on post count alone: five ordinary
    posts would outrank one genuinely fast-moving post.
    """
    posts = [_post(f"m{n}", 100, 10, "cats", hours=1) for n in range(5)]
    posts.append(_post("f", 400, 40, "dogs", hours=1))
    topics = [
        _topic("many", [f"m{n}" for n in range(5)]),
        _topic("fast", ["f"]),
    ]
    scored = {t.id: t for t in score_topics(topics, posts, NOW, {})}
    assert scored["fast"].trend_score > scored["many"].trend_score


def test_topics_with_no_known_posts_are_dropped():
    posts = [_post("a", 100, 10, "cats", hours=2)]
    topics = [_topic("real", ["a"]), _topic("ghost", ["missing"])]
    assert [t.id for t in score_topics(topics, posts, NOW, {})] == ["real"]


def test_empty_input_returns_empty():
    assert score_topics([], [], NOW, {}) == []


def test_weights_are_configurable():
    posts = [
        _post("a", 10000, 1, "cats", hours=1),
        _post("b", 1, 10000, "dogs", hours=1),
    ]
    topics = [_topic("upvoted", ["a"]), _topic("discussed", ["b"])]
    weights = ScoreWeights(
        upvote_velocity=0.0, comment_velocity=1.0, channel_spread=0.0, rank_delta=0.0
    )
    scored = {t.id: t for t in score_topics(topics, posts, NOW, {}, weights)}
    assert scored["discussed"].trend_score > scored["upvoted"].trend_score
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_analysis_score.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'zeitgeist.analysis.score'`

- [ ] **Step 3: Write `zeitgeist/analysis/score.py`**

```python
"""Trend scoring. Pure Python on purpose: reproducible and unit-testable,
which an LLM's numeric judgment is not.
"""

from datetime import datetime

from pydantic import BaseModel

from zeitgeist.models import Post, Topic

MIN_AGE_HOURS = 0.5


class ScoreWeights(BaseModel):
    upvote_velocity: float = 0.4
    comment_velocity: float = 0.3
    channel_spread: float = 0.3
    rank_delta: float = 0.25


def score_topics(
    topics: list[Topic],
    posts: list[Post],
    now: datetime,
    previous_scores: dict[str, float],
    weights: ScoreWeights | None = None,
) -> list[Topic]:
    """Attach a trend score and its component breakdown to each topic."""
    weights = weights or ScoreWeights()
    by_id = {post.source_id: post for post in posts}

    live: list[tuple[Topic, list[Post]]] = []
    for topic in topics:
        matched = [by_id[pid] for pid in topic.post_ids if pid in by_id]
        if matched:
            live.append((topic, matched))

    if not live:
        return []

    raw_uv = [_mean_velocity(p, now, "score") for _, p in live]
    raw_cv = [_mean_velocity(p, now, "comment_count") for _, p in live]
    raw_cs = [float(len({post.channel for post in p})) for _, p in live]

    uv, cv, cs = _normalise(raw_uv), _normalise(raw_cv), _normalise(raw_cs)

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
        for i in range(len(live))
    ]

    raw_delta = [
        bases[i] - previous_scores.get(topic.label, bases[i])
        for i, (topic, _) in enumerate(live)
    ]
    delta = _normalise(raw_delta)

    scored: list[Topic] = []
    for i, (topic, _) in enumerate(live):
        trend = (1.0 - weights.rank_delta) * bases[i] + weights.rank_delta * delta[i]
        scored.append(
            topic.model_copy(
                update={
                    "trend_score": trend,
                    "score_components": {
                        "upvote_velocity": uv[i],
                        "comment_velocity": cv[i],
                        "channel_spread": cs[i],
                        "rank_delta": delta[i],
                        "base": bases[i],
                    },
                }
            )
        )
    return scored


def _mean_velocity(posts: list[Post], now: datetime, attribute: str) -> float:
    values = []
    for post in posts:
        hours = (now - post.created_at).total_seconds() / 3600.0
        values.append(getattr(post, attribute) / max(hours, MIN_AGE_HOURS))
    return sum(values) / len(values)


def _normalise(values: list[float]) -> list[float]:
    """Min-max normalise. A zero range yields zeros, never a division error."""
    low, high = min(values), max(values)
    if high - low == 0:
        return [0.0] * len(values)
    return [(value - low) / (high - low) for value in values]
```

Note the `previous_scores.get(topic.label, bases[i])` default: a topic with no
history gets `delta_raw = 0.0`, which is exactly the "zero when no history"
rule, without special-casing.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_analysis_score.py -v`
Expected: PASS, 11 tests

- [ ] **Step 5: Commit**

```bash
git add zeitgeist/analysis/score.py tests/test_analysis_score.py
git commit -m "feat: add pure trend scoring with component breakdown"
```

---

### Task 11: Sentiment judgement and weighted selection

**Files:**
- Create: `zeitgeist/analysis/sentiment.py`
- Test: `tests/test_analysis_sentiment.py`

**Interfaces:**
- Consumes: `Sentiment`, `Topic`, `ScoredTopic` (Task 1), `Settings` (Task 2), `LLMProvider` (Task 3)
- Produces:
  - `SentimentJudgement(BaseModel)` with `primary_sentiment: Sentiment`, `secondary_sentiments: list[Sentiment]`, `valence: float`, `meme_potential: float`
  - `judge_topics(topics, provider) -> list[ScoredTopic]`
  - `select(scored, weights, top_n) -> list[ScoredTopic]`
  - `SENTIMENT_SYSTEM: str`

`select` computes `trend_score × sentiment_weight × meme_potential`, sorts descending, assigns `final_rank` from 1, and returns the top N. **No sentiment is excluded** — a strong enough trend carries a negative topic through, which is intended.

- [ ] **Step 1: Write the failing test**

Create `tests/test_analysis_sentiment.py`:

```python
from zeitgeist.analysis.sentiment import SentimentJudgement, judge_topics, select
from zeitgeist.config import DEFAULT_SENTIMENT_WEIGHTS
from zeitgeist.llm.base import FakeLLMProvider, LLMError
from zeitgeist.models import ScoredTopic, Sentiment, Topic


def _topic(tid: str, score: float = 0.5) -> Topic:
    return Topic(
        id=tid, label=tid.title(), summary=f"About {tid}.",
        post_ids=["p1"], trend_score=score,
    )


def _judgement(sentiment: Sentiment, meme: float = 0.8) -> SentimentJudgement:
    return SentimentJudgement(
        primary_sentiment=sentiment,
        secondary_sentiments=[],
        valence=0.5,
        meme_potential=meme,
    )


def _scored(tid: str, sentiment: Sentiment, trend: float, meme: float = 1.0):
    return ScoredTopic(
        id=tid, label=tid.title(), summary="", post_ids=["p1"],
        trend_score=trend, primary_sentiment=sentiment,
        valence=0.0, meme_potential=meme,
    )


def test_carries_every_judgement_field_onto_the_scored_topic():
    """valence and meme_potential are distinct values here on purpose: if
    the mapping crosses them, selection silently ranks by the wrong number
    and nothing else in the suite notices.
    """
    judgement = SentimentJudgement(
        primary_sentiment=Sentiment.CUTE,
        secondary_sentiments=[Sentiment.FUNNY],
        valence=0.25,
        meme_potential=0.75,
    )
    scored = judge_topics([_topic("cats", 0.5)], FakeLLMProvider([judgement]))[0]

    assert scored.primary_sentiment == Sentiment.CUTE
    assert scored.secondary_sentiments == [Sentiment.FUNNY]
    assert scored.valence == 0.25
    assert scored.meme_potential == 0.75


def test_preserves_the_topic_it_was_given():
    """The trend score computed in the previous stage must survive into
    selection; recomputing or defaulting it would discard the scoring work.
    """
    provider = FakeLLMProvider([_judgement(Sentiment.CUTE)])
    scored = judge_topics([_topic("cats", 0.75)], provider)[0]
    assert scored.id == "cats"
    assert scored.trend_score == 0.75
    assert scored.summary == "About cats."


def test_calls_provider_once_per_topic():
    provider = FakeLLMProvider([_judgement(Sentiment.FUNNY)] * 3)
    judge_topics([_topic("a"), _topic("b"), _topic("c")], provider)
    assert len(provider.calls) == 3


def test_prompt_contains_label_and_summary():
    provider = FakeLLMProvider([_judgement(Sentiment.AWE)])
    judge_topics([_topic("cats")], provider)
    assert "Cats" in provider.calls[0].prompt
    assert "About cats." in provider.calls[0].prompt


def test_failed_topic_is_dropped_and_run_continues():
    provider = FakeLLMProvider([LLMError("nope"), _judgement(Sentiment.CUTE)])
    scored = judge_topics([_topic("dropped"), _topic("kept")], provider)
    assert [t.id for t in scored] == ["kept"]


def test_select_prefers_positive_sentiment_at_equal_trend():
    topics = [
        _scored("grim", Sentiment.OUTRAGE, trend=0.8),
        _scored("sweet", Sentiment.HEARTWARMING, trend=0.8),
    ]
    picked = select(topics, DEFAULT_SENTIMENT_WEIGHTS, top_n=2)
    assert [t.id for t in picked] == ["sweet", "grim"]


def test_strongly_trending_negative_topic_still_wins():
    topics = [
        _scored("grim", Sentiment.OUTRAGE, trend=1.0),
        _scored("sweet", Sentiment.HEARTWARMING, trend=0.4),
    ]
    picked = select(topics, DEFAULT_SENTIMENT_WEIGHTS, top_n=2)
    assert picked[0].id == "grim"


def test_no_sentiment_is_excluded_outright():
    topics = [_scored(s.value, s, trend=0.5) for s in Sentiment]
    picked = select(topics, DEFAULT_SENTIMENT_WEIGHTS, top_n=len(topics))
    assert len(picked) == len(topics)


def test_select_truncates_to_top_n_and_ranks_from_one():
    topics = [
        _scored("a", Sentiment.FUNNY, trend=0.9),
        _scored("b", Sentiment.FUNNY, trend=0.5),
        _scored("c", Sentiment.FUNNY, trend=0.1),
    ]
    picked = select(topics, DEFAULT_SENTIMENT_WEIGHTS, top_n=2)
    assert [t.id for t in picked] == ["a", "b"]
    assert [t.final_rank for t in picked] == [1, 2]


def test_meme_potential_affects_ordering():
    topics = [
        _scored("dull", Sentiment.FUNNY, trend=0.9, meme=0.1),
        _scored("punchy", Sentiment.FUNNY, trend=0.6, meme=1.0),
    ]
    picked = select(topics, DEFAULT_SENTIMENT_WEIGHTS, top_n=2)
    assert picked[0].id == "punchy"


def test_select_on_empty_input_returns_empty():
    assert select([], DEFAULT_SENTIMENT_WEIGHTS, top_n=5) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_analysis_sentiment.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'zeitgeist.analysis.sentiment'`

- [ ] **Step 3: Write `zeitgeist/analysis/sentiment.py`**

```python
"""Sentiment judgement and final selection.

Weights favour positive output without excluding anything: a sufficiently
strong trend carries a negatively-flavoured topic into the selection, which
is intended. The zeitgeist is not always cheerful, and a tool that only ever
sees the cheerful half is not measuring it.
"""

import logging

from pydantic import BaseModel, Field

from zeitgeist.llm.base import LLMProvider
from zeitgeist.models import ScoredTopic, Sentiment, Topic

log = logging.getLogger(__name__)

SENTIMENT_SYSTEM = (
    "You judge the emotional flavour of a trending topic. Choose the single "
    "primary sentiment that best describes how people feel about it, plus any "
    "secondary sentiments that also apply. Valence runs from -1 (thoroughly "
    "negative) to 1 (thoroughly positive). Meme potential runs from 0 to 1 and "
    "measures how readily the topic yields a joke that would land with people "
    "who have not read the source posts."
)


class SentimentJudgement(BaseModel):
    """The model's read on how a topic feels."""

    primary_sentiment: Sentiment
    secondary_sentiments: list[Sentiment] = Field(default_factory=list)
    valence: float = Field(ge=-1.0, le=1.0)
    meme_potential: float = Field(ge=0.0, le=1.0)


def judge_topics(topics: list[Topic], provider: LLMProvider) -> list[ScoredTopic]:
    """Judge each topic. A topic whose call fails is dropped, not fatal."""
    scored: list[ScoredTopic] = []

    for topic in topics:
        try:
            judgement = provider.complete(
                _build_prompt(topic), SentimentJudgement, system=SENTIMENT_SYSTEM
            )
        except Exception:
            log.warning("Sentiment judgement failed for %r; dropping", topic.label)
            continue

        scored.append(
            ScoredTopic(
                **topic.model_dump(),
                primary_sentiment=judgement.primary_sentiment,
                secondary_sentiments=judgement.secondary_sentiments,
                valence=judgement.valence,
                meme_potential=judgement.meme_potential,
            )
        )

    return scored


def select(
    scored: list[ScoredTopic],
    weights: dict[Sentiment, float],
    top_n: int,
) -> list[ScoredTopic]:
    """Rank by trend x sentiment weight x meme potential, keep the top N."""
    ranked = sorted(
        scored,
        key=lambda topic: (
            topic.trend_score
            * weights.get(topic.primary_sentiment, 1.0)
            * topic.meme_potential
        ),
        reverse=True,
    )
    return [
        topic.model_copy(update={"final_rank": position})
        for position, topic in enumerate(ranked[:top_n], start=1)
    ]


def _build_prompt(topic: Topic) -> str:
    return (
        f"Topic: {topic.label}\n"
        f"Summary: {topic.summary}\n"
        f"Appears in {len(topic.post_ids)} posts.\n\n"
        "Judge this topic's sentiment and meme potential."
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_analysis_sentiment.py -v`
Expected: PASS, 11 tests

- [ ] **Step 5: Commit**

```bash
git add zeitgeist/analysis/sentiment.py tests/test_analysis_sentiment.py
git commit -m "feat: add sentiment judgement and weighted selection"
```

---

### Task 12: Template manifests, loader, and validator

**Files:**
- Create: `zeitgeist/media/__init__.py`, `zeitgeist/media/templates.py`, `scripts/make_placeholder_templates.py`, `zeitgeist/media/templates/*.json`, `zeitgeist/media/templates/*.png`, `zeitgeist/media/fonts/DejaVuSans-Bold.ttf`
- Test: `tests/test_media_templates.py`, `tests/fixtures/templates/`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `Slot(BaseModel)` with `name: str`, `box: tuple[int, int, int, int]`, `max_chars: int`
  - `TemplateManifest(BaseModel)` with `id: str`, `image: str`, `shape: str`, `slots: list[Slot]`
  - `load_templates(directory: Path) -> dict[str, TemplateManifest]`
  - `validate_templates(directory: Path) -> list[str]` returning human-readable problems, empty when all is well
  - `TemplateError(Exception)`

`box` is `[left, top, right, bottom]` in pixels, measured against that
specific image file. Because 24 manifests are hand-measured, the validator is
the gate — at this count a mis-measured box will not be caught by eye, and the
symptom is text silently rendering off-canvas.

- [ ] **Step 1: Create empty `zeitgeist/media/__init__.py`**

Empty file.

- [ ] **Step 2: Write the failing test**

Create `tests/test_media_templates.py`:

```python
import json

import pytest
from PIL import Image

from zeitgeist.media.templates import (
    TemplateError,
    load_templates,
    validate_templates,
)


def _write_template(directory, tid, box=(10, 10, 90, 90), size=(100, 100), image=None):
    directory.mkdir(parents=True, exist_ok=True)
    image_name = image if image is not None else f"{tid}.png"
    if image is None:
        Image.new("RGB", size, "white").save(directory / image_name)
    manifest = {
        "id": tid,
        "image": image_name,
        "shape": "a shape",
        "slots": [{"name": "top", "box": list(box), "max_chars": 40}],
    }
    (directory / f"{tid}.json").write_text(json.dumps(manifest), encoding="utf-8")


def test_loads_manifests_keyed_by_id(tmp_path):
    _write_template(tmp_path, "drake")
    templates = load_templates(tmp_path)
    assert templates["drake"].shape == "a shape"
    assert templates["drake"].slots[0].name == "top"


def test_missing_directory_raises(tmp_path):
    with pytest.raises(TemplateError):
        load_templates(tmp_path / "absent")


def test_directory_with_no_manifests_raises(tmp_path):
    tmp_path.mkdir(exist_ok=True)
    with pytest.raises(TemplateError):
        load_templates(tmp_path)


def test_manifest_id_must_match_filename(tmp_path):
    _write_template(tmp_path, "drake")
    (tmp_path / "drake.json").write_text(
        json.dumps(
            {
                "id": "mismatch",
                "image": "drake.png",
                "shape": "s",
                "slots": [{"name": "t", "box": [0, 0, 10, 10], "max_chars": 10}],
            }
        ),
        encoding="utf-8",
    )
    assert any("filename" in problem for problem in validate_templates(tmp_path))


def test_validator_passes_a_good_directory(tmp_path):
    _write_template(tmp_path, "drake")
    assert validate_templates(tmp_path) == []


def test_validator_reports_missing_image(tmp_path):
    _write_template(tmp_path, "drake")
    (tmp_path / "drake.png").unlink()
    assert any("image" in problem for problem in validate_templates(tmp_path))


def test_validator_reports_box_outside_image_bounds(tmp_path):
    _write_template(tmp_path, "drake", box=(10, 10, 500, 500), size=(100, 100))
    assert any("bounds" in problem for problem in validate_templates(tmp_path))


def test_validator_reports_inverted_box(tmp_path):
    _write_template(tmp_path, "drake", box=(90, 90, 10, 10))
    assert any("inverted" in problem for problem in validate_templates(tmp_path))


def test_validator_reports_duplicate_slot_names(tmp_path):
    _write_template(tmp_path, "drake")
    manifest = json.loads((tmp_path / "drake.json").read_text(encoding="utf-8"))
    manifest["slots"].append(
        {"name": "top", "box": [0, 0, 10, 10], "max_chars": 10}
    )
    (tmp_path / "drake.json").write_text(json.dumps(manifest), encoding="utf-8")
    assert any("duplicate" in problem for problem in validate_templates(tmp_path))


def test_validator_reports_non_positive_max_chars(tmp_path):
    """A zero max_chars is a silent trap: the manifest loads, and the model
    is told it may write no characters at all.
    """
    _write_template(tmp_path, "drake")
    manifest = json.loads((tmp_path / "drake.json").read_text(encoding="utf-8"))
    manifest["slots"][0]["max_chars"] = 0
    (tmp_path / "drake.json").write_text(json.dumps(manifest), encoding="utf-8")
    assert any("max_chars" in problem for problem in validate_templates(tmp_path))


def test_validator_reports_unparseable_manifest(tmp_path):
    tmp_path.mkdir(exist_ok=True)
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")
    assert any("parse" in problem for problem in validate_templates(tmp_path))


def test_shipped_templates_are_all_valid():
    from zeitgeist.config import PACKAGE_ROOT

    assert validate_templates(PACKAGE_ROOT / "media" / "templates") == []


def test_shipped_templates_number_twenty_four():
    from zeitgeist.config import PACKAGE_ROOT

    assert len(load_templates(PACKAGE_ROOT / "media" / "templates")) == 24
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_media_templates.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'zeitgeist.media.templates'`

- [ ] **Step 4: Write `zeitgeist/media/templates.py`**

```python
"""Meme template manifests: loading and validation.

At twenty-four hand-measured manifests, a mis-measured box will not be caught
by eye. The validator is the gate.
"""

import json
from pathlib import Path

from PIL import Image
from pydantic import BaseModel, ValidationError


class TemplateError(Exception):
    """Raised when the template library cannot be loaded at all."""


class Slot(BaseModel):
    """One text box. `box` is [left, top, right, bottom] in pixels."""

    name: str
    box: tuple[int, int, int, int]
    max_chars: int


class TemplateManifest(BaseModel):
    """A meme template and the rhetorical shape it expresses."""

    id: str
    image: str
    shape: str
    slots: list[Slot]


def load_templates(directory: Path) -> dict[str, TemplateManifest]:
    directory = Path(directory)
    if not directory.is_dir():
        raise TemplateError(f"Template directory not found: {directory}")

    templates: dict[str, TemplateManifest] = {}
    for path in sorted(directory.glob("*.json")):
        try:
            manifest = TemplateManifest.model_validate_json(
                path.read_text(encoding="utf-8")
            )
        except (ValidationError, json.JSONDecodeError) as exc:
            raise TemplateError(f"Could not parse {path.name}: {exc}") from exc
        templates[manifest.id] = manifest

    if not templates:
        raise TemplateError(f"No template manifests found in {directory}")
    return templates


def validate_templates(directory: Path) -> list[str]:
    """Return every problem found, newest-engineer-readable. Empty means good."""
    directory = Path(directory)
    if not directory.is_dir():
        return [f"Template directory not found: {directory}"]

    problems: list[str] = []
    for path in sorted(directory.glob("*.json")):
        try:
            manifest = TemplateManifest.model_validate_json(
                path.read_text(encoding="utf-8")
            )
        except (ValidationError, json.JSONDecodeError) as exc:
            problems.append(f"{path.name}: could not parse manifest ({exc})")
            continue

        if manifest.id != path.stem:
            problems.append(
                f"{path.name}: id {manifest.id!r} does not match filename"
            )

        image_path = directory / manifest.image
        if not image_path.is_file():
            problems.append(f"{path.name}: image {manifest.image!r} not found")
            continue

        with Image.open(image_path) as image:
            width, height = image.size

        seen: set[str] = set()
        for slot in manifest.slots:
            if slot.name in seen:
                problems.append(f"{path.name}: duplicate slot name {slot.name!r}")
            seen.add(slot.name)

            left, top, right, bottom = slot.box
            if right <= left or bottom <= top:
                problems.append(f"{path.name}: slot {slot.name!r} box is inverted")
            elif not (
                0 <= left < right <= width and 0 <= top < bottom <= height
            ):
                problems.append(
                    f"{path.name}: slot {slot.name!r} box falls outside image "
                    f"bounds ({width}x{height})"
                )

            if slot.max_chars <= 0:
                problems.append(
                    f"{path.name}: slot {slot.name!r} has non-positive max_chars"
                )

    return problems
```

- [ ] **Step 5: Vendor the font**

Download DejaVu Sans Bold and save it to `zeitgeist/media/fonts/DejaVuSans-Bold.ttf`.

Source: https://github.com/dejavu-fonts/dejavu-fonts/releases — take
`DejaVuSans-Bold.ttf` from the `ttf/` directory of the release archive.

It is vendored rather than resolved from system fonts so that golden-image
tests are reproducible across machines. Its licence (Bitstream Vera / Arev,
permissive with attribution) allows redistribution; record that in
`zeitgeist/media/fonts/LICENCE.txt` alongside the file, copying the licence
text from the release archive.

If you prefer the authentic meme look, set `FONT_PATH` to
`C:\Windows\Fonts\impact.ttf` in `.env` — but leave the vendored default in
place, because the golden tests depend on it.

- [ ] **Step 6: Build the 24-template library**

**Placeholder images for now.** The real meme images will be sourced by hand
later. For this task, generate a placeholder PNG per template so the pipeline
runs end to end and the geometry is real.

Create `scripts/make_placeholder_templates.py`:

```python
"""Generates placeholder template images and manifests.

Placeholders are laid out on a fixed 800x800 canvas with evenly stacked
slots, so box geometry is real and the renderer can be exercised properly.
Replace the PNGs with genuine meme images later and re-measure the boxes;
`zeitgeist validate-templates` will catch any that no longer fit.
"""

import json
from pathlib import Path

from PIL import Image, ImageDraw

TEMPLATES: list[tuple[str, str, list[str]]] = [
    ("drake", "rejecting option A in favour of preferred option B",
     ["rejected", "preferred"]),
    # ... one entry per row of the table below ...
]

WIDTH = HEIGHT = 800
MARGIN = 20
OUT = Path("zeitgeist/media/templates")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for template_id, shape, slot_names in TEMPLATES:
        image = Image.new("RGB", (WIDTH, HEIGHT), "#d9d9d9")
        draw = ImageDraw.Draw(image)

        band = (HEIGHT - MARGIN * (len(slot_names) + 1)) // len(slot_names)
        slots = []
        for index, name in enumerate(slot_names):
            top = MARGIN + index * (band + MARGIN)
            box = (MARGIN, top, WIDTH - MARGIN, top + band)
            draw.rectangle(box, outline="#8a8a8a", width=3)
            slots.append(
                {
                    "name": name,
                    "box": list(box),
                    "max_chars": max(20, (WIDTH - 2 * MARGIN) // 7),
                }
            )

        image.save(OUT / f"{template_id}.png")
        (OUT / f"{template_id}.json").write_text(
            json.dumps(
                {
                    "id": template_id,
                    "image": f"{template_id}.png",
                    "shape": shape,
                    "slots": slots,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    print(f"wrote {len(TEMPLATES)} placeholder templates to {OUT}")


if __name__ == "__main__":
    main()
```

Fill `TEMPLATES` with all 24 rows from the table below, copying each `id`,
`shape`, and slot-name list verbatim. Then run:

```bash
uv run python scripts/make_placeholder_templates.py
```

The `shape` strings matter more than the images do — they are what the model
actually selects on, and they must be right now even though the pictures are
placeholders.

The library spans eight rhetorical shapes rather than twenty-four different
pictures, because selection quality depends on the model finding a shape that
fits the topic. Twenty-four variations on comparison would be worth less than
this spread.

When the real images replace the placeholders, keep the ids and slot names
identical — briefs, tests, and any committed run output all key on them.

| id | shape | slots |
|---|---|---|
| `drake` | rejecting option A in favour of preferred option B | `rejected`, `preferred` |
| `left_exit_12` | swerving away from the expected choice toward another | `straight_ahead`, `exit`, `driver` |
| `buff_doge_vs_cheems` | a confident past self against a feeble present one | `strong`, `weak` |
| `expanding_brain` | four takes, each more absurdly enlightened than the last | `level1`, `level2`, `level3`, `level4` |
| `increasingly_buff_spongebob` | the same thing escalating to an extreme | `stage1`, `stage2`, `stage3` |
| `panik_kalm_panik` | alarm, brief relief, then renewed alarm | `panik1`, `kalm`, `panik2` |
| `distracted_boyfriend` | being tempted away from A by a newer B | `boyfriend`, `girlfriend`, `other_woman` |
| `woman_yelling_at_cat` | a furious accusation meeting an unbothered response | `accuser`, `responder` |
| `spiderman_pointing` | two identical things accusing each other | `left`, `right` |
| `gru_plan` | a plan whose final step reveals it backfiring | `step1`, `step2`, `step3`, `step4` |
| `surprised_pikachu` | shock at an entirely predictable consequence | `setup`, `consequence` |
| `this_is_fine` | insisting all is well amid visible disaster | `situation`, `denial` |
| `anakin_padme` | a confident claim meeting a horrified realisation | `claim`, `question`, `silence`, `repeat` |
| `is_this_a_pigeon` | confidently misidentifying something obvious | `subject`, `object`, `caption` |
| `they_dont_know` | imagined superiority while standing alone | `thought` |
| `hide_the_pain_harold` | smiling through quiet discomfort | `top`, `bottom` |
| `disaster_girl` | quiet satisfaction at chaos you caused | `caption` |
| `change_my_mind` | a provocative thesis stated flatly and defended | `thesis` |
| `two_buttons` | agonising over a false dilemma | `button1`, `button2`, `label` |
| `roll_safe` | misguided reasoning presented as cleverness | `top`, `bottom` |
| `first_time` | weary recognition of a familiar ordeal | `caption` |
| `clown_makeup` | progressive self-humiliation, step by step | `step1`, `step2`, `step3`, `step4` |
| `always_has_been` | a mundane truth revealed as having always been so | `realisation`, `response` |
| `bernie_asking` | asking once again for a modest thing | `request` |

- [ ] **Step 7: Run the validator against the real library**

Run: `uv run python -c "from pathlib import Path; from zeitgeist.media.templates import validate_templates; print(validate_templates(Path('zeitgeist/media/templates')) or 'all valid')"`
Expected: `all valid`

Fix any reported problem before continuing. A box outside bounds means a
mis-measurement; re-measure against the actual image file.

- [ ] **Step 8: Run tests to verify they pass**

Run: `uv run pytest tests/test_media_templates.py -v`
Expected: PASS, 13 tests

- [ ] **Step 9: Commit**

```bash
git add zeitgeist/media scripts/make_placeholder_templates.py tests/test_media_templates.py
git commit -m "feat: add template manifests, loader, validator, and 24 placeholders"
```

---

### Task 13: Meme renderer

**Files:**
- Create: `zeitgeist/media/render.py`, `scripts/make_golden.py`
- Test: `tests/test_media_render.py`, `tests/fixtures/golden/`

**Interfaces:**
- Consumes: `MediaBrief` (Task 1), `TemplateManifest`, `Slot` (Task 12)
- Produces: `render_meme(brief, manifest, templates_dir, out_path, font_path) -> Path` and `RenderError(Exception)`

Deterministic, no LLM involvement. Text is word-wrapped, then the font shrinks
until the block fits its box, and is drawn with a stroke outline so it stays
legible on any background.

The golden test compares mean absolute pixel difference rather than exact
equality, so a Pillow patch release that nudges antialiasing does not fail the
suite while a genuine layout regression still does.

- [ ] **Step 1: Write the failing test**

Create `tests/test_media_render.py`:

```python
import json

import pytest
from PIL import Image, ImageChops, ImageStat

from zeitgeist.config import PACKAGE_ROOT
from zeitgeist.media.render import RenderError, render_meme
from zeitgeist.media.templates import TemplateManifest
from zeitgeist.models import MediaBrief

FONT = PACKAGE_ROOT / "media" / "fonts" / "DejaVuSans-Bold.ttf"


@pytest.fixture
def template_dir(tmp_path):
    Image.new("RGB", (400, 400), "white").save(tmp_path / "test.png")
    manifest = TemplateManifest(
        id="test",
        image="test.png",
        shape="a shape",
        slots=[
            {"name": "top", "box": (10, 10, 390, 190), "max_chars": 60},
            {"name": "bottom", "box": (10, 210, 390, 390), "max_chars": 60},
        ],
    )
    (tmp_path / "test.json").write_text(manifest.model_dump_json(), encoding="utf-8")
    return tmp_path, manifest


def _brief(**slots) -> MediaBrief:
    return MediaBrief(
        topic_id="t", template_id="test", caption_slots=slots, rationale="because"
    )


def test_writes_a_png_of_the_template_size(tmp_path, template_dir):
    directory, manifest = template_dir
    out = tmp_path / "out.png"
    result = render_meme(
        _brief(top="Hello", bottom="World"), manifest, directory, out, FONT
    )
    assert result == out
    with Image.open(out) as image:
        assert image.size == (400, 400)


def test_drawing_changes_the_image(tmp_path, template_dir):
    directory, manifest = template_dir
    out = tmp_path / "out.png"
    render_meme(_brief(top="Hello", bottom="World"), manifest, directory, out, FONT)
    with Image.open(out) as rendered, Image.open(directory / "test.png") as blank:
        difference = ImageChops.difference(rendered.convert("RGB"), blank)
        assert ImageStat.Stat(difference).sum[0] > 0


def test_long_text_stays_inside_its_box(tmp_path, template_dir):
    directory, manifest = template_dir
    out = tmp_path / "out.png"
    render_meme(
        _brief(top="word " * 80, bottom="short"), manifest, directory, out, FONT
    )
    with Image.open(out) as rendered:
        below = rendered.convert("RGB").crop((0, 195, 400, 205))
        assert ImageStat.Stat(below).stddev[0] == pytest.approx(0.0, abs=1.0)


def test_missing_slot_raises(tmp_path, template_dir):
    directory, manifest = template_dir
    with pytest.raises(RenderError, match="bottom"):
        render_meme(
            _brief(top="only one"), manifest, directory, tmp_path / "o.png", FONT
        )


def test_unknown_slot_raises(tmp_path, template_dir):
    directory, manifest = template_dir
    with pytest.raises(RenderError, match="middle"):
        render_meme(
            _brief(top="a", bottom="b", middle="c"),
            manifest, directory, tmp_path / "o.png", FONT,
        )


def test_missing_image_raises(tmp_path, template_dir):
    directory, manifest = template_dir
    (directory / "test.png").unlink()
    with pytest.raises(RenderError, match="image"):
        render_meme(
            _brief(top="a", bottom="b"), manifest, directory, tmp_path / "o.png", FONT
        )


def test_blank_caption_leaves_that_area_untouched(tmp_path, template_dir):
    """Exercises the early return. Without it, a whitespace caption draws a
    stroke-outlined blank onto the template.
    """
    directory, manifest = template_dir
    out = tmp_path / "out.png"
    render_meme(_brief(top="   ", bottom="
"), manifest, directory, out, FONT)
    with Image.open(out) as rendered, Image.open(directory / "test.png") as blank:
        difference = ImageChops.difference(rendered.convert("RGB"), blank)
        assert ImageStat.Stat(difference).sum[0] == 0


def test_output_is_reproducible(tmp_path, template_dir):
    directory, manifest = template_dir
    brief = _brief(top="Same input", bottom="Same output")
    first, second = tmp_path / "1.png", tmp_path / "2.png"
    render_meme(brief, manifest, directory, first, FONT)
    render_meme(brief, manifest, directory, second, FONT)
    assert first.read_bytes() == second.read_bytes()


def test_matches_the_golden_image(tmp_path, template_dir):
    """Regenerate with: uv run python scripts/make_golden.py"""
    directory, manifest = template_dir
    golden = PACKAGE_ROOT.parent / "tests" / "fixtures" / "golden" / "test_meme.png"
    out = tmp_path / "out.png"
    render_meme(
        _brief(top="Trending topic", bottom="Obvious punchline"),
        manifest, directory, out, FONT,
    )
    with Image.open(out) as rendered, Image.open(golden) as expected:
        assert rendered.size == expected.size
        difference = ImageChops.difference(
            rendered.convert("RGB"), expected.convert("RGB")
        )
        assert ImageStat.Stat(difference).mean[0] < 2.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_media_render.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'zeitgeist.media.render'`

- [ ] **Step 3: Write `zeitgeist/media/render.py`**

```python
"""Pillow compositing. Fully deterministic: no model involvement at all."""

import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from zeitgeist.media.templates import Slot, TemplateManifest
from zeitgeist.models import MediaBrief

MAX_FONT_SIZE = 64
MIN_FONT_SIZE = 12
STROKE_WIDTH = 2
LINE_SPACING = 1.1


class RenderError(Exception):
    """Raised when a brief cannot be drawn onto its template."""


def render_meme(
    brief: MediaBrief,
    manifest: TemplateManifest,
    templates_dir: Path,
    out_path: Path,
    font_path: Path,
) -> Path:
    slot_names = {slot.name for slot in manifest.slots}
    given = set(brief.caption_slots)

    if missing := sorted(slot_names - given):
        raise RenderError(f"Brief is missing slots: {', '.join(missing)}")
    if extra := sorted(given - slot_names):
        raise RenderError(f"Brief has unknown slots: {', '.join(extra)}")

    image_path = Path(templates_dir) / manifest.image
    if not image_path.is_file():
        raise RenderError(f"Template image not found: {image_path}")

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with Image.open(image_path) as source:
        canvas = source.convert("RGB")
        draw = ImageDraw.Draw(canvas)
        for slot in manifest.slots:
            _draw_slot(draw, slot, brief.caption_slots[slot.name], font_path)
        canvas.save(out_path, format="PNG")

    return out_path


def _draw_slot(
    draw: ImageDraw.ImageDraw, slot: Slot, text: str, font_path: Path
) -> None:
    left, top, right, bottom = slot.box
    width, height = right - left, bottom - top
    text = text.strip()
    if not text:
        return

    for size in range(MAX_FONT_SIZE, MIN_FONT_SIZE - 1, -2):
        font = ImageFont.truetype(str(font_path), size)
        lines = _wrap(draw, text, font, width)
        line_height = size * LINE_SPACING
        if line_height * len(lines) <= height:
            break

    block_height = line_height * len(lines)
    y = top + (height - block_height) / 2

    for line in lines:
        line_width = draw.textlength(line, font=font)
        draw.text(
            (left + (width - line_width) / 2, y),
            line,
            font=font,
            fill="white",
            stroke_width=STROKE_WIDTH,
            stroke_fill="black",
        )
        y += line_height


def _wrap(
    draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, width: int
) -> list[str]:
    """Wrap by measured pixel width, narrowing until every line fits."""
    for chars in range(60, 4, -2):
        lines = textwrap.wrap(text, width=chars) or [text]
        if all(draw.textlength(line, font=font) <= width for line in lines):
            return lines
    return textwrap.wrap(text, width=6) or [text]
```

- [ ] **Step 4: Generate the golden image**

Run the renderer once by hand to produce the committed reference:

Create `scripts/make_golden.py`:

```python
"""Regenerates the committed golden render. Run after intentional layout changes."""

import shutil
import tempfile
from pathlib import Path

from PIL import Image

from zeitgeist.config import PACKAGE_ROOT
from zeitgeist.media.render import render_meme
from zeitgeist.media.templates import TemplateManifest
from zeitgeist.models import MediaBrief

MANIFEST = TemplateManifest(
    id="test",
    image="test.png",
    shape="a shape",
    slots=[
        {"name": "top", "box": (10, 10, 390, 190), "max_chars": 60},
        {"name": "bottom", "box": (10, 210, 390, 390), "max_chars": 60},
    ],
)


def main() -> None:
    out = Path("tests/fixtures/golden/test_meme.png")
    out.parent.mkdir(parents=True, exist_ok=True)

    scratch = Path(tempfile.mkdtemp())
    try:
        Image.new("RGB", (400, 400), "white").save(scratch / "test.png")
        render_meme(
            MediaBrief(
                topic_id="t",
                template_id="test",
                caption_slots={
                    "top": "Trending topic",
                    "bottom": "Obvious punchline",
                },
                rationale="because",
            ),
            MANIFEST,
            scratch,
            out,
            PACKAGE_ROOT / "media" / "fonts" / "DejaVuSans-Bold.ttf",
        )
    finally:
        shutil.rmtree(scratch, ignore_errors=True)

    print(f"wrote {out}")


if __name__ == "__main__":
    main()
```

Then run it:

```bash
uv run python scripts/make_golden.py
```

A script rather than a one-liner, because this needs re-running every time the
renderer's layout changes on purpose — and a throwaway shell one-liner is the
kind of thing nobody can reproduce six months later.

Open `tests/fixtures/golden/test_meme.png` and confirm both captions are
centred inside their halves and legible. If they are not, fix the renderer
before committing — you are about to freeze this as the reference.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_media_render.py -v`
Expected: PASS, 9 tests

- [ ] **Step 6: Commit**

```bash
git add zeitgeist/media/render.py scripts/make_golden.py tests/test_media_render.py tests/fixtures/golden
git commit -m "feat: add deterministic Pillow meme renderer"
```

---

### Task 14: Brief generation

**Files:**
- Create: `zeitgeist/media/brief.py`
- Test: `tests/test_media_brief.py`

**Interfaces:**
- Consumes: `MediaBrief`, `ScoredTopic` (Tasks 1, 11), `TemplateManifest` (Task 12), `LLMProvider` (Task 3)
- Produces:
  - `BriefChoice(BaseModel)` with `template_id: str`, `caption_slots: dict[str, str]`, `rationale: str`
  - `generate_brief(topic, templates, provider) -> MediaBrief`
  - `generate_briefs(topics, templates, provider) -> list[MediaBrief]`
  - `BriefError(Exception)`
  - `BRIEF_SYSTEM: str`

The model returns `BriefChoice`, not `MediaBrief` — `topic_id` is attached by
us so the model cannot invent it. Because the model may only select from
supplied ids and fill named slots, a hallucinated template or missing slot
fails validation here rather than reaching the renderer. One retry with the
error appended, then the topic is skipped.

- [ ] **Step 1: Write the failing test**

Create `tests/test_media_brief.py`:

```python
import pytest

from zeitgeist.llm.base import FakeLLMProvider, LLMError
from zeitgeist.media.brief import (
    BriefChoice,
    BriefError,
    generate_brief,
    generate_briefs,
)
from zeitgeist.media.templates import TemplateManifest
from zeitgeist.models import ScoredTopic, Sentiment


def _templates() -> dict[str, TemplateManifest]:
    return {
        "drake": TemplateManifest(
            id="drake",
            image="drake.png",
            shape="rejecting option A in favour of preferred option B",
            slots=[
                {"name": "rejected", "box": (0, 0, 10, 10), "max_chars": 60},
                {"name": "preferred", "box": (0, 10, 10, 20), "max_chars": 60},
            ],
        ),
        "this_is_fine": TemplateManifest(
            id="this_is_fine",
            image="this_is_fine.png",
            shape="insisting all is well amid visible disaster",
            slots=[
                {"name": "situation", "box": (0, 0, 10, 10), "max_chars": 60},
                {"name": "denial", "box": (0, 10, 10, 20), "max_chars": 60},
            ],
        ),
    }


def _topic(tid: str = "cats") -> ScoredTopic:
    return ScoredTopic(
        id=tid, label=tid.title(), summary=f"About {tid}.", post_ids=["p1"],
        trend_score=0.8, primary_sentiment=Sentiment.CUTE,
        valence=0.7, meme_potential=0.9,
    )


def _choice(**overrides) -> BriefChoice:
    defaults = dict(
        template_id="drake",
        caption_slots={"rejected": "Dogs", "preferred": "Cats"},
        rationale="Preference structure fits.",
    )
    return BriefChoice(**{**defaults, **overrides})


def test_returns_a_brief_with_the_topic_id_attached():
    provider = FakeLLMProvider([_choice()])
    brief = generate_brief(_topic(), _templates(), provider)
    assert brief.topic_id == "cats"
    assert brief.template_id == "drake"
    assert brief.caption_slots["preferred"] == "Cats"
    # The spec keeps the rationale specifically for debugging bad captions.
    assert brief.rationale == "Preference structure fits."


def test_captions_are_stripped_before_rendering():
    """Leading newlines are common in model output and would shift the text
    off-centre inside its box.
    """
    provider = FakeLLMProvider(
        [_choice(caption_slots={"rejected": "  Dogs ", "preferred": "Cats
"})]
    )
    brief = generate_brief(_topic(), _templates(), provider)
    assert brief.caption_slots == {"rejected": "Dogs", "preferred": "Cats"}


def test_prompt_lists_every_template_id_shape_and_slots():
    provider = FakeLLMProvider([_choice()])
    generate_brief(_topic(), _templates(), provider)
    prompt = provider.calls[0].prompt
    assert "drake" in prompt and "this_is_fine" in prompt
    assert "rejecting option A" in prompt
    assert "rejected" in prompt and "preferred" in prompt


def test_prompt_includes_topic_sentiment():
    provider = FakeLLMProvider([_choice()])
    generate_brief(_topic(), _templates(), provider)
    assert "cute" in provider.calls[0].prompt.lower()


def test_hallucinated_template_id_triggers_retry():
    provider = FakeLLMProvider([_choice(template_id="invented"), _choice()])
    brief = generate_brief(_topic(), _templates(), provider)
    assert brief.template_id == "drake"
    assert len(provider.calls) == 2
    assert "invented" in provider.calls[1].prompt


def test_missing_slot_triggers_retry():
    bad = _choice(caption_slots={"rejected": "Dogs"})
    provider = FakeLLMProvider([bad, _choice()])
    assert generate_brief(_topic(), _templates(), provider).template_id == "drake"


def test_unknown_slot_triggers_retry():
    bad = _choice(
        caption_slots={"rejected": "a", "preferred": "b", "extra": "c"}
    )
    provider = FakeLLMProvider([bad, _choice()])
    assert generate_brief(_topic(), _templates(), provider).template_id == "drake"


def test_second_failure_raises_brief_error():
    provider = FakeLLMProvider(
        [_choice(template_id="nope"), _choice(template_id="also-nope")]
    )
    with pytest.raises(BriefError):
        generate_brief(_topic(), _templates(), provider)


def test_provider_error_raises_brief_error():
    provider = FakeLLMProvider([LLMError("down")])
    with pytest.raises(BriefError):
        generate_brief(_topic(), _templates(), provider)


def test_generate_briefs_skips_failures_and_keeps_the_rest():
    provider = FakeLLMProvider(
        [LLMError("down"), _choice(), _choice()]
    )
    briefs = generate_briefs(
        [_topic("dropped"), _topic("kept")], _templates(), provider
    )
    assert [brief.topic_id for brief in briefs] == ["kept"]


def test_blank_caption_triggers_retry():
    provider = FakeLLMProvider(
        [_choice(caption_slots={"rejected": "  ", "preferred": "Cats"}), _choice()]
    )
    assert generate_brief(_topic(), _templates(), provider).template_id == "drake"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_media_brief.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'zeitgeist.media.brief'`

- [ ] **Step 3: Write `zeitgeist/media/brief.py`**

```python
"""Topic to template choice and captions.

The model may only pick from supplied ids and fill named slots, so a
hallucinated template or a missing slot fails here rather than reaching the
renderer. The rationale is kept deliberately: reading why the model chose a
template is the main tool for debugging poor captions.
"""

import logging

from pydantic import BaseModel

from zeitgeist.llm.base import LLMProvider
from zeitgeist.media.templates import TemplateManifest
from zeitgeist.models import MediaBrief, ScoredTopic

log = logging.getLogger(__name__)

BRIEF_SYSTEM = (
    "You write memes. Given a trending topic and a library of meme templates, "
    "pick the template whose rhetorical shape genuinely fits the topic, then "
    "write the caption for every one of its slots. Captions are short, "
    "specific, and land for someone who has not read the source posts. Find "
    "the humane or absurd angle rather than punching down, and never make a "
    "joke at the expense of people who have been harmed. Use only template "
    "ids from the library and fill exactly the slots that template lists."
)


class BriefChoice(BaseModel):
    """The model's template choice and captions. `topic_id` is attached by us."""

    template_id: str
    caption_slots: dict[str, str]
    rationale: str


class BriefError(Exception):
    """Raised when no valid brief could be produced for a topic."""


def generate_brief(
    topic: ScoredTopic,
    templates: dict[str, TemplateManifest],
    provider: LLMProvider,
) -> MediaBrief:
    prompt = _build_prompt(topic, templates)
    attempt_prompt = prompt
    last_error: str | None = None

    for _ in range(2):
        try:
            choice = provider.complete(
                attempt_prompt, BriefChoice, system=BRIEF_SYSTEM
            )
        except Exception as exc:
            raise BriefError(f"Provider failed for {topic.label!r}: {exc}") from exc

        problem = _validate(choice, templates)
        if problem is None:
            return MediaBrief(
                topic_id=topic.id,
                template_id=choice.template_id,
                caption_slots={
                    name: text.strip()
                    for name, text in choice.caption_slots.items()
                },
                rationale=choice.rationale,
            )

        last_error = problem
        attempt_prompt = (
            f"{prompt}\n\nYour previous answer was rejected: {problem}\n"
            "Return a corrected answer."
        )

    raise BriefError(f"No valid brief for {topic.label!r}: {last_error}")


def generate_briefs(
    topics: list[ScoredTopic],
    templates: dict[str, TemplateManifest],
    provider: LLMProvider,
) -> list[MediaBrief]:
    """Brief every topic. A topic that cannot be briefed is skipped."""
    briefs: list[MediaBrief] = []
    for topic in topics:
        try:
            briefs.append(generate_brief(topic, templates, provider))
        except BriefError as exc:
            log.warning("Skipping %r: %s", topic.label, exc)
    return briefs


def _validate(
    choice: BriefChoice, templates: dict[str, TemplateManifest]
) -> str | None:
    manifest = templates.get(choice.template_id)
    if manifest is None:
        return (
            f"template_id {choice.template_id!r} is not in the library; "
            f"choose one of: {', '.join(sorted(templates))}"
        )

    expected = {slot.name for slot in manifest.slots}
    given = set(choice.caption_slots)

    if missing := sorted(expected - given):
        return f"missing captions for slots: {', '.join(missing)}"
    if extra := sorted(given - expected):
        return f"unknown slots for {manifest.id!r}: {', '.join(extra)}"
    if blank := sorted(n for n, t in choice.caption_slots.items() if not t.strip()):
        return f"blank captions for slots: {', '.join(blank)}"
    return None


def _build_prompt(
    topic: ScoredTopic, templates: dict[str, TemplateManifest]
) -> str:
    library = "\n".join(
        f"- id={manifest.id} | shape: {manifest.shape} | "
        f"slots: {', '.join(slot.name for slot in manifest.slots)}"
        for manifest in templates.values()
    )
    return (
        f"Topic: {topic.label}\n"
        f"Summary: {topic.summary}\n"
        f"Sentiment: {topic.primary_sentiment.value}\n"
        f"Meme potential: {topic.meme_potential:.2f}\n\n"
        f"Template library:\n{library}\n\n"
        "Pick the best-fitting template and write its captions."
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_media_brief.py -v`
Expected: PASS, 11 tests

- [ ] **Step 5: Commit**

```bash
git add zeitgeist/media/brief.py tests/test_media_brief.py
git commit -m "feat: add validated brief generation from topics"
```

---

### Task 15: CLI orchestration, checkpointing, and end-to-end test

**Files:**
- Create: `zeitgeist/pipeline.py`, `zeitgeist/cli.py`, `README.md`
- Test: `tests/test_pipeline.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: everything from Tasks 1–14
- Produces:
  - `Stage` (str enum): `INGEST`, `ANALYSE`, `EVALUATE`, `GENERATE`
  - `run_pipeline(settings, source, provider, store, run_id, start_at=Stage.INGEST) -> Path` returning the run directory
  - `main(argv=None) -> int`

Checkpointing is what lets stage D be re-run repeatedly against a frozen
`ranked.json` while tuning caption prompts, without re-scraping or re-paying
for stages B and C. `--resume-from` is the switch that uses it.

- [ ] **Step 1: Write the failing pipeline test**

Create `tests/test_pipeline.py`:

```python
import json

import pytest

from zeitgeist.analysis.consolidate import ConsolidatedTopic, Consolidation
from zeitgeist.analysis.extract import PostTags, TagExtraction
from zeitgeist.analysis.sentiment import SentimentJudgement
from zeitgeist.config import Settings
from zeitgeist.llm.base import FakeLLMProvider, LLMError
from zeitgeist.media.brief import BriefChoice
from zeitgeist.models import Sentiment
from zeitgeist.pipeline import Stage, run_pipeline
from zeitgeist.store import Store


class StubSource:
    name = "stub"

    def __init__(self, posts):
        self._posts = posts
        self.fetch_calls = 0

    def fetch(self, limit):
        self.fetch_calls += 1
        return self._posts[:limit]


@pytest.fixture
def settings(tmp_path):
    return Settings(
        reddit_client_id="id",
        reddit_client_secret="secret",
        anthropic_api_key="key",
        topic_count=1,
        output_dir=tmp_path / "output",
        db_path=tmp_path / "data" / "z.db",
    )


def _provider(posts):
    return FakeLLMProvider(
        [
            TagExtraction(
                assignments=[
                    PostTags(post_id=post.source_id, tags=["cats"]) for post in posts
                ]
            ),
            Consolidation(
                topics=[
                    ConsolidatedTopic(
                        label="Cats", summary="Cat things.", tags=["cats"]
                    )
                ]
            ),
            SentimentJudgement(
                primary_sentiment=Sentiment.CUTE,
                secondary_sentiments=[],
                valence=0.8,
                meme_potential=0.9,
            ),
            BriefChoice(
                template_id="drake",
                caption_slots={"rejected": "Dogs", "preferred": "Cats"},
                rationale="Fits.",
            ),
        ]
    )


def _store(settings):
    store = Store(settings.db_path)
    store.init_schema()
    return store


def test_writes_every_checkpoint(settings, sample_posts):
    posts = sample_posts[:3]
    run_dir = run_pipeline(
        settings, StubSource(posts), _provider(posts), _store(settings), "run1"
    )
    for name in ("posts.json", "topics.json", "ranked.json", "briefs.json"):
        assert (run_dir / name).is_file()


def test_produces_a_png(settings, sample_posts):
    posts = sample_posts[:3]
    run_dir = run_pipeline(
        settings, StubSource(posts), _provider(posts), _store(settings), "run1"
    )
    assert list(run_dir.glob("*.png"))


def test_records_the_run_in_the_store(settings, sample_posts):
    posts = sample_posts[:3]
    store = _store(settings)
    run_pipeline(settings, StubSource(posts), _provider(posts), store, "run1")
    assert store.previous_scores(exclude_run_id="run2") != {}


def test_resume_from_generate_skips_scraping(settings, sample_posts):
    posts = sample_posts[:3]
    source = StubSource(posts)
    run_pipeline(settings, source, _provider(posts), _store(settings), "run1")
    assert source.fetch_calls == 1

    provider = FakeLLMProvider(
        [
            BriefChoice(
                template_id="drake",
                caption_slots={"rejected": "Cats", "preferred": "Dogs"},
                rationale="Retuned.",
            )
        ]
    )
    run_pipeline(
        settings, source, provider, _store(settings), "run1",
        start_at=Stage.GENERATE,
    )
    assert source.fetch_calls == 1


def test_resume_without_checkpoint_raises(settings, sample_posts):
    with pytest.raises(FileNotFoundError):
        run_pipeline(
            settings, StubSource(sample_posts), FakeLLMProvider(),
            _store(settings), "never-ran", start_at=Stage.GENERATE,
        )


def test_a_failing_stage_degrades_rather_than_killing_the_run(settings, sample_posts):
    """The spec's central error rule: fewer memes is a success, no output is
    a failure. One topic's sentiment call fails; the other must still reach
    a rendered PNG.
    """
    posts = sample_posts[:3]
    provider = FakeLLMProvider(
        [
            TagExtraction(
                assignments=[
                    PostTags(post_id=post.source_id, tags=["cats"]) for post in posts
                ]
            ),
            Consolidation(
                topics=[
                    ConsolidatedTopic(
                        label="Cats", summary="Cat things.", tags=["cats"]
                    ),
                    ConsolidatedTopic(
                        label="Dogs", summary="Dog things.", tags=["cats"]
                    ),
                ]
            ),
            LLMError("sentiment call failed"),
            SentimentJudgement(
                primary_sentiment=Sentiment.CUTE,
                secondary_sentiments=[],
                valence=0.8,
                meme_potential=0.9,
            ),
            BriefChoice(
                template_id="drake",
                caption_slots={"rejected": "Dogs", "preferred": "Cats"},
                rationale="Fits.",
            ),
        ]
    )
    run_dir = run_pipeline(
        settings.model_copy(update={"topic_count": 2}),
        StubSource(posts),
        provider,
        _store(settings),
        "run1",
    )

    ranked = json.loads((run_dir / "ranked.json").read_text(encoding="utf-8"))
    assert [entry["label"] for entry in ranked] == ["Dogs"]
    assert len(list(run_dir.glob("*.png"))) == 1


def test_checkpoints_are_valid_json(settings, sample_posts):
    posts = sample_posts[:3]
    run_dir = run_pipeline(
        settings, StubSource(posts), _provider(posts), _store(settings), "run1"
    )
    ranked = json.loads((run_dir / "ranked.json").read_text(encoding="utf-8"))
    assert ranked[0]["primary_sentiment"] == "cute"
    assert ranked[0]["final_rank"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_pipeline.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'zeitgeist.pipeline'`

- [ ] **Step 3: Write `zeitgeist/pipeline.py`**

```python
"""Stage orchestration and checkpointing.

Each stage writes its output before the next begins, so stage D can be re-run
against a frozen ranked.json while tuning prompts, and a crash always leaves
partial artifacts to inspect.
"""

import json
import logging
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path

from pydantic import BaseModel

from zeitgeist.analysis.consolidate import consolidate
from zeitgeist.analysis.extract import extract_tags
from zeitgeist.analysis.score import score_topics
from zeitgeist.analysis.sentiment import judge_topics, select
from zeitgeist.config import Settings
from zeitgeist.llm.base import LLMProvider
from zeitgeist.media.brief import generate_briefs
from zeitgeist.media.render import RenderError, render_meme
from zeitgeist.media.templates import load_templates
from zeitgeist.models import MediaBrief, Post, ScoredTopic, Topic
from zeitgeist.sources.base import Source
from zeitgeist.store import Store

log = logging.getLogger(__name__)


class Stage(str, Enum):
    INGEST = "ingest"
    ANALYSE = "analyse"
    EVALUATE = "evaluate"
    GENERATE = "generate"


ORDER = [Stage.INGEST, Stage.ANALYSE, Stage.EVALUATE, Stage.GENERATE]


def new_run_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def run_pipeline(
    settings: Settings,
    source: Source,
    provider: LLMProvider,
    store: Store,
    run_id: str,
    start_at: Stage = Stage.INGEST,
) -> Path:
    run_dir = Path(settings.output_dir) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    resuming = ORDER.index(start_at)

    store.start_run(run_id)
    posts: list[Post] = []

    # Stage A — fatal on failure: with no posts there is nothing to analyse.
    if resuming <= ORDER.index(Stage.INGEST):
        posts = source.fetch(limit=settings.post_limit)
        log.info("Fetched %d posts", len(posts))
        _write(run_dir / "posts.json", posts)
    else:
        posts = _read(run_dir / "posts.json", Post)

    if resuming <= ORDER.index(Stage.ANALYSE):
        tags = extract_tags(posts, provider)
        topics = consolidate(tags, provider)
        topics = score_topics(
            topics, posts, datetime.now(UTC), store.previous_scores(run_id)
        )
        log.info("Identified %d topics", len(topics))
        store.record_topics(run_id, topics)
        _write(run_dir / "topics.json", topics)

    if resuming <= ORDER.index(Stage.EVALUATE):
        topics = _read(run_dir / "topics.json", Topic)
        ranked = select(
            judge_topics(topics, provider),
            settings.sentiment_weights,
            settings.topic_count,
        )
        log.info("Selected %d topics", len(ranked))
        _write(run_dir / "ranked.json", ranked)

    ranked = _read(run_dir / "ranked.json", ScoredTopic)
    templates = load_templates(settings.templates_dir)
    briefs = generate_briefs(ranked, templates, provider)
    _write(run_dir / "briefs.json", briefs)

    rendered = _render_all(briefs, templates, settings, run_dir)
    log.info("Rendered %d memes into %s", rendered, run_dir)

    store.finish_run(run_id, status="ok", post_count=len(posts))
    return run_dir


def _render_all(
    briefs: list[MediaBrief],
    templates: dict,
    settings: Settings,
    run_dir: Path,
) -> int:
    count = 0
    for position, brief in enumerate(briefs, start=1):
        try:
            render_meme(
                brief,
                templates[brief.template_id],
                settings.templates_dir,
                run_dir / f"{position:02d}-{brief.topic_id}.png",
                settings.font_path,
            )
            count += 1
        except RenderError as exc:
            log.warning("Could not render %r: %s", brief.topic_id, exc)
    return count


def _write(path: Path, models: list[BaseModel]) -> None:
    payload = [model.model_dump(mode="json") for model in models]
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _read(path: Path, schema: type) -> list:
    if not path.is_file():
        raise FileNotFoundError(f"Missing checkpoint: {path}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [schema.model_validate(entry) for entry in raw]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_pipeline.py -v`
Expected: PASS, 7 tests

- [ ] **Step 5: Write the failing CLI test**

Create `tests/test_cli.py`:

```python
import pytest

from zeitgeist.cli import build_parser, main


def test_run_is_the_default_command():
    args = build_parser().parse_args([])
    assert args.command == "run"


def test_bare_invocation_carries_every_run_attribute():
    args = build_parser().parse_args([])
    assert args.run_id is None
    assert args.resume_from == "ingest"
    assert args.verbose is False


def test_resume_from_is_parsed():
    args = build_parser().parse_args(
        ["run", "--run-id", "abc", "--resume-from", "generate"]
    )
    assert args.run_id == "abc"
    assert args.resume_from == "generate"


def test_resume_from_requires_a_run_id(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(["run", "--resume-from", "generate"])
    assert exit_info.value.code == 2
    assert "--run-id" in capsys.readouterr().err


def test_validate_templates_reports_success(capsys):
    assert main(["validate-templates"]) == 0
    assert "valid" in capsys.readouterr().out


def test_validate_templates_reports_problems(tmp_path, capsys):
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")
    assert main(["validate-templates", "--dir", str(tmp_path)]) == 1
    assert "parse" in capsys.readouterr().out
```

- [ ] **Step 6: Run test to verify it fails**

Run: `uv run pytest tests/test_cli.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'zeitgeist.cli'`

- [ ] **Step 7: Write `zeitgeist/cli.py`**

```python
"""Command-line entry point."""

import argparse
import logging
import sys
from pathlib import Path

from zeitgeist.config import PACKAGE_ROOT, Settings
from zeitgeist.llm.factory import build_provider
from zeitgeist.media.templates import validate_templates
from zeitgeist.pipeline import Stage, new_run_id, run_pipeline
from zeitgeist.sources.reddit import RedditSource
from zeitgeist.store import Store


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="zeitgeist")
    subparsers = parser.add_subparsers(dest="command")
    # Bare `zeitgeist` means `zeitgeist run`, so the top-level parser must
    # carry every attribute `_run` reads — not just `command`.
    parser.set_defaults(
        command="run",
        run_id=None,
        resume_from=Stage.INGEST.value,
        verbose=False,
    )

    run = subparsers.add_parser("run", help="Scrape, analyse, and generate memes")
    run.add_argument("--run-id", default=None, help="Reuse an existing run directory")
    run.add_argument(
        "--resume-from",
        choices=[stage.value for stage in Stage],
        default=Stage.INGEST.value,
        help="Skip earlier stages and reuse their checkpoints",
    )
    run.add_argument("--verbose", action="store_true")

    check = subparsers.add_parser(
        "validate-templates", help="Check every template manifest"
    )
    check.add_argument("--dir", default=None, help="Template directory to check")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "validate-templates":
        return _validate(args, parser)
    return _run(args, parser)


def _validate(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    # Deliberately does not build Settings: checking the shipped templates
    # should work before anyone has written a .env.
    directory = (
        Path(args.dir)
        if args.dir
        else PACKAGE_ROOT / "media" / "templates"
    )
    problems = validate_templates(directory)
    if not problems:
        print(f"All templates in {directory} are valid.")
        return 0
    for problem in problems:
        print(problem)
    return 1


def _run(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    start_at = Stage(args.resume_from)
    if start_at is not Stage.INGEST and not args.run_id:
        parser.error("--resume-from requires --run-id")

    settings = _settings_or_exit(parser)
    store = Store(settings.db_path)
    store.init_schema()

    try:
        run_dir = run_pipeline(
            settings=settings,
            source=RedditSource.from_settings(settings),
            provider=build_provider(settings),
            store=store,
            run_id=args.run_id or new_run_id(),
            start_at=start_at,
        )
        summary = store.run_summary(args.run_id or run_dir.name)
    finally:
        store.close()

    memes = len(list(run_dir.glob("*.png")))
    posts = (summary or {}).get("post_count", 0)
    print(f"Run complete: {run_dir} ({posts} posts, {memes} memes)")
    return 0


def _settings_or_exit(parser: argparse.ArgumentParser) -> Settings:
    try:
        return Settings()
    except Exception as exc:
        parser.error(f"Configuration error: {exc}\nCopy .env.example to .env.")


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 8: Run the full suite**

Run: `uv run pytest -v`
Expected: PASS, all tests across every module

- [ ] **Step 9: Write `README.md`**

````markdown
# Zeitgeist Actualiser

Scrapes Reddit, works out what is trending, and generates memes about it.

## Setup

Install [uv](https://docs.astral.sh/uv/), then:

```bash
uv sync
```

That creates `.venv/`, installs the exact versions in `uv.lock`, and fetches
the Python version named in `.python-version` if you do not have it. Then copy
the config template:

```bash
copy .env.example .env
```

Fill in `.env`. Reddit credentials come from
https://www.reddit.com/prefs/apps — create a **script** app; the pipeline uses
read-only access, so no user login is needed.

## Running

```bash
uv run zeitgeist run
```

Output lands in `output/<run-id>/`: the four stage checkpoints as JSON, plus
one PNG per selected topic.

Re-run only the meme generation against an existing run, which is how you tune
caption prompts without re-scraping or paying for analysis again:

```bash
uv run zeitgeist run --run-id 20260816T120000Z --resume-from generate
```

Check the template library after editing a manifest:

```bash
uv run zeitgeist validate-templates
```

## Using a local model

Install Ollama, pull a model, then set in `.env`:

```
LLM_PROVIDER=ollama
LLM_MODEL=qwen2.5:14b
```

Nothing else changes. Comparing the two backends on identical input is the
point of the provider abstraction.

## Tests

```bash
uv run pytest
```

No test touches the network. Every LLM call goes through `FakeLLMProvider`.
````

- [ ] **Step 10: Commit**

```bash
git add zeitgeist/pipeline.py zeitgeist/cli.py README.md tests/test_pipeline.py tests/test_cli.py
git commit -m "feat: add pipeline orchestration, CLI, and README"
```

---

## Verification

After Task 15, confirm the whole thing works against real services. These
steps need network access and Reddit credentials, so they are deliberately
outside the test suite.

- [ ] **Full suite passes**

Run: `uv run pytest -v`
Expected: every test passes, no network calls

- [ ] **Lint and format are clean**

Run: `uv run ruff format --check . && uv run ruff check .`
Expected: no diffs and no violations

- [ ] **The lockfile is current**

Run: `uv lock --check`
Expected: reports the lockfile is up to date. If it does not, run `uv lock` and commit the result — a stale lockfile means the environment is not reproducible.

- [ ] **Template library validates**

Run: `uv run zeitgeist validate-templates`
Expected: `All templates in ... are valid.`

- [ ] **A real run produces memes**

Run: `uv run zeitgeist run --verbose`
Expected: `output/<run-id>/` contains `posts.json`, `topics.json`,
`ranked.json`, `briefs.json`, and up to 5 PNGs. Open the PNGs — captions
should be legible and inside their boxes.

- [ ] **Resume works**

Run: `uv run zeitgeist run --run-id <that-run-id> --resume-from generate`
Expected: completes in seconds without re-scraping, and rewrites the PNGs.

- [ ] **History accumulates**

Run `uv run zeitgeist run` a second time, then inspect `topics.json` from the second
run. Expected: `score_components.rank_delta` is non-zero for at least one
topic that appeared in both runs.

- [ ] **Local backend works**

Set `LLM_PROVIDER=ollama` and `LLM_MODEL` to a pulled model, then run
`uv run zeitgeist run --verbose`. Expected: completes without changing any code.
Compare the topics and captions against an Anthropic run — that comparison is
the point of the abstraction.
