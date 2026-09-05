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

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from zeitgeist.config import Settings
from zeitgeist.runner import ExecuteFn, RunService
from zeitgeist.store import Store

log = logging.getLogger(__name__)


def get_store(request: Request) -> Store:
    """The app's store. Declared as a dependency rather than reached for
    directly so a router never touches `app.state`.
    """
    return request.app.state.store


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_runner(request: Request) -> RunService:
    return request.app.state.runner


def create_app(settings: Settings, *, execute: ExecuteFn | None = None) -> FastAPI:
    # Opened here rather than inside the lifespan: `TestClient` runs the
    # lifespan only when used as a context manager, and two of this task's
    # tests call `create_app` without a client at all. The lifespan's only
    # job is to close it.
    #
    # check_same_thread=False: this Store is held for the app's whole
    # lifetime, but ASGI servers dispatch sync dependencies and sync path
    # operations through a thread pool, and TestClient runs the lifespan's
    # startup/shutdown on its own portal thread — so the connection is
    # legitimately touched from more than one thread. See the parameter's
    # docstring on Store.__init__ for why that is safe for the concurrent
    # reads this phase does — not a blanket guarantee about writes, which
    # phase 3's PUT /api/settings will need to reckon with separately.
    store = Store(settings.db_path, check_same_thread=False)
    store.init_schema()

    interrupted = store.reconcile_interrupted()
    if interrupted:
        log.info(
            "Marked %d run(s) interrupted after an unclean shutdown: %s",
            len(interrupted),
            ", ".join(interrupted),
        )

    # The same Store as app.state.store, not a second connection: enqueue
    # opens a run's row on the request thread, through this Store, before
    # the client is ever handed the id — see RunService's docstring.
    runner = RunService(settings, store, execute=execute)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # The worker thread starts here rather than in `create_app`, unlike
        # the store: an app that is built and never entered — which two tests
        # in test_api_app.py do deliberately — must not leave a live thread
        # behind.
        runner.start()
        try:
            yield
        finally:
            runner.shutdown()
            store.close()

    app = FastAPI(title="Zeitgeist", lifespan=lifespan)
    app.state.store = store
    app.state.settings = settings
    app.state.runner = runner

    from zeitgeist.api import control as control_router
    from zeitgeist.api import options as options_router
    from zeitgeist.api import renders as renders_router
    from zeitgeist.api import runs as runs_router
    from zeitgeist.api import settings as settings_router
    from zeitgeist.api import topics as topics_router

    # control.router owns POST /api/runs and GET /api/runs/active; it must
    # be mounted before runs.router, which owns GET /api/runs/{run_id} — a
    # path parameter that would otherwise capture "active" and 404 it as an
    # unknown run.
    app.include_router(control_router.router)
    app.include_router(settings_router.router)
    app.include_router(runs_router.router)
    app.include_router(renders_router.router)
    app.include_router(topics_router.router)
    app.include_router(options_router.router)

    return app
