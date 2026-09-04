import sqlite3

import pytest
from fastapi.testclient import TestClient

from zeitgeist.api import create_app
from zeitgeist.config import Settings
from zeitgeist.schema import SCHEMA_VERSION


def _settings(tmp_path) -> Settings:
    return Settings(
        _env_file=None,
        db_path=tmp_path / "data" / "z.db",
        output_dir=tmp_path / "output",
    )


def test_the_app_serves_its_openapi_schema(tmp_path):
    """The schema is the contract phase 5 generates its client from, so it
    has to be reachable before any endpoint exists."""
    client = TestClient(create_app(_settings(tmp_path)))

    response = client.get("/openapi.json")

    assert response.status_code == 200
    assert "paths" in response.json()


def test_the_app_opens_the_database_it_was_given(tmp_path):
    """Not the ambient one. A factory that reached for `data/zeitgeist.db`
    would make every test depend on whether the tool had been run locally."""
    settings = _settings(tmp_path)

    create_app(settings)

    assert (tmp_path / "data" / "z.db").is_file()


def test_the_app_closes_its_store_when_it_shuts_down(tmp_path):
    """The lifespan's only job is to close the store, and no other test
    runs it: two build no client and the third never enters the context
    manager. Deleting the `finally: store.close()` would pass all of them.
    """
    app = create_app(_settings(tmp_path))

    with TestClient(app) as client:
        client.get("/openapi.json")

    with pytest.raises(sqlite3.ProgrammingError):
        app.state.store._conn.execute("SELECT 1")


def test_the_app_creates_its_schema_on_startup(tmp_path):
    """A fresh install serves an empty database rather than 500ing on the
    first query."""
    create_app(_settings(tmp_path))

    conn = sqlite3.connect(tmp_path / "data" / "z.db")
    try:
        [(version,)] = conn.execute("PRAGMA user_version").fetchall()
    finally:
        conn.close()
    # Compared against the constant rather than a literal 3: bumping the
    # schema version is a decision someone is entitled to make, and this
    # test exists to catch init_schema not being called at all, which
    # leaves the version at 0.
    assert version == SCHEMA_VERSION
