# Web UI Phase 2 — Read API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Serve everything phase 1 persisted over HTTP, so a run produced by `scripts/run_pipeline.py` is fully readable through a REST API.

**Architecture:** A FastAPI app built by a factory that takes `Settings`, opens one `Store`, and mounts four resource routers — runs, topics, renders, settings. Endpoints read the tables phase 1 wrote; the two that need prose (topic detail's dossier and replies) read the checkpoint payloads for the one topic being viewed. No writes, no SSE, no frontend.

**Tech Stack:** Python 3.14, FastAPI, uvicorn, pydantic 2, sqlite3 (stdlib), pytest with FastAPI's `TestClient`.

## Global Constraints

Copied from `docs/superpowers/specs/2026-09-02-web-ui-design.md`. Every task's requirements implicitly include this section.

- **Definition of Done, run before claiming any task complete:** `uv run ruff check .`, `uv run ruff format --check .`, `uv run ty check`, `uv run pytest`. All four must pass. **Unlike phase 1, there is no red window — the tree is green at the start of every task and must be green at the end.** The frontend gate commands do not exist yet and must not be added.
- **Resource-shaped REST, not screen-shaped.** The merged Topics screen issues three parallel queries rather than hitting one bespoke endpoint, so each response stays independently cacheable and the in-flight poll does not drag topic data along with it. Do not add a `/api/overview`.
- **`GET /api/runs/{id}/topics` returns the full ordering**, not just the kept topics — the ranking screen draws below-the-cut rows with their ranks and scores before dimming them. `run_topics` already holds every topic; the endpoint queries it and does no sorting of its own.
- **Never re-derive the trend-versus-meme blend.** `sentiment.rank_score` is the single place it is defined, and `run_topics.final_rank` was written with it. The API sorts by the stored rank.
- **Meme counts are `COUNT(*)` over `renders` at query time**, never a denormalised column.
- **`ANTHROPIC_API_KEY` is never returned**, in any form, by any endpoint.
- **No migrations.** `SCHEMA_VERSION` stays 3; this phase adds no tables and no columns.
- **Optionality expresses a real state, never a migration concession.**
- Python 3.14: PEP 695 generics (`def f[T: Bound](...)`), never `typing.TypeVar`.
- **`model_config = STRICT`** (`ConfigDict(extra="forbid")`, in `zeitgeist/models.py`) on every new pydantic model.
- ruff: line length 88, rules `E, F, I, UP, B, SIM`. `docs/` is excluded.
- ty: fix type errors at the root cause. No blanket `# type: ignore`; a narrow suppression needs a comment explaining why.
- **Tests are hermetic.** No network. `tests/conftest.py`'s autouse fixture strips every environment variable `Settings` reads and repoints `DB_PATH` at a per-test path — if you add a `Settings` field that reads the environment, add its variable to `_SETTINGS_ENV_VARS`.
- **Fixtures are built through the real models**, never hand-written dicts. `tests/run_factory.py` and `tests/template_factory.py` are the established pattern.

## What phase 1 left you

`Store` (`zeitgeist/store.py`) already has, and you should not reimplement:

`init_schema`, `start_run(run_id, config)`, `finish_run(run_id, *, status, item_count, trends_found, topics_kept, phrases_found)`, `fail_run(run_id, error)`, `get_run(run_id) -> RunRecordRow | None`, `previous_sub_scores(exclude_run_id)`, `write_run_topics(rows)`, `run_topics(run_id) -> list[TopicRow]`, `write_checkpoint(run_id, stage, models) -> int`, `write_analyse_checkpoint(run_id, topics, meme_potential_weight) -> int`, `read_checkpoint[T: BaseModel](run_id, stage, schema) -> list[T]`, `record_stage(run_id, record)`, `stages_for_run(run_id) -> list[StageRecord]`, `add_render(record)`, `get_render(render_id) -> RenderRecord | None`, `renders_for_run(run_id) -> list[RenderRecord]`, `get_settings() -> dict[str, str]`, `set_setting(key, value)`, `clear_setting(key)`, `close()`. `MissingCheckpoint` is raised by `read_checkpoint`.

Models: `zeitgeist/records.py` has `Stage`, `ORDER`, `RunStatus`, `StageStatus`, `RunConfig`, `RunError`, `RunRecordRow`, `StageRecord`, `AutoOrigin`, `ManualOrigin`, `Origin`, `RenderRecord`. `zeitgeist/projection.py` has `TopicRow` and `flatten`. `zeitgeist/models.py` has the pipeline domain — `Topic`, `ScoredTopic`, `Dossier`, `Phrase`, `TrendEvidence`, `PostEvidence`, `Item`, `Reply`, `MediaBrief`, `Sentiment`, `Register`, `TrendStatus`, `STRICT`.

`zeitgeist/settings_source.py` has `WRITABLE_KEYS` (the seven tunable fields) and `_dotenv_value(key)`.

Renders live at `Settings.output_dir / <run_id> / "renders" / f"{render_id}.png"`, with a thumbnail at `f"{render_id}.thumb.png"`.

## File Structure

**Created:**

| File | Responsibility |
| --- | --- |
| `zeitgeist/api/__init__.py` | Exports `create_app`. |
| `zeitgeist/api/app.py` | The app factory and its dependencies — one `Store` per app, `Settings` injected. Mounts the routers. Nothing endpoint-specific. |
| `zeitgeist/api/schemas.py` | Response models for the endpoints whose shape is a composition rather than a stored row. Storage models are returned directly where they suffice. |
| `zeitgeist/api/runs.py` | The runs router: list, detail, ranking, topic detail, log. Five endpoints, all scoped to one run. |
| `zeitgeist/api/topics.py` | The cross-run topics index. One endpoint, the most complex query in the phase. |
| `zeitgeist/api/renders.py` | Render detail and image serving. |
| `zeitgeist/api/settings.py` | The settings read, including which layer supplied each value. |
| `zeitgeist/serve.py` | The console entry point: builds the app and runs uvicorn. |
| `tests/api_factory.py` | Builds a `TestClient` over a `Store` seeded with a real run. |
| `tests/test_api_runs.py`, `tests/test_api_topics.py`, `tests/test_api_renders.py`, `tests/test_api_settings.py`, `tests/test_api_app.py` | One test module per router. |

**Modified:** `zeitgeist/store.py` (four new read accessors), `zeitgeist/records.py` (`LogLine`), `pyproject.toml` (dependencies and `[project.scripts]`), `README.md`.

Routers are split by resource rather than kept in one `app.py` because `runs.py` alone carries five endpoints and the topic-detail one reads two checkpoint payloads; a single module would be the largest file in the codebase by a wide margin. `store.py` is already 430 lines — the new accessors are four short queries, which it absorbs without needing a split.

**Deliberately not in this phase:** no writes of any kind (`PUT /api/settings` is phase 3), no `/api/runs/active`, no SSE, no `/api/config/options`, and **no generated TypeScript**. The spec moved type generation to phase 5, where a toolchain exists to lint the result; this phase exposes the OpenAPI schema and documents the command.

---

### Task 1: The app factory and `zeitgeist serve`

**Files:**
- Create: `zeitgeist/api/__init__.py`, `zeitgeist/api/app.py`, `zeitgeist/serve.py`
- Create: `tests/test_api_app.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Consumes: `Settings` from `zeitgeist.config`, `Store` from `zeitgeist.store`.
- Produces:
  - `zeitgeist.api.create_app(settings: Settings) -> FastAPI`
  - `zeitgeist.api.app.get_store(request: Request) -> Store` — the FastAPI dependency every router uses
  - `zeitgeist.api.app.get_settings(request: Request) -> Settings`
  - `zeitgeist.serve.main(argv: list[str] | None = None) -> int`

**Why the factory takes `Settings`:** tests need a `Store` on `tmp_path`, and the app must not reach for the ambient database. Passing `Settings` in is what makes the app testable without monkeypatching module state.

**Why one `Store` per app rather than per request:** `sqlite3` connections are thread-bound (`check_same_thread=True`), and phase 3 adds a worker thread that constructs its own. Holding one connection for the app's lifetime is correct for reads and is what phase 3 expects to find.

- [ ] **Step 1: Add the dependencies**

Run: `uv add fastapi uvicorn`

Expected: `pyproject.toml` gains both under `dependencies`, and `uv.lock` updates. Commit the lockfile with the code — CI runs `uv sync --locked` and a stale lockfile fails fast.

- [ ] **Step 2: Restore the console entry point**

In `pyproject.toml`, add back the block phase 1 removed, now pointing at the server:

```toml
[project.scripts]
zeitgeist = "zeitgeist.serve:main"
```

- [ ] **Step 3: Write the failing tests**

Create `tests/test_api_app.py`:

```python
from fastapi.testclient import TestClient

from zeitgeist.api import create_app
from zeitgeist.config import Settings


def _settings(tmp_path) -> Settings:
    return Settings(
        _env_file=None,
        db_path=tmp_path / "data" / "z.db",
        output_dir=tmp_path / "output",
    )


def test_the_app_serves_its_openapi_schema(tmp_path):
    """The schema is the contract phase 5 generates its client from, so it
    has to be reachable before any endpoint exists."""
    client = TestClient(create_app(_settings(tmp_path)))

    response = client.get("/openapi.json")

    assert response.status_code == 200
    assert response.json()["info"]["title"] == "Zeitgeist"


def test_the_app_opens_the_database_it_was_given(tmp_path):
    """Not the ambient one. A factory that reached for `data/zeitgeist.db`
    would make every test depend on whether the tool had been run locally."""
    settings = _settings(tmp_path)

    create_app(settings)

    assert (tmp_path / "data" / "z.db").is_file()


def test_the_app_creates_its_schema_on_startup(tmp_path):
    """A fresh install serves an empty database rather than 500ing on the
    first query."""
    import sqlite3

    create_app(_settings(tmp_path))

    conn = sqlite3.connect(tmp_path / "data" / "z.db")
    try:
        [(version,)] = conn.execute("PRAGMA user_version").fetchall()
    finally:
        conn.close()
    assert version == 3
```

- [ ] **Step 4: Run to verify they fail**

Run: `uv run pytest tests/test_api_app.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'zeitgeist.api'`.

- [ ] **Step 5: Write the app factory**

Create `zeitgeist/api/app.py`:

```python
"""The FastAPI app and the two dependencies every router uses.

The factory takes `Settings` rather than building its own so a test can
point it at `tmp_path`. A factory that reached for the ambient database
would make the suite's result depend on whether the tool had been run
locally, which is the hermeticity problem `conftest` already guards against
for `Settings` itself.

One `Store` for the app's lifetime rather than one per request: `sqlite3`
connections are thread-bound, reads need no isolation from each other, and
phase 3's worker thread constructs its own connection anyway.
"""

from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI, Request

from zeitgeist.config import Settings
from zeitgeist.store import Store


def get_store(request: Request) -> Store:
    """The app's store. Declared as a dependency rather than reached for
    directly so a router never touches `app.state`.
    """
    return request.app.state.store


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def create_app(settings: Settings) -> FastAPI:
    # Opened here rather than inside the lifespan: `TestClient` runs the
    # lifespan only when used as a context manager, and two of this task's
    # tests call `create_app` without a client at all. The lifespan's only
    # job is to close it.
    store = Store(settings.db_path)
    store.init_schema()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            store.close()

    app = FastAPI(title="Zeitgeist", lifespan=lifespan)
    app.state.store = store
    app.state.settings = settings
    return app
```


- [ ] **Step 6: Write the package export**

Create `zeitgeist/api/__init__.py`:

```python
"""HTTP read API over what the pipeline persisted."""

from zeitgeist.api.app import create_app

__all__ = ["create_app"]
```

- [ ] **Step 7: Write the entry point**

Create `zeitgeist/serve.py`:

```python
"""The console entry point: `uv run zeitgeist`.

No subcommands. The web UI is the interface, so the one thing this command
does is start the server. `--reload` is off by default deliberately:
uvicorn's reloader kills the worker thread phase 3 adds if a file is saved
while a pipeline is in flight, and losing a run to an editor autosave is a
worse default than restarting by hand.
"""

import argparse
import sys

import uvicorn

from zeitgeist.api import create_app
from zeitgeist.config import Settings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="zeitgeist")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Restart on file changes. Off by default: the reloader kills an "
        "in-flight run.",
    )
    args = parser.parse_args(argv)

    uvicorn.run(
        create_app(Settings()),
        host=args.host,
        port=args.port,
        reload=args.reload,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 8: Run the tests**

Run: `uv run pytest tests/test_api_app.py -v`

Expected: PASS, 3 tests.

- [ ] **Step 9: Run the full gate**

Run: `uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest`

Expected: all four pass. Also run `uv sync --locked` and confirm it succeeds — the lockfile must match the new dependencies.

- [ ] **Step 10: Commit**

```bash
git add -A
git commit -m "Serve a FastAPI app, and restore the console entry point

The factory takes Settings rather than building its own, so a test can
point it at tmp_path; a factory reaching for the ambient database would
make the suite depend on whether the tool had been run locally.

One Store for the app's lifetime rather than one per request: sqlite3
connections are thread-bound, reads need no isolation from each other, and
phase 3's worker thread opens its own.

zeitgeist takes no subcommands - the one thing it does is start the server.
--reload is off by default because uvicorn's reloader kills the worker
thread phase 3 adds, and losing a run to an editor autosave is a worse
default than restarting by hand.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: The test client factory

**Files:**
- Create: `tests/api_factory.py`

**Interfaces:**
- Consumes: `create_app` from Task 1; `Store`; the builders in `tests/run_factory.py`.
- Produces:
  - `api_settings(tmp_path) -> Settings`
  - `seeded_client(tmp_path, *, runs: Sequence[SeededRun] = ()) -> TestClient`
  - `SeededRun` — a dataclass describing one run to seed: `run_id`, `status`, `topics`, `stages`, `renders`, `evidence`
  - `seed_run(store, spec: SeededRun) -> None`

There is no failing test to write first — this is test infrastructure, and Task 3 is its first consumer, exactly as `tests/run_factory.py` was in phase 1.

**Why seed through `Store` rather than raw SQL:** a seeder that writes rows by hand would keep passing after the store's own writers changed shape, and the endpoints would then be serving a table layout nothing produces. Seeding through `write_analyse_checkpoint`, `record_stage` and `add_render` means these tests break when the writers do.

- [ ] **Step 1: Write the file**

Create `tests/api_factory.py`:

```python
"""A TestClient over a Store seeded with real runs.

Seeded through the store's own writers rather than raw SQL: a hand-written
INSERT would keep passing after `write_analyse_checkpoint` changed shape,
and the endpoints would be serving a table layout nothing produces.

`api_settings` points `output_dir` and `db_path` inside `tmp_path`, so a
test's renders and database are its own.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from fastapi.testclient import TestClient

from zeitgeist.api import create_app
from zeitgeist.config import Settings
from zeitgeist.models import Topic, TrendEvidence
from zeitgeist.records import RenderRecord, RunConfig, Stage, StageRecord
from zeitgeist.store import Store

from tests.run_factory import make_run_config, make_topic


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
    return Settings(
        _env_file=None,
        db_path=tmp_path / "data" / "z.db",
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


def seeded_client(
    tmp_path: Path, *, runs: Sequence[SeededRun] = ()
) -> TestClient:
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
```

- [ ] **Step 2: Verify it builds a working client**

Run:

```bash
uv run python -c "import sys, tempfile, pathlib; sys.path.insert(0,'.'); from tests.api_factory import seeded_client, SeededRun; d=pathlib.Path(tempfile.mkdtemp()); c=seeded_client(d, runs=[SeededRun()]); print(c.get('/openapi.json').status_code)"
```

Expected: `200`

- [ ] **Step 3: Run the full gate**

Run: `uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest`

Expected: all four pass.

- [ ] **Step 4: Commit**

```bash
git add tests/api_factory.py
git commit -m "Add a seeded TestClient factory for the API tests

Seeds through the store's own writers rather than raw SQL: a hand-written
INSERT would keep passing after write_analyse_checkpoint changed shape, and
the endpoints would then be serving a table layout nothing produces.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: `GET /api/settings`

**Files:**
- Create: `zeitgeist/api/settings.py`, `tests/test_api_settings.py`
- Modify: `zeitgeist/api/app.py` (mount the router)

**Interfaces:**
- Consumes: `get_store`, `get_settings` from Task 1; `seeded_client`, `api_settings` from Task 2; `WRITABLE_KEYS` and `_dotenv_value` from `zeitgeist.settings_source`.
- Produces:
  - `zeitgeist.api.settings.router` — a `fastapi.APIRouter`
  - `zeitgeist.api.schemas.SettingField` — `key: str`, `value: float | int`, `source: SettingSource`
  - `zeitgeist.api.schemas.SettingSource = Literal["settings", "environment", "dotenv", "default"]`

**The design gap you are resolving:** the settings screen draws three chips — `SET HERE`, `FROM .env`, `DEFAULT` — but there are four layers, because a shell variable outranks all of them. The API tells the truth and returns four possible sources; the screen that consumes this in phase 6 will need a fourth chip or a decision to fold `environment` into one of the three. Note it in the endpoint's docstring so phase 6 finds it.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_api_settings.py`:

```python
from zeitgeist.settings_source import WRITABLE_KEYS
from zeitgeist.store import Store

from tests.api_factory import api_settings, seeded_client


def test_every_tunable_field_is_reported(tmp_path):
    """The settings screen renders one row per field, so a field missing
    from the response is a row the screen cannot draw."""
    client = seeded_client(tmp_path)

    body = client.get("/api/settings").json()

    assert {field["key"] for field in body} == set(WRITABLE_KEYS)


def test_a_stored_override_reports_itself_as_set_here(tmp_path):
    settings = api_settings(tmp_path)
    store = Store(settings.db_path)
    store.init_schema()
    store.set_setting("bluesky_trend_limit", "11")
    store.close()
    client = seeded_client(tmp_path)

    body = {field["key"]: field for field in client.get("/api/settings").json()}

    assert body["bluesky_trend_limit"]["value"] == 11
    assert body["bluesky_trend_limit"]["source"] == "settings"


def test_an_untouched_field_reports_the_default(tmp_path):
    client = seeded_client(tmp_path)

    body = {field["key"]: field for field in client.get("/api/settings").json()}

    assert body["phrase_min_authors"]["value"] == 3
    assert body["phrase_min_authors"]["source"] == "default"


def test_a_shell_variable_is_reported_as_environment(tmp_path, monkeypatch):
    """A shell variable outranks the settings table, so a screen showing
    'SET HERE' for a value the environment is actually supplying would be
    lying about which layer won."""
    monkeypatch.setenv("PHRASE_MIN_AUTHORS", "7")
    client = seeded_client(tmp_path)

    body = {field["key"]: field for field in client.get("/api/settings").json()}

    assert body["phrase_min_authors"]["value"] == 7
    assert body["phrase_min_authors"]["source"] == "environment"


def test_the_api_key_is_never_in_the_response(tmp_path, monkeypatch):
    """It is not a tunable field, and a settings endpoint that leaked one
    would be a different and worse thing than a tuning screen."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-secret")
    client = seeded_client(tmp_path)

    raw = client.get("/api/settings").text

    assert "sk-ant-secret" not in raw
    assert "anthropic_api_key" not in raw
