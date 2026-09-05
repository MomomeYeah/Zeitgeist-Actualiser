"""A TestClient over a Store seeded with real runs.

Seeded through the store's own writers rather than raw SQL: a hand-written
INSERT would keep passing after `write_analyse_checkpoint` changed shape,
and the endpoints would be serving a table layout nothing produces.

`api_settings` points `output_dir` inside `tmp_path` and reads `db_path`
from `DB_PATH`, so a test's renders and database are its own.
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
from zeitgeist.records import (
    RenderRecord,
    RunConfig,
    RunError,
    RunStatus,
    Stage,
    StageRecord,
)
from zeitgeist.store import Store

# Clients `seeded_client` has entered as a context manager, awaiting exit.
#
# `seeded_client` returns a plain client to its 52 call sites, unchanged, so
# entering the lifespan here rather than pushing `with seeded_client(...) as
# client:` onto every one of them. Something still has to call `__exit__` or
# the store each client opened leaks for the process's lifetime, so this
# module remembers what it opened and `conftest`'s autouse fixture closes
# each one after the test body finishes — the same shape `TestClient` itself
# would use if two tests couldn't ever run inside the same process.
_open_clients: list[TestClient] = []


@dataclass
class SeededRun:
    """One run to write into the store before the client is built."""

    run_id: str = "20260901T120000Z"
    status: RunStatus = "ok"
    config: RunConfig = field(default_factory=make_run_config)
    topics: list[Topic] = field(default_factory=lambda: [make_topic()])
    stages: list[StageRecord] = field(default_factory=list)
    renders: list[RenderRecord] = field(default_factory=list)
    evidence: list[TrendEvidence] = field(default_factory=list)


def api_settings(tmp_path: Path) -> Settings:
    """Build the `Settings` a test's `TestClient` runs against.

    `db_path` is read from `DB_PATH` rather than chosen here, because
    `SettingsTableSource` resolves the settings table from that variable and
    not from `Settings.db_path` — asking the object being constructed where
    its own table lives would be circular (see
    settings_source.SettingsTableSource's docstring). `conftest`'s autouse
    fixture already points `DB_PATH` at a per-test path inside `tmp_path`
    before every test body runs, so reading it here makes this factory and
    the settings source agree by construction, with no environment mutation
    and nothing to clean up.
    """
    return Settings(
        _env_file=None,
        db_path=Path(os.environ["DB_PATH"]),
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

    if spec.status == "running":
        return  # start_run already left the row in this state.
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
        return
    if spec.status == "failed":
        store.fail_run(
            spec.run_id,
            RunError(
                kind="SeededFailure",
                message="seeded as failed",
                stage=Stage.INGEST,
            ),
        )
        return
    # "aborted" and "interrupted" have no writer anywhere in this phase —
    # see records.RunStatus's docstring: phase 3's execution service is what
    # will honour the stop button and reconcile a dead process into these,
    # and no accessor exists yet that produces either. A test that needs one
    # would be testing a state this phase cannot actually write, so this
    # fails loudly rather than silently leaving the row "running".
    raise NotImplementedError(
        f"seed_run has no way to write status={spec.status!r} yet — phase 3's "
        "execution service is what writes it"
    )


def seeded_client(tmp_path: Path, *, runs: Sequence[SeededRun] = ()) -> TestClient:
    """An app over a store holding `runs`, with its lifespan already running.

    The store is seeded before `create_app` opens its own connection, so the
    app sees the rows on its first query.

    `TestClient` only runs startup/shutdown when entered as a context
    manager; a bare `TestClient(app)` serves requests with the lifespan
    never having fired. Entering it here — and registering it in
    `_open_clients` for `conftest`'s autouse fixture to exit later — means
    every caller gets a client whose lifespan has actually started, without
    having to become a `with` block itself.
    """
    settings = api_settings(tmp_path)
    store = Store(settings.db_path)
    store.init_schema()
    for spec in runs:
        seed_run(store, spec)
    store.close()
    client = TestClient(create_app(settings))
    client.__enter__()
    _open_clients.append(client)
    return client
