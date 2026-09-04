from tests.api_factory import SeededRun, seeded_client
from tests.run_factory import make_dossier, make_render_record, make_topic
from zeitgeist.models import Sentiment


def test_a_topic_seen_in_several_runs_appears_once(tmp_path):
    """The index is deduplicated across the window: `SEEN IN 3 RUNS` is one
    card, not three."""
    client = seeded_client(
        tmp_path,
        runs=[
            SeededRun(run_id="20260901T100000Z", topics=[make_topic("cats")]),
            SeededRun(run_id="20260901T110000Z", topics=[make_topic("cats")]),
        ],
    )

    body = client.get("/api/topics").json()

    assert [entry["topic"]["topic_id"] for entry in body["topics"]] == ["cats"]
    assert body["topics"][0]["run_count"] == 2


def test_the_newest_occurrence_wins(tmp_path):
    """A deduplicated card shows current scores, not the first sighting's."""
    client = seeded_client(
        tmp_path,
        runs=[
            SeededRun(
                run_id="20260901T100000Z",
                topics=[make_topic("cats", trend_score=0.1)],
            ),
            SeededRun(
                run_id="20260901T110000Z",
                topics=[make_topic("cats", trend_score=0.9)],
            ),
        ],
    )

    body = client.get("/api/topics").json()

    assert body["topics"][0]["topic"]["trend_score"] == 0.9
    assert body["topics"][0]["topic"]["run_id"] == "20260901T110000Z"


def test_the_window_bounds_how_many_runs_are_considered(tmp_path):
    client = seeded_client(
        tmp_path,
        runs=[
            SeededRun(run_id="20260901T100000Z", topics=[make_topic("old")]),
            SeededRun(run_id="20260901T110000Z", topics=[make_topic("new")]),
        ],
    )

    body = client.get("/api/topics", params={"window": 1}).json()

    assert [entry["topic"]["topic_id"] for entry in body["topics"]] == ["new"]


def test_the_status_filter_narrows_the_list(tmp_path):
    client = seeded_client(
        tmp_path,
        runs=[
            SeededRun(
                topics=[
                    make_topic("hot", trend_status="trending"),
                    make_topic("cold", trend_status="cooling"),
                ]
            )
        ],
    )

    body = client.get("/api/topics", params={"status": "cooling"}).json()

    assert [entry["topic"]["topic_id"] for entry in body["topics"]] == ["cold"]


def test_status_totals_count_the_whole_window_not_the_filtered_list(tmp_path):
    """The filter chips show `trending 9 / saturating 6 / cooling 4` while
    one of them is active, so the totals cannot come from the filtered
    result."""
    client = seeded_client(
        tmp_path,
        runs=[
            SeededRun(
                topics=[
                    make_topic("hot", trend_status="trending"),
                    make_topic("cold", trend_status="cooling"),
                ]
            )
        ],
    )

    body = client.get("/api/topics", params={"status": "cooling"}).json()

    assert body["status_totals"] == {"trending": 1, "cooling": 1}


def test_the_sentiment_distribution_covers_the_window(tmp_path):
    """The mood bar is one segment per sentiment sized by share."""
    client = seeded_client(
        tmp_path,
        runs=[
            SeededRun(
                topics=[
                    make_topic(
                        "a", dossier=make_dossier(event_sentiment=Sentiment.FUNNY)
                    ),
                    make_topic(
                        "b", dossier=make_dossier(event_sentiment=Sentiment.FUNNY)
                    ),
                    make_topic(
                        "c", dossier=make_dossier(event_sentiment=Sentiment.CUTE)
                    ),
                ]
            )
        ],
    )

    body = client.get("/api/topics").json()

    assert body["sentiment_totals"] == {"funny": 2, "cute": 1}


def test_the_previous_run_distribution_is_reported_separately(tmp_path):
    """The mood line reads `versus the previous run`, so the comparison has
    to arrive without a second request."""
    client = seeded_client(
        tmp_path,
        runs=[
            SeededRun(
                run_id="20260901T100000Z",
                topics=[
                    make_topic(
                        "old", dossier=make_dossier(event_sentiment=Sentiment.SAD)
                    )
                ],
            ),
            SeededRun(
                run_id="20260901T110000Z",
                topics=[
                    make_topic(
                        "new",
                        dossier=make_dossier(event_sentiment=Sentiment.FUNNY),
                    )
                ],
            ),
        ],
    )

    body = client.get("/api/topics", params={"window": 1}).json()

    assert body["sentiment_totals"] == {"funny": 1}
    assert body["previous_sentiment_totals"] == {"sad": 1}


def test_each_indexed_topic_carries_its_render_count(tmp_path):
    """The card's meme score sits beside a count that comes from the
    topic's own run — the newest occurrence — the same way `run_count`
    does. Nothing else in this module reads it, so a lookup keyed by topic
    id alone, colliding across runs, would pass every other test."""
    client = seeded_client(
        tmp_path,
        runs=[
            SeededRun(
                topics=[make_topic("cats")],
                renders=[
                    make_render_record("a", topic_id="cats"),
                    make_render_record("b", topic_id="cats"),
                ],
            )
        ],
    )

    body = client.get("/api/topics").json()

    assert body["topics"][0]["render_count"] == 2


def test_an_empty_database_returns_an_empty_index(tmp_path):
    client = seeded_client(tmp_path)

    body = client.get("/api/topics").json()

    assert body == {
        "topics": [],
        "status_totals": {},
        "sentiment_totals": {},
        "previous_sentiment_totals": {},
    }