```

Note: `seeded_client` builds its own `Settings`, which reads the environment — so `monkeypatch.setenv` before constructing the client is what puts a value in the environment layer. `tests/conftest.py` strips these variables for every test, so the setenv is the only source.

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_api_settings.py -v`

Expected: FAIL with 404s — the router does not exist.

- [ ] **Step 3: Write the response models**

Create `zeitgeist/api/schemas.py`:

```python
"""Response models for endpoints whose shape is a composition.

Storage models are returned directly wherever they suffice — `TopicRow`,
`StageRecord` and `RenderRecord` are already the shape the UI reads. These
exist only where an endpoint joins several sources into one body.
"""

from typing import Literal

from pydantic import BaseModel

from zeitgeist.models import STRICT

# Four layers, though the settings screen draws three chips. A shell
# variable outranks the settings table, so `environment` is a real answer
# and the screen consuming this needs a fourth chip or a deliberate
# decision to fold it into one of the three.
SettingSource = Literal["settings", "environment", "dotenv", "default"]


class SettingField(BaseModel):
    """One tunable field, its effective value, and which layer supplied it."""

    model_config = STRICT

    key: str
    value: float | int
    source: SettingSource
```

- [ ] **Step 4: Write the router**

Create `zeitgeist/api/settings.py`:

```python
"""The settings read.

Reports which layer supplied each value, because a settings screen that
hides which layer won is worse than no settings screen. Only the seven
tunable fields appear: a UI that could rewrite where the database lives, or
read an API key back out, is a different and worse thing than a tuning
screen.
"""

import os

from fastapi import APIRouter, Depends

from zeitgeist.api.app import get_settings, get_store
from zeitgeist.api.schemas import SettingField, SettingSource
from zeitgeist.config import Settings
from zeitgeist.settings_source import WRITABLE_KEYS, _dotenv_value
from zeitgeist.store import Store

router = APIRouter(prefix="/api/settings", tags=["settings"])


def _source(key: str, stored: dict[str, str]) -> SettingSource:
    """Which layer supplied this field, in `Settings`' own precedence.

    Environment first, then the settings table, then `.env`, then the field
    default — the order `settings_customise_sources` establishes.
    """
    if key.upper() in os.environ:
        return "environment"
    if key in stored:
        return "settings"
    if _dotenv_value(key.upper()) is not None:
        return "dotenv"
    return "default"


@router.get("", response_model=list[SettingField])
def read_settings(
    store: Store = Depends(get_store),
    settings: Settings = Depends(get_settings),
) -> list[SettingField]:
    stored = store.get_settings()
    return [
        SettingField(
            key=key,
            value=getattr(settings, key),
            source=_source(key, stored),
        )
        for key in sorted(WRITABLE_KEYS)
    ]
```

