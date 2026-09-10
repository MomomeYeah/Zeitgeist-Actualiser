import sqlite3
import threading
from datetime import UTC, datetime

import pytest

from tests.run_factory import (
    make_render_record,
    make_run_config,
    make_stage_record,
    make_topic,
)
from zeitgeist.analysis.slug import slugify
from zeitgeist.logcapture import CapturedLine
from zeitgeist.models import (
    BlueskyMetrics,
    Item,
    MediaBrief,
    PostEvidence,
    Topic,
    TrendEvidence,
    TrendInfo,
)
from zeitgeist.projection import flatten
from zeitgeist.records import AutoOrigin, ManualOrigin, RunError, Stage
from zeitgeist.store import SCHEMA_VERSION, MissingCheckpoint, Store, StoreSchemaError


def _topic(label: str, components: dict[str, float]) -> Topic:
    return Topic(
        id=label.lower(),
        label=label,
        summary=f"About {label}.",
        item_ids=["x"],
        trend_status="trending",
        score_components=components,
    )


def _trend_evidence() -> TrendEvidence:
    metrics = BlueskyMetrics(
        like_count=12,
        reply_count=3,
        repost_count=4,
        trend="airport cat",
        status="trending",
        created_at=datetime(2026, 9, 1, tzinfo=UTC),
    )
    item = Item(
        source_id="at://post/1",
        title="A cat got into an airport.",
        permalink="https://bsky.app/post/1",
        fetched_at=datetime(2026, 9, 1, tzinfo=UTC),
        metrics=metrics,
    )
    return TrendEvidence(
        trend=TrendInfo(
            topic_id="airport-cat",
            display_name="Airport Cat",
            started_at=datetime(2026, 9, 1, tzinfo=UTC),
            status="trending",
        ),
        posts=[PostEvidence(item=item)],
    )


def _store(tmp_path) -> Store:
    store = Store(tmp_path / "test.db")
    store.init_schema()
    return store


def _analyse(store: Store, run_id: str, topics: list[Topic]) -> None:
    """Persist a run's topics the one way production does.

    `topic_scores` has no writer of its own: it is filled inside the analyse
    checkpoint's transaction. Building the table by hand in the history tests
    below would let that transaction stop writing it without a single failure
    here.

    `start_run` runs first because `previous_sub_scores` joins `topic_scores`
    to `run_records` to order by `started_at`: a run with no `run_records`
    row is invisible to that join, however faithfully its checkpoint was
    written. Production always calls `store.start_run` before analyse, so
    skipping it here would test a state that never occurs.
    """
    store.start_run(run_id, make_run_config())
    store.write_analyse_checkpoint(run_id, topics, meme_potential_weight=0.3)


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


def test_a_real_older_database_is_refused_rather_than_adopted(tmp_path):
    """Schema 2's tables were `runs` and `topics`; the current schema declares
    neither. Probing for a table only the *current* schema names therefore
    reads a genuine v2 file as fresh, runs the IF NOT EXISTS DDL beside its
    tables and stamps it with the current version — no error, and the
    surviving topic_scores history stranded behind a join to a run_records
    that has no rows for it. This builds the file the real transition
    produces rather than stamping a current-schema file with an older
    number, which is the case the two tests above already cover.
    """
    path = tmp_path / "z.db"
    old = sqlite3.connect(path)
    old.execute("CREATE TABLE runs (run_id TEXT PRIMARY KEY, started_at TEXT)")
    old.execute("CREATE TABLE topics (run_id TEXT, label_slug TEXT)")
    old.execute("PRAGMA user_version = 2")
    old.commit()
    old.close()

    with pytest.raises(StoreSchemaError, match=r"version 2.*expects 4"):
        Store(path).init_schema()


def test_resuming_a_run_keeps_the_time_it_actually_began(tmp_path):
    """The Runs list orders by started_at and renders a duration from it. A
    resume that reset it would move the run to the top of the list and report
    the resume as its start; the counts and the error, which describe the
    attempt being redone, must still be cleared.
    """
    store = _store(tmp_path)
    store.start_run("r1", make_run_config())
    # Backdated rather than compared against the first call's own timestamp:
    # two start_run calls a microsecond apart can share a clock reading on
    # Windows, and this test must fail on a store that rewrites the column.
    began = datetime(2026, 8, 1, 9, 30, tzinfo=UTC)
    store._conn.execute("UPDATE run_records SET started_at = ?", (began.isoformat(),))
    store._conn.commit()
    store.finish_run(
        "r1", status="ok", item_count=9, trends_found=2, topics_kept=1, phrases_found=0
    )

    store.start_run("r1", make_run_config(top_count=42))

    resumed = store.get_run("r1")
    assert resumed is not None
    assert resumed.started_at == began
    assert resumed.status == "running"
    assert resumed.finished_at is None
    assert resumed.item_count is None
    # The config is still replaced: a resume can narrow the template library.
    assert resumed.config.top_count == 42


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


