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
    """
    store = _store(tmp_path)
    store.start_run("r1", make_run_config())
    log = logging.getLogger("zeitgeist.testing.threaded")
    done = threading.Event()

    with capture_run_log("r1", store) as buffer:

        def worker() -> None:
            log.info("from the worker")
            done.set()

        thread = threading.Thread(target=worker)
        thread.start()
        assert done.wait(timeout=5)
        thread.join(timeout=5)

        assert [line.message for line in buffer.since(0)] == ["from the worker"]