`_dotenv_value` is underscore-prefixed but is the module's own helper for exactly this question; importing it here is deliberate rather than reaching into a private. If ruff or a reviewer objects, rename it to `dotenv_value` in `settings_source.py` and update its two call sites — do not duplicate the parser.

- [ ] **Step 5: Mount the router**

In `zeitgeist/api/app.py`'s `create_app`, after constructing `app`:

```python
    from zeitgeist.api import settings as settings_router

    app.include_router(settings_router.router)
```

Import inside the function to avoid a cycle: `settings.py` imports `get_store` from `app.py`.

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/test_api_settings.py -v`

Expected: PASS, 5 tests.

- [ ] **Step 7: Run the full gate**

Run: `uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest`

Expected: all four pass.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "Serve the tunable settings and which layer supplied each

A settings screen that hides which layer won is worse than no settings
screen, so every field reports its source. Four are possible - environment,
the settings table, .env, default - though the design draws three chips; a
shell variable outranks the table, so `environment` is a real answer the
screen will need to account for.

Only the seven tunable fields appear, and the response is asserted not to
contain the API key in any form.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: `Store.list_runs` and `GET /api/runs`

**Files:**
- Modify: `zeitgeist/store.py`
- Create: `zeitgeist/api/runs.py`, `tests/test_api_runs.py`
- Modify: `zeitgeist/api/app.py` (mount), `tests/test_store.py`

**Interfaces:**
- Consumes: everything from Tasks 1–3.
- Produces:
  - `Store.list_runs(limit: int, cursor: str | None = None) -> list[RunRecordRow]` — newest first
  - `Store.render_counts(run_id: str) -> dict[str, int]` — topic id to render count
  - `zeitgeist.api.schemas.RunSummary` — `run: RunRecordRow`, `topic_labels: list[str]`, `render_ids: list[str]`
  - `zeitgeist.api.schemas.RunPage` — `runs: list[RunSummary]`, `next_cursor: str | None`
  - `zeitgeist.api.runs.router`

**The cursor:** the `started_at` of the last row on the page, as an ISO string. Ordering is `started_at DESC`. `started_at` comes from `datetime.now(UTC).isoformat()` at microsecond precision and the queue runs one run at a time, so a tie is not reachable in practice; a tie would skip a row rather than loop, which is the safe direction to fail.

- [ ] **Step 1: Write the failing store tests**

Add to `tests/test_store.py`:

```python
def test_runs_come_back_newest_first(tmp_path):
    """The Runs list is reverse-chronological and the in-flight run pins to
    the top, so ordering is the endpoint's whole job."""
    store = _store(tmp_path)
    for run_id in ("20260901T100000Z", "20260901T120000Z", "20260901T110000Z"):
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
```

`make_render_record`'s default `run_id` is `"20260901T120000Z"`, which is why the third test asserts against that id.

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_store.py -k "newest_first or cursor or render_counts" -v`

Expected: FAIL with `AttributeError: 'Store' object has no attribute 'list_runs'`.

- [ ] **Step 3: Add the store accessors**

In `zeitgeist/store.py`, beside `get_run`:

```python
    def list_runs(
        self, limit: int, cursor: str | None = None
    ) -> list[RunRecordRow]:
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
            "SELECT topic_id, COUNT(*) FROM renders WHERE run_id = ? "
            "GROUP BY topic_id",
            (run_id,),
        ).fetchall()
        return {topic_id: count for topic_id, count in rows}
```

`get_run` currently builds its `RunRecordRow` inline. Extract that construction into a module-level `_run_record(row: tuple) -> RunRecordRow` beside `_render`, and have both `get_run` and `list_runs` call it — the column list and the parsing are identical, and two copies would drift.

- [ ] **Step 4: Write the failing API tests**

Create `tests/test_api_runs.py`:

```python
from tests.api_factory import SeededRun, seeded_client
from tests.run_factory import make_render_record, make_run_config, make_topic


def test_the_runs_list_is_newest_first(tmp_path):
    client = seeded_client(
        tmp_path,
        runs=[
            SeededRun(run_id="20260901T100000Z"),
            SeededRun(run_id="20260901T120000Z"),
        ],
    )

    body = client.get("/api/runs").json()

    assert [entry["run"]["run_id"] for entry in body["runs"]] == [
        "20260901T120000Z",
        "20260901T100000Z",
    ]


def test_a_run_carries_the_counts_the_list_shows(tmp_path):
    """`25 trends -> 5 kept` is drawn straight from these."""
    client = seeded_client(
        tmp_path,
        runs=[
            SeededRun(
                config=make_run_config(top_count=1),
                topics=[make_topic("cats"), make_topic("dogs")],
            )
        ],
    )

    [entry] = client.get("/api/runs").json()["runs"]

    assert entry["run"]["trends_found"] == 2
    assert entry["run"]["topics_kept"] == 1


def test_a_run_carries_its_topic_labels_in_rank_order(tmp_path):
    """Column two of the row is the titles joined by a middot, ellipsised.
    Rank order is what makes the truncation show the topics that mattered."""
    client = seeded_client(
        tmp_path,
        runs=[
            SeededRun(
                topics=[
                    make_topic("quiet", trend_score=0.1),
                    make_topic("loud", trend_score=0.9),
                ]
            )
        ],
    )

    [entry] = client.get("/api/runs").json()["runs"]

    assert entry["topic_labels"] == ["Loud", "Quiet"]


def test_a_run_carries_its_render_ids_for_thumbnails(tmp_path):
    client = seeded_client(
        tmp_path,
        runs=[
            SeededRun(
                renders=[
                    make_render_record("r1", topic_id="cats"),
                    make_render_record("r2", topic_id="cats"),
                ]
            )
        ],
    )

    [entry] = client.get("/api/runs").json()["runs"]

    assert entry["render_ids"] == ["r1", "r2"]


def test_the_page_reports_a_cursor_when_more_runs_remain(tmp_path):
    client = seeded_client(
        tmp_path,
        runs=[
            SeededRun(run_id="20260901T100000Z"),
            SeededRun(run_id="20260901T110000Z"),
            SeededRun(run_id="20260901T120000Z"),
        ],
    )

    first = client.get("/api/runs", params={"limit": 2}).json()
    second = client.get(
        "/api/runs", params={"limit": 2, "cursor": first["next_cursor"]}
    ).json()

    assert len(first["runs"]) == 2
    assert first["next_cursor"] is not None
    assert [entry["run"]["run_id"] for entry in second["runs"]] == [
        "20260901T100000Z"
    ]
    assert second["next_cursor"] is None


def test_an_empty_database_returns_an_empty_page(tmp_path):
    """The first screen anyone sees. A 500 here is the worst possible
    first impression."""
    client = seeded_client(tmp_path)

    body = client.get("/api/runs").json()

    assert body == {"runs": [], "next_cursor": None}
```

`make_topic("loud")` produces the label `"Loud"` — `make_topic` derives its label from the id by replacing hyphens and title-casing, which is why the expected labels are capitalised.

- [ ] **Step 5: Run to verify they fail**

Run: `uv run pytest tests/test_api_runs.py -v`

Expected: FAIL with 404s.

- [ ] **Step 6: Add the response models**

In `zeitgeist/api/schemas.py`:

```python
class RunSummary(BaseModel):
    """One row of the Runs list.

    `topic_labels` and `render_ids` are joins the row needs and the run
    record does not carry: column two is the titles, column four the
    thumbnails.
    """

    model_config = STRICT

    run: RunRecordRow
    topic_labels: list[str]
    render_ids: list[str]


class RunPage(BaseModel):
    """One page of runs. `next_cursor` is None on the last page."""

    model_config = STRICT

    runs: list[RunSummary]
    next_cursor: str | None
```

Add `from zeitgeist.records import RunRecordRow` to the imports.

- [ ] **Step 7: Write the router**

Create `zeitgeist/api/runs.py`:

```python
"""Everything scoped to one run: the list, the detail, the ranking, one
topic's dossier, and the log.
"""

from fastapi import APIRouter, Depends, Query

from zeitgeist.api.app import get_store
from zeitgeist.api.schemas import RunPage, RunSummary
from zeitgeist.store import Store

router = APIRouter(prefix="/api/runs", tags=["runs"])

# The Runs list draws three rows in the sidebar strip and pages beyond that.
DEFAULT_PAGE = 25


@router.get("", response_model=RunPage)
def list_runs(
    limit: int = Query(default=DEFAULT_PAGE, ge=1, le=100),
    cursor: str | None = None,
    store: Store = Depends(get_store),
) -> RunPage:
    rows = store.list_runs(limit=limit, cursor=cursor)
    summaries = [
        RunSummary(
            run=row,
            topic_labels=[t.label for t in store.run_topics(row.run_id)],
            render_ids=[r.id for r in store.renders_for_run(row.run_id)],
        )
        for row in rows
    ]
    # A short page is the last page. Reporting a cursor here would hand the
    # client one more request that always comes back empty.
    next_cursor = (
        rows[-1].started_at.isoformat() if len(rows) == limit else None
    )
    return RunPage(runs=summaries, next_cursor=next_cursor)
```

`store.run_topics` returns rows ordered by `final_rank`, which is why `topic_labels` needs no sorting.

- [ ] **Step 8: Mount the router**

In `create_app`, alongside the settings router:

```python
    from zeitgeist.api import runs as runs_router

    app.include_router(runs_router.router)
```

- [ ] **Step 9: Run the tests**

Run: `uv run pytest tests/test_api_runs.py tests/test_store.py -v`

Expected: PASS.

- [ ] **Step 10: Run the full gate**

Run: `uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest`

Expected: all four pass.

- [ ] **Step 11: Commit**

```bash
git add -A
git commit -m "Serve the runs list

Keyset pagination on started_at rather than OFFSET: a run started between
two requests would shift an offset page and duplicate a row across the seam.
A short page reports no cursor, so the client never makes a request that
comes back empty by construction.

Topic labels come back in rank order, which is what makes the row's
ellipsised title list show the topics that mattered. Render counts are a
COUNT at query time rather than a column, so nothing has to keep a
denormalised number correct across phase 4's separate executor.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 5: `GET /api/runs/{id}` — detail with computed resume stage

**Files:**
- Modify: `zeitgeist/api/runs.py`, `zeitgeist/api/schemas.py`, `tests/test_api_runs.py`

**Interfaces:**
- Consumes: `Store.get_run`, `Store.stages_for_run`, `Store.read_checkpoint`, `MissingCheckpoint`.
- Produces:
  - `zeitgeist.api.schemas.RunDetail` — `run: RunRecordRow`, `stages: list[StageRecord]`, `resume_stage: Stage | None`
  - `zeitgeist.api.runs.resume_stage(store: Store, run_id: str) -> Stage | None`
  - `Store.written_stages(run_id: str) -> set[Stage]` — which stages have a checkpoint, without reading the payloads

**The resume rule, stated once so it is not re-derived:** `resume_stage` is the first `Stage` in `ORDER` with no checkpoint row. If that is `INGEST` — nothing was written at all, which is what a source outage looks like — it is `None`, because the UI must not offer a resume it cannot honour; the run has to start over. If all four checkpoints exist, it is `GENERATE`: re-rendering a frozen ranking is always available and is the template-tuning loop.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_api_runs.py`:

