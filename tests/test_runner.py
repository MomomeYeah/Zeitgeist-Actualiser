import threading

import pytest

from tests.run_factory import make_run_config
from zeitgeist.config import Settings
from zeitgeist.progress import Aborted
from zeitgeist.records import Stage
from zeitgeist.runner import RunAlreadyActive, RunRequest, RunService
from zeitgeist.store import Store


def _settings(tmp_path) -> Settings:
    return Settings(
        _env_file=None,
        db_path=tmp_path / "z.db",
        output_dir=tmp_path / "output",
    )


def _open_store(tmp_path) -> Store:
    """The "request-thread" Store `enqueue` now opens a run's row through —
    standing in for the app's own `app.state.store` in `create_app`.
    `check_same_thread=False` because `enqueue` in these tests is called
    from the same thread as everything else here, but the real one is
    touched from whatever thread FastAPI dispatches a request onto.
    """
    settings = _settings(tmp_path)
    store = Store(settings.db_path, check_same_thread=False)
    store.init_schema()
    return store


class _Gate:
    """A run that blocks until released, so a test can hold the worker in a
    known state without sleeping.

    It opens the run row itself. The real executor reaches `run_pipeline`,
    and `run_pipeline` is what calls `store.start_run`; a fake that skips
    that leaves `run_records` empty, and both `abort_run` and `fail_run` are
    `UPDATE ... WHERE run_id = ?`, so every terminal-status assertion would
    read back `None` no matter what the worker did.
    """

    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()
        self.run_ids: list[str] = []
        self.raise_on_release: Exception | None = None

    def __call__(self, settings, request, store, observer, token) -> None:
        run_id = request.run_id or ""
        store.start_run(run_id, make_run_config())
        self.run_ids.append(run_id)
        self.entered.set()
        assert self.release.wait(timeout=5)
        if self.raise_on_release is not None:
            raise self.raise_on_release


def _service(tmp_path, execute) -> RunService:
    service = RunService(_settings(tmp_path), _open_store(tmp_path), execute=execute)
    service.start()
    return service


def test_a_run_starts_immediately_when_the_worker_is_idle(tmp_path):
    """`POST /api/runs` reports position 0 for a run that begins now and a
    positive one for a run that waits, and the New run screen renders a
    "queues it behind" notice off that number. A service always reporting 0
    would hide the queue entirely."""
    gate = _Gate()
    service = _service(tmp_path, gate)
    try:
        queued = service.enqueue(RunRequest())

        assert queued.position == 0
        assert gate.entered.wait(timeout=5)
    finally:
        gate.release.set()
        service.shutdown()


def test_a_second_run_waits_behind_the_first(tmp_path):
    """At most one run executes at a time, which is the whole reason the
    queue exists: two concurrent pipelines would contend on one GPU and
    interleave their log lines into each other's rows."""
    gate = _Gate()
    service = _service(tmp_path, gate)
    try:
        service.enqueue(RunRequest())
        assert gate.entered.wait(timeout=5)

        second = service.enqueue(RunRequest())

        assert second.position == 1
        assert service.active().current is not None
        assert service.active().queued == [second.run_id]
    finally:
        gate.release.set()
        service.shutdown()


def test_queued_runs_execute_in_the_order_they_were_posted(tmp_path):
    """FIFO. A queue drained in any other order would run the user's newest
    request last, which is the opposite of what a queue notice promises.

    Auto-generated `run_id`s, exercising the real `new_run_id()`: it now has
    millisecond resolution backed by a monotonic counter, so three calls
    issued this close together can no longer collide on the same string.
    """
    gate = _Gate()
    service = _service(tmp_path, gate)
    try:
        first = service.enqueue(RunRequest())
        assert gate.entered.wait(timeout=5)
        second = service.enqueue(RunRequest())
        third = service.enqueue(RunRequest())
        gate.release.set()
        service.shutdown(timeout=10)
    finally:
        gate.release.set()

    assert gate.run_ids == [first.run_id, second.run_id, third.run_id]


def test_a_completed_run_leaves_the_queue(tmp_path):
    """`GET /api/runs/active` drives the sidebar's in-flight card. A run that
    stayed listed after finishing would pin that card forever."""
    gate = _Gate()
    service = _service(tmp_path, gate)
    gate.release.set()
    service.enqueue(RunRequest())
    service.shutdown(timeout=10)

    assert service.active().current is None
    assert service.active().queued == []


