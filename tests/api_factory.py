"""A TestClient over a Store seeded with real runs.

Seeded through the store's own writers rather than raw SQL: a hand-written
INSERT would keep passing after `write_analyse_checkpoint` changed shape,
and the endpoints would be serving a table layout nothing produces.

`api_settings` points `output_dir` and `db_path` inside `tmp_path`, so a
test's renders and database are its own.
"""

import os
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from fastapi.testclient import TestClient

from tests.run_factory import make_run_config, make_topic
from zeitgeist.api import create_app
from zeitgeist.config import Settings
from zeitgeist.models import Topic, TrendEvidence
from zeitgeist.records import RenderRecord, RunConfig, Stage, StageRecord
from zeitgeist.store import Store


@dataclass
class SeededRun:
    """One run to write into the store before the client is built."""

    run_id: str = "20260901T120000Z"
    status: str = "ok"
    config: RunConfig = field(default_factory=make_run_config)
    topics: list[Topic] = field(default_factory=lambda: [make_topic()])
    stages: list[StageRecord] = field(default_factory=list)
    renders: list[RenderRecord] = field(default_factory=list)
    evidence: list[TrendEvidence] = field(default_factory=list)


def api_settings(tmp_path: Path) -> Settings:
    # SettingsTableSource resolves where the settings table lives from
    # DB_PATH (environment, then .env) rather than from this call's own
    # db_path= argument: that argument becomes Settings.db_path, the object
    # being constructed, and asking it where its own table is would be
    # circular (see settings_source.SettingsTableSource's docstring). So
    # DB_PATH is set here too, to the same file, the way
    # tests/test_settings_source.py always does with monkeypatch.setenv —
    # without it, a store.set_setting() written to this db_path is invisible
    # to every Settings() this factory builds, because the table source goes
    # looking in conftest's no-ambient-database.db instead.
    db_path = tmp_path / "data" / "z.db"
    os.environ["DB_PATH"] = str(db_path)
    return Settings(
        _env_file=None,
        db_path=db_path,
        output_dir=tmp_path / "output",
    )


def seed_run(store: Store, spec: SeededRun) -> None:
    """Write one run the way the pipeline would have."""
    store.start_run(spec.run_id, spec.config)
    if spec.evidence:
        store.write_checkpoint(spec.run_id, Stage.INGEST, spec.evidence)
    if spec.topics:
        store.write_analyse_checkpoint(
            spec.run_id, spec.topics, spec.config.meme_potential_weight
        )
    for stage in spec.stages:
        store.record_stage(spec.run_id, stage)
    for render in spec.renders:
        store.add_render(render)
    if spec.status == "ok":
        store.finish_run(
            spec.run_id,
            status="ok",
            item_count=sum(len(t.item_ids) for t in spec.topics),
            trends_found=len(spec.topics),
            topics_kept=min(spec.config.top_count, len(spec.topics)),
            phrases_found=sum(
                len(t.dossier.recurring_phrases) if t.dossier else 0
                for t in spec.topics
            ),
        )


def seeded_client(tmp_path: Path, *, runs: Sequence[SeededRun] = ()) -> TestClient:
    """An app over a store holding `runs`.

    The store is seeded before `create_app` opens its own connection, so the
    app sees the rows on its first query.
    """
    settings = api_settings(tmp_path)
    store = Store(settings.db_path)
    store.init_schema()
    for spec in runs:
        seed_run(store, spec)
    store.close()
    return TestClient(create_app(settings))