```python
import pytest

from zeitgeist.records import Stage
from tests.run_factory import make_stage_record


def test_run_detail_carries_the_frozen_config(tmp_path):
    """The config line shows what the run used, which a since-edited .env
    cannot supply."""
    client = seeded_client(
        tmp_path,
        runs=[SeededRun(config=make_run_config(top_count=9, llm_model="qwen3.5"))],
    )

    body = client.get("/api/runs/20260901T120000Z").json()

    assert body["run"]["config"]["top_count"] == 9
    assert body["run"]["config"]["llm_model"] == "qwen3.5"


def test_run_detail_carries_its_stages_in_pipeline_order(tmp_path):
    client = seeded_client(
        tmp_path,
        runs=[
            SeededRun(
                stages=[
                    make_stage_record(Stage.GENERATE),
                    make_stage_record(Stage.INGEST),
                ]
            )
        ],
    )

    body = client.get("/api/runs/20260901T120000Z").json()

    assert [s["stage"] for s in body["stages"]] == ["ingest", "generate"]


def test_a_run_with_every_checkpoint_resumes_from_generate(tmp_path):
    """Re-rendering a frozen ranking is always available - it is the
    template-tuning loop."""
    client = seeded_client(tmp_path, runs=[SeededRun()])
    # SeededRun writes the analyse checkpoint; write the other three directly
    # so all four exist. Empty payloads are enough - resume_stage asks which
    # stages have a row, not what is in it.
    store = Store(api_settings(tmp_path).db_path)
    store.write_checkpoint(
        "20260901T120000Z",
        Stage.INGEST,
        [],
    )
    store.write_checkpoint(
        "20260901T120000Z",
        Stage.EVALUATE,
        [],
    )
    store.write_checkpoint("20260901T120000Z", Stage.GENERATE, [])
    store.close()

    body = client.get("/api/runs/20260901T120000Z").json()

    assert body["resume_stage"] == "generate"


def test_a_run_that_failed_at_evaluate_resumes_from_evaluate(tmp_path):
    client = seeded_client(tmp_path, runs=[SeededRun()])
    store = Store(api_settings(tmp_path).db_path)
    store.write_checkpoint("20260901T120000Z", Stage.INGEST, [])
    store.close()

    body = client.get("/api/runs/20260901T120000Z").json()

    assert body["resume_stage"] == "evaluate"


def test_a_run_with_no_checkpoints_cannot_be_resumed(tmp_path):
    """A source outage writes nothing, so there is nothing to resume from
    and the UI must not offer an action it cannot honour."""
    client = seeded_client(
        tmp_path, runs=[SeededRun(topics=[], status="failed")]
    )

    body = client.get("/api/runs/20260901T120000Z").json()

    assert body["resume_stage"] is None


def test_an_unknown_run_is_a_404(tmp_path):
    client = seeded_client(tmp_path)

    assert client.get("/api/runs/nope").status_code == 404
```

These tests need two more names at the top of the module, alongside the imports already there:

```python
from tests.api_factory import SeededRun, api_settings, seeded_client
from zeitgeist.store import Store
```

`SeededRun(topics=[])` writes no analyse checkpoint, which is what makes the no-checkpoints case reachable.

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_api_runs.py -k "detail or resume or unknown" -v`

Expected: FAIL with 404 on every request — the route does not exist.

- [ ] **Step 3: Add the response model**

In `zeitgeist/api/schemas.py`:

```python
class RunDetail(BaseModel):
    """One run's header: what it was configured with, how its stages went,
    and where a resume would start.
    """

    model_config = STRICT

    run: RunRecordRow
    stages: list[StageRecord]
    # None when nothing was written at all, which is what a source outage
    # looks like. The UI must not offer a resume it cannot honour.
    resume_stage: Stage | None
```

Add `from zeitgeist.records import RunRecordRow, Stage, StageRecord` to the imports.

- [ ] **Step 4: Add the endpoint**

In `zeitgeist/api/runs.py`:

```python
def resume_stage(store: Store, run_id: str) -> Stage | None:
    """The first stage with no checkpoint, or None if that is ingest.

    Nothing written at all means the run has to start over rather than
    resume, which is what a source outage looks like. Every checkpoint
    present means generate: re-rendering a frozen ranking is always
    available, and is the template-tuning loop.
    """
    written = store.written_stages(run_id)
    for stage in ORDER:
        if stage not in written:
            return None if stage is Stage.INGEST else stage
    return Stage.GENERATE


@router.get("/{run_id}", response_model=RunDetail)
def read_run(run_id: str, store: Store = Depends(get_store)) -> RunDetail:
    run = store.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"No such run: {run_id}")
    return RunDetail(
        run=run,
        stages=store.stages_for_run(run_id),
        resume_stage=resume_stage(store, run_id),
    )
```

Add `HTTPException` to the fastapi imports, and `from zeitgeist.records import ORDER, Stage`.

- [ ] **Step 5: Add the store accessor `resume_stage` needs**

`resume_stage` asks which stages have checkpoints. Reading each payload back to find out would deserialise megabytes to answer a question about row existence, so add to `zeitgeist/store.py`:

```python
    def written_stages(self, run_id: str) -> set[Stage]:
        """Which stages have a checkpoint, without reading the payloads.

        `read_checkpoint` would deserialise a run's whole evidence to answer
        a question about row existence.
        """
        rows = self._conn.execute(
            "SELECT stage FROM checkpoints WHERE run_id = ?", (run_id,)
        ).fetchall()
        return {Stage(stage) for (stage,) in rows}
```

Add a store test:

```python
def test_written_stages_reports_only_what_was_checkpointed(tmp_path):
    store = _store(tmp_path)
    store.write_checkpoint("r1", Stage.INGEST, [make_topic()])
    store.write_checkpoint("r1", Stage.EVALUATE, [])

    assert store.written_stages("r1") == {Stage.INGEST, Stage.EVALUATE}
```

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/test_api_runs.py tests/test_store.py -v`

Expected: PASS.

- [ ] **Step 7: Run the full gate**

Run: `uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest`

Expected: all four pass.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "Serve one run's detail, with a computed resume stage

resume_stage is the first stage with no checkpoint. None when that is
ingest, because nothing was written and the run has to start over rather
than resume - which is what a source outage looks like, and the UI must not
offer an action it cannot honour. Generate when all four exist, since
re-rendering a frozen ranking is always available.

written_stages answers the row-existence question without read_checkpoint
deserialising a run's whole evidence to do it.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 6: `GET /api/runs/{id}/topics` — the ranking

**Files:**
- Modify: `zeitgeist/api/runs.py`, `zeitgeist/api/schemas.py`, `tests/test_api_runs.py`

**Interfaces:**
- Consumes: `Store.run_topics`, `Store.render_counts` from Task 4, `Store.get_run`.
- Produces: `zeitgeist.api.schemas.RankedTopic` — `topic: TopicRow`, `render_count: int`, `above_cut: bool`

**Why `above_cut` is computed here:** the cut is `RunConfig.top_count`, frozen on the run. The screen draws rows above it solid and rows below it dashed at 62% opacity with a `generate ↗` link, so the boolean is load-bearing and the client should not have to know the rule.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_api_runs.py`:

```python
def test_the_ranking_includes_topics_below_the_cut(tmp_path):
    """The screen draws them dimmed with a generate link - they were never
    briefed, and that row is the escape hatch to brief them by hand."""
    client = seeded_client(
        tmp_path,
        runs=[
            SeededRun(
                config=make_run_config(top_count=1),
                topics=[
                    make_topic("loud", trend_score=0.9),
                    make_topic("quiet", trend_score=0.1),
                ],
            )
        ],
    )

    body = client.get("/api/runs/20260901T120000Z/topics").json()

    assert [entry["topic"]["topic_id"] for entry in body] == ["loud", "quiet"]
    assert [entry["above_cut"] for entry in body] == [True, False]


def test_the_ranking_is_ordered_by_the_stored_rank(tmp_path):
    """final_rank was written with sentiment.rank_score. The endpoint sorts
    by nothing of its own - a second implementation of the blend would
    drift from the evaluate checkpoint silently."""
    client = seeded_client(
        tmp_path,
        runs=[
            SeededRun(
                topics=[
                    make_topic("third", trend_score=0.1),
                    make_topic("first", trend_score=0.9),
                    make_topic("second", trend_score=0.5),
                ]
            )
        ],
    )

    body = client.get("/api/runs/20260901T120000Z/topics").json()

    assert [entry["topic"]["final_rank"] for entry in body] == [1, 2, 3]
    assert [entry["topic"]["topic_id"] for entry in body] == [
        "first",
        "second",
        "third",
    ]


def test_each_topic_carries_its_render_count(tmp_path):
    """`no memes yet` on a card is the cue to go and generate some, so a
    zero has to be a real zero rather than a missing key."""
    client = seeded_client(
        tmp_path,
        runs=[
            SeededRun(
                topics=[make_topic("cats"), make_topic("dogs")],
                renders=[
                    make_render_record("a", topic_id="cats"),
                    make_render_record("b", topic_id="cats"),
                ],
            )
        ],
    )

    body = {
        entry["topic"]["topic_id"]: entry["render_count"]
        for entry in client.get("/api/runs/20260901T120000Z/topics").json()
    }

    assert body == {"cats": 2, "dogs": 0}


def test_the_ranking_of_an_unknown_run_is_a_404(tmp_path):
    client = seeded_client(tmp_path)

    assert client.get("/api/runs/nope/topics").status_code == 404
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_api_runs.py -k "ranking or render_count" -v`

Expected: FAIL with 404s.

- [ ] **Step 3: Add the response model**

In `zeitgeist/api/schemas.py`:

```python
class RankedTopic(BaseModel):
    """One row of the ranking list.

    `above_cut` is computed from the run's frozen `top_count` rather than
    left to the client: the screen draws rows below the cut dashed and
    dimmed with a generate link, so the rule is load-bearing.
    """

    model_config = STRICT

    topic: TopicRow
    render_count: int
    above_cut: bool
