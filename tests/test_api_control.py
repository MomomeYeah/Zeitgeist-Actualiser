import threading

from tests.api_factory import GatedExecute, SeededRun, seeded_client
from tests.run_factory import make_evidence, make_run_config
from zeitgeist.records import Stage


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
    """
    seen: list[str] = []

    def execute(settings, request, store, observer, token) -> None:
        seen.append(request.run_id or "")

    client = seeded_client(
        tmp_path,
        runs=[SeededRun(run_id="20260901T120000Z")],
        execute=execute,
    )

    response = client.post(
        "/api/runs/20260901T120000Z/resume", json={"stage": "generate"}
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
    """
    seen: list[list[str] | None] = []

    def execute(settings, request, store, observer, token) -> None:
        seen.append(request.template_ids)

    client = seeded_client(
        tmp_path,
        runs=[SeededRun(run_id="20260901T120000Z")],
        execute=execute,
    )

    client.post(
        "/api/runs/20260901T120000Z/resume",
        json={"stage": "generate", "template_ids": ["drake"]},
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


def test_stopping_a_run_that_is_not_executing_is_a_404(tmp_path):
    """The inline abort confirmation is drawn from a poll that can be a
    moment stale. Reporting success for a run that already finished would
    leave the UI showing "aborting…" for a run that is done.
    """
    client = seeded_client(tmp_path, runs=[SeededRun(run_id="20260901T120000Z")])

    assert client.post("/api/runs/20260901T120000Z/stop").status_code == 404
    assert client.post("/api/runs/20260901T120000Z/abort").status_code == 404
