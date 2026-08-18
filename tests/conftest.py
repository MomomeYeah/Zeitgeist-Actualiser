import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from zeitgeist.models import Post

FIXTURES = Path(__file__).parent / "fixtures"

# Settings fields that read from the environment. A developer's real shell
# can plausibly have any of these set (e.g. REDDIT_CLIENT_ID from other
# work), and Settings(_env_file=None) only disables .env, not os.environ —
# so left alone, the suite's result depends on who is running it.
_SETTINGS_ENV_VARS = (
    "SOURCES",
    "SUBREDDITS",
    "REDDIT_CLIENT_ID",
    "REDDIT_CLIENT_SECRET",
    "REDDIT_USER_AGENT",
    "ANTHROPIC_API_KEY",
    "LLM_PROVIDER",
    "LLM_MODEL",
    "OLLAMA_HOST",
    "LEMMY_INSTANCE",
    "LEMMY_INCLUDE_NSFW",
    "SENTIMENT_WEIGHTS",
    "POST_LIMIT",
    "TOPIC_COUNT",
)


@pytest.fixture(autouse=True)
def _clean_settings_env(monkeypatch):
    """Strip real env vars Settings reads, for every test in the suite.

    Runs before each test body, so a test that calls monkeypatch.setenv
    itself (e.g. to exercise the real env-var decode path) still sees its
    own value — this only removes what the ambient shell contributed.
    """
    for name in _SETTINGS_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def sample_posts() -> list[Post]:
    raw = json.loads((FIXTURES / "posts.json").read_text(encoding="utf-8"))
    return [Post.model_validate(entry) for entry in raw]


@pytest.fixture
def fixture_now() -> datetime:
    """The `fetched_at` shared by every fixture post."""
    return datetime(2026, 8, 16, 12, 0, tzinfo=UTC)