```

Add `from zeitgeist.projection import TopicRow` to the imports.

- [ ] **Step 4: Add the endpoint**

In `zeitgeist/api/runs.py`:

```python
@router.get("/{run_id}/topics", response_model=list[RankedTopic])
def read_ranking(
    run_id: str, store: Store = Depends(get_store)
) -> list[RankedTopic]:
    run = store.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"No such run: {run_id}")
    counts = store.render_counts(run_id)
    return [
        RankedTopic(
            topic=row,
            render_count=counts.get(row.topic_id, 0),
            above_cut=row.final_rank <= run.config.top_count,
        )
        # Already ordered by final_rank. The endpoint sorts by nothing of
        # its own: rank_score is the single place the blend is defined.
        for row in store.run_topics(run_id)
    ]
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_api_runs.py -v`

Expected: PASS.

- [ ] **Step 6: Run the full gate**

Run: `uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest`

Expected: all four pass.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "Serve the full ranking, including below the cut

Every topic, not just the kept ones: the screen draws below-the-cut rows
dimmed with a generate link, and that row is the escape hatch to brief a
topic the pipeline passed over.

above_cut is computed from the run's frozen top_count rather than left to
the client. Ordering comes from the stored final_rank - the endpoint sorts
by nothing of its own, because rank_score is the single place the blend of
trend and meme potential is defined.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 7: `GET /api/runs/{id}/topics/{topic_id}` — the dossier

**Files:**
- Modify: `zeitgeist/api/runs.py`, `zeitgeist/api/schemas.py`, `tests/test_api_runs.py`
- Modify: `zeitgeist/store.py`

**Interfaces:**
- Consumes: `Store.read_checkpoint`, `MissingCheckpoint`, `Store.renders_for_run`.
- Produces:
  - `Store.topic_recurrence(label_slug: str) -> tuple[int, str | None]` — the count and the earliest run id. A tuple rather than the response model, so `store.py` never imports from `zeitgeist.api`.
  - `zeitgeist.api.schemas.TopicRecurrence` — `run_count: int`, `first_seen_run_id: str | None`, built by the router from that tuple
  - `zeitgeist.api.schemas.TopicDetail` — `topic: TopicRow`, `dossier: Dossier | None`, `replies: list[Reply]`, `renders: list[RenderRecord]`, `recurrence: TopicRecurrence`

**Where each piece comes from:** `topic` and `recurrence` from tables; `dossier` from the **analyse** checkpoint, finding the one `Topic` whose `id` matches; `replies` from the **ingest** checkpoint, taking the replies of every post whose `item.source_id` is in that topic's `item_ids`. That is the one place this phase reads a checkpoint payload for prose, and it is why the design keeps evidence out of the projection.

**Replies are capped and ordered.** The design does not say how many, so: most-liked first, at most 20. A topic can carry hundreds and the card list is not paginated. State the cap as a module constant so phase 5 can find it.

**No author, handle or avatar.** `Reply` carries `author_key`, which exists only to count distinct accounts behind a phrase. **It must not be serialised** — the project stores no personal data and an API that returned it would undo that. The response model carries `text`, `like_count` and `created_at` only.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_api_runs.py`:

```python
from datetime import UTC, datetime

from zeitgeist.models import (
    BlueskyMetrics,
    Item,
    PostEvidence,
    Reply,
    Sentiment,
    TrendEvidence,
    TrendInfo,
)
from tests.run_factory import make_dossier


def _evidence_for(source_ids: list[str], replies: list[Reply]) -> TrendEvidence:
    now = datetime(2026, 9, 1, tzinfo=UTC)
    return TrendEvidence(
        trend=TrendInfo(
            topic_id="t",
            display_name="Cats",
            started_at=now,
            status="trending",
        ),
        posts=[
            PostEvidence(
                item=Item(
                    source_id=source_id,
                    title="a post",
                    permalink=f"https://bsky.app/{source_id}",
                    fetched_at=now,
                    metrics=BlueskyMetrics(
                        like_count=1,
                        reply_count=1,
                        repost_count=0,
                        trend="Cats",
                        status="trending",
                        created_at=now,
                    ),
                ),
                replies=replies,
            )
            for source_id in source_ids
        ],
    )


def _reply(text: str, likes: int) -> Reply:
    return Reply(
        text=text,
        like_count=likes,
        created_at=datetime(2026, 9, 1, tzinfo=UTC),
        author_key="a",
    )


def test_topic_detail_carries_the_dossier(tmp_path):
    client = seeded_client(
        tmp_path,
        runs=[
            SeededRun(
                topics=[
                    make_topic(
                        "cats",
                        dossier=make_dossier(event_sentiment=Sentiment.CUTE),
                    )
                ]
            )
        ],
    )

    body = client.get("/api/runs/20260901T120000Z/topics/cats").json()

    assert body["dossier"]["event_sentiment"] == "cute"
    assert body["dossier"]["what_happened"]


def test_topic_detail_carries_the_replies_most_liked_first(tmp_path):
    client = seeded_client(
        tmp_path,
        runs=[
            SeededRun(
                topics=[make_topic("cats", item_ids=["p1"])],
                evidence=[
                    _evidence_for(
                        ["p1"], [_reply("quiet", 1), _reply("loud", 99)]
                    )
                ],
            )
        ],
    )

    body = client.get("/api/runs/20260901T120000Z/topics/cats").json()

    assert [r["text"] for r in body["replies"]] == ["loud", "quiet"]


def test_replies_come_only_from_this_topics_own_posts(tmp_path):
    """item_ids is what ties a topic to its evidence. Returning every reply
    in the run would put another topic's conversation on this dossier."""
    client = seeded_client(
        tmp_path,
        runs=[
            SeededRun(
                topics=[make_topic("cats", item_ids=["p1"])],
                evidence=[
                    _evidence_for(["p1"], [_reply("mine", 1)]),
                    _evidence_for(["p2"], [_reply("theirs", 1)]),
                ],
            )
        ],
    )

    body = client.get("/api/runs/20260901T120000Z/topics/cats").json()

    assert [r["text"] for r in body["replies"]] == ["mine"]


def test_a_reply_never_carries_an_author_key(tmp_path):
    """author_key exists to count distinct accounts behind a phrase. The
    project stores no personal data and an API returning it would undo
    that."""
    client = seeded_client(
        tmp_path,
        runs=[
            SeededRun(
                topics=[make_topic("cats", item_ids=["p1"])],
                evidence=[_evidence_for(["p1"], [_reply("hello", 1)])],
            )
        ],
    )

    raw = client.get("/api/runs/20260901T120000Z/topics/cats").text

    assert "author_key" not in raw


def test_topic_detail_reports_how_many_runs_the_topic_appeared_in(tmp_path):
    """`SEEN IN 3 RUNS` on the card. Keyed on the label slug, which is the
    only cross-run identity the store has."""
    client = seeded_client(
        tmp_path,
        runs=[
            SeededRun(run_id="20260901T100000Z", topics=[make_topic("cats")]),
            SeededRun(run_id="20260901T120000Z", topics=[make_topic("cats")]),
        ],
    )

    body = client.get("/api/runs/20260901T120000Z/topics/cats").json()

    assert body["recurrence"]["run_count"] == 2
    assert body["recurrence"]["first_seen_run_id"] == "20260901T100000Z"


def test_topic_detail_survives_a_run_whose_evidence_was_pruned(tmp_path):
    """The ingest checkpoint is the biggest thing in the database and a
    later phase may prune it. A dossier without replies is still a dossier;
    a 500 is not."""
    client = seeded_client(
        tmp_path, runs=[SeededRun(topics=[make_topic("cats")], evidence=[])]
    )

    body = client.get("/api/runs/20260901T120000Z/topics/cats").json()

    assert body["replies"] == []
    assert body["dossier"] is not None


def test_an_unknown_topic_is_a_404(tmp_path):
    client = seeded_client(tmp_path, runs=[SeededRun(topics=[make_topic("cats")])])

    assert (
        client.get("/api/runs/20260901T120000Z/topics/nope").status_code == 404
    )
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_api_runs.py -k "topic_detail or replies or recurrence or unknown_topic" -v`

Expected: FAIL with 404s.

- [ ] **Step 3: Add the store accessor**

In `zeitgeist/store.py`:

```python
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
```

The `||` concatenation is how the earliest run's id comes back from a `MIN` over its timestamp in one query — SQLite has no `argmin`. The separator is `|`, which cannot appear in an ISO timestamp or a run id.

Add a store test:

```python
def test_topic_recurrence_counts_runs_and_names_the_earliest(tmp_path):
    store = _store(tmp_path)
    for run_id in ("20260901T120000Z", "20260901T100000Z"):
        store.start_run(run_id, make_run_config())
        store.write_analyse_checkpoint(
            run_id, [make_topic("cats")], meme_potential_weight=0.3
        )

    assert store.topic_recurrence("cats") == (2, "20260901T100000Z")


def test_topic_recurrence_of_an_unseen_slug_is_zero(tmp_path):
    assert _store(tmp_path).topic_recurrence("nope") == (0, None)
```

- [ ] **Step 4: Add the response models**

In `zeitgeist/api/schemas.py`:

```python
class ReplyOut(BaseModel):
    """One reply, as the dossier shows it.

    No author, handle or avatar. `Reply.author_key` exists only to count the
    distinct accounts behind a repeated phrase; the project stores no
    personal data and an API that returned it would undo that.
    """

    model_config = STRICT

    text: str
    like_count: int
    created_at: datetime


class TopicRecurrence(BaseModel):
    """How often this topic has been seen, keyed on its label slug.

    A floor rather than a total: the slug fixes case and punctuation drift
    across runs but not wording drift, so a relabelled topic reads as new.
    """

    model_config = STRICT

    run_count: int
    first_seen_run_id: str | None


class TopicDetail(BaseModel):
    """One topic's dossier: the row, the prose, what people said, and what
    was rendered from it.
    """

    model_config = STRICT

    topic: TopicRow
    # None on the dormant path and on a stale checkpoint. The topic was
    # still ranked, so the row still exists.
    dossier: Dossier | None
    replies: list[ReplyOut]
    renders: list[RenderRecord]
    recurrence: TopicRecurrence
```

Add `from datetime import datetime`, `from zeitgeist.models import Dossier`, and `from zeitgeist.records import RenderRecord` to the imports.

- [ ] **Step 5: Add the endpoint**

In `zeitgeist/api/runs.py`:

```python
# A topic can carry hundreds of replies and the card list is not paginated.
# Most-liked first: the design shows the conversation, not all of it.
MAX_REPLIES = 20


def _replies_for(store: Store, run_id: str, item_ids: set[str]) -> list[ReplyOut]:
    """Replies under this topic's own posts, most-liked first.

    A missing ingest checkpoint is not an error: it is the biggest payload
    in the database and a later phase may prune it. A dossier without
    replies is still a dossier.
    """
    try:
        evidence = store.read_checkpoint(run_id, Stage.INGEST, TrendEvidence)
    except MissingCheckpoint:
        return []
    replies = [
        reply
        for entry in evidence
        for post in entry.posts
        if post.item.source_id in item_ids
        for reply in post.replies
    ]
    replies.sort(key=lambda reply: reply.like_count, reverse=True)
    return [
        ReplyOut(
            text=reply.text,
            like_count=reply.like_count,
            created_at=reply.created_at,
        )
        for reply in replies[:MAX_REPLIES]
    ]


@router.get("/{run_id}/topics/{topic_id}", response_model=TopicDetail)
def read_topic(
    run_id: str, topic_id: str, store: Store = Depends(get_store)
) -> TopicDetail:
    row = next(
        (r for r in store.run_topics(run_id) if r.topic_id == topic_id), None
    )
    if row is None:
        raise HTTPException(
            status_code=404, detail=f"No such topic in {run_id}: {topic_id}"
        )

    try:
        topics = store.read_checkpoint(run_id, Stage.ANALYSE, Topic)
    except MissingCheckpoint:
        topics = []
    topic = next((t for t in topics if t.id == topic_id), None)

    count, first_seen = store.topic_recurrence(row.label_slug)
    return TopicDetail(
        topic=row,
        dossier=None if topic is None else topic.dossier,
        replies=_replies_for(
            store, run_id, set(topic.item_ids) if topic else set()
        ),
        renders=[
            render
            for render in store.renders_for_run(run_id)
            if render.topic_id == topic_id
        ],
        recurrence=TopicRecurrence(
            run_count=count, first_seen_run_id=first_seen
        ),
    )
```

