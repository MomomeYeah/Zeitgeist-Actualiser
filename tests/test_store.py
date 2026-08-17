from zeitgeist.models import Topic
from zeitgeist.store import Store


def _topic(label: str, score: float) -> Topic:
    return Topic(
        id=label.lower(),
        label=label,
        summary=f"About {label}.",
        post_ids=["p1"],
        trend_score=score,
    )


def _store(tmp_path) -> Store:
    store = Store(tmp_path / "test.db")
    store.init_schema()
    return store


def test_previous_scores_is_empty_on_first_run(tmp_path):
    store = _store(tmp_path)
    assert store.previous_scores(exclude_run_id="run1") == {}


def test_records_and_reads_back_topic_scores(tmp_path):
    store = _store(tmp_path)
    store.start_run("run1")
    store.record_topics("run1", [_topic("Cats", 0.8)])
    store.finish_run("run1", status="ok", post_count=10)

    assert store.previous_scores(exclude_run_id="run2") == {"Cats": 0.8}


def test_current_run_is_excluded_from_its_own_history(tmp_path):
    store = _store(tmp_path)
    store.start_run("run1")
    store.record_topics("run1", [_topic("Cats", 0.8)])

    assert store.previous_scores(exclude_run_id="run1") == {}


def test_most_recent_prior_run_wins(tmp_path):
    store = _store(tmp_path)
    for run_id, score in [("run1", 0.2), ("run2", 0.5), ("run3", 0.9)]:
        store.start_run(run_id)
        store.record_topics(run_id, [_topic("Cats", score)])
        store.finish_run(run_id, status="ok", post_count=10)

    assert store.previous_scores(exclude_run_id="run4") == {"Cats": 0.9}


def test_each_label_tracks_its_own_history(tmp_path):
    """Guards the correlated subquery: a naive MAX over all runs would give
    every label the newest run's score.
    """
    store = _store(tmp_path)
    store.start_run("run1")
    store.record_topics("run1", [_topic("Cats", 0.2), _topic("Dogs", 0.9)])
    store.finish_run("run1", status="ok", post_count=10)

    store.start_run("run2")
    store.record_topics("run2", [_topic("Cats", 0.7)])
    store.finish_run("run2", status="ok", post_count=10)

    assert store.previous_scores(exclude_run_id="run3") == {"Cats": 0.7, "Dogs": 0.9}


def test_finish_run_records_the_outcome(tmp_path):
    """Without this, deleting the body of finish_run breaks no test, and the
    CLI's closing summary silently reports nothing.
    """
    store = _store(tmp_path)
    store.start_run("run1")
    assert store.run_summary("run1") == {
        "status": None,
        "post_count": None,
        "finished_at": None,
    }

    store.finish_run("run1", status="ok", post_count=42)
    summary = store.run_summary("run1")
    assert summary["status"] == "ok"
    assert summary["post_count"] == 42
    assert summary["finished_at"] is not None


def test_run_summary_is_none_for_an_unknown_run(tmp_path):
    assert _store(tmp_path).run_summary("never-happened") is None


def test_init_schema_is_idempotent(tmp_path):
    """The CLI calls init_schema on every run, so a bare CREATE TABLE would
    fail the second time anyone used the tool.
    """
    store = Store(tmp_path / "test.db")
    store.init_schema()
    store.init_schema()
    assert store.previous_scores(exclude_run_id="x") == {}


def test_creates_parent_directory(tmp_path):
    """data/ is gitignored, so it does not exist on a fresh clone."""
    store = Store(tmp_path / "nested" / "dir" / "test.db")
    store.init_schema()
    assert (tmp_path / "nested" / "dir" / "test.db").exists()