def test_reconciling_marks_a_running_run_interrupted(tmp_path):
    """The process died mid-run. Left at `running`, the UI polls it forever
    and draws an in-flight card for a run with no worker behind it."""
    store = _store(tmp_path)
    store.start_run("20260905T120000Z", make_run_config())

    changed = store.reconcile_interrupted()

    assert changed == ["20260905T120000Z"]
    record = store.get_run("20260905T120000Z")
    assert record is not None
    assert record.status == "interrupted"


def test_reconciling_leaves_finished_runs_alone(tmp_path):
    """This runs on every startup, over the whole table. A predicate matching
    more than `status = 'running'` would rewrite the history of every run the
    user has ever made, on every restart, silently.
    """
    store = _store(tmp_path)
    store.start_run("ok-run", make_run_config())
    store.finish_run(
        "ok-run",
        status="ok",
        item_count=1,
        trends_found=1,
        topics_kept=1,
        phrases_found=0,
    )
    store.start_run("failed-run", make_run_config())
    store.fail_run(
        "failed-run",
        RunError(kind="DistilError", message="no", stage=Stage.ANALYSE),
    )

    assert store.reconcile_interrupted() == []

    # Guarded rather than dereferenced inline: `get_run` returns
    # `RunRecordRow | None`, and `ty` covers tests as part of the gate.
    finished = store.get_run("ok-run")
    failed = store.get_run("failed-run")
    assert finished is not None
    assert failed is not None
    assert (finished.status, failed.status) == ("ok", "failed")


def test_reconciling_an_already_reconciled_database_changes_nothing(tmp_path):
    """Restarts happen back to back during development, and `--reload`
    restarts on every save. A second pass must be a no-op rather than
    re-stamping rows or reporting the same run again.
    """
    store = _store(tmp_path)
    store.start_run("20260905T120000Z", make_run_config())
    store.reconcile_interrupted()

    assert store.reconcile_interrupted() == []


def test_aborting_a_run_records_it_without_counts(tmp_path):
    """`finish_run` requires the four counts and a run that ended early has
    none. Routing an abort through it would mean inventing zeros, which the
    Runs list would render as a run that found nothing — indistinguishable
    from a real empty result.
    """
    store = _store(tmp_path)
    store.start_run("20260905T120000Z", make_run_config())

    store.abort_run("20260905T120000Z")

    record = store.get_run("20260905T120000Z")
    assert record is not None
    assert record.status == "aborted"
    assert record.item_count is None


def test_aborting_a_run_that_already_finished_changes_nothing(tmp_path):
    """The worker calls this on both the stop and the abort path, and an
    abort can land after the pipeline already wrote `ok`. Relabelling a
    completed run as aborted would lose a successful run's outcome — and the
    counts with it.
    """
    store = _store(tmp_path)
    store.start_run("20260905T120000Z", make_run_config())
    store.finish_run(
        "20260905T120000Z",
        status="ok",
        item_count=4,
        trends_found=2,
        topics_kept=1,
        phrases_found=0,
    )

    store.abort_run("20260905T120000Z")

    record = store.get_run("20260905T120000Z")
    assert record is not None
    assert record.status == "ok"
    assert record.item_count == 4


def test_reconciling_preserves_the_checkpoints_a_resume_needs(tmp_path):
    """An interrupted run is resumable from its last good checkpoint like any
    other. A reconciliation that cleared partial state — the tempting reading
    of "clean up the dead run" — would throw away the ingest payload the user
    waited minutes for.
    """
    store = _store(tmp_path)
    store.start_run("20260905T120000Z", make_run_config())
    store.write_analyse_checkpoint(
        "20260905T120000Z", [make_topic("cats")], meme_potential_weight=0.3
    )

    store.reconcile_interrupted()

    assert Stage.ANALYSE in store.written_stages("20260905T120000Z")
    assert store.run_topics("20260905T120000Z")


def test_get_run_returns_none_for_a_run_that_does_not_exist(tmp_path):
    assert _store(tmp_path).get_run("nope") is None


