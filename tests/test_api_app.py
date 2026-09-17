import sqlite3

import pytest
from fastapi.testclient import TestClient

from tests.api_factory import api_db_path, app_of, seeded_client
from tests.run_factory import make_run_config
from zeitgeist.api import create_app
from zeitgeist.config import Settings
from zeitgeist.schema import SCHEMA_VERSION
from zeitgeist.store import DB_PATH, Store


def _settings(tmp_path) -> Settings:
    return Settings(
        output_dir=tmp_path / "output",
    )


def test_the_app_serves_its_openapi_schema(tmp_path):
    """The schema is the contract phase 5 generates its client from, so it
    has to be reachable before any endpoint exists."""
    client = TestClient(
        create_app(_settings(tmp_path), db_path=tmp_path / "data" / "z.db")
    )

    response = client.get("/openapi.json")

    assert response.status_code == 200
    assert "paths" in response.json()


def test_the_app_opens_the_database_it_was_given(tmp_path):
    """Not the ambient one. A factory that reached for `data/zeitgeist.db`
    would make every test depend on whether the tool had been run locally."""
    settings = _settings(tmp_path)

    create_app(settings, db_path=tmp_path / "data" / "z.db")

    assert (tmp_path / "data" / "z.db").is_file()


def test_create_app_opens_its_database_at_the_path_it_is_given(tmp_path):
    """The path is a parameter of the factory, not a field of Settings.

    `nested/` does not exist beforehand: `Store.__init__` creates the parent,
    and a test that pre-created it would pass even if the path were ignored
    in favour of the `data/` default.
    """
    path = tmp_path / "nested" / "z.db"
    app = create_app(Settings(), db_path=path)
    try:
        assert app.state.store.path == path
        assert path.is_file()
    finally:
        app.state.store.close()


def test_create_app_defaults_to_the_database_the_constant_names(tmp_path, monkeypatch):
    """No `db_path` argument, so the factory must resolve `DB_PATH` itself.

    `DB_PATH` is relative, so `chdir` keeps this hermetic while still
    exercising the real default. Asserted on the file that appears rather
    than on the signature object: a factory that declared the default and
    then opened somewhere else leaves `tmp_path/data/zeitgeist.db` missing,
    which introspecting `inspect.signature` would never notice.
    """
    monkeypatch.chdir(tmp_path)

    app = create_app(Settings())
    try:
        assert app.state.store.path == DB_PATH
        assert (tmp_path / "data" / "zeitgeist.db").is_file()
    finally:
        app.state.store.close()


def test_the_app_closes_its_store_when_it_shuts_down(tmp_path):
    """The lifespan's only job is to close the store. Deleting the
    `finally: store.close()` would pass every other test in this module,
    none of which enters the client as a context manager itself.
    """
    app = create_app(_settings(tmp_path), db_path=tmp_path / "data" / "z.db")

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
    store = app_of(client).state.store

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
    create_app(_settings(tmp_path), db_path=tmp_path / "data" / "z.db")

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
    store = Store(api_db_path(tmp_path))
    store.init_schema()
    store.start_run("20260905T120000Z", make_run_config())
    store.close()

    client = seeded_client(tmp_path)

    body = client.get("/api/runs/20260905T120000Z").json()
    assert body["run"]["status"] == "interrupted"
