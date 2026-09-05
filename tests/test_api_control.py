import json
import threading

from tests.api_factory import GatedExecute, LoggingGate, SeededRun, seeded_client
from tests.run_factory import make_evidence, make_run_config
from zeitgeist.records import LogLine, Stage


def test_posting_a_run_returns_the_id_it_will_have(tmp_path):
    """The New run screen navigates straight to the run's detail page. A
    response without the id would leave it with nowhere to go, and polling
    the runs list for "the newest one" races a second tab.
    """
    gate = GatedExecute()
    gate.release.set()
    client = seeded_client(tmp_path, execute=gate)

    response = client.post("/api/runs", json={})

    assert response.status_code == 202
    assert response.json()["run_id"]


def test_a_run_started_immediately_reports_position_zero(tmp_path):
    """The screen shows a "queues it behind N" notice only when the number is
    positive. A response that always reported a position would show that
    notice for a run starting right now."""
    gate = GatedExecute()
    client = seeded_client(tmp_path, execute=gate)
    try:
        body = client.post("/api/runs", json={}).json()

        assert body["position"] == 0
    finally:
        gate.release.set()


def test_a_second_run_reports_the_queue_it_is_behind(tmp_path):
    """This number is the notice. Reporting 0 for a queued run would promise
    the user it had started when it had not."""
    gate = GatedExecute()
    client = seeded_client(tmp_path, execute=gate)
    try:
        client.post("/api/runs", json={})
        assert gate.entered.wait(timeout=5)

        body = client.post("/api/runs", json={}).json()

        assert body["position"] == 1
    finally:
        gate.release.set()


def test_the_active_endpoint_reports_the_running_run_and_the_queue(tmp_path):
    """The sidebar's in-flight card polls this. An endpoint reporting only
    the current run would leave a queued one invisible until it started."""
    gate = GatedExecute()
    client = seeded_client(tmp_path, execute=gate)
    try:
        first = client.post("/api/runs", json={}).json()
        assert gate.entered.wait(timeout=5)
        second = client.post("/api/runs", json={}).json()

        body = client.get("/api/runs/active").json()

        assert body["current"] == first["run_id"]
        assert body["queued"] == [second["run_id"]]
    finally:
        gate.release.set()


def test_the_active_endpoint_reports_nothing_when_idle(tmp_path):
    """The common case, and the one that decides whether the card renders at
    all. An endpoint 404ing or erroring when idle would break every poll on a
    quiet server."""
    client = seeded_client(tmp_path)

    body = client.get("/api/runs/active").json()

    assert body["current"] is None
    assert body["queued"] == []


def test_overrides_reach_the_run(tmp_path):
    """The four config cards on the New run screen are these overrides.
    Dropped in the router, every run would use `.env` and the cards would be
    decorative."""
    seen: list[int] = []

    def execute(settings, request, store, observer, token) -> None:
        seen.append(settings.topic_count)

    client = seeded_client(tmp_path, execute=execute)

    client.post("/api/runs", json={"overrides": {"topic_count": "9"}})
    client.app.state.runner.shutdown(timeout=10)

    assert seen == [9]


def test_a_posted_template_selection_reaches_the_run(tmp_path):
    """The New run screen's template picker is this field. Dropped in the
    router, every run would render against the whole library and the picker
    would be decorative — and the resume endpoint's own test would not
    notice, because that is a different call site with its own body model.
    """
    seen: list[list[str] | None] = []

    def execute(settings, request, store, observer, token) -> None:
        seen.append(request.template_ids)

    client = seeded_client(tmp_path, execute=execute)

    client.post("/api/runs", json={"template_ids": ["drake"]})
    client.app.state.runner.shutdown(timeout=10)

    assert seen == [["drake"]]


def test_an_override_outside_the_allowlist_is_a_400(tmp_path):
    """`db_path` and `anthropic_api_key` are not run options. The service
    raises ValueError; a router that let it escape would return 500 and tell
    the user the server was broken rather than the request."""
    client = seeded_client(tmp_path)

    response = client.post(
        "/api/runs", json={"overrides": {"db_path": "/tmp/elsewhere.db"}}
    )

    assert response.status_code == 400


