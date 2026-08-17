"""Cross-run history. The minimum needed to detect topics rising and falling."""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from zeitgeist.models import Topic

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id      TEXT PRIMARY KEY,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    status      TEXT,
    post_count  INTEGER
);

CREATE TABLE IF NOT EXISTS topics (
    run_id      TEXT NOT NULL,
    label       TEXT NOT NULL,
    trend_score REAL NOT NULL,
    created_at  TEXT NOT NULL,
    PRIMARY KEY (run_id, label)
);

CREATE INDEX IF NOT EXISTS idx_topics_label ON topics (label);
"""


class Store:
    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._path)

    def init_schema(self) -> None:
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def start_run(self, run_id: str) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO runs (run_id, started_at) VALUES (?, ?)",
            (run_id, _now()),
        )
        self._conn.commit()

    def finish_run(self, run_id: str, status: str, post_count: int) -> None:
        self._conn.execute(
            "UPDATE runs SET finished_at = ?, status = ?, post_count = ? "
            "WHERE run_id = ?",
            (_now(), status, post_count, run_id),
        )
        self._conn.commit()

    def record_topics(self, run_id: str, topics: list[Topic]) -> None:
        self._conn.executemany(
            "INSERT OR REPLACE INTO topics "
            "(run_id, label, trend_score, created_at) VALUES (?, ?, ?, ?)",
            [(run_id, t.label, t.trend_score, _now()) for t in topics],
        )
        self._conn.commit()

    def previous_scores(self, exclude_run_id: str) -> dict[str, float]:
        """Each label's score from the most recent prior run containing it."""
        rows = self._conn.execute(
            """
            SELECT t.label, t.trend_score
            FROM topics t
            JOIN runs r ON r.run_id = t.run_id
            WHERE t.run_id != ?
              AND r.started_at = (
                  SELECT MAX(r2.started_at)
                  FROM topics t2
                  JOIN runs r2 ON r2.run_id = t2.run_id
                  WHERE t2.label = t.label AND t2.run_id != ?
              )
            """,
            (exclude_run_id, exclude_run_id),
        ).fetchall()
        return {label: score for label, score in rows}

    def run_summary(self, run_id: str) -> dict | None:
        """Outcome of a run, or None if there is no such run. Used by the CLI
        to report what a run actually did.
        """
        row = self._conn.execute(
            "SELECT status, post_count, finished_at FROM runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if row is None:
            return None
        return {"status": row[0], "post_count": row[1], "finished_at": row[2]}

    def close(self) -> None:
        self._conn.close()


def _now() -> str:
    return datetime.now(UTC).isoformat()
