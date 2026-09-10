# Run Control Screens Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Start, watch, stop and abort a run from the browser, and tune the
seven writable settings from a screen — phase 6 of
`docs/superpowers/specs/2026-09-02-web-ui-design.md`.

**Architecture:** Three Python tasks first, because the in-flight screens the
design specifies read progress the pipeline never persisted (see "Decisions",
1). They add `done`/`total` to `StageRecord`, make the runner's observer write
what it watches instead of discarding it, and emit progress from the analyse
stage. Then nine React tasks: the live hooks and the mutation client, the
`InlineConfirm` and `LiveLog` primitives, the three places an active run
surfaces (sidebar card, run strip, Runs in-flight card), the two in-flight
run-detail states with their event stream, the New run screen, and the
settings screen. A final task walks the whole thing against a real run.

**Tech Stack:** Python 3.14, FastAPI, pydantic 2, SQLite. React 19,
TypeScript 5.7, Vite 7, TanStack Query 5, React Router 7, CSS Modules,
Vitest + Testing Library + MSW.

## Global Constraints

- **Definition of Done.** All seven commands pass before any task is
  reported finished: `uv run ruff check .`, `uv run ruff format --check .`,
  `uv run ty check`, `uv run pytest`, `npm --prefix web run lint`,
  `npm --prefix web run typecheck`, `npm --prefix web test`.
- **Python 3.14.** PEP 695 generics (`def f[T: Bound](...)`), never
  `typing.TypeVar`.
- **ruff.** Rules `E, F, I, UP, B, SIM`, line length 88.
- **ty.** No blanket `# type: ignore`. A narrow suppression needs a comment
  saying why.
- **TypeScript.** No `any`, no `!`, no `as`. `eslint.config.js` enforces all
  three; `src/api/client.ts` is the one file exempt from the assertion rule,
  because `Response.json()` is `Promise<any>` by definition. Anything that
  needs to narrow untyped JSON goes there, or uses a `value is T` predicate.
- **No raw colours in `.module.css`.** `src/styles/no-raw-colours.test.ts`
  fails on any `#hex` or `rgba(` outside `tokens.css`, with
  `StageBar.module.css` the one documented exception. New colours become
  tokens.
- **No `styles.foo` without a matching class.** The same test file checks
  every static `styles.x` against its paired stylesheet.
- **Contract drift is a gate, twice.** `uv run pytest` asserts
  `web/openapi.json` matches the app; `npm --prefix web run typecheck`
  asserts `web/src/api/schema.ts` matches `web/openapi.json`. Any response
  model change means running both:
  `uv run python scripts/dump_openapi.py` then
  `npm --prefix web run generate:types`.
- **Tests are hermetic.** `tests/conftest.py` strips every environment
  variable `Settings` reads and repoints `DB_PATH` into `tmp_path`. No
  network, every model call through `FakeLLMProvider`.
- **MSW declares every response.** `src/test/server.ts` ships no default
  handlers and `setup.ts` sets `onUnhandledRequest: "error"`, so a screen
  that fetches something the test did not describe fails loudly.
- **Fixtures come from factories.** `tests/run_factory.py` and
  `web/src/test/factories.ts`. Never a hand-written dict or object literal
  standing in for a contract type.
- **No modals.** Every confirmation swaps in place, per the handoff.
- **Copy is final.** Where this plan quotes UI text, it is the design's own
  wording and is transcribed exactly.

---

## Decisions this phase is required to make

### 1. The in-flight progress data does not exist, and this phase writes it

Phase 3 built `RunObserver` and `CancelToken` (`zeitgeist/progress.py`) but
wired `_StageTracker` — a `NullObserver` subclass recording only
`last_stage` — as the only observer `RunService._run_one` ever passes
(`runner.py:145`, `runner.py:428`). Three consequences, all of which block
the designed screens:

- `pipeline._stage()` writes a `StageRecord` only at stage *end*, always
  `status="ok"`. No stage is ever `running` in the database.
- `StageRecord` has no counters, so 5a/5b's `17 / 25`, the partial stage bar
  and `~4m left` have nothing behind them.
- `observer.stage_progress` is called from exactly one place, `_render_all`
  (`pipeline.py:287`). The analyse stage never emits it at all.

Tasks 1–3 close the first three. `StageRecord` gains `done: int | None` and
`total: int | None`; the runner's observer writes a `running` row on
`stage_started` and rewrites it with counters on `stage_progress`; the
analyse stage emits progress per distilled topic.

**`~4m left` is dropped.** An estimate needs a rate, and the only honest
rate — elapsed over `done` — is meaningless for the first item and wrong
whenever the remaining work is unlike the work already done. The artifact
line on a running card shows the checkpoint name alone, which is what a
stage that has written nothing yet actually knows.

### 2. Ranking rows do not append mid-analyse; that is deferred

`topic_distilled` fires per topic (`distil.py:188`) but persisting one needs
a `run_topics` row, and `TopicRow` requires `trend_score`, `final_score` and
`final_rank` — none of which exist until every topic is distilled and
`score_topics` has run. The design already concedes the point ("Order is not
decided until evaluate, so the rank column shows `·`"), which means
mid-analyse rows are a *different shape*, needing a rank-less response model
and a second endpoint.

That is a contract change with its own design questions, and folding it into
a screens phase would mix a storage decision into React work. So: during
analyse the ranking section renders its label with the hint
`final order is set in evaluate` and the line
`Distilling — the ranking appears when analyse finishes.` The live log is
where per-topic progress is visible in this phase, and it is genuinely
per-topic (`distil.py` logs `Distilled %r in %.1fs` at DEBUG for each).

Written down as deferred work in the spec's own terms rather than silently
dropped.

### 3. Model rows carry no annotation

The design's model radio list draws a right-aligned `default` / `slower` /
`cheap`. `GET /api/config/options` returns `models: dict[str, list[str]]` —
bare ids — and `zeitgeist/llm/registry.py` holds no annotation data for
either provider. Ollama's list is whatever `/api/tags` reports locally, so
annotations there could never be more than guesses about someone else's
machine.

Both provider lists render the model id alone. A hardcoded editorial claim
about speed and cost that nothing verifies, and that goes stale as models
change, would be worse than the blank. Flagged back to the designer as
needing a real source or removal.

### 4. Settings rows show the real key names

The spec's three cards name `trend_limit` and `posts_per_trend`. The actual
writable keys are `bluesky_trend_limit` and `bluesky_posts_per_trend`
(`settings_source.py:22`). The screen shows the real keys.

The whole point of this screen is telling you which layer supplied which
setting; printing a key name that no layer would ever match — not the
environment variable, not the `.env` line, not the settings row — would undo
that on the one screen where it matters most. Card *grouping* follows the
spec exactly.

### 5. There are four source chips, not three

`SettingSource` is `Literal["settings", "environment", "dotenv", "default"]`
and `api/schemas.py` flags the mismatch in its own comment: a shell variable
outranks the settings table, so `environment` is a real answer the design
never drew.

Four chips: `SET HERE` in `accent-tint`, `FROM ENV` in `chip-fill-strong`,
`FROM .env` in `chip-fill`, `DEFAULT` in `text-30`. `FROM ENV` gets the
stronger fill because it is the one state where Save cannot change what the
next run actually uses, and that must not look identical to the ordinary
`.env` fallback.

### 6. The verbose toggle filters on the client

The spec says the toggle filters "what the client renders and what the
stream sends". The stream does not filter: `control.py:169` sends every line
in the buffer regardless. Changing that would mean a per-connection filter on
an endpoint whose contract phase 5 already generated against.

So the toggle is a client-side filter over lines already received — which is
what makes it retroactive, which is the behaviour the spec actually wants
("Flipping it works retroactively on lines already captured"). The
post-mortem log for a finished run keeps using the server's own `?verbose=`
filter, because there is no buffer to filter locally.

### 7. `defaults.sources` is not read

`ConfigOptions.defaults` is built as `str(getattr(settings, key))`
(`options.py:38`), and `Settings.sources` is a `list[str]` — so the value
arrives as the Python repr `"['bluesky']"`, not a platform name. The New run
screen takes its default platform from `platforms[]` where `enabled` is
true, and posts `sources` as a bare name, which `Settings._split_csv`
accepts. Every other key in `defaults` is a scalar and is read normally.

### 8. Elapsed ticks on the client

Nothing on the wire carries "how long has this been running". The screens
compute it from `run.started_at` against a clock that re-renders once a
second while a run is live, and clear the interval when it is not. One
`setInterval` in one hook, not one per screen.

---

## What phases 1–5 left you

Read these before starting. Every one is load-bearing for some task below.

**Backend**

- `zeitgeist/records.py` — `Stage`, `RunStatus`, `StageStatus`, `RunConfig`,
  `RunError`, `RunRecordRow`, `StageRecord`, `RenderRecord`, `LogLine`.
- `zeitgeist/progress.py` — `RunObserver` Protocol, `NullObserver`,
  `RecordingObserver`, `CancelToken`, `Aborted`.
- `zeitgeist/runner.py` — `RunService`, `RunRequest`, `QueuedRun`,
  `ActiveRuns`, `RUN_OVERRIDE_KEYS`, `resolve_settings`, `_StageTracker`.
- `zeitgeist/pipeline.py` — `run_pipeline`, `_stage`, `_skip`, `_render_all`.
- `zeitgeist/store.py` — `record_stage` (INSERT OR REPLACE),
  `stages_for_run`, `log_lines(run_id, verbose=)`, `get_settings`,
  `set_setting`, `clear_setting`.
- `zeitgeist/schema.py` — `SCHEMA_VERSION = 3`, the `run_stages` DDL.
- `zeitgeist/api/control.py` — `POST /api/runs`, `GET /api/runs/active`,
  `POST /{id}/resume`, `/stop`, `/abort`, `GET /{id}/events` (SSE).
- `zeitgeist/api/options.py`, `api/settings.py`, `api/schemas.py`.
- `tests/api_factory.py` — `seeded_client`, `SeededRun`, `seed_run`,
  `GatedExecute`, `LoggingGate`, `api_settings`.
- `tests/run_factory.py` — `make_run_config`, `make_stage_record`,
  `make_topic`, `make_render_record`, `FIXED_TIME`.

**Frontend**

- `src/api/client.ts` — `apiGet`, `imageUrl`, `ApiError`, `QueryParams`.
- `src/api/types.ts` — every named alias, `STAGES`, `ARTIFACT_NAMES`.
- `src/api/queries.ts` — `queryKeys`, six read hooks, `DEFAULT_RUN_LIMIT`,
  `DEFAULT_WINDOW`.
- `src/format.ts` — `formatBytes`, `formatDuration`, `formatRelative`,
  `formatClock`, `formatScore`, `shortRunId`.
- `src/components/` — `Chip`, `StatusPill`, `StageBar`, `MemeTile`,
  `SectionLabel`, `MetaLine`, `Breadcrumb`, `EmptyState`, `QueryBoundary`.
- `src/app/` — `routes.tsx` (five routes), `AppLayout.tsx`, `Sidebar.tsx`
  (two nav items), `providers.tsx`.
- `src/features/runs/` — `RunsPage`, `RunRow`, `RunDetailPage`,
  `StageCards`, `RankingList`, `RankRow`, `survived.ts`.
- `src/features/topics/` — `TopicsPage` and its parts.
- `src/test/` — `render.tsx` (`renderWithProviders`, `.Wrapper`),
  `server.ts`, `setup.ts`, `factories.ts`.
- `src/styles/tokens.css`, `no-raw-colours.test.ts`.

**Design sources**

- `docs/superpowers/specs/2026-09-02-web-ui-design.md` — "Run execution
  service", "API surface", "Frontend", "The live log", "Failure and abort
  states", "Settings", "Jump to latest", "Settings storage".
- `docs/superpowers/UI/README.md` — screens 1, 3, 7 and 8; the token,
  typography and geometry tables.

---

## File Structure

**Created**

| File | Responsibility |
| --- | --- |
| `web/src/components/InlineConfirm.tsx` + `.module.css` | Swap-in-place confirm. Abort here, render delete in phase 7. |
| `web/src/components/InlineConfirm.test.tsx` | Its behaviour. |
| `web/src/features/runs/progress.ts` | `activeStage`, `stageFill`, `stageCounter` — pure, shared by three screens. |
| `web/src/features/runs/progress.test.ts` | Its tests. |
| `web/src/features/runs/LiveLog.tsx` + `.module.css` | The log block, follow behaviour, jump-to-latest, verbose toggle. |
| `web/src/features/runs/LiveLog.test.tsx` | Its tests. |
| `web/src/features/runs/InFlightCard.tsx` + `.module.css` | The Runs-screen card: badge, elapsed, four-segment bar. |
| `web/src/features/runs/RunStrip.tsx` + `.module.css` | Topics' three-row run strip. |
| `web/src/features/runs/RunActions.tsx` + `.module.css` | The header button pair, both states. |
| `web/src/features/newrun/NewRunPage.tsx` + `.module.css` | The screen and its submit. |
| `web/src/features/newrun/ModelCard.tsx` + `.module.css` | Provider pills, key line, model list. |
| `web/src/features/newrun/PlatformCard.tsx` + `.module.css` | 3-up radio cards. |
| `web/src/features/newrun/CountCard.tsx` + `.module.css` | `topic_count` pills and custom. |
| `web/src/features/newrun/TemplateCard.tsx` + `.module.css` | `all N` plus one chip per template. |
| `web/src/features/newrun/NewRunPage.test.tsx` | Its tests. |
| `web/src/features/settings/SettingsPage.tsx` + `.module.css` | Three cards, Save, Reset to .env. |
| `web/src/features/settings/SettingRow.tsx` + `.module.css` | One row: name, input, source chip, explanation. |
| `web/src/features/settings/fields.ts` | Card grouping, explanations, hints — data, not markup. |
| `web/src/features/settings/SettingsPage.test.tsx` | Its tests. |
| `web/src/app/Sidebar.test.tsx` | Nav items and the in-flight card. |
| `web/src/test/eventsource.ts` | `FakeEventSource`, installed per test. |

**Modified**

| File | Change |
| --- | --- |
| `zeitgeist/records.py` | `StageRecord` gains `done`, `total`. |
| `zeitgeist/schema.py` | `run_stages` gains two columns; `SCHEMA_VERSION` → 4. |
| `zeitgeist/store.py` | `record_stage` / `stages_for_run` carry the two columns. |
| `zeitgeist/runner.py` | `_StageTracker` becomes `_RunRecorder`, which writes. |
| `zeitgeist/pipeline.py` | Analyse emits `stage_progress` per distilled topic. |
| `tests/run_factory.py` | `make_stage_record` gains `done`, `total`. |
| `web/openapi.json`, `web/src/api/schema.ts` | Regenerated. |
| `web/src/api/client.ts` | `apiSend`, `openRunEvents`, `parseLogEvent`. |
| `web/src/api/types.ts` | `ActiveRuns`, `QueuedRun`, `ConfigOptions`, `SettingSource`, `TemplateOption`, `PlatformOption`, `SETTING_KEYS`. |
| `web/src/api/queries.ts` | Live hooks, `useRunEvents`, five mutations. |
| `web/src/format.ts` | `formatElapsed`. |
| `web/src/styles/tokens.css` | Three tokens. |
| `web/src/app/routes.tsx` | `/runs/new`, `/settings`. |
| `web/src/app/Sidebar.tsx` | Settings nav item, in-flight card. |
| `web/src/features/runs/StageCards.tsx` | Running treatment, counters, partial fill. |
| `web/src/features/runs/RunDetailPage.tsx` | Live header, actions, log, in-flight ranking. |
| `web/src/features/runs/RunsPage.tsx` | In-flight card, New run button. |
| `web/src/features/runs/RankingList.tsx` | The mid-analyse line and hint. |
| `web/src/features/topics/TopicsPage.tsx` | Run strip, New run button. |
| `web/src/test/factories.ts` | Six new factories. |
| `web/src/test/setup.ts` | Installs `FakeEventSource`. |
| `README.md` | The settings screen, and starting a run from the browser. |

---

### Task 1: `StageRecord` learns to count, and the schema goes to 4

The contract change this phase needs, made once and regenerated once. A
stage that reports counters is `analyse` and `generate`; `ingest` and
`evaluate` report none, and `None` there is a real state rather than a
migration concession — they are single opaque operations with nothing to
count.

**Files:**
- Modify: `zeitgeist/records.py` (`StageRecord`)
- Modify: `zeitgeist/schema.py` (`SCHEMA_VERSION`, `run_stages` DDL)
- Modify: `zeitgeist/store.py:568-606` (`record_stage`, `stages_for_run`)
- Modify: `tests/run_factory.py:88-104` (`make_stage_record`)
- Modify: `web/openapi.json`, `web/src/api/schema.ts` (regenerated)
- Test: `tests/test_store.py`, `tests/test_records.py`

**Interfaces:**
- Consumes: `StageRecord`, `Store.record_stage`, `Store.stages_for_run`,
  `run_factory.make_stage_record` as they stand.
- Produces: `StageRecord.done: int | None`, `StageRecord.total: int | None`;
  `make_stage_record(..., done=None, total=None)`; a `StageRecord` schema in
  `web/src/api/schema.ts` carrying both fields as `number | null`.

- [ ] **Step 1: Write the failing store round-trip test**

Add to `tests/test_store.py`:

```python
def test_record_stage_round_trips_progress_counters(tmp_path):
    """A running stage's counters survive the write and the read.

    The in-flight stage card draws `17 / 25` and a partial bar from these
    two numbers; a column that silently dropped them would leave the card
    rendering a stage that is running with nothing to say about it.
    """
    store = Store(tmp_path / "z.db")
    store.init_schema()
    store.start_run("20260901T120000Z", make_run_config())

    store.record_stage(
        "20260901T120000Z",
        make_stage_record(
            Stage.ANALYSE,
            status="running",
            finished_at=None,
            payload_bytes=None,
            summary="distilling airport-cat",
            done=17,
            total=25,
        ),
    )

    (record,) = store.stages_for_run("20260901T120000Z")
    assert record.status == "running"
    assert record.done == 17
    assert record.total == 25
    store.close()


def test_record_stage_defaults_counters_to_none(tmp_path):
    """Ingest and evaluate count nothing, and say so.

    `None` here is not an unwritten field: those two stages are single
    opaque operations. A zero would claim they had done none of a known
    amount of work.
    """
    store = Store(tmp_path / "z.db")
    store.init_schema()
    store.start_run("20260901T120000Z", make_run_config())

    store.record_stage("20260901T120000Z", make_stage_record(Stage.INGEST))

    (record,) = store.stages_for_run("20260901T120000Z")
    assert record.done is None
    assert record.total is None
    store.close()


def test_record_stage_overwrites_a_running_row_with_its_final_one(tmp_path):
    """`INSERT OR REPLACE` keyed on (run_id, stage): the completed row must
    leave no trace of the counters the running row carried, or a finished
    stage card would draw `17 / 25` beside its duration forever."""
    store = Store(tmp_path / "z.db")
    store.init_schema()
    store.start_run("20260901T120000Z", make_run_config())

    store.record_stage(
        "20260901T120000Z",
        make_stage_record(
            Stage.ANALYSE, status="running", finished_at=None, done=17, total=25
        ),
    )
    store.record_stage(
        "20260901T120000Z",
        make_stage_record(Stage.ANALYSE, status="ok", summary="25 topics distilled"),
    )

    (record,) = store.stages_for_run("20260901T120000Z")
    assert record.status == "ok"
    assert record.done is None
    assert record.total is None
    store.close()
```

Make sure `tests/test_store.py` imports what these need — it already imports
`Store` and `Stage`; add `make_stage_record` and `make_run_config` to its
`tests.run_factory` import if either is missing.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/test_store.py -k progress_counters -v
```

Expected: FAIL with `TypeError: make_stage_record() got an unexpected keyword
argument 'done'`.

- [ ] **Step 3: Add the two fields to `StageRecord`**

In `zeitgeist/records.py`, replace the `StageRecord` class body:

```python
class StageRecord(BaseModel):
    """One stage of one run.

    Every `| None` here is a real state: a queued stage has not started, a
    running one has not finished, and a failed or skipped one wrote no
    checkpoint.

    `done` and `total` are the stage-relative counters the in-flight card
    draws as `17 / 25`, and the partial fill on its top bar. They default
    to None because two of the four stages have nothing to count — ingest
    is one opaque fetch and evaluate one ranking pass — so requiring every
    construction site to spell out `done=None, total=None` would state
    nothing four times over. A running stage that reports no counters
    renders an indeterminate bar rather than a zero-length one.
    """

    model_config = STRICT

    stage: Stage
    status: StageStatus
    started_at: datetime | None
    finished_at: datetime | None
    payload_bytes: int | None
    summary: str
    done: int | None = None
    total: int | None = None
```

- [ ] **Step 4: Add the columns and bump the schema version**

In `zeitgeist/schema.py`, change `SCHEMA_VERSION = 3` to:

```python
SCHEMA_VERSION = 4
```

and replace the `run_stages` table:

```sql
CREATE TABLE IF NOT EXISTS run_stages (
    run_id        TEXT NOT NULL,
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
```

- [ ] **Step 5: Carry the columns through the store**

In `zeitgeist/store.py`, replace `record_stage` and the `stages_for_run`
query:

```python
    def record_stage(self, run_id: str, record: StageRecord) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO run_stages (run_id, stage, status, "
            "started_at, finished_at, payload_bytes, summary, done, total) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                run_id,
                record.stage.value,
                record.status,
                record.started_at.isoformat() if record.started_at else None,
                record.finished_at.isoformat() if record.finished_at else None,
                record.payload_bytes,
                record.summary,
                record.done,
                record.total,
            ),
        )
        self._conn.commit()

    def stages_for_run(self, run_id: str) -> list[StageRecord]:
        """In pipeline order. The four stage cards are drawn in the order the
        stages run, which is not the order their rows were written.
        """
        rows = self._conn.execute(
            "SELECT stage, status, started_at, finished_at, payload_bytes, "
            "summary, done, total FROM run_stages WHERE run_id = ?",
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
                done=row[6],
                total=row[7],
            )
            for row in rows
        ]
        return sorted(records, key=lambda record: ORDER.index(record.stage))
```

- [ ] **Step 6: Teach the factory the two fields**

In `tests/run_factory.py`, replace `make_stage_record`:

```python
def make_stage_record(
    stage: Stage = Stage.INGEST,
    *,
    status: StageStatus = "ok",
    started_at: datetime | None = FIXED_TIME,
    finished_at: datetime | None = FIXED_TIME,
    payload_bytes: int | None = 1024,
    summary: str = "25 trends",
    done: int | None = None,
    total: int | None = None,
) -> StageRecord:
    return StageRecord(
        stage=stage,
        status=status,
        started_at=started_at,
        finished_at=finished_at,
        payload_bytes=payload_bytes,
        summary=summary,
        done=done,
        total=total,
    )
```

- [ ] **Step 7: Run the store tests**

```bash
uv run pytest tests/test_store.py -v
```

Expected: PASS. If an existing test fails on a stale database file, that is
the schema bump doing its job — delete `data/zeitgeist.db`; the suite itself
never touches it (`conftest.py` repoints `DB_PATH` into `tmp_path`).

- [ ] **Step 8: Regenerate the contract, both sides**

```bash
uv run python scripts/dump_openapi.py
```

```bash
npm --prefix web run generate:types
```

- [ ] **Step 9: Run the two drift gates and the full Python suite**

```bash
uv run pytest
```

```bash
npm --prefix web run typecheck
```

Expected: both PASS. `tests/test_openapi_schema.py` proves `openapi.json` is
the app's own; `check-types.mjs` proves `schema.ts` is `openapi.json`'s own.

- [ ] **Step 10: Commit**

```bash
git add zeitgeist/records.py zeitgeist/schema.py zeitgeist/store.py tests/run_factory.py tests/test_store.py web/openapi.json web/src/api/schema.ts
git commit -m "feat: StageRecord carries stage-relative progress counters"
```

---

### Task 2: the runner writes what it watches

`_StageTracker` becomes `_RunRecorder`: it still remembers the last stage
started, because `RunError.stage` depends on it, and it now writes a
`running` `StageRecord` when a stage begins and rewrites it with counters as
the stage reports progress.

The observer runs on the worker thread, so it uses the worker's own `Store`
— the one `_run_one` already holds. It must never raise: `RunObserver`'s
docstring says a run must not fail because something watching it did, and a
locked database or a closed connection is exactly the kind of thing that
would otherwise take a run down at its last stage.

**Files:**
- Modify: `zeitgeist/runner.py:145-162` (`_StageTracker` → `_RunRecorder`),
  `runner.py:428` (its construction)
- Test: `tests/test_runner.py`

**Interfaces:**
- Consumes: `Store.record_stage(run_id, StageRecord)` with `done`/`total`
  from Task 1; `Stage`, `StageRecord` from `zeitgeist.records`;
  `NullObserver` from `zeitgeist.progress`.
- Produces: `_RunRecorder(store: Store, run_id: str)` with
  `last_stage: Stage | None`, satisfying `RunObserver`. Nothing outside
  `runner.py` imports it; `RunService._run_one` is its only construction
  site.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_runner.py`:

```python
def test_a_running_stage_gets_a_row_while_it_is_still_running(tmp_path):
    """Without this, `GET /api/runs/{id}` during a run reports only the
    stages that already finished, and the in-flight screen has no way to say
    which stage is live except by guessing from the gap."""
    seen: list[list[StageRecord]] = []

    def execute(settings, request, store, observer, token) -> None:
        observer.stage_started(Stage.ANALYSE)
        seen.append(store.stages_for_run(request.run_id or ""))

    service = _service(tmp_path, execute=execute)
    _run_to_completion(service, RunRequest())

    (during,) = seen
    assert [record.stage for record in during] == [Stage.ANALYSE]
    assert during[0].status == "running"
    assert during[0].started_at is not None
    assert during[0].finished_at is None


def test_stage_progress_updates_the_running_row_in_place(tmp_path):
    """One row per (run_id, stage), rewritten — not a row per tick. Twenty
    five distilled topics must not leave twenty five analyse rows for
    `stages_for_run` to sort."""
    seen: list[list[StageRecord]] = []

    def execute(settings, request, store, observer, token) -> None:
        observer.stage_started(Stage.ANALYSE)
        observer.stage_progress(Stage.ANALYSE, done=1, total=25, detail="cat")
        observer.stage_progress(Stage.ANALYSE, done=17, total=25, detail="rat")
        seen.append(store.stages_for_run(request.run_id or ""))

    service = _service(tmp_path, execute=execute)
    _run_to_completion(service, RunRequest())

    (during,) = seen
    assert len(during) == 1
    assert during[0].done == 17
    assert during[0].total == 25
    assert during[0].summary == "rat"


def test_progress_keeps_the_started_at_the_stage_began_with(tmp_path):
    """The in-flight card shows how long the *stage* has been running. A
    progress write that reset `started_at` to now would make that read zero
    on every tick."""
    seen: list[list[StageRecord]] = []

    def execute(settings, request, store, observer, token) -> None:
        observer.stage_started(Stage.ANALYSE)
        first = store.stages_for_run(request.run_id or "")[0].started_at
        observer.stage_progress(Stage.ANALYSE, done=3, total=25, detail="cat")
        seen.append([first, store.stages_for_run(request.run_id or "")[0].started_at])

    service = _service(tmp_path, execute=execute)
    _run_to_completion(service, RunRequest())

    (at_start, at_progress) = seen[0]
    assert at_start == at_progress


def test_a_store_failure_in_the_observer_never_fails_the_run(tmp_path):
    """`RunObserver`'s contract: a run must not fail because something
    watching it did. A closed connection under the observer is the realistic
    version of that — it must cost the progress display, not the run."""
    reached_the_end = []

    def execute(settings, request, store, observer, token) -> None:
        store.close()
        observer.stage_started(Stage.ANALYSE)
        observer.stage_progress(Stage.ANALYSE, done=1, total=2, detail="cat")
        reached_the_end.append(True)

    service = _service(tmp_path, execute=execute)
    _run_to_completion(service, RunRequest())

    assert reached_the_end == [True]
```

