"""Cross-run history. The minimum needed to detect topics rising and falling."""

import json
import sqlite3
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel

from zeitgeist.analysis.slug import slugify
from zeitgeist.models import Topic
from zeitgeist.projection import TopicRow, flatten
from zeitgeist.records import (
    ORDER,
    RenderRecord,
    RunConfig,
    RunError,
    RunRecordRow,
    RunStatus,
    Stage,
    StageRecord,
)
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
    def __init__(self, path: Path, *, check_same_thread: bool = True) -> None:
        """`check_same_thread` defaults to sqlite3's own safe default: a
        `Store` built for a single thread should leave it alone, and gets
        an immediate `sqlite3.ProgrammingError` if it is ever touched from
        another one.

        The API app (`zeitgeist/api/app.py`) is the one caller that passes
        `False`. It opens a single `Store` for the whole life of the FastAPI
        app, but that connection is touched from more than one thread: ASGI
        servers dispatch sync dependencies and sync path operations through
        a thread pool, and `TestClient` runs the lifespan's startup and
        shutdown on its own portal thread. Passing `False` there is safe
        because `sqlite3.threadsafety == 3` in this environment — the
        underlying SQLite library is built in serialized mode, so a single
        connection is safe to share across threads, concurrently, without
        external locking.
        """
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._path, check_same_thread=check_same_thread)
        # The worker thread writes while the API reads. Without WAL a reader
        # blocks behind every checkpoint write, which the UI feels as the
        # in-flight poll hitching.
        self._conn.execute("PRAGMA journal_mode = WAL")

    def init_schema(self) -> None:
        # "Is this file fresh?" is asked of the whole database, not of one
        # table's name. Probing for a table this version happens to declare
        # takes the create-fresh branch for every *older* schema — whose
        # sentinel table had a different name — so the IF NOT EXISTS DDL runs
        # alongside the old tables and stamps the current version onto them.
        # StoreSchemaError would then never fire for the one transition it
        # exists to catch, and the surviving history would be unreachable
        # rather than reported.
        [(tables,)] = self._conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
        ).fetchall()
        if tables == 0:
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
        """Open a run, or reopen one being resumed.

        Upsert rather than INSERT OR REPLACE, so `started_at` survives a
        resume. The Runs list orders by it and renders a duration from it, so
        replacing the row would make a run resumed a day later claim to have
        begun a day late. Everything else *is* cleared: the outcome, its
        counts and any error describe the previous attempt, which is being
        redone.
        """
        self._conn.execute(
            "INSERT INTO run_records (run_id, status, started_at, config) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(run_id) DO UPDATE SET "
            "status = excluded.status, config = excluded.config, "
            "finished_at = NULL, error = NULL, item_count = NULL, "
            "trends_found = NULL, topics_kept = NULL, phrases_found = NULL",
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
        return None if row is None else _run_record(row)

    def list_runs(self, limit: int, cursor: str | None = None) -> list[RunRecordRow]:
        """Runs newest first, one page at a time.

        `cursor` is the `started_at` of the last row of the previous page.
        Keyset rather than OFFSET: a run started between two requests would
        shift an offset-paginated page and duplicate a row across the seam.
        """
        sql = (
            "SELECT run_id, status, started_at, finished_at, config, error, "
            "item_count, trends_found, topics_kept, phrases_found "
            "FROM run_records "
        )
        params: tuple[object, ...] = ()
        if cursor is not None:
            sql += "WHERE started_at < ? "
            params = (cursor,)
        sql += "ORDER BY started_at DESC LIMIT ?"
        rows = self._conn.execute(sql, (*params, limit)).fetchall()
        return [_run_record(row) for row in rows]

    def render_counts(self, run_id: str) -> dict[str, int]:
        """Renders per topic for one run.

        A COUNT at query time rather than a column on `run_topics`: a
        denormalised count would have to be kept correct on every render
        insert, failure and delete, including from phase 4's separate
        executor.
        """
        rows = self._conn.execute(
            "SELECT topic_id, COUNT(*) FROM renders WHERE run_id = ? GROUP BY topic_id",
            (run_id,),
        ).fetchall()
        return {topic_id: count for topic_id, count in rows}

    def topic_recurrence(self, label_slug: str) -> tuple[int, str | None]:
        """How many runs this topic appeared in, and the earliest.

        Keyed on `label_slug` because that is the only cross-run identity
        the store has: labels are model-generated every run, and the slug
        fixes case and punctuation drift but not wording drift. A topic
        relabelled "Rescue Dog Adoptions" from "Shelter Dog Adoption" reads
        as new, so the count is a floor rather than a total.
        """
        row = self._conn.execute(
            "SELECT COUNT(DISTINCT t.run_id), MIN(r.started_at || '|' || t.run_id) "
            "FROM run_topics t JOIN run_records r ON r.run_id = t.run_id "
            "WHERE t.label_slug = ?",
            (label_slug,),
        ).fetchone()
        count, earliest = row
        first_seen = earliest.split("|", 1)[1] if earliest else None
        return count, first_seen

    def _insert_topic_scores(self, run_id: str, topics: Sequence[Topic]) -> None:
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

    def previous_sub_scores(self, exclude_run_id: str) -> dict[str, dict[str, float]]:
        """Each platform's sub-score per label-slug, from the most recent
        prior run containing that platform/label pair. Keys are
        slugify(label) (see `_insert_topic_scores`); callers must look up with
        the same normalisation, which score_topics does.
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

    def write_run_topics(self, rows: Sequence[TopicRow]) -> None:
        with self._conn:
            self._insert_run_topics(rows)

    def _insert_run_topics(self, rows: Sequence[TopicRow]) -> None:
        self._conn.executemany(
            "INSERT OR REPLACE INTO run_topics (run_id, topic_id, label, "
            "label_slug, trend_status, event_sentiment, conversation_register, "
            "meme_potential, trend_score, final_score, final_rank, post_count, "
            "top_phrase, top_phrase_authors) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    row.run_id,
                    row.topic_id,
                    row.label,
                    row.label_slug,
                    row.trend_status,
                    row.event_sentiment,
                    row.conversation_register,
                    row.meme_potential,
                    row.trend_score,
                    row.final_score,
                    row.final_rank,
                    row.post_count,
                    row.top_phrase,
                    row.top_phrase_authors,
                )
                for row in rows
            ],
        )

    def run_topics(self, run_id: str) -> list[TopicRow]:
        rows = self._conn.execute(
            "SELECT run_id, topic_id, label, label_slug, trend_status, "
            "event_sentiment, conversation_register, meme_potential, trend_score, "
            "final_score, final_rank, post_count, top_phrase, top_phrase_authors "
            "FROM run_topics WHERE run_id = ? ORDER BY final_rank",
            (run_id,),
        ).fetchall()
        return [
            TopicRow(
                run_id=row[0],
                topic_id=row[1],
                label=row[2],
                label_slug=row[3],
                trend_status=row[4],
                event_sentiment=row[5],
                conversation_register=row[6],
                meme_potential=row[7],
                trend_score=row[8],
                final_score=row[9],
                final_rank=row[10],
                post_count=row[11],
                top_phrase=row[12],
                top_phrase_authors=row[13],
            )
            for row in rows
        ]

    def write_checkpoint(
        self, run_id: str, stage: Stage, models: Sequence[BaseModel]
    ) -> int:
        """Persist a stage's output. Returns the payload's size in bytes,
        which is what the stage card displays.

        Sequence rather than list: list is invariant, so a list[Topic] is not
        a list[BaseModel] and every call site would be rejected.
        """
        payload = json.dumps([model.model_dump(mode="json") for model in models])
        with self._conn:
            self._insert_checkpoint(run_id, stage, payload)
        return len(payload.encode("utf-8"))

    def _insert_checkpoint(self, run_id: str, stage: Stage, payload: str) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO checkpoints "
            "(run_id, stage, payload, written_at) VALUES (?, ?, ?, ?)",
            (run_id, stage.value, payload, _now()),
        )

    def write_analyse_checkpoint(
        self, run_id: str, topics: Sequence[Topic], meme_potential_weight: float
    ) -> int:
        """Write the analyse payload and everything derived from it in one
        transaction.

        Together, or not at all. `run_topics` and `topic_scores` are both
        derived from this payload, and the claim that they cannot disagree
        with it only holds if a crash leaves none of the three.

        Both derived tables are cleared for this run first. Their keys are
        `(run_id, topic_id)` and `(run_id, label, platform)`, so an upsert
        alone would leave rows for topics the *previous* analyse produced and
        this one did not: three rows against a two-topic checkpoint, two of
        them ranked 1. Re-analysing is reachable from `start_at=ANALYSE`, and
        those stale sub-scores feed the next run's rank delta.
        """
        payload = json.dumps([topic.model_dump(mode="json") for topic in topics])
        rows = flatten(run_id, list(topics), meme_potential_weight)
        with self._conn:
            self._insert_checkpoint(run_id, Stage.ANALYSE, payload)
            self._conn.execute("DELETE FROM run_topics WHERE run_id = ?", (run_id,))
            self._insert_run_topics(rows)
            self._conn.execute("DELETE FROM topic_scores WHERE run_id = ?", (run_id,))
            self._insert_topic_scores(run_id, topics)
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

    def written_stages(self, run_id: str) -> set[Stage]:
        """Which stages have a checkpoint, without reading the payloads.

        `read_checkpoint` would deserialise a run's whole evidence to answer
        a question about row existence.
        """
        rows = self._conn.execute(
            "SELECT stage FROM checkpoints WHERE run_id = ?", (run_id,)
        ).fetchall()
        return {Stage(stage) for (stage,) in rows}

    def record_stage(self, run_id: str, record: StageRecord) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO run_stages (run_id, stage, status, "
            "started_at, finished_at, payload_bytes, summary) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                run_id,
                record.stage.value,
                record.status,
                record.started_at.isoformat() if record.started_at else None,
                record.finished_at.isoformat() if record.finished_at else None,
                record.payload_bytes,
                record.summary,
            ),
        )
        self._conn.commit()

    def stages_for_run(self, run_id: str) -> list[StageRecord]:
        """In pipeline order. The four stage cards are drawn in the order the
        stages run, which is not the order their rows were written.
        """
        rows = self._conn.execute(
            "SELECT stage, status, started_at, finished_at, payload_bytes, summary "
            "FROM run_stages WHERE run_id = ?",
            (run_id,),
        ).fetchall()
        records = [
            StageRecord(
                stage=Stage(row[0]),
                status=row[1],
                started_at=datetime.fromisoformat(row[2]) if row[2] else None,
                finished_at=datetime.fromisoformat(row[3]) if row[3] else None,
                payload_bytes=row[4],
                summary=row[5],
            )
            for row in rows
        ]
        return sorted(records, key=lambda record: ORDER.index(record.stage))

    def add_render(self, record: RenderRecord) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO renders (id, run_id, topic_id, template_id, "
            "caption_slots, origin, status, error, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                record.id,
                record.run_id,
                record.topic_id,
                record.template_id,
                json.dumps(record.caption_slots),
                record.origin.model_dump_json(),
                record.status,
                record.error,
                record.created_at.isoformat(),
            ),
        )
        self._conn.commit()

    def get_render(self, render_id: str) -> RenderRecord | None:
        row = self._conn.execute(
            "SELECT id, run_id, topic_id, template_id, caption_slots, origin, "
            "status, error, created_at FROM renders WHERE id = ?",
            (render_id,),
        ).fetchone()
        return None if row is None else _render(row)

    def renders_for_run(self, run_id: str) -> list[RenderRecord]:
        rows = self._conn.execute(
            "SELECT id, run_id, topic_id, template_id, caption_slots, origin, "
            "status, error, created_at FROM renders WHERE run_id = ? "
            "ORDER BY created_at, id",
            (run_id,),
        ).fetchall()
        return [_render(row) for row in rows]

    def get_settings(self) -> dict[str, str]:
        return {
            row[0]: row[1]
            for row in self._conn.execute("SELECT key, value FROM settings")
        }

    def set_setting(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES (?, ?, ?)",
            (key, value, _now()),
        )
        self._conn.commit()

    def clear_setting(self, key: str) -> None:
        """Delete the override so the .env value, or the field default, applies
        again. This is what the settings screen's "Reset to .env" does.
        """
        self._conn.execute("DELETE FROM settings WHERE key = ?", (key,))
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _run_record(row: tuple) -> RunRecordRow:
    """Rebuild a `RunRecordRow` from a row. Shared by `get_run` and
    `list_runs`, whose column list and parsing are identical — two copies
    would drift.
    """
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


def _render(row: tuple) -> RenderRecord:
    """Rebuild a RenderRecord from a row.

    `origin` goes back through the model rather than being reconstructed by
    hand, so the discriminator picks the concrete class and a manual render
    cannot come back carrying a rationale.
    """
    return RenderRecord(
        id=row[0],
        run_id=row[1],
        topic_id=row[2],
        template_id=row[3],
        caption_slots=json.loads(row[4]),
        origin=json.loads(row[5]),
        status=row[6],
        error=row[7],
        created_at=datetime.fromisoformat(row[8]),
    )