def test_the_api_key_is_not_accepted_as_an_override(tmp_path):
    """Named separately from the test above because this one is the reason
    the allowlist exists at all: a request able to set it would put a secret
    into a run's frozen config."""
    client = seeded_client(tmp_path)

    response = client.post(
        "/api/runs", json={"overrides": {"anthropic_api_key": "sk-ant-nope"}}
    )

    assert response.status_code == 400


def test_resuming_reuses_the_runs_existing_id(tmp_path):
    """Resume continues a run rather than starting a new one — its
    checkpoints are the whole point. A resume that allocated a fresh id would
    write a second run's rows and leave the first stranded at `interrupted`
    forever.

    Resumes at `evaluate` rather than `generate`: `generate` needs an
    EVALUATE checkpoint, which nothing in this factory can seed, so a request
    naming it would now be refused by the resume-stage check regardless of
    id reuse — which is not what this test is about. `evaluate` only needs
    INGEST and ANALYSE, which the added evidence and the run's default topic
    already back, so the request still reaches the executor.
    """
    seen: list[str] = []

    def execute(settings, request, store, observer, token) -> None:
        seen.append(request.run_id or "")

    client = seeded_client(
        tmp_path,
        runs=[
            SeededRun(
                run_id="20260901T120000Z",
                evidence=[make_evidence(["p1"])],
            )
        ],
        execute=execute,
    )

    response = client.post(
        "/api/runs/20260901T120000Z/resume", json={"stage": "evaluate"}
    )
    client.app.state.runner.shutdown(timeout=10)

    assert response.status_code == 202
    assert seen == ["20260901T120000Z"]


def test_resuming_without_a_stage_uses_the_computed_one(tmp_path):
    """The button posts no stage. A router requiring one would make the
    button unusable, and defaulting to `ingest` would silently redo the
    minutes of fetching that the run's checkpoints already hold.

    The run is seeded with its ingest evidence as well as its topics, so
    INGEST and ANALYSE are written and EVALUATE is not — making the computed
    stage EVALUATE rather than either end of `ORDER`, so a router hardcoding
    one fails here. The default `SeededRun` will not do: with no evidence it
    writes no INGEST checkpoint, `resume_stage` returns `None`, and the
    endpoint 409s before the default is ever consulted.
    """
    seen: list[Stage] = []

    def execute(settings, request, store, observer, token) -> None:
        seen.append(request.start_at)

    client = seeded_client(
        tmp_path,
        runs=[
            SeededRun(
                run_id="20260901T120000Z",
                evidence=[make_evidence(["p1"])],
            )
        ],
        execute=execute,
    )

    client.post("/api/runs/20260901T120000Z/resume", json={})
    client.app.state.runner.shutdown(timeout=10)

    assert seen == [Stage.EVALUATE]


def test_resuming_carries_the_narrowed_template_library(tmp_path):
    """This is the tuning loop the design's button cannot otherwise express:
    edit a manifest, re-render the same frozen topics against one template.
    Dropped here, resume would re-render against the whole library every
    time and the loop would be no faster than a fresh run.

    Resumes at `evaluate` rather than `generate`, for the same reason as
    `test_resuming_reuses_the_runs_existing_id`: there is no way to seed the
    EVALUATE checkpoint `generate` needs, and this test's subject is
    `template_ids` reaching the request, not which stage was named.
    """
    seen: list[list[str] | None] = []

    def execute(settings, request, store, observer, token) -> None:
        seen.append(request.template_ids)

    client = seeded_client(
        tmp_path,
        runs=[
            SeededRun(
                run_id="20260901T120000Z",
                evidence=[make_evidence(["p1"])],
            )
        ],
        execute=execute,
    )

    client.post(
        "/api/runs/20260901T120000Z/resume",
        json={"stage": "evaluate", "template_ids": ["drake"]},
    )
    client.app.state.runner.shutdown(timeout=10)

    assert seen == [["drake"]]


def test_resuming_an_unknown_run_is_a_404(tmp_path):
    client = seeded_client(tmp_path)

    response = client.post("/api/runs/nope/resume", json={})

    assert response.status_code == 404


def test_resuming_a_run_with_no_checkpoints_is_refused(tmp_path):
    """A source outage writes nothing, so there is nothing to resume from —
    phase 2's `resume_stage` returns `None` for exactly this. Enqueuing it
    anyway would start a run that fails on its first checkpoint read, and the
    user would see a second failure rather than a refusal.
    """
    client = seeded_client(
        tmp_path,
        runs=[SeededRun(run_id="20260901T120000Z", topics=[], status="failed")],
    )

    response = client.post("/api/runs/20260901T120000Z/resume", json={})

    assert response.status_code == 409


