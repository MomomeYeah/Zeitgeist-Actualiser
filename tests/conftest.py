import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from zeitgeist.models import Item

FIXTURES = Path(__file__).parent / "fixtures"

# Settings fields that read from the environment. A developer's real shell
# can plausibly have any of these set (e.g. ANTHROPIC_API_KEY from other
# work), and Settings(_env_file=None) only disables .env, not os.environ —
# so left alone, the suite's result depends on who is running it.
_SETTINGS_ENV_VARS = (
    "DB_PATH",
    "SOURCES",
    "ANTHROPIC_API_KEY",
    "LLM_PROVIDER",
    "LLM_MODEL",
    "OLLAMA_HOST",
    "LEMMY_INSTANCE",
    "LEMMY_INCLUDE_NSFW",
    "WIKIPEDIA_PROJECT",
    "WIKIPEDIA_CONTACT",
    "BLUESKY_API_BASE",
    "BLUESKY_TREND_LIMIT",
    "BLUESKY_POSTS_PER_TREND",
    "BLUESKY_FETCH_CONCURRENCY",
    "TOPIC_COUNT",
    "PHRASE_MIN_AUTHORS",
    "MEME_POTENTIAL_WEIGHT",
    "DISTIL_CHAR_BUDGET",
    "DISTIL_CONCURRENCY",
)


@pytest.fixture(autouse=True)
def _clean_settings_env(monkeypatch, tmp_path):
    """Strip real env vars Settings reads, for every test in the suite.

    Runs before each test body, so a test that calls monkeypatch.setenv
    itself (e.g. to exercise the real env-var decode path) still sees its
    own value — this only removes what the ambient shell contributed.

    An ambient *file* is as much a hermeticity threat as an ambient shell
    variable. `zeitgeist.settings_source` reads `DB_PATH` and, when it is
    unset, falls back to the relative path `data/zeitgeist.db`. Merely
    deleting `DB_PATH` from the environment (as the loop below does for
    every other var) would let that fallback fire, so a real database left
    at that path by a previous local run — one containing tuned settings
    rows, such as a non-default `bluesky_trend_limit` — would silently feed
    those values into every `Settings()` built by the suite. So `DB_PATH` is
    additionally repointed at a name inside this test's own `tmp_path`,
    which pytest creates fresh and empty per test and which nothing can have
    written a database into ahead of time.
    """
    for name in _SETTINGS_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DB_PATH", str(tmp_path / "no-ambient-database.db"))


@pytest.fixture
def sample_items() -> list[Item]:
    raw = json.loads((FIXTURES / "items.json").read_text(encoding="utf-8"))
    return [Item.model_validate(entry) for entry in raw]


@pytest.fixture
def fixture_now() -> datetime:
    """The `fetched_at` shared by every fixture item."""
    return datetime(2026, 8, 16, 12, 0, tzinfo=UTC)
