import sqlite3

import pytest

from tests.run_factory import make_run_config
from zeitgeist.analysis.slug import slugify
from zeitgeist.models import Topic
from zeitgeist.records import RunError, Stage
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


def test_schema_creates_every_table_the_ui_reads(tmp_path):
    store = Store(tmp_path / "z.db")
    store.init_schema()

    names = {
        row[0]
        for row in store._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }

    assert {
        "checkpoints",
        "run_records",
        "run_stages",
        "run_topics",
        "renders",
        "log_lines",
        "settings",
        "topic_scores",
    } <= names


def test_a_reader_is_not_blocked_by_an_open_write(tmp_path):
    """The worker writes while the API reads. Without WAL the reader waits
    for the writer and the in-flight poll hitches every time a stage
    checkpoints; with it the reader sees the last committed snapshot.

    Asserts the behaviour rather than `PRAGMA journal_mode`, which would
    fail only if someone changed the setting on purpose.
    """
    path = tmp_path / "z.db"
    writer = Store(path)
    writer.init_schema()
    writer.start_run("r1", make_run_config())

    writer._conn.execute("BEGIN IMMEDIATE")
    writer._conn.execute(
        "INSERT INTO checkpoints (run_id, stage, payload, written_at) "
        "VALUES ('r2', 'ingest', '[]', '2026-09-01T00:00:00+00:00')"
    )

    # timeout=0.1 so a rollback-journal database fails fast rather than
    # hanging for sqlite3's five-second default.
    reader = sqlite3.connect(path, timeout=0.1)
    try:
        [(count,)] = reader.execute("SELECT COUNT(*) FROM run_records").fetchall()
    finally:
        reader.close()
        writer._conn.rollback()
        writer.close()

    assert count == 1


def test_a_database_from_an_older_schema_is_refused(tmp_path):
    path = tmp_path / "z.db"
    store = Store(path)
    store.init_schema()
    store._conn.execute("PRAGMA user_version = 2")
    store._conn.commit()
    store.close()

    with pytest.raises(StoreSchemaError, match="version 2"):
        Store(path).init_schema()


def test_a_started_run_records_the_config_it_froze(tmp_path):
    """Run detail's config line and Re-run config both need what the run
    used, which a since-edited .env cannot supply."""
    store = _store(tmp_path)
    config = make_run_config(top_count=9, llm_model="qwen3.5")

    store.start_run("r1", config)

    record = store.get_run("r1")
    assert record is not None
    assert record.status == "running"
    assert record.config.top_count == 9
    assert record.config.llm_model == "qwen3.5"
    assert record.finished_at is None


def test_finishing_a_run_records_the_counts_the_runs_list_shows(tmp_path):
    store = _store(tmp_path)
    store.start_run("r1", make_run_config())

    store.finish_run(
        "r1",
        status="ok",
        item_count=214,
        trends_found=25,
        topics_kept=5,
        phrases_found=31,
    )

    record = store.get_run("r1")
    assert record is not None
    assert record.status == "ok"
    # All four, not a sample: they are four ints bound positionally in one
    # UPDATE, which is exactly the shape a swap hides in.
    assert (
        record.item_count,
        record.trends_found,
        record.topics_kept,
        record.phrases_found,
    ) == (214, 25, 5, 31)
    assert record.finished_at is not None


def test_a_failed_run_records_the_error_and_the_stage(tmp_path):
    """Today a failure leaves a NULL status and the reason is only printed.
    The Runs screen renders the class, the stage and the message."""
    store = _store(tmp_path)
    store.start_run("r1", make_run_config())

    store.fail_run(
        "r1",
        RunError(kind="SourceError", message="no trends returned", stage=Stage.INGEST),
    )

    record = store.get_run("r1")
    assert record is not None
    assert record.status == "failed"
    assert record.error is not None
    assert record.error.kind == "SourceError"
    assert record.error.stage is Stage.INGEST


def test_get_run_returns_none_for_a_run_that_does_not_exist(tmp_path):
    assert _store(tmp_path).get_run("nope") is None


def test_previous_sub_scores_are_keyed_by_platform_then_label_slug(tmp_path):
    store = Store(tmp_path / "z.db")
    store.init_schema()
    store.start_run("r1", make_run_config())
    store.record_topics("r1", [_topic("Shelter Dog Adoption", {"lemmy": 0.7})])
    store.finish_run(
        "r1", status="ok", item_count=1, trends_found=1, topics_kept=1, phrases_found=0
    )
    store.start_run("r2", make_run_config())

    previous = store.previous_sub_scores("r2")

    assert previous == {"lemmy": {"shelter-dog-adoption": 0.7}}