Add `from zeitgeist.models import Topic, TrendEvidence` and `from zeitgeist.store import MissingCheckpoint, Store` to the imports.

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/test_api_runs.py tests/test_store.py -v`

Expected: PASS.

- [ ] **Step 7: Run the full gate**

Run: `uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest`

Expected: all four pass.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "Serve one topic's dossier

The one endpoint that reads checkpoint payloads for prose: the dossier from
the analyse payload, the replies from ingest, filtered to the posts this
topic's item_ids name. Returning every reply in the run would put another
topic's conversation on this dossier.

Replies carry no author, handle or avatar. author_key exists only to count
distinct accounts behind a repeated phrase, and an API returning it would
undo the project's choice not to store personal data - there is a test
asserting the string never appears in the response.

A missing ingest checkpoint returns no replies rather than 500ing: it is
the biggest payload in the database and a later phase may prune it.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 8: `GET /api/runs/{id}/log`

**Files:**
- Modify: `zeitgeist/store.py`, `zeitgeist/records.py`, `zeitgeist/api/runs.py`, `tests/test_api_runs.py`, `tests/test_store.py`

**Interfaces:**
- Produces:
  - `zeitgeist.records.LogLine` — `seq: int`, `logged_at: datetime`, `level: str`, `logger: str`, `message: str`
  - `Store.log_lines(run_id: str, *, verbose: bool) -> list[LogLine]`

**Why this exists now, with an always-empty table:** `log_lines` was created in phase 1 and nothing writes to it until phase 3 adds log capture. The endpoint is built here because it is part of the contract phase 5 generates its client from, and phase 3 then adds only the writer. Its tests seed the table directly — that is the only thing in this plan that writes SQL by hand, and it is justified because the writer does not exist yet.

**What `verbose` means:** off returns `INFO` and above; on returns everything including `DEBUG`. The server always captures at DEBUG (phase 3), so the toggle filters rather than changing what was recorded — which is what makes flipping it work retroactively on lines already captured.

- [ ] **Step 1: Add the model**

In `zeitgeist/records.py`:

```python
class LogLine(BaseModel):
    """One line of a run's log.

    `seq` orders lines within a run: two lines can share a timestamp at the
    resolution the handler records, and the live log's ordering has to be
    total.
    """

    model_config = STRICT

    seq: int
    logged_at: datetime
    level: str
    logger: str
    message: str
```

- [ ] **Step 2: Write the failing store tests**

Add to `tests/test_store.py`:

```python
def _log(store, run_id: str, seq: int, level: str, message: str) -> None:
    """Seed a log line directly.

    The only hand-written SQL in these tests: phase 3 owns the writer, and
    the reader has to be testable before it exists.
    """
    store._conn.execute(
        "INSERT INTO log_lines (run_id, seq, logged_at, level, logger, message) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (run_id, seq, "2026-09-01T12:00:00+00:00", level, "zeitgeist.pipeline", message),
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

    assert [line.message for line in store.log_lines("r1", verbose=True)] == [
        "mine"
    ]
```

- [ ] **Step 3: Run to verify they fail**

Run: `uv run pytest tests/test_store.py -k "log" -v`

Expected: FAIL with `AttributeError: 'Store' object has no attribute 'log_lines'`.

- [ ] **Step 4: Add the store accessor**

In `zeitgeist/store.py`:

```python
    # DEBUG is captured always and filtered here, so the UI's verbose toggle
    # works retroactively on lines already recorded rather than showing
    # nothing until the next line arrives.
    _QUIET_LEVELS = ("INFO", "WARNING", "ERROR", "CRITICAL")

    def log_lines(self, run_id: str, *, verbose: bool) -> list[LogLine]:
        sql = (
            "SELECT seq, logged_at, level, logger, message FROM log_lines "
            "WHERE run_id = ? "
        )
        params: tuple[object, ...] = (run_id,)
        if not verbose:
            placeholders = ", ".join("?" for _ in self._QUIET_LEVELS)
            sql += f"AND level IN ({placeholders}) "
            params = (run_id, *self._QUIET_LEVELS)
        sql += "ORDER BY seq"
        rows = self._conn.execute(sql, params).fetchall()
        return [
            LogLine(
                seq=seq,
                logged_at=datetime.fromisoformat(logged_at),
                level=level,
                logger=logger,
                message=message,
            )
            for seq, logged_at, level, logger, message in rows
        ]
```

Add `LogLine` to the `zeitgeist.records` import.

- [ ] **Step 5: Write the failing API tests**

Add to `tests/test_api_runs.py`:

```python
def test_the_log_of_a_run_with_no_lines_is_empty(tmp_path):
    """Nothing writes log lines until phase 3 adds capture. The endpoint
    exists now because it is part of the contract phase 5 builds against."""
    client = seeded_client(tmp_path, runs=[SeededRun()])

    body = client.get("/api/runs/20260901T120000Z/log").json()

    assert body == []


def test_the_log_endpoint_filters_on_verbose(tmp_path):
    from tests.api_factory import api_settings
    from zeitgeist.store import Store

    client = seeded_client(tmp_path, runs=[SeededRun()])
    store = Store(api_settings(tmp_path).db_path)
    store._conn.execute(
        "INSERT INTO log_lines (run_id, seq, logged_at, level, logger, message) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            "20260901T120000Z",
            1,
            "2026-09-01T12:00:00+00:00",
            "DEBUG",
            "zeitgeist.pipeline",
            "noisy",
        ),
    )
    store._conn.commit()
    store.close()

    quiet = client.get("/api/runs/20260901T120000Z/log").json()
    loud = client.get(
        "/api/runs/20260901T120000Z/log", params={"verbose": "true"}
    ).json()

    assert quiet == []
    assert [line["message"] for line in loud] == ["noisy"]


def test_the_log_of_an_unknown_run_is_a_404(tmp_path):
    client = seeded_client(tmp_path)

    assert client.get("/api/runs/nope/log").status_code == 404
```

- [ ] **Step 6: Add the endpoint**

In `zeitgeist/api/runs.py`:

```python
@router.get("/{run_id}/log", response_model=list[LogLine])
def read_log(
    run_id: str, verbose: bool = False, store: Store = Depends(get_store)
) -> list[LogLine]:
    if store.get_run(run_id) is None:
        raise HTTPException(status_code=404, detail=f"No such run: {run_id}")
    return store.log_lines(run_id, verbose=verbose)
```

Add `LogLine` to the `zeitgeist.records` import.

- [ ] **Step 7: Run the tests**

Run: `uv run pytest tests/test_api_runs.py tests/test_store.py -v`

Expected: PASS.

- [ ] **Step 8: Run the full gate**

Run: `uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest`

Expected: all four pass.

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "Serve a run's log, with the verbose filter

Built now, though log_lines stays empty until phase 3 adds capture: the
endpoint and its filter are part of the contract phase 5 generates its
client from, and phase 3 then adds only the writer. The tests seed the
table directly, which is the one place in this phase that writes SQL by
hand and is justified because the writer does not exist yet.

verbose filters what was already captured rather than changing what is
recorded, so flipping it works retroactively on lines already there instead
of showing nothing until the next line arrives.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 9: `GET /api/renders/{id}` and image serving

**Files:**
- Create: `zeitgeist/api/renders.py`, `tests/test_api_renders.py`
- Modify: `zeitgeist/api/app.py` (mount)

**Interfaces:**
- Consumes: `Store.get_render`, `get_settings`.
- Produces: `zeitgeist.api.renders.router`

**Why the record endpoint exists:** the full-size meme view is deep-linkable, so a render has to be addressable on its own rather than only arriving embedded in topic detail. It returns the whole `RenderRecord` — including, for an auto render, the `rationale` that explains the template choice. That is the screen's whole point.

**The file is on disk and the database is authoritative for whether it exists.** A PNG deleted out from under the row is a 404 with a message saying so, not a 500 and not a silent empty body.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_api_renders.py`:

```python
from PIL import Image

from tests.api_factory import SeededRun, api_settings, seeded_client
from tests.run_factory import make_render_record
from zeitgeist.records import AutoOrigin, ManualOrigin


def _write_png(tmp_path, run_id: str, render_id: str, suffix: str = "") -> None:
    directory = tmp_path / "output" / run_id / "renders"
    directory.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (40, 20), "white").save(
        directory / f"{render_id}{suffix}.png"
    )


def test_a_render_carries_the_brief_that_produced_it(tmp_path):
    """The full-size view shows the slot text and the reasoning, so the
    record has to be addressable rather than only embedded in topic
    detail."""
    client = seeded_client(
        tmp_path,
        runs=[
            SeededRun(
                renders=[
                    make_render_record(
                        "rnd1",
                        caption_slots={"rejected": "a", "preferred": "b"},
                        origin=AutoOrigin(rationale="it fits"),
                    )
                ]
            )
        ],
    )

    body = client.get("/api/renders/rnd1").json()

    assert body["caption_slots"] == {"rejected": "a", "preferred": "b"}
    assert body["origin"]["provenance"] == "auto"
    assert body["origin"]["rationale"] == "it fits"


def test_a_hand_written_render_carries_no_rationale(tmp_path):
    """The union makes it unrepresentable rather than empty, and that has
    to survive serialisation."""
    client = seeded_client(
        tmp_path,
        runs=[SeededRun(renders=[make_render_record("rnd2", origin=ManualOrigin())])],
    )

    body = client.get("/api/renders/rnd2").json()

    assert body["origin"] == {"provenance": "manual"}


def test_an_unknown_render_is_a_404(tmp_path):
    client = seeded_client(tmp_path)

    assert client.get("/api/renders/nope").status_code == 404


def test_the_full_image_is_served(tmp_path):
    client = seeded_client(
        tmp_path, runs=[SeededRun(renders=[make_render_record("rnd1")])]
    )
    _write_png(tmp_path, "20260901T120000Z", "rnd1")

    response = client.get("/api/renders/rnd1/image")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"


def test_the_thumbnail_is_a_different_file(tmp_path):
    """The Runs list draws these at 34px. Serving the full PNG there would
    ship 800KB per tile."""
    client = seeded_client(
        tmp_path, runs=[SeededRun(renders=[make_render_record("rnd1")])]
    )
    _write_png(tmp_path, "20260901T120000Z", "rnd1")
    directory = tmp_path / "output" / "20260901T120000Z" / "renders"
    Image.new("RGB", (96, 48), "black").save(directory / "rnd1.thumb.png")

    full = client.get("/api/renders/rnd1/image", params={"size": "full"})
    thumb = client.get("/api/renders/rnd1/image", params={"size": "thumb"})

    assert full.content != thumb.content


def test_a_render_whose_file_is_gone_is_a_404(tmp_path):
    """The database is authoritative for whether a render exists. A PNG
    deleted underneath the row is a 404 with a reason, not a 500."""
    client = seeded_client(
        tmp_path, runs=[SeededRun(renders=[make_render_record("rnd1")])]
    )

    response = client.get("/api/renders/rnd1/image")

    assert response.status_code == 404


def test_an_unknown_size_is_rejected(tmp_path):
    client = seeded_client(
        tmp_path, runs=[SeededRun(renders=[make_render_record("rnd1")])]
    )

    assert (
        client.get(
            "/api/renders/rnd1/image", params={"size": "enormous"}
        ).status_code
        == 422
    )
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_api_renders.py -v`

