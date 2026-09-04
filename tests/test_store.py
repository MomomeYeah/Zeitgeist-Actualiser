import pytest

from zeitgeist.analysis.slug import slugify
from zeitgeist.models import Topic
from zeitgeist.store import SCHEMA_VERSION, Store, StoreSchemaError


def _topic(label: str, components: dict[str, float]) -> Topic:
    return Topic(
        id=label.lower(),
        label=label,
        summary=f"About {label}.",
        item_ids=["x"],
        trend_status="trending",
        score_components=components,
    )


def _store(tmp_path) -> Store:
    store = Store(tmp_path / "test.db")
    store.init_schema()
    return store


def test_previous_sub_scores_are_keyed_by_platform_then_label_slug(tmp_path):
    store = Store(tmp_path / "z.db")
    store.init_schema()
    store.start_run("r1")
    store.record_topics("r1", [_topic("Shelter Dog Adoption", {"lemmy": 0.7})])
    store.finish_run("r1", status="ok", item_count=1)
    store.start_run("r2")

    previous = store.previous_sub_scores("r2")

    assert previous == {"lemmy": {"shelter-dog-adoption": 0.7}}


def test_sub_scores_from_different_platforms_do_not_collide(tmp_path):
    """Both platforms saw the same topic; each must keep its own number.
    A schema keyed only on (run_id, label) would silently lose one."""
    store = Store(tmp_path / "z.db")
    store.init_schema()
    store.start_run("r1")
    store.record_topics("r1", [_topic("Cats", {"lemmy": 0.4, "wikipedia": 0.9})])
    store.finish_run("r1", status="ok", item_count=1)
    store.start_run("r2")

    previous = store.previous_sub_scores("r2")

    assert previous["lemmy"]["cats"] == 0.4
    assert previous["wikipedia"]["cats"] == 0.9


def test_corroboration_is_not_persisted_as_a_platform(tmp_path):
    """score_components carries a 'corroboration' key that is a multiplier,
    not a platform sub-score. Persisting it would make the next run's
    rank-delta compare a score against a multiplier."""
    store = Store(tmp_path / "z.db")
    store.init_schema()
    store.start_run("r1")
    store.record_topics("r1", [_topic("Cats", {"lemmy": 0.4, "corroboration": 1.25})])
    store.finish_run("r1", status="ok", item_count=1)
    store.start_run("r2")

    previous = store.previous_sub_scores("r2")

    assert "corroboration" not in previous


def test_a_stale_database_is_rejected_with_an_actionable_message(tmp_path):
    """CREATE TABLE IF NOT EXISTS accepts an old schema silently and fails
    later with something cryptic. This turns it into a startup failure."""
    path = tmp_path / "z.db"
    import sqlite3

    conn = sqlite3.connect(path)
    conn.executescript("CREATE TABLE runs (run_id TEXT PRIMARY KEY);")
    conn.execute("PRAGMA user_version = 1")
    conn.commit()
    conn.close()

    # Matches the variable part — which file, and which versions — rather
    # than the fixed prose, following the same pattern as
    # tests/test_config.py's match="mastodon". Rewording the instruction is
    # a decision; failing to name the file the user must delete is a bug,
    # because the message is the only place that path appears.
    with pytest.raises(StoreSchemaError, match=r"z\.db.*version 1.*expects 2"):
        Store(path).init_schema()


def test_a_fresh_database_is_stamped_with_the_current_version(tmp_path):
    store = Store(tmp_path / "z.db")
    store.init_schema()

    version = store._conn.execute("PRAGMA user_version").fetchone()[0]
    assert version == SCHEMA_VERSION


def test_previous_sub_scores_is_empty_on_the_first_run(tmp_path):
    store = Store(tmp_path / "z.db")
    store.init_schema()

    assert store.previous_sub_scores("r1") == {}


def test_the_most_recent_prior_run_wins(tmp_path):
    """Guards MAX(started_at): without it the lookup returns whichever row
    SQLite happened to visit first, so rank-delta compares against an
    arbitrarily old score.
    """
    store = Store(tmp_path / "z.db")
    store.init_schema()
    for run_id, sub_score in [("r1", 0.2), ("r2", 0.5), ("r3", 0.9)]:
        store.start_run(run_id)
        store.record_topics(run_id, [_topic("Cats", {"lemmy": sub_score})])
        store.finish_run(run_id, status="ok", item_count=1)

    assert store.previous_sub_scores("r4") == {"lemmy": {"cats": 0.9}}


