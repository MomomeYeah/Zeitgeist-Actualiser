"""Cross-run history. The minimum needed to detect topics rising and falling."""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from zeitgeist.analysis.slug import slugify
from zeitgeist.models import NON_PLATFORM_COMPONENTS, Topic

SCHEMA_VERSION = 2

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id      TEXT PRIMARY KEY,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    status      TEXT,
    item_count  INTEGER
);

CREATE TABLE IF NOT EXISTS topics (
    run_id      TEXT NOT NULL,
    label       TEXT NOT NULL,
    trend_score REAL NOT NULL,
    created_at  TEXT NOT NULL,
    PRIMARY KEY (run_id, label)
);

CREATE TABLE IF NOT EXISTS topic_scores (
    run_id    TEXT NOT NULL,
    label     TEXT NOT NULL,
    platform  TEXT NOT NULL,
    sub_score REAL NOT NULL,
    PRIMARY KEY (run_id, label, platform)
);

CREATE INDEX IF NOT EXISTS idx_topics_label ON topics (label);
CREATE INDEX IF NOT EXISTS idx_topic_scores_label ON topic_scores (label);
"""


class StoreSchemaError(RuntimeError):
    """The database on disk was written by a different schema version."""


class Store:
    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._path)

    def init_schema(self) -> None:
        existing = self._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='runs'"
        ).fetchone()
        if existing is None:
            self._conn.executescript(SCHEMA)
            self._conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            self._conn.commit()
            return

        version = self._conn.execute("PRAGMA user_version").fetchone()[0]
        if version != SCHEMA_VERSION:
            raise StoreSchemaError(
                f"{self._path} was written by schema version {version}; this "
                f"build expects {SCHEMA_VERSION}. Delete it and re-run — "
                "cross-run trend history will be lost, nothing else."
            )

    def start_run(self, run_id: str) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO runs (run_id, started_at) VALUES (?, ?)",
            (run_id, _now()),
        )
        self._conn.commit()

    def finish_run(self, run_id: str, status: str, item_count: int) -> None:
        self._conn.execute(
            "UPDATE runs SET finished_at = ?, status = ?, item_count = ? "
            "WHERE run_id = ?",
            (_now(), status, item_count, run_id),
        )
        self._conn.commit()

    def record_topics(self, run_id: str, topics: list[Topic]) -> None:
        # Keyed on slugify(label), not the raw label: labels are free text
        # the model regenerates every run, so "Shelter Dog Adoption" and
        # "shelter dog adoption" must be treated as the same topic across
        # runs or rank_delta never finds a match against real data. This
        # fixes case and punctuation drift only, not wording drift — a
        # genuinely reworded label ("Rescue Dog Adoptions") still misses.
        self._conn.executemany(
            "INSERT OR REPLACE INTO topics "
            "(run_id, label, trend_score, created_at) VALUES (?, ?, ?, ?)",
            [(run_id, slugify(t.label), t.trend_score, _now()) for t in topics],
        )
        self._conn.executemany(
            "INSERT OR REPLACE INTO topic_scores "
            "(run_id, label, platform, sub_score) VALUES (?, ?, ?, ?)",
            [
                (run_id, slugify(topic.label), platform, value)
                for topic in topics
                for platform, value in topic.score_components.items()
                if platform not in NON_PLATFORM_COMPONENTS
            ],
        )
        self._conn.commit()

    def previous_sub_scores(self, exclude_run_id: str) -> dict[str, dict[str, float]]:
        """Each platform's sub-score per label-slug, from the most recent
        prior run containing that platform/label pair. Keys are
        slugify(label) (see record_topics); callers must look up with the
        same normalisation, which score_topics does.
        """
        rows = self._conn.execute(
            """
            SELECT s.platform, s.label, s.sub_score
            FROM topic_scores s
            JOIN runs r ON r.run_id = s.run_id
            WHERE s.run_id != ?
              AND r.started_at = (
                  SELECT MAX(r2.started_at)
                  FROM topic_scores s2
                  JOIN runs r2 ON r2.run_id = s2.run_id
                  WHERE s2.label = s.label
                    AND s2.platform = s.platform
                    AND s2.run_id != ?
              )
            """,
            (exclude_run_id, exclude_run_id),
        ).fetchall()

        previous: dict[str, dict[str, float]] = {}
        for platform, label, sub_score in rows:
            previous.setdefault(platform, {})[label] = sub_score
        return previous

    def run_summary(self, run_id: str) -> dict | None:
        """Outcome of a run, or None if there is no such run. Used by the CLI
        to report what a run actually did.
        """
        row = self._conn.execute(
            "SELECT status, item_count, finished_at FROM runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if row is None:
            return None
        return {"status": row[0], "item_count": row[1], "finished_at": row[2]}

    def close(self) -> None:
        self._conn.close()


def _now() -> str:
    return datetime.now(UTC).isoformat()
