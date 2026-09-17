import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from zeitgeist.models import Item

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def _close_seeded_clients():
    """Exit every `TestClient` `seeded_client` entered during this test.

    `seeded_client` (tests/api_factory.py) enters the client's lifespan
    itself and appends it to `_open_clients`, rather than every one of its
    52 call sites becoming a `with` block. This fixture is the other half:
    it runs the deferred `__exit__` after the test body finishes, whether
    the test passed or raised, so the app's `finally: store.close()` still
    runs and the connection does not leak for the rest of the process.
    """
    yield
    from tests import api_factory

    while api_factory._open_clients:
        api_factory._open_clients.pop().__exit__(None, None, None)


@pytest.fixture
def sample_items() -> list[Item]:
    raw = json.loads((FIXTURES / "items.json").read_text(encoding="utf-8"))
    return [Item.model_validate(entry) for entry in raw]


@pytest.fixture
def fixture_now() -> datetime:
    """The `fetched_at` shared by every fixture item."""
    return datetime(2026, 8, 16, 12, 0, tzinfo=UTC)
