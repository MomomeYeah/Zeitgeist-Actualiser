"""Two sinks for one run's log, written from the same handler.

The `log_lines` table is what makes the post-mortem block work for a run
that failed last week. The bounded in-memory buffer is what the SSE stream
reads. Both are fed from `emit`, so a line cannot reach one and miss the
other.
"""

import logging
import threading
from collections import deque
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime

from zeitgeist.store import Store

log = logging.getLogger(__name__)

LOGGER_NAME = "zeitgeist"
DEFAULT_MAXLEN = 2000
DEFAULT_BATCH_SIZE = 50


@dataclass(frozen=True)
class CapturedLine:
    """One captured line. Structurally identical to `records.LogLine`, which
    is what the store reads back — kept separate so `logcapture` depends on
    `store` and never the reverse.
    """

    seq: int
    logged_at: datetime
    level: str
    logger: str
    message: str


class RunLogBuffer:
    """The seam between the worker thread and the event loop.

    A `deque` with a `maxlen`: `append` and `popleft` are atomic under the
    GIL, so the handler writes from the worker while the SSE generator reads
    from the loop with no lock. Deliberately holds no reference to any event
    loop — `loop.call_soon_threadsafe` into an `asyncio.Queue` would couple
    the handler to a running loop, and the same handler has to work under
    `TestClient` and under the dev harness. A quarter-second of polling
    latency on a log line is invisible.
    """

    def __init__(self, maxlen: int = DEFAULT_MAXLEN) -> None:
        self._lines: deque[CapturedLine] = deque(maxlen=maxlen)

    def append(self, line: CapturedLine) -> None:
        self._lines.append(line)

    def since(self, seq: int) -> list[CapturedLine]:
        """Every held line after `seq`.

        A client whose `seq` was evicted gets what is still held rather than
        nothing: returning nothing would stall it forever on a sequence
        number that will never come back.
        """
        return [line for line in tuple(self._lines) if line.seq > seq]


class RunLogHandler(logging.Handler):
    """Writes one run's lines to a buffer and, in batches, to the store.

    Attached to the `"zeitgeist"` logger for a run's whole duration (see
    `capture_run_log`), which means *any* code under that namespace logging
    from *any* thread reaches `emit` while a run is in flight — not only the
    thread that entered `capture_run_log`. That is not a narrow case:
    `distil_topics`'s `_distil_one` (`zeitgeist/analysis/distil.py`) runs on
    a `ThreadPoolExecutor`, so every "Distilling %r" and "Distilled %r in
    %.1fs" DEBUG line — the only visibility
    `GET /api/runs/{id}/log?verbose=true` has into the analyse stage — is
    logged from a pool thread, never the thread that entered
    `capture_run_log`.

    An earlier version of this handler dropped every record whose thread
    did not match the one that constructed it. That guarded against the
    wrong thing: the actual hazard was writing through a `Store` opened
    `check_same_thread=True` (sqlite3's default, and what the worker's own
    `Store` uses) from a thread that did not open it, which raises
    `sqlite3.ProgrammingError`. Pool threads spawned *by the run* are
    legitimately part of it; dropping their lines silently discarded real
    diagnostics rather than fixing the actual problem. The fix is a `Store`
    of this handler's own, opened `check_same_thread=False`
    (`capture_run_log` opens it and owns closing it) — the same pattern
    `zeitgeist/api/app.py` already uses for its long-lived,
    multi-thread-touched `Store`.

    `Store.__init__`'s docstring on `check_same_thread` says why that is
    safe here: every public `Store` method holds that store's lock for its
    whole body, so two threads calling `flush` at once write one batch
    after the other rather than racing the connection's one transaction.
    SQLite's own serialized mode is not enough on its own — see that
    docstring for what a real run showed without the lock.

    The one real trade-off left by capturing every thread rather than only
    the owner: a request thread logging under the `zeitgeist` namespace
    while a run happens to be in flight now has its line captured into
    *that run's* log. `zeitgeist/llm/registry.py:59` is the one known case
    — a debug line logged on the request thread handling
    `GET /api/config/options` when Ollama is unreachable. That is a
    cosmetic oddity in a log; losing the analyse stage's diagnostics, which
    is what the thread filter did, was a functional loss. The trade is
    deliberate.
    """

    def __init__(
        self,
        run_id: str,
        buffer: RunLogBuffer,
        store: Store,
        batch_size: int = DEFAULT_BATCH_SIZE,
        after_seq: int = 0,
    ) -> None:
        super().__init__(level=logging.DEBUG)
        self._run_id = run_id
        self._buffer = buffer
        self._store = store
        self._batch_size = batch_size
        self._pending: list[CapturedLine] = []
        # The handler's rather than the database's: two lines can share a
        # timestamp at the resolution recorded here, and the live log's
        # ordering has to be total. Starts after `after_seq` — the last line
        # a previous attempt at this run recorded, 0 for a fresh run — so a
        # resume continues the numbering rather than colliding with it.
        self._seq = after_seq
        # Guards `_seq` and `_pending` only — never held across the store
        # write in `flush`. Matters more now than it used to: with no
        # thread filter ahead of it, every thread logging under the
        # namespace reaches here, so a `_seq` read-modify-write or a
        # `_pending` swap racing an `append` is real contention, not a
        # foreign-thread-only theoretical.
        self._lock = threading.Lock()

    def emit(self, record: logging.LogRecord) -> None:
        with self._lock:
            self._seq += 1
            seq = self._seq
            line = CapturedLine(
                seq=seq,
                logged_at=datetime.fromtimestamp(record.created, UTC),
                level=record.levelname,
                logger=record.name,
                message=record.getMessage(),
            )
            self._buffer.append(line)
            self._pending.append(line)
            should_flush = len(self._pending) >= self._batch_size
        if should_flush:
            self.flush()

    def flush(self) -> None:
        with self._lock:
            if not self._pending:
                return
            batch, self._pending = self._pending, []
        self._store.write_log_lines(self._run_id, batch)