def test_an_aborted_run_is_recorded_as_aborted(tmp_path):
    """Only the worker can tell abort from success: `run_pipeline` lets
    `Aborted` propagate rather than writing a status. Uncaught here, the run
    would keep the `running` row it started with and be reconciled to
    `interrupted` on the next restart — the wrong story entirely."""
    gate = _Gate()
    gate.raise_on_release = Aborted("run aborted")
    service = _service(tmp_path, gate)
    gate.release.set()
    queued = service.enqueue(RunRequest())
    service.shutdown(timeout=10)

    store = Store(_settings(tmp_path).db_path)
    store.init_schema()
    record = store.get_run(queued.run_id)
    store.close()
    assert record is not None
    assert record.status == "aborted"


def test_a_run_that_raises_is_recorded_as_failed_with_its_error(tmp_path):
    """The Runs screen renders "RenderError in generate" from these two
    fields. A worker that caught the exception and wrote a bare `failed`
    would leave the post-mortem block with nothing to show."""
    gate = _Gate()
    gate.raise_on_release = RuntimeError("boom")
    service = _service(tmp_path, gate)
    gate.release.set()
    queued = service.enqueue(RunRequest())
    service.shutdown(timeout=10)

    store = Store(_settings(tmp_path).db_path)
    store.init_schema()
    record = store.get_run(queued.run_id)
    store.close()
    assert record is not None
    assert record.status == "failed"
    assert record.error is not None
    assert record.error.kind == "RuntimeError"


def test_one_run_failing_does_not_stop_the_worker(tmp_path):
    """A worker whose loop exited on the first exception would leave every
    queued run stuck forever, and the only symptom would be a queue that
    never drains — with the traceback already swallowed into a run row."""
    gate = _Gate()
    gate.raise_on_release = RuntimeError("boom")
    service = _service(tmp_path, gate)
    gate.release.set()
    service.enqueue(RunRequest())
    second = service.enqueue(RunRequest())
    service.shutdown(timeout=10)

    assert second.run_id in gate.run_ids


def test_aborting_the_current_run_trips_its_token(tmp_path):
    """The endpoint's only job is to reach the token the worker handed the
    pipeline. A service keeping tokens per request rather than per run would
    return True and cancel nothing."""
    seen: list[bool] = []

    def execute(settings, request, store, observer, token) -> None:
        entered.set()
        assert released.wait(timeout=5)
        seen.append(token.aborted)

    entered = threading.Event()
    released = threading.Event()
    service = RunService(_settings(tmp_path), _open_store(tmp_path), execute=execute)
    service.start()
    try:
        queued = service.enqueue(RunRequest())
        assert entered.wait(timeout=5)

        assert service.abort(queued.run_id) is True
    finally:
        released.set()
        service.shutdown(timeout=10)

    assert seen == [True]


def test_stopping_the_current_run_trips_stopping_but_not_aborted(tmp_path):
    """Two buttons, two meanings. A stop routed to `abort()` would unwind the
    stage mid-flight and lose the checkpoint the stop button promises to
    write."""
    seen: list[tuple[bool, bool]] = []

    def execute(settings, request, store, observer, token) -> None:
        entered.set()
        assert released.wait(timeout=5)
        seen.append((token.stopping, token.aborted))

    entered = threading.Event()
    released = threading.Event()
    service = RunService(_settings(tmp_path), _open_store(tmp_path), execute=execute)
    service.start()
    try:
        queued = service.enqueue(RunRequest())
        assert entered.wait(timeout=5)

        assert service.stop(queued.run_id) is True
    finally:
        released.set()
        service.shutdown(timeout=10)

    assert seen == [(True, False)]