def test_previous_sub_scores_are_keyed_by_platform_then_label_slug(tmp_path):
    store = Store(tmp_path / "z.db")
    store.init_schema()
    store.start_run("r1", make_run_config())
    _analyse(store, "r1", [_topic("Shelter Dog Adoption", {"lemmy": 0.7})])
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
    _analyse(store, "r1", [_topic("Cats", {"lemmy": 0.4, "wikipedia": 0.9})])
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
    _analyse(store, "r1", [_topic("Cats", {"lemmy": 0.4, "corroboration": 1.25})])
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
    with pytest.raises(StoreSchemaError, match=r"z\.db.*version 1.*expects 4"):
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
        _analyse(store, run_id, [_topic("Cats", {"lemmy": sub_score})])
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
    _analyse(
        store,
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
    _analyse(store, "r2", [_topic("Cats", {"lemmy": 0.7})])
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
    _analyse(store, "r1", [_topic("Cats", {"lemmy": 0.8})])

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
    _analyse(store, "r1", [_topic("Cats", {"lemmy": 0.2})])
    store.finish_run(
        "r1", status="ok", item_count=1, trends_found=1, topics_kept=1, phrases_found=0
    )

    store.start_run("r2", make_run_config())
    _analyse(store, "r2", [_topic("Cats", {"lemmy": 0.99})])
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
    _analyse(store, "r1", [_topic("Shelter Dog Adoption", {"lemmy": 0.8})])
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


def _query_from_another_thread(store: Store) -> BaseException | None:
    """Run a trivial query against `store` on a fresh thread and hand back
    whatever it raised, or None if it didn't.
    """
    caught: list[BaseException | None] = [None]

    def target() -> None:
        try:
            store._conn.execute("SELECT 1")
        except BaseException as exc:  # noqa: BLE001 - relaying, not handling
            caught[0] = exc

    thread = threading.Thread(target=target)
    thread.start()
    thread.join()
    return caught[0]


def test_a_default_store_refuses_cross_thread_use(tmp_path):
    """The safe default: a Store built for a single thread raises
    immediately if another thread ever touches it by mistake, rather than
    corrupting data silently. This is what the check_same_thread=False API
    app passes stays opt-in for every other caller.
    """
    store = _store(tmp_path)

    error = _query_from_another_thread(store)

    assert isinstance(error, sqlite3.ProgrammingError)


def test_check_same_thread_false_permits_cross_thread_use(tmp_path):
    """The API app holds one Store across FastAPI's thread pool and
    TestClient's portal thread, so it opts out of the guard above.
    """
    store = Store(tmp_path / "z.db", check_same_thread=False)
    store.init_schema()

    error = _query_from_another_thread(store)

    assert error is None


def test_a_checkpoint_round_trips_through_its_model(tmp_path):
    """This is what resuming a run depends on. A payload that does not round
    trip breaks resume silently rather than loudly."""
    store = _store(tmp_path)
    topics = [make_topic("airport-cat"), make_topic("stadium-rat")]

    store.write_checkpoint("r1", Stage.ANALYSE, topics)
    restored = store.read_checkpoint("r1", Stage.ANALYSE, Topic)

    assert restored == topics


def test_a_checkpoint_round_trips_a_discriminated_union(tmp_path):
    """Metrics is discriminated on platform. A payload that deserialises to
    the wrong union member would score the topic with the wrong scorer."""
    store = _store(tmp_path)
    evidence = [_trend_evidence()]

    store.write_checkpoint("r1", Stage.INGEST, evidence)
    [restored] = store.read_checkpoint("r1", Stage.INGEST, TrendEvidence)

    assert isinstance(restored.posts[0].item.metrics, BlueskyMetrics)


def test_writing_a_checkpoint_twice_replaces_it(tmp_path):
    """Resuming rewrites the stages it re-runs."""
    store = _store(tmp_path)
    store.write_checkpoint("r1", Stage.ANALYSE, [make_topic("first")])

    store.write_checkpoint("r1", Stage.ANALYSE, [make_topic("second")])

    [topic] = store.read_checkpoint("r1", Stage.ANALYSE, Topic)
    assert topic.id == "second"


def test_write_checkpoint_reports_the_payload_size(tmp_path):
    """The stage card shows this number, so it has to be the size of what
    was actually written - not merely some positive number. Returning
    len(models) would satisfy `> 0` and be wrong by three orders."""
    store = _store(tmp_path)

    size = store.write_checkpoint("r1", Stage.ANALYSE, [make_topic()])

    [(stored_bytes,)] = store._conn.execute(
        "SELECT LENGTH(CAST(payload AS BLOB)) FROM checkpoints "
        "WHERE run_id = ? AND stage = ?",
        ("r1", Stage.ANALYSE.value),
    ).fetchall()
    assert size == stored_bytes


def test_reading_a_checkpoint_that_was_never_written_raises(tmp_path):
    """Resuming from a stage whose predecessor never ran must say so, not
    return an empty list that looks like a run with no topics."""
    store = _store(tmp_path)

    with pytest.raises(MissingCheckpoint, match="analyse"):
        store.read_checkpoint("r1", Stage.ANALYSE, Topic)


def test_an_empty_checkpoint_is_not_a_missing_one(tmp_path):
    """A generate stage that briefed nothing wrote an empty list. That is a
    result, and resuming past it must not raise."""
    store = _store(tmp_path)
    store.write_checkpoint("r1", Stage.GENERATE, [])

    assert store.read_checkpoint("r1", Stage.GENERATE, MediaBrief) == []


def test_written_stages_reports_only_what_was_checkpointed(tmp_path):
    store = _store(tmp_path)
    store.write_checkpoint("r1", Stage.INGEST, [make_topic()])
    store.write_checkpoint("r1", Stage.EVALUATE, [])

    assert store.written_stages("r1") == {Stage.INGEST, Stage.EVALUATE}


def test_stages_come_back_in_pipeline_order(tmp_path):
    """The four stage cards are drawn left to right in the order they run,
    not the order rows happened to be written."""
    store = _store(tmp_path)
    store.record_stage("r1", make_stage_record(Stage.GENERATE))
    store.record_stage("r1", make_stage_record(Stage.INGEST))
    store.record_stage("r1", make_stage_record(Stage.EVALUATE))
    store.record_stage("r1", make_stage_record(Stage.ANALYSE))

    stages = store.stages_for_run("r1")

    assert [s.stage for s in stages] == [
        Stage.INGEST,
        Stage.ANALYSE,
        Stage.EVALUATE,
        Stage.GENERATE,
    ]


def test_recording_a_stage_twice_replaces_it(tmp_path):
    """A stage moves queued to running to ok, rewriting its row each time."""
    store = _store(tmp_path)
    store.record_stage(
        "r1", make_stage_record(Stage.INGEST, status="running", finished_at=None)
    )

    store.record_stage("r1", make_stage_record(Stage.INGEST, status="ok"))

    [stage] = store.stages_for_run("r1")
    assert stage.status == "ok"
    assert stage.finished_at is not None


def test_a_queued_stage_round_trips_its_absent_timings(tmp_path):
    store = _store(tmp_path)
    store.record_stage(
        "r1",
        make_stage_record(
            Stage.GENERATE,
            status="queued",
            started_at=None,
            finished_at=None,
            payload_bytes=None,
            summary="queued",
        ),
    )

    [stage] = store.stages_for_run("r1")

    assert (stage.started_at, stage.finished_at, stage.payload_bytes) == (
        None,
        None,
        None,
    )


def test_record_stage_round_trips_progress_counters(tmp_path):
    """A running stage's counters survive the write and the read.

    The in-flight stage card draws `17 / 25` and a partial bar from these
    two numbers; a column that silently dropped them would leave the card
    rendering a stage that is running with nothing to say about it.
    """
    store = Store(tmp_path / "z.db")
    store.init_schema()
    store.start_run("20260901T120000Z", make_run_config())

    store.record_stage(
        "20260901T120000Z",
        make_stage_record(
            Stage.ANALYSE,
            status="running",
            finished_at=None,
            payload_bytes=None,
            summary="distilling airport-cat",
            done=17,
            total=25,
        ),
    )

    (record,) = store.stages_for_run("20260901T120000Z")
    assert record.status == "running"
    assert record.done == 17
    assert record.total == 25
    store.close()


def test_record_stage_defaults_counters_to_none(tmp_path):
    """Ingest and evaluate count nothing, and say so.

    `None` here is not an unwritten field: those two stages are single
    opaque operations. A zero would claim they had done none of a known
    amount of work.
    """
    store = Store(tmp_path / "z.db")
    store.init_schema()
    store.start_run("20260901T120000Z", make_run_config())

    store.record_stage("20260901T120000Z", make_stage_record(Stage.INGEST))

    (record,) = store.stages_for_run("20260901T120000Z")
    assert record.done is None
    assert record.total is None
    store.close()


def test_record_stage_overwrites_a_running_row_with_its_final_one(tmp_path):
    """`INSERT OR REPLACE` keyed on (run_id, stage): the completed row must
    leave no trace of the counters the running row carried, or a finished
    stage card would draw `17 / 25` beside its duration forever."""
    store = Store(tmp_path / "z.db")
    store.init_schema()
    store.start_run("20260901T120000Z", make_run_config())

    store.record_stage(
        "20260901T120000Z",
        make_stage_record(
            Stage.ANALYSE, status="running", finished_at=None, done=17, total=25
        ),
    )
    store.record_stage(
        "20260901T120000Z",
        make_stage_record(Stage.ANALYSE, status="ok", summary="25 topics distilled"),
    )

    (record,) = store.stages_for_run("20260901T120000Z")
    assert record.status == "ok"
    assert record.done is None
    assert record.total is None
    store.close()


def test_run_topics_round_trip_through_the_store(tmp_path):
    store = _store(tmp_path)
    rows = flatten("r1", [make_topic("airport-cat")], meme_potential_weight=0.3)

    store.write_run_topics(rows)

    stored = store.run_topics("r1")
    assert [row.topic_id for row in stored] == ["airport-cat"]
    assert stored[0].label_slug == "airport-cat"


def test_the_analyse_checkpoint_and_its_rows_commit_together(tmp_path):
    store = _store(tmp_path)

    store.write_analyse_checkpoint(
        "r1", [make_topic("airport-cat")], meme_potential_weight=0.3
    )

    assert len(store.read_checkpoint("r1", Stage.ANALYSE, Topic)) == 1
    assert len(store.run_topics("r1")) == 1


def test_the_analyse_checkpoint_also_writes_the_cross_run_sub_scores(tmp_path):
    """topic_scores is derived from the same payload and has no other writer.
    Committing it separately, before the checkpoint, left a window where a
    crash stranded sub-scores for a run whose analyse never landed — and
    previous_sub_scores feeds those into the next run's rank delta."""
    store = _store(tmp_path)

    _analyse(store, "r1", [_topic("Cats", {"lemmy": 0.4})])

    assert store.previous_sub_scores("r2") == {"lemmy": {"cats": 0.4}}


def test_re_analysing_a_run_leaves_only_the_new_topics(tmp_path):
    """Reachable from start_at=ANALYSE. Keyed on (run_id, topic_id), an upsert
    with no clear leaves every topic the previous analyse produced: three rows
    against a checkpoint holding two, two of them ranked 1, and stale sub-
    scores feeding the next run's rank delta under labels this run dropped.
    """
    store = _store(tmp_path)
    _analyse(store, "r1", [_topic("Aardvarks", {"lemmy": 0.9}), _topic("Bees", {})])

    _analyse(store, "r1", [_topic("Cats", {"lemmy": 0.1})])

    rows = store.run_topics("r1")
    assert [row.topic_id for row in rows] == ["cats"]
    assert [row.final_rank for row in rows] == [1]
    assert store.previous_sub_scores("r2") == {"lemmy": {"cats": 0.1}}


def test_a_failure_partway_leaves_none_of_the_three(tmp_path, monkeypatch):
    """The whole 'they cannot disagree' claim rests on one transaction.
    Separate commits would leave a window where a crash strands one.

    Fails the *last* insert, so the checkpoint and run_topics rows are already
    written inside the transaction and have to be rolled back — a test that
    failed the first would pass against three independent commits.
    """
    store = _store(tmp_path)

    def boom(*args, **kwargs):
        raise RuntimeError("interrupted")

    monkeypatch.setattr(store, "_insert_topic_scores", boom)

    with pytest.raises(RuntimeError):
        store.write_analyse_checkpoint(
            "r1", [_topic("Cats", {"lemmy": 0.4})], meme_potential_weight=0.3
        )

    counts = [
        store._conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in ("checkpoints", "run_topics", "topic_scores")
    ]
    assert counts == [0, 0, 0]


def test_a_render_round_trips_with_its_origin_intact(tmp_path):
    store = _store(tmp_path)
    record = make_render_record("rnd1", origin=AutoOrigin(rationale="it fits"))

    store.add_render(record)

    restored = store.get_render("rnd1")
    assert restored == record
    assert isinstance(restored.origin, AutoOrigin)


def test_a_hand_written_render_comes_back_manual(tmp_path):
    """The union is what makes 'was this written by a person' a type check
    rather than a string comparison."""
    store = _store(tmp_path)
    store.add_render(make_render_record("rnd2", origin=ManualOrigin()))

    restored = store.get_render("rnd2")

    assert restored is not None
    assert isinstance(restored.origin, ManualOrigin)


def test_a_failed_render_keeps_its_error(tmp_path):
    """The renderer fails per meme, so a partial failure is real. The tile
    shows the message rather than vanishing."""
    store = _store(tmp_path)
    store.add_render(
        make_render_record("rnd3", status="failed", error="caption does not fit")
    )

    restored = store.get_render("rnd3")

    assert restored is not None
    assert restored.status == "failed"
    assert restored.error == "caption does not fit"


def test_add_renders_writes_every_record_in_one_transaction(tmp_path):
    """The happy path: a `count=4` seed lands as four rows from one call,
    exactly as four calls to `add_render` would, but through one commit."""
    store = _store(tmp_path)
    records = [
        make_render_record("a", status="generating"),
        make_render_record("b", status="generating"),
        make_render_record("c", status="generating"),
    ]

    store.add_renders(records)

    ids = {r.id for r in store.renders_for_run("20260901T120000Z")}
    assert ids == {"a", "b", "c"}


def test_add_renders_leaves_nothing_behind_when_one_insert_fails(tmp_path):
    """All-or-nothing is the whole point: a `count=4` seed where the third
    row fails must not strand the first two as permanently-`generating`
    rows nobody will ever finish. `executemany` plus a single `commit`
    means a `PRIMARY KEY` collision partway through rolls the lot back,
    rather than committing what came before it."""
    store = _store(tmp_path)
    store.add_render(make_render_record("dup", status="ready"))

    with pytest.raises(sqlite3.IntegrityError):
        store.add_renders(
            [
                make_render_record("new1", status="generating"),
                make_render_record("dup", status="generating"),
            ]
        )

    assert store.get_render("new1") is None
    # The pre-existing row must be untouched, not overwritten by the
    # colliding insert before the transaction rolled back.
    survivor = store.get_render("dup")
    assert survivor is not None
    assert survivor.status == "ready"


def test_renders_for_a_run_come_back_oldest_first(tmp_path):
    store = _store(tmp_path)
    store.add_render(
        make_render_record("second", created_at=datetime(2026, 9, 1, 13, tzinfo=UTC))
    )
    store.add_render(
        make_render_record("first", created_at=datetime(2026, 9, 1, 12, tzinfo=UTC))
    )

    ids = [r.id for r in store.renders_for_run("20260901T120000Z")]

    assert ids == ["first", "second"]


def test_get_render_returns_none_for_an_unknown_id(tmp_path):
    assert _store(tmp_path).get_render("nope") is None


def test_runs_come_back_newest_first(tmp_path):
    """The Runs list is reverse-chronological and the in-flight run pins to
    the top, so ordering is the endpoint's whole job."""
    store = _store(tmp_path)
    # Insert in chronological order. `started_at` is stamped by `_now()` at
    # insert time and has nothing to do with the run id, so the order rows
    # go in *is* the order they come back.
    for run_id in ("20260901T100000Z", "20260901T110000Z", "20260901T120000Z"):
        store.start_run(run_id, make_run_config())

    ids = [row.run_id for row in store.list_runs(limit=10)]

    assert ids == [
        "20260901T120000Z",
        "20260901T110000Z",
        "20260901T100000Z",
    ]


def test_the_cursor_resumes_after_the_last_row_of_the_previous_page(tmp_path):
    store = _store(tmp_path)
    for run_id in ("20260901T100000Z", "20260901T110000Z", "20260901T120000Z"):
        store.start_run(run_id, make_run_config())

    first = store.list_runs(limit=2)
    second = store.list_runs(limit=2, cursor=first[-1].started_at.isoformat())

    assert [row.run_id for row in first] == [
        "20260901T120000Z",
        "20260901T110000Z",
    ]
    assert [row.run_id for row in second] == ["20260901T100000Z"]


def test_render_counts_are_keyed_by_topic(tmp_path):
    """Meme counts are a COUNT(*) at query time rather than a column, so
    this is the only thing standing between the UI and a wrong number."""
    store = _store(tmp_path)
    store.add_render(make_render_record("a", topic_id="cats"))
    store.add_render(make_render_record("b", topic_id="cats"))
    store.add_render(make_render_record("c", topic_id="dogs"))

    assert store.render_counts("20260901T120000Z") == {"cats": 2, "dogs": 1}


def test_render_counts_are_scoped_to_the_run(tmp_path):
    store = _store(tmp_path)
    store.add_render(make_render_record("a", run_id="r1", topic_id="cats"))
    store.add_render(make_render_record("b", run_id="r2", topic_id="cats"))

    assert store.render_counts("r1") == {"cats": 1}


def test_render_counts_excludes_generating_and_failed_rows(tmp_path):
    """The count means 'memes that exist' — what the grid draws thumbnails
    for. A row still `generating` has no image yet, and a `failed` one
    never will; neither should inflate the number, and a topic with only
    such rows must not appear in the mapping at all."""
    store = _store(tmp_path)
    store.add_render(make_render_record("a", topic_id="cats", status="ready"))
    store.add_render(make_render_record("b", topic_id="cats", status="generating"))
    store.add_render(make_render_record("c", topic_id="cats", status="failed"))
    store.add_render(make_render_record("d", topic_id="dogs", status="generating"))

    assert store.render_counts("20260901T120000Z") == {"cats": 1}


def test_topic_recurrence_counts_runs_and_names_the_earliest(tmp_path):
    store = _store(tmp_path)
    # Earliest first, because `MIN(started_at ...)` picks the row inserted
    # first — `started_at` is wall-clock, not parsed from the run id.
    for run_id in ("20260901T100000Z", "20260901T120000Z"):
        store.start_run(run_id, make_run_config())
        store.write_analyse_checkpoint(
            run_id, [make_topic("cats")], meme_potential_weight=0.3
        )

    assert store.topic_recurrence("cats") == (2, "20260901T100000Z")


def test_topic_recurrence_of_an_unseen_slug_is_zero(tmp_path):
    assert _store(tmp_path).topic_recurrence("nope") == (0, None)


def _log(store, run_id: str, seq: int, level: str, message: str) -> None:
    """Seed a log line directly.

    The only hand-written SQL in these tests: phase 3 owns the writer, and
    the reader has to be testable before it exists.
    """
    store._conn.execute(
        "INSERT INTO log_lines (run_id, seq, logged_at, level, logger, message) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            run_id,
            seq,
            "2026-09-01T12:00:00+00:00",
            level,
            "zeitgeist.pipeline",
            message,
        ),
    )
    store._conn.commit()


