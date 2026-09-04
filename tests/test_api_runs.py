from tests.api_factory import SeededRun, api_settings, seeded_client
from tests.run_factory import (
    make_render_record,
    make_run_config,
    make_stage_record,
    make_topic,
)
from zeitgeist.records import Stage
from zeitgeist.store import Store


def test_the_runs_list_is_newest_first(tmp_path):
    client = seeded_client(
        tmp_path,
        runs=[
            SeededRun(run_id="20260901T100000Z"),
            SeededRun(run_id="20260901T120000Z"),
        ],
    )

    body = client.get("/api/runs").json()

    assert [entry["run"]["run_id"] for entry in body["runs"]] == [
        "20260901T120000Z",
        "20260901T100000Z",
    ]


def test_a_run_carries_the_counts_the_list_shows(tmp_path):
    """`25 trends -> 5 kept` is drawn straight from these."""
    client = seeded_client(
        tmp_path,
        runs=[
            SeededRun(
                config=make_run_config(top_count=1),
                topics=[make_topic("cats"), make_topic("dogs")],
            )
        ],
    )

    [entry] = client.get("/api/runs").json()["runs"]

    assert entry["run"]["trends_found"] == 2
    assert entry["run"]["topics_kept"] == 1


def test_a_run_carries_its_topic_labels_in_rank_order(tmp_path):
    """Column two of the row is the titles joined by a middot, ellipsised.
    Rank order is what makes the truncation show the topics that mattered."""
    client = seeded_client(
        tmp_path,
        runs=[
            SeededRun(
                topics=[
                    make_topic("quiet", trend_score=0.1),
                    make_topic("loud", trend_score=0.9),
                ]
            )
        ],
    )

    [entry] = client.get("/api/runs").json()["runs"]

    assert entry["topic_labels"] == ["Loud", "Quiet"]


def test_a_run_carries_its_render_ids_for_thumbnails(tmp_path):
    client = seeded_client(
        tmp_path,
        runs=[
            SeededRun(
                renders=[
                    make_render_record("r1", topic_id="cats"),
                    make_render_record("r2", topic_id="cats"),
                ]
            )
        ],
    )

    [entry] = client.get("/api/runs").json()["runs"]

    assert entry["render_ids"] == ["r1", "r2"]


def test_the_page_reports_a_cursor_when_more_runs_remain(tmp_path):
    client = seeded_client(
        tmp_path,
        runs=[
            SeededRun(run_id="20260901T100000Z"),
            SeededRun(run_id="20260901T110000Z"),
            SeededRun(run_id="20260901T120000Z"),
        ],
    )

    first = client.get("/api/runs", params={"limit": 2}).json()
    second = client.get(
        "/api/runs", params={"limit": 2, "cursor": first["next_cursor"]}
    ).json()

    assert len(first["runs"]) == 2
    assert first["next_cursor"] is not None
    assert [entry["run"]["run_id"] for entry in second["runs"]] == ["20260901T100000Z"]
    assert second["next_cursor"] is None


def test_an_empty_database_returns_an_empty_page(tmp_path):
    """The first screen anyone sees. A 500 here is the worst possible
    first impression."""
    client = seeded_client(tmp_path)

    body = client.get("/api/runs").json()

    assert body == {"runs": [], "next_cursor": None}


def test_run_detail_carries_the_frozen_config(tmp_path):
    """The config line shows what the run used, which a since-edited .env
    cannot supply."""
    client = seeded_client(
        tmp_path,
        runs=[SeededRun(config=make_run_config(top_count=9, llm_model="qwen3.5"))],
    )

    body = client.get("/api/runs/20260901T120000Z").json()

    assert body["run"]["config"]["top_count"] == 9
    assert body["run"]["config"]["llm_model"] == "qwen3.5"


def test_run_detail_carries_its_stages_in_pipeline_order(tmp_path):
    client = seeded_client(
        tmp_path,
        runs=[
            SeededRun(
                stages=[
                    make_stage_record(Stage.GENERATE),
                    make_stage_record(Stage.INGEST),
                ]
            )
        ],
    )

    body = client.get("/api/runs/20260901T120000Z").json()

    assert [s["stage"] for s in body["stages"]] == ["ingest", "generate"]


def test_a_run_with_every_checkpoint_resumes_from_generate(tmp_path):
    """Re-rendering a frozen ranking is always available - it is the
    template-tuning loop."""
    client = seeded_client(tmp_path, runs=[SeededRun()])
    # SeededRun writes the analyse checkpoint; write the other three directly
    # so all four exist. Empty payloads are enough - resume_stage asks which
    # stages have a row, not what is in it.
    store = Store(api_settings(tmp_path).db_path)
    store.write_checkpoint(
        "20260901T120000Z",
        Stage.INGEST,
        [],
    )
    store.write_checkpoint(
        "20260901T120000Z",
        Stage.EVALUATE,
        [],
    )
    store.write_checkpoint("20260901T120000Z", Stage.GENERATE, [])
    store.close()

    body = client.get("/api/runs/20260901T120000Z").json()

    assert body["resume_stage"] == "generate"


def test_a_run_that_failed_at_evaluate_resumes_from_evaluate(tmp_path):
    client = seeded_client(tmp_path, runs=[SeededRun()])
    store = Store(api_settings(tmp_path).db_path)
    store.write_checkpoint("20260901T120000Z", Stage.INGEST, [])
    store.close()

    body = client.get("/api/runs/20260901T120000Z").json()

    assert body["resume_stage"] == "evaluate"


def test_a_run_with_no_checkpoints_cannot_be_resumed(tmp_path):
    """A source outage writes nothing, so there is nothing to resume from
    and the UI must not offer an action it cannot honour."""
    client = seeded_client(tmp_path, runs=[SeededRun(topics=[], status="failed")])

    body = client.get("/api/runs/20260901T120000Z").json()

    assert body["resume_stage"] is None


def test_an_unknown_run_is_a_404(tmp_path):
    client = seeded_client(tmp_path)

    assert client.get("/api/runs/nope").status_code == 404
