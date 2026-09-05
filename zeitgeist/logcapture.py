"""Two sinks for one run's log, written from the same handler.

The `log_lines` table is what makes the post-mortem block work for a run
that failed last week. The bounded in-memory buffer is what the SSE stream
reads. Both are fed from `emit`, so a line cannot reach one and miss the
other.
"""

import logging
from collections import deque
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime

from zeitgeist.store import Store

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

    Safe as a plain handler because the queue guarantees one run at a time,
    so a second run's handler is never attached simultaneously.
    """

    def __init__(
        self,
        run_id: str,
        buffer: RunLogBuffer,
        store: Store,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> None:
        super().__init__(level=logging.DEBUG)
        self._run_id = run_id
        self._buffer = buffer
        self._store = store
        self._batch_size = batch_size
        self._pending: list[CapturedLine] = []
        # Starts at 1, and is the handler's rather than the database's:
        # two lines can share a timestamp at the resolution recorded here,
        # and the live log's ordering has to be total.
        self._seq = 0

    def emit(self, record: logging.LogRecord) -> None:
        self._seq += 1
        line = CapturedLine(
            seq=self._seq,
            logged_at=datetime.fromtimestamp(record.created, UTC),
            level=record.levelname,
            logger=record.name,
            message=record.getMessage(),
        )
        self._buffer.append(line)
        self._pending.append(line)
        if len(self._pending) >= self._batch_size:
            self.flush()

    def flush(self) -> None:
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

    The `finally` is load-bearing: runs fail, and an abort unwinds through
    here. A handler detached only on the success path would leak onto the
    `zeitgeist` logger for the life of the process the first time a run
    failed, and capture the next run's lines into the previous run's rows.
    """
    buffer = RunLogBuffer(maxlen=maxlen)
    handler = RunLogHandler(run_id, buffer, store, batch_size=batch_size)
    logger = logging.getLogger(LOGGER_NAME)
    # The server always captures at DEBUG and the toggle filters what is
    # *returned*, which is what lets flipping it work retroactively on lines
    # already recorded. A logger left at WARNING would make the toggle a
    # permanent no-op no matter what the endpoint does.
    previous_level = logger.level
    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    try:
        yield buffer
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)
        handler.flush()