def test_log_lines_come_back_in_sequence(tmp_path):
    store = _store(tmp_path)
    _log(store, "r1", 2, "INFO", "second")
    _log(store, "r1", 1, "INFO", "first")

    assert [line.message for line in store.log_lines("r1", verbose=True)] == [
        "first",
        "second",
    ]


def test_a_quiet_log_omits_debug_lines(tmp_path):
    """The toggle filters what was already captured, so flipping it works
    retroactively rather than showing nothing until the next line."""
    store = _store(tmp_path)
    _log(store, "r1", 1, "DEBUG", "noisy")
    _log(store, "r1", 2, "INFO", "useful")
    _log(store, "r1", 3, "WARNING", "important")

    quiet = [line.message for line in store.log_lines("r1", verbose=False)]

    assert quiet == ["useful", "important"]


def test_a_verbose_log_keeps_everything(tmp_path):
    store = _store(tmp_path)
    _log(store, "r1", 1, "DEBUG", "noisy")
    _log(store, "r1", 2, "INFO", "useful")

    loud = [line.message for line in store.log_lines("r1", verbose=True)]

    assert loud == ["noisy", "useful"]


def test_log_lines_are_scoped_to_the_run(tmp_path):
    store = _store(tmp_path)
    _log(store, "r1", 1, "INFO", "mine")
    _log(store, "r2", 1, "INFO", "theirs")

    assert [line.message for line in store.log_lines("r1", verbose=True)] == ["mine"]