**`last_stage` gets no new test.** `tests/test_runner.py:682`
(`test_a_run_failing_after_a_later_stage_is_recorded_with_that_stage`)
already drives a run that starts at ingest, reports entering generate, and
raises, asserting `record.error.stage == Stage.GENERATE` against exactly the
code path this task renames. Any mutation that breaks `last_stage` in
`_RunRecorder` turns that test red first, and a second test of the same
behaviour would add a maintenance burden rather than a guard.

These reuse `test_runner.py`'s existing helpers. If that module does not
already have `_service`, `_run_to_completion` and `_db_path`, add them at the
top of the file:

```python
def _db_path(tmp_path: Path) -> Path:
    return tmp_path / "runner.db"


def _service(tmp_path: Path, *, execute: ExecuteFn) -> RunService:
    """A service whose API-side store and worker store are separate objects,
    as they are in the app: `sqlite3` connections are thread-bound."""
    settings = Settings(_env_file=None, db_path=_db_path(tmp_path))
    store = Store(settings.db_path)
    store.init_schema()
    return RunService(settings, store, execute=execute)


def _run_to_completion(service: RunService, request: RunRequest) -> str:
    """Enqueue, let the worker finish, and hand back the run id.

    `shutdown` puts a sentinel behind the request on the same FIFO queue, so
    joining the worker is what waits for the run — no sleeping, no polling.
    """
    service.start()
    queued = service.enqueue(request)
    service.shutdown(timeout=10.0)
    return queued.run_id
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/test_runner.py -k "running_stage or stage_progress or observer" -v
```

Expected: FAIL — `assert [] == [Stage.ANALYSE]`, because `_StageTracker`
writes nothing.

- [ ] **Step 3: Replace `_StageTracker` with `_RunRecorder`**

In `zeitgeist/runner.py`, replace the `_StageTracker` class:

```python
class _RunRecorder(NullObserver):
    """Writes a stage's progress as it happens, and remembers where the run
    got to.

    Two jobs in one observer because both are the worker's own bookkeeping
    and both key on the same events. The remembering half is what
    `_StageTracker` used to do alone: `RunError.stage` must name where a run
    *died*, not where it *started*, and `request.start_at` is the latter.

    The writing half exists because `pipeline._stage()` records a stage only
    when it ends, always as `ok`. Nothing else ever writes a `running` row,
    so without this the in-flight screens can see which stages have finished
    and nothing about the one happening now.

    Subclasses `NullObserver` rather than proxying with `__getattr__`
    because `ty` will not accept a `__getattr__` proxy as a `RunObserver`.
    The two events this does not implement — `topic_distilled` and
    `render_finished` — are inherited as no-ops deliberately: persisting a
    topic mid-analyse needs a rank it does not have yet (see the phase 6
    plan, "Decisions", 2), and a finished render already writes its own row.

    Every store call is guarded. A `RunObserver` may not raise, and a
    locked or closed database is exactly the kind of thing that would
    otherwise take a run down at its last stage — costing the run rather
    than the progress display.
    """

    def __init__(self, store: Store, run_id: str) -> None:
        self._store = store
        self._run_id = run_id
        self._started_at: dict[Stage, datetime] = {}
        self.last_stage: Stage | None = None

    def stage_started(self, stage: Stage) -> None:
        self.last_stage = stage
        self._started_at[stage] = datetime.now(UTC)
        self._write(stage, summary=stage.value, done=None, total=None)

    def stage_progress(self, stage: Stage, done: int, total: int, detail: str) -> None:
        # `started_at` comes from the dict rather than from now, so the
        # in-flight card's "how long has this stage been running" does not
        # reset to zero on every tick. A progress event for a stage that
        # never announced itself falls back to now, which is the only
        # honest answer available.
        self._write(stage, summary=detail, done=done, total=total)

    def _write(
        self, stage: Stage, *, summary: str, done: int | None, total: int | None
    ) -> None:
        started = self._started_at.setdefault(stage, datetime.now(UTC))
        try:
            self._store.record_stage(
                self._run_id,
                StageRecord(
                    stage=stage,
                    status="running",
                    started_at=started,
                    finished_at=None,
                    payload_bytes=None,
                    summary=summary,
                    done=done,
                    total=total,
                ),
            )
        except Exception:  # noqa: BLE001 - an observer may not fail a run
            log.debug("Could not record progress for %s", stage, exc_info=True)
```

Add the imports this needs at the top of `runner.py`:

```python
from datetime import UTC, datetime
```

and extend the `zeitgeist.records` import to include `StageRecord`:

```python
from zeitgeist.records import RunConfig, RunError, Stage, StageRecord
```

- [ ] **Step 4: Construct it in `_run_one`**

In `zeitgeist/runner.py`, inside `_run_one`, replace:

```python
        stage_tracker = _StageTracker()
```

with:

```python
        # Built with the worker's own store, not the API's: `sqlite3`
        # connections are thread-bound and this one is written from the
        # worker thread for the whole run.
        recorder = _RunRecorder(store, run_id)
```

Then replace the two remaining uses in the same method:

```python
                self._execute(settings, request, store, recorder, token)
```

and, in the `except Exception` branch:

```python
                    stage=recorder.last_stage or request.start_at,
```

- [ ] **Step 5: Run the runner tests**

```bash
uv run pytest tests/test_runner.py -v
```

Expected: PASS, including the pre-existing tests that covered
`_StageTracker`'s `last_stage` behaviour.

- [ ] **Step 6: Run the full Python gate**

```bash
uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest
```

Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add zeitgeist/runner.py tests/test_runner.py
git commit -m "feat: the runner records a stage while it is still running"
```

---

### Task 3: the analyse stage reports progress

`observer.stage_progress` is emitted once, from `_render_all`. Analyse — the
stage that dominates a run's wall clock and the one 5a is a screenshot of —
emits nothing. `distil_topics` already takes an `on_topic` callback that
fires per topic, so this is a counting wrapper around the callback the
pipeline already passes, and no change to `distil.py` at all.

**Files:**
- Modify: `zeitgeist/pipeline.py:183-207` (the analyse branch)
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: `distil_topics(..., on_topic=Callable[[Topic], None])`
  (`analysis/distil.py:139`); `RunObserver.stage_progress(stage, done,
  total, detail)`; `RecordingObserver` from `zeitgeist.progress`.
- Produces: no new names. `stage_progress` now fires `len(evidence)` times
  for `Stage.ANALYSE` with `done` counting up from 1 and `total` equal to
  the number of trends fetched.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_pipeline.py`:

```python
def test_analyse_counts_progress_against_the_trends_it_was_given(tmp_path):
    """`17 / 25` on the in-flight analyse card comes from here, and nowhere
    else.

    Two trends, the second of which fails distillation and is dropped:
    `total` must stay at the trend count and `done` must stop at 1. A
    fixture where every trend yields a topic cannot tell `len(evidence)`
    from `len(topics)`, and those two disagree on exactly the run where
    this counter's honesty matters.
    """
    observer = RecordingObserver()

    run_pipeline(
        *_full_run_args(
            tmp_path,
            source=_FakeTrendSource([_evidence("A trend"), _evidence("B trend")]),
            provider=FakeLLMProvider(
                responses=[_draft(), LLMError("model refused"), _choice()]
            ),
        ),
        observer=observer,
    )

    analyse = [
        event
        for event in observer.named("stage_progress")
        if event.payload[0] is Stage.ANALYSE
    ]
    assert [(event.payload[1], event.payload[2]) for event in analyse] == [(1, 2)]


def test_analyse_progress_names_the_topic_it_just_finished(tmp_path):
    """The summary line on the running card is this `detail`, and it is the
    topic's label. A topic id would be honest but unreadable — and a type
    assertion would pass for the id, for the stage name, or for any other
    non-empty string the wrapper happened to send.
    """
    observer = RecordingObserver()

    run_pipeline(
        *_full_run_args(
            tmp_path, source=_FakeTrendSource([_evidence("Airport cat")])
        ),
        observer=observer,
    )

    (event,) = [
        event
        for event in observer.named("stage_progress")
        if event.payload[0] is Stage.ANALYSE
    ]
    assert event.payload[3] == "Airport cat"


def test_analyse_progress_arrives_during_the_stage_not_after_it(tmp_path):
    """A wrapper that collected its events and flushed them once
    `distil_topics` returned would satisfy every count assertion above while
    leaving the card at `0 / 25` for the several minutes analyse takes. The
    events' position in the stream is the only thing that tells the two
    apart, so this asserts the interleaving rather than the values.
    """
    observer = RecordingObserver()

    run_pipeline(
        *_full_run_args(
            tmp_path,
            source=_FakeTrendSource([_evidence("A trend"), _evidence("B trend")]),
            provider=FakeLLMProvider(responses=[_draft(), _draft(), _choice()]),
        ),
        observer=observer,
    )

    sequence = [
        event.name
        for event in observer.events
        if event.name == "topic_distilled"
        or (
            event.name in {"stage_progress", "stage_finished"}
            and event.payload[0] is Stage.ANALYSE
        )
    ]
    assert sequence == [
        "topic_distilled",
        "stage_progress",
        "topic_distilled",
        "stage_progress",
        "stage_finished",
    ]


def test_topic_distilled_still_fires_once_per_topic(tmp_path):
    """The wrapper must not swallow or double the callback it wraps: the
    spec's own testing section calls this out as the thing to assert."""
    observer = RecordingObserver()

    run_pipeline(
        *_full_run_args(
            tmp_path,
            source=_FakeTrendSource([_evidence("A trend"), _evidence("B trend")]),
            provider=FakeLLMProvider(responses=[_draft(), _draft(), _choice()]),
        ),
        observer=observer,
    )

    assert len(observer.named("topic_distilled")) == 2
```

These use `tests/test_pipeline.py`'s own helpers — `_full_run_args`,
`_FakeTrendSource`, `_evidence`, `_draft`, `_choice` — rather than a new
one. `_full_run_args(tmp_path, **overrides)` returns the five positional
arguments `run_pipeline` takes, and `LLMError` is already imported in that
module (`test_pipeline.py:12`). A queued `Exception` in `FakeLLMProvider` is
raised rather than returned (`llm/base.py:94`), which is how the dropped
trend in the first test is produced; `distil_topics` counts that trend as a
failure and never calls `on_topic` for it (`distil.py:175`).

The first test's two distil calls run on a `ThreadPoolExecutor`, so which
trend receives the `LLMError` is not fixed — but exactly one topic survives
either way, so `(1, 2)` holds regardless. The third test's ordering
assertion is safe for the same reason `test_topics_are_reported_during_
analyse_not_after_it` (`test_pipeline.py:679`) is: `distil_topics` calls
`on_topic` while iterating `pool.map`'s results on the calling thread, in
evidence order.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/test_pipeline.py -k analyse_counts_progress -v
```

Expected: FAIL with `assert [] == [1, 2]`.

- [ ] **Step 3: Emit progress from the analyse branch**

In `zeitgeist/pipeline.py`, replace the `distil_topics` call inside the
analyse branch:

```python
        observer.stage_started(Stage.ANALYSE)
        started = datetime.now(UTC)
        distilled = 0

        def _distilled(topic: Topic) -> None:
            """Count, tell the observer, then pass the topic on.

            No lock: `distil_topics` runs its pool with `pool.map` and calls
            `on_topic` while iterating the results on *this* thread, so the
            increment is single-threaded even though the model calls behind
            it were not.

            `total` is the trend count rather than the topic count, because
            a trend whose distillation fails is dropped — so `done` can end
            below `total`, which is the truth about that run and not an
            off-by-one.
            """
            nonlocal distilled
            distilled += 1
            observer.topic_distilled(topic)
            observer.stage_progress(
                Stage.ANALYSE,
                done=distilled,
                total=len(evidence),
                detail=topic.label,
            )

        topics = distil_topics(
            evidence,
            provider,
            settings,
            on_topic=_distilled,
            token=token,
        )
```

Everything after that line — `score_topics`, the log line, the checkpoint
write, `_stage`, `observer.stage_finished` — is unchanged.

Check `Topic` is imported in `pipeline.py`; if it is not, add it to the
`zeitgeist.models` import.

- [ ] **Step 4: Run the tests to verify they pass**

```bash
uv run pytest tests/test_pipeline.py -v
```

Expected: PASS.

- [ ] **Step 5: Run the full Python gate**

```bash
uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest
```

Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add zeitgeist/pipeline.py tests/test_pipeline.py
git commit -m "feat: the analyse stage reports progress per distilled topic"
```

---

### Task 4: the mutation client, the live hooks, and the test doubles

Everything later tasks fetch through, in one place, so a key cannot drift
from the fetch that uses it. Phase 5 left `queries.ts` with six read hooks
and a comment saying the live ones are phase 6's; this is that.

The event stream is opened through an injectable factory rather than
`new EventSource(...)` directly. jsdom implements `EventSource` and MSW does
not intercept it, so a test that mounted a live screen would open a real
connection to nothing; making the transport a seam means the fake is
installed once in `setup.ts` and no test can reach the network by
forgetting.

**Files:**
- Modify: `web/src/api/client.ts`
- Modify: `web/src/api/types.ts`
- Modify: `web/src/api/queries.ts`
- Modify: `web/src/format.ts`
- Modify: `web/src/styles/tokens.css`
- Modify: `web/src/test/factories.ts`
- Modify: `web/src/test/setup.ts`
- Create: `web/src/test/eventsource.ts`
- Test: `web/src/api/client.test.ts`, `web/src/api/queries.test.tsx`,
  `web/src/format.test.ts`

**Interfaces:**
- Consumes: `apiGet`, `ApiError`, `detailOf` (module-private) from
  `client.ts`; `queryKeys` and the six read hooks from `queries.ts`; the
  generated `components["schemas"]` from Task 1's regenerated `schema.ts`.
- Produces:
  - `client.ts`: `apiSend<T>(method: "POST" | "PUT", path: string, body?: unknown): Promise<T>`;
    `openRunEvents(runId: string): RunEventSource`;
    `parseLogEvent(data: string): LogLine[]`;
    `setEventSourceFactory(factory: (url: string) => RunEventSource): void`;
    `type RunEventSource = EventTarget & { close(): void }`.
  - `types.ts`: `ActiveRuns`, `QueuedRun`, `RunActionAck`, `StartRunBody`,
    `ResumeBody`, `ConfigOptions`, `PlatformOption`, `TemplateOption`,
    `SettingsUpdate`, `SettingSource`.
  - `queries.ts`: `queryKeys.active()`, `.log()`, `.configOptions()`,
    `.settings()`; `useActiveRun()`, `useRunLog(runId, verbose, enabled)`,
    `useConfigOptions()`, `useSettings()`, `useRunEvents(runId, enabled)`,
    `useStartRun()`, `useResumeRun(runId)`, `useStopRun(runId)`,
    `useAbortRun(runId)`, `useSaveSettings()`; `ACTIVE_POLL_MS`,
    `TICK_INVALIDATE_MS`, `MAX_LOG_LINES`.
  - `format.ts`: `formatElapsed(startedAt: string, now?: Date): string`.
  - `factories.ts`: `makeActiveRuns`, `makeQueuedRun`, `makeConfigOptions`,
    `makeSettingField`, `makeSettingFields`, `makeLogLine`.
  - `eventsource.ts`: `FakeEventSource` with `instances`, `reset()`,
    `latest()`, `emitLog(lines)`, `emitTick()`, `closed`.

- [ ] **Step 1: Write the failing tests**

Add to `web/src/format.test.ts`:

```ts
describe("formatElapsed", () => {
  it("counts up from the start in minutes and seconds", () => {
    expect(
      formatElapsed("2026-08-29T09:00:00Z", new Date("2026-08-29T09:06:41Z")),
    ).toBe("t+06:41");
  });

  it("keeps counting in minutes past an hour", () => {
    // Not wrapped into hours on purpose: the whole job of this display is
    // "how long has this been going", and `t+72:15` answers that faster
    // than `t+1:12:15` does.
    expect(
      formatElapsed("2026-08-29T09:00:00Z", new Date("2026-08-29T10:12:15Z")),
    ).toBe("t+72:15");
  });

  it("never counts backwards from a clock that is behind the server", () => {
    expect(
      formatElapsed("2026-08-29T09:00:00Z", new Date("2026-08-29T08:59:00Z")),
    ).toBe("t+00:00");
  });
});
```

Add to `web/src/api/client.test.ts`:

```ts
describe("apiSend", () => {
  it("sends a JSON body and returns the parsed reply", async () => {
    let seen: unknown = null;
    server.use(
      http.post("/api/runs", async ({ request }) => {
        seen = await request.json();
        return HttpResponse.json(makeQueuedRun({ runId: "r1", position: 0 }), {
          status: 202,
        });
      }),
    );

    const queued = await apiSend<QueuedRun>("POST", "/api/runs", {
      template_ids: null,
      overrides: { topic_count: "3" },
    });

    expect(seen).toEqual({ template_ids: null, overrides: { topic_count: "3" } });
    expect(queued.run_id).toBe("r1");
  });

  it("raises an ApiError carrying the server's own detail", async () => {
    // The 409 the resume endpoint answers with when a run wrote no
    // checkpoints. The screen prints this sentence verbatim, so losing it
    // would leave the user with a status code and no explanation.
    server.use(
      http.post("/api/runs/r1/resume", () =>
        HttpResponse.json({ detail: "Run r1 wrote no checkpoints" }, { status: 409 }),
      ),
    );

    await expect(apiSend("POST", "/api/runs/r1/resume", {})).rejects.toMatchObject({
      status: 409,
      detail: "Run r1 wrote no checkpoints",
    });
  });
});

describe("parseLogEvent", () => {
  it("reads the array of lines an SSE log event carries", () => {
    const line = makeLogLine({ seq: 4, message: "Fetched 25 trends" });
    expect(parseLogEvent(JSON.stringify([line]))).toEqual([line]);
  });

  it("yields nothing for a truncated frame rather than throwing", () => {
    // A stream can be cut mid-frame by a server restart. A parse error
    // there must cost one batch of log lines, never the screen.
    expect(parseLogEvent('[{"seq": 1,')).toEqual([]);
  });

  it("yields nothing for a frame that is not an array of lines", () => {
    // The one guard the truncated-frame test does not reach: replace the
    // body with a bare `JSON.parse(...) as LogLine[]` and that test still
    // passes. `LiveLog` maps over whatever this returns, so a well-formed
    // object frame must cost a batch of lines rather than the screen.
    expect(parseLogEvent('{"detail": "run not found"}')).toEqual([]);
    expect(parseLogEvent("null")).toEqual([]);
  });
});
```

Add to `web/src/api/queries.test.tsx`:

```ts
describe("useActiveRun", () => {
  it("does not poll while nothing is running", async () => {
    let calls = 0;
    server.use(
      http.get("/api/runs/active", () => {
        calls += 1;
        return HttpResponse.json(makeActiveRuns({ current: null }));
      }),
    );

    const { result } = renderHook(() => useActiveRun(), {
      wrapper: renderWithProviders.Wrapper,
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    await new Promise((resolve) => setTimeout(resolve, ACTIVE_POLL_MS + 200));
    expect(calls).toBe(1);
  });

  it("polls while a run is in flight", async () => {
    let calls = 0;
    server.use(
      http.get("/api/runs/active", () => {
        calls += 1;
        return HttpResponse.json(makeActiveRuns({ current: "r1" }));
      }),
    );

    const { result } = renderHook(() => useActiveRun(), {
      wrapper: renderWithProviders.Wrapper,
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    await waitFor(() => expect(calls).toBeGreaterThan(1), {
      timeout: ACTIVE_POLL_MS * 3,
    });
  });
});

describe("useRunEvents", () => {
  it("accumulates the lines the stream sends", async () => {
    const { result } = renderHook(() => useRunEvents("r1", true), {
      wrapper: renderWithProviders.Wrapper,
    });

    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));
    act(() => {
      FakeEventSource.latest().emitLog([makeLogLine({ seq: 1, message: "one" })]);
      FakeEventSource.latest().emitLog([makeLogLine({ seq: 2, message: "two" })]);
    });

    await waitFor(() => expect(result.current).toHaveLength(2));
    expect(result.current.map((line) => line.message)).toEqual(["one", "two"]);
  });

  it("keeps only the most recent lines once the cap is reached", async () => {
    // A DEBUG run logs per distilled topic and per rendered meme; the DOM
    // would otherwise grow for as long as the run does.
    const { result } = renderHook(() => useRunEvents("r1", true), {
      wrapper: renderWithProviders.Wrapper,
    });
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));

    const flood = Array.from({ length: MAX_LOG_LINES + 5 }, (_, index) =>
      makeLogLine({ seq: index, message: `line ${index}` }),
    );
    act(() => FakeEventSource.latest().emitLog(flood));

    await waitFor(() => expect(result.current).toHaveLength(MAX_LOG_LINES));
    expect(result.current[0].message).toBe("line 5");
  });

  it("opens the run's own stream and refreshes it on a tick, at most once a second", async () => {
    // Half of this hook is the tick handler, and nothing else in the plan
    // calls `emitTick`. Delete the listener, or drop the throttle so all
    // four ticks a second refetch run detail, and no other test notices.
    // The URL is asserted here for the same reason: a wrong path delivers
    // no events at all, silently.
    let detailCalls = 0;
    server.use(
      http.get("/api/runs/r1", () => {
        detailCalls += 1;
        return HttpResponse.json(makeRunDetail({ runId: "r1", status: "running" }));
      }),
    );

    const { result } = renderHook(
      () => ({ run: useRun("r1"), lines: useRunEvents("r1", true) }),
      { wrapper: renderWithProviders.Wrapper },
    );
    await waitFor(() => expect(result.current.run.isSuccess).toBe(true));
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));
    expect(FakeEventSource.latest().url).toBe("/api/runs/r1/events");

    act(() => {
      FakeEventSource.latest().emitTick();
      FakeEventSource.latest().emitTick();
      FakeEventSource.latest().emitTick();
    });

    // One refetch for the burst, not three: the stream ticks four times a
    // second and the rows behind it change once a stage.
    await waitFor(() => expect(detailCalls).toBe(2));
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(detailCalls).toBe(2);
  });

  it("opens no stream, and closes an open one, when it is not enabled", async () => {
    const { rerender } = renderHook(
      ({ live }: { live: boolean }) => useRunEvents("r1", live),
      { wrapper: renderWithProviders.Wrapper, initialProps: { live: true } },
    );
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));

    rerender({ live: false });

    await waitFor(() => expect(FakeEventSource.latest().closed).toBe(true));
    expect(FakeEventSource.instances).toHaveLength(1);
  });
});

describe("the run mutations", () => {
  it("abort posts to the run and refreshes what is active", async () => {
    let aborted = "";
    let activeCalls = 0;
    server.use(
      http.post("/api/runs/:runId/abort", ({ params }) => {
        aborted = String(params.runId);
        return HttpResponse.json({ run_id: aborted, requested: "abort" }, { status: 202 });
      }),
      http.get("/api/runs/active", () => {
        activeCalls += 1;
        return HttpResponse.json(makeActiveRuns({ current: null }));
      }),
    );

    const { result } = renderHook(
      () => ({ active: useActiveRun(), abort: useAbortRun("r1") }),
      { wrapper: renderWithProviders.Wrapper },
    );
    await waitFor(() => expect(result.current.active.isSuccess).toBe(true));

    await act(async () => {
      await result.current.abort.mutateAsync();
    });

    expect(aborted).toBe("r1");
    await waitFor(() => expect(activeCalls).toBeGreaterThan(1));
  });

  it("saving settings writes the reply straight into the cache", async () => {
    // PUT /api/settings returns the same shape as the GET, on purpose, so
    // the source chips re-render from the reply rather than from a second
    // request. A refetch here would be a wasted round trip and a visible
    // flicker on the chip that just changed.
    let getCalls = 0;
    server.use(
      http.get("/api/settings", () => {
        getCalls += 1;
        return HttpResponse.json(makeSettingFields());
      }),
      http.put("/api/settings", () =>
        HttpResponse.json([
          makeSettingField({ key: "phrase_min_authors", value: 9, source: "settings" }),
        ]),
      ),
    );

    const { result } = renderHook(
      () => ({ settings: useSettings(), save: useSaveSettings() }),
      { wrapper: renderWithProviders.Wrapper },
    );
    await waitFor(() => expect(result.current.settings.isSuccess).toBe(true));

    await act(async () => {
      await result.current.save.mutateAsync({ values: { phrase_min_authors: "9" } });
    });

    await waitFor(() => expect(result.current.settings.data).toHaveLength(1));
    expect(result.current.settings.data?.[0].value).toBe(9);
    expect(getCalls).toBe(1);
  });
});
```

Both test modules need their imports extended — `act`, `renderHook`,
`waitFor` from `@testing-library/react`, `http`/`HttpResponse` from `msw`,
`FakeEventSource` from `@/test/eventsource`, the new hooks (`useActiveRun`,
`useRun`, `useRunEvents`, `useSettings`, `useSaveSettings`, `useAbortRun`)
and constants (`ACTIVE_POLL_MS`, `MAX_LOG_LINES`) from `@/api/queries`,
`apiSend` and `parseLogEvent` from `@/api/client`, and the factories
(`makeActiveRuns`, `makeQueuedRun`, `makeLogLine`, `makeRunDetail`,
`makeSettingField`, `makeSettingFields`) from `@/test/factories`.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
npm --prefix web test -- --run src/api src/format.test.ts
```

Expected: FAIL — `apiSend is not exported`, `formatElapsed is not a
function`.

- [ ] **Step 3: Add the three tokens**

In `web/src/styles/tokens.css`, add beside the existing accent and contrast
groups, and document each in the file's header comment block the way the
existing extras are:

```css
  --accent-border-soft: rgba(255, 217, 61, 0.2);