def test_resuming_at_a_stage_the_run_cannot_honour_is_refused(tmp_path):
    """A client-named stage is not the computed one — nothing guarantees its
    predecessors were actually written. This run has an INGEST checkpoint
    but no ANALYSE one (`topics=[]`), and is resumed at `generate`, whose
    predecessors in `ORDER` are INGEST, ANALYSE and EVALUATE. Without a
    check on the *named* stage, only the "nothing at all was written" branch
    guards this route, `stage` is used as given, and the run is enqueued: it
    reaches `generate`'s branch of `run_pipeline`, which reads a missing
    ANALYSE or EVALUATE checkpoint and fails on the worker thread — a 202
    now, a `failed` row later, instead of a 409 at the door. Asserting on
    `seen` (not just the status code) catches a fix that returns 409 while
    still calling `runner.enqueue` first.
    """
    seen: list[str] = []

    def execute(settings, request, store, observer, token) -> None:
        seen.append(request.run_id or "")

    client = seeded_client(
        tmp_path,
        runs=[
            SeededRun(
                run_id="20260901T120000Z",
                topics=[],
                evidence=[make_evidence(["p1"])],
            )
        ],
        execute=execute,
    )

    response = client.post(
        "/api/runs/20260901T120000Z/resume", json={"stage": "generate"}
    )

    assert response.status_code == 409
    assert seen == []


def test_resuming_at_a_stage_the_run_can_honour_is_accepted(tmp_path):
    """The companion to `test_resuming_at_a_stage_the_run_cannot_honour_is_
    refused`: a fix that refuses every explicit `stage` — not just an
    unbacked one — would also pass that test, since it never checks `seen`
    is non-empty anywhere else. Here INGEST (from the added evidence) and
    ANALYSE (from the run's default topic) are both written, which is
    everything `evaluate` needs from `ORDER`, so the request must still
    reach the executor with a 202.
    """
    seen: list[str] = []

    def execute(settings, request, store, observer, token) -> None:
        seen.append(request.run_id or "")

    client = seeded_client(
        tmp_path,
        runs=[
            SeededRun(
                run_id="20260901T120000Z",
                evidence=[make_evidence(["p1"])],
            )
        ],
        execute=execute,
    )

    response = client.post(
        "/api/runs/20260901T120000Z/resume", json={"stage": "evaluate"}
    )
    client.app.state.runner.shutdown(timeout=10)

    assert response.status_code == 202
    assert seen == ["20260901T120000Z"]


def test_resuming_a_run_twice_is_a_409_the_second_time(tmp_path):
    """Critical 2: a double-clicked Resume button, or a second tab racing
    the first. Before the fix, the second POST silently replaced the live
    run's `CancelToken` with one nobody reads — the run became unstoppable
    — and the worker's own second dequeue then raised `KeyError` before
    `_run_one`'s `try` began, leaving `GET /api/runs/active` reporting this
    run as current forever. This 409 must read differently from the
    "wrote no checkpoints" 409 above, so a client can tell a duplicate
    request apart from one that never had anything to resume from — and
    the run itself must still be exactly what `active()` reports, not
    replaced or lost.
    """
    gate = GatedExecute()
    client = seeded_client(
        tmp_path,
        runs=[
            SeededRun(
                run_id="20260901T120000Z",
                evidence=[make_evidence(["p1"])],
            )
        ],
        execute=gate,
    )
    try:
        first = client.post(
            "/api/runs/20260901T120000Z/resume", json={"stage": "evaluate"}
        )
        assert first.status_code == 202
        assert gate.entered.wait(timeout=5)

        second = client.post(
            "/api/runs/20260901T120000Z/resume", json={"stage": "evaluate"}
        )

        assert second.status_code == 409
        assert second.json()["detail"] != (
            "Run 20260901T120000Z wrote no checkpoints; there is nothing to "
            "resume from."
        )
        assert client.get("/api/runs/active").json()["current"] == ("20260901T120000Z")
    finally:
        gate.release.set()
        client.app.state.runner.shutdown(timeout=10)

    assert client.get("/api/runs/active").json()["current"] is None


