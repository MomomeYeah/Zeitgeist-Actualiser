import logging
import threading
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from unittest.mock import patch

from tests.run_factory import make_run_config
from zeitgeist.logcapture import CapturedLine, RunLogBuffer, capture_run_log
from zeitgeist.store import Store


def _store(tmp_path) -> Store:
    store = Store(tmp_path / "z.db")
    store.init_schema()
    return store


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
    above while doing 12 transactions.

    Patches `Store.write_log_lines` at the class level rather than
    subclassing the `store` handed to `capture_run_log`, the way this test
    used to: the handler now writes through its own dedicated `Store`,
    opened internally by `capture_run_log` from `store.path` (see its
    docstring), never the instance the caller passes in — so a subclass
    instance handed in here would never be the object whose
    `write_log_lines` actually runs. Patching the class instead catches
    the call regardless of which instance makes it, and delegating to the
    original implementation still runs the real write, so the rows stay
    assertable exactly as before.
    """
    store = _store(tmp_path)
    store.start_run("r1", make_run_config())
    log = logging.getLogger("zeitgeist.testing.batch")
    batches: list[int] = []
    original = Store.write_log_lines

    def counting(self: Store, run_id: str, lines: Sequence[CapturedLine]) -> None:
        batches.append(len(lines))
        original(self, run_id, lines)

    with (
        patch.object(Store, "write_log_lines", counting),
        capture_run_log("r1", store, batch_size=5),
    ):
        for index in range(12):
            log.info("line %d", index)

    assert max(batches) > 1
    assert sum(batches) == 12
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
    one — matching how the worker actually uses it: it enters the context
    manager and then runs the pipeline synchronously on itself. The `store`
    passed in is still thread-bound to whichever thread built it (here, the
    spawned one), because it is only used to read `store.path` — the
    handler writes through its own separate `check_same_thread=False`
    connection (see `capture_run_log`'s docstring), so which thread built
    `store` no longer matters to `emit` the way it once did.
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
    # handler open — the buffer itself must tolerate that.
    assert [line.message for line in buffers[0].since(0)] == ["from the worker"]

    release.set()
    thread.join(timeout=5)


def test_a_line_from_another_thread_is_captured_not_dropped(tmp_path):
    """This used to be
    `test_a_record_from_a_foreign_thread_is_dropped_without_raising`,
    pinning Critical 1's thread-identity filter: a line logged from a
    thread other than the one that entered `capture_run_log` was silently
    dropped, because the handler wrote through the caller's own
    `check_same_thread=True` `Store` and a foreign thread touching it would
    raise `sqlite3.ProgrammingError`.

    That filter is gone. It drew the wrong distinction — "which thread"
    rather than "writing through a connection that belongs to another
    thread" — and dropped `distil_topics`'s own `ThreadPoolExecutor`
    workers along with genuine foreign noise (see `RunLogHandler`'s
    docstring). This test now proves the opposite of what it used to: a
    line from another thread is captured, in both sinks, and still raises
    nothing — proof the handler's own dedicated,
    `check_same_thread=False` `Store` is what makes that safe rather than
    a filter that also threw away real diagnostics.
    """
    store = _store(tmp_path)
    store.start_run("r1", make_run_config())
    log = logging.getLogger("zeitgeist.testing.otherthread")
    raised: list[BaseException] = []

    with capture_run_log("r1", store) as buffer:

        def other() -> None:
            try:
                log.info("from another thread")
            except BaseException as exc:  # noqa: BLE001 - proving nothing escapes
                raised.append(exc)

        thread = threading.Thread(target=other)
        thread.start()
        thread.join(timeout=5)
        assert not thread.is_alive()

        log.info("from the caller")

    assert raised == []
    messages = {"from another thread", "from the caller"}
    assert {line.message for line in buffer.since(0)} == messages
    assert {line.message for line in store.log_lines("r1", verbose=True)} == messages


def test_a_line_from_a_thread_pool_executor_worker_reaches_both_sinks(tmp_path):
    """Important 1 (follow-up): `distil_topics` dispatches `_distil_one`
    through a `ThreadPoolExecutor` via `pool.map`, and its two `log.debug`
    calls — the per-topic "Distilling %r" line and the "Distilled %r in
    %.1fs" line — are the only visibility
    `GET /api/runs/{id}/log?verbose=true` has into the analyse stage. They
    run on pool threads, never the thread that entered `capture_run_log`.

    The old thread-identity filter would have dropped every one of these:
    exactly the regression this test guards against. A real
    `ThreadPoolExecutor`, not a bare `Thread` per line, because that is
    what `distil_topics` actually uses — pool threads are reused across
    tasks, which a fresh `Thread` per call does not exercise.
    """
    store = _store(tmp_path)
    store.start_run("r1", make_run_config())
    log = logging.getLogger("zeitgeist.testing.pool")
    task_count = 8

    def log_from_pool(index: int) -> None:
        log.debug("pool task %d", index)

    with (
        capture_run_log("r1", store) as buffer,
        ThreadPoolExecutor(max_workers=3) as pool,
    ):
        list(pool.map(log_from_pool, range(task_count)))

    expected = {f"pool task {index}" for index in range(task_count)}
    assert {line.message for line in buffer.since(0)} == expected
    assert {line.message for line in store.log_lines("r1", verbose=True)} == expected


def test_concurrent_logging_from_many_threads_produces_a_gapless_unique_sequence(
    tmp_path,
):
    """`_seq` is an unguarded read-modify-write and `flush`'s batch swap
    races an `append` if either runs without the lock: two emits landing on
    `_seq` at once could hand out the same number twice, which is an
    `IntegrityError` against `log_lines`' `(run_id, seq)` primary key.

    This used to be
    `test_concurrent_foreign_noise_leaves_the_owners_seq_unique_and_increasing`,
    which hammered `emit` from several "foreign" threads the guard then
    dropped, leaving only the owner thread's own lines to check. With the
    guard gone every thread's lines are legitimate and must all land, so
    this now drives real concurrent contention from several threads at
    once — mirroring a distillation pool rather than one owner plus
    discarded noise — and checks the union: every line from every thread
    captured exactly once, with a `seq` sequence that is a gapless,
    duplicate-free permutation of 1..total. Fixed counts per thread, not an
    open-ended loop stopped by a flag, so the expected total is exact
    rather than however much noise happened to land before `stop` was
    seen.
    """
    store = _store(tmp_path)
    store.start_run("r1", make_run_config())
    log = logging.getLogger("zeitgeist.testing.concurrent")
    thread_count = 5
    per_thread = 50
    total = thread_count * per_thread

    def worker(index: int) -> None:
        for line in range(per_thread):
            log.info("thread %d line %d", index, line)

    with capture_run_log("r1", store) as buffer:
        threads = [
            threading.Thread(target=worker, args=(index,))
            for index in range(thread_count)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5)
            assert not thread.is_alive()

    expected_messages = {
        f"thread {index} line {line}"
        for index in range(thread_count)
        for line in range(per_thread)
    }

    lines = buffer.since(0)
    assert len(lines) == total
    assert {line.message for line in lines} == expected_messages
    assert sorted(line.seq for line in lines) == list(range(1, total + 1))

    stored = store.log_lines("r1", verbose=True)
    assert len(stored) == total
    assert {line.message for line in stored} == expected_messages
    assert sorted(line.seq for line in stored) == list(range(1, total + 1))
