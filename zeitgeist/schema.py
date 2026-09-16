"""The database's shape.

Lives apart from `store.py` so ninety lines of DDL do not sit in the middle
of the accessors that use it.

There is no migration path and none is written: the project is in active
development and data loss is acceptable, so `StoreSchemaError` refusing to
open a mismatched database *is* the strategy. Bumping SCHEMA_VERSION means
deleting the file.

Every table but `settings` hangs off `run_records` by `run_id`, and says so
with a real `REFERENCES` clause. Declaring them is only half of it —
SQLite's foreign key enforcement is off unless a connection asks for it, so
`Store.__init__` issues `PRAGMA foreign_keys = ON` and every write goes
through a `Store`. Without both halves a checkpoint, a log line or a render
could name a run that does not exist, and nothing would say so until a
screen rendered a row with no run behind it.
"""

SCHEMA_VERSION = 6

SCHEMA = """
CREATE TABLE IF NOT EXISTS run_records (
    run_id        TEXT PRIMARY KEY,
    status        TEXT NOT NULL,
    started_at    TEXT NOT NULL,
    -- When the *current* attempt opened, which `started_at` deliberately is
    -- not: a resume keeps the original `started_at` so the Runs list still
    -- orders by when the run first began. The in-flight elapsed clock reads
    -- this instead, so a run resumed a day later counts from the resume
    -- rather than claiming to have been going for a day. Equal to
    -- `started_at` on a run that has never been resumed.
    attempt_started_at TEXT NOT NULL,
    finished_at   TEXT,
    config        TEXT NOT NULL,
    error         TEXT,
    item_count    INTEGER,
    trends_found  INTEGER,
    topics_kept   INTEGER,
    phrases_found INTEGER
);

-- The four stage artifacts, held whole rather than normalised. Nothing
-- queries inside a payload except topic detail's replies, and a blob
-- round-trips through model_validate_json exactly, which is what resuming a
-- run depends on.
CREATE TABLE IF NOT EXISTS checkpoints (
    run_id      TEXT NOT NULL REFERENCES run_records (run_id) ON DELETE CASCADE,
    stage       TEXT NOT NULL,
    payload     TEXT NOT NULL,
    written_at  TEXT NOT NULL,
    PRIMARY KEY (run_id, stage)
);

CREATE TABLE IF NOT EXISTS run_stages (
    run_id        TEXT NOT NULL REFERENCES run_records (run_id) ON DELETE CASCADE,
    stage         TEXT NOT NULL,
    status        TEXT NOT NULL,
    started_at    TEXT,
    finished_at   TEXT,
    payload_bytes INTEGER,
    summary       TEXT NOT NULL,
    -- Stage-relative counters, NULL for the two stages that count nothing.
    -- Phase 6's in-flight stage card reads them as `17 / 25` and as the
    -- partial fill on its top bar.
    done          INTEGER,
    total         INTEGER,
    PRIMARY KEY (run_id, stage)
);

-- The analyse and evaluate payloads flattened into columns you can filter,
-- sort and join on. Written in the same transaction as the checkpoint it
-- flattens, so the two cannot disagree.
--
-- No render_count column: meme counts are COUNT(*) over renders at query
-- time. Denormalising it would mean keeping it correct on every render
-- insert, failure and delete, including from the on-demand executor, to save
-- a join over a table holding single digits per run.
CREATE TABLE IF NOT EXISTS run_topics (
    run_id                TEXT NOT NULL
        REFERENCES run_records (run_id) ON DELETE CASCADE,
    topic_id              TEXT NOT NULL,
    label                 TEXT NOT NULL,
    label_slug            TEXT NOT NULL,
    trend_status          TEXT NOT NULL,
    event_sentiment       TEXT,
    conversation_register TEXT,
    meme_potential        REAL,
    trend_score           REAL NOT NULL,
    final_score           REAL NOT NULL,
    final_rank            INTEGER NOT NULL,
    post_count            INTEGER NOT NULL,
    top_phrase            TEXT,
    top_phrase_authors    INTEGER,
    PRIMARY KEY (run_id, topic_id)
);

-- `topic_id` names a row in `run_topics` but does not reference it: the
-- on-demand generator briefs from the *analyse* checkpoint, which holds
-- every topic, while `run_topics` holds only what evaluate ranked. A
-- composite foreign key here would refuse a render for a topic that was
-- distilled and never ranked — which is exactly the below-the-cut case the
-- generate link exists for.
CREATE TABLE IF NOT EXISTS renders (
    id            TEXT PRIMARY KEY,
    run_id        TEXT NOT NULL REFERENCES run_records (run_id) ON DELETE CASCADE,
    topic_id      TEXT NOT NULL,
    -- NULL while the model has yet to choose a template for a render it
    -- was asked to choose one for, and on a render whose brief failed
    -- before it did. Every other row names the template it was drawn on.
    template_id   TEXT,
    caption_slots TEXT NOT NULL,
    origin        TEXT NOT NULL,
    status        TEXT NOT NULL,
    error         TEXT,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS log_lines (
    run_id    TEXT NOT NULL REFERENCES run_records (run_id) ON DELETE CASCADE,
    seq       INTEGER NOT NULL,
    logged_at TEXT NOT NULL,
    level     TEXT NOT NULL,
    logger    TEXT NOT NULL,
    message   TEXT NOT NULL,
    PRIMARY KEY (run_id, seq)
);

-- One row per tuning field the settings screen has overridden. Absent means
-- fall through to .env. The one table with no run behind it, and so the one
-- with no foreign key: a setting outlives every run.
CREATE TABLE IF NOT EXISTS settings (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Survives from schema 2 unchanged. Per-platform sub-scores have no home in
-- run_topics, and previous_sub_scores is the one query that needs them.
CREATE TABLE IF NOT EXISTS topic_scores (
    run_id    TEXT NOT NULL REFERENCES run_records (run_id) ON DELETE CASCADE,
    label     TEXT NOT NULL,
    platform  TEXT NOT NULL,
    sub_score REAL NOT NULL,
    PRIMARY KEY (run_id, label, platform)
);

CREATE INDEX IF NOT EXISTS idx_run_topics_slug ON run_topics (label_slug);
-- The topics index deduplicates across runs by topic id, which the
-- (run_id, topic_id) primary key cannot serve: run_id leads it.
CREATE INDEX IF NOT EXISTS idx_run_topics_topic ON run_topics (topic_id);
CREATE INDEX IF NOT EXISTS idx_run_topics_status ON run_topics (trend_status);
CREATE INDEX IF NOT EXISTS idx_renders_run_topic ON renders (run_id, topic_id);
CREATE INDEX IF NOT EXISTS idx_topic_scores_label ON topic_scores (label);
-- (started_at, run_id) rather than started_at alone, because that pair is
-- what `list_runs` both orders and pages by: its keyset cursor carries the
-- run id as a tiebreaker, and a one-column index would leave the tiebreak
-- to a sort.
CREATE INDEX IF NOT EXISTS idx_run_records_started
    ON run_records (started_at, run_id);
"""
