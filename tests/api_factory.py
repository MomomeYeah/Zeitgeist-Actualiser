"""A TestClient over a Store seeded with real runs.

Seeded through the store's own writers rather than raw SQL: a hand-written
INSERT would keep passing after `write_analyse_checkpoint` changed shape,
and the endpoints would be serving a table layout nothing produces.

`api_settings` points `output_dir` inside `tmp_path` and reads `db_path`
from `DB_PATH`, so a test's renders and database are its own.
"""

import logging
import os
import threading
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from tests.run_factory import make_run_config, make_topic
from zeitgeist.api import create_app
from zeitgeist.config import Settings
from zeitgeist.generation import GenerateFn
from zeitgeist.models import Topic, TrendEvidence
from zeitgeist.records import (
    RenderRecord,
    RunConfig,
    RunError,
    RunStatus,
    Stage,
    StageRecord,
)
from zeitgeist.runner import ExecuteFn
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


@dataclass
class GatedExecute:
    """A run that blocks until released, so a test can hold the worker in a
    known state without sleeping. Lives here rather than in one test module
    because both the control tests and the SSE tests need it.

    It opens the run row, because the real executor reaches `run_pipeline`
    and `run_pipeline` is what calls `store.start_run`. Without that, every
    endpoint guarded by `_run_or_404` — the event stream among them —
    answers 404 for a run that is executing.
    """

    entered: threading.Event = field(default_factory=threading.Event)
    release: threading.Event = field(default_factory=threading.Event)
    run_ids: list[str] = field(default_factory=list)

    def __call__(self, settings, request, store, observer, token) -> None:
        run_id = request.run_id or ""
        store.start_run(run_id, make_run_config())
        self.run_ids.append(run_id)
        self.entered.set()
        assert self.release.wait(timeout=5), "release was never set"


@dataclass
class LoggingGate:
    """A run that opens its row, logs one line, then blocks until released.

    The line has to be emitted while the run is still executing, because the
    worker drops the buffer the moment it ends — so a stream opened after the
    run finished can never carry it.
    """

    message: str = "hello from the run"
    entered: threading.Event = field(default_factory=threading.Event)
    release: threading.Event = field(default_factory=threading.Event)

    def __call__(self, settings, request, store, observer, token) -> None:
        store.start_run(request.run_id or "", make_run_config())
        logging.getLogger("zeitgeist.testing.sse").info(self.message)
        self.entered.set()
        assert self.release.wait(timeout=5), "release was never set"


def api_settings(
    tmp_path: Path,
    *,
    templates_dir: Path | None = None,
    anthropic_api_key: str | None = None,
) -> Settings:
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

    `templates_dir` lets a test own its template library outright, the way
    `test_pipeline.py` already does: a generation test that named a shipped
    template would break when the library changed, for reasons that have
    nothing to do with generation.

    `anthropic_api_key` exists because `GenerationService.submit` builds a
    provider on the request thread, and `llm_provider` defaults to
    "anthropic", whose factory raises on an empty key — which this suite
    guarantees, since `conftest` strips `ANTHROPIC_API_KEY` for every test.
    A test posting `mode: "llm"` without it gets a 400 from the endpoint's
    `except ValueError` branch rather than the 202 it is asserting on. It
    stays hermetic: `AnthropicProvider.__init__` only constructs the SDK
    client and makes no network call, and such tests inject a `generate`
    seam so nothing ever calls through it.
    """
    # Built as a plain dict rather than the brief's inline `**({} if ... )`
    # splats: ty infers each conditional dict literal's value type from
    # both branches together, so a `Path`-only branch and a `str`-only
    # branch each widen to a type the *other* keyword-only parameter
    # rejects, and it reports one such mismatch per field on `Settings`.
    # `dict[str, Any]` sidesteps that — the values really are heterogeneous
    # here, `Settings` still validates them, and the resulting call passes
    # identical arguments either way.
    kwargs: dict[str, Any] = {
        "_env_file": None,
        "db_path": Path(os.environ["DB_PATH"]),
        "output_dir": tmp_path / "output",
    }
    if templates_dir is not None:
        kwargs["templates_dir"] = templates_dir
    if anthropic_api_key is not None:
        kwargs["anthropic_api_key"] = anthropic_api_key
    return Settings(**kwargs)


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
    if spec.status == "aborted":
        # Store.abort_run is exactly the writer the "no writer anywhere in
        # this phase" comment used to say did not exist — it does now,
        # phase 3's stop/abort endpoints are what call it, and Critical 2's
        # tests want a run seeded straight into this status.
        store.abort_run(spec.run_id)
        return
    # "interrupted" still has no writer this factory can safely use for one
    # run in isolation: Store.reconcile_interrupted is the only accessor
    # that produces it, and it marks *every* row still "running" across the
    # whole store, not just this one — reconciling it here would also flip
    # any other "running" run a test happened to seed alongside it. A test
    # that needs "interrupted" would be testing a state this factory cannot
    # write for a single run, so this fails loudly rather than silently
    # leaving the row "running" or reconciling rows the test never asked
    # about.
    raise NotImplementedError(
        f"seed_run has no way to write status={spec.status!r} for one run in isolation"
    )


def seeded_client(
    tmp_path: Path,
    *,
    runs: Sequence[SeededRun] = (),
    execute: ExecuteFn | None = None,
    generate: GenerateFn | None = None,
    templates_dir: Path | None = None,
    anthropic_api_key: str | None = None,
) -> TestClient:
    """An app over a store holding `runs`, with its lifespan already running.

    The store is seeded before `create_app` opens its own connection, so the
    app sees the rows on its first query.

    `TestClient` only runs startup/shutdown when entered as a context
    manager; a bare `TestClient(app)` serves requests with the lifespan
    never having fired. Entering it here — and registering it in
    `_open_clients` for `conftest`'s autouse fixture to exit later — means
    every caller gets a client whose lifespan has actually started, without
    having to become a `with` block itself.

    `execute` threads a fake executor into the app's `RunService`, so a test
    can drive the queue without a real pipeline.

    `generate` does the same for the `GenerationService`, so a test can
    drive the endpoint without Pillow or a model. `templates_dir` and
    `anthropic_api_key` pass straight through to `api_settings`; see its
    docstring for why the second one is needed.
    """
    settings = api_settings(
        tmp_path,
        templates_dir=templates_dir,
        anthropic_api_key=anthropic_api_key,
    )
    store = Store(settings.db_path)
    store.init_schema()
    for spec in runs:
        seed_run(store, spec)
    store.close()
    client = TestClient(create_app(settings, execute=execute, generate=generate))
    client.__enter__()
    _open_clients.append(client)
    return client