def test_each_label_and_platform_tracks_its_own_history(tmp_path):
    """Guards both correlations: a naive MAX over all runs would give every
    label the newest run's score, and dropping `s2.platform = s.platform`
    would let one platform's newer row hide another platform's older one.
    """
    store = Store(tmp_path / "z.db")
    store.init_schema()
    store.start_run("r1")
    store.record_topics(
        "r1",
        [
            _topic("Cats", {"lemmy": 0.2, "wikipedia": 0.6}),
            _topic("Dogs", {"lemmy": 0.9}),
        ],
    )
    store.finish_run("r1", status="ok", item_count=2)

    store.start_run("r2")
    store.record_topics("r2", [_topic("Cats", {"lemmy": 0.7})])
    store.finish_run("r2", status="ok", item_count=1)

    assert store.previous_sub_scores("r3") == {
        "lemmy": {"cats": 0.7, "dogs": 0.9},
        "wikipedia": {"cats": 0.6},
    }


def test_the_current_run_is_excluded_from_its_own_history(tmp_path):
    """Guards the outer `s.run_id != ?`. Without it a run reads back the
    sub-scores it has just written, so every raw delta is base minus itself
    — zero — and rank_delta goes inert against real data without failing
    anything. The excluded run is the only run here, so no other test in
    this file can tell the two implementations apart.
    """
    store = Store(tmp_path / "z.db")
    store.init_schema()
    store.start_run("r1")
    store.record_topics("r1", [_topic("Cats", {"lemmy": 0.8})])

    assert store.previous_sub_scores("r1") == {}


def test_the_excluded_runs_own_rows_do_not_hide_the_older_run(tmp_path):
    """Guards the subquery's own `s2.run_id != ?`. Without it the excluded
    run — the newest for this label and platform — sets MAX(started_at) to a
    timestamp no included row can match, dropping the label from the result
    entirely instead of falling back to the older run's score.
    """
    store = Store(tmp_path / "z.db")
    store.init_schema()
    store.start_run("r1")
    store.record_topics("r1", [_topic("Cats", {"lemmy": 0.2})])
    store.finish_run("r1", status="ok", item_count=1)

    store.start_run("r2")
    store.record_topics("r2", [_topic("Cats", {"lemmy": 0.99})])
    store.finish_run("r2", status="ok", item_count=1)

    assert store.previous_sub_scores("r2") == {"lemmy": {"cats": 0.2}}


def test_relabelled_topic_is_still_matched_across_runs(tmp_path):
    """Labels are free text the LLM regenerates every run, so the same
    subject often comes back with different casing or punctuation. A topic
    recorded as "Shelter Dog Adoption" must still be found by a later run
    that labels the same subject "shelter dog adoption" — otherwise
    rank_delta (25% of trend_score) is inert against real data, since every
    label would look brand new every run.
    """
    store = Store(tmp_path / "z.db")
    store.init_schema()
    store.start_run("r1")
    store.record_topics("r1", [_topic("Shelter Dog Adoption", {"lemmy": 0.8})])
    store.finish_run("r1", status="ok", item_count=1)

    previous = store.previous_sub_scores("r2")
    assert previous["lemmy"].get(slugify("shelter dog adoption")) == 0.8


def test_finish_run_records_the_outcome_and_item_count(tmp_path):
    """Without this, deleting the body of finish_run breaks no test, and the
    CLI's closing summary silently reports nothing.
    """
    store = _store(tmp_path)
    store.start_run("run1")
    assert store.run_summary("run1") == {
        "status": None,
        "item_count": None,
        "finished_at": None,
    }

    store.finish_run("run1", status="ok", item_count=42)
    summary = store.run_summary("run1")
    assert summary is not None
    assert summary["status"] == "ok"
    assert summary["item_count"] == 42
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
    assert store.previous_sub_scores("x") == {}


def test_creates_parent_directory(tmp_path):
    """data/ is gitignored, so it does not exist on a fresh clone."""
    store = Store(tmp_path / "nested" / "dir" / "test.db")
    store.init_schema()
    assert (tmp_path / "nested" / "dir" / "test.db").exists()
