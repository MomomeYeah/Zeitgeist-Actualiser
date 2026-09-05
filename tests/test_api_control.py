from tests.api_factory import GatedExecute, seeded_client


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
