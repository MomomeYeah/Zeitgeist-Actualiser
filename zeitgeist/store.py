"""Cross-run history. The minimum needed to detect topics rising and falling."""

import json
import sqlite3
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel

from zeitgeist.analysis.slug import slugify
from zeitgeist.models import Topic
from zeitgeist.records import RunConfig, RunError, RunRecordRow, RunStatus, Stage
from zeitgeist.schema import SCHEMA, SCHEMA_VERSION

__all__ = ["SCHEMA_VERSION", "MissingCheckpoint", "Store", "StoreSchemaError"]

# score_components carries this alongside the real platform sub-scores. It is a
# multiplier, not a platform's opinion, so it must never reach topic_scores or be
# counted as a platform contributing to a topic.
NON_PLATFORM_COMPONENTS = frozenset({"corroboration"})


class StoreSchemaError(RuntimeError):
    """The database on disk was written by a different schema version."""


class MissingCheckpoint(Exception):
    """A stage was resumed from, but its predecessor never wrote anything.

    Distinct from an empty checkpoint, which is a result: a generate stage
    that briefed nothing wrote `[]`, and resuming past it is legitimate.
    """


class Store:
    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._path)
        # The worker thread writes while the API reads. Without WAL a reader
        # blocks behind every checkpoint write, which the UI feels as the
        # in-flight poll hitching.
        self._conn.execute("PRAGMA journal_mode = WAL")

    def init_schema(self) -> None:
        existing = self._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='run_records'"
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

    def start_run(self, run_id: str, config: RunConfig) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO run_records "
            "(run_id, status, started_at, config) VALUES (?, ?, ?, ?)",
            (run_id, "running", _now(), config.model_dump_json()),
        )
        self._conn.commit()

    def finish_run(
        self,
        run_id: str,
        *,
        status: RunStatus,
        item_count: int,
        trends_found: int,
        topics_kept: int,
        phrases_found: int,
    ) -> None:
        self._conn.execute(
            "UPDATE run_records SET status = ?, finished_at = ?, item_count = ?, "
            "trends_found = ?, topics_kept = ?, phrases_found = ? WHERE run_id = ?",
            (
                status,
                _now(),
                item_count,
                trends_found,
                topics_kept,
                phrases_found,
                run_id,
            ),
        )
        self._conn.commit()

    def fail_run(self, run_id: str, error: RunError) -> None:
        """Record why a run failed.

        Separate from finish_run rather than a status argument to it, because
        a failure has no counts to record and an error to record instead.
        """
        self._conn.execute(
            "UPDATE run_records SET status = ?, finished_at = ?, error = ? "
            "WHERE run_id = ?",
            ("failed", _now(), error.model_dump_json(), run_id),
        )
        self._conn.commit()

    def get_run(self, run_id: str) -> RunRecordRow | None:
        row = self._conn.execute(
            "SELECT run_id, status, started_at, finished_at, config, error, "
            "item_count, trends_found, topics_kept, phrases_found "
            "FROM run_records WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if row is None:
            return None
        return RunRecordRow(
            run_id=row[0],
            status=row[1],
            started_at=datetime.fromisoformat(row[2]),
            finished_at=datetime.fromisoformat(row[3]) if row[3] else None,
            config=RunConfig.model_validate_json(row[4]),
            error=RunError.model_validate_json(row[5]) if row[5] else None,
            item_count=row[6],
            trends_found=row[7],
            topics_kept=row[8],
            phrases_found=row[9],
        )

    def record_topics(self, run_id: str, topics: list[Topic]) -> None:
        # Keyed on slugify(label), not the raw label: labels are free text
        # the model regenerates every run, so "Shelter Dog Adoption" and
        # "shelter dog adoption" must be treated as the same topic across
        # runs or rank_delta never finds a match against real data. This
        # fixes case and punctuation drift only, not wording drift — a
        # genuinely reworded label ("Rescue Dog Adoptions") still misses.
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
            JOIN run_records r ON r.run_id = s.run_id
            WHERE s.run_id != ?
              AND r.started_at = (
                  SELECT MAX(r2.started_at)
                  FROM topic_scores s2
                  JOIN run_records r2 ON r2.run_id = s2.run_id
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

    def write_checkpoint(
        self, run_id: str, stage: Stage, models: Sequence[BaseModel]
    ) -> int:
        """Persist a stage's output. Returns the payload's size in bytes,
        which is what the stage card displays.

        Sequence rather than list: list is invariant, so a list[Topic] is not
        a list[BaseModel] and every call site would be rejected.
        """
        payload = json.dumps([model.model_dump(mode="json") for model in models])
        self._conn.execute(
            "INSERT OR REPLACE INTO checkpoints "
            "(run_id, stage, payload, written_at) VALUES (?, ?, ?, ?)",
            (run_id, stage.value, payload, _now()),
        )
        self._conn.commit()
        return len(payload.encode("utf-8"))

    def read_checkpoint[T: BaseModel](
        self, run_id: str, stage: Stage, schema: type[T]
    ) -> list[T]:
        row = self._conn.execute(
            "SELECT payload FROM checkpoints WHERE run_id = ? AND stage = ?",
            (run_id, stage.value),
        ).fetchone()
        if row is None:
            raise MissingCheckpoint(f"Run {run_id!r} has no {stage.value} checkpoint")
        return [schema.model_validate(entry) for entry in json.loads(row[0])]

    def close(self) -> None:
        self._conn.close()


def _now() -> str:
    return datetime.now(UTC).isoformat()