def test_a_batch_of_log_lines_round_trips(tmp_path):
    """The writer phase 2's reader was built against. `Store.log_lines`
    already has tests, but they seed rows with hand-written SQL because no
    writer existed — so nothing yet proves the two agree on column order,
    and a mismatch would surface as levels appearing in the message column.
    """
    store = _store(tmp_path)
    store.start_run("20260905T120000Z", make_run_config())

    store.write_log_lines(
        "20260905T120000Z",
        [
            CapturedLine(
                seq=1,
                logged_at=datetime(2026, 9, 5, 12, tzinfo=UTC),
                level="INFO",
                logger="zeitgeist.pipeline",
                message="Fetched 3 trends",
            ),
            CapturedLine(
                seq=2,
                logged_at=datetime(2026, 9, 5, 12, tzinfo=UTC),
                level="DEBUG",
                logger="zeitgeist.media.render",
                message="Slot top fitted at 48pt",
            ),
        ],
    )

    lines = store.log_lines("20260905T120000Z", verbose=True)
    assert [(line.seq, line.level, line.logger) for line in lines] == [
        (1, "INFO", "zeitgeist.pipeline"),
        (2, "DEBUG", "zeitgeist.media.render"),
    ]
    assert lines[0].message == "Fetched 3 trends"


def test_writing_no_lines_is_not_an_error(tmp_path):
    """`detach` flushes whatever is pending, which is routinely nothing — a
    run that ended right after a batch boundary. An empty `executemany` is
    fine, but an implementation building a VALUES list by hand would produce
    invalid SQL for the empty case and only fail on that timing.
    """
    store = _store(tmp_path)
    store.start_run("20260905T120000Z", make_run_config())

    store.write_log_lines("20260905T120000Z", [])

    assert store.log_lines("20260905T120000Z", verbose=True) == []


