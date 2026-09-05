import sqlite3

import pytest
from fastapi.testclient import TestClient

from tests.api_factory import api_settings, seeded_client
from tests.run_factory import make_run_config
from zeitgeist.api import create_app
from zeitgeist.config import Settings
from zeitgeist.schema import SCHEMA_VERSION
from zeitgeist.store import Store


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
    """The lifespan's only job is to close the store. Deleting the
    `finally: store.close()` would pass every other test in this module,
    none of which enters the client as a context manager itself.
    """
    app = create_app(_settings(tmp_path))

    with TestClient(app) as client:
        client.get("/openapi.json")

    with pytest.raises(sqlite3.ProgrammingError):
        app.state.store._conn.execute("SELECT 1")


def test_seeded_client_runs_the_apps_lifespan(tmp_path):
    """`seeded_client` (tests/api_factory.py) is what every other API test
    module actually builds its client from. If it returned a bare
    `TestClient(create_app(settings))` — the shape it used to have —
    Starlette would never run startup or shutdown, and this would still
    pass every test in this module (they all build their own client) while
    every seeded API test silently ran without ever exercising the
    lifespan, and leaked its store's connection for the process's
    lifetime.
    """
    from tests import api_factory

    client = api_factory.seeded_client(tmp_path)
    store = client.app.state.store

    # api_factory._open_clients is what conftest's autouse fixture drains
    # after the test body finishes; exiting it here, from inside the test,
    # is what proves __exit__ (and therefore the lifespan's shutdown) is
    # reachable at all.
    api_factory._open_clients.remove(client)
    client.__exit__(None, None, None)

    with pytest.raises(sqlite3.ProgrammingError):
        store._conn.execute("SELECT 1")


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


def test_a_run_left_running_by_a_crash_is_interrupted_on_startup(tmp_path):
    """End to end, because the store test alone cannot show that anything
    calls it. A `reconcile_interrupted` that existed but was never wired in
    would pass every test in `test_store.py` and leave the UI polling a dead
    run forever.
    """
    settings = api_settings(tmp_path)
    store = Store(settings.db_path)
    store.init_schema()
    store.start_run("20260905T120000Z", make_run_config())
    store.close()

    client = seeded_client(tmp_path)

    body = client.get("/api/runs/20260905T120000Z").json()
    assert body["run"]["status"] == "interrupted"