def test_a_run_stopped_after_a_stage_is_recorded_as_aborted(tmp_path):
    """`run_pipeline` returns normally on a stop, without writing a terminal
    status: only the worker holds the token and can tell a stop from a clean
    completion. Left unwritten, the run keeps the `running` row it started
    with and the next startup reconciles it to `interrupted` — a crash story
    for a run the user deliberately stopped.

    Distinct from the abort test above, which reaches the `except Aborted`
    branch: this one reaches `if token.stopping`, and deleting that branch
    fails nothing else in the suite.
    """
    entered = threading.Event()
    released = threading.Event()

    def execute(settings, request, store, observer, token) -> None:
        store.start_run(request.run_id or "", make_run_config())
        entered.set()
        assert released.wait(timeout=5)
        # A stop is honoured at a stage boundary: the pipeline returns rather
        # than raising, which is what returning here stands in for.

    service = RunService(_settings(tmp_path), _open_store(tmp_path), execute=execute)
    service.start()
    queued = service.enqueue(RunRequest())
    assert entered.wait(timeout=5)
    assert service.stop(queued.run_id) is True
    released.set()
    service.shutdown(timeout=10)

    store = Store(_settings(tmp_path).db_path)
    store.init_schema()
    record = store.get_run(queued.run_id)
    store.close()
    assert record is not None
    assert record.status == "aborted"


def test_aborting_an_unknown_run_reports_that_it_did_nothing(tmp_path):
    """The endpoint turns this into a 404. A service returning True for a run
    it has never heard of would tell the user a finished run was aborting."""
    gate = _Gate()
    gate.release.set()
    service = _service(tmp_path, gate)
    try:
        assert service.abort("nope") is False
        assert service.stop("nope") is False
    finally:
        service.shutdown(timeout=10)


def test_a_run_gets_a_log_buffer_for_its_duration(tmp_path):
    """The SSE endpoint reads this buffer. A service that created one per
    request, or returned None while a run was executing, would stream an
    empty log for every run."""
    buffers: list[object] = []

    def execute(settings, request, store, observer, token) -> None:
        buffers.append(service.buffer(request.run_id or ""))
        entered.set()
        assert released.wait(timeout=5)

    entered = threading.Event()
    released = threading.Event()
    service = RunService(_settings(tmp_path), _open_store(tmp_path), execute=execute)
    service.start()
    try:
        service.enqueue(RunRequest())
        assert entered.wait(timeout=5)
    finally:
        released.set()
        service.shutdown(timeout=10)

    assert buffers and buffers[0] is not None


def test_an_override_outside_the_allowlist_is_refused(tmp_path):
    """`db_path`, `output_dir` and `anthropic_api_key` are not run options.
    A request able to set them could point a run at another database or hand
    it a key, neither of which the New run screen offers."""
    gate = _Gate()
    gate.release.set()
    service = _service(tmp_path, gate)
    try:
        with pytest.raises(ValueError):
            service.enqueue(RunRequest(overrides={"db_path": "/tmp/elsewhere.db"}))
    finally:
        service.shutdown(timeout=10)


def test_an_allowlisted_override_reaches_the_run(tmp_path):
    """The New run screen's config cards are these overrides. Dropped on the
    way through, every run would silently use `.env`'s values and the screen
    would be decorative."""
    seen: list[int] = []

    def execute(settings, request, store, observer, token) -> None:
        seen.append(settings.topic_count)

    service = RunService(_settings(tmp_path), _open_store(tmp_path), execute=execute)
    service.start()
    service.enqueue(RunRequest(overrides={"topic_count": "9"}))
    service.shutdown(timeout=10)

    assert seen == [9]


def test_a_run_that_fails_before_any_row_exists_still_leaves_a_failed_row(tmp_path):
    """Building the trend source and the provider happens inside the real
    executor, before `run_pipeline` reaches `store.start_run`. A failure in
    that window used to mean `fail_run`'s `UPDATE ... WHERE run_id = ?`
    matched no row at all: the client already held a run_id from
    `POST /api/runs`, and the exception left the run existing only in the
    server log — a run the UI would navigate to and 404 on forever. The
    worker must open the row itself before ever calling out to the executor,
    so this executor is written to raise immediately, before it does
    anything a real one would use to open a row."""

    def execute(settings, request, store, observer, token) -> None:
        raise RuntimeError("boom before the executor did anything")

    service = RunService(_settings(tmp_path), _open_store(tmp_path), execute=execute)
    service.start()
    queued = service.enqueue(RunRequest())
    service.shutdown(timeout=10)

    store = Store(_settings(tmp_path).db_path)
    store.init_schema()
    record = store.get_run(queued.run_id)
    store.close()
    assert record is not None
    assert record.status == "failed"
    assert record.error is not None
    assert record.error.kind == "RuntimeError"