Expected: FAIL with 404s.

- [ ] **Step 3: Write the router**

Create `zeitgeist/api/renders.py`:

```python
"""One render's record, and its image.

The record endpoint exists because the full-size view is deep-linkable: a
render has to be addressable on its own rather than only arriving embedded
in topic detail, and the view shows the slot text and — for an auto render —
the rationale behind the template choice.

The database is authoritative for whether a render exists. A PNG deleted out
from under its row is a 404 that says so, never a 500.
"""

from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from zeitgeist.api.app import get_settings, get_store
from zeitgeist.config import Settings
from zeitgeist.records import RenderRecord
from zeitgeist.store import Store

router = APIRouter(prefix="/api/renders", tags=["renders"])

ImageSize = Literal["full", "thumb"]


def _image_path(settings: Settings, record: RenderRecord, size: ImageSize) -> Path:
    suffix = ".png" if size == "full" else ".thumb.png"
    return (
        Path(settings.output_dir)
        / record.run_id
        / "renders"
        / f"{record.id}{suffix}"
    )


@router.get("/{render_id}", response_model=RenderRecord)
def read_render(
    render_id: str, store: Store = Depends(get_store)
) -> RenderRecord:
    record = store.get_render(render_id)
    if record is None:
        raise HTTPException(
            status_code=404, detail=f"No such render: {render_id}"
        )
    return record


@router.get("/{render_id}/image")
def read_image(
    render_id: str,
    size: ImageSize = "full",
    store: Store = Depends(get_store),
    settings: Settings = Depends(get_settings),
) -> FileResponse:
    record = store.get_render(render_id)
    if record is None:
        raise HTTPException(
            status_code=404, detail=f"No such render: {render_id}"
        )
    path = _image_path(settings, record, size)
    if not path.is_file():
        raise HTTPException(
            status_code=404,
            detail=f"Render {render_id} has no {size} image on disk",
        )
    return FileResponse(path, media_type="image/png")
```

- [ ] **Step 4: Mount the router**

In `create_app`:

```python
    from zeitgeist.api import renders as renders_router

    app.include_router(renders_router.router)
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_api_renders.py -v`

Expected: PASS, 7 tests.

- [ ] **Step 6: Run the full gate**

Run: `uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest`

Expected: all four pass.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "Serve one render and its image

The record is addressable on its own because the full-size view is
deep-linkable and shows the slot text and the rationale behind the template
choice - which is the view's whole point, and is not reachable from a
render embedded in topic detail.

The database is authoritative for whether a render exists, so a PNG deleted
out from under its row is a 404 that says so rather than a 500. Thumbnails
are a separate file: the Runs list draws these at 34px and serving the full
PNG there would ship 800KB per tile.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 10: `GET /api/topics` — the cross-run index

**Files:**
- Create: `zeitgeist/api/topics.py`, `tests/test_api_topics.py`
- Modify: `zeitgeist/store.py`, `zeitgeist/api/schemas.py`, `zeitgeist/api/app.py`, `tests/test_store.py`

**Interfaces:**
- Produces:
  - `Store.recent_run_ids(limit: int) -> list[str]` — newest first
  - `Store.topics_for_runs(run_ids: Sequence[str]) -> list[TopicRow]`
  - `zeitgeist.api.schemas.IndexedTopic` — `topic: TopicRow`, `run_count: int`, `render_count: int`
  - `zeitgeist.api.schemas.TopicIndex` — `topics: list[IndexedTopic]`, `status_totals: dict[str, int]`, `sentiment_totals: dict[str, int]`, `previous_sentiment_totals: dict[str, int]`

**What "deduplicated by topic id" means in practice:** the design says the index is deduplicated across a window of runs. The only cross-run identity the store has is `label_slug`, so dedup is on that, keeping the occurrence from the most recent run — a topic seen in three runs appears once, with its newest scores and a `run_count` of 3.

**The mood bar's delta:** the design's bottom row compares average meme potential and sentiment mix "versus the previous run". `previous_sentiment_totals` is the distribution of the run immediately before the window's newest, so the client can draw the comparison without a second request.

- [ ] **Step 1: Write the failing store tests**

Add to `tests/test_store.py`:

```python
def test_recent_run_ids_are_newest_first(tmp_path):
    store = _store(tmp_path)
    for run_id in ("20260901T100000Z", "20260901T120000Z", "20260901T110000Z"):
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
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_store.py -k "recent_run_ids or topics_for_runs" -v`

Expected: FAIL with `AttributeError`.

- [ ] **Step 3: Add the store accessors**

In `zeitgeist/store.py`:

```python
    def recent_run_ids(self, limit: int) -> list[str]:
        rows = self._conn.execute(
            "SELECT run_id FROM run_records ORDER BY started_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [run_id for (run_id,) in rows]

    def topics_for_runs(self, run_ids: Sequence[str]) -> list[TopicRow]:
        """Every topic across the named runs, newest run first.

        An empty `run_ids` short-circuits: `WHERE run_id IN ()` is a syntax
        error in SQLite, not an empty result.
        """
        if not run_ids:
            return []
        placeholders = ", ".join("?" for _ in run_ids)
        rows = self._conn.execute(
            "SELECT t.run_id, t.topic_id, t.label, t.label_slug, "
            "t.trend_status, t.event_sentiment, t.conversation_register, "
            "t.meme_potential, t.trend_score, t.final_score, t.final_rank, "
            "t.post_count, t.top_phrase, t.top_phrase_authors "
            "FROM run_topics t JOIN run_records r ON r.run_id = t.run_id "
            f"WHERE t.run_id IN ({placeholders}) "
            "ORDER BY r.started_at DESC, t.final_rank",
            tuple(run_ids),
        ).fetchall()
        return [_topic_row(row) for row in rows]
```

`run_topics` currently builds its `TopicRow` inline. Extract that into a module-level `_topic_row(row: tuple) -> TopicRow` beside `_render` and `_run_record`, and have both methods use it.

- [ ] **Step 4: Write the failing API tests**

Create `tests/test_api_topics.py`:

```python
from zeitgeist.models import Sentiment

from tests.api_factory import SeededRun, seeded_client
from tests.run_factory import make_dossier, make_topic


def test_a_topic_seen_in_several_runs_appears_once(tmp_path):
    """The index is deduplicated across the window: `SEEN IN 3 RUNS` is one
    card, not three."""
    client = seeded_client(
        tmp_path,
        runs=[
            SeededRun(run_id="20260901T100000Z", topics=[make_topic("cats")]),
            SeededRun(run_id="20260901T110000Z", topics=[make_topic("cats")]),
        ],
    )

    body = client.get("/api/topics").json()

    assert [entry["topic"]["topic_id"] for entry in body["topics"]] == ["cats"]
    assert body["topics"][0]["run_count"] == 2


def test_the_newest_occurrence_wins(tmp_path):
    """A deduplicated card shows current scores, not the first sighting's."""
    client = seeded_client(
        tmp_path,
        runs=[
            SeededRun(
                run_id="20260901T100000Z",
                topics=[make_topic("cats", trend_score=0.1)],
            ),
            SeededRun(
                run_id="20260901T110000Z",
                topics=[make_topic("cats", trend_score=0.9)],
            ),
        ],
    )

    body = client.get("/api/topics").json()

    assert body["topics"][0]["topic"]["trend_score"] == 0.9
    assert body["topics"][0]["topic"]["run_id"] == "20260901T110000Z"


def test_the_window_bounds_how_many_runs_are_considered(tmp_path):
    client = seeded_client(
        tmp_path,
        runs=[
            SeededRun(run_id="20260901T100000Z", topics=[make_topic("old")]),
            SeededRun(run_id="20260901T110000Z", topics=[make_topic("new")]),
        ],
    )

    body = client.get("/api/topics", params={"window": 1}).json()

    assert [entry["topic"]["topic_id"] for entry in body["topics"]] == ["new"]


def test_the_status_filter_narrows_the_list(tmp_path):
    client = seeded_client(
        tmp_path,
        runs=[
            SeededRun(
                topics=[
                    make_topic("hot", trend_status="trending"),
                    make_topic("cold", trend_status="cooling"),
                ]
            )
        ],
    )

    body = client.get("/api/topics", params={"status": "cooling"}).json()

    assert [entry["topic"]["topic_id"] for entry in body["topics"]] == ["cold"]


def test_status_totals_count_the_whole_window_not_the_filtered_list(tmp_path):
    """The filter chips show `trending 9 / saturating 6 / cooling 4` while
    one of them is active, so the totals cannot come from the filtered
    result."""
    client = seeded_client(
        tmp_path,
        runs=[
            SeededRun(
                topics=[
                    make_topic("hot", trend_status="trending"),
                    make_topic("cold", trend_status="cooling"),
                ]
            )
        ],
    )

    body = client.get("/api/topics", params={"status": "cooling"}).json()

    assert body["status_totals"] == {"trending": 1, "cooling": 1}


def test_the_sentiment_distribution_covers_the_window(tmp_path):
    """The mood bar is one segment per sentiment sized by share."""
    client = seeded_client(
        tmp_path,
        runs=[
            SeededRun(
                topics=[
                    make_topic(
                        "a", dossier=make_dossier(event_sentiment=Sentiment.FUNNY)
                    ),
                    make_topic(
                        "b", dossier=make_dossier(event_sentiment=Sentiment.FUNNY)
                    ),
                    make_topic(
                        "c", dossier=make_dossier(event_sentiment=Sentiment.CUTE)
                    ),
                ]
            )
        ],
    )

    body = client.get("/api/topics").json()

    assert body["sentiment_totals"] == {"funny": 2, "cute": 1}


def test_the_previous_run_distribution_is_reported_separately(tmp_path):
    """The mood line reads `versus the previous run`, so the comparison has
    to arrive without a second request."""
    client = seeded_client(
        tmp_path,
        runs=[
            SeededRun(
                run_id="20260901T100000Z",
                topics=[
                    make_topic(
                        "old", dossier=make_dossier(event_sentiment=Sentiment.SAD)
                    )
                ],
            ),
            SeededRun(
                run_id="20260901T110000Z",
                topics=[
                    make_topic(
                        "new",
                        dossier=make_dossier(event_sentiment=Sentiment.FUNNY),
                    )
                ],
            ),
        ],
    )

    body = client.get("/api/topics", params={"window": 1}).json()

    assert body["sentiment_totals"] == {"funny": 1}
    assert body["previous_sentiment_totals"] == {"sad": 1}


def test_an_empty_database_returns_an_empty_index(tmp_path):
    client = seeded_client(tmp_path)

    body = client.get("/api/topics").json()

    assert body == {
        "topics": [],
        "status_totals": {},
        "sentiment_totals": {},
        "previous_sentiment_totals": {},
    }
```

