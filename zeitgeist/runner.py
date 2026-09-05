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
from zeitgeist.records import RunConfig, RunError, Stage
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


class RunAlreadyActive(ValueError):
    """`enqueue` refuses a `run_id` that is already `_current`, in
    `_waiting`, or in `_tokens` — a duplicate resume, or a double-clicked
    Resume button.

    A `ValueError` subclass rather than a fresh base: a caller that only
    catches `ValueError` still gets a 4xx instead of a 500, while
    `resume_run` and `POST /api/runs` can each catch this one specifically,
    ahead of the generic `ValueError`, to give it its own status code.
    """


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


class _StageTracker(NullObserver):
    """Records the last stage `stage_started` reported.

    `RunError.stage` must name where a run *died*, not where it *started*:
    `request.start_at` is the latter, and a run that starts at ingest and
    fails in generate must not be recorded as failing in ingest. Subclassing
    `NullObserver` rather than proxying with `__getattr__` because `ty` will
    not accept a `__getattr__` proxy as a `RunObserver`.
    """

    def __init__(self) -> None:
        self.last_stage: Stage | None = None

    def stage_started(self, stage: Stage) -> None:
        self.last_stage = stage


class RunService:
    """One worker thread, one FIFO queue, at most one run executing.

    The worker constructs its own `Store` because `sqlite3` connections are
    thread-bound: the API's and the worker's are separate objects. `store`
    is a *third*, distinct role — the API's own long-lived, `check_same_
    thread=False` connection (see `zeitgeist.api.app.create_app`), reused
    here rather than opened again, so `enqueue` can open a run's row on
    whichever request thread calls it, before the id is ever handed back.
    Without that, no `run_records` row exists until the worker actually
    dequeues the request, and a client holding a freshly queued id 404s on
    both its detail page and its event stream in the meantime.

    The queue is in-memory. A restart loses queued runs, which for a
    single-user local tool is the right trade against persisting a job table.
    """

    def __init__(
        self,
        settings: Settings,
        store: Store,
        *,
        execute: ExecuteFn | None = None,
        worker_store: Callable[[], Store] | None = None,
    ) -> None:
        self._settings = settings
        self._store = store
        self._execute = execute or _execute
        # Injectable for the same reason `execute` is: a test that needs
        # the worker's own connection to misbehave in a controlled way
        # (see test_runner.py's coverage of _work's except/finally) has no
        # other seam to reach it through, since _work always builds this
        # itself rather than taking it as a constructor argument.
        self._worker_store = worker_store or (lambda: Store(self._settings.db_path))
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
        """Ask the worker to stop after finishing what is already queued,
        and wait up to `timeout` for it to get there.

        Called from the app's lifespan. The sentinel is put onto the same
        FIFO queue, so anything already queued is *offered the chance* to
        run first — but at the default 5 second timeout that is aspirational
        for any real run, which takes minutes: `join` will typically time
        out while the worker is still mid-run, this call returns anyway, and
        the worker (a daemon thread) is killed outright at interpreter exit
        with whatever it was doing — including any run still queued behind
        it — left undone. Its row stays `running`; the next startup's
        reconciliation marks it `interrupted`, which is the correct story
        for a run that was cut off mid-flight.

        If the worker is still alive after the join, `_thread` is left set
        so a later `start()` cannot spawn a second worker onto the same
        queue while the first is still running.
        """
        if self._thread is None:
            return
        self._queue.put(SHUTDOWN)
        self._thread.join(timeout=timeout)
        if self._thread.is_alive():
            log.warning(
                "Worker did not stop within %.1fs of shutdown; leaving it running",
                timeout,
            )
            return
        self._thread = None

    def enqueue(self, request: RunRequest) -> QueuedRun:
        unknown = sorted(set(request.overrides) - RUN_OVERRIDE_KEYS)
        if unknown:
            raise ValueError(f"Not settable per run: {', '.join(unknown)}")
        # Validate on the request thread, before a run_id is ever issued. A
        # bad override (an unknown source, a non-numeric topic_count) raises
        # ValueError here, which the endpoint turns into a 4xx — and the
        # built Settings is also what freezes the row opened below.
        settings = self._build_settings(request.overrides)

        run_id = request.run_id or new_run_id()
        request = request.model_copy(update={"run_id": run_id})
        with self._lock:
            if (
                run_id == self._current
                or run_id in self._waiting
                or run_id in self._tokens
            ):
                # A duplicate enqueue of a live run: resuming twice, or a
                # double-clicked Resume button. Refusing here — rather than
                # the old unconditional self._tokens[run_id] = CancelToken(),
                # which silently replaced the live token — is what stops two
                # failures at once: the replacement token orphans the one
                # stop/abort still reach, so a still-executing run becomes
                # impossible to stop; and a second dequeue of the same
                # run_id would find its own entry already removed from
                # _waiting, its token already gone from _tokens (see
                # _run_one's finally), and raise KeyError before _run_one's
                # own try began — leaving _current stuck on this run_id
                # forever, since the finally that clears it never runs.
                raise RunAlreadyActive(f"Run {run_id} is already queued or executing")
            # Appended unconditionally, and *before* the worker can possibly
            # have caught up to this request: between this put() and the
            # worker's own lock acquisition in _run_one, the request is in
            # flight but must still be visible to active()/enqueue's own
            # position math, or two POSTs landing in that window both see
            # "nothing running, nothing waiting" and both report position 0.
            # _run_one removes this entry once it becomes _current.
            position = (0 if self._current is None else 1) + len(self._waiting)
            self._waiting.append(run_id)
            self._tokens[run_id] = CancelToken()
        # Opened here, on the request thread, rather than left for _run_one
        # to open on the worker thread: a client holding this id must be
        # able to GET /api/runs/{run_id} and open its event stream
        # immediately, not only once the worker actually dequeues it.
        # RunStatus has no "queued" state, so this uses "running" like
        # every other open row — startup reconciliation already turns a
        # "running" row left over from a dead process into "interrupted",
        # which is the right story for one that never got past the queue
        # either. Store.start_run is an upsert that leaves `started_at`
        # untouched on a second call (see _run_one), so the two calls
        # below — this one, then _run_one's, then run_pipeline's own —
        # all agree on when the run "started" as this first one.
        self._store.start_run(run_id, RunConfig.freeze(settings, request.template_ids))
        self._queue.put(request)
        return QueuedRun(run_id=run_id, position=position)

    def _build_settings(self, overrides: dict[str, str]) -> Settings:
        """Build the per-run `Settings`: this service's own settings for
        everything not run-settable, the request's overrides for what is.

        Only the fields *outside* `RUN_OVERRIDE_KEYS` are taken from this
        snapshot. Those are the fields a run cannot set for itself — `db_path`,
        `output_dir`, `anthropic_api_key` and the rest — and the API's own
        `Settings` may carry programmatic values for them that must survive.
        Splatting *every* field here, as this service's own settings, would
        pin every run-settable field at its value from RunService's own
        construction: `init_settings` outranks everything else in
        `Settings.settings_customise_sources`, so a value written to the
        settings table afterwards (`PUT /api/settings`) would never reach a
        run started later. Leaving those fields out lets them resolve
        through the normal precedence chain instead, picking up the table's
        current value when the request itself doesn't override them.

        Building a fresh `Settings` rather than `model_copy(update=...)`,
        which bypasses validation entirely: `"9"` would stay the string
        `"9"` for `topic_count`, with no error raised anywhere. Constructing
        instead runs the overrides through pydantic as constructor
        arguments — the highest-precedence layer, which is exactly what a
        per-run override should be — so they arrive coerced to the right
        type, and an invalid one (an unknown source, a non-numeric count)
        raises `ValueError` here.
        """
        snapshot = self._settings.model_dump(exclude=set(RUN_OVERRIDE_KEYS))
        return Settings(**(snapshot | dict(overrides)))

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
        store = self._worker_store()
        store.init_schema()
        try:
            while True:
                item = self._queue.get()
                if item is SHUTDOWN:
                    return
                try:
                    self._run_one(item, store)
                except Exception:  # noqa: BLE001 - the loop must outlive this
                    # _run_one's own exception handlers call the store
                    # directly (abort_run, fail_run), and either can raise
                    # something _run_one does not itself catch — its
                    # `finally` still runs first, since a `finally` always
                    # does, but the exception then propagates here. Without
                    # this handler that would kill the thread: active()
                    # would report a stale _current forever, every later
                    # enqueue would never be picked up, and shutdown would
                    # find nothing to join cleanly.
                    log.exception("Worker loop swallowed an unhandled error")
        finally:
            store.close()

    def _run_one(self, request: RunRequest, store: Store) -> None:
        run_id = request.run_id or new_run_id()
        with self._lock:
            self._current = run_id
            if run_id in self._waiting:
                self._waiting.remove(run_id)

        stage_tracker = _StageTracker()
        try:
            # setdefault, not self._tokens[run_id]: the latter raised
            # KeyError for a request with no pre-registered token (only
            # possible by bypassing enqueue entirely), and it raised it
            # *before* this try began — so the `finally` below never ran,
            # `_current` stayed pinned to this run_id forever, and every
            # later enqueue()'d run would sit behind a "current" run that
            # was not actually executing. Moving the lookup in here, using
            # setdefault, means the only bookkeeping now able to run before
            # `try` is the lock-protected block above — plain dict/list
            # operations on state this method already owns, which do not
            # raise — so `finally` is now unconditionally reached and
            # `_current` is always cleared.
            with self._lock:
                token = self._tokens.setdefault(run_id, CancelToken())
            settings = self._build_settings(request.overrides)
            # Opened before _execute, not inside it: build_trend_source and
            # build_provider (called from the default _execute) can raise —
            # a dormant/unknown source or a bad provider config — and
            # everything before this line runs before any row exists on
            # *this* connection. store.fail_run below is `UPDATE ... WHERE
            # run_id = ?`, a silent no-op against a row that was never
            # opened.
            #
            # This is actually the *second* open of this row: enqueue
            # already opened it, on the request thread, through the API's
            # own Store, so the client has had something to GET since
            # before this method ever ran. run_pipeline calls start_run a
            # third time with the same (run_id, config) pair. All three are
            # upserts keyed on run_id (see Store.start_run), and none but
            # the first touches `started_at` — its `DO UPDATE SET` omits
            # that column, so a second or third call only refreshes
            # `status`/`config` back to "running" and clears the previous
            # attempt's outcome columns to NULL. There is no previous
            # outcome yet on a fresh run, so this call's result is
            # identical to the row enqueue already wrote.
            store.start_run(run_id, RunConfig.freeze(settings, request.template_ids))
            with capture_run_log(run_id, store) as buffer:
                with self._lock:
                    self._buffers[run_id] = buffer
                self._execute(settings, request, store, stage_tracker, token)
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
                    stage=stage_tracker.last_stage or request.start_at,
                ),
            )
        finally:
            with self._lock:
                self._current = None
                self._buffers.pop(run_id, None)
                self._tokens.pop(run_id, None)

    def _aborted(self, store: Store, run_id: str) -> None:
        """Stop and abort share `aborted`: `RunStatus` has no separate
        "stopped", and the two differ in what was preserved rather than in
        the label.

        `Store.abort_run` is idempotent on a run that already reached a
        terminal status, which matters because an abort can land after
        `run_pipeline` has already written `ok`.
        """
        store.abort_run(run_id)