def test_enqueue_lists_every_queued_run_before_the_worker_catches_up(tmp_path):
    """Between `enqueue`'s `put` and the worker's own lock acquisition in
    `_run_one`, a request is in flight but was previously invisible to
    `enqueue`'s own position math and to `active()`. Two POSTs landing in
    that window would both see "nothing running, nothing waiting" and both
    report position 0 — and neither would show up in `queued` until the
    worker started it, which is what would let a user double-post.

    Never starting the worker reproduces that window deterministically:
    nothing ever dequeues either request, so both stay exactly as `enqueue`
    left them for this assertion to inspect."""
    service = RunService(
        _settings(tmp_path), _open_store(tmp_path), execute=lambda *a: None
    )

    first = service.enqueue(RunRequest())
    second = service.enqueue(RunRequest())

    assert first.position == 0
    assert second.position == 1
    assert service.active().queued == [first.run_id, second.run_id]


def test_enqueuing_a_run_id_already_executing_is_refused(tmp_path):
    """Critical 2: a duplicate resume, or a double-clicked Resume button.
    The old code unconditionally replaced `_tokens[run_id]`, orphaning the
    token `stop`/`abort` still reach — the live run became unstoppable —
    and the second dequeue's own `self._tokens[run_id]` then raised
    `KeyError` before `_run_one`'s `try` began, leaving `_current` stuck on
    this run_id forever. Refusing the duplicate outright, before either of
    those has a chance to happen, is what this proves: `active()` must
    still name the original run as current, and the *original* token —
    not a replacement nobody is holding — must still be the one `stop`
    reaches.
    """
    gate = _Gate()
    service = _service(tmp_path, gate)
    try:
        first = service.enqueue(RunRequest(run_id="dup-run"))
        assert gate.entered.wait(timeout=5)

        with pytest.raises(RunAlreadyActive):
            service.enqueue(RunRequest(run_id="dup-run"))

        # Evidence the defect is gone: active() is still clean — naming
        # exactly the original run, nothing stale or doubled — and the
        # original token (not a replacement) still stops it.
        assert service.active().current == first.run_id
        assert service.active().queued == []
        assert service.stop(first.run_id) is True
    finally:
        gate.release.set()
        service.shutdown(timeout=10)

    assert service.active().current is None


def test_enqueuing_a_run_id_already_waiting_is_refused(tmp_path):
    """The companion case: the duplicate names a run still queued behind
    the current one, rather than the one executing right now."""
    gate = _Gate()
    service = _service(tmp_path, gate)
    try:
        service.enqueue(RunRequest())
        assert gate.entered.wait(timeout=5)
        service.enqueue(RunRequest(run_id="waiting-run"))

        with pytest.raises(RunAlreadyActive):
            service.enqueue(RunRequest(run_id="waiting-run"))

        assert service.active().queued == ["waiting-run"]
    finally:
        gate.release.set()
        service.shutdown(timeout=10)


def test_start_after_a_timed_out_shutdown_does_not_spawn_a_second_worker(tmp_path):
    """A `shutdown` that times out while a run is still executing must leave
    `_thread` set. Unconditionally clearing it, as before, would mean a later
    `start()` sees `_thread is None` and spawns a second worker thread onto
    the same queue while the first is still running its own item — two
    threads able to both call `_queue.get()` and both call `run_pipeline` at
    once, which is exactly the invariant this class exists to hold."""
    gate = _Gate()
    service = _service(tmp_path, gate)
    try:
        service.enqueue(RunRequest())
        assert gate.entered.wait(timeout=5)

        service.shutdown(timeout=0.05)  # times out: gate.release is not set
        service.start()

        workers = [t for t in threading.enumerate() if t.name == "zeitgeist-runner"]
        assert len(workers) == 1
    finally:
        gate.release.set()
        service.shutdown(timeout=10)