- [ ] **Step 5: Add the response models**

In `zeitgeist/api/schemas.py`:

```python
class IndexedTopic(BaseModel):
    """One card in the topics index.

    `run_count` is how many runs in the window carried this topic, keyed on
    its label slug — `SEEN IN 3 RUNS` on the card, or `NEW THIS RUN` at one.
    """

    model_config = STRICT

    topic: TopicRow
    run_count: int
    render_count: int


class TopicIndex(BaseModel):
    """The topics index and the aggregates drawn beside it.

    `status_totals` counts the whole window rather than the filtered list,
    because the filter chips show every bucket's total while one of them is
    active. `previous_sentiment_totals` is the run before the window, which
    is what the mood line's "versus the previous run" compares against.
    """

    model_config = STRICT

    topics: list[IndexedTopic]
    status_totals: dict[str, int]
    sentiment_totals: dict[str, int]
    previous_sentiment_totals: dict[str, int]
```

- [ ] **Step 6: Write the router**

Create `zeitgeist/api/topics.py`:

```python
"""The cross-run topics index.

Deduplicated on `label_slug`, which is the only cross-run identity the store
has: labels are model-generated every run, and the slug fixes case and
punctuation drift but not wording drift. A relabelled topic reads as new, so
`run_count` is a floor rather than a total — the UI says "seen in" rather
than claiming a count.
"""

from collections import Counter

from fastapi import APIRouter, Depends, Query

from zeitgeist.api.app import get_store
from zeitgeist.api.schemas import IndexedTopic, TopicIndex
from zeitgeist.models import TrendStatus
from zeitgeist.projection import TopicRow
from zeitgeist.store import Store

router = APIRouter(prefix="/api/topics", tags=["topics"])

# The design's header reads "across the last 6 runs".
DEFAULT_WINDOW = 6


def _sentiments(rows: list[TopicRow]) -> dict[str, int]:
    return dict(
        Counter(row.event_sentiment for row in rows if row.event_sentiment)
    )


@router.get("", response_model=TopicIndex)
def read_index(
    window: int = Query(default=DEFAULT_WINDOW, ge=1, le=50),
    status: TrendStatus | None = None,
    store: Store = Depends(get_store),
) -> TopicIndex:
    run_ids = store.recent_run_ids(window + 1)
    in_window, previous = run_ids[:window], run_ids[window : window + 1]

    rows = store.topics_for_runs(in_window)
    # topics_for_runs is newest-run-first, so the first row for a slug is
    # its most recent occurrence — a deduplicated card shows current scores
    # rather than the first sighting's.
    newest: dict[str, TopicRow] = {}
    counts: Counter[str] = Counter()
    for row in rows:
        counts[row.label_slug] += 1
        newest.setdefault(row.label_slug, row)

    render_counts: dict[str, int] = {}
    for run_id in in_window:
        render_counts |= {
            f"{run_id}:{topic_id}": count
            for topic_id, count in store.render_counts(run_id).items()
        }

    selected = [
        row for row in newest.values() if status is None or row.trend_status == status
    ]
    return TopicIndex(
        topics=[
            IndexedTopic(
                topic=row,
                run_count=counts[row.label_slug],
                render_count=render_counts.get(f"{row.run_id}:{row.topic_id}", 0),
            )
            for row in selected
        ],
        # The whole window, not the filtered list: the chips show every
        # bucket's total while one of them is active.
        status_totals=dict(Counter(row.trend_status for row in newest.values())),
        sentiment_totals=_sentiments(list(newest.values())),
        previous_sentiment_totals=_sentiments(store.topics_for_runs(previous)),
    )
```

- [ ] **Step 7: Mount the router**

In `create_app`:

```python
    from zeitgeist.api import topics as topics_router

    app.include_router(topics_router.router)
```

- [ ] **Step 8: Run the tests**

Run: `uv run pytest tests/test_api_topics.py tests/test_store.py -v`

Expected: PASS.

- [ ] **Step 9: Run the full gate**

Run: `uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest`

Expected: all four pass.

- [ ] **Step 10: Commit**

```bash
git add -A
git commit -m "Serve the cross-run topics index

Deduplicated on label_slug, keeping the newest occurrence so a card shows
current scores rather than the first sighting's. run_count is a floor
rather than a total: the slug fixes case and punctuation drift across runs
but not wording drift, so a relabelled topic reads as new.

status_totals counts the whole window rather than the filtered list,
because the filter chips show every bucket's total while one of them is
active. previous_sentiment_totals is the run before the window, which is
what the mood line's 'versus the previous run' compares against - it
arrives in the same response so the client needs no second request.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 11: Documentation

**Files:**
- Modify: `README.md`

**Interfaces:** none — this task changes no code.

- [ ] **Step 1: Rewrite the running section**

The README currently describes `scripts/run_pipeline.py` as the only way to use the tool. Add a `## The web UI` section before `## Tests` covering:

- Starting the server: `uv run zeitgeist`, which serves on `127.0.0.1:8000` by default, with `--host`, `--port` and `--reload`.
- That `--reload` is off by default because uvicorn's reloader kills a run in flight, and phase 3 adds runs that can be in flight.
- Where the API documents itself: `http://127.0.0.1:8000/docs` for the interactive schema, `/openapi.json` for the raw one.
- That this phase serves reads only — starting a run is still `uv run python scripts/run_pipeline.py`.
- How the frontend's TypeScript types will be generated, for whoever picks up phase 5:

  ```bash
  npx openapi-typescript http://127.0.0.1:8000/openapi.json -o web/src/api/schema.ts
  ```

  and that this is deliberately not run yet — there is no `web/` and no gate command that would check the result.

Keep the existing `scripts/run_pipeline.py` instructions; they are still how a run is produced.

- [ ] **Step 2: Verify the documented commands actually work**

Run: `uv run zeitgeist --help`

Expected: usage text listing `--host`, `--port`, `--reload`.

Then start the server, check the two documentation URLs, and stop it:

```bash
uv run zeitgeist --port 8123 &
sleep 3
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8123/docs
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8123/openapi.json
kill %1
```

Expected: `200` twice. If `curl` is unavailable, use `uv run python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8123/openapi.json').status)"`.

- [ ] **Step 3: Run the full gate**

Run: `uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest`

Expected: all four pass.

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "Document the server

Covers starting it, why --reload is off by default, and where the API
documents itself. Records the command phase 5 will use to generate the
client's TypeScript types, and that it is deliberately not run yet: there
is no web/ and no gate command that would check the result.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Verification

After Task 11, confirm the phase's stated end condition — a run produced by the harness, served correctly over HTTP.

- [ ] **Produce a run**

```bash
uv run python scripts/run_pipeline.py
```

- [ ] **Serve it and read it back**

```bash
uv run zeitgeist --port 8123 &
sleep 3
curl -s "http://127.0.0.1:8123/api/runs" | jq '.runs[0].run.run_id, .runs[0].topic_labels'
RUN=$(curl -s "http://127.0.0.1:8123/api/runs" | jq -r '.runs[0].run.run_id')
curl -s "http://127.0.0.1:8123/api/runs/$RUN" | jq '.resume_stage, (.stages | length)'
curl -s "http://127.0.0.1:8123/api/runs/$RUN/topics" | jq '[.[] | {rank: .topic.final_rank, id: .topic.topic_id, above: .above_cut}]'
TOPIC=$(curl -s "http://127.0.0.1:8123/api/runs/$RUN/topics" | jq -r '.[0].topic.topic_id')
curl -s "http://127.0.0.1:8123/api/runs/$RUN/topics/$TOPIC" | jq '.dossier.event_sentiment, (.replies | length), .recurrence'
curl -s "http://127.0.0.1:8123/api/topics" | jq '.status_totals, .sentiment_totals'
curl -s "http://127.0.0.1:8123/api/settings" | jq '.[0]'
RENDER=$(curl -s "http://127.0.0.1:8123/api/runs/$RUN/topics/$TOPIC" | jq -r '.renders[0].id')
curl -s -o /dev/null -w "image %{http_code} %{size_download} bytes\n" "http://127.0.0.1:8123/api/renders/$RENDER/image"
curl -s -o /dev/null -w "thumb %{http_code} %{size_download} bytes\n" "http://127.0.0.1:8123/api/renders/$RENDER/image?size=thumb"
kill %1
```

Expected: the run id and its topic labels; a resume stage of `generate` and four stages; every topic with a rank and an `above_cut` flag, more topics than `top_count`; a real sentiment, some replies and a recurrence of 1; non-empty status and sentiment totals; a settings field with a `source`; and two `200`s where the thumbnail is markedly smaller than the full image.

- [ ] **Confirm the key never appears**

```bash
uv run zeitgeist --port 8123 &
sleep 3
curl -s "http://127.0.0.1:8123/api/settings" | grep -i "anthropic\|sk-ant" && echo "LEAK" || echo "clean"
kill %1
```

Expected: `clean`.

---

## Notes for the executor

**There is no red window in this phase.** Unlike phase 1, every task starts and ends with all four gate commands green. A failure that is not yours is a signal something is wrong, not something to work around.

**Do not add write endpoints.** `PUT /api/settings`, `POST /api/runs`, resume, stop, abort and the SSE stream are phase 3. `POST .../renders` and `DELETE /api/renders/{id}` are phase 4. An endpoint built early has no consumer, no test that means anything, and a contract nobody has reviewed against the screens that will use it.

**Do not generate TypeScript.** The spec moved it to phase 5, where the Vite scaffold exists to lint and typecheck the result. This phase exposes the schema and documents the command.

**Do not add an `/api/overview`.** The merged Topics screen deliberately issues three parallel queries so each response stays independently cacheable — a screen-shaped endpoint would couple them and drag topic data along with the in-flight poll phase 3 adds.

**Two things this phase surfaces that the design did not anticipate**, both noted in the code and worth carrying into phase 6 rather than solving here:

- The settings screen draws three source chips but there are four layers, because a shell variable outranks the settings table. `GET /api/settings` returns `environment` as a fourth value.
- `Reply.author_key` must never be serialised. There is a test asserting the string does not appear in a topic-detail response; keep it.

**If a test in this plan seems wrong, say so rather than weakening it.** Several assert properties the spec argues for at length: that the ranking includes below-the-cut topics, that `status_totals` counts the window rather than the filtered list, that replies come only from the topic's own posts, and that a missing ingest checkpoint degrades to no replies rather than a 500. Changing one to make it pass would remove the thing it exists to protect.