def test_sub_scores_from_different_platforms_do_not_collide(tmp_path):
    """Both platforms saw the same topic; each must keep its own number.
    A schema keyed only on (run_id, label) would silently lose one."""
    store = Store(tmp_path / "z.db")
    store.init_schema()
    store.start_run("r1", make_run_config())
    store.record_topics("r1", [_topic("Cats", {"lemmy": 0.4, "wikipedia": 0.9})])
    store.finish_run(
        "r1", status="ok", item_count=1, trends_found=1, topics_kept=1, phrases_found=0
    )
    store.start_run("r2", make_run_config())

    previous = store.previous_sub_scores("r2")

    assert previous["lemmy"]["cats"] == 0.4
    assert previous["wikipedia"]["cats"] == 0.9


def test_corroboration_is_not_persisted_as_a_platform(tmp_path):
    """score_components carries a 'corroboration' key that is a multiplier,
    not a platform sub-score. Persisting it would make the next run's
    rank-delta compare a score against a multiplier."""
    store = Store(tmp_path / "z.db")
    store.init_schema()
    store.start_run("r1", make_run_config())
    store.record_topics("r1", [_topic("Cats", {"lemmy": 0.4, "corroboration": 1.25})])
    store.finish_run(
        "r1", status="ok", item_count=1, trends_found=1, topics_kept=1, phrases_found=0
    )
    store.start_run("r2", make_run_config())

    previous = store.previous_sub_scores("r2")

    assert "corroboration" not in previous


def test_a_stale_database_is_rejected_with_an_actionable_message(tmp_path):
    """CREATE TABLE IF NOT EXISTS accepts an old schema silently and fails
    later with something cryptic. This turns it into a startup failure."""
    path = tmp_path / "z.db"
    store = Store(path)
    store.init_schema()
    store._conn.execute("PRAGMA user_version = 1")
    store._conn.commit()
    store.close()

    # Matches the variable part — which file, and which versions — rather
    # than the fixed prose, following the same pattern as
    # tests/test_config.py's match="mastodon". Rewording the instruction is
    # a decision; failing to name the file the user must delete is a bug,
    # because the message is the only place that path appears.
    with pytest.raises(StoreSchemaError, match=r"z\.db.*version 1.*expects 3"):
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
        store.start_run(run_id, make_run_config())
        store.record_topics(run_id, [_topic("Cats", {"lemmy": sub_score})])
        store.finish_run(
            run_id,
            status="ok",
            item_count=1,
            trends_found=1,
            topics_kept=1,
            phrases_found=0,
        )

    assert store.previous_sub_scores("r4") == {"lemmy": {"cats": 0.9}}


def test_each_label_and_platform_tracks_its_own_history(tmp_path):
    """Guards both correlations: a naive MAX over all runs would give every
    label the newest run's score, and dropping `s2.platform = s.platform`
    would let one platform's newer row hide another platform's older one.
    """
    store = Store(tmp_path / "z.db")
    store.init_schema()
    store.start_run("r1", make_run_config())
    store.record_topics(
        "r1",
        [
            _topic("Cats", {"lemmy": 0.2, "wikipedia": 0.6}),
            _topic("Dogs", {"lemmy": 0.9}),
        ],
    )
    store.finish_run(
        "r1", status="ok", item_count=2, trends_found=2, topics_kept=2, phrases_found=0
    )

    store.start_run("r2", make_run_config())
    store.record_topics("r2", [_topic("Cats", {"lemmy": 0.7})])
    store.finish_run(
        "r2", status="ok", item_count=1, trends_found=1, topics_kept=1, phrases_found=0
    )

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
    store.start_run("r1", make_run_config())
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
    store.start_run("r1", make_run_config())
    store.record_topics("r1", [_topic("Cats", {"lemmy": 0.2})])
    store.finish_run(
        "r1", status="ok", item_count=1, trends_found=1, topics_kept=1, phrases_found=0
    )

    store.start_run("r2", make_run_config())
    store.record_topics("r2", [_topic("Cats", {"lemmy": 0.99})])
    store.finish_run(
        "r2", status="ok", item_count=1, trends_found=1, topics_kept=1, phrases_found=0
    )

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
    store.start_run("r1", make_run_config())
    store.record_topics("r1", [_topic("Shelter Dog Adoption", {"lemmy": 0.8})])
    store.finish_run(
        "r1", status="ok", item_count=1, trends_found=1, topics_kept=1, phrases_found=0
    )

    previous = store.previous_sub_scores("r2")
    assert previous["lemmy"].get(slugify("shelter dog adoption")) == 0.8


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
