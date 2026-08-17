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