```

```css
  --contrast-confirm: rgba(61, 99, 230, 0.1);
  --contrast-border-strong: rgba(61, 99, 230, 0.45);
```

Extend the header comment with:

```
 *   --accent-border-soft   accent 20% — the in-flight card's border, in the
 *                      sidebar and on Runs. Softer than --accent-border
 *                      because the card is a status, not a selection.
 *   --contrast-confirm rgba(61,99,230,.1) — the fill an inline confirm
 *                      swaps to, on the abort button and on phase 7's
 *                      render tile.
 *   --contrast-border-strong rgba(61,99,230,.45) — the Abort button's own
 *                      border, one step up from --contrast-border so a
 *                      destructive action reads as one before it is asked.
```

- [ ] **Step 4: Add `formatElapsed`**

Append to `web/src/format.ts`:

```ts
/**
 * `t+06:41` — how long a run has been going.
 *
 * Minutes are not wrapped into hours. The whole job of this display is
 * answering "how long has this been going", and `t+72:15` answers it
 * faster than `t+1:12:15` does.
 *
 * Clamped at zero: the client's clock and the server's need not agree, and
 * a run that started "in the future" must read `t+00:00` rather than
 * counting down.
 */
export function formatElapsed(startedAt: string, now: Date = new Date()): string {
  const seconds = Math.max(
    0,
    Math.floor((now.getTime() - new Date(startedAt).getTime()) / 1000),
  );
  const minutes = Math.floor(seconds / 60);
  const pad = (value: number) => String(value).padStart(2, "0");
  return `t+${pad(minutes)}:${pad(seconds % 60)}`;
}
```

- [ ] **Step 5: Extend the client**

Append to `web/src/api/client.ts` (and add
`import type { LogLine } from "@/api/types";` at the top):

```ts
export async function apiSend<T>(
  method: "POST" | "PUT",
  path: string,
  body?: unknown,
): Promise<T> {
  const response = await fetch(path, {
    method,
    headers: {
      accept: "application/json",
      ...(body === undefined ? {} : { "content-type": "application/json" }),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    throw new ApiError(response.status, await detailOf(response));
  }
  return (await response.json()) as T;
}

/**
 * What `openRunEvents` hands back.
 *
 * `EventTarget & { close() }` rather than `EventSource` because that is the
 * whole of what this app uses, and narrowing the type is what lets a test
 * substitute a transport without asserting one type onto another.
 */
export type RunEventSource = EventTarget & { close(): void };

let eventSourceFactory: (url: string) => RunEventSource = (url) =>
  new EventSource(url);

/**
 * Swap the transport. Tests call this; nothing in the app does.
 *
 * jsdom implements `EventSource` and MSW does not intercept it, so without
 * a seam here a test that mounted a live screen would open a real
 * connection to a server that is not running. `src/test/setup.ts` installs
 * the fake for every test, so reaching the network is not something a test
 * can do by forgetting.
 */
export function setEventSourceFactory(
  factory: (url: string) => RunEventSource,
): void {
  eventSourceFactory = factory;
}

export function openRunEvents(runId: string): RunEventSource {
  return eventSourceFactory(`/api/runs/${encodeURIComponent(runId)}/events`);
}

/**
 * The lines one `log` frame carries, or none.
 *
 * A stream can be cut mid-frame by a server restart, and a parse error
 * there must cost one batch of log lines rather than the screen watching
 * the run. This is the second and last place the app turns untyped JSON
 * into a contract type, which is why it lives in this file with `apiGet`
 * rather than beside its caller.
 */
export function parseLogEvent(data: string): LogLine[] {
  try {
    const parsed: unknown = JSON.parse(data);
    return Array.isArray(parsed) ? (parsed as LogLine[]) : [];
  } catch {
    return [];
  }
}
```

- [ ] **Step 6: Add the contract aliases**

Append to `web/src/api/types.ts`, beside the existing groups:

```ts
export type ActiveRuns = Schemas["ActiveRuns"];
export type QueuedRun = Schemas["QueuedRun"];
export type RunActionAck = Schemas["RunActionAck"];
export type StartRunBody = Schemas["StartRunBody"];
export type ResumeBody = Schemas["ResumeBody"];
export type SettingsUpdate = Schemas["SettingsUpdate"];
export type SettingSource = SettingField["source"];
export type ConfigOptions = Schemas["ConfigOptions"];
export type PlatformOption = Schemas["PlatformOption"];
export type TemplateOption = Schemas["TemplateOption"];
```

- [ ] **Step 7: Write the fake transport**

Create `web/src/test/eventsource.ts`:

```ts
/**
 * The SSE transport tests drive by hand.
 *
 * `EventTarget` gives it `addEventListener` and `dispatchEvent` for free,
 * which is the whole of the interface `useRunEvents` uses — so this is a
 * real implementation of the seam rather than a mock of one.
 */
import type { LogLine } from "@/api/types";

export class FakeEventSource extends EventTarget {
  static instances: FakeEventSource[] = [];

  closed = false;

  constructor(readonly url: string) {
    super();
    FakeEventSource.instances.push(this);
  }

  close(): void {
    this.closed = true;
  }

  emitLog(lines: LogLine[]): void {
    this.dispatchEvent(new MessageEvent("log", { data: JSON.stringify(lines) }));
  }

  emitTick(seq = 0): void {
    this.dispatchEvent(new MessageEvent("tick", { data: JSON.stringify({ seq }) }));
  }

  static reset(): void {
    FakeEventSource.instances = [];
  }

  /** The stream the component under test just opened. */
  static latest(): FakeEventSource {
    const source = FakeEventSource.instances.at(-1);
    if (source === undefined) {
      throw new Error("No stream was opened");
    }
    return source;
  }
}
```

- [ ] **Step 8: Install it for every test**

In `web/src/test/setup.ts`, add the import and a `beforeEach`:

```ts
import { beforeEach } from "vitest";

import { setEventSourceFactory } from "@/api/client";
import { FakeEventSource } from "@/test/eventsource";

// Installed for every test, not only the ones that assert on a stream: a
// screen that opens one in an effect must not reach the network because
// the test did not think to stub it.
beforeEach(() => {
  FakeEventSource.reset();
  setEventSourceFactory((url) => new FakeEventSource(url));
});
```

- [ ] **Step 9: Add the six factories**

Append to `web/src/test/factories.ts`, extending its type import with
`ActiveRuns`, `ConfigOptions`, `LogLine`, `QueuedRun`, `SettingField`,
`SettingSource`:

```ts
export function makeActiveRuns(
  options: { current?: string | null; queued?: string[] } = {},
): ActiveRuns {
  return {
    current: options.current === undefined ? null : options.current,
    queued: options.queued ?? [],
  };
}

export function makeQueuedRun(
  options: { runId?: string; position?: number } = {},
): QueuedRun {
  return {
    run_id: options.runId ?? "20260829T140200Z",
    position: options.position ?? 0,
  };
}

export function makeLogLine(
  options: {
    seq?: number;
    level?: string;
    logger?: string;
    message?: string;
    loggedAt?: string;
  } = {},
): LogLine {
  return {
    seq: options.seq ?? 1,
    logged_at: options.loggedAt ?? FIXED_START,
    level: options.level ?? "INFO",
    logger: options.logger ?? "zeitgeist.pipeline",
    message: options.message ?? "Fetched 25 trends",
  };
}

export function makeConfigOptions(
  options: {
    models?: Record<string, string[]>;
    platforms?: ConfigOptions["platforms"];
    templates?: ConfigOptions["templates"];
    defaults?: Record<string, string>;
    anthropicKeyPresent?: boolean;
  } = {},
): ConfigOptions {
  return {
    models: options.models ?? {
      anthropic: ["claude-opus-5", "claude-sonnet-5"],
      ollama: ["qwen3.5:latest"],
    },
    platforms: options.platforms ?? [
      { name: "lemmy", enabled: false },
      { name: "wikipedia", enabled: false },
      { name: "bluesky", enabled: true },
    ],
    templates: options.templates ?? [
      { id: "drake", slots: ["rejected", "preferred"] },
      { id: "two_buttons", slots: ["left", "right", "sweating"] },
    ],
    defaults: options.defaults ?? {
      bluesky_fetch_concurrency: "8",
      bluesky_posts_per_trend: "10",
      bluesky_trend_limit: "25",
      distil_char_budget: "24000",
      distil_concurrency: "4",
      llm_model: "claude-sonnet-5",
      llm_provider: "anthropic",
      meme_potential_weight: "0.3",
      phrase_min_authors: "3",
      // The Python repr, because `options.py` builds every default with
      // `str(...)` and `Settings.sources` is a list. The New run screen
      // deliberately ignores this key; the fixture carries it so a screen
      // that started reading it would be tested against what the server
      // really sends.
      sources: "['bluesky']",
      topic_count: "5",
    },
    anthropic_key_present: options.anthropicKeyPresent ?? true,
  };
}

export function makeSettingField(
  options: { key?: string; value?: number; source?: SettingSource } = {},
): SettingField {
  return {
    key: options.key ?? "phrase_min_authors",
    value: options.value ?? 3,
    source: options.source ?? "default",
  };
}

/** All seven, in the order `GET /api/settings` returns them: sorted by key. */
export function makeSettingFields(
  overrides: Partial<Record<string, Partial<SettingField>>> = {},
): SettingField[] {
  const base: SettingField[] = [
    { key: "bluesky_fetch_concurrency", value: 8, source: "default" },
    { key: "bluesky_posts_per_trend", value: 10, source: "default" },
    { key: "bluesky_trend_limit", value: 25, source: "default" },
    { key: "distil_char_budget", value: 24000, source: "default" },
    { key: "distil_concurrency", value: 4, source: "default" },
    { key: "meme_potential_weight", value: 0.3, source: "default" },
    { key: "phrase_min_authors", value: 3, source: "default" },
  ];
  return base.map((field) => ({ ...field, ...(overrides[field.key] ?? {}) }));
}
```

- [ ] **Step 10: Add the hooks**

Replace the header comment of `web/src/api/queries.ts` and append the new
members. The keys first, inside the existing `queryKeys` object:

```ts
  active: () => ["runs", "active"],
  log: (runId: string, verbose: boolean) => ["runs", runId, "log", { verbose }],
  configOptions: () => ["config", "options"],
  settings: () => ["settings"],
```

Then, after the six read hooks:

```ts
/** How often the active-run query re-asks while something is running. */
export const ACTIVE_POLL_MS = 2000;
/**
 * The floor between two tick-driven invalidations.
 *
 * The stream ticks every 250ms (`control.POLL_SECONDS`). Refetching run
 * detail four times a second would spend most of a run re-reading rows that
 * change once a stage, so a tick is a hint to refresh rather than an
 * instruction to.
 */
export const TICK_INVALIDATE_MS = 1000;
/** Lines held in the DOM before the oldest are dropped. */
export const MAX_LOG_LINES = 2000;

/**
 * The in-flight run and the queue — the single source of truth for the
 * sidebar card, the run strip, the Runs in-flight card and New run's queue
 * notice.
 *
 * `refetchInterval` is `false` while nothing is running, so an idle app
 * makes no requests at all. A run started from this app invalidates the
 * query on success, and `refetchOnWindowFocus` (left on in `providers.tsx`)
 * covers coming back to a tab after one was started elsewhere.
 */
export function useActiveRun() {
  return useQuery<ActiveRuns, ApiError>({
    queryKey: queryKeys.active(),
    queryFn: () => apiGet<ActiveRuns>("/api/runs/active"),
    refetchInterval: (query) =>
      query.state.data === undefined || query.state.data.current === null
        ? false
        : ACTIVE_POLL_MS,
    staleTime: 0,
  });
}

/**
 * A finished run's log.
 *
 * `verbose` is a server-side filter here, unlike the live log's, because
 * there is no buffer on the client to filter — the lines come from
 * `log_lines` and the endpoint already knows how to narrow them.
 */
export function useRunLog(
  runId: string | undefined,
  verbose: boolean,
  enabled = true,
) {
  return useQuery<LogLine[], ApiError>({
    queryKey: queryKeys.log(runId ?? "", verbose),
    queryFn: () =>
      apiGet<LogLine[]>(`/api/runs/${encodeURIComponent(runId ?? "")}/log`, {
        verbose,
      }),
    enabled: enabled && runId !== undefined,
  });
}

export function useConfigOptions() {
  return useQuery<ConfigOptions, ApiError>({
    queryKey: queryKeys.configOptions(),
    queryFn: () => apiGet<ConfigOptions>("/api/config/options"),
  });
}

export function useSettings() {
  return useQuery<SettingField[], ApiError>({
    queryKey: queryKeys.settings(),
    queryFn: () => apiGet<SettingField[]>("/api/settings"),
  });
}

/**
 * Everything under `["runs", ...]`: the list, every detail, every ranking,
 * and `active`. One invalidation rather than four, because every mutation
 * here can change all of them — a started run is a new row, a new active
 * run, and a page whose counts moved.
 */
function useRunsInvalidator() {
  const client = useQueryClient();
  return () => {
    void client.invalidateQueries({ queryKey: ["runs"] });
  };
}

export function useStartRun() {
  const invalidate = useRunsInvalidator();
  return useMutation<QueuedRun, ApiError, StartRunBody>({
    mutationFn: (body) => apiSend<QueuedRun>("POST", "/api/runs", body),
    onSuccess: invalidate,
  });
}

export function useResumeRun(runId: string) {
  const invalidate = useRunsInvalidator();
  return useMutation<QueuedRun, ApiError, ResumeBody>({
    mutationFn: (body) =>
      apiSend<QueuedRun>("POST", `/api/runs/${encodeURIComponent(runId)}/resume`, body),
    onSuccess: invalidate,
  });
}

export function useStopRun(runId: string) {
  const invalidate = useRunsInvalidator();
  return useMutation<RunActionAck, ApiError, void>({
    mutationFn: () =>
      apiSend<RunActionAck>("POST", `/api/runs/${encodeURIComponent(runId)}/stop`),
    onSuccess: invalidate,
  });
}

export function useAbortRun(runId: string) {
  const invalidate = useRunsInvalidator();
  return useMutation<RunActionAck, ApiError, void>({
    mutationFn: () =>
      apiSend<RunActionAck>("POST", `/api/runs/${encodeURIComponent(runId)}/abort`),
    onSuccess: invalidate,
  });
}

/**
 * `PUT /api/settings` answers with the same shape as the `GET`, so the
 * reply goes straight into the cache. A refetch instead would be a wasted
 * round trip and a visible flicker on the very chip that just changed.
 */
export function useSaveSettings() {
  const client = useQueryClient();
  return useMutation<SettingField[], ApiError, SettingsUpdate>({
    mutationFn: (body) => apiSend<SettingField[]>("PUT", "/api/settings", body),
    onSuccess: (fields) => client.setQueryData(queryKeys.settings(), fields),
  });
}

/**
 * The run's live log, and the nudge that keeps the rest of the screen
 * current.
 *
 * Lines accumulate in local state rather than in the query cache: they
 * arrive as a stream of appends, and a cache entry rewritten on every frame
 * would invalidate every consumer of it on every frame.
 *
 * Incoming lines are batched to an animation frame. A DEBUG run emits a
 * line per distilled topic from a thread pool, so appending one at a time
 * would re-render the log once per line.
 */
export function useRunEvents(runId: string | undefined, enabled: boolean) {
  const client = useQueryClient();
  const [lines, setLines] = useState<LogLine[]>([]);
  const pending = useRef<LogLine[]>([]);
  const frame = useRef<number | null>(null);
  const lastInvalidated = useRef(0);

  useEffect(() => {
    if (runId === undefined || !enabled) return;
    setLines([]);
    const source = openRunEvents(runId);

    const flush = () => {
      frame.current = null;
      const batch = pending.current;
      pending.current = [];
      if (batch.length === 0) return;
      setLines((held) => {
        const next = [...held, ...batch];
        return next.length > MAX_LOG_LINES
          ? next.slice(next.length - MAX_LOG_LINES)
          : next;
      });
    };

    const onLog = (event: Event) => {
      pending.current = [...pending.current, ...parseLogEvent(eventData(event))];
      if (frame.current === null) {
        frame.current = requestAnimationFrame(flush);
      }
    };

    const onTick = () => {
      const now = Date.now();
      if (now - lastInvalidated.current < TICK_INVALIDATE_MS) return;
      lastInvalidated.current = now;
      void client.invalidateQueries({ queryKey: ["runs"] });
    };

    source.addEventListener("log", onLog);
    source.addEventListener("tick", onTick);
    return () => {
      source.removeEventListener("log", onLog);
      source.removeEventListener("tick", onTick);
      source.close();
      if (frame.current !== null) cancelAnimationFrame(frame.current);
      frame.current = null;
      pending.current = [];
    };
  }, [runId, enabled, client]);

  return lines;
}

/**
 * An SSE frame's payload.
 *
 * `addEventListener` on a name outside `EventSourceEventMap` is typed with
 * a plain `Event`, so the narrowing is real rather than ceremonial — and it
 * is a narrowing, not an assertion, which is what keeps this out of
 * `client.ts`.
 */
function eventData(event: Event): string {
  return event instanceof MessageEvent && typeof event.data === "string"
    ? event.data
    : "";
}
```

Extend the module's imports:

```ts
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { apiGet, apiSend, openRunEvents, parseLogEvent } from "@/api/client";
import type {
  ActiveRuns,
  ConfigOptions,
  LogLine,
  QueuedRun,
  RankedTopic,
  RenderRecord,
  ResumeBody,
  RunActionAck,
  RunDetail,
  RunPage,
  SettingField,
  SettingsUpdate,
  StartRunBody,
  TopicDetail,
  TopicIndex,
  TrendStatus,
} from "@/api/types";
```

and update its header comment: the six read hooks are now sixteen members,
and the sentence saying the live hooks are phase 6's is no longer true.

- [ ] **Step 11: Run the tests to verify they pass**

```bash
npm --prefix web test -- --run src/api src/format.test.ts
```

Expected: PASS.

- [ ] **Step 12: Run the whole web gate**

```bash
npm --prefix web run lint && npm --prefix web run typecheck && npm --prefix web test
```

Expected: all PASS. If `no-raw-colours` fails, a token was added to a
`.module.css` rather than to `tokens.css`.

- [ ] **Step 13: Commit**

```bash
git add web/src/api web/src/format.ts web/src/format.test.ts web/src/styles/tokens.css web/src/test
git commit -m "feat: the mutation client, the live hooks and the SSE transport seam"
```

---

### Task 5: `InlineConfirm`

The swap-in-place confirmation, shared because it is a pattern rather than a
one-off: the Abort button here, the render tile's delete and the meme view's
delete in phase 7. No modals, per the handoff.

**Files:**
- Create: `web/src/components/InlineConfirm.tsx`,
  `web/src/components/InlineConfirm.module.css`
- Test: `web/src/components/InlineConfirm.test.tsx`

**Interfaces:**
- Consumes: `tokens.css`'s `--contrast-confirm`, `--contrast-border`,
  `--contrast-light`, `--border-strong`, `--transition` from Task 4.
- Produces: `InlineConfirm({ label, question, onConfirm, className }):
  JSX.Element`, where `label` is the resting button text, `question` the
  text shown while asking, and `className` an optional class the caller
  gives the resting button so a screen can size it like its neighbours.

- [ ] **Step 1: Write the failing test**

Create `web/src/components/InlineConfirm.test.tsx`:

```tsx
import userEvent from "@testing-library/user-event";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { InlineConfirm } from "@/components/InlineConfirm";

function setup(onConfirm = vi.fn()) {
  render(<InlineConfirm label="Abort" question="Abort run?" onConfirm={onConfirm} />);
  return { onConfirm, user: userEvent.setup() };
}

describe("InlineConfirm", () => {
  it("asks in place rather than opening a dialog", async () => {
    const { user } = setup();

    await user.click(screen.getByRole("button", { name: "Abort" }));

    expect(screen.getByText("Abort run?")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Abort" })).not.toBeInTheDocument();
  });

  it("does nothing until yes is chosen", async () => {
    const { onConfirm, user } = setup();

    await user.click(screen.getByRole("button", { name: "Abort" }));
    expect(onConfirm).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "yes" }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("reverts on no", async () => {
    const { onConfirm, user } = setup();

    await user.click(screen.getByRole("button", { name: "Abort" }));
    await user.click(screen.getByRole("button", { name: "no" }));

    expect(onConfirm).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Abort" })).toBeInTheDocument();
  });

  it("reverts on Escape", async () => {
    // Escape is the one way out that costs nothing to reach. A confirm you
    // can only leave by aiming at a 20px "no" is a confirm people click
    // through.
    const { onConfirm, user } = setup();

    await user.click(screen.getByRole("button", { name: "Abort" }));
    await user.keyboard("{Escape}");

    expect(onConfirm).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Abort" })).toBeInTheDocument();
  });

  it("reverts when focus leaves it entirely", async () => {
    const { user } = setup();
    render(<button type="button">elsewhere</button>);

    await user.click(screen.getByRole("button", { name: "Abort" }));
    await user.click(screen.getByRole("button", { name: "elsewhere" }));

    expect(screen.getByRole("button", { name: "Abort" })).toBeInTheDocument();
  });

  it("stays open while focus moves between yes and no", async () => {
    // The blur revert must not fire on the tab from `yes` to `no`, or the
    // keyboard path through this control would be unusable.
    const { user } = setup();

    await user.click(screen.getByRole("button", { name: "Abort" }));
    await user.tab();
    await user.tab();

    expect(screen.getByText("Abort run?")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
npm --prefix web test -- --run src/components/InlineConfirm.test.tsx
```

Expected: FAIL — cannot resolve `@/components/InlineConfirm`.

- [ ] **Step 3: Write the component**

Create `web/src/components/InlineConfirm.tsx`:

```tsx
import type { FocusEvent, KeyboardEvent } from "react";
import { useEffect, useRef, useState } from "react";

import styles from "./InlineConfirm.module.css";

/**
 * A destructive action that asks in place.
 *
 * No modal, per the handoff: the button becomes the question, and the
 * answer is two words beside it. Reverts on `no`, on Escape, and when focus
 * leaves the control entirely — the last one so an abandoned confirm does
 * not sit armed on the screen.
 *
 * Focus moves to `no` when the question appears, which puts the safe answer
 * under the keyboard and under Escape at the same time.
 */
export function InlineConfirm({
  label,
  question,
  onConfirm,
  className,
}: {
  label: string;
  question: string;
  onConfirm: () => void;
  className?: string;
}) {
  const [asking, setAsking] = useState(false);
  const cancel = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    if (asking) cancel.current?.focus();
  }, [asking]);

  if (!asking) {
    return (
      <button
        type="button"
        className={[styles.trigger, className].filter(Boolean).join(" ")}
        onClick={() => setAsking(true)}
      >
        {label}
      </button>
    );
  }

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape") setAsking(false);
  }

  function onBlur(event: FocusEvent<HTMLDivElement>) {
    // Focus moving from `yes` to `no` is still inside the control, and must
    // not close it — otherwise the keyboard path through this is unusable.
    if (event.currentTarget.contains(event.relatedTarget)) return;
    setAsking(false);
  }

  return (
    <div className={styles.asking} onKeyDown={onKeyDown} onBlur={onBlur}>
      <span className={styles.question}>{question}</span>
      <button
        type="button"
        className={styles.answer}
        onClick={() => {
          setAsking(false);
          onConfirm();
        }}
      >
        yes
      </button>
      <span className={styles.dot}>·</span>
      <button
        ref={cancel}
        type="button"
        className={styles.answer}
        onClick={() => setAsking(false)}
      >
        no
      </button>
    </div>
  );
}
```

- [ ] **Step 4: Write the stylesheet**

Create `web/src/components/InlineConfirm.module.css`:

```css
/* The handoff's abort confirmation: contrast at 10% fill, a contrast
   border, the question in contrast-light, and yes/no in mono 700/10
   separated by a middle dot. 150ms ease-out, which is --transition. */
.trigger {
  padding: 8px 14px;
  border: 1px solid var(--contrast-border-strong);
  border-radius: var(--radius-pill);
  background: none;
  font-family: var(--font-ui);
  font-size: 12px;
  font-weight: 700;
  line-height: 1;
  color: var(--contrast-light);
  cursor: pointer;
  transition: background var(--transition), border-color var(--transition);
}

.trigger:hover {
  background: var(--contrast-confirm);
}

.asking {
  display: inline-flex;
  align-items: center;
  gap: var(--gap-tight);
  padding: 7px 13px;
  border: 1px solid var(--contrast-border);
  border-radius: var(--radius-pill);
  background: var(--contrast-confirm);
  transition: background var(--transition);
}

.question {
  font-family: var(--font-ui);
  font-size: 12px;
  font-weight: 700;
  line-height: 1;
  color: var(--contrast-light);
}

.answer {
  padding: 0;
  border: none;
  background: none;
  font-family: var(--font-mono);
  font-size: 10px;
  font-weight: 700;
  line-height: 1;
  color: var(--contrast-light);
  cursor: pointer;
}

.answer:hover,
.answer:focus-visible {
  color: var(--text);
}

.dot {
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--contrast-light);
}
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
npm --prefix web test -- --run src/components/InlineConfirm.test.tsx
```

Expected: PASS.

- [ ] **Step 6: Run the whole web gate**

```bash
npm --prefix web run lint && npm --prefix web run typecheck && npm --prefix web test
```

Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add web/src/components/InlineConfirm.tsx web/src/components/InlineConfirm.module.css web/src/components/InlineConfirm.test.tsx
git commit -m "feat: an inline confirm that swaps in place instead of opening a modal"
```

---

### Task 6: reading progress out of the stage records

Three pure functions and the stage cards that use them. Pure because the
same three answers are needed by the stage cards, the Runs in-flight card
and the sidebar card, and a rule reimplemented in three components drifts in
two of them.

**Files:**
- Create: `web/src/features/runs/progress.ts`,
  `web/src/features/runs/progress.test.ts`
- Modify: `web/src/features/runs/StageCards.tsx`,
  `web/src/features/runs/StageCards.module.css`
- Test: `web/src/features/runs/RunDetailPage.test.tsx` (the card states)

**Interfaces:**
- Consumes: `StageRecord`, `Stage`, `STAGES`, `ARTIFACT_NAMES` from
  `@/api/types`; `StageBar` from `@/components/StageBar`; `formatBytes`,
  `formatDuration` from `@/format`.
- Produces:
  - `activeStage(stages: StageRecord[]): Stage | undefined`
  - `stageFill(record: StageRecord | undefined): number`
  - `stageCounter(record: StageRecord | undefined): string | null`
  - `byStage(stages: StageRecord[]): Map<Stage, StageRecord>`

- [ ] **Step 1: Write the failing tests**

Create `web/src/features/runs/progress.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import {
  activeStage,
  byStage,
  stageCounter,
  stageFill,
} from "@/features/runs/progress";
import { makeStageRecord } from "@/test/factories";

describe("activeStage", () => {
  it("names the stage whose row says it is running", () => {
    expect(
      activeStage([
        makeStageRecord({ stage: "ingest" }),
        makeStageRecord({ stage: "analyse", status: "running", finishedAt: null }),
      ]),
    ).toBe("analyse");
  });

  it("falls back to the first stage with no row at all", () => {
    // The window between the worker opening the run row and the first
    // stage announcing itself. Reporting nothing there would leave the
    // in-flight screen with no live card for as long as ingest takes to
    // start.
    expect(activeStage([])).toBe("ingest");
    expect(activeStage([makeStageRecord({ stage: "ingest" })])).toBe("analyse");
  });

  it("names nothing once every stage has settled", () => {
    expect(
      activeStage([
        makeStageRecord({ stage: "ingest" }),
        makeStageRecord({ stage: "analyse" }),
        makeStageRecord({ stage: "evaluate" }),
        makeStageRecord({ stage: "generate" }),
      ]),
    ).toBeUndefined();
  });

  it("treats a skipped stage as settled", () => {
    // A resumed run skips everything before its start stage. Those are
    // done, not pending, and pointing the live card at one would show a
    // stage that will never run again.
    expect(
      activeStage([
        makeStageRecord({ stage: "ingest", status: "skipped" }),
        makeStageRecord({ stage: "analyse", status: "skipped" }),
      ]),
    ).toBe("evaluate");
  });
});

describe("stageFill", () => {
  it("fills a completed stage", () => {
    expect(stageFill(makeStageRecord({ stage: "ingest" }))).toBe(1);
  });

  it("fills a running stage by its counters", () => {
    expect(
      stageFill(
        makeStageRecord({ stage: "analyse", status: "running", done: 17, total: 25 }),
      ),
    ).toBeCloseTo(0.68);
  });

  it("leaves a running stage with no counters empty", () => {
    // Ingest and evaluate count nothing. A fabricated half-fill would be a
    // claim about progress nothing measured.
    expect(
      stageFill(makeStageRecord({ stage: "ingest", status: "running" })),
    ).toBe(0);
  });

  it("leaves an absent stage empty", () => {
    expect(stageFill(undefined)).toBe(0);
  });

  it("does not divide by a zero total", () => {
    // A run whose ingest returned nothing reaches analyse with zero trends.
    expect(
      stageFill(
        makeStageRecord({ stage: "analyse", status: "running", done: 0, total: 0 }),
      ),
    ).toBe(0);
  });
});

describe("stageCounter", () => {
  it("reads a running stage's counters", () => {
    expect(
      stageCounter(
        makeStageRecord({ stage: "analyse", status: "running", done: 17, total: 25 }),
      ),
    ).toBe("17 / 25");
  });

  it("says nothing for a stage that has finished", () => {
    // The finished card shows a duration in this slot. A counter there
    // would claim work is still going.
    expect(
      stageCounter(makeStageRecord({ stage: "analyse", done: 25, total: 25 })),
    ).toBeNull();
  });

  it("says nothing for a running stage that counts nothing", () => {
    expect(
      stageCounter(makeStageRecord({ stage: "ingest", status: "running" })),
    ).toBeNull();
  });
});

describe("byStage", () => {
  it("indexes the records a run recorded", () => {
    const analyse = makeStageRecord({ stage: "analyse" });
    expect(byStage([analyse]).get("analyse")).toEqual(analyse);
    expect(byStage([analyse]).get("generate")).toBeUndefined();
  });
});
```

`makeStageRecord` needs the two new options. Extend it in
`web/src/test/factories.ts`:

```ts
export function makeStageRecord(
  options: {
    stage?: Stage;
    status?: StageStatus;
    startedAt?: string | null;
    finishedAt?: string | null;
    payloadBytes?: number | null;
    summary?: string;
    done?: number | null;
    total?: number | null;
  } = {},
): StageRecord {
  return {
    stage: options.stage ?? "ingest",
    status: options.status ?? "ok",
    started_at: options.startedAt === undefined ? FIXED_START : options.startedAt,
    finished_at:
      options.finishedAt === undefined ? "2026-08-29T09:01:12Z" : options.finishedAt,
    payload_bytes:
      options.payloadBytes === undefined ? 1_363_148 : options.payloadBytes,
    summary: options.summary ?? "25 trends, 750 posts",
    done: options.done ?? null,
    total: options.total ?? null,
  };
}
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
npm --prefix web test -- --run src/features/runs/progress.test.ts
```

Expected: FAIL — cannot resolve `@/features/runs/progress`.

- [ ] **Step 3: Write the module**

Create `web/src/features/runs/progress.ts`:

```ts
/**
 * What the stage records say about a run that is still going.
 *
 * Pure, and shared: the stage cards, the Runs in-flight card and the
 * sidebar card each need the same three answers, and a rule reimplemented
 * in three components drifts in two of them.
 */
import type { Stage, StageRecord } from "@/api/types";
import { STAGES } from "@/api/types";

/** A stage that will not change again. */
function settled(record: StageRecord): boolean {
  return record.status !== "running" && record.status !== "queued";
}

function counted(
  record: StageRecord,
): { done: number; total: number } | null {
  const { done, total } = record;
  if (done === null || done === undefined) return null;
  if (total === null || total === undefined || total <= 0) return null;
  return { done, total };
}

export function byStage(stages: StageRecord[]): Map<Stage, StageRecord> {
  return new Map(stages.map((record) => [record.stage, record]));
}

/**
 * Which stage is happening now, or undefined if none is.
 *
 * The `running` row is the direct answer, and the runner writes one as
 * every stage begins. The fallback covers the window between the worker
 * opening the run row and its first stage announcing itself: nothing is
 * running and nothing has finished, and the first stage with no row is the
 * one about to start.
 */
export function activeStage(stages: StageRecord[]): Stage | undefined {
  const running = stages.find((record) => record.status === "running");
  if (running !== undefined) return running.stage;
  const done = new Set(stages.filter(settled).map((record) => record.stage));
  return STAGES.find((stage) => !done.has(stage));
}

/** 0-1, for `StageBar`. A stage with nothing to count stays at 0. */
export function stageFill(record: StageRecord | undefined): number {
  if (record === undefined) return 0;
  if (record.status === "ok" || record.status === "skipped") return 1;
  if (record.status !== "running") return 0;
  const progress = counted(record);
  return progress === null ? 0 : progress.done / progress.total;
}

/**
 * `17 / 25`, or null where the design draws a duration instead.
 *
 * Only a running stage that counts something has one. Ingest is a single
 * opaque fetch and evaluate a single ranking pass, so both report null and
 * their cards show an indeterminate bar rather than a fabricated fraction.
 */
export function stageCounter(record: StageRecord | undefined): string | null {
  if (record === undefined || record.status !== "running") return null;
  const progress = counted(record);
  return progress === null ? null : `${progress.done} / ${progress.total}`;
}
```

- [ ] **Step 4: Teach the stage cards the running state**

Replace the body of `web/src/features/runs/StageCards.tsx`:

```tsx
import type { StageRecord } from "@/api/types";
import { ARTIFACT_NAMES, STAGES } from "@/api/types";
import { StageBar } from "@/components/StageBar";
import { byStage, stageCounter, stageFill } from "@/features/runs/progress";
import { formatBytes, formatDuration } from "@/format";

import styles from "./StageCards.module.css";

/**
 * Four cards, always.
 *
 * `stages_for_run` returns only the stages that were recorded, so a run
 * that died in analyse has no evaluate or generate row at all. The design
 * draws four regardless — the ones that never ran are `queued` in
 * `text-30` with no accent bar — because "this stage has not happened" is
 * information, and a three-card row would just look like a different
 * screen.
 *
 * Three treatments: complete (accent bar full), running (accent border,
 * accent wash, partial bar, a counter where the duration goes), and idle.
 * The artifact line drops its size on a running card, because a stage
 * that has not written its checkpoint has no size to report and `—` beside
 * a name reads as a missing value rather than an unwritten one.
 */
export function StageCards({ stages }: { stages: StageRecord[] }) {
  const recorded = byStage(stages);

  return (
    <ul className={styles.grid}>
      {STAGES.map((name) => {
        const record = recorded.get(name);
        const complete = record?.status === "ok" || record?.status === "skipped";
        const running = record?.status === "running";
        const counter = stageCounter(record);
        return (
          <li
            key={name}
            className={[
              styles.card,
              running ? styles.running : "",
              complete || running ? "" : styles.idle,
            ]
              .filter(Boolean)
              .join(" ")}
          >
            {complete || running ? (
              <StageBar fill={stageFill(record)} />
            ) : (
              <StageBar fill={0} tone="muted" />
            )}
            <div className={styles.head}>
              <span className={styles.name}>{name}</span>
              <span className={running ? styles.counter : styles.duration}>
                {counter ??
                  (record === undefined || record.started_at === null
                    ? "—"
                    : formatDuration(record.started_at, record.finished_at))}
              </span>
            </div>
            <p className={styles.summary}>{record?.summary ?? "queued"}</p>
            <span className={styles.artifact}>
              {running
                ? ARTIFACT_NAMES[name]
                : `${ARTIFACT_NAMES[name]} · ${formatBytes(record?.payload_bytes)}`}
            </span>
          </li>
        );
      })}
    </ul>
  );
}
```

- [ ] **Step 5: Add the two classes**

Append to `web/src/features/runs/StageCards.module.css`:

```css
/* The active card, per 5a: a 35% accent border and the accent wash, so the
   eye lands on the stage that is happening now. */
.running {
  border-color: var(--accent-border-strong);
  background: var(--accent-wash);
}

/* Where the duration sits on a finished card. Mono, and accent, because it
   is a live count rather than a settled fact. */
.counter {
  font-family: var(--font-mono);
  font-size: 10px;
  font-weight: 600;
  line-height: 1;
  color: var(--accent);
}
```

- [ ] **Step 6: Add the card-state tests**

Add to `web/src/features/runs/RunDetailPage.test.tsx`:

```tsx
it("marks the running stage and counts it", async () => {
  server.use(
    http.get("/api/runs/:runId", () =>
      HttpResponse.json(
        makeRunDetail({
          status: "running",
          stages: [
            makeStageRecord({ stage: "ingest" }),
            makeStageRecord({
              stage: "analyse",
              status: "running",
              finishedAt: null,
              payloadBytes: null,
              summary: "airport cat",
              done: 17,
              total: 25,
            }),
          ],
        }),
      ),
    ),
    http.get("/api/runs/:runId/topics", () => HttpResponse.json([])),
    http.get("/api/runs/:runId/log", () => HttpResponse.json([])),
    http.get("/api/runs/active", () =>
      HttpResponse.json(makeActiveRuns({ current: "20260829T090000Z" })),
    ),
  );

  renderWithProviders(<RunDetailPage />, {
    route: "/runs/20260829T090000Z",
    path: "/runs/:runId",
  });

  expect(await screen.findByText("17 / 25")).toBeInTheDocument();
  expect(screen.getByText("airport cat")).toBeInTheDocument();
});

it("shows no checkpoint size for a stage that has not written one", async () => {
  // `evidence · —` reads as a size that went missing. `evidence` alone
  // reads as a checkpoint not yet written, which is what is true.
  server.use(
    http.get("/api/runs/:runId", () =>
      HttpResponse.json(
        makeRunDetail({
          status: "running",
          stages: [
            makeStageRecord({
              stage: "ingest",
              status: "running",
              finishedAt: null,
              payloadBytes: null,
            }),
          ],
        }),
      ),
    ),
    http.get("/api/runs/:runId/topics", () => HttpResponse.json([])),
    http.get("/api/runs/:runId/log", () => HttpResponse.json([])),
    http.get("/api/runs/active", () =>
      HttpResponse.json(makeActiveRuns({ current: "20260829T090000Z" })),
    ),
  );

  renderWithProviders(<RunDetailPage />, {
    route: "/runs/20260829T090000Z",
    path: "/runs/:runId",
  });

  expect(await screen.findByText("evidence")).toBeInTheDocument();
  expect(screen.queryByText(/evidence · /)).not.toBeInTheDocument();
});
```

These two will not pass until Task 10 wires the page's live queries; add
them now and expect them red, or add them at the end of Task 10. Either
way they are written before the code that satisfies them.

- [ ] **Step 7: Run the progress tests**

```bash
npm --prefix web test -- --run src/features/runs/progress.test.ts
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add web/src/features/runs/progress.ts web/src/features/runs/progress.test.ts web/src/features/runs/StageCards.tsx web/src/features/runs/StageCards.module.css web/src/test/factories.ts
git commit -m "feat: stage cards read the running stage and its counters"
```

---

### Task 7: the live log

The one piece of UI mechanics the spec singles out as easy to get subtly
wrong, so its details are transcribed rather than reinvented: a 24px
threshold rather than an equality test, `following` in a ref and mirrored to
state only when it flips, an imperative passive scroll listener, a layout
effect for the pin, `overflow-anchor: none`, and no smooth scrolling.

Batching and the 2000-line cap live in `useRunEvents` (Task 4), not here:
they are properties of the stream, and the post-mortem log renders the same
component from a finished query.

**Files:**
- Create: `web/src/features/runs/LiveLog.tsx`,
  `web/src/features/runs/LiveLog.module.css`,
  `web/src/features/runs/LiveLog.test.tsx`

**Interfaces:**
- Consumes: `LogLine` from `@/api/types`; `SectionLabel` from
  `@/components/SectionLabel`.
- Produces: `LiveLog({ lines, live, verbose, onVerboseChange }): JSX.Element`.
  The scroller carries `data-testid="log-scroller"`.

- [ ] **Step 1: Write the failing test**

Create `web/src/features/runs/LiveLog.test.tsx`:

```tsx
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { LiveLog } from "@/features/runs/LiveLog";
import { makeLogLine } from "@/test/factories";

/**
 * jsdom lays nothing out, so every scroll dimension is 0 and every log is
 * trivially "at the bottom". These make the container a real scroller for
 * the assertions that depend on one.
 */
function makeScrollable(node: HTMLElement, scrollHeight: number, clientHeight = 200) {
  Object.defineProperty(node, "scrollHeight", {
    value: scrollHeight,
    configurable: true,
  });
  Object.defineProperty(node, "clientHeight", {
    value: clientHeight,
    configurable: true,
  });
}

function lines(count: number) {
  return Array.from({ length: count }, (_, index) =>
    makeLogLine({ seq: index, message: `line ${index}` }),
  );
}

describe("LiveLog", () => {
  it("renders each line with the logger that emitted it", () => {
    render(
      <LiveLog
        lines={[makeLogLine({ logger: "zeitgeist.media.render", message: "drawing" })]}
        live
        verbose={false}
        onVerboseChange={vi.fn()}
      />,
    );

    expect(screen.getByText("zeitgeist.media.render")).toBeInTheDocument();
    expect(screen.getByText("drawing")).toBeInTheDocument();
  });

  it("pins to the bottom as lines arrive while following", () => {
    const { rerender } = render(
      <LiveLog lines={lines(3)} live verbose={false} onVerboseChange={vi.fn()} />,
    );
    const scroller = screen.getByTestId("log-scroller");
    makeScrollable(scroller, 1000);

    rerender(
      <LiveLog lines={lines(4)} live verbose={false} onVerboseChange={vi.fn()} />,
    );

    expect(scroller.scrollTop).toBe(1000);
  });

  it("releases follow when scrolled away from the bottom", async () => {
    const user = userEvent.setup();
    render(<LiveLog lines={lines(3)} live verbose={false} onVerboseChange={vi.fn()} />);
    const scroller = screen.getByTestId("log-scroller");
    makeScrollable(scroller, 1000);

    scroller.scrollTop = 200;
    fireEvent.scroll(scroller);

    const jump = await screen.findByRole("button", { name: "jump to latest" });
    expect(screen.queryByText("following")).not.toBeInTheDocument();

    await user.click(jump);

    expect(scroller.scrollTop).toBe(1000);
    expect(screen.getByText("following")).toBeInTheDocument();
  });

  it("keeps following within the threshold of the bottom", () => {
    // The log is 11px mono at line-height 1.9, so lines are 20.9px and an
    // exact equality test would release follow on virtually every line.
    render(<LiveLog lines={lines(3)} live verbose={false} onVerboseChange={vi.fn()} />);
    const scroller = screen.getByTestId("log-scroller");
    makeScrollable(scroller, 1000);

    scroller.scrollTop = 780;
    fireEvent.scroll(scroller);

    expect(screen.getByText("following")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "jump to latest" }),
    ).not.toBeInTheDocument();
  });

  it("hides DEBUG lines until verbose is on, retroactively", async () => {
    const user = userEvent.setup();
    const onVerboseChange = vi.fn();
    const held = [
      makeLogLine({ seq: 1, level: "INFO", message: "Fetched 25 trends" }),
      makeLogLine({ seq: 2, level: "DEBUG", message: "Distilled 'cat' in 2.1s" }),
    ];
    const { rerender } = render(
      <LiveLog lines={held} live verbose={false} onVerboseChange={onVerboseChange} />,
    );

    expect(screen.queryByText("Distilled 'cat' in 2.1s")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "verbose" }));
    expect(onVerboseChange).toHaveBeenCalledWith(true);

    rerender(
      <LiveLog lines={held} live verbose onVerboseChange={onVerboseChange} />,
    );

    expect(screen.getByText("Distilled 'cat' in 2.1s")).toBeInTheDocument();
    expect(screen.getByText("Fetched 25 trends")).toBeInTheDocument();
  });

  it("offers neither follow nor jump for a finished run", () => {
    // The post-mortem block is the same component. A "following" indicator
    // on a log that will never gain another line is a lie about what the
    // screen is doing.
    render(
      <LiveLog lines={lines(3)} live={false} verbose={false} onVerboseChange={vi.fn()} />,
    );

    expect(screen.queryByText("following")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "jump to latest" }),
    ).not.toBeInTheDocument();
    expect(screen.getByText("Log")).toBeInTheDocument();
  });

  it("says so when a run has logged nothing yet", () => {
    render(<LiveLog lines={[]} live verbose={false} onVerboseChange={vi.fn()} />);

    expect(screen.getByText("Waiting for the first line…")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
npm --prefix web test -- --run src/features/runs/LiveLog.test.tsx
```

Expected: FAIL — cannot resolve `@/features/runs/LiveLog`.

- [ ] **Step 3: Write the component**

Create `web/src/features/runs/LiveLog.tsx`:

```tsx
import { useEffect, useLayoutEffect, useRef, useState } from "react";

import type { LogLine } from "@/api/types";
import { SectionLabel } from "@/components/SectionLabel";

import styles from "./LiveLog.module.css";

/**
 * Within this many pixels of the bottom still counts as following.
 *
 * A threshold, never an equality test: the log is 11px mono at line-height
 * 1.9, so lines are 20.9px and exact equality effectively never holds.
 */
const FOLLOW_THRESHOLD_PX = 24;

/** Lines at the end that stay at full-ish opacity, so the eye lands late. */
const RECENT = 20;

/**
 * The run's log, live or post-mortem.
 *
 * Follow behaviour is the one piece of mechanics here worth reading
 * carefully. `following` lives in a ref and is mirrored into state only
 * when it flips, so the header can render an indicator without the
 * component re-rendering on every scroll event. The listener is attached
 * imperatively and passive, which is what makes the ref necessary rather
 * than merely tidy: a listener registered once in a mount-only effect
 * captures its render's variables permanently, so reading state inside it
 * would compare against the first render's value forever.
 *
 * New lines pin to the bottom from a `useLayoutEffect`, which runs before
 * paint, so the jump never renders as a flicker.
 *
 * `verbose` is a filter over lines already held, not a request for
 * different ones — which is what makes flipping it work retroactively, and
 * is what anyone toggling it mid-run wants. The stream sends everything
 * regardless (`control.py` applies no filter of its own).
 */
export function LiveLog({
  lines,
  live,
  verbose,
  onVerboseChange,
}: {
  lines: LogLine[];
  live: boolean;
  verbose: boolean;
  onVerboseChange: (verbose: boolean) => void;
}) {
  const scroller = useRef<HTMLDivElement | null>(null);
  const following = useRef(true);
  const [released, setReleased] = useState(false);

  const shown = verbose ? lines : lines.filter((line) => line.level !== "DEBUG");

  useEffect(() => {
    const node = scroller.current;
    if (node === null) return;

    const onScroll = () => {
      const distance = node.scrollHeight - node.scrollTop - node.clientHeight;
      const next = distance <= FOLLOW_THRESHOLD_PX;
      if (next === following.current) return;
      following.current = next;
      setReleased(!next);
    };

    node.addEventListener("scroll", onScroll, { passive: true });
    return () => node.removeEventListener("scroll", onScroll);
  }, []);

  useLayoutEffect(() => {
    const node = scroller.current;
    if (node === null || !following.current) return;
    node.scrollTop = node.scrollHeight;
  }, [shown.length]);

  function jump() {
    const node = scroller.current;
    if (node === null) return;
    node.scrollTop = node.scrollHeight;
    following.current = true;
    setReleased(false);
  }

  return (
    <section className={styles.section}>
      <SectionLabel
        hint={
          <span className={styles.controls}>
            {live &&
              (released ? (
                // The handoff draws the indicator but no way back. This is
                // the way back: the same dot, made a button.
                <button type="button" className={styles.jump} onClick={jump}>
                  <span className={styles.dot} />
                  jump to latest
                </button>
              ) : (
                <span className={styles.following}>
                  <span className={styles.dot} />
                  following
                </span>
              ))}
            <button
              type="button"
              className={verbose ? styles.toggleOn : styles.toggle}
              aria-pressed={verbose}
              onClick={() => onVerboseChange(!verbose)}
            >
              verbose
            </button>
          </span>
        }
      >
        {live ? "Live log" : "Log"}
      </SectionLabel>

      <div className={styles.block} data-testid="log-scroller" ref={scroller}>
        {shown.length === 0 ? (
          <p className={styles.empty}>
            {live ? "Waiting for the first line…" : "This run logged nothing."}
          </p>
        ) : (
          shown.map((line, index) => (
            <p
              key={line.seq}
              className={[styles.line, toneOf(line, index, shown.length, live)]
                .filter(Boolean)
                .join(" ")}
            >
              <span className={styles.logger}>{line.logger}</span>
              <span className={styles.message}>{line.message}</span>
            </p>
          ))
        )}
      </div>
    </section>
  );
}

/**
 * Older lines fade so the eye lands on recent ones, and the line being
 * worked on right now is fully accent.
 *
 * A warning or an error outranks both: it is the reason to read the log at
 * all, and dimming one because it scrolled up would hide the thing someone
 * opened this to find.
 */
function toneOf(line: LogLine, index: number, count: number, live: boolean): string {
  if (line.level === "WARNING" || line.level === "ERROR" || line.level === "CRITICAL") {
    return styles.warn;
  }
  if (live && index === count - 1) return styles.current;
  return index < count - RECENT ? styles.dim : styles.mid;
}
```

- [ ] **Step 4: Write the stylesheet**

Create `web/src/features/runs/LiveLog.module.css`:

```css
.section {
  display: flex;
  flex-direction: column;
  gap: 9px;
}

.block {
  max-height: 260px;
  overflow-y: auto;
  padding: 12px 14px;
  border-radius: var(--radius-sm);
  background: var(--surface-log);
  /* The browser's own scroll anchoring fights the pin-to-bottom logic
     exactly when it matters — when lines are being appended. */
  overflow-anchor: none;
  /* Deliberately no `scroll-behavior: smooth`: lines can arrive faster
     than a smooth scroll completes, and the view falls permanently
     behind. */
}

.line {
  display: flex;
  gap: 10px;
  margin: 0;
  font-family: var(--font-mono);
  font-size: 11px;
  font-weight: 400;
  line-height: 1.9;
}

.logger {
  flex: none;
  color: inherit;
  opacity: 0.7;
}

.message {
  min-width: 0;
  word-break: break-word;
}

.dim {
  color: var(--text);
  opacity: 0.4;
}

.mid {
  color: var(--text);
  opacity: 0.55;
}

.current {
  color: var(--accent);
}

.warn {
  color: var(--accent);
}

.empty {
  margin: 0;
  font-family: var(--font-mono);
  font-size: 11px;
  line-height: 1.9;
  color: var(--text-35);
}

.controls {
  display: inline-flex;
  align-items: center;
  gap: 10px;
}

.following {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-family: var(--font-mono);
  font-size: 9.5px;
  font-weight: 600;
  color: var(--accent);
}

.jump {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 4px 9px;
  border: none;
  border-radius: var(--radius-pill);
  background: var(--accent-tint);
  font-family: var(--font-mono);
  font-size: 9.5px;
  font-weight: 600;
  color: var(--accent);
  cursor: pointer;
}

.dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--accent);
}

.toggle,
.toggleOn {
  padding: 4px 9px;
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-pill);
  background: none;
  font-family: var(--font-mono);
  font-size: 9.5px;
  font-weight: 600;
  color: var(--text-55);
  cursor: pointer;
  transition: background var(--transition), color var(--transition);
}

.toggleOn {
  border-color: var(--accent-border);
  background: var(--accent-tint);
  color: var(--accent);
}
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
npm --prefix web test -- --run src/features/runs/LiveLog.test.tsx
```

Expected: PASS.

- [ ] **Step 6: Run the whole web gate**

```bash
npm --prefix web run lint && npm --prefix web run typecheck && npm --prefix web test
```

Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add web/src/features/runs/LiveLog.tsx web/src/features/runs/LiveLog.module.css web/src/features/runs/LiveLog.test.tsx
git commit -m "feat: the live log, its follow behaviour and its way back"
```

---

### Task 8: the two new routes, the third nav item, and the sidebar's in-flight card

The shell learns about the phase. `routes.tsx` and `Sidebar.tsx` both carry
comments naming what phase 6 adds; this removes them by doing it.

The in-flight card pins to the bottom via `margin-top: auto`, which is what
lets Settings sit beneath Runs without anything else moving — the one place
these screens change the handoff's own layout rather than extending it.

**Files:**
- Create: `web/src/features/runs/useNow.ts`,
  `web/src/features/runs/useNow.test.ts`
- Create: `web/src/app/Sidebar.test.tsx`
- Modify: `web/src/app/routes.tsx`, `web/src/app/Sidebar.tsx`,
  `web/src/app/Sidebar.module.css`
- Test: `web/src/app/routes.test.tsx`

**Interfaces:**
- Consumes: `useActiveRun`, `useRun` from `@/api/queries`; `activeStage`
  from `@/features/runs/progress`; `formatElapsed` from `@/format`.
- Produces: `useNow(active: boolean, intervalMs?: number): Date`; routes
  `/runs/new` and `/settings`; a sidebar that renders the in-flight card
  only while a run is active.

Both new routes point at placeholders in this task and get their real
screens in Tasks 11 and 12. That is deliberate: the shell is a reviewable
deliverable on its own, and a route that 404s until three tasks later is a
worse checkpoint than one that renders a heading.

- [ ] **Step 1: Write the failing tests**

Create `web/src/features/runs/useNow.test.ts`:

```ts
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useNow } from "@/features/runs/useNow";

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe("useNow", () => {
  it("advances once a second while it is active", () => {
    const { result } = renderHook(() => useNow(true));
    const first = result.current;

    act(() => vi.advanceTimersByTime(2000));

    expect(result.current.getTime()).toBeGreaterThan(first.getTime());
  });

  it("holds still when it is not", () => {
    // An idle app must not re-render once a second forever. Every screen
    // that shows an elapsed time mounts this, and only one of them ever
    // has a live run behind it.
    const { result } = renderHook(() => useNow(false));
    const first = result.current;

    act(() => vi.advanceTimersByTime(5000));

    expect(result.current).toBe(first);
  });

  it("stops when it becomes inactive", () => {
    const { result, rerender } = renderHook(
      ({ live }: { live: boolean }) => useNow(live),
      { initialProps: { live: true } },
    );

    rerender({ live: false });
    const settled = result.current;
    act(() => vi.advanceTimersByTime(5000));

    expect(result.current).toBe(settled);
  });
});
```

Create `web/src/app/Sidebar.test.tsx`:

```tsx
import { screen } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";

import { Sidebar } from "@/app/Sidebar";
import {
  makeActiveRuns,
  makeRunDetail,
  makeStageRecord,
} from "@/test/factories";
import { renderWithProviders } from "@/test/render";
import { server } from "@/test/server";

describe("Sidebar", () => {
  it("offers Topics, Runs and Settings, in that order", async () => {
    server.use(
      http.get("/api/runs/active", () => HttpResponse.json(makeActiveRuns())),
    );

    renderWithProviders(<Sidebar />);

    const links = await screen.findAllByRole("link");
    expect(links.map((link) => link.textContent)).toEqual([
      "Topics",
      "Runs",
      "Settings",
    ]);
  });

  it("shows no in-flight card while nothing is running", async () => {
    server.use(
      http.get("/api/runs/active", () =>
        HttpResponse.json(makeActiveRuns({ current: null })),
      ),
    );

    renderWithProviders(<Sidebar />);
    await screen.findByRole("link", { name: "Runs" });

    expect(screen.queryByText("IN FLIGHT")).not.toBeInTheDocument();
  });

  it("names the running stage while one is", async () => {
    server.use(
      http.get("/api/runs/active", () =>
        HttpResponse.json(makeActiveRuns({ current: "20260829T140200Z" })),
      ),
      http.get("/api/runs/:runId", () =>
        HttpResponse.json(
          makeRunDetail({
            runId: "20260829T140200Z",
            status: "running",
            stages: [
              makeStageRecord({ stage: "ingest" }),
              makeStageRecord({
                stage: "analyse",
                status: "running",
                finishedAt: null,
              }),
            ],
          }),
        ),
      ),
    );

    renderWithProviders(<Sidebar />);

    expect(await screen.findByText("IN FLIGHT")).toBeInTheDocument();
    expect(screen.getByText(/analyse/)).toBeInTheDocument();
  });

  it("links the card to the run it is about", async () => {
    server.use(
      http.get("/api/runs/active", () =>
        HttpResponse.json(makeActiveRuns({ current: "20260829T140200Z" })),
      ),
      http.get("/api/runs/:runId", () =>
        HttpResponse.json(
          makeRunDetail({ runId: "20260829T140200Z", status: "running" }),
        ),
      ),
    );

    renderWithProviders(<Sidebar />);

    const card = await screen.findByRole("link", { name: /IN FLIGHT/ });
    expect(card).toHaveAttribute("href", "/runs/20260829T140200Z");
  });
});
```

Add to `web/src/app/routes.test.tsx`:

```tsx
it("routes /runs/new and /settings", async () => {
  server.use(
    http.get("/api/runs/active", () => HttpResponse.json(makeActiveRuns())),
    http.get("/api/config/options", () =>
      HttpResponse.json(makeConfigOptions()),
    ),
    http.get("/api/settings", () => HttpResponse.json(makeSettingFields())),
  );

  renderWithProviders(<AppRoutes />, { route: "/runs/new" });
  expect(await screen.findByRole("heading", { name: "New run" })).toBeInTheDocument();

  renderWithProviders(<AppRoutes />, { route: "/settings" });
  expect(await screen.findByRole("heading", { name: "Settings" })).toBeInTheDocument();
});
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
npm --prefix web test -- --run src/app src/features/runs/useNow.test.ts
```

Expected: FAIL — cannot resolve `@/features/runs/useNow`, and the sidebar
has two links rather than three.

- [ ] **Step 3: Write `useNow`**

Create `web/src/features/runs/useNow.ts`:

```ts
import { useEffect, useState } from "react";

/**
 * A clock that ticks only while something is watching it.
 *
 * Nothing on the wire says how long a run has been going, so every elapsed
 * display is computed against now — and "now" has to advance for the
 * display to. `active` is what keeps an idle app from re-rendering once a
 * second forever: every screen showing an elapsed time mounts this, and
 * only one of them ever has a live run behind it.
 */
export function useNow(active: boolean, intervalMs = 1000): Date {
  const [now, setNow] = useState(() => new Date());

  useEffect(() => {
    if (!active) return;
    const id = setInterval(() => setNow(new Date()), intervalMs);
    return () => clearInterval(id);
  }, [active, intervalMs]);

  return now;
}
```

- [ ] **Step 4: Rewrite the sidebar**

Replace `web/src/app/Sidebar.tsx`:

```tsx
import { Link, NavLink } from "react-router-dom";

import { useActiveRun, useRun } from "@/api/queries";
import { activeStage } from "@/features/runs/progress";
import { useNow } from "@/features/runs/useNow";
import { formatElapsed } from "@/format";

import styles from "./Sidebar.module.css";

/**
 * 180px, one step darker than the page, three destinations and a card.
 *
 * Topics, Runs and Settings, in that order. The spec merges the landing
 * dashboard and the topics index into `/`, so the first two are the
 * handoff's own nav; Settings sits beneath them, which is the one place
 * these screens change the handoff's layout rather than extending it. The
 * in-flight card still pins to the bottom via `margin-top: auto`, so
 * nothing else moves.
 */
export function Sidebar() {
  return (
    <nav className={styles.rail}>
      <span className={styles.wordmark}>Zeitgeist</span>
      <ul className={styles.nav}>
        <li>
          {/* `end` because "/" prefix-matches every route in the app. */}
          <NavLink to="/" end className={navClass}>
            Topics
          </NavLink>
        </li>
        <li>
          <NavLink to="/runs" className={navClass}>
            Runs
          </NavLink>
        </li>
        <li>
          <NavLink to="/settings" className={navClass}>
            Settings
          </NavLink>
        </li>
      </ul>
      <InFlight />
    </nav>
  );
}

/**
 * Rendered only while a run is active, per the handoff.
 *
 * Two queries rather than one: `active` says *whether*, and is the app's
 * single source of truth for that; the run's own detail says *which stage*,
 * which `ActiveRuns` does not carry. The second is `enabled` only when the
 * first names a run, so an idle app issues neither.
 */
function InFlight() {
  const active = useActiveRun();
  const runId = active.data?.current ?? undefined;
  const run = useRun(runId);
  const now = useNow(runId !== undefined);

  if (runId === undefined || run.data === undefined) return null;

  const stage = activeStage(run.data.stages) ?? "finishing";
  return (
    <Link to={`/runs/${encodeURIComponent(runId)}`} className={styles.card}>
      <span className={styles.cardLabel}>IN FLIGHT</span>
      <span className={styles.cardDetail}>
        {stage} · {formatElapsed(run.data.run.started_at, now)}
      </span>
    </Link>
  );
}

function navClass({ isActive }: { isActive: boolean }): string | undefined {
  return isActive ? `${styles.item} ${styles.active}` : styles.item;
}
```

- [ ] **Step 5: Style the card**

Append to `web/src/app/Sidebar.module.css`:

```css
/* Pinned to the bottom, which is what lets Settings join the nav above
   without anything else moving. */
.card {
  margin-top: auto;
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 11px;
  border: 1px solid var(--accent-border-soft);
  border-radius: 9px;
  background: var(--accent-wash);
  transition: border-color var(--transition);
}

.card:hover {
  border-color: var(--accent-border);
}

.cardLabel {
  font-family: var(--font-mono);
  font-size: 9.5px;
  font-weight: 600;
  letter-spacing: 0.12em;
  line-height: 1;
  color: var(--accent);
}

.cardDetail {
  font-family: var(--font-mono);
  font-size: 10px;
  font-weight: 500;
  line-height: 1.5;
  color: var(--text-50);
}
```

- [ ] **Step 6: Add the two routes**

In `web/src/app/routes.tsx`, replace the phase-6 comment and add the routes:

```tsx
/**
 * Seven routes. Topic detail is run-scoped because the dossier, the
 * replies and the renders all belong to one run, and because generating a
 * meme needs an unambiguous run to attach to.
 *
 * `/runs/new` sits before `/runs/:runId` so the literal wins; React Router
 * ranks static segments above dynamic ones regardless, and the order here
 * says so to a reader.
 */
```

```tsx
        <Route path="/runs" element={<RunsPage />} />
        <Route path="/runs/new" element={<NewRunPage />} />
        <Route path="/runs/:runId" element={<RunDetailPage />} />
```

```tsx
        <Route path="/settings" element={<SettingsPage />} />
```

with the imports:

```tsx
import { NewRunPage } from "@/features/newrun/NewRunPage";
import { SettingsPage } from "@/features/settings/SettingsPage";
```

- [ ] **Step 7: Write the two placeholders**

Create `web/src/features/newrun/NewRunPage.tsx`:

```tsx
/** Task 11 builds this. The route exists now so the shell is complete. */
export function NewRunPage() {
  return <h1>New run</h1>;
}
```

Create `web/src/features/settings/SettingsPage.tsx`:

```tsx
/** Task 12 builds this. The route exists now so the shell is complete. */
export function SettingsPage() {
  return <h1>Settings</h1>;
}
```

- [ ] **Step 8: Run the tests to verify they pass**

```bash
npm --prefix web test -- --run src/app src/features/runs/useNow.test.ts
```

Expected: PASS. The `routes.test.tsx` addition passes against the
placeholders, and keeps passing against the real screens because both give
their page an `h1` with the same text.

- [ ] **Step 9: Run the whole web gate**

```bash
npm --prefix web run lint && npm --prefix web run typecheck && npm --prefix web test
```

Expected: all PASS.

- [ ] **Step 10: Commit**

```bash
git add web/src/app web/src/features/runs/useNow.ts web/src/features/runs/useNow.test.ts web/src/features/newrun web/src/features/settings
git commit -m "feat: a Settings destination, the in-flight card, and two new routes"
```

---

### Task 9: the in-flight card on Runs, the run strip on Topics, and New run

The two remaining places an active run surfaces, plus the button that
creates one. All three read `useActiveRun`, which is what keeps them
agreeing about what is happening.

**Files:**
- Create: `web/src/features/runs/InFlightCard.tsx` + `.module.css`
- Create: `web/src/features/runs/RunStrip.tsx` + `.module.css`
- Create: `web/src/features/newrun/NewRunButton.tsx` + `.module.css`
- Modify: `web/src/features/runs/RunsPage.tsx` + `.module.css`
- Modify: `web/src/features/topics/TopicsPage.tsx` + `.module.css`
- Test: `web/src/features/runs/RunsPage.test.tsx`,
  `web/src/features/topics/TopicsPage.test.tsx`

**Interfaces:**
- Consumes: `useActiveRun`, `useRun`, `useRuns` from `@/api/queries`;
  `activeStage`, `byStage`, `stageFill` from `@/features/runs/progress`;
  `useNow`; `StageBar`, `StatusPill`, `EmptyState`; `formatElapsed`,
  `shortRunId`, `formatRelative`; `STAGES` from `@/api/types`.
- Produces:
  - `InFlightCard({ runId }): JSX.Element | null`
  - `RunStrip({ runs, activeRunId }): JSX.Element`
  - `NewRunButton({ from }?: { from?: string }): JSX.Element` — a Link to
    `/runs/new`, or `/runs/new?from=<runId>` when `from` is given, which is
    what "Re-run config" posts through in Task 10.

- [ ] **Step 1: Write the failing tests**

Add to `web/src/features/runs/RunsPage.test.tsx`:

```tsx
it("pins the in-flight run above the list", async () => {
  server.use(
    http.get("/api/runs", () =>
      HttpResponse.json(makeRunPage([makeRunSummary({ runId: "20260829T090000Z" })])),
    ),
    http.get("/api/runs/active", () =>
      HttpResponse.json(makeActiveRuns({ current: "20260829T140200Z" })),
    ),
    http.get("/api/runs/:runId", () =>
      HttpResponse.json(
        makeRunDetail({
          runId: "20260829T140200Z",
          status: "running",
          stages: [
            makeStageRecord({ stage: "ingest" }),
            makeStageRecord({
              stage: "analyse",
              status: "running",
              finishedAt: null,
              done: 17,
              total: 25,
            }),
          ],
        }),
      ),
    ),
  );

  renderWithProviders(<RunsPage />);

  expect(await screen.findByText("RUNNING")).toBeInTheDocument();
  expect(screen.getByText("20260829T140200Z")).toBeInTheDocument();
  // Every stage named beneath its segment, so a glance says how far in it is.
  for (const stage of ["ingest", "analyse", "evaluate", "generate"]) {
    expect(screen.getByText(stage)).toBeInTheDocument();
  }
});

it("draws no in-flight card while nothing is running", async () => {
  server.use(
    http.get("/api/runs", () => HttpResponse.json(makeRunPage())),
    http.get("/api/runs/active", () =>
      HttpResponse.json(makeActiveRuns({ current: null })),
    ),
  );

  renderWithProviders(<RunsPage />);
  await screen.findByRole("heading", { name: "Runs" });

  expect(screen.queryByText("RUNNING")).not.toBeInTheDocument();
});

it("offers New run from the header", async () => {
  server.use(
    http.get("/api/runs", () => HttpResponse.json(makeRunPage())),
    http.get("/api/runs/active", () => HttpResponse.json(makeActiveRuns())),
  );

  renderWithProviders(<RunsPage />);

  expect(await screen.findByRole("link", { name: "New run" })).toHaveAttribute(
    "href",
    "/runs/new",
  );
});

it("offers New run from the empty state, which is the only thing to do there", async () => {
  server.use(
    http.get("/api/runs", () => HttpResponse.json(makeRunPage([]))),
    http.get("/api/runs/active", () => HttpResponse.json(makeActiveRuns())),
  );

  renderWithProviders(<RunsPage />);

  expect(await screen.findByText("Nothing has run yet")).toBeInTheDocument();
  expect(screen.getAllByRole("link", { name: "New run" })).toHaveLength(2);
});
```

Add to `web/src/features/topics/TopicsPage.test.tsx`:

```tsx
it("shows the last three runs beside the mood bar", async () => {
  server.use(
    http.get("/api/topics", () => HttpResponse.json(makeTopicIndex())),
    http.get("/api/runs", () =>
      HttpResponse.json(
        makeRunPage([
          makeRunSummary({ runId: "20260829T090000Z" }),
          makeRunSummary({ runId: "20260828T090000Z", status: "failed" }),
        ]),
      ),
    ),
    http.get("/api/runs/active", () => HttpResponse.json(makeActiveRuns())),
  );

  renderWithProviders(<TopicsPage />);

  const strip = await screen.findByTestId("run-strip");
  expect(within(strip).getByText("…829T090000Z")).toBeInTheDocument();
  expect(within(strip).getByText("…828T090000Z")).toBeInTheDocument();
});

it("marks only the active run's row, whatever the list says about it", async () => {
  server.use(
    http.get("/api/topics", () => HttpResponse.json(makeTopicIndex())),
    http.get("/api/runs", () =>
      HttpResponse.json(
        makeRunPage([
          makeRunSummary({ runId: "20260829T140200Z", status: "running" }),
          makeRunSummary({ runId: "20260828T090000Z", status: "ok" }),
        ]),
      ),
    ),
    http.get("/api/runs/active", () =>
      HttpResponse.json(makeActiveRuns({ current: "20260829T140200Z" })),
    ),
    http.get("/api/runs/:runId", () =>
      HttpResponse.json(
        makeRunDetail({ runId: "20260829T140200Z", status: "running" }),
      ),
    ),
  );

  renderWithProviders(<TopicsPage />);

  const strip = await screen.findByTestId("run-strip");
  const live = within(strip).getByRole("link", { name: /829T140200Z/ });
  const over = within(strip).getByRole("link", { name: /828T090000Z/ });

  // The accent treatment is the only thing `activeRunId` decides: a run in
  // flight already carries the status `running` in its own row, so
  // asserting the word alone would pass with the prop removed entirely.
  expect(live).toHaveClass(styles.running);
  expect(over).not.toHaveClass(styles.running);
});

it("asks for only the three runs the strip draws", async () => {
  // `RunStrip` maps over what it is given with no slice of its own, so the
  // cap is the query's `limit` and this is the only place it is enforced.
  // Raise it to `DEFAULT_RUN_LIMIT` and twenty-five rows appear beside a
  // mood bar sized for three, with no other test noticing.
  let limit: string | null = null;
  server.use(
    http.get("/api/topics", () => HttpResponse.json(makeTopicIndex())),
    http.get("/api/runs", ({ request }) => {
      limit = new URL(request.url).searchParams.get("limit");
      return HttpResponse.json(makeRunPage());
    }),
    http.get("/api/runs/active", () => HttpResponse.json(makeActiveRuns())),
  );

  renderWithProviders(<TopicsPage />);
  await screen.findByTestId("run-strip");

  expect(limit).toBe("3");
});
```

The first of these imports the stylesheet it asserts against:

```tsx
import styles from "@/features/runs/RunStrip.module.css";
```

Vitest runs with `css: false`, so that import is a proxy handing back a
manufactured class name for any key — which is exactly what makes
`toHaveClass(styles.running)` a real assertion here rather than a string
comparison against a hardcoded name that could drift.

Every existing test in both modules now needs a `/api/runs/active` handler,
because both pages fetch it. Add one returning `makeActiveRuns()` to each —
`onUnhandledRequest: "error"` will name any that is missing.

Both modules also need `within` from `@testing-library/react`, and
`TopicsPage.test.tsx` needs `makeRunDetail`, `makeRunSummary`, `makeRunPage`
and `makeActiveRuns` from `@/test/factories` plus the `RunStrip` stylesheet
import named above.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
npm --prefix web test -- --run src/features/runs/RunsPage.test.tsx src/features/topics/TopicsPage.test.tsx
```

Expected: FAIL — no `RUNNING` badge, no `run-strip`.

- [ ] **Step 3: Write `NewRunButton`**

Create `web/src/features/newrun/NewRunButton.tsx`:

```tsx
import { Link } from "react-router-dom";

import styles from "./NewRunButton.module.css";

/**
 * The accent pill on the Topics and Runs headers.
 *
 * `from` carries a run id into the New run screen, which is how "Re-run
 * config" reaches it: the screen reads that run's frozen `RunConfig` and
 * prefills every card from it, rather than a second screen existing to do
 * the same job with different defaults.
 */
export function NewRunButton({ from }: { from?: string } = {}) {
  const to = from === undefined ? "/runs/new" : `/runs/new?from=${encodeURIComponent(from)}`;
  return (
    <Link to={to} className={styles.button}>
      New run
    </Link>
  );
}
```

Create `web/src/features/newrun/NewRunButton.module.css`:

```css
.button {
  display: inline-block;
  padding: 9px 16px;
  border-radius: var(--radius-pill);
  background: var(--accent);
  font-family: var(--font-ui);
  font-size: 12px;
  font-weight: 700;
  line-height: 1;
  color: var(--on-accent);
  transition: filter var(--transition);
}

.button:hover {
  filter: brightness(0.94);
}
```

- [ ] **Step 4: Write `InFlightCard`**

Create `web/src/features/runs/InFlightCard.tsx`:

```tsx
import { Link } from "react-router-dom";

import { STAGES } from "@/api/types";
import { useRun } from "@/api/queries";
import { StageBar } from "@/components/StageBar";
import { StatusPill } from "@/components/StatusPill";
import { activeStage, byStage, stageFill } from "@/features/runs/progress";
import { useNow } from "@/features/runs/useNow";
import { formatElapsed } from "@/format";

import styles from "./InFlightCard.module.css";

/**
 * The card pinned above the Runs list while a run is in flight.
 *
 * Four segments rather than one bar, because the four stages are the unit
 * anyone reasons about a run in: a single 43% bar says less than "ingest
 * and analyse are done, evaluate is going".
 *
 * Returns null rather than a skeleton while the run's detail is still
 * loading. The card appearing a moment late is invisible; a placeholder
 * card that then becomes a real one is a layout shift on the screen's most
 * prominent element.
 */
export function InFlightCard({ runId }: { runId: string }) {
  const run = useRun(runId);
  const now = useNow(true);

  if (run.data === undefined) return null;

  const stages = byStage(run.data.stages);
  const current = activeStage(run.data.stages);

  return (
    <Link to={`/runs/${encodeURIComponent(runId)}`} className={styles.card}>
      <div className={styles.head}>
        <StatusPill status="running" />
        <span className={styles.runId}>{runId}</span>
        <span className={styles.elapsed}>
          {formatElapsed(run.data.run.started_at, now)}
        </span>
        {current !== undefined && <span className={styles.stage}>{current}</span>}
      </div>

      <div className={styles.segments}>
        {STAGES.map((stage) => (
          <div key={stage} className={styles.segment}>
            <StageBar fill={stageFill(stages.get(stage))} />
            <span className={styles.segmentName}>{stage}</span>
          </div>
        ))}
      </div>
    </Link>
  );
}
```

Create `web/src/features/runs/InFlightCard.module.css`:

```css
.card {
  display: flex;
  flex-direction: column;
  gap: var(--gap-section);
  padding: 16px 18px;
  border: 1px solid var(--accent-border-soft);
  border-radius: var(--radius-card);
  background: var(--accent-wash);
  transition: border-color var(--transition);
}

.card:hover {
  border-color: var(--accent-border);
}

.head {
  display: flex;
  align-items: center;
  gap: 10px;
}

.runId {
  font-family: var(--font-mono);
  font-size: 12px;
  font-weight: 600;
  color: var(--text);
}

.elapsed {
  font-family: var(--font-mono);
  font-size: 10.5px;
  color: var(--accent);
}

.stage {
  font-family: var(--font-mono);
  font-size: 10.5px;
  color: var(--text-35);
}

.segments {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 4px;
}

.segment {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.segmentName {
  font-family: var(--font-mono);
  font-size: 9.5px;
  font-weight: 600;
  letter-spacing: 0.12em;
  color: var(--text-35);
}
```

- [ ] **Step 5: Write `RunStrip`**

Create `web/src/features/runs/RunStrip.tsx`:

```tsx
import { Link } from "react-router-dom";

import type { RunSummary } from "@/api/types";
import { formatRelative, shortRunId } from "@/format";

import styles from "./RunStrip.module.css";

/**
 * Three rows, per the handoff. The running one takes the accent border and
 * wash, which is the only difference between the rows.
 *
 * `state` is the run's own status rather than a rephrasing of it: `ok`,
 * `failed`, `aborted`, `interrupted`, `running` are the words the rest of
 * the app uses for these, and inventing friendlier ones here would mean two
 * vocabularies for one set of states.
 */
export function RunStrip({
  runs,
  activeRunId,
}: {
  runs: RunSummary[];
  activeRunId: string | null;
}) {
  return (
    <ul className={styles.strip} data-testid="run-strip">
      {runs.map((summary) => {
        const running = summary.run.run_id === activeRunId;
        return (
          <li key={summary.run.run_id}>
            <Link
              to={`/runs/${encodeURIComponent(summary.run.run_id)}`}
              className={[styles.row, running ? styles.running : ""]
                .filter(Boolean)
                .join(" ")}
            >
              <span
                className={[styles.dot, running ? styles.dotRunning : ""]
                  .filter(Boolean)
                  .join(" ")}
              />
              <span className={styles.runId}>{shortRunId(summary.run.run_id)}</span>
              <span className={styles.state}>
                {running ? "running" : summary.run.status}
              </span>
              <span className={styles.when}>
                {formatRelative(summary.run.finished_at ?? summary.run.started_at)}
              </span>
            </Link>
          </li>
        );
      })}
    </ul>
  );
}
```

Create `web/src/features/runs/RunStrip.module.css`:

```css
.strip {
  display: flex;
  flex-direction: column;
  gap: 7px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.row {
  display: grid;
  grid-template-columns: 6px 1fr auto auto;
  align-items: center;
  gap: 9px;
  padding: 9px 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius-panel);
  background: var(--surface);
  transition: border-color var(--transition);
}

.row:hover {
  border-color: var(--border-hover);
}

.running {
  border-color: var(--accent-border);
  background: var(--accent-wash);
}

.dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--text-30);
}

.dotRunning {
  background: var(--accent);
}

.runId {
  font-family: var(--font-mono);
  font-size: 11px;
  font-weight: 500;
  color: var(--text-70);
}

.state {
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--text-55);
}

.when {
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--text-35);
}
```

- [ ] **Step 6: Wire both pages**

In `web/src/features/runs/RunsPage.tsx`, add the imports:

```tsx
import { useActiveRun, useRuns } from "@/api/queries";
import { InFlightCard } from "@/features/runs/InFlightCard";
import { NewRunButton } from "@/features/newrun/NewRunButton";
```

read the active run in the component:

```tsx
export function RunsPage() {
  const query = useRuns();
  const active = useActiveRun();
  const activeRunId = active.data?.current ?? null;
```

give the header its button:

```tsx
          <header className={styles.header}>
            <div className={styles.titleRow}>
              <h1 className={styles.title}>Runs</h1>
              <NewRunButton />
            </div>
            {page.runs.length > 0 && <MetaLine>{summarise(page.runs)}</MetaLine>}
          </header>

          {activeRunId !== null && <InFlightCard runId={activeRunId} />}
```

and give the empty state its action:

```tsx
            <EmptyState
              headline="Nothing has run yet"
              body="A run reads Bluesky, works out what is trending, and generates memes about it. The first one takes a few minutes."
              action={<NewRunButton />}
            />
```

Add `.titleRow` to `RunsPage.module.css`:

```css
.titleRow {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--gap-section);
}
```

In `web/src/features/topics/TopicsPage.tsx`, add the same imports plus
`RunStrip`, read `useActiveRun()`, put a `NewRunButton` in the header row
beside "Right now", and add the strip beside the mood bar:

```tsx
                <div className={styles.bottom}>
                  <div className={styles.mood}>
                    <SectionLabel>The mood today</SectionLabel>
                    <MoodBar
                      totals={data.sentiment_totals}
                      previous={data.previous_sentiment_totals}
                    />
                  </div>
                  <div className={styles.runs}>
                    <SectionLabel>Runs</SectionLabel>
                    <RunStrip
                      runs={runs.data?.runs ?? []}
                      activeRunId={active.data?.current ?? null}
                    />
                  </div>
                </div>
```

with `.bottom` in `TopicsPage.module.css`:

```css
/* The handoff's `1fr 320px`: the mood bar wants the width, the strip does
   not. */
.bottom {
  display: grid;
  grid-template-columns: 1fr 320px;
  gap: 18px;
  align-items: start;
}

.runs {
  display: flex;
  flex-direction: column;
  gap: 9px;
}
```

The existing `.mood` wrapper stays; it moves inside `.bottom`.

Also give the empty state on Topics the same action:

```tsx
              <EmptyState
                headline="Nothing has run yet"
                body="A run reads Bluesky, works out what is trending, and generates memes about it. The first one takes a few minutes."
                action={<NewRunButton />}
              />
```

- [ ] **Step 7: Run the tests to verify they pass**

```bash
npm --prefix web test -- --run src/features/runs src/features/topics
```

Expected: PASS.

- [ ] **Step 8: Run the whole web gate**

```bash
npm --prefix web run lint && npm --prefix web run typecheck && npm --prefix web test
```

Expected: all PASS.

- [ ] **Step 9: Commit**

```bash
git add web/src/features/runs web/src/features/topics web/src/features/newrun
git commit -m "feat: the in-flight card, the run strip, and a way to start a run"
```

---

### Task 10: run detail, in flight

The same screen as the completed one — identical stage cards, identical
ranking grid — with the differences that follow from the run still being
live. Once it completes, this screen *is* the completed one: bars go solid,
the log stops following, header actions swap to Re-run config / Resume.

**Files:**
- Create: `web/src/features/runs/RunActions.tsx` + `.module.css`
- Modify: `web/src/features/runs/RunDetailPage.tsx` + `.module.css`
- Modify: `web/src/features/runs/RankingList.tsx` + `.module.css`
- Test: `web/src/features/runs/RunDetailPage.test.tsx`

**Interfaces:**
- Consumes: `useRun`, `useRanking`, `useActiveRun`, `useRunEvents`,
  `useRunLog`, `useStopRun`, `useAbortRun`, `useResumeRun`; `LiveLog`;
  `InlineConfirm`; `NewRunButton`; `useNow`; `formatClock`,
  `formatElapsed`, `formatDuration`.
- Produces: `RunActions({ detail, live }): JSX.Element`. `RankingList`
  gains a `distilling?: boolean` prop.

- [ ] **Step 1: Write the failing tests**

Add to `web/src/features/runs/RunDetailPage.test.tsx` (alongside Task 6's
two card-state tests):

This module needs `act`, `waitFor` and `within` from
`@testing-library/react`, `userEvent`, `vi` from `vitest`, `FakeEventSource`
from `@/test/eventsource`, and `makeActiveRuns`, `makeLogLine`,
`makeQueuedRun` and `makeStageRecord` from `@/test/factories`.

```tsx
/** Every handler a live run's detail page asks for. */
function liveRun(overrides: Partial<Parameters<typeof makeRunDetail>[0]> = {}) {
  return [
    http.get("/api/runs/:runId", () =>
      HttpResponse.json(
        makeRunDetail({
          runId: "20260829T140200Z",
          status: "running",
          finishedAt: null,
          stages: [
            makeStageRecord({ stage: "ingest" }),
            makeStageRecord({
              stage: "analyse",
              status: "running",
              finishedAt: null,
              done: 17,
              total: 25,
            }),
          ],
          ...overrides,
        }),
      ),
    ),
    http.get("/api/runs/:runId/topics", () => HttpResponse.json([])),
    http.get("/api/runs/active", () =>
      HttpResponse.json(makeActiveRuns({ current: "20260829T140200Z" })),
    ),
  ];
}

function renderDetail(runId = "20260829T140200Z") {
  return renderWithProviders(<RunDetailPage />, {
    route: `/runs/${runId}`,
    path: "/runs/:runId",
  });
}

it("counts up while the run is live, and says when it started", async () => {
  // The fixture's `started_at` is frozen, so the clock it is measured
  // against has to be too: comparing a fixed date to the real `new Date()`
  // makes the rendered elapsed time a function of the day the suite runs,
  // and a `/^t\+\d\d:\d\d$/` shape assertion would pass just as happily for
  // an elapsed computed off the wrong field or with the sign flipped.
  vi.useFakeTimers({ shouldAdvanceTime: true });
  vi.setSystemTime(new Date("2026-08-29T09:06:41Z"));
  try {
    server.use(...liveRun());

    renderDetail();

    expect(await screen.findByText("RUNNING")).toBeInTheDocument();
    expect(screen.getByText("t+06:41")).toBeInTheDocument();
    expect(screen.getByText(/started 09:00/)).toBeInTheDocument();
  } finally {
    vi.useRealTimers();
  }
});

it("says a queued run has not started", async () => {
  // A queued run's row says `running` too — `enqueue` opens it that way —
  // so `active.queued` is the only thing that separates the two, and this
  // notice is the only place the screen reads it.
  server.use(
    http.get("/api/runs/:runId", () =>
      HttpResponse.json(
        makeRunDetail({ runId: "20260829T150000Z", status: "running", stages: [] }),
      ),
    ),
    http.get("/api/runs/:runId/topics", () => HttpResponse.json([])),
    http.get("/api/runs/active", () =>
      HttpResponse.json(
        makeActiveRuns({
          current: "20260829T140200Z",
          queued: ["20260829T150000Z"],
        }),
      ),
    ),
  );

  renderDetail("20260829T150000Z");

  expect(
    await screen.findByText(
      "Waiting behind the run in flight. Nothing has started yet.",
    ),
  ).toBeInTheDocument();
});

it("does not call the run in flight queued", async () => {
  // The negative case, because a notice rendered unconditionally — or from
  // an inverted condition — would pass the test above while telling
  // everyone watching a live run that nothing had started.
  server.use(...liveRun());

  renderDetail();
  await screen.findByText("RUNNING");

  expect(
    screen.queryByText(/Waiting behind the run in flight/),
  ).not.toBeInTheDocument();
});

it("offers stop and abort while live, and neither afterwards", async () => {
  server.use(...liveRun());
  renderDetail();

  expect(
    await screen.findByRole("button", { name: "Stop after this stage" }),
  ).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Abort" })).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "New run" })).not.toBeInTheDocument();
});

it("stop needs no confirmation, because it is not destructive", async () => {
  const user = userEvent.setup();
  let stopped = "";
  server.use(
    ...liveRun(),
    http.post("/api/runs/:runId/stop", ({ params }) => {
      stopped = String(params.runId);
      return HttpResponse.json(
        { run_id: stopped, requested: "stop" },
        { status: 202 },
      );
    }),
  );
  renderDetail();

  await user.click(
    await screen.findByRole("button", { name: "Stop after this stage" }),
  );

  await waitFor(() => expect(stopped).toBe("20260829T140200Z"));
});

it("abort asks first, and aborts only when told twice", async () => {
  const user = userEvent.setup();
  let aborted = "";
  server.use(
    ...liveRun(),
    http.post("/api/runs/:runId/abort", ({ params }) => {
      aborted = String(params.runId);
      return HttpResponse.json(
        { run_id: aborted, requested: "abort" },
        { status: 202 },
      );
    }),
  );
  renderDetail();

  await user.click(await screen.findByRole("button", { name: "Abort" }));
  expect(screen.getByText("Abort run?")).toBeInTheDocument();
  expect(aborted).toBe("");

  await user.click(screen.getByRole("button", { name: "yes" }));
  await waitFor(() => expect(aborted).toBe("20260829T140200Z"));
});

it("streams the log while live", async () => {
  server.use(...liveRun());
  renderDetail();
  await screen.findByText("RUNNING");

  await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));
  act(() =>
    FakeEventSource.latest().emitLog([
      makeLogLine({ logger: "zeitgeist.analysis.distil", message: "Distilled 'cat'" }),
    ]),
  );

  expect(await screen.findByText("Distilled 'cat'")).toBeInTheDocument();
});

it("says the ranking is not decided yet while analyse is running", async () => {
  // The order is set in evaluate, so there is nothing honest to draw here
  // until the stage ends. Saying so beats an empty section.
  server.use(...liveRun());
  renderDetail();

  expect(
    await screen.findByText("Distilling — the ranking appears when analyse finishes."),
  ).toBeInTheDocument();
  expect(screen.getByText("final order is set in evaluate")).toBeInTheDocument();
});

it("reads a finished run's log from the server, and opens no stream", async () => {
  server.use(
    http.get("/api/runs/:runId", () => HttpResponse.json(makeRunDetail())),
    http.get("/api/runs/:runId/topics", () => HttpResponse.json([])),
    http.get("/api/runs/active", () => HttpResponse.json(makeActiveRuns())),
    http.get("/api/runs/:runId/log", () =>
      HttpResponse.json([makeLogLine({ message: "Fetched 25 trends" })]),
    ),
  );

  renderDetail("20260829T090000Z");

  expect(await screen.findByText("Fetched 25 trends")).toBeInTheDocument();
  expect(FakeEventSource.instances).toHaveLength(0);
});

it("offers Re-run config and Resume once a run is over", async () => {
  server.use(
    http.get("/api/runs/:runId", () =>
      HttpResponse.json(makeRunDetail({ resumeStage: "generate" })),
    ),
    http.get("/api/runs/:runId/topics", () => HttpResponse.json([])),
    http.get("/api/runs/active", () => HttpResponse.json(makeActiveRuns())),
    http.get("/api/runs/:runId/log", () => HttpResponse.json([])),
  );

  renderDetail("20260829T090000Z");

  expect(await screen.findByRole("link", { name: "New run" })).toHaveAttribute(
    "href",
    "/runs/new?from=20260829T090000Z",
  );
  expect(
    screen.getByRole("button", { name: "Resume from generate" }),
  ).toBeInTheDocument();
});

it("hides Resume entirely when there is nothing to resume from", async () => {
  // A source outage: ingest returned nothing, so no checkpoint exists. The
  // spec is explicit that the button is absent rather than disabled — a
  // disabled control still says the action exists.
  server.use(
    http.get("/api/runs/:runId", () =>
      HttpResponse.json(
        makeRunDetail({
          status: "failed",
          resumeStage: null,
          error: { kind: "SourceError", message: "no trends returned", stage: "ingest" },
        }),
      ),
    ),
    http.get("/api/runs/:runId/topics", () => HttpResponse.json([])),
    http.get("/api/runs/active", () => HttpResponse.json(makeActiveRuns())),
    http.get("/api/runs/:runId/log", () => HttpResponse.json([])),
  );

  renderDetail("20260829T090000Z");

  await screen.findByText("FAILED");
  expect(screen.queryByRole("button", { name: /Resume/ })).not.toBeInTheDocument();
  expect(screen.getByRole("link", { name: "New run" })).toBeInTheDocument();
});

it("resumes from the computed stage without naming one", async () => {
  // The button posts an empty body: `resume_stage` is the server's own
  // computation, and a client that echoed it back could send a stale one.
  const user = userEvent.setup();
  let body: unknown = null;
  server.use(
    http.get("/api/runs/:runId", () =>
      HttpResponse.json(makeRunDetail({ resumeStage: "generate" })),
    ),
    http.get("/api/runs/:runId/topics", () => HttpResponse.json([])),
    http.get("/api/runs/active", () => HttpResponse.json(makeActiveRuns())),
    http.get("/api/runs/:runId/log", () => HttpResponse.json([])),
    http.post("/api/runs/:runId/resume", async ({ request }) => {
      body = await request.json();
      return HttpResponse.json(makeQueuedRun({ runId: "20260829T090000Z" }), {
        status: 202,
      });
    }),
  );

  renderDetail("20260829T090000Z");
  await user.click(
    await screen.findByRole("button", { name: "Resume from generate" }),
  );

  await waitFor(() => expect(body).toEqual({}));
});

it("reports a refused action rather than swallowing it", async () => {
  // The 409 the server answers a double-clicked Resume with. Silence here
  // would leave someone clicking a button that has already worked.
  const user = userEvent.setup();
  server.use(
    http.get("/api/runs/:runId", () =>
      HttpResponse.json(makeRunDetail({ resumeStage: "generate" })),
    ),
    http.get("/api/runs/:runId/topics", () => HttpResponse.json([])),
    http.get("/api/runs/active", () => HttpResponse.json(makeActiveRuns())),
    http.get("/api/runs/:runId/log", () => HttpResponse.json([])),
    http.post("/api/runs/:runId/resume", () =>
      HttpResponse.json(
        { detail: "Run 20260829T090000Z is already queued or executing" },
        { status: 409 },
      ),
    ),
  );

  renderDetail("20260829T090000Z");
  await user.click(
    await screen.findByRole("button", { name: "Resume from generate" }),
  );

  expect(
    await screen.findByText("Run 20260829T090000Z is already queued or executing"),
  ).toBeInTheDocument();
});
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
npm --prefix web test -- --run src/features/runs/RunDetailPage.test.tsx
```

Expected: FAIL — no `RUNNING` header treatment, no action buttons, no log.

- [ ] **Step 3: Write `RunActions`**

Create `web/src/features/runs/RunActions.tsx`:

```tsx
import type { RunDetail } from "@/api/types";
import { useAbortRun, useResumeRun, useStopRun } from "@/api/queries";
import { InlineConfirm } from "@/components/InlineConfirm";
import { NewRunButton } from "@/features/newrun/NewRunButton";

import styles from "./RunActions.module.css";

/**
 * The header's button pair, in both of the run's lives.
 *
 * Live: **Stop after this stage** and **Abort**. Stop carries no confirm —
 * it lets the current stage write its checkpoint and leaves the run
 * resumable, so it destroys nothing. Abort does, and asks.
 *
 * Over: **Re-run config**, which is `NewRunButton` carrying this run's id
 * so the New run screen prefills from its frozen `RunConfig`; and
 * **Resume from &lt;stage&gt;**, whose stage name is computed by the server
 * and is therefore absent — not disabled — when there is nothing to resume
 * from. A disabled control still says the action exists.
 *
 * A refused action is reported where it happened. All three of these can
 * come back 409 (a double click, a second tab, a run that ended between
 * the render and the click) and the sentence the server sends is the only
 * thing that distinguishes them.
 */
export function RunActions({ detail, live }: { detail: RunDetail; live: boolean }) {
  const runId = detail.run.run_id;
  const stop = useStopRun(runId);
  const abort = useAbortRun(runId);
  const resume = useResumeRun(runId);

  const failure = stop.error ?? abort.error ?? resume.error ?? null;

  return (
    <div className={styles.actions}>
      {live ? (
        <>
          <button
            type="button"
            className={styles.ghost}
            disabled={stop.isPending}
            onClick={() => stop.mutate()}
          >
            Stop after this stage
          </button>
          <InlineConfirm
            label="Abort"
            question="Abort run?"
            onConfirm={() => abort.mutate()}
          />
        </>
      ) : (
        <>
          <NewRunButton from={runId} />
          {detail.resume_stage !== null && (
            <button
              type="button"
              className={styles.accent}
              disabled={resume.isPending}
              // An empty body: the stage is the server's own computation
              // (`resume_stage`), and echoing it back could send a stale
              // one if the run gained a checkpoint since this render.
              onClick={() => resume.mutate({})}
            >
              Resume from {detail.resume_stage}
            </button>
          )}
        </>
      )}
      {failure !== null && <p className={styles.failure}>{failure.detail}</p>}
    </div>
  );
}
```

Create `web/src/features/runs/RunActions.module.css`:

```css
.actions {
  display: flex;
  align-items: center;
  gap: var(--gap-tight);
  flex-wrap: wrap;
  justify-content: flex-end;
}

.ghost {
  padding: 8px 14px;
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-pill);
  background: none;
  font-family: var(--font-ui);
  font-size: 12px;
  font-weight: 700;
  line-height: 1;
  color: var(--text-70);
  cursor: pointer;
  transition: border-color var(--transition), color var(--transition);
}

.ghost:hover:not(:disabled) {
  border-color: var(--border-hover);
  color: var(--text);
}

.accent {
  padding: 9px 16px;
  border: none;
  border-radius: var(--radius-pill);
  background: var(--accent);
  font-family: var(--font-ui);
  font-size: 12px;
  font-weight: 700;
  line-height: 1;
  color: var(--on-accent);
  cursor: pointer;
  transition: filter var(--transition);
}

.accent:hover:not(:disabled) {
  filter: brightness(0.94);
}

.ghost:disabled,
.accent:disabled {
  opacity: 0.5;
  cursor: default;
}

.failure {
  flex-basis: 100%;
  margin: 0;
  text-align: right;
  font-family: var(--font-mono);
  font-size: 10.5px;
  color: var(--contrast-light);
}
```

- [ ] **Step 4: Rewrite the page**

Replace `web/src/features/runs/RunDetailPage.tsx`:

```tsx
import { useState } from "react";
import { useParams } from "react-router-dom";

import type { RankedTopic, RunDetail, StageRecord } from "@/api/types";
import {
  useActiveRun,
  useRanking,
  useRun,
  useRunEvents,
  useRunLog,
} from "@/api/queries";
import { Breadcrumb } from "@/components/Breadcrumb";
import { MetaLine } from "@/components/MetaLine";
import { QueryBoundary } from "@/components/QueryBoundary";
import { StatusPill } from "@/components/StatusPill";
import { LiveLog } from "@/features/runs/LiveLog";
import { RankingList } from "@/features/runs/RankingList";
import { RunActions } from "@/features/runs/RunActions";
import { StageCards } from "@/features/runs/StageCards";
import { activeStage } from "@/features/runs/progress";
import { survivedFor } from "@/features/runs/survived";
import { useNow } from "@/features/runs/useNow";
import { formatClock, formatDuration, formatElapsed, shortRunId } from "@/format";

import styles from "./RunDetailPage.module.css";

/**
 * Sources, the three fan-out numbers, the model, and either how long it
 * took or when it started.
 *
 * A live run has no duration to report, and `formatDuration` correctly
 * answers `—` for one. An em dash at the end of the config line reads as a
 * missing value; `started 14:02` is what a run that has not finished
 * actually knows about its own clock.
 */
function configLine(detail: RunDetail, live: boolean): string {
  const { run } = detail;
  const config = run.config;
  return [
    config.sources.join(" · "),
    `trend_limit ${config.trend_limit}`,
    `posts_per_trend ${config.posts_per_trend}`,
    `top_count ${config.top_count}`,
    config.llm_model,
    live
      ? `started ${formatClock(run.started_at)}`
      : formatDuration(run.started_at, run.finished_at),
  ].join(" · ");
}

/**
 * The generate stage ran and produced nothing.
 *
 * Both halves are needed: a run that died in analyse also has zero renders,
 * and telling that user every brief failed would send them looking for a
 * renderer problem that does not exist.
 */
function everyBriefFailed(stages: StageRecord[], ranking: RankedTopic[]): boolean {
  const generate = stages.find((stage) => stage.stage === "generate");
  if (
    generate === undefined ||
    generate.status === "queued" ||
    generate.status === "running"
  ) {
    return false;
  }
  return ranking.length > 0 && ranking.every((entry) => entry.render_count === 0);
}

export function RunDetailPage() {
  const { runId } = useParams();
  const run = useRun(runId);
  const ranking = useRanking(runId);
  const active = useActiveRun();
  const [verbose, setVerbose] = useState(false);

  // The run's own row, not `active`: a run that has just ended is no longer
  // current, and the screen must stop following it the moment its status
  // settles rather than one poll later. `active` is still read, because a
  // queued run's row also says `running` and only `active.queued` tells the
  // two apart for the sidebar — this screen treats both as live, which is
  // right: a queued run has an open stream and a working abort.
  const live = run.data?.run.status === "running";
  const streamed = useRunEvents(runId, live);
  const history = useRunLog(runId, verbose, !live);
  const now = useNow(live);

  return (
    <QueryBoundary query={run} missing="No such run.">
      {(detail) => {
        const current = activeStage(detail.stages);
        const queued = active.data?.queued.includes(detail.run.run_id) ?? false;
        return (
          <div className={styles.page}>
            <Breadcrumb
              trail={[
                { label: "Runs", to: "/runs" },
                // Shortened rather than the mockup's full id: the header
                // two lines down already shows it in full, and `findByText`
                // (and a reader's eye) needs the run id to appear once, not
                // twice, in identical text.
                { label: shortRunId(detail.run.run_id) },
              ]}
            />

            <header className={styles.header}>
              <div className={styles.headRow}>
                <div className={styles.identity}>
                  <StatusPill status={detail.run.status} />
                  <span className={styles.runId}>{detail.run.run_id}</span>
                  {live && (
                    <span className={styles.elapsed}>
                      {formatElapsed(detail.run.started_at, now)}
                    </span>
                  )}
                </div>
                <RunActions detail={detail} live={live} />
              </div>
              <MetaLine>{configLine(detail, live)}</MetaLine>
              {queued && (
                <p className={styles.queued}>
                  Waiting behind the run in flight. Nothing has started yet.
                </p>
              )}
              {detail.run.error !== null && (
                <p className={styles.error}>
                  {detail.run.error.kind} in {detail.run.error.stage} —{" "}
                  {detail.run.error.message} · {survivedFor(detail.run.error.stage)}
                </p>
              )}
            </header>

            <StageCards stages={detail.stages} />

            <QueryBoundary query={ranking} missing="No such run.">
              {(rows) =>
                rows.length === 0 ? (
                  live ? (
                    <RankingList
                      ranking={[]}
                      topCount={detail.run.config.top_count}
                      everyBriefFailed={false}
                      distilling={current === "ingest" || current === "analyse"}
                    />
                  ) : (
                    <p className={styles.noRanking}>
                      This run wrote no ranking — it did not reach evaluate.
                    </p>
                  )
                ) : (
                  <RankingList
                    ranking={rows}
                    topCount={detail.run.config.top_count}
                    everyBriefFailed={everyBriefFailed(detail.stages, rows)}
                  />
                )
              }
            </QueryBoundary>

            <LiveLog
              lines={live ? streamed : (history.data ?? [])}
              live={live}
              verbose={verbose}
              onVerboseChange={setVerbose}
            />
          </div>
        );
      }}
    </QueryBoundary>
  );
}
```

Append to `web/src/features/runs/RunDetailPage.module.css`:

```css
.headRow {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--gap-section);
}

.elapsed {
  font-family: var(--font-mono);
  font-size: 11px;
  font-weight: 600;
  color: var(--accent);
}

.queued {
  margin: 0;
  font-family: var(--font-mono);
  font-size: 10.5px;
  color: var(--text-35);
}
```

- [ ] **Step 5: Give `RankingList` its distilling state**

In `web/src/features/runs/RankingList.tsx`, add the prop and the branch:

```tsx
export function RankingList({
  ranking,
  topCount,
  everyBriefFailed,
  distilling = false,
}: {
  ranking: RankedTopic[];
  topCount: number;
  everyBriefFailed: boolean;
  /**
   * Ingest or analyse is running and no rows exist yet.
   *
   * The design draws rows appending as topics are distilled. Persisting a
   * half-scored topic needs a rank that does not exist until every topic
   * has been distilled and scored, which is a contract change with its own
   * questions — see the phase 6 plan, "Decisions", 2. So the section says
   * what is happening and where the order comes from, and the live log
   * carries the per-topic detail in the meantime.
   */
  distilling?: boolean;
}) {
  const below = ranking.filter((entry) => !entry.above_cut).length;

  return (
    <section className={styles.section}>
      <SectionLabel
        hint={
          distilling ? "final order is set in evaluate" : `top ${topCount} of ${ranking.length}`
        }
      >
        Ranking
      </SectionLabel>

      {distilling && (
        <p className={styles.distilling}>
          Distilling — the ranking appears when analyse finishes.
        </p>
      )}
      ...
```

Append to `web/src/features/runs/RankingList.module.css`:

```css
.distilling {
  margin: 0;
  padding: 14px 16px;
  border: 1px dashed var(--accent-border);
  border-radius: var(--radius-panel);
  font-family: var(--font-ui);
  font-size: 12.5px;
  color: var(--text-55);
}
```

- [ ] **Step 6: Run the tests to verify they pass**

```bash
npm --prefix web test -- --run src/features/runs/RunDetailPage.test.tsx
```

Expected: PASS, including Task 6's two stage-card tests.

- [ ] **Step 7: Run the whole web gate**

```bash
npm --prefix web run lint && npm --prefix web run typecheck && npm --prefix web test
```

Expected: all PASS.

- [ ] **Step 8: Commit**

```bash
git add web/src/features/runs
git commit -m "feat: run detail, live — stop, abort, resume and the streaming log"
```

---

### Task 11: the New run screen

Four config cards, a queue notice, and a button that starts a run and
navigates to it. "Re-run config" arrives here as `?from=<runId>` and
prefills every card from that run's frozen `RunConfig`, which is why there
is one screen rather than two.

**Files:**
- Modify: `web/src/features/newrun/NewRunPage.tsx` (replacing the
  placeholder) + `.module.css`
- Create: `web/src/features/newrun/ModelCard.tsx` + `.module.css`
- Create: `web/src/features/newrun/PlatformCard.tsx` + `.module.css`
- Create: `web/src/features/newrun/CountCard.tsx` + `.module.css`
- Create: `web/src/features/newrun/TemplateCard.tsx` + `.module.css`
- Test: `web/src/features/newrun/NewRunPage.test.tsx`

**Interfaces:**
- Consumes: `useConfigOptions`, `useActiveRun`, `useRun`, `useStartRun`;
  `Breadcrumb`, `MetaLine`, `SectionLabel`, `QueryBoundary`, `Chip`;
  `shortRunId`.
- Produces:
  - `ModelCard({ models, provider, model, keyPresent, onProvider, onModel })`
  - `PlatformCard({ platforms, selected, onSelect })`
  - `CountCard({ count, trendLimit, onCount })`
  - `TemplateCard({ templates, selected, onSelect })` where `selected` is
    `string[] | null` and `null` means the whole library.

- [ ] **Step 1: Write the failing test**

Create `web/src/features/newrun/NewRunPage.test.tsx`:

```tsx
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";

import { NewRunPage } from "@/features/newrun/NewRunPage";
import {
  makeActiveRuns,
  makeConfigOptions,
  makeQueuedRun,
  makeRunDetail,
} from "@/test/factories";
import { renderWithProviders } from "@/test/render";
import { server } from "@/test/server";

function options(overrides = {}) {
  return http.get("/api/config/options", () =>
    HttpResponse.json(makeConfigOptions(overrides)),
  );
}

function idle() {
  return http.get("/api/runs/active", () =>
    HttpResponse.json(makeActiveRuns({ current: null })),
  );
}

describe("NewRunPage", () => {
  it("swaps the model list when the provider changes", async () => {
    // The one behaviour the handoff calls out in bold. Ollama shows local
    // model tags, not Claude ids.
    const user = userEvent.setup();
    server.use(options(), idle());

    renderWithProviders(<NewRunPage />, { route: "/runs/new" });
    expect(await screen.findByRole("radio", { name: /claude-opus-5/ })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "ollama" }));

    expect(screen.getByRole("radio", { name: /qwen3.5:latest/ })).toBeInTheDocument();
    expect(screen.queryByRole("radio", { name: /claude-opus-5/ })).not.toBeInTheDocument();
  });

  it("selects a model from the new provider when the old one does not exist there", async () => {
    // Otherwise the form would post `claude-sonnet-5` to ollama, and the
    // run would fail on the worker thread with a model nobody chose.
    const user = userEvent.setup();
    let sent: unknown = null;
    server.use(
      options(),
      idle(),
      http.post("/api/runs", async ({ request }) => {
        sent = await request.json();
        return HttpResponse.json(makeQueuedRun(), { status: 202 });
      }),
    );

    renderWithProviders(<NewRunPage />, { route: "/runs/new" });
    await screen.findByRole("button", { name: "ollama" });

    await user.click(screen.getByRole("button", { name: "ollama" }));
    await user.click(screen.getByRole("button", { name: /Start run/ }));

    await waitFor(() => expect(sent).not.toBeNull());
    expect(sent).toMatchObject({
      overrides: { llm_provider: "ollama", llm_model: "qwen3.5:latest" },
    });
  });

  it("shows the dormant platforms without letting them be picked", async () => {
    const user = userEvent.setup();
    server.use(options(), idle());

    renderWithProviders(<NewRunPage />, { route: "/runs/new" });

    const lemmy = await screen.findByRole("radio", { name: /lemmy/ });
    expect(lemmy).toBeDisabled();
    expect(screen.getByText("dormant · no clustering")).toBeInTheDocument();

    await user.click(lemmy);
    expect(screen.getByRole("radio", { name: /bluesky/ })).toBeChecked();
  });

  it("warns when the Anthropic key is missing", async () => {
    server.use(options({ anthropicKeyPresent: false }), idle());

    renderWithProviders(<NewRunPage />, { route: "/runs/new" });

    expect(
      await screen.findByText("ANTHROPIC_API_KEY is not set · this run would fail"),
    ).toBeInTheDocument();
  });

  it("does not warn when the key is there", async () => {
    // The negative case, because a card that ignored `keyPresent` and
    // always warned would pass the test above — and telling someone with a
    // working key that their run will fail is the worse of the two bugs.
    server.use(options({ anthropicKeyPresent: true }), idle());

    renderWithProviders(<NewRunPage />, { route: "/runs/new" });

    expect(
      await screen.findByText("key present · ANTHROPIC_API_KEY"),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("ANTHROPIC_API_KEY is not set · this run would fail"),
    ).not.toBeInTheDocument();
  });

  it("keeps the last good count when the custom box is emptied mid-edit", async () => {
    // `Number("")` is 0, and a run started with topic_count 0 renders
    // nothing. The box has to be allowed to be empty while someone retypes
    // it without the form reading the empty string as a number — which is
    // the whole reason `CountCard`'s guard exists, and nothing else here
    // touches the custom input at all.
    const user = userEvent.setup();
    let sent: unknown = null;
    server.use(
      options(),
      idle(),
      http.post("/api/runs", async ({ request }) => {
        sent = await request.json();
        return HttpResponse.json(makeQueuedRun(), { status: 202 });
      }),
    );

    renderWithProviders(<NewRunPage />, { route: "/runs/new" });

    const custom = await screen.findByLabelText("custom count");
    await user.type(custom, "7");
    await user.clear(custom);
    await user.click(screen.getByRole("button", { name: /Start run/ }));

    await waitFor(() =>
      expect(sent).toMatchObject({ overrides: { topic_count: "7" } }),
    );
  });

  it("sends null template ids for the whole library", async () => {
    // `all N` is not an explicit list of every template: null is what the
    // pipeline reads as "the whole library", and stays right as the
    // library changes.
    const user = userEvent.setup();
    let sent: unknown = null;
    server.use(
      options(),
      idle(),
      http.post("/api/runs", async ({ request }) => {
        sent = await request.json();
        return HttpResponse.json(makeQueuedRun(), { status: 202 });
      }),
    );

    renderWithProviders(<NewRunPage />, { route: "/runs/new" });
    await user.click(await screen.findByRole("button", { name: /Start run/ }));

    await waitFor(() => expect(sent).toMatchObject({ template_ids: null }));
  });

  it("names the count of templates it actually has", async () => {
    // The handoff says `all 4`; the repository ships a different number.
    // The chip is driven by the loaded manifests so it stays true.
    server.use(options(), idle());

    renderWithProviders(<NewRunPage />, { route: "/runs/new" });

    expect(await screen.findByRole("button", { name: "all 2" })).toBeInTheDocument();
  });

  it("sends the templates that were chosen instead", async () => {
    const user = userEvent.setup();
    let sent: unknown = null;
    server.use(
      options(),
      idle(),
      http.post("/api/runs", async ({ request }) => {
        sent = await request.json();
        return HttpResponse.json(makeQueuedRun(), { status: 202 });
      }),
    );

    renderWithProviders(<NewRunPage />, { route: "/runs/new" });
    await user.click(await screen.findByRole("button", { name: "drake" }));
    await user.click(screen.getByRole("button", { name: /Start run/ }));

    await waitFor(() => expect(sent).toMatchObject({ template_ids: ["drake"] }));
  });

  it("says what a new run would queue behind", async () => {
    server.use(
      options(),
      http.get("/api/runs/active", () =>
        HttpResponse.json(makeActiveRuns({ current: "20260829T140200Z" })),
      ),
    );

    renderWithProviders(<NewRunPage />, { route: "/runs/new" });

    expect(
      await screen.findByText(
        "A run is already in flight. Starting this one queues it behind …829T140200Z.",
      ),
    ).toBeInTheDocument();
  });

  it("goes to the run it just started", async () => {
    const user = userEvent.setup();
    server.use(
      options(),
      idle(),
      http.post("/api/runs", () =>
        HttpResponse.json(makeQueuedRun({ runId: "20260829T150000Z" }), { status: 202 }),
      ),
      http.get("/api/runs/:runId", () =>
        HttpResponse.json(
          makeRunDetail({ runId: "20260829T150000Z", status: "running" }),
        ),
      ),
      http.get("/api/runs/:runId/topics", () => HttpResponse.json([])),
    );

    renderWithProviders(<AppRoutes />, { route: "/runs/new" });
    await user.click(await screen.findByRole("button", { name: /Start run/ }));

    expect(await screen.findByText("20260829T150000Z")).toBeInTheDocument();
  });

  it("prefills every card from the run it is re-running", async () => {
    server.use(
      options(),
      idle(),
      http.get("/api/runs/:runId", () =>
        HttpResponse.json(
          makeRunDetail({
            runId: "20260829T090000Z",
            config: {
              llm_provider: "ollama",
              llm_model: "qwen3.5:latest",
              top_count: 10,
              template_ids: ["drake"],
            },
          }),
        ),
      ),
    );

    renderWithProviders(<NewRunPage />, {
      route: "/runs/new?from=20260829T090000Z",
    });

    expect(await screen.findByRole("radio", { name: /qwen3.5:latest/ })).toBeChecked();
    expect(screen.getByRole("button", { name: "10" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("button", { name: "drake" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("reports a refused start rather than navigating", async () => {
    const user = userEvent.setup();
    server.use(
      options(),
      idle(),
      http.post("/api/runs", () =>
        HttpResponse.json({ detail: "Not settable per run: db_path" }, { status: 400 }),
      ),
    );

    renderWithProviders(<NewRunPage />, { route: "/runs/new" });
    await user.click(await screen.findByRole("button", { name: /Start run/ }));

    expect(
      await screen.findByText("Not settable per run: db_path"),
    ).toBeInTheDocument();
  });
});
```

The navigation test needs `AppRoutes` and `renderWithProviders` without a
`path`, since the router itself is under test there; import `AppRoutes` from
`@/app/routes`.

- [ ] **Step 2: Run the test to verify it fails**

```bash
npm --prefix web test -- --run src/features/newrun
```

Expected: FAIL — the placeholder renders a heading and nothing else.

- [ ] **Step 3: Write the four cards**

Create `web/src/features/newrun/ModelCard.tsx`:

```tsx
import { SectionLabel } from "@/components/SectionLabel";

import styles from "./ModelCard.module.css";

/**
 * Provider pills over a per-provider model list.
 *
 * The model rows carry no `default` / `slower` / `cheap` annotation. The
 * contract returns bare ids and the registry holds no annotation data, and
 * for ollama it could not: that list is whatever is pulled on this machine.
 * A hardcoded editorial claim that nothing verifies would be worse than the
 * blank. See the phase 6 plan, "Decisions", 3.
 */
export function ModelCard({
  models,
  provider,
  model,
  keyPresent,
  onProvider,
  onModel,
}: {
  models: Record<string, string[]>;
  provider: string;
  model: string;
  keyPresent: boolean;
  onProvider: (provider: string) => void;
  onModel: (model: string) => void;
}) {
  const available = models[provider] ?? [];

  return (
    <section className={styles.card}>
      <SectionLabel>Model</SectionLabel>

      <div className={styles.pills}>
        {Object.keys(models).map((name) => (
          <button
            key={name}
            type="button"
            aria-pressed={name === provider}
            className={name === provider ? styles.pillOn : styles.pill}
            onClick={() => onProvider(name)}
          >
            {name}
          </button>
        ))}
      </div>

      {provider === "anthropic" && (
        <p className={keyPresent ? styles.keyLine : styles.keyMissing}>
          {keyPresent
            ? "key present · ANTHROPIC_API_KEY"
            : "ANTHROPIC_API_KEY is not set · this run would fail"}
        </p>
      )}

      <div className={styles.models} role="radiogroup" aria-label="Model">
        {available.length === 0 ? (
          // Ollama's list comes from `/api/tags` on the configured host and
          // is empty when the daemon is not running. Saying so beats an
          // empty box that looks like a loading state.
          <p className={styles.none}>
            No models found. Is Ollama running on the configured host?
          </p>
        ) : (
          available.map((id) => (
            <button
              key={id}
              type="button"
              role="radio"
              aria-checked={id === model}
              className={id === model ? styles.modelOn : styles.model}
              onClick={() => onModel(id)}
            >
              {id}
            </button>
          ))
        )}
      </div>
    </section>
  );
}
```

Create `web/src/features/newrun/PlatformCard.tsx`:

```tsx
import type { PlatformOption } from "@/api/types";
import { SectionLabel } from "@/components/SectionLabel";

import styles from "./PlatformCard.module.css";

/**
 * 3-up radio cards, `exactly one`, and the dormant platforms shown but
 * unpickable.
 *
 * Lemmy and Wikipedia are in `KNOWN_SOURCES` and have code and tests, but
 * nothing consumes a flat item list and `Settings` rejects them. Hiding
 * them would leave someone wondering why a platform they know exists is not
 * offered; disabling them says which and why.
 */
export function PlatformCard({
  platforms,
  selected,
  onSelect,
}: {
  platforms: PlatformOption[];
  selected: string;
  onSelect: (name: string) => void;
}) {
  return (
    <section className={styles.card}>
      <SectionLabel hint="exactly one">Platform</SectionLabel>

      <div className={styles.grid} role="radiogroup" aria-label="Platform">
        {platforms.map((platform) => (
          <button
            key={platform.name}
            type="button"
            role="radio"
            disabled={!platform.enabled}
            aria-checked={platform.name === selected}
            className={[
              styles.option,
              platform.enabled ? "" : styles.dormant,
              platform.name === selected ? styles.chosen : "",
            ]
              .filter(Boolean)
              .join(" ")}
            onClick={() => onSelect(platform.name)}
          >
            <span className={styles.name}>{platform.name}</span>
            <span className={styles.sublabel}>
              {platform.enabled ? "clusters its own trends" : "dormant · no clustering"}
            </span>
          </button>
        ))}
      </div>
    </section>
  );
}
```

Create `web/src/features/newrun/CountCard.tsx`:

```tsx
import { SectionLabel } from "@/components/SectionLabel";

import styles from "./CountCard.module.css";

const PRESETS = [1, 3, 5, 10];

/**
 * The one card with an accent border, because it is the setting that
 * changes the output.
 *
 * `custom` is a number input rather than a fifth pill: the presets cover
 * what anyone picks in practice, and the input is there for the time they
 * do not.
 */
export function CountCard({
  count,
  trendLimit,
  onCount,
}: {
  count: number;
  trendLimit: string;
  onCount: (count: number) => void;
}) {
  const custom = !PRESETS.includes(count);

  return (
    <section className={styles.card}>
      <SectionLabel hint="topic_count · default 5">Memes to generate</SectionLabel>
      <p className={styles.explain}>
        How many of the ranked topics get briefed and rendered.
      </p>

      <div className={styles.pills}>
        {PRESETS.map((preset) => (
          <button
            key={preset}
            type="button"
            aria-pressed={count === preset}
            className={count === preset ? styles.pillOn : styles.pill}
            onClick={() => onCount(preset)}
          >
            {preset}
          </button>
        ))}
        <label className={custom ? styles.customOn : styles.custom}>
          custom
          <input
            type="number"
            min={1}
            aria-label="custom count"
            className={styles.input}
            value={custom ? count : ""}
            onChange={(event) => {
              const next = Number(event.target.value);
              if (Number.isFinite(next) && next > 0) onCount(next);
            }}
          />
        </label>
      </div>

      <p className={styles.note}>of {trendLimit} trends analysed</p>
    </section>
  );
}
```

Create `web/src/features/newrun/TemplateCard.tsx`:

```tsx
import type { TemplateOption } from "@/api/types";
import { SectionLabel } from "@/components/SectionLabel";

import styles from "./TemplateCard.module.css";

/**
 * `all N` plus one chip per template, where N is the library's real size.
 *
 * The handoff names four templates and the repository ships a different
 * set; only `drake` overlaps. Every chip is driven by the loaded manifests,
 * so this reads `all 5` today and stays correct as the library changes.
 *
 * `all N` sends null rather than an explicit list of every id, which is the
 * pipeline's own convention for "the whole library" and is what keeps a run
 * started today from freezing a template list that a manifest added
 * tomorrow would not be in.
 */
export function TemplateCard({
  templates,
  selected,
  onSelect,
}: {
  templates: TemplateOption[];
  selected: string[] | null;
  onSelect: (selected: string[] | null) => void;
}) {
  function toggle(id: string) {
    const held = selected ?? [];
    const next = held.includes(id)
      ? held.filter((other) => other !== id)
      : [...held, id];
    onSelect(next.length === 0 ? null : next);
  }

  return (
    <section className={styles.card}>
      <SectionLabel hint="default: whole library">Templates</SectionLabel>

      <div className={styles.chips}>
        <button
          type="button"
          aria-pressed={selected === null}
          className={selected === null ? styles.chipOn : styles.chip}
          onClick={() => onSelect(null)}
        >
          all {templates.length}
        </button>
        {templates.map((template) => (
          <button
            key={template.id}
            type="button"
            aria-pressed={selected?.includes(template.id) ?? false}
            className={
              (selected?.includes(template.id) ?? false) ? styles.chipOn : styles.chip
            }
            onClick={() => toggle(template.id)}
          >
            {template.id}
          </button>
        ))}
      </div>
    </section>
  );
}
```

Each card's stylesheet follows the same shape — `surface` fill, radius 12,
`17px 19px` padding, a `column` flex with 10px gaps — and uses only the
tokens named in `tokens.css`. Write the four `.module.css` files with the
classes each component names, drawing the pill, chip and radio treatments
from the handoff's own values: pills at `radius-pill` with `accent` fill and
`on-accent` text when selected, chips at `radius-pill` with `chip-fill` and
`accent-tint` when selected, radio rows at `radius-tile` with `10px 12px`
padding and mono 600/11.5 for the id. The `MEMES TO GENERATE` card is the
only one with `border-color: var(--accent-border)` and
`background: var(--accent-wash)`. `no-raw-colours.test.ts` will name any
literal that slips in, and the phantom-class check will name any class a
component references that its stylesheet does not define.

- [ ] **Step 4: Write the page**

Replace `web/src/features/newrun/NewRunPage.tsx`:

```tsx
import type { FormEvent } from "react";
import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import type { ConfigOptions, RunConfig } from "@/api/types";
import { useActiveRun, useConfigOptions, useRun, useStartRun } from "@/api/queries";
import { Breadcrumb } from "@/components/Breadcrumb";
import { MetaLine } from "@/components/MetaLine";
import { QueryBoundary } from "@/components/QueryBoundary";
import { CountCard } from "@/features/newrun/CountCard";
import { ModelCard } from "@/features/newrun/ModelCard";
import { PlatformCard } from "@/features/newrun/PlatformCard";
import { TemplateCard } from "@/features/newrun/TemplateCard";
import { shortRunId } from "@/format";

import styles from "./NewRunPage.module.css";

export function NewRunPage() {
  const [params] = useSearchParams();
  const from = params.get("from") ?? undefined;
  const options = useConfigOptions();
  const source = useRun(from);

  return (
    <QueryBoundary query={options} missing="No configuration.">
      {(config) => (
        <div className={styles.page}>
          <Breadcrumb trail={[{ label: "Runs", to: "/runs" }, { label: "new" }]} />
          <header className={styles.header}>
            <h1 className={styles.title}>New run</h1>
            <MetaLine>
              defaults come from <Link to="/settings">settings</Link> · changes apply
              to this run only
            </MetaLine>
          </header>

          {/* The form owns its state and seeds it from props, so the
              seeding happens once, at mount, rather than in an effect that
              has to decide whether the user has since edited a field. That
              means waiting for the source run before mounting it. */}
          {from !== undefined && source.data === undefined ? (
            <p className={styles.loading}>Loading that run's config…</p>
          ) : (
            <NewRunForm config={config} preset={source.data?.run.config} />
          )}
        </div>
      )}
    </QueryBoundary>
  );
}

function NewRunForm({
  config,
  preset,
}: {
  config: ConfigOptions;
  preset?: RunConfig;
}) {
  const navigate = useNavigate();
  const active = useActiveRun();
  const start = useStartRun();

  const [provider, setProvider] = useState(
    preset?.llm_provider ?? config.defaults.llm_provider ?? "anthropic",
  );
  const [model, setModel] = useState(
    preset?.llm_model ?? config.defaults.llm_model ?? "",
  );
  const [platform, setPlatform] = useState(
    // Not `config.defaults.sources`: `options.py` stringifies every default
    // and `Settings.sources` is a list, so that key arrives as the Python
    // repr `"['bluesky']"` rather than a platform name. The enabled
    // platform is the honest default and there is exactly one.
    preset?.sources[0] ?? config.platforms.find((one) => one.enabled)?.name ?? "",
  );
  const [count, setCount] = useState(
    preset?.top_count ?? Number(config.defaults.topic_count ?? "5"),
  );
  const [templateIds, setTemplateIds] = useState<string[] | null>(
    preset?.template_ids ?? null,
  );

  function chooseProvider(next: string) {
    setProvider(next);
    // The model list is per-provider, so a model carried over from the old
    // one would post `claude-sonnet-5` to ollama and fail on the worker
    // thread with a model nobody chose.
    const available = config.models[next] ?? [];
    if (!available.includes(model)) setModel(available[0] ?? "");
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    start.mutate(
      {
        template_ids: templateIds,
        overrides: {
          llm_provider: provider,
          llm_model: model,
          // A bare name: `Settings._split_csv` accepts a CSV string, and
          // the config's own validator enforces exactly one.
          sources: platform,
          topic_count: String(count),
        },
      },
      {
        onSuccess: (queued) =>
          navigate(`/runs/${encodeURIComponent(queued.run_id)}`),
      },
    );
  }

  const queuedBehind = active.data?.current ?? null;

  return (
    <form className={styles.layout} onSubmit={submit}>
      <div className={styles.cards}>
        <ModelCard
          models={config.models}
          provider={provider}
          model={model}
          keyPresent={config.anthropic_key_present}
          onProvider={chooseProvider}
          onModel={setModel}
        />
        <PlatformCard
          platforms={config.platforms}
          selected={platform}
          onSelect={setPlatform}
        />
        <CountCard
          count={count}
          trendLimit={config.defaults.bluesky_trend_limit ?? "25"}
          onCount={setCount}
        />
        <TemplateCard
          templates={config.templates}
          selected={templateIds}
          onSelect={setTemplateIds}
        />
      </div>

      <aside className={styles.side}>
        {queuedBehind !== null && (
          <p className={styles.notice}>
            A run is already in flight. Starting this one queues it behind{" "}
            {shortRunId(queuedBehind)}.
          </p>
        )}
        <button type="submit" className={styles.start} disabled={start.isPending}>
          Start run
        </button>
        {start.error !== null && <p className={styles.failure}>{start.error.detail}</p>}
      </aside>
    </form>
  );
}
```

Create `web/src/features/newrun/NewRunPage.module.css` with `.page`,
`.header`, `.title` (Outfit 800/22/1/-.03em), `.loading`, `.layout`
(`grid-template-columns: 1fr 320px`, 18px gap, `align-items: start`),
`.cards` (column flex, 16px gap), `.side` (a `surface` card, radius 12,
`17px 19px` padding, column flex, 16px gap), `.notice` (`--contrast-wash`
fill, `--contrast-border` border, `--contrast-light` text, radius 9, mono
10.5), `.start` (accent fill, full width, 14px padding, radius 9, Outfit
700/12), and `.failure` (mono 10.5 in `--contrast-light`).

- [ ] **Step 5: Run the tests to verify they pass**

```bash
npm --prefix web test -- --run src/features/newrun
```

Expected: PASS.

- [ ] **Step 6: Run the whole web gate**

```bash
npm --prefix web run lint && npm --prefix web run typecheck && npm --prefix web test
```

Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add web/src/features/newrun
git commit -m "feat: the New run screen, and re-running a run's frozen config"
```

---

### Task 12: the settings screen

Seven fields in three cards, each saying which layer supplied its value.
Making the layering visible is the point — a settings screen that hides
which layer won is worse than no settings screen.

**Files:**
- Create: `web/src/features/settings/fields.ts`
- Create: `web/src/features/settings/SettingRow.tsx` + `.module.css`
- Modify: `web/src/features/settings/SettingsPage.tsx` (replacing the
  placeholder) + `.module.css`
- Test: `web/src/features/settings/SettingsPage.test.tsx`

**Interfaces:**
- Consumes: `useSettings`, `useSaveSettings`; `SettingField`,
  `SettingSource`; `SectionLabel`, `MetaLine`, `QueryBoundary`.
- Produces:
  - `fields.ts`: `CARDS: readonly SettingCard[]`, where
    `SettingCard = { label: string; fields: readonly FieldSpec[] }` and
    `FieldSpec = { key: string; explanation: string; hint?: string }`;
    `SOURCE_LABELS: Readonly<Record<SettingSource, string>>`.
  - `SettingRow({ field, draft, spec, onDraft })`.

- [ ] **Step 1: Write the failing test**

Create `web/src/features/settings/SettingsPage.test.tsx`:

```tsx
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";

import { SettingsPage } from "@/features/settings/SettingsPage";
import { makeSettingField, makeSettingFields } from "@/test/factories";
import { renderWithProviders } from "@/test/render";
import { server } from "@/test/server";

describe("SettingsPage", () => {
  it("groups the seven writable fields into the three cards", async () => {
    server.use(
      http.get("/api/settings", () => HttpResponse.json(makeSettingFields())),
    );

    renderWithProviders(<SettingsPage />, { route: "/settings" });

    expect(await screen.findByText("Fan-out")).toBeInTheDocument();
    expect(screen.getByText("Ranking")).toBeInTheDocument();
    expect(screen.getByText("Distillation")).toBeInTheDocument();
    expect(screen.getAllByRole("spinbutton")).toHaveLength(7);
  });

  it("names each field by the key a layer would actually match", async () => {
    // Not `trend_limit`. The environment variable, the .env line and the
    // settings row are all `bluesky_trend_limit`, and a screen whose whole
    // job is showing which layer won must not print a name no layer uses.
    server.use(
      http.get("/api/settings", () => HttpResponse.json(makeSettingFields())),
    );

    renderWithProviders(<SettingsPage />, { route: "/settings" });

    expect(await screen.findByText("bluesky_trend_limit")).toBeInTheDocument();
    expect(screen.queryByText("trend_limit")).not.toBeInTheDocument();
  });

  it("says where each value came from, including the environment", async () => {
    // Four layers, though the design drew three. A shell variable outranks
    // the settings table, so `environment` is a real answer — and it is the
    // one state where saving cannot change what the next run uses.
    server.use(
      http.get("/api/settings", () =>
        HttpResponse.json([
          makeSettingField({ key: "phrase_min_authors", source: "settings" }),
          makeSettingField({ key: "distil_concurrency", source: "environment" }),
          makeSettingField({ key: "distil_char_budget", source: "dotenv" }),
          makeSettingField({ key: "meme_potential_weight", source: "default" }),
        ]),
      ),
    );

    renderWithProviders(<SettingsPage />, { route: "/settings" });

    expect(await screen.findByText("SET HERE")).toBeInTheDocument();
    expect(screen.getByText("FROM ENV")).toBeInTheDocument();
    expect(screen.getByText("FROM .env")).toBeInTheDocument();
    expect(screen.getByText("DEFAULT")).toBeInTheDocument();
  });

  it("carries the API ceiling on the field that has one", async () => {
    server.use(
      http.get("/api/settings", () => HttpResponse.json(makeSettingFields())),
    );

    renderWithProviders(<SettingsPage />, { route: "/settings" });

    expect(await screen.findByText("max 25 · API ceiling")).toBeInTheDocument();
  });

  it("saves only the fields that were edited", async () => {
    // Sending all seven would write a settings row for every one of them,
    // pinning six values that were only ever defaults — and a later .env
    // edit would then be invisible.
    const user = userEvent.setup();
    let sent: unknown = null;
    server.use(
      http.get("/api/settings", () => HttpResponse.json(makeSettingFields())),
      http.put("/api/settings", async ({ request }) => {
        sent = await request.json();
        return HttpResponse.json(makeSettingFields());
      }),
    );

    renderWithProviders(<SettingsPage />, { route: "/settings" });

    const field = await screen.findByLabelText("phrase_min_authors");
    await user.clear(field);
    await user.type(field, "9");
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(sent).toEqual({ values: { phrase_min_authors: "9" } }),
    );
  });

  it("resets every field to its .env value by clearing the rows", async () => {
    // An empty string deletes the row so the fallback applies again.
    // Writing the default back would pin the value and make a later .env
    // edit invisible — the endpoint's own reasoning, honoured here.
    const user = userEvent.setup();
    let sent: unknown = null;
    server.use(
      http.get("/api/settings", () => HttpResponse.json(makeSettingFields())),
      http.put("/api/settings", async ({ request }) => {
        sent = await request.json();
        return HttpResponse.json(makeSettingFields());
      }),
    );

    renderWithProviders(<SettingsPage />, { route: "/settings" });
    await screen.findByLabelText("phrase_min_authors");

    await user.click(screen.getByRole("button", { name: "Reset to .env" }));

    await waitFor(() => expect(sent).not.toBeNull());
    expect(sent).toEqual({
      values: {
        bluesky_fetch_concurrency: "",
        bluesky_posts_per_trend: "",
        bluesky_trend_limit: "",
        distil_char_budget: "",
        distil_concurrency: "",
        meme_potential_weight: "",
        phrase_min_authors: "",
      },
    });
  });

  it("shows the server's own rejection when a value is out of range", async () => {
    const user = userEvent.setup();
    server.use(
      http.get("/api/settings", () => HttpResponse.json(makeSettingFields())),
      http.put("/api/settings", () =>
        HttpResponse.json(
          {
            detail:
              "meme_potential_weight: Input should be less than or equal to 1",
          },
          { status: 400 },
        ),
      ),
    );

    renderWithProviders(<SettingsPage />, { route: "/settings" });

    const field = await screen.findByLabelText("meme_potential_weight");
    await user.clear(field);
    await user.type(field, "2");
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(
      await screen.findByText(
        "meme_potential_weight: Input should be less than or equal to 1",
      ),
    ).toBeInTheDocument();
  });
});
```

**The frozen-config note gets no test.** `Changes apply to new runs. A run
in flight keeps the config it froze.` is rendered unconditionally, from no
data, under no branch — so the only production changes that could fail such
a test are deleting the sentence or rewording it, both of which are
decisions someone is entitled to make. It would fire on a redesign and sleep
through every bug on the screen it sits on. The conditional copy elsewhere
in this plan — the distilling line, the queue notice, the key warning — is
tested because each is a branch; this is not one.

- [ ] **Step 2: Run the test to verify it fails**

```bash
npm --prefix web test -- --run src/features/settings
```

Expected: FAIL — the placeholder renders a heading and nothing else.

- [ ] **Step 3: Write the field data**

Create `web/src/features/settings/fields.ts`:

```ts
/**
 * The three cards, the seven fields, and what each one does.
 *
 * The explanations are lifted from the comments already in `config.py`,
 * which explain every one of these better than new copy would — and which
 * a reader who goes looking will find saying the same thing.
 *
 * Keys are the real ones. The spec's card grouping names `trend_limit` and
 * `posts_per_trend`; the writable keys are `bluesky_trend_limit` and
 * `bluesky_posts_per_trend`, and this screen's whole job is telling you
 * which layer supplied which key. See the phase 6 plan, "Decisions", 4.
 */
import type { SettingSource } from "@/api/types";

export interface FieldSpec {
  key: string;
  explanation: string;
  /** A constraint that is not a preference. Only one field has one. */
  hint?: string;
}

export interface SettingCard {
  label: string;
  fields: readonly FieldSpec[];
}

export const CARDS: readonly SettingCard[] = [
  {
    label: "Fan-out",
    fields: [
      {
        key: "bluesky_trend_limit",
        explanation:
          "Trends fetched per run. Not a tuning parameter above 25 — the endpoint refuses it.",
        hint: "max 25 · API ceiling",
      },
      {
        key: "bluesky_posts_per_trend",
        explanation:
          "Posts read per trend. With the trend limit, this is the real fan-out budget — one number could not express trends-by-posts.",
      },
      {
        key: "bluesky_fetch_concurrency",
        explanation:
          "Parallel fetches. A semaphore of zero blocks every fetch forever with no diagnostic, so the floor is one.",
      },
    ],
  },
  {
    label: "Ranking",
    fields: [
      {
        key: "meme_potential_weight",
        explanation:
          "Share of the ranking given to the dossier's meme potential, the rest going to trend score. Raise it to favour what will actually make a meme over what is merely loud.",
      },
      {
        key: "phrase_min_authors",
        explanation:
          "Distinct accounts a phrase needs before it counts as recurring. Below this, a repeated phrase is one person or a small ring, not a zeitgeist.",
      },
    ],
  },
  {
    label: "Distillation",
    fields: [
      {
        key: "distil_char_budget",
        explanation:
          "Reply characters sent per distillation call. A single trend can yield six hundred replies, and a 32k-context local model truncates silently well before that.",
      },
      {
        key: "distil_concurrency",
        explanation:
          "Parallel distillation calls. Local Ollama serialises on one GPU, so one or two is right there; a hosted provider benefits from more.",
      },
    ],
  },
];

/**
 * Four, though the design drew three.
 *
 * A shell variable outranks the settings table, so `environment` is a real
 * answer — and it is the one state where Save cannot change what the next
 * run actually uses. See the phase 6 plan, "Decisions", 5.
 */
export const SOURCE_LABELS: Readonly<Record<SettingSource, string>> = {
  settings: "SET HERE",
  environment: "FROM ENV",
  dotenv: "FROM .env",
  default: "DEFAULT",
};

/** Every writable key, in the order the cards draw them. */
export const SETTING_KEYS: readonly string[] = CARDS.flatMap((card) =>
  card.fields.map((field) => field.key),
);
```

- [ ] **Step 4: Write the row**

Create `web/src/features/settings/SettingRow.tsx`:

```tsx
import type { SettingField } from "@/api/types";
import type { FieldSpec } from "@/features/settings/fields";
import { SOURCE_LABELS } from "@/features/settings/fields";

import styles from "./SettingRow.module.css";

/**
 * One tunable: its key, its value, where the value came from, and what it
 * does.
 *
 * The input is uncontrolled-looking but controlled: `draft` is the edited
 * string, falling back to the server's value. Keeping the draft as a string
 * rather than a number is deliberate — the field must be allowed to be
 * empty while someone is retyping it, and `Number("")` is `0`, which would
 * silently rewrite the value the moment the box was cleared.
 */
export function SettingRow({
  field,
  spec,
  draft,
  onDraft,
}: {
  field: SettingField;
  spec: FieldSpec;
  draft: string | undefined;
  onDraft: (value: string) => void;
}) {
  return (
    <div className={styles.row}>
      <div className={styles.head}>
        <label className={styles.key} htmlFor={`setting-${field.key}`}>
          {field.key}
        </label>
        <span className={styles[field.source]}>{SOURCE_LABELS[field.source]}</span>
        <input
          id={`setting-${field.key}`}
          type="number"
          step="any"
          className={styles.input}
          value={draft ?? String(field.value)}
          onChange={(event) => onDraft(event.target.value)}
        />
      </div>
      <p className={styles.explanation}>
        {spec.explanation}
        {spec.hint !== undefined && <span className={styles.hint}>{spec.hint}</span>}
      </p>
    </div>
  );
}
```

Create `web/src/features/settings/SettingRow.module.css` with `.row`,
`.head` (`grid-template-columns: 1fr auto 72px`, 10px gap, centred),
`.key` (mono 600/11.5 in `--text`), `.input` (72px, right-aligned, mono
600/12 on `--surface-log`, 1px `--border`, radius 8), `.explanation`
(Outfit 400/11.5 in `--text-55`), `.hint` (mono 9.5 in `--text-35`), and one
class per source — `.settings` on `--accent-tint` with `--accent` text,
`.environment` on `--chip-fill-strong`, `.dotenv` on `--chip-fill`, and
`.default` in `--text-30` with no fill — each a mono 9.5/`.12em` chip.

The four source classes are reached as `styles[field.source]`, which
`no-raw-colours.test.ts` skips by design (it resolves no runtime key), so
check the four names against the stylesheet by eye when writing it.

- [ ] **Step 5: Write the page**

Replace `web/src/features/settings/SettingsPage.tsx`:

```tsx
import { useState } from "react";

import type { SettingField } from "@/api/types";
import { useSaveSettings, useSettings } from "@/api/queries";
import { MetaLine } from "@/components/MetaLine";
import { QueryBoundary } from "@/components/QueryBoundary";
import { SectionLabel } from "@/components/SectionLabel";
import { SettingRow } from "@/features/settings/SettingRow";
import { CARDS, SETTING_KEYS } from "@/features/settings/fields";

import styles from "./SettingsPage.module.css";

export function SettingsPage() {
  const settings = useSettings();
  const save = useSaveSettings();
  const [drafts, setDrafts] = useState<Record<string, string>>({});

  function commit(fields: SettingField[]) {
    // Only what was actually edited. Sending all seven would write a
    // settings row for every one of them, pinning six values that were
    // only ever defaults — and a later `.env` edit would then be invisible.
    const held = new Map(fields.map((field) => [field.key, String(field.value)]));
    const changed = Object.fromEntries(
      Object.entries(drafts).filter(([key, value]) => held.get(key) !== value),
    );
    if (Object.keys(changed).length === 0) return;
    save.mutate({ values: changed }, { onSuccess: () => setDrafts({}) });
  }

  function reset() {
    // An empty string clears that field's row so the `.env` fallback
    // applies again. Writing the default back would pin the value.
    save.mutate(
      { values: Object.fromEntries(SETTING_KEYS.map((key) => [key, ""])) },
      { onSuccess: () => setDrafts({}) },
    );
  }

  return (
    <QueryBoundary query={settings} missing="No settings.">
      {(fields) => {
        const byKey = new Map(fields.map((field) => [field.key, field]));
        return (
          <div className={styles.page}>
            <header className={styles.header}>
              <h1 className={styles.title}>Settings</h1>
              <MetaLine>the seven fields a run can be tuned with</MetaLine>
            </header>

            <div className={styles.layout}>
              <div className={styles.cards}>
                {CARDS.map((card) => (
                  <section key={card.label} className={styles.card}>
                    <SectionLabel>{card.label}</SectionLabel>
                    {card.fields.map((spec) => {
                      const field = byKey.get(spec.key);
                      // A key the server did not return is a contract
                      // change, not a state: skipping it beats rendering a
                      // row with nothing behind it.
                      return field === undefined ? null : (
                        <SettingRow
                          key={spec.key}
                          field={field}
                          spec={spec}
                          draft={drafts[spec.key]}
                          onDraft={(value) =>
                            setDrafts((held) => ({ ...held, [spec.key]: value }))
                          }
                        />
                      );
                    })}
                  </section>
                ))}
              </div>

              <aside className={styles.side}>
                <button
                  type="button"
                  className={styles.save}
                  disabled={save.isPending}
                  onClick={() => commit(fields)}
                >
                  Save
                </button>
                <button
                  type="button"
                  className={styles.reset}
                  disabled={save.isPending}
                  onClick={reset}
                >
                  Reset to .env
                </button>
                <p className={styles.note}>
                  Changes apply to new runs. A run in flight keeps the config it
                  froze.
                </p>
                {save.error !== null && (
                  <p className={styles.failure}>{save.error.detail}</p>
                )}
              </aside>
            </div>
          </div>
        );
      }}
    </QueryBoundary>
  );
}
```

Create `web/src/features/settings/SettingsPage.module.css` mirroring New
run's: `.layout` at `1fr 320px` with an 18px gap, `.cards` a column flex at
16px, `.card` on `--surface` at radius 12 with `17px 19px` padding, `.side`
a `--surface` card holding an accent `.save` (full width, 14px padding,
radius 9), a ghost `.reset` beneath it, a `.note` in mono 10.5 `--text-35`,
and a `.failure` in `--contrast-light`.

- [ ] **Step 6: Run the tests to verify they pass**

```bash
npm --prefix web test -- --run src/features/settings
```

Expected: PASS.

- [ ] **Step 7: Run the whole gate, both halves**

```bash
uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest
```

```bash
npm --prefix web run lint && npm --prefix web run typecheck && npm --prefix web test
```

Expected: all seven PASS.

- [ ] **Step 8: Commit**

```bash
git add web/src/features/settings
git commit -m "feat: the settings screen, and which layer supplied each value"
```

---

### Task 13: run it against a real run, then write down what changed

Phase 5's own walk against a real run found three defects that MSW fixtures
structurally could not: an image that never resolves in a test never errors,
so `RenderDetailPage`'s missing `onError` fallback was invisible. This phase
has more of that surface, not less — a real SSE stream, a real worker
thread, a real settings table, and a form that posts to a real validator.

Run it. Fix what the walk finds, each with a test that would have caught it.

**Files:**
- Modify: whatever the walk finds
- Modify: `README.md`
- Modify: `docs/superpowers/specs/2026-09-02-web-ui-design.md` (the phase 6
  entry, recording what was deferred)

**Interfaces:**
- Consumes: everything Tasks 1–12 built.
- Produces: no new names. A green gate, a README that describes the app as
  it now is, and the deferred work written down where the next phase will
  read it.

- [ ] **Step 1: Start both processes**

The database's schema version moved to 4 in Task 1, so an existing
`data/zeitgeist.db` will refuse to open. That is the migration strategy
working. Delete it first:

```bash
rm -f data/zeitgeist.db
```

```bash
uv run zeitgeist
```

```bash
npm --prefix web run dev
```

- [ ] **Step 2: Point it at the local model**

The Anthropic path costs real money per run and this walk needs several.
Put this in `.env`, or set it in the shell that runs `zeitgeist`:

```bash
LLM_PROVIDER=ollama
LLM_MODEL=qwen3.5:latest
OLLAMA_HOST=http://localhost:11434
DISTIL_CONCURRENCY=2
```

`distil_concurrency` at 2 because local Ollama serialises on one GPU, which
is the comment `config.py` already carries.

- [ ] **Step 3: Walk the settings screen**

Open `/settings`. Check each against what the API says:

- [ ] Every field shows a source chip, and the chip matches where the value
      really came from. Set `PHRASE_MIN_AUTHORS=7` in the shell running
      uvicorn, restart it, and confirm that field reads `FROM ENV`.
- [ ] Save one field. The chip becomes `SET HERE` without a second request
      — watch the network panel.
- [ ] Save an out-of-range `meme_potential_weight` (say `2`). The screen
      shows the server's own sentence, and nothing was written: reload and
      confirm the old value is still there.
- [ ] Reset to .env. Every chip that said `SET HERE` stops saying it.

- [ ] **Step 4: Start a run and watch it**

Open `/runs/new`.

- [ ] Switch the provider to ollama. The model list becomes what is pulled
      locally. If it is empty, the card says so rather than showing a blank.
- [ ] Start the run. The browser lands on `/runs/<id>` with a RUNNING pill.
- [ ] The elapsed time counts up once a second.
- [ ] The log fills, with real logger names. Scroll up: `following` becomes
      `jump to latest`. Click it: the log snaps to the bottom and follows
      again.
- [ ] Toggle `verbose`. DEBUG lines appear retroactively, including the
      per-topic `Distilled ... in ...s` lines from the distil pool.
- [ ] The analyse card shows a counter that climbs, and its bar fills to
      match. Confirm the counter's total is the trend count.
- [ ] The sidebar card names the running stage, and the Runs screen's
      in-flight card shows four segments with the right ones filled.
- [ ] When the run finishes, the screen becomes the completed one without a
      reload: bars solid, log stops following, actions become Re-run config
      and Resume.

- [ ] **Step 5: Walk the two ways a run ends early**

- [ ] Start a run and click **Stop after this stage**. The current stage
      finishes, writes its checkpoint, and the run ends `ABORTED`. Confirm
      **Resume from &lt;stage&gt;** appears and works.
- [ ] Start another and click **Abort**, then `yes`. It ends now.
- [ ] Press Escape on an armed abort confirm. It reverts and the run
      continues.
- [ ] Start a run while one is in flight. The New run screen's notice names
      the run it queues behind; the queued run's detail page opens rather
      than 404ing, and its own stream stays open.

- [ ] **Step 6: Fix what the walk found**

For each defect: write the test that would have caught it, watch it fail,
fix it, watch it pass. A fix with no test is a defect that comes back.

- [ ] **Step 7: Update the README**

The usage sections describe a CLI-less app whose screens are read-only.
Extend them: starting a run from the browser, the settings screen and what
it can and cannot change, and the fact that `zeitgeist` serves the API while
`npm --prefix web run dev` serves the SPA in development.

- [ ] **Step 8: Record what was deferred**

In `docs/superpowers/specs/2026-09-02-web-ui-design.md`, extend the phase 6
entry the way phase 5's records its real-run walk. Name the two things this
phase did not build and why:

- Ranking rows appending mid-analyse, which needs a rank-less response model
  and a second endpoint (see "Decisions", 2).
- `~4m left`, which needs a rate no honest source provides (see
  "Decisions", 1).

and the two flagged back to the designer:

- Model annotations (`default` / `slower` / `cheap`), which have no source.
- The fourth settings source chip, `FROM ENV`, which the design never drew
  because it did not know the environment outranks the table.

- [ ] **Step 9: Run the whole gate one last time**

```bash
uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest
```

```bash
npm --prefix web run lint && npm --prefix web run typecheck && npm --prefix web test
```

Expected: all seven PASS.

- [ ] **Step 10: Commit**

```bash
git add -A
git commit -m "fix: what a real run found, and the docs it changed"
```

---

## Tests

What this phase's suite covers, and why each is worth its line.

**Backend**

| Area | Assertion |
| --- | --- |
| `StageRecord` round trip | Counters survive `record_stage` → `stages_for_run`; a completed row leaves none behind. |
| Counter defaults | Ingest and evaluate report `None`, not `0`. |
| `_RunRecorder` | A `running` row exists *while* the stage runs; progress rewrites it in place rather than appending; `started_at` is the stage's, not now's. |
| Observer failure | A store error under the observer costs the display, never the run. |
| `last_stage` | Preserved from `_StageTracker`: a run that dies in generate is recorded as dying in generate. |
| Analyse progress | Counts against trends, not surviving topics — proven with a trend that fails distillation; names the topic's label; arrives interleaved with `topic_distilled` rather than flushed at the end; `topic_distilled` still fires exactly once per topic. |
| Contract gates | `openapi.json` is the app's; `schema.ts` is `openapi.json`'s. |

**Frontend**

| Area | Assertion |
| --- | --- |
| `apiSend` | Sends the body it was given; raises `ApiError` carrying the server's own `detail`. |
| `parseLogEvent` | Reads a frame; yields nothing for a truncated one rather than throwing. |
| `useActiveRun` | Silent while idle; polls while a run is live. |
| `useRunEvents` | Accumulates; caps at 2000, dropping the oldest; opens no stream when disabled and closes one when it becomes disabled. |
| Mutations | Abort posts and refreshes `active`; saving settings writes the reply into the cache instead of refetching. |
| `formatElapsed` | `t+06:41`; keeps counting in minutes past an hour; never counts backwards. |
| `InlineConfirm` | Asks in place, not in a dialog; confirms only on `yes`; reverts on `no`, Escape and blur; survives focus moving between its own two answers. |
| `progress.ts` | Names the running stage; falls back to the first unrecorded one; treats skipped as settled; never divides by zero; no counter on a settled stage. |
| `LiveLog` | Pins while following; releases past the threshold; stays within it; jump-to-latest re-engages; verbose filters retroactively; no follow indicator on a finished run. |
| `Sidebar` | Three destinations in order; no card while idle; names the running stage; links to the run. |
| `useNow` | Ticks while active, holds still otherwise, stops when it becomes inactive. |
| Runs / Topics | In-flight card pinned above the list; run strip marks the running row; New run reachable from the header and from the empty state. |
| Run detail | Live header with elapsed and `started`; stop without a confirm, abort with one; streams the log; reads a finished run's log from the server and opens no stream; Resume absent — not disabled — with nothing to resume from; posts an empty resume body; reports a 409. |
| New run | Model list swaps with the provider and never carries a model across; dormant platforms shown and unpickable; key warning; `all N` sends null; chosen templates send a list; queue notice; navigates to the started run; prefills from `?from=`; reports a refused start. |
| Settings | Three cards, seven fields; real key names; four source chips; the API ceiling hint; saves only what changed; reset clears every row; shows the server's validation sentence; the frozen-config note. |

**Not tested, deliberately**

- The design itself. High-fidelity CSS is not meaningfully unit-testable and
  fidelity is a human review against the mockups — which Task 13 is.
- The four card stylesheets' exact values. `no-raw-colours.test.ts` holds
  the invariant a person cannot (no colour outside `tokens.css`); the rest
  is read against the handoff by eye.

---

## Self-review

Run against the spec after writing, before handing over.

**1. Spec coverage.** Phase 6's entry names: the New run screen and its four
config cards (Task 11); the two in-flight run-detail states (Tasks 6, 9, 10);
the live log with its follow behaviour and jump-to-latest (Task 7); the
inline abort confirmation (Tasks 5, 10); the sidebar in-flight card and the
run strip (Tasks 8, 9); the settings screen and its third nav item (Tasks 8,
12). "Ends with a run startable, watchable and abortable from the browser"
is Task 13's walk.

Two spec elements have no task and are recorded as deferred rather than
missed: ranking rows appending mid-analyse ("Decisions", 2) and `~4m left`
("Decisions", 1). Two more are flagged back to the designer: model
annotations ("Decisions", 3) and the fourth source chip ("Decisions", 5).

**2. Placeholder scan.** The two page stubs in Task 8 are the one
intentional exception, and they are replaced by Tasks 11 and 12 in the same
phase — a route that renders a heading is a better checkpoint than one that
404s for three tasks. Task 11's and Task 12's stylesheets are described by
their classes and token values rather than transcribed in full; every class
a component references is named, which is what the phantom-class gate
checks. Everything else carries its real content.

**3. Type consistency.** `stageFill`, `stageCounter`, `activeStage` and
`byStage` are named identically in `progress.ts`, `StageCards`,
`InFlightCard` and `Sidebar`. `RunEventSource` is the return of
`openRunEvents` and the parameter of `setEventSourceFactory`.
`SETTING_KEYS` is exported from `fields.ts` and consumed by
`SettingsPage.reset`. `NewRunButton`'s `from` prop is what `RunActions`
passes and what `NewRunPage` reads from `useSearchParams`. `StageRecord`'s
`done`/`total` are `int | None` in Python, `number | null | undefined` in
TypeScript after generation, and `counted()` is the single place that
narrows all three.

---

## Test audit

`CLAUDE.md`'s second gate — the `reviewing-plan-tests` skill — **has been
run** over Tasks 1–13. Thirteen findings, all applied. Recorded here so the
gate's effect stays legible, and so a later reader can tell an amended test
from an original one.

**Rewritten (5)**

1. `marks the running row in the strip` — the fixture's own run carried
   status `running`, so the assertion passed with `activeRunId` removed
   entirely. Now asserts the accent class on the active row and its absence
   on the other, which is the only thing that prop decides.
2. `counts up while the run is live` — compared a frozen `started_at`
   against the real `new Date()`, so it was red on a correct implementation
   and its result changed daily. Now pins the clock and asserts `t+06:41`
   rather than a `\d\d:\d\d` shape that would pass for the wrong field.
3. `test_analyse_progress_names_the_topic_it_just_finished` — asserted
   `isinstance(str)`, which passes for the topic id, the stage name and any
   other string. Now asserts the label.
4. `test_analyse_reports_progress_for_every_distilled_topic` — every trend
   in the fixture distilled, so `len(evidence)` and `len(topics)` agreed and
   the test could not tell them apart. Rewritten as
   `test_analyse_counts_progress_against_the_trends_it_was_given`, with a
   trend that fails distillation.
5. `warns when the Anthropic key is missing, and not when it is there` —
   only rendered the missing case, so a card that always warned would pass.
   Split into two tests, one per branch.

**Deleted (2)**

6. `says that a run already in flight keeps the config it froze` — an
   unconditional sentence under no branch. Only a reword or a deletion could
   fail it, both intentional decisions.
7. `test_the_recorder_still_names_the_stage_a_run_died_in` — already covered
   by `tests/test_runner.py:682`, and as written it could only ever fail with
   an `AttributeError`: it called `Store.run`, which does not exist (the
   accessor is `Store.get_run`), against a second connection opened without
   `init_schema()`.

**Added (6)**

8. `test_analyse_progress_arrives_during_the_stage_not_after_it` — every
   count assertion passed for an implementation that buffered its events and
   flushed them once the stage ended, which is the exact break the tests
   claimed to catch.
9. `asks for only the three runs the strip draws` — `RunStrip` has no slice
   of its own, so the query's `limit` is the only cap and nothing tested it.
10. `opens the run's own stream and refreshes it on a tick, at most once a
    second` — half of `useRunEvents` is the tick handler, and no test called
    `emitTick`. Also pins the stream URL, whose being wrong is silent.
11. `says a queued run has not started` and `does not call the run in flight
    queued` — the one place the screen distinguishes a queued run from an
    executing one, previously exercised only by Task 13's manual walk.
12. `keeps the last good count when the custom box is emptied mid-edit` —
    nothing touched `CountCard`'s custom input, whose guard is all that stops
    `Number("")` posting `topic_count: "0"`.
13. `yields nothing for a frame that is not an array of lines` — the
    truncated-frame test reached only `parseLogEvent`'s `try/catch`, not its
    `Array.isArray` guard.

**The change-detector pass.** The skill records that this gate reliably
misses one category — tests only an intentional decision could break — and
asks the planner to walk the tests again for it. Done. Two survived
deliberately: the sidebar's nav order and the settings screen's three card
labels are both explicit requirements of the handoff and the spec rather
than free choices, and each rides alongside a real assertion in the same
test (a missing destination; a missing field). Everything else asserting
copy is conditional, and so tests a branch.

---

## Execution Handoff

Thirteen tasks. Tasks 1–3 are Python and must land in order; Task 1's
contract change is what Tasks 6 and 10 read. Tasks 4–7 are frontend
foundations with no dependency on each other beyond Task 4, which every
later task consumes. Tasks 8–12 are screens and can be reviewed
independently. Task 13 is the walk.

One branch off `main`, one pull request, per the spec's "Landing the work".
Every commit above leaves the seven gate commands green, so the branch has a
checkpoint at each one.
