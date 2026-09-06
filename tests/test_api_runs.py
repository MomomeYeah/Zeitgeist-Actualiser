from datetime import UTC, datetime

from tests.api_factory import SeededRun, api_settings, seeded_client
from tests.run_factory import (
    make_dossier,
    make_render_record,
    make_run_config,
    make_stage_record,
    make_topic,
)
from zeitgeist.api.runs import MAX_REPLIES
from zeitgeist.models import (
    BlueskyMetrics,
    Item,
    PostEvidence,
    Reply,
    Sentiment,
    TrendEvidence,
    TrendInfo,
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


def test_a_run_seeded_as_failed_is_reported_as_failed(tmp_path):
    """seed_run used to special-case only status="ok", leaving every other
    value in the "running" state start_run wrote and never calling
    fail_run. This run relied on the analyse checkpoint being absent rather
    than on the stored status actually reading "failed" -- pinning the
    status itself here is what would have caught that."""
    client = seeded_client(tmp_path, runs=[SeededRun(topics=[], status="failed")])

    body = client.get("/api/runs/20260901T120000Z").json()

    assert body["run"]["status"] == "failed"


def test_a_run_seeded_as_aborted_is_reported_as_aborted(tmp_path):
    """`seed_run` used to raise `NotImplementedError` for "aborted" — its
    own comment said no writer existed anywhere in this phase, which
    `Store.abort_run` (added for the stop/abort endpoints) has since made
    false. This pins that seeding a run straight into this status actually
    works, the way `test_a_run_seeded_as_failed_is_reported_as_failed`
    already does for "failed".
    """
    client = seeded_client(tmp_path, runs=[SeededRun(status="aborted")])

    body = client.get("/api/runs/20260901T120000Z").json()

    assert body["run"]["status"] == "aborted"


def test_an_unknown_run_is_a_404(tmp_path):
    client = seeded_client(tmp_path)

    assert client.get("/api/runs/nope").status_code == 404


def test_the_ranking_includes_topics_below_the_cut(tmp_path):
    """The screen draws them dimmed with a generate link - they were never
    briefed, and that row is the escape hatch to brief them by hand."""
    client = seeded_client(
        tmp_path,
        runs=[
            SeededRun(
                config=make_run_config(top_count=1),
                topics=[
                    make_topic("loud", trend_score=0.9),
                    make_topic("quiet", trend_score=0.1),
                ],
            )
        ],
    )

    body = client.get("/api/runs/20260901T120000Z/topics").json()

    assert [entry["topic"]["topic_id"] for entry in body] == ["loud", "quiet"]
    assert [entry["above_cut"] for entry in body] == [True, False]


def test_the_ranking_is_ordered_by_the_stored_rank(tmp_path):
    """final_rank was written with sentiment.rank_score. The endpoint sorts
    by nothing of its own - a second implementation of the blend would
    drift from the evaluate checkpoint silently."""
    client = seeded_client(
        tmp_path,
        runs=[
            SeededRun(
                topics=[
                    make_topic("third", trend_score=0.1),
                    make_topic("first", trend_score=0.9),
                    make_topic("second", trend_score=0.5),
                ]
            )
        ],
    )

    body = client.get("/api/runs/20260901T120000Z/topics").json()

    assert [entry["topic"]["final_rank"] for entry in body] == [1, 2, 3]
    assert [entry["topic"]["topic_id"] for entry in body] == [
        "first",
        "second",
        "third",
    ]


def test_each_topic_carries_its_render_count(tmp_path):
    """`no memes yet` on a card is the cue to go and generate some, so a
    zero has to be a real zero rather than a missing key."""
    client = seeded_client(
        tmp_path,
        runs=[
            SeededRun(
                topics=[make_topic("cats"), make_topic("dogs")],
                renders=[
                    make_render_record("a", topic_id="cats"),
                    make_render_record("b", topic_id="cats"),
                ],
            )
        ],
    )

    body = {
        entry["topic"]["topic_id"]: entry["render_count"]
        for entry in client.get("/api/runs/20260901T120000Z/topics").json()
    }

    assert body == {"cats": 2, "dogs": 0}


def test_the_ranking_of_an_unknown_run_is_a_404(tmp_path):
    client = seeded_client(tmp_path)

    assert client.get("/api/runs/nope/topics").status_code == 404


def _evidence_for(source_ids: list[str], replies: list[Reply]) -> TrendEvidence:
    now = datetime(2026, 9, 1, tzinfo=UTC)
    return TrendEvidence(
        trend=TrendInfo(
            topic_id="t",
            display_name="Cats",
            started_at=now,
            status="trending",
        ),
        posts=[
            PostEvidence(
                item=Item(
                    source_id=source_id,
                    title="a post",
                    permalink=f"https://bsky.app/{source_id}",
                    fetched_at=now,
                    metrics=BlueskyMetrics(
                        like_count=1,
                        reply_count=1,
                        repost_count=0,
                        trend="Cats",
                        status="trending",
                        created_at=now,
                    ),
                ),
                replies=replies,
            )
            for source_id in source_ids
        ],
    )


def _reply(text: str, likes: int) -> Reply:
    return Reply(
        text=text,
        like_count=likes,
        created_at=datetime(2026, 9, 1, tzinfo=UTC),
        author_key="a",
    )


def test_topic_detail_carries_the_dossier(tmp_path):
    client = seeded_client(
        tmp_path,
        runs=[
            SeededRun(
                topics=[
                    make_topic(
                        "cats",
                        dossier=make_dossier(event_sentiment=Sentiment.CUTE),
                    )
                ]
            )
        ],
    )

    body = client.get("/api/runs/20260901T120000Z/topics/cats").json()

    assert body["dossier"]["event_sentiment"] == "cute"
    assert body["dossier"]["what_happened"]


def test_topic_detail_carries_the_score_breakdown(tmp_path):
    """The spec lists score_components alongside dossier and phrases as part
    of this endpoint's contract; an implementation that kept dossier but
    dropped this field would pass every other test here."""
    client = seeded_client(
        tmp_path,
        runs=[
            SeededRun(
                topics=[
                    make_topic(
                        "cats",
                        score_components={"bluesky": 0.7, "corroboration": 0.4},
                    )
                ]
            )
        ],
    )

    body = client.get("/api/runs/20260901T120000Z/topics/cats").json()

    assert body["score_components"] == {"bluesky": 0.7, "corroboration": 0.4}


def test_topic_detail_reports_no_score_breakdown_for_a_pruned_checkpoint(tmp_path):
    """The analyse checkpoint holds score_components; when it has been
    pruned there is nothing to report, and the response should say so with
    {} rather than raising or fabricating a value."""
    client = seeded_client(
        tmp_path, runs=[SeededRun(topics=[make_topic("cats")], evidence=[])]
    )
    store = Store(api_settings(tmp_path).db_path)
    store._conn.execute(
        "DELETE FROM checkpoints WHERE run_id = ? AND stage = ?",
        ("20260901T120000Z", "analyse"),
    )
    store._conn.commit()
    store.close()

    body = client.get("/api/runs/20260901T120000Z/topics/cats").json()

    assert body["score_components"] == {}


def test_topic_detail_carries_the_replies_most_liked_first(tmp_path):
    client = seeded_client(
        tmp_path,
        runs=[
            SeededRun(
                topics=[make_topic("cats", item_ids=["p1"])],
                evidence=[
                    _evidence_for(["p1"], [_reply("quiet", 1), _reply("loud", 99)])
                ],
            )
        ],
    )

    body = client.get("/api/runs/20260901T120000Z/topics/cats").json()

    assert [r["text"] for r in body["replies"]] == ["loud", "quiet"]


def test_replies_come_only_from_this_topics_own_posts(tmp_path):
    """item_ids is what ties a topic to its evidence. Returning every reply
    in the run would put another topic's conversation on this dossier."""
    client = seeded_client(
        tmp_path,
        runs=[
            SeededRun(
                topics=[make_topic("cats", item_ids=["p1"])],
                evidence=[
                    _evidence_for(["p1"], [_reply("mine", 1)]),
                    _evidence_for(["p2"], [_reply("theirs", 1)]),
                ],
            )
        ],
    )

    body = client.get("/api/runs/20260901T120000Z/topics/cats").json()

    assert [r["text"] for r in body["replies"]] == ["mine"]


def test_a_reply_never_carries_an_author_key(tmp_path):
    """author_key exists to count distinct accounts behind a phrase. The
    project stores no personal data and an API returning it would undo
    that."""
    client = seeded_client(
        tmp_path,
        runs=[
            SeededRun(
                topics=[make_topic("cats", item_ids=["p1"])],
                evidence=[_evidence_for(["p1"], [_reply("hello", 1)])],
            )
        ],
    )

    raw = client.get("/api/runs/20260901T120000Z/topics/cats").text

    assert "author_key" not in raw


def test_replies_are_capped_after_sorting_not_before(tmp_path):
    """A topic can carry hundreds of replies and the card list is not
    paginated. Nothing else here supplies more than a handful, so removing
    the slice entirely would pass every other reply test — and capping
    before the sort rather than after would keep an arbitrary twenty
    instead of the twenty people actually engaged with."""
    client = seeded_client(
        tmp_path,
        runs=[
            SeededRun(
                topics=[make_topic("cats", item_ids=["p1"])],
                evidence=[
                    _evidence_for(["p1"], [_reply(f"reply {i}", i) for i in range(50)])
                ],
            )
        ],
    )

    body = client.get("/api/runs/20260901T120000Z/topics/cats").json()

    assert len(body["replies"]) == MAX_REPLIES
    assert body["replies"][0]["text"] == "reply 49"


def test_topic_detail_reports_how_many_runs_the_topic_appeared_in(tmp_path):
    """`SEEN IN 3 RUNS` on the card. Keyed on the label slug, which is the
    only cross-run identity the store has."""
    client = seeded_client(
        tmp_path,
        runs=[
            SeededRun(run_id="20260901T100000Z", topics=[make_topic("cats")]),
            SeededRun(run_id="20260901T120000Z", topics=[make_topic("cats")]),
        ],
    )

    body = client.get("/api/runs/20260901T120000Z/topics/cats").json()

    assert body["recurrence"]["run_count"] == 2
    assert body["recurrence"]["first_seen_run_id"] == "20260901T100000Z"


def test_topic_detail_survives_a_run_whose_evidence_was_pruned(tmp_path):
    """The ingest checkpoint is the biggest thing in the database and a
    later phase may prune it. A dossier without replies is still a dossier;
    a 500 is not."""
    client = seeded_client(
        tmp_path, runs=[SeededRun(topics=[make_topic("cats")], evidence=[])]
    )

    body = client.get("/api/runs/20260901T120000Z/topics/cats").json()

    assert body["replies"] == []
    assert body["dossier"] is not None


def test_topic_detail_reports_no_dossier_for_a_dormant_topic(tmp_path):
    """A topic can be ranked with no dossier at all — the dormant path never
    built one — with the analyse checkpoint present and intact. That is a
    different state from the pruned-checkpoint case above, and nothing else
    exercises it."""
    client = seeded_client(
        tmp_path, runs=[SeededRun(topics=[make_topic("cats", dossier=None)])]
    )

    body = client.get("/api/runs/20260901T120000Z/topics/cats").json()

    assert body["dossier"] is None
    assert body["topic"]["topic_id"] == "cats"


def test_an_unknown_topic_is_a_404(tmp_path):
    client = seeded_client(tmp_path, runs=[SeededRun(topics=[make_topic("cats")])])

    assert client.get("/api/runs/20260901T120000Z/topics/nope").status_code == 404


def test_an_unknown_run_on_the_topic_route_names_the_run_not_the_topic(tmp_path):
    """read_topic used to resolve its 404 off store.run_topics(run_id)
    returning no match, rather than off store.get_run — so an unknown run
    reported the topic-specific message ("No such topic in {run}: {topic}")
    instead of the run-specific one every sibling handler uses. Routing it
    through _run_or_404 makes an unknown run report itself here exactly as
    it does on the other three run-scoped routes."""
    client = seeded_client(tmp_path)

    response = client.get("/api/runs/nope/topics/cats")

    assert response.status_code == 404
    assert response.json()["detail"] == "No such run: nope"


def test_an_unknown_topic_in_a_real_run_still_names_the_topic(tmp_path):
    """The fix for the case above must not blur into reporting every 404 on
    this route as a run problem — a real run with no such topic still gets
    the topic-specific message."""
    client = seeded_client(tmp_path, runs=[SeededRun(topics=[make_topic("cats")])])

    response = client.get("/api/runs/20260901T120000Z/topics/nope")

    assert response.status_code == 404
    assert response.json()["detail"] == "No such topic in 20260901T120000Z: nope"


def test_the_log_of_a_run_with_no_lines_is_empty(tmp_path):
    """Nothing writes log lines until phase 3 adds capture. The endpoint
    exists now because it is part of the contract phase 5 builds against."""
    client = seeded_client(tmp_path, runs=[SeededRun()])

    body = client.get("/api/runs/20260901T120000Z/log").json()

    assert body == []


def test_the_log_endpoint_filters_on_verbose(tmp_path):
    client = seeded_client(tmp_path, runs=[SeededRun()])
    store = Store(api_settings(tmp_path).db_path)
    store._conn.execute(
        "INSERT INTO log_lines (run_id, seq, logged_at, level, logger, message) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            "20260901T120000Z",
            1,
            "2026-09-01T12:00:00+00:00",
            "DEBUG",
            "zeitgeist.pipeline",
            "noisy",
        ),
    )
    store._conn.commit()
    store.close()

    quiet = client.get("/api/runs/20260901T120000Z/log").json()
    loud = client.get(
        "/api/runs/20260901T120000Z/log", params={"verbose": "true"}
    ).json()

    assert quiet == []
    assert [line["message"] for line in loud] == ["noisy"]


def test_the_log_of_an_unknown_run_is_a_404(tmp_path):
    client = seeded_client(tmp_path)

    assert client.get("/api/runs/nope/log").status_code == 404