@contextmanager
def capture_run_log(
    run_id: str,
    store: Store,
    *,
    maxlen: int = DEFAULT_MAXLEN,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> Iterator[RunLogBuffer]:
    """Attach a handler for one run's duration, and detach it after.

    `store` is used only to find the database's path (`store.path`) — the
    handler never writes through the caller's own connection. A second
    connection is opened here instead, `check_same_thread=False`, because
    `emit` can now be reached from any thread logging under the
    `zeitgeist` namespace (see `RunLogHandler`'s docstring), and the
    caller's `store` is typically the worker's own, opened
    `check_same_thread=True`.

    The two `finally`s are load-bearing, one each. The inner one detaches
    the handler: runs fail, and an abort unwinds through here, so a handler
    detached only on the success path would leak onto the `zeitgeist`
    logger for the life of the process the first time a run failed, and
    capture the next run's lines into the previous run's rows. The outer
    one closes the dedicated connection, which has to happen on every path
    — including a failure reading `last_log_seq` before the handler even
    exists, which is why the connection's `try` starts the moment it is
    opened — or it leaks one open `sqlite3` connection per run for the
    life of the process.

    The last flush cannot fail the run. It runs after the pipeline has
    already written the run's terminal status, and an error escaping from
    here reached the worker's `except Exception`, whose `Store.fail_run`
    has no `status = 'running'` guard — so a run that had rendered every
    meme was recorded as failed. It also skipped the close. A lost batch
    of log lines is reported, as an error on this module's own logger
    (the handler is detached by then, so the report cannot recurse into
    it), and the run keeps the status it earned.
    """
    buffer = RunLogBuffer(maxlen=maxlen)
    log_store = Store(store.path, check_same_thread=False)
    try:
        handler = RunLogHandler(
            run_id,
            buffer,
            log_store,
            batch_size=batch_size,
            after_seq=log_store.last_log_seq(run_id),
        )
        logger = logging.getLogger(LOGGER_NAME)
        # The server always captures at DEBUG and the toggle filters what is
        # *returned*, which is what lets flipping it work retroactively on
        # lines already recorded. A logger left at WARNING would make the
        # toggle a permanent no-op no matter what the endpoint does.
        previous_level = logger.level
        logger.setLevel(logging.DEBUG)
        logger.addHandler(handler)
        try:
            yield buffer
        finally:
            logger.removeHandler(handler)
            logger.setLevel(previous_level)
            try:
                handler.flush()
            except Exception:  # noqa: BLE001 - the run's status outranks its log
                log.exception("Could not write the last log lines for run %s", run_id)
    finally:
        log_store.close()