def test_stop_trips_stopping_and_abort_trips_aborted(tmp_path):
    """Two buttons, two meanings, and 202 from both. A stop wired to
    `runner.abort` would answer 202 exactly as it does now while unwinding
    the stage mid-flight and losing the checkpoint the stop button promises —
    so what gets asserted is the token the worker handed the run, not the
    status code. Task 8 pins this at the service; nothing else pins it at the
    seam the button actually goes through.
    """
    flags: dict[str, tuple[bool, bool]] = {}
    entered = threading.Event()
    released = threading.Event()

    def execute(settings, request, store, observer, token) -> None:
        run_id = request.run_id or ""
        store.start_run(run_id, make_run_config())
        entered.set()
        assert released.wait(timeout=5)
        flags[run_id] = (token.stopping, token.aborted)

    client = seeded_client(tmp_path, execute=execute)

    stopped = client.post("/api/runs", json={}).json()
    assert entered.wait(timeout=5)
    assert client.post(f"/api/runs/{stopped['run_id']}/stop").status_code == 202
    released.set()
    client.app.state.runner.shutdown(timeout=10)

    entered.clear()
    released.clear()
    client.app.state.runner.start()
    aborted = client.post("/api/runs", json={}).json()
    assert entered.wait(timeout=5)
    assert client.post(f"/api/runs/{aborted['run_id']}/abort").status_code == 202
    released.set()
    client.app.state.runner.shutdown(timeout=10)

    assert flags[stopped["run_id"]] == (True, False)
    assert flags[aborted["run_id"]] == (True, True)


def test_stop_and_abort_report_a_declared_response_shape(tmp_path):
    """Both endpoints used to return a bare `dict[str, str]` with no
    `response_model`, unlike every other endpoint in the project. Phase 5
    generates a TypeScript client from this OpenAPI schema, and this pins
    the body's actual shape — not just its status code, which every other
    test here already covers — so a regression to an undeclared dict would
    still be caught even though FastAPI would happily serialise one.
    """
    entered = threading.Event()
    released = threading.Event()

    def execute(settings, request, store, observer, token) -> None:
        run_id = request.run_id or ""
        store.start_run(run_id, make_run_config())
        entered.set()
        assert released.wait(timeout=5)

    client = seeded_client(tmp_path, execute=execute)

    body = client.post("/api/runs", json={}).json()
    assert entered.wait(timeout=5)

    response = client.post(f"/api/runs/{body['run_id']}/stop")
    released.set()
    client.app.state.runner.shutdown(timeout=10)

    assert response.json() == {"run_id": body["run_id"], "requested": "stop"}


def test_stopping_a_run_that_is_not_executing_is_a_404(tmp_path):
    """The inline abort confirmation is drawn from a poll that can be a
    moment stale. Reporting success for a run that already finished would
    leave the UI showing "aborting…" for a run that is done.
    """
    client = seeded_client(tmp_path, runs=[SeededRun(run_id="20260901T120000Z")])

    assert client.post("/api/runs/20260901T120000Z/stop").status_code == 404
    assert client.post("/api/runs/20260901T120000Z/abort").status_code == 404


def _events(client, url, *, release_after=None, limit=400):
    """Read an SSE response into (event, data) pairs until it closes.

    `release_after` is called once, after the first batch of events has been
    read, to let a gated run finish — otherwise the stream would stay open
    for as long as the run does and this would never return.

    Bounded, so a generator that fails to terminate fails the test in a few
    seconds rather than hanging it. Do not raise the bound to make a test
    pass; a stream that will not close is the bug.
    """
    collected: list[tuple[str, str]] = []
    released = False
    with client.stream("GET", url) as response:
        assert response.status_code == 200
        name = ""
        for index, line in enumerate(response.iter_lines()):
            if index > limit:
                raise AssertionError("stream did not end")
            if line.startswith("event:"):
                name = line.removeprefix("event:").strip()
            elif line.startswith("data:"):
                collected.append((name, line.removeprefix("data:").strip()))
                if release_after is not None and not released:
                    released = True
                    release_after()
    return collected


def _logged(events):
    return [
        line["message"]
        for name, data in events
        if name == "log"
        for line in json.loads(data)
    ]


def test_the_stream_carries_the_runs_log_lines(tmp_path):
    """The live log is the reason this endpoint exists. A stream emitting
    only ticks would leave the client polling the historical log endpoint it
    was built to replace.
    """
    gate = LoggingGate()
    client = seeded_client(tmp_path, execute=gate)
    body = client.post("/api/runs", json={}).json()
    assert gate.entered.wait(timeout=5)

    events = _events(
        client,
        f"/api/runs/{body['run_id']}/events",
        release_after=gate.release.set,
    )

    assert "hello from the run" in _logged(events)


