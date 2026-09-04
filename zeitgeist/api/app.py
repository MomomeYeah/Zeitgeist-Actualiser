"""The FastAPI app and the two dependencies every router uses.

The factory takes `Settings` rather than building its own so a test can
point it at `tmp_path`. A factory that reached for the ambient database
would make the suite's result depend on whether the tool had been run
locally, which is the hermeticity problem `conftest` already guards against
for `Settings` itself.

One `Store` for the app's lifetime rather than one per request: `sqlite3`
connections are thread-bound, reads need no isolation from each other, and
phase 3's worker thread constructs its own connection anyway.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from zeitgeist.config import Settings
from zeitgeist.store import Store


def get_store(request: Request) -> Store:
    """The app's store. Declared as a dependency rather than reached for
    directly so a router never touches `app.state`.
    """
    return request.app.state.store


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def create_app(settings: Settings) -> FastAPI:
    # Opened here rather than inside the lifespan: `TestClient` runs the
    # lifespan only when used as a context manager, and two of this task's
    # tests call `create_app` without a client at all. The lifespan's only
    # job is to close it.
    store = Store(settings.db_path)
    store.init_schema()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            store.close()

    app = FastAPI(title="Zeitgeist", lifespan=lifespan)
    app.state.store = store
    app.state.settings = settings
    return app
