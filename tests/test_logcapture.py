import logging
import threading
from datetime import UTC, datetime

from tests.run_factory import make_run_config
from zeitgeist.logcapture import CapturedLine, RunLogBuffer, capture_run_log
from zeitgeist.store import Store


def _store(tmp_path) -> Store:
    store = Store(tmp_path / "z.db")
    store.init_schema()
    return store


class _CountingStore(Store):
    """Records the size of each batch handed to `write_log_lines`.

    A subclass rather than an assignment over the instance method: assigning
    needs a `type: ignore[method-assign]` that the project's suppression rule
    would then have to justify, and the override still calls `super()`, so
    every row really is written and the rows themselves stay assertable.
    """

    def __init__(self, path) -> None:
        super().__init__(path)
        self.batches: list[int] = []

    def write_log_lines(self, run_id: str, lines) -> None:
        self.batches.append(len(lines))
        super().write_log_lines(run_id, lines)


def _line(seq: int, message: str = "hello") -> CapturedLine:
    return CapturedLine(
        seq=seq,
        logged_at=datetime(2026, 9, 5, 12, tzinfo=UTC),
        level="INFO",
        logger="zeitgeist.pipeline",
        message=message,
    )


def test_the_buffer_returns_only_lines_after_the_given_seq():
    """The SSE generator polls with the last seq it sent. A `since` that
    returned everything would resend the whole log every quarter second, and
    the browser would render duplicates for the life of the run.
    """
    buffer = RunLogBuffer(maxlen=10)
    for seq in (1, 2, 3):
        buffer.append(_line(seq))

    assert [line.seq for line in buffer.since(1)] == [2, 3]


def test_the_buffer_drops_the_oldest_lines_when_it_is_full():
    """Bounded on purpose: a DEBUG run emits several hundred lines and the
    buffer lives for the run's duration. Unbounded, a long run's buffer would
    grow without limit in a process that is also serving requests.
    """
    buffer = RunLogBuffer(maxlen=2)
    for seq in (1, 2, 3):
        buffer.append(_line(seq))

    assert [line.seq for line in buffer.since(0)] == [2, 3]


def test_a_client_that_missed_evicted_lines_still_advances():
    """A slow client asks for everything after seq 1 when the buffer has
    already evicted through seq 5. Returning nothing would stall it forever
    on a seq that will never come back; it must get what is still held.
    """
    buffer = RunLogBuffer(maxlen=2)
    for seq in (1, 2, 3, 4, 5):
        buffer.append(_line(seq))

    assert [line.seq for line in buffer.since(1)] == [4, 5]


def test_captured_lines_reach_both_the_buffer_and_the_table(tmp_path):
    """The two sinks exist for different readers — the table for a run that
    failed last week, the buffer for the stream watching one now — and both
    are fed from the same `emit`. An implementation writing only one would
    pass whichever half of the suite tested the other.
    """
    store = _store(tmp_path)
    store.start_run("r1", make_run_config())
    log = logging.getLogger("zeitgeist.testing.capture")

    with capture_run_log("r1", store) as buffer:
        log.info("first")
        log.info("second")

    assert [line.message for line in buffer.since(0)] == ["first", "second"]
    assert [line.message for line in store.log_lines("r1", verbose=True)] == [
        "first",
        "second",
    ]


def test_lines_are_written_in_batches_rather_than_one_row_at_a_time(tmp_path):
    """A DEBUG run emits several hundred lines and a transaction each would
    be gratuitous. This pins the batching by counting writes: an
    implementation flushing per record would pass every content assertion
    above while doing 200 transactions.
    """
    store = _CountingStore(tmp_path / "z.db")
    store.init_schema()
    store.start_run("r1", make_run_config())
    log = logging.getLogger("zeitgeist.testing.batch")

    with capture_run_log("r1", store, batch_size=5):
        for index in range(12):
            log.info("line %d", index)

    assert max(store.batches) > 1
    assert sum(store.batches) == 12
    assert [line.message for line in store.log_lines("r1", verbose=True)] == [
        f"line {index}" for index in range(12)
    ]


def test_the_handler_detaches_when_the_run_ends(tmp_path):
    """One run at a time is what makes a plain handler safe. A handler left
    attached would capture the *next* run's lines into the previous run's
    rows — and worse, keep a closed `Store` alive after the worker moved on.
    """
    store = _store(tmp_path)
    store.start_run("r1", make_run_config())
    log = logging.getLogger("zeitgeist.testing.detach")

    with capture_run_log("r1", store):
        log.info("during")
    log.info("after")

    assert [line.message for line in store.log_lines("r1", verbose=True)] == ["during"]


def test_the_handler_detaches_even_when_the_run_raises(tmp_path):
    """Runs fail, and an abort unwinds through here. A handler detached only
    on the success path would leak onto the logger for the life of the
    process the first time a run failed.
    """
    store = _store(tmp_path)
    store.start_run("r1", make_run_config())
    log = logging.getLogger("zeitgeist.testing.raising")
    before = len(logging.getLogger("zeitgeist").handlers)

    try:
        with capture_run_log("r1", store):
            log.info("during")
            raise RuntimeError("boom")
    except RuntimeError:
        pass

    assert len(logging.getLogger("zeitgeist").handlers) == before
    assert [line.message for line in store.log_lines("r1", verbose=True)] == ["during"]


