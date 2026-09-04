"""The database's shape.

Lives apart from `store.py` so ninety lines of DDL do not sit in the middle
of the accessors that use it.

There is no migration path and none is written: the project is in active
development and data loss is acceptable, so `StoreSchemaError` refusing to
open a mismatched database *is* the strategy. Bumping SCHEMA_VERSION means
deleting the file.
"""

SCHEMA_VERSION = 3

SCHEMA = """
-- The four stage artifacts, held whole rather than normalised. Nothing
-- queries inside a payload except topic detail's replies, and a blob
-- round-trips through model_validate_json exactly, which is what resuming a
-- run depends on.
CREATE TABLE IF NOT EXISTS checkpoints (
    run_id      TEXT NOT NULL,
    stage       TEXT NOT NULL,
    payload     TEXT NOT NULL,
    written_at  TEXT NOT NULL,
    PRIMARY KEY (run_id, stage)
);

CREATE TABLE IF NOT EXISTS run_records (
    run_id        TEXT PRIMARY KEY,
    status        TEXT NOT NULL,
    started_at    TEXT NOT NULL,
    finished_at   TEXT,
    config        TEXT NOT NULL,
    error         TEXT,
    item_count    INTEGER,
    trends_found  INTEGER,
    topics_kept   INTEGER,
    phrases_found INTEGER
);

CREATE TABLE IF NOT EXISTS run_stages (
    run_id        TEXT NOT NULL,
    stage         TEXT NOT NULL,
    status        TEXT NOT NULL,
    started_at    TEXT,
    finished_at   TEXT,
    payload_bytes INTEGER,
    summary       TEXT NOT NULL,
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
    run_id                TEXT NOT NULL,
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

CREATE TABLE IF NOT EXISTS renders (
    id            TEXT PRIMARY KEY,
    run_id        TEXT NOT NULL,
    topic_id      TEXT NOT NULL,
    template_id   TEXT NOT NULL,
    caption_slots TEXT NOT NULL,
    origin        TEXT NOT NULL,
    status        TEXT NOT NULL,
    error         TEXT,
    created_at    TEXT NOT NULL
);

-- Created here so phase 3 needs no second version bump. Nothing writes to it
-- in phase 1 and no accessor for it exists yet.
CREATE TABLE IF NOT EXISTS log_lines (
    run_id    TEXT NOT NULL,
    seq       INTEGER NOT NULL,
    logged_at TEXT NOT NULL,
    level     TEXT NOT NULL,
    logger    TEXT NOT NULL,
    message   TEXT NOT NULL,
    PRIMARY KEY (run_id, seq)
);

-- One row per tuning field the settings screen has overridden. Absent means
-- fall through to .env.
CREATE TABLE IF NOT EXISTS settings (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Survives from schema 2 unchanged. Per-platform sub-scores have no home in
-- run_topics, and previous_sub_scores is the one query that needs them.
CREATE TABLE IF NOT EXISTS topic_scores (
    run_id    TEXT NOT NULL,
    label     TEXT NOT NULL,
    platform  TEXT NOT NULL,
    sub_score REAL NOT NULL,
    PRIMARY KEY (run_id, label, platform)
);

CREATE INDEX IF NOT EXISTS idx_run_topics_slug ON run_topics (label_slug);
CREATE INDEX IF NOT EXISTS idx_run_topics_status ON run_topics (trend_status);
CREATE INDEX IF NOT EXISTS idx_renders_run_topic ON renders (run_id, topic_id);
CREATE INDEX IF NOT EXISTS idx_topic_scores_label ON topic_scores (label);
CREATE INDEX IF NOT EXISTS idx_run_records_started ON run_records (started_at);
"""
