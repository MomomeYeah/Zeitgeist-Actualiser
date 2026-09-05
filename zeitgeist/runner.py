"""The single worker thread that executes runs, and the queue in front of it.

Imports nothing from `zeitgeist.api`: the worker is a pipeline concern the
API drives, not the reverse — the same direction that keeps `store.py` free
of API imports. `RunRequest` is defined here for that reason rather than in
`api/schemas.py`.
"""

import logging
import queue
import threading
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from zeitgeist.config import Settings
from zeitgeist.llm.factory import build_provider
from zeitgeist.logcapture import RunLogBuffer, capture_run_log
from zeitgeist.models import STRICT
from zeitgeist.pipeline import new_run_id, run_pipeline
from zeitgeist.progress import Aborted, CancelToken, NullObserver, RunObserver
from zeitgeist.records import RunError, Stage
from zeitgeist.settings_source import WRITABLE_KEYS
from zeitgeist.sources import build_trend_source
from zeitgeist.store import Store

log = logging.getLogger(__name__)

# What the New run screen offers, and what "Re-run config" reposts. Anything
# outside this cannot be set per run: a request able to write `db_path` or
# `anthropic_api_key` would point a run at another database or hand it a key,
# neither of which is a run option.
RUN_OVERRIDE_KEYS = WRITABLE_KEYS | {
    "llm_provider",
    "llm_model",
    "sources",
    "topic_count",
}

SHUTDOWN = object()


class RunRequest(BaseModel):
    """What to run. `run_id` is set only for a resume, which reuses the
    existing run's checkpoints; a new run gets its id from `new_run_id()`.
    """

    model_config = STRICT

    run_id: str | None = None
    start_at: Stage = Stage.INGEST
    template_ids: list[str] | None = None
    overrides: dict[str, str] = {}


class QueuedRun(BaseModel):
    """`position` 0 means executing now; higher means waiting behind that
    many runs, which is what the "queues it behind" notice reads.
    """

    model_config = STRICT

    run_id: str
    position: int


class ActiveRuns(BaseModel):
    model_config = STRICT

    current: str | None
    queued: list[str]


ExecuteFn = Callable[[Settings, RunRequest, Store, RunObserver, CancelToken], None]


def _execute(
    settings: Settings,
    request: RunRequest,
    store: Store,
    observer: RunObserver,
    token: CancelToken,
) -> None:
    """The real run. Injectable so tests can drive the queue without a
    pipeline, a model or a sleep."""
    run_pipeline(
        settings,
        build_trend_source(settings),
        build_provider(settings),
        store,
        request.run_id or new_run_id(),
        start_at=request.start_at,
        template_ids=request.template_ids,
        observer=observer,
        token=token,
    )


class RunService:
    """One worker thread, one FIFO queue, at most one run executing.

    The worker constructs its own `Store` because `sqlite3` connections are
    thread-bound: the API's and the worker's are separate objects.

    The queue is in-memory. A restart loses queued runs, which for a
    single-user local tool is the right trade against persisting a job table.
    """

    def __init__(self, settings: Settings, *, execute: ExecuteFn | None = None) -> None:
        self._settings = settings
        self._execute = execute or _execute
        self._queue: queue.Queue[Any] = queue.Queue()
        self._thread: threading.Thread | None = None
        # Guards the three dicts below, which the request threads read and
        # the worker writes. Short critical sections only — never held across
        # a run.
        self._lock = threading.Lock()
        self._current: str | None = None
        self._waiting: list[str] = []
        self._tokens: dict[str, CancelToken] = {}
        self._buffers: dict[str, RunLogBuffer] = {}

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._work, name="zeitgeist-runner", daemon=True
        )
        self._thread.start()

    def shutdown(self, timeout: float = 5.0) -> None:
        """Drain what is queued, then stop the worker.

        Called from the app's lifespan. Queued runs execute rather than being
        discarded, because a shutdown that dropped them would look identical
        to one that ran them.
        """
        if self._thread is None:
            return
        self._queue.put(SHUTDOWN)
        self._thread.join(timeout=timeout)
        self._thread = None

    def enqueue(self, request: RunRequest) -> QueuedRun:
        unknown = sorted(set(request.overrides) - RUN_OVERRIDE_KEYS)
        if unknown:
            raise ValueError(f"Not settable per run: {', '.join(unknown)}")

        run_id = request.run_id or new_run_id()
        request = request.model_copy(update={"run_id": run_id})
        with self._lock:
            position = (0 if self._current is None else 1) + len(self._waiting)
            if self._current is not None or self._waiting:
                self._waiting.append(run_id)
            self._tokens[run_id] = CancelToken()
        self._queue.put(request)
        return QueuedRun(run_id=run_id, position=position)

    def active(self) -> ActiveRuns:
        with self._lock:
            return ActiveRuns(current=self._current, queued=list(self._waiting))

    def stop(self, run_id: str) -> bool:
        return self._signal(run_id, lambda token: token.stop_after_stage())

    def abort(self, run_id: str) -> bool:
        return self._signal(run_id, lambda token: token.abort())

    def buffer(self, run_id: str) -> RunLogBuffer | None:
        with self._lock:
            return self._buffers.get(run_id)

    def _signal(self, run_id: str, apply: Callable[[CancelToken], None]) -> bool:
        with self._lock:
            token = self._tokens.get(run_id)
        if token is None:
            return False
        apply(token)
        return True

    def _work(self) -> None:
        store = Store(self._settings.db_path)
        store.init_schema()
        try:
            while True:
                item = self._queue.get()
                if item is SHUTDOWN:
                    return
                self._run_one(item, store)
        finally:
            store.close()

    def _run_one(self, request: RunRequest, store: Store) -> None:
        run_id = request.run_id or new_run_id()
        with self._lock:
            self._current = run_id
            if run_id in self._waiting:
                self._waiting.remove(run_id)
            token = self._tokens[run_id]

        try:
            settings = Settings(
                **(self._settings.model_dump() | dict(request.overrides))
            )
            with capture_run_log(run_id, store) as buffer:
                with self._lock:
                    self._buffers[run_id] = buffer
                self._execute(settings, request, store, NullObserver(), token)
                if token.stopping:
                    self._aborted(store, run_id)
        except Aborted:
            self._aborted(store, run_id)
        except Exception as exc:  # noqa: BLE001 - one run's failure is a row
            log.exception("Run %s failed", run_id)
            store.fail_run(
                run_id,
                RunError(
                    kind=type(exc).__name__,
                    message=str(exc),
                    stage=request.start_at,
                ),
            )
        finally:
            with self._lock:
                self._current = None
                self._buffers.pop(run_id, None)

    def _aborted(self, store: Store, run_id: str) -> None:
        """Stop and abort share `aborted`: `RunStatus` has no separate
        "stopped", and the two differ in what was preserved rather than in
        the label.

        `Store.abort_run` is idempotent on a run that already reached a
        terminal status, which matters because an abort can land after
        `run_pipeline` has already written `ok`.
        """
        store.abort_run(run_id)