def test_debug_lines_are_captured_so_the_toggle_can_filter_them(tmp_path):
    """The server always captures at DEBUG and the toggle filters what is
    *returned* — that is what makes flipping it work retroactively on lines
    already recorded. A handler set to INFO would make the toggle a
    permanent no-op no matter what the endpoint does.
    """
    store = _store(tmp_path)
    store.start_run("r1", make_run_config())
    log = logging.getLogger("zeitgeist.testing.level")

    with capture_run_log("r1", store):
        log.debug("quiet")
        log.info("loud")

    assert [line.level for line in store.log_lines("r1", verbose=True)] == [
        "DEBUG",
        "INFO",
    ]
    assert [line.level for line in store.log_lines("r1", verbose=False)] == ["INFO"]


def test_lines_written_from_a_worker_thread_are_visible_to_the_reader(tmp_path):
    """The buffer is the seam between the worker thread and the event loop:
    the handler appends on the worker, the SSE generator reads from the loop.
    A buffer using thread-local state, or one built per reader, would pass
    every single-threaded test here and stream nothing during a real run.

    `capture_run_log` is entered *on* the spawned thread here, not the main
    one — and so is the `Store` it wraps, for the same reason `RunService`'s
    worker builds its own rather than reusing one built elsewhere: a
    `sqlite3` connection is thread-bound, so a `Store` built on the main
    thread would itself raise when this handler's `flush` reached it from
    the worker. In production the worker thread does both: it enters the
    context manager and then runs the pipeline synchronously on itself, and
    the handler only ever captures records from that one thread. Entering
    the context manager on the main thread and logging from a second,
    unrelated thread — as this test used to — is exactly the foreign-thread
    case the guard drops, and would make this assertion fail for the wrong
    reason.
    """
    log = logging.getLogger("zeitgeist.testing.threaded")
    entered = threading.Event()
    release = threading.Event()
    buffers: list[RunLogBuffer] = []

    def worker() -> None:
        store = _store(tmp_path)
        store.start_run("r1", make_run_config())
        with capture_run_log("r1", store) as buffer:
            buffers.append(buffer)
            log.info("from the worker")
            entered.set()
            assert release.wait(timeout=5)

    thread = threading.Thread(target=worker)
    thread.start()
    assert entered.wait(timeout=5)

    # Read from the main thread while the worker thread still holds the
    # handler open — the buffer itself must tolerate that, even though the
    # handler no longer accepts writes from any thread but the worker's.
    assert [line.message for line in buffers[0].since(0)] == ["from the worker"]

    release.set()
    thread.join(timeout=5)


def test_a_record_from_a_foreign_thread_is_dropped_without_raising(tmp_path):
    """Critical 1: `llm/registry.py` logs on a request thread while a run's
    handler happens to be attached to the `zeitgeist` logger. Before the
    thread guard, `emit` would try to flush that line through the worker's
    thread-bound `Store` from the foreign thread and raise
    `sqlite3.ProgrammingError` — a 500 out of a read-only endpoint that has
    nothing to do with the run. It must instead be silently dropped: not
    captured, and no exception escapes the foreign thread either.
    """
    store = _store(tmp_path)
    store.start_run("r1", make_run_config())
    log = logging.getLogger("zeitgeist.testing.foreign")
    raised: list[BaseException] = []

    with capture_run_log("r1", store) as buffer:

        def foreign() -> None:
            try:
                log.info("from a foreign thread")
            except BaseException as exc:  # noqa: BLE001 - proving nothing escapes
                raised.append(exc)

        thread = threading.Thread(target=foreign)
        thread.start()
        thread.join(timeout=5)

        log.info("from the owner")

    assert raised == []
    assert [line.message for line in buffer.since(0)] == ["from the owner"]
    assert [line.message for line in store.log_lines("r1", verbose=True)] == [
        "from the owner"
    ]


def test_concurrent_foreign_noise_leaves_the_owners_seq_unique_and_increasing(
    tmp_path,
):
    """`_seq` is an unguarded read-modify-write and `flush`'s batch swap
    races an `append` if either runs without the lock: two emits landing on
    `_seq` at once could hand out the same number twice, which is an
    `IntegrityError` against `log_lines`' `(run_id, seq)` primary key.

    Several foreign threads hammer `emit` throughout, concurrently with the
    owner thread logging its own 200 lines — real contention on the
    handler's internal state, not simulated. The foreign lines must all be
    dropped (proven by the exact count and content below) and the owner's
    own sequence numbers must come out as a gapless, duplicate-free run —
    proof the lock, and the thread guard ahead of it, both hold up under
    load rather than merely in the single-threaded case.
    """
    store = _store(tmp_path)
    store.start_run("r1", make_run_config())
    log = logging.getLogger("zeitgeist.testing.concurrent")
    owner_count = 200
    stop = threading.Event()

    def foreign_noise() -> None:
        while not stop.is_set():
            log.info("noise")

    with capture_run_log("r1", store, batch_size=11) as buffer:
        noise_threads = [threading.Thread(target=foreign_noise) for _ in range(4)]
        for thread in noise_threads:
            thread.start()
        for index in range(owner_count):
            log.info("owner %d", index)
        stop.set()
        for thread in noise_threads:
            thread.join(timeout=5)

    lines = buffer.since(0)
    assert [line.message for line in lines] == [
        f"owner {index}" for index in range(owner_count)
    ]
    assert [line.seq for line in lines] == list(range(1, owner_count + 1))
    stored = store.log_lines("r1", verbose=True)
    assert [line.message for line in stored] == [
        f"owner {index}" for index in range(owner_count)
    ]
    assert [line.seq for line in stored] == list(range(1, owner_count + 1))