def test_recent_run_ids_are_newest_first(tmp_path):
    store = _store(tmp_path)
    # Chronological insertion: `started_at` is wall-clock at insert time,
    # not derived from the run id.
    for run_id in ("20260901T100000Z", "20260901T110000Z", "20260901T120000Z"):
        store.start_run(run_id, make_run_config())

    assert store.recent_run_ids(2) == [
        "20260901T120000Z",
        "20260901T110000Z",
    ]


def test_topics_for_runs_spans_every_run_named(tmp_path):
    store = _store(tmp_path)
    for run_id, topic in (("r1", "cats"), ("r2", "dogs")):
        store.start_run(run_id, make_run_config())
        store.write_analyse_checkpoint(
            run_id, [make_topic(topic)], meme_potential_weight=0.3
        )

    rows = store.topics_for_runs(["r1", "r2"])

    assert {row.topic_id for row in rows} == {"cats", "dogs"}


def test_topics_for_no_runs_is_empty(tmp_path):
    """An empty window must not become `WHERE run_id IN ()`, which is a
    syntax error in SQLite."""
    assert _store(tmp_path).topics_for_runs([]) == []


def test_update_render_replaces_the_mutable_columns(tmp_path):
    """A generating render is finished in place: the brief arrives after
    the row does."""
    store = _store(tmp_path)
    store.add_render(make_render_record("rnd1", status="generating", caption_slots={}))

    updated = store.update_render(
        make_render_record(
            "rnd1",
            status="ready",
            caption_slots={"rejected": "a", "preferred": "b"},
            origin=AutoOrigin(rationale="the shape matches"),
        )
    )

    assert updated is True
    record = store.get_render("rnd1")
    assert record is not None
    assert record.status == "ready"
    assert record.caption_slots == {"rejected": "a", "preferred": "b"}
    assert record.origin == AutoOrigin(rationale="the shape matches")