def test_the_stream_ends_when_the_run_ends(tmp_path):
    """A stream that never closed would hold one connection per watched run
    for the life of the process — and because the browser reconnects on
    close, one that stayed open after the run finished would never let it
    stop watching either.

    The bound inside `_events` is what turns "never closes" into a failure;
    reaching this assertion at all is the result.
    """
    gate = LoggingGate()
    client = seeded_client(tmp_path, execute=gate)
    body = client.post("/api/runs", json={}).json()
    assert gate.entered.wait(timeout=5)

    events = _events(
        client,
        f"/api/runs/{body['run_id']}/events",
        release_after=gate.release.set,
    )

    assert events


def test_a_line_is_sent_once(tmp_path):
    """The generator polls with the last seq it sent. Draining from 0 each
    time would resend the whole log on every tick, and the browser would
    render the run's output over and over for the life of the run.
    """
    gate = LoggingGate(message="only once")
    client = seeded_client(tmp_path, execute=gate)
    body = client.post("/api/runs", json={}).json()
    assert gate.entered.wait(timeout=5)

    events = _events(
        client,
        f"/api/runs/{body['run_id']}/events",
        release_after=gate.release.set,
    )

    assert _logged(events).count("only once") == 1


def test_every_poll_emits_a_tick_the_client_can_invalidate_on(tmp_path):
    """A tick carries no data of its own: the observer has already written
    `run_records`, `run_stages` and `run_topics` from the worker thread, and
    the tick is what tells the client to refetch them. Without it the stream
    would deliver log lines and nothing else, and the stage cards would never
    advance until the page was reloaded — which no other test here would
    notice, because they all filter for `log`.
    """
    client = seeded_client(tmp_path, runs=[SeededRun(run_id="20260901T120000Z")])

    events = _events(client, "/api/runs/20260901T120000Z/events")

    ticks = [json.loads(data) for name, data in events if name == "tick"]
    assert ticks
    assert all(set(tick) == {"seq"} for tick in ticks)


def test_a_streamed_line_carries_everything_the_log_viewer_renders(tmp_path):
    """The viewer colours by level, groups by logger and orders by seq, and
    the historical endpoint returns all five fields. A stream sending only
    the message would make the live log and the post-mortem log two different
    things, and the verbose toggle would have nothing to filter on until the
    run ended.
    """
    gate = LoggingGate()
    client = seeded_client(tmp_path, execute=gate)
    body = client.post("/api/runs", json={}).json()
    assert gate.entered.wait(timeout=5)

    events = _events(
        client,
        f"/api/runs/{body['run_id']}/events",
        release_after=gate.release.set,
    )

    lines = [
        line for name, data in events if name == "log" for line in json.loads(data)
    ]
    [line] = [line for line in lines if line["message"] == gate.message]
    # Parity with `LogLine` rather than a literal key set: the invariant is
    # that the live stream and the historical endpoint carry the same fields,
    # so adding one to both should keep this passing and adding it to only
    # one should not. A hardcoded set would fire on the former, which is a
    # decision rather than a bug.
    assert set(line) == set(LogLine.model_fields)
    assert line["level"] == "INFO"
    assert line["logger"] == "zeitgeist.testing.sse"


def test_streaming_an_unknown_run_is_a_404(tmp_path):
    """The client opens this from a run detail page. A stream that opened
    for any id would leave a mistyped URL hanging rather than erroring."""
    client = seeded_client(tmp_path)

    response = client.get("/api/runs/nope/events")

    assert response.status_code == 404


def test_streaming_a_finished_run_ends_immediately(tmp_path):
    """A completed run has no buffer — the worker drops it when the run ends,
    and the historical log endpoint serves it instead. This must close rather
    than wait forever for a run that will never emit anything, which is the
    case a client hitting an old run's detail page produces.

    No `release_after` here: there is nothing holding this stream open, and
    needing one would mean the terminating condition was wrong.
    """
    client = seeded_client(tmp_path, runs=[SeededRun(run_id="20260901T120000Z")])

    events = _events(client, "/api/runs/20260901T120000Z/events")

    assert _logged(events) == []