def test_a_token_less_run_gets_a_fresh_one_and_the_worker_moves_on(tmp_path):
    """Critical 2: `_run_one` used to look its token up with a plain
    `self._tokens[run_id]`, sitting *before* its own try/except but after
    `self._current = run_id` had already been assigned. A request queued
    without ever going through `enqueue` — bypassing `_waiting` and
    `_tokens` both — raised `KeyError` right there, escaping before the
    `try` was ever entered. The worker loop's own handler kept the thread
    alive, but `_run_one`'s `finally` had never run, so `_current` stayed
    pinned to the ghost run forever: `active()` would report it as current
    with nothing actually executing, and every later run would queue
    behind a run that had already vanished.

    `_run_one` now looks the token up with `self._tokens.setdefault(...)`,
    inside its own try, so a token-less request no longer raises at all —
    it gets a fresh, ad-hoc one and runs to completion like any properly
    enqueued run, and the worker is free to dequeue whatever comes next.
    `gate.release` is set up front so neither run blocks, which is what
    lets both come out the other side well within the test."""
    gate = _Gate()
    gate.release.set()
    service = _service(tmp_path, gate)
    try:
        service._queue.put(RunRequest(run_id="ghost-with-no-token"))
        second = service.enqueue(RunRequest())
        service.shutdown(timeout=10)
    finally:
        gate.release.set()
        service.shutdown(timeout=10)

    assert gate.run_ids == ["ghost-with-no-token", second.run_id]
    assert service.active().current is None


def test_a_run_failing_after_a_later_stage_is_recorded_with_that_stage(tmp_path):
    """`stage=request.start_at` names where a run *started*, not where it
    *failed*: a run that starts at ingest and dies in generate must not be
    recorded as failing in ingest. The Runs screen renders "RenderError in
    generate" from exactly this field, so the run here starts at ingest but
    reports entering generate before it raises — a stage later than its
    start, which is the only way this assertion can tell the fix from the
    bug it replaces."""
    entered = threading.Event()
    released = threading.Event()

    def execute(settings, request, store, observer, token) -> None:
        observer.stage_started(Stage.GENERATE)
        entered.set()
        assert released.wait(timeout=5)
        raise RuntimeError("boom in generate")

    service = RunService(_settings(tmp_path), _open_store(tmp_path), execute=execute)
    service.start()
    queued = service.enqueue(RunRequest(start_at=Stage.INGEST))
    assert entered.wait(timeout=5)
    released.set()
    service.shutdown(timeout=10)

    store = Store(_settings(tmp_path).db_path)
    store.init_schema()
    record = store.get_run(queued.run_id)
    store.close()
    assert record is not None
    assert record.status == "failed"
    assert record.error is not None
    assert record.error.stage == Stage.GENERATE


def test_aborting_a_completed_run_reports_that_it_did_nothing(tmp_path):
    """A stale token for a run that finished hours ago must not trip and
    report `True`: the endpoint turns `False` into a 404, and returning
    `True` here would tell the user a finished run was aborting. The
    existing "unknown run" test only covers a `run_id` never enqueued at
    all, which passes trivially whether or not `_tokens` is ever cleaned
    up — this one enqueues, lets the run finish, and only then aborts it."""
    gate = _Gate()
    service = _service(tmp_path, gate)
    gate.release.set()
    queued = service.enqueue(RunRequest())
    service.shutdown(timeout=10)

    assert service.abort(queued.run_id) is False
    assert service.stop(queued.run_id) is False


def test_a_run_picks_up_the_settings_table_for_fields_it_does_not_override(
    tmp_path, monkeypatch
):
    """`PUT /api/settings` writes to this table, and the spec's promise is
    that changes apply to new runs. Splatting *every* field of this
    service's own startup settings as constructor arguments would pin every
    run-settable field at its value from `RunService.__init__` forever —
    `init_settings` outranks the table in `Settings.settings_customise_
    sources` — making that promise false until a restart. A request that
    does not override `phrase_min_authors` must still see a value written
    to the table after the service started.

    `SettingsTableSource` cannot resolve its database from a constructed
    `Settings.db_path` — that would be circular — so it re-derives its own
    path from `DB_PATH`/`.env` instead (see `zeitgeist/settings_source.py`).
    `DB_PATH` has to point at this test's database for the table to be
    consulted at all, the same as every test in `test_settings_source.py`.
    """
    settings = _settings(tmp_path)
    monkeypatch.setenv("DB_PATH", str(settings.db_path))
    store = Store(settings.db_path)
    store.init_schema()
    store.set_setting("phrase_min_authors", "7")
    store.close()

    seen: list[int] = []

    def execute(settings, request, store, observer, token) -> None:
        seen.append(settings.phrase_min_authors)

    service = RunService(settings, _open_store(tmp_path), execute=execute)
    service.start()
    service.enqueue(RunRequest())
    service.shutdown(timeout=10)

    assert seen == [7]