def test_update_render_does_not_resurrect_a_deleted_row(tmp_path):
    """`add_render` is INSERT OR REPLACE, so finishing a job with it would
    bring back a render somebody deleted while it was still generating.
    That is why the finishing path is an UPDATE."""
    store = _store(tmp_path)
    store.add_render(make_render_record("rnd1", status="generating"))
    store.delete_render("rnd1")

    updated = store.update_render(make_render_record("rnd1", status="ready"))

    assert updated is False
    assert store.get_render("rnd1") is None


def test_update_render_cannot_move_a_render_to_another_run(tmp_path):
    """run_id, topic_id and created_at are fixed at insert. A job
    finishing writes the brief, not the identity."""
    store = _store(tmp_path)
    store.add_render(
        make_render_record("rnd1", run_id="run-1", topic_id="cat", status="generating")
    )

    store.update_render(
        make_render_record("rnd1", run_id="run-2", topic_id="dog", status="ready")
    )

    record = store.get_render("rnd1")
    assert record is not None
    assert (record.run_id, record.topic_id) == ("run-1", "cat")


def test_delete_render_removes_the_row(tmp_path):
    store = _store(tmp_path)
    store.add_render(make_render_record("rnd1"))

    assert store.delete_render("rnd1") is True
    assert store.get_render("rnd1") is None


def test_delete_render_reports_an_unknown_id(tmp_path):
    """The endpoint 404s on it, so a silent success would be a lie."""
    store = _store(tmp_path)

    assert store.delete_render("nope") is False


def test_renders_for_topic_excludes_other_topics_and_other_runs(tmp_path):
    store = _store(tmp_path)
    store.add_render(make_render_record("a", run_id="r1", topic_id="cat"))
    store.add_render(make_render_record("b", run_id="r1", topic_id="dog"))
    store.add_render(make_render_record("c", run_id="r2", topic_id="cat"))

    records = store.renders_for_topic("r1", "cat")

    assert [record.id for record in records] == ["a"]


def test_renders_for_topic_returns_oldest_first(tmp_path):
    """Topic detail's grid reads in creation order, so the newest tile is
    last rather than wherever SQLite happened to put it."""
    store = _store(tmp_path)
    store.add_render(
        make_render_record("second", created_at=datetime(2026, 9, 2, tzinfo=UTC))
    )
    store.add_render(
        make_render_record("first", created_at=datetime(2026, 9, 1, tzinfo=UTC))
    )

    ids = [r.id for r in store.renders_for_topic("20260901T120000Z", "airport-cat")]
    assert ids == ["first", "second"]
