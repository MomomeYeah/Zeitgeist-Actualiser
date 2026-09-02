# Zeitgeist Web UI — Architecture

**Date:** 2026-09-02
**Status:** Draft

## Purpose

Zeitgeist Actualiser is a CLI. Everything it produces — the trends, the
dossiers, the ranking, the memes — lands as JSON and PNG in `output/<run-id>/`
and is read by opening files. A run is a black box until it finishes, a failed
run reports one line, and there is no way to generate a meme for a topic the
pipeline ranked below the cut short of editing `ranked.json` by hand.

A design handoff exists for a web frontend covering six screens: what is
trending, the run list, run detail with live progress, topic detail with the
full dossier, and run configuration. This spec covers how that gets built:
technology, the changes the pipeline needs, where data lives, the API, and the
phases the work splits into.

The design is high-fidelity — colours, typography, spacing and copy are final
and are reproduced faithfully. This document does not restate the design. It
records what the design assumes that the codebase does not yet provide, and
the decisions taken where the two disagree.

## Scope

In:

- A FastAPI server exposing REST endpoints over runs, topics and renders.
- A React SPA reproducing the handoff's screens.
- Per-run records the design needs and the pipeline does not currently write:
  frozen config, stage timings, failure detail, a render ledger.
- A SQLite read model over those records, rebuildable from disk.
- Clearing `output/` and `data/zeitgeist.db`. Runs written before this work are
  discarded rather than migrated, so the new models can require the fields they
  always populate. See "Existing runs are discarded".
- Progress and cancellation seams in the pipeline, defaulting to no-ops so the
  CLI is unchanged.
- A run execution service: a queue, a worker thread, live log capture, and
  stop/abort.
- On-demand meme generation, both model-written and hand-written, and render
  deletion.

Out:

- Authentication and multi-user support. This is a single-user tool on
  localhost.
- Production deployment. Development runs Vite and uvicorn as two processes;
  mounting the built SPA from `serve` is a later addition of about ten lines.
- Mobile layouts, explicitly undesigned in the handoff.
- The full-size meme detail view, empty and first-run states, the abort
  confirmation dialog, and a settings screen for the `.env` values cut from the
  New run screen. All four are flagged by the handoff as not yet designed; see
  "Deferred".

## Decisions

| Area | Choice | Why |
| --- | --- | --- |
| Backend | FastAPI + uvicorn | Pydantic 2 is already a dependency, so domain models serialise to responses with no translation layer. `ty`-clean. Its OpenAPI schema generates the TypeScript client types. |
| Pipeline execution | A worker thread, never the event loop | A run takes minutes and the UI polls throughout it. Sharing a loop would stall request handling on every CPU-bound moment inside the run. See "Why a thread, not the event loop". |
| Frontend | React + TypeScript + Vite | Largest ecosystem for the pieces this design needs — React Router for six routes, TanStack Query for fetch-on-navigation plus the polled active run. |
| Styling | CSS custom properties + CSS Modules | The handoff's token table maps 1:1 onto `:root` custom properties. The design is bespoke rather than systematic (radii of 11–12px, eight text opacities), so a utility framework's config would be a translation layer the handoff has to be read through. |
| Live updates | SSE for the log, query invalidation for state | The log is the only thing that genuinely streams. A progress tick on the stream invalidates the run queries rather than a timer polling blindly. `EventSource` reconnects on its own and degrades to polling. |
| Read model | SQLite index, prose on disk | `evidence.json` is 1.3MB per run and `topics.json` ~105KB. Indexing what the UI filters and sorts on, while reading prose per-topic from disk, keeps the database small and — critically — derivable. |
| Client types | `openapi-typescript`, checked in | One source of truth for the contract. Regeneration drift fails the gate. |
| Fonts | `@fontsource` | A local tool should not need the network to render correctly. |
| Layout | `web/` in this repo | Dev: Vite proxying `/api` to uvicorn. No CORS, one repository, one contract. |

## What the design assumes the pipeline does not record

Each of these is a display the mockups make and the codebase cannot currently
satisfy. They are the reason Phase A exists.

**Per-run config.** Run detail's config line (sources, `trend_limit`,
`posts_per_trend`, `top_count`, model id) and the "Re-run config" action need
the settings frozen at run time. `store.runs` holds `run_id`, `started_at`,
`finished_at`, `status` and `item_count`. Nothing else. Configuration is read
from the ambient environment at each invocation and never persisted, so it is
not recoverable after the fact.

**Per-stage timing and status.** The four stage cards want a name, a duration,
a one-line summary and an artifact filename with its size. Nothing records
stage boundaries. Artifacts can be `stat`ed, but durations for the runs already
in `output/` are gone.

**Failures.** `run_pipeline` calls `store.finish_run` only on success
(`pipeline.py:96`); the CLI catches `SourceError`, `DistilError`,
`TemplateError` and `StoreSchemaError`, prints one line, and returns 1. A
failed run therefore leaves a `runs` row with a NULL status. Everything the
failed row on the Runs screen displays — the error class, the stage it failed
in, "3 of 5 briefs written", "ranked.json intact", the resume command — is new.

**Partial failure.** `_render_all` catches `RenderError` per brief, logs a
warning and continues (`pipeline.py:123`), and the run still finishes `ok`. The
handoff is right that partial failure is real; nothing records which briefs
failed or why.

**Trend status on a topic.** The UI leans on `trend_status` throughout — topic
cards, the `trending / saturating / cooling / stale` filters, ranking sublines.
`Topic` has no such field. Status lives on `BlueskyMetrics.status` per item and
on `TrendInfo.status` in `evidence.json`. `Topic` gains a `trend_status` field,
populated in `distil.py` where the `TrendEvidence` is already in hand. Adding
the field is preferable to joining through `evidence.json` on every read: it is
a property of the topic, and the data is present at the point the topic is
constructed.

The field is **required** — `trend_status: TrendStatus`, no default. Every
`TrendEvidence` carries a status, so a topic without one is a bug rather than a
state. See "Existing runs are discarded" for why this does not need a migration
concession.

**Cross-run topic identity.** The topics index deduplicates by topic id and
shows recurrence ("SEEN IN 3 RUNS", "NEW THIS RUN") plus a `stale` bucket of
topics no longer trending. The only cross-run key today is `slugify(label)` in
`topic_scores`, and `store.py:96` already documents its limit: it fixes case
and punctuation drift, not wording drift. A topic relabelled "Rescue Dog
Adoptions" from "Shelter Dog Adoption" reads as new. We keep that behaviour
rather than adding fuzzy or embedding-based matching, which is a separate piece
of work with its own accuracy questions. The limitation is stated in the UI's
own terms — recurrence is a floor, not a count.

**Renders.** The design needs several renders per topic, `auto` versus
`manual` provenance, per-render status and error text, and deletion. Today
there is one brief per topic, one PNG named `{position:02d}-{topic_id}.png`,
and `briefs.json` is a flat list keyed by topic. The filename collides the
moment two memes are generated for one topic.

**Progress and cancellation.** The in-flight screens need stage-relative
counters (`17 / 25` distilled, `2 / 5` rendered), partial stage bars, log lines
with real logger names, and ranking rows appended as each topic is distilled.
`distil_topics` owns a `ThreadPoolExecutor` and returns a list; there is no
event seam anywhere in the pipeline, and no cancellation.

## Data model

### Existing runs are discarded

`output/` is emptied and `data/zeitgeist.db` deleted as part of this work.
Nothing on disk today is migrated or read.

This is a deliberate trade, and it buys more than it costs. Every run directory
already written predates `run.json`, `renders.json`, the renders subdirectory
and `Topic.trend_status`. Supporting them means either a synthesis path that
invents `run.json` from directory mtimes and parses render provenance out of
filenames, or optional fields on the new models standing in for data that was
never recorded. The first is a body of code that exists solely to read seven
directories once. The second is worse: it puts `| None` on fields that are
always present going forward, so every consumer — API, read model, UI — has to
handle a state that only ever existed historically, and the null branch is
untestable against anything real.

What is lost is seven runs of meme output and the cross-run trend history in
`topic_scores`, which `Store.previous_sub_scores` feeds into `rank_delta`. The
store's own `StoreSchemaError` message already describes that loss as
acceptable ("Delete it and re-run — cross-run trend history will be lost,
nothing else"), and the history rebuilds over the next few runs.

**The principle this sets, which applies to every model in this spec:**
optionality expresses a real state, never a migration concession. A field is
`| None` only where the pipeline genuinely has no value for it — a stage that
has not started, a run that has not finished, a render that has not failed. It
is never `| None` because an old file on disk lacks the key.

### Run directory artifacts

Two new JSON artifacts per run directory, plus a log and a renders
subdirectory. Writing them to disk rather than only to SQLite is what preserves
the property that the database is a cache: everything the UI shows can be
reconstructed from `output/` alone.

`run.json` — the run's own record. Nothing in it is derivable from the stage
checkpoints, which is why it must be written.

```python
class StageRecord(BaseModel):
    stage: Stage
    status: Literal["ok", "failed", "skipped", "queued", "running"]
    started_at: datetime | None
    finished_at: datetime | None
    artifact: str | None          # "evidence.json"
    artifact_bytes: int | None
    summary: str                  # "25 trends, 214 posts, 3,318 replies"


class RunRecord(BaseModel):
    run_id: str
    status: Literal["running", "ok", "failed", "aborted", "interrupted"]
    started_at: datetime
    finished_at: datetime | None
    config: RunConfig             # frozen Settings subset
    stages: list[StageRecord]
    error: RunError | None        # class name, message, stage
    resume_stage: Stage | None    # computed from the last ok checkpoint
```

Every `| None` on these two models is a real state and stays optional: a queued
stage has not started, a running one has not finished, a failed one wrote no
artifact, a successful run has no error, and a run whose ingest failed has no
stage to resume from.

`StageRecord` is deliberately **not** split into a discriminated union the way
`RenderRecord` is, even though its status and its timestamps co-vary. A render
is created as one kind or the other and never changes; a stage moves
`queued → running → ok`, so a union would mean the record changing class as it
progresses — a worse model of a mutable in-flight record than four honest
optionals. The rule is unrepresentable-invalid-states where a value is fixed at
creation, not everywhere a `Literal` appears.

`RunConfig` is the subset the run detail config line and "Re-run config" need:
`sources`, `trend_limit`, `posts_per_trend`, `top_count`,
`meme_potential_weight`, `phrase_min_authors`, `distil_char_budget`,
`distil_concurrency`, `llm_provider`, `llm_model`, `template_ids`. It is a
frozen copy, not a reference to live `Settings`.

`renders.json` — the mutable render ledger.

```python
class AutoOrigin(BaseModel):
    """A render the model briefed: it chose the template and said why."""

    model_config = STRICT
    provenance: Literal["auto"] = "auto"
    rationale: str


class ManualOrigin(BaseModel):
    """A render written by hand. No model call, so no template choice to explain."""

    model_config = STRICT
    provenance: Literal["manual"] = "manual"


Origin = Annotated[AutoOrigin | ManualOrigin, Field(discriminator="provenance")]


class RenderRecord(BaseModel):
    model_config = STRICT

    id: str                       # uuid4 hex
    topic_id: str
    template_id: str
    caption_slots: dict[str, str]
    origin: Origin
    status: Literal["generating", "ready", "failed"]
    error: str | None             # set only when status is "failed"
    created_at: datetime
```

`rationale` lives on `AutoOrigin` rather than on `RenderRecord` because a
hand-written render has no template choice to justify — the person made it.
Holding it as `rationale: str` with `""` for manual renders, or as
`rationale: str | None` alongside a separate `provenance` flag, both make
`provenance="manual"` with a non-empty rationale representable and meaningless.
This is the same discriminated-union shape `Metrics` already uses in
`models.py`, for the same reason: the checkpoint deserialises back to the
concrete class rather than to whichever union member happens to validate.

`briefs.json` stays exactly as it is: the pipeline's immutable checkpoint of
what the model produced, and the input `--resume-from generate` reads. Deleting
a render touches `renders.json` and the PNG, never the checkpoint. The two
answer different questions — "what did the model write this run" versus "what
images exist now" — and conflating them would make deletion destroy a
checkpoint.

`renders/<render_id>.png` and `renders/<render_id>.thumb.png` at 96px. The
thumbnail exists because the Runs list draws renders at 34px and the PNGs are
300–800KB.

`run.log` — the run's log at DEBUG, one line per record, ISO-8601 timestamp,
level, logger name, message. Scoped to the `zeitgeist` logger, deliberately not
root: `httpx` and `anthropic` at DEBUG emit a line per HTTP request, roughly
275 per run from Bluesky alone. See "Log capture".

### SQLite read model

`store.py` grows four tables alongside the existing `runs`, `topics` and
`topic_scores`, which keep their current role in cross-run trend scoring and
are not repurposed.

- `run_records` — one row per run: status, timings, duration, frozen config as
  JSON, error class and stage, and the aggregate counts the Runs list shows
  (trends fetched, topics kept, phrase count, render count).
- `run_stages` — one row per stage per run.
- `run_topics` — one row per topic per run, holding exactly what the topics
  index and ranking lists filter or sort on: `trend_status`, `event_sentiment`,
  `conversation_register`, `meme_potential`, `trend_score`, `final_score`,
  `final_rank`, `post_count`, `render_count`, `label_slug`, and the top
  recurring phrase with its author count.
- `renders` — one row per render, mirroring `RenderRecord` plus its run id.

Dossier prose, entities, the full phrase list, replies and evidence are never
copied in. Topic detail reads them from `topics.json` and `evidence.json` for
the one topic being viewed.

`SCHEMA_VERSION` goes to 3.

`rebuild-index` also rebuilds the pre-existing `topics` and `topic_scores`
tables, not just the four new ones. Everything in them is derivable from
`topics.json` — the label slug, `trend_score`, and each platform's entry in
`score_components` less the `corroboration` multiplier, which
`NON_PLATFORM_COMPONENTS` already excludes. That makes the whole database
disposable rather than only the new half, and turns `StoreSchemaError`'s
existing advice ("Delete it and re-run — cross-run trend history will be lost")
into advice that loses nothing at all, provided `output/` is intact.

### Rebuild

`zeitgeist rebuild-index` drops every table in the read model and rebuilds it
by reading `run.json`, `topics.json`, `ranked.json` and `renders.json` from
each directory under `output/`. It reads only artifacts this spec defines;
there is no synthesis path and no legacy handling, because there are no legacy
runs.

It is idempotent, and it is what makes the database disposable: a corrupted
index, a schema bump, or a directory copied in from elsewhere are all fixed by
running it. That is what allows `SCHEMA_VERSION` to advance without a migration
and what lets the read model stay a pure projection rather than becoming a
second source of truth.

A directory that fails to parse is reported and skipped, not fatal. One
half-written run — a process killed mid-write — should not stop the other
thirty from being indexed.

**One projection function, two callers.** The obvious failure mode for a
derived index is drift: the live write path and the rebuild path construct the
same rows in two places, and over time they stop agreeing, so a rebuild
silently changes what the UI shows. The projection is therefore a single pure
function — run directory artifacts in, read-model rows out — called by the
observer as a run progresses and by `rebuild-index` afterwards. Neither caller
builds rows itself.

That gives the property a test can assert directly, and it is the one test that
keeps the whole "database is a cache" claim honest: run a pipeline against
fakes, snapshot the read model, run `rebuild-index` over the same directory,
and assert the read model is byte-identical. If those ever diverge, the index
has stopped being derived and the design has quietly broken.

### What the read model may not hold

Because it is rebuilt from disk, every column in it must be derivable from
`output/`. This rules out anything the user creates in the UI and the pipeline
does not write — a pinned topic, a "last viewed" timestamp, a note against a
run. There is no such feature in this design, but there is an obvious pull
towards adding one, so the rule is written down: state of that kind belongs in
a separate table that `rebuild-index` does not drop, and mixing it into the
projection tables is what would turn the cache back into a source of truth.

## Pipeline changes

Both seams default to no-ops, so `zeitgeist run` behaves exactly as it does
today.

### RunObserver

A new `zeitgeist/progress.py`:

```python
class RunObserver(Protocol):
    def stage_started(self, stage: Stage) -> None: ...
    def stage_progress(
        self, stage: Stage, done: int, total: int, detail: str
    ) -> None: ...
    def stage_finished(self, stage: Stage, artifact: Path | None) -> None: ...
    def topic_distilled(self, topic: Topic) -> None: ...
    def render_finished(
        self, brief: MediaBrief, path: Path | None, error: str | None
    ) -> None: ...
```

`run_pipeline` takes `observer: RunObserver = NullObserver()`. `distil_topics`
gains an `on_topic: Callable[[Topic], None] | None` callback, invoked as each
future resolves rather than when the pool drains — that is what lets ranking
rows append during the analyse stage, which the mid-analyse screen draws.

### CancelToken

```python
class CancelToken:
    def stop_after_stage(self) -> None: ...
    def abort(self) -> None: ...
    def check(self) -> None: ...          # raises Aborted
    @property
    def stopping(self) -> bool: ...
```

Stop-after-stage is checked at stage boundaries in `run_pipeline`, so the
current stage writes its checkpoint and the run stays resumable — which is what
the button promises. Abort raises `Aborted` from `check()`, called inside the
distil worker before each model call and inside `_render_all` between briefs.

**Known limitation.** `fetch_evidence` is a single opaque `asyncio.run()` with
no interior checkpoint, so abort during ingest cannot take effect until the
fetch returns. The UI shows "aborting…" for up to the remainder of the ingest.
Threading a cancellation token through `BlueskySource`'s async fan-out would
fix it and is deliberately not in scope here. Running each pipeline in a
subprocess would also fix it — abort becomes a kill — but it turns progress
events and log capture into an IPC problem, which is a poor trade for a
single-user local tool whose worst case is waiting out one fetch.

### Log capture

A `logging.Handler` attached to the `zeitgeist` logger for the run's duration
and detached after. Safe as a plain handler because the queue guarantees one
run at a time. It writes two sinks: `run.log` on disk, which is what makes the
post-mortem block work for a run that failed last week, and a bounded in-memory
ring buffer, which is what the SSE stream reads.

That buffer is the seam between the worker thread and the event loop, and it is
the one place the thread boundary needs care. It is a `collections.deque` with
a `maxlen` — `append` and `popleft` are atomic under the GIL, so no lock is
needed — written by the handler on the worker thread and drained by the SSE
generator with `await asyncio.sleep(0.25)` between polls. Polling rather than
`loop.call_soon_threadsafe` into an `asyncio.Queue` because a quarter-second of
latency on a log line is invisible, and it keeps the logging handler free of
any reference to the loop, which matters because the same handler has to work
under `TestClient` and under the CLI.

Progress events cross the same boundary the same way: the observer mutates the
run record and the read model from the worker thread, and the SSE generator
emits a tick that tells the client to invalidate. No pipeline code ever touches
the loop.

At present the pipeline emits four INFO lines per run plus warnings, and
nothing at DEBUG on the live path — the only `log.debug` is in
`consolidate.py`, which left the pipeline in the 2026-08-26 rework. The verbose
toggle would therefore do nothing. Phase C adds DEBUG statements: per-trend
fetch and reply counts in `sources.bluesky`, per-topic distil start and finish
with elapsed and reply-character count in `analysis.distil`, chosen template
and retry attempts in `media.brief`, and per-slot font fitting in
`media.render` — which has no logger at all today, despite the design showing
its name in the log.

**Constraint:** no DEBUG line may carry reply text, post bodies or
`author_key`. `Item`'s docstring and `Reply.author_key` show the project is
deliberate about not storing personal data, and a debug log that dumps reply
text to disk would quietly undo it. Debug lines carry counts, ids, permalinks
and elapsed times.

## Run execution service

### Why a thread, not the event loop

FastAPI is built on asyncio, so the obvious question is whether the pipeline
could run on its loop. It could be made to — but it should not, and the reason
is not the one that first presents itself.

The visible obstacle is that `BlueskySource.fetch_evidence` calls
`asyncio.run(self._gather(...))` internally (`sources/bluesky.py:119`), which
raises when called from a running loop. That is trivially fixable: expose
`_gather` as an `async def fetch_evidence_async` and make the sync method a
thin wrapper. It is also beside the point, because ingest is one of five
blocking things in a run and not the expensive one:

| Stage | Blocking work | Cost |
| --- | --- | --- |
| ingest | `asyncio.run(self._gather(...))`, async internally | seconds |
| analyse | `ThreadPoolExecutor` over **sync** `provider.complete()` | minutes |
| analyse | `Store.record_topics` — `sqlite3` | ms |
| evaluate | 1.3MB JSON write, pydantic over thousands of models | hundreds of ms |
| generate | `generate_briefs` — a sequential loop, one blocking call per topic | minutes |
| generate | `_render_all` — Pillow decode, font fitting, PNG encode | ~100–300ms × N, CPU-bound |

Both providers are synchronous: `anthropic.py` constructs `Anthropic`, not
`AsyncAnthropic`, and `ollama.py` uses `httpx.Client()`. `distil.py` wraps them
in a thread pool precisely because they block. So making ingest loop-native
leaves the two stages that dominate wall-clock time still unable to run there.

Converting the whole pipeline would mean async providers, `gather` plus a
semaphore in place of the `ThreadPoolExecutor`, `run_in_executor` for Pillow
regardless because it is CPU-bound, the same for `sqlite3`, and `run_pipeline`
becoming `async def` with the CLI wrapping it in `asyncio.run`. That is a
rewrite of the pipeline's concurrency model, and it would not change the
conclusion.

**The real reason is isolation.** A run takes minutes, and the UI polls the API
for its entire duration. Sharing a loop means every CPU-bound moment inside the
run — encoding a PNG, serialising 1.3MB of JSON, validating thousands of
models — stalls request handling. The in-flight screen would stutter exactly
when it is being watched. Even a fully async pipeline belongs off the
request-handling loop, so the thread is the design rather than a workaround,
and removing the `asyncio.run` would not justify moving it.

Two consequences follow:

- **The worker constructs its own `Store`.** `store.py:57` calls
  `sqlite3.connect(self._path)` in `__init__`, and the default
  `check_same_thread=True` raises if that connection is used from another
  thread. The API's `Store` and the worker's are separate objects.
- **The read model opens in WAL mode.** The worker writes while the API reads;
  without WAL those reads block behind the writes, surfacing as the in-flight
  poll hitching every time a stage checkpoints.

### Queue and lifecycle

A single worker thread with a FIFO queue, at most one run executing — which is
what the New run screen's "queues it behind …" notice describes.

- `POST /api/runs` enqueues. If the queue is empty and the worker idle, it
  starts immediately; otherwise the response says what it is behind.
- The worker constructs `Settings` from `.env` with the request's overrides
  applied, freezes it into `RunConfig`, writes `run.json` with status
  `running`, and calls `run_pipeline` with an observer that updates the record,
  the read model and the SSE buffer.
- On completion, failure or abort it writes the terminal status and detaches
  the log handler.
- On server startup, any run still marked `running` in the read model is
  marked `interrupted` — the process died mid-run, and the UI should say so
  rather than showing a run that will never progress. An interrupted run is
  resumable from its last good checkpoint like any other.

The queue is in-memory. A restart loses queued runs, which for a single-user
local tool is the right trade against persisting a job table.

On-demand generation runs on a **separate** small executor, not this queue. The
design shows tiles generating on topic detail while a run is in flight, so they
cannot share a worker. That means two concurrent callers of the LLM provider,
which is free on Anthropic and contended on local Ollama, where inference
serialises on one GPU. Documented rather than solved with a global lock.

## API surface

Resource-shaped REST. The merged Topics screen issues three parallel queries
rather than hitting one bespoke endpoint, so each response stays independently
cacheable and the in-flight poll does not drag topic data along with it.

| Phase | Endpoint | Serves |
| --- | --- | --- |
| A | `GET /api/runs?limit&cursor` | Runs list: status, timings, `25 trends → 5 kept`, phrase count, topic labels, thumbnails; for a failure the error, its stage, and what survived |
| A | `GET /api/runs/{id}` | Frozen config, `stages[]`, error, computed `resume_stage` |
| A | `GET /api/runs/{id}/topics` | Full ranking including below the cut |
| A | `GET /api/runs/{id}/topics/{topic_id}` | Dossier, entities, `score_components`, phrases, replies, renders, recurrence |
| A | `GET /api/runs/{id}/log?verbose=` | Historical log for a completed or failed run |
| A | `GET /api/topics?window=6&status=` | Cross-run deduplicated index, recurrence, per-status bucket totals, and the sentiment distribution with its previous-run delta |
| A | `GET /api/renders/{id}/image?size=full\|thumb` | PNG serving |
| C | `GET /api/runs/active` | The in-flight run and the queue |
| C | `GET /api/config/options` | Providers, per-provider models, platforms with enabled flags, templates with slots, `.env` defaults, key-present booleans |
| C | `POST /api/runs` | Start or queue a run; "Re-run config" posts the old run's frozen config |
| C | `POST /api/runs/{id}/resume` | `{stage}` — reuses the existing run directory |
| C | `POST /api/runs/{id}/stop`, `POST /api/runs/{id}/abort` | Stop after this stage; abort now |
| C | `GET /api/runs/{id}/events` | SSE: log lines and progress ticks |
| D | `POST /api/runs/{id}/topics/{topic_id}/renders` | `{mode: "llm", template_id, count}` or `{mode: "manual", template_id, caption_slots}`; also what the below-the-cut `generate ↗` calls |
| D | `DELETE /api/renders/{id}` | Deletes the ledger entry, the PNG and the thumbnail |

`GET /api/runs/{id}/topics` returns the **full** ordering, not just the kept
topics, because the ranking list draws below-the-cut rows with ranks and scores
before dimming them. `ranked.json` holds only the top `top_count`, so the full
ordering is computed once when `run_topics` rows are written — during the run,
or by `rebuild-index` — by ranking every topic in `topics.json` with
`sentiment.rank_score` under the run's frozen `meme_potential_weight`. That is
the same function `select()` ranks with, so the first `top_count` rows agree
with `ranked.json` by construction; `ranked.json` supplies the cut line and
nothing else. The endpoint then queries `run_topics` and does no sorting of its
own. Ranks past the cut exist only in the read model, never in a checkpoint.

Reusing `rank_score` rather than re-deriving the ordering is deliberate: it is
the single place the blend of trend score and meme potential is defined, and a
second implementation in the API would drift from it silently.

`GET /api/config/options` reports whether `ANTHROPIC_API_KEY` is set as a
boolean. The key itself is never returned.

## Frontend

```
web/src/
  api/          generated types, typed fetch client, query hooks
  styles/       tokens.css, reset, fonts
  components/   Chip, StatusPill, StageBar, MemeTile, SectionLabel, RankRow
  features/
    topics/     TopicsPage, TopicCard, MoodBar, TopicDetailPage, GeneratePanels
    runs/       RunsPage, RunRow, InFlightCard, RunDetailPage, StageCards,
                RankingList, LiveLog
    newrun/     NewRunPage and the four config cards
  app/          router, AppLayout (Sidebar), providers
```

Routes: `/`, `/runs`, `/runs/new`, `/runs/:runId`, `/topics/:runId/:topicId`.

Topic detail is run-scoped because the dossier, replies and renders all belong
to one run, and because generating a meme needs an unambiguous run directory to
write into. The breadcrumb still reads `Topics / <topic id> · first seen <run
id>` as designed, with "first seen" computed from the read model. The topics
index links each topic to the most recent run containing it.

`tokens.css` transcribes the handoff's colour, typography and geometry tables
verbatim as custom properties. Component styles live in `.module.css` beside
their component.

Two hooks carry the live behaviour:

- `useActiveRun()` — one query whose `refetchInterval` is `null` when nothing
  is running, so an idle app makes no requests. It is the single source of
  truth for the sidebar card, the run strip, the in-flight cards and the New
  run queue notice.
- `useRunEvents(runId)` — mounts an `EventSource` only on run detail for a live
  run. Log lines accumulate in local state; a progress tick invalidates the run
  queries rather than a timer polling blindly.

### The live log

Follow behaviour is the one piece of UI mechanics worth specifying, because it
is easy to get subtly wrong.

`following` is true while the scroll position is within 24px of the bottom —
a threshold, never an equality test: the log is 11px mono at line-height 1.9,
so lines are 20.9px and exact equality effectively never holds. The value is
held in a ref, mirrored into state only when it flips so the header's indicator
can render without re-rendering on every scroll event. The scroll listener is
attached imperatively and passive, which is what makes the ref necessary rather
than merely tidy: a listener registered once in a mount-only effect captures
its render's variables permanently, so reading state inside it would compare
against the first render's value forever.

New lines pin to the bottom from a `useLayoutEffect` on the line array — layout
effects run before paint, so the jump never renders as a flicker. Four details
that are invisible until they bite: `overflow-anchor: none` on the container,
because the browser's own scroll anchoring fights this logic exactly when it
matters; no `scroll-behavior: smooth`, because lines can arrive faster than a
smooth scroll completes and the view falls permanently behind; incoming SSE
lines batched and flushed per animation frame rather than appended one at a
time; and a client-side cap of ~2000 lines, dropping the oldest, since the DOM
otherwise grows unbounded on a long DEBUG run.

## Decisions taken against the handoff

The handoff asks for several things to be flagged rather than decided
silently. These are the calls made, with reasons.

**The topics screens are merged.** The handoff notes that the landing dashboard
and the topics index overlap and asks for a flag rather than a silent merge.
They are merged into one `/` screen: the hero and mood bar above the two lists,
which is the merge the handoff itself describes as natural. The sidebar's two
destinations become Topics (`/`) and Runs (`/runs`).

**The off-consensus reply signal is dropped.** Topic detail draws a 2px left
border on each reply, accent when it matches the dominant sentiment and white
15% when it does not, and says this is the only signal on those cards. Nothing
computes per-reply sentiment, and doing it properly is a model call per reply.
Every reply gets the accent border. Fabricating the signal on a screen whose
entire purpose is showing what people actually said would be worse than not
having it. Flagged back to the designer as needing either a real source or
removal.

**The template library is read from the manifests.** The design names `drake`,
`always_has_been`, `expanding_brain` and `panik_kalm_panik`; the repository
ships `distracted_boyfriend`, `drake`, `hide_the_pain_harold`,
`is_this_a_pigeon` and `two_buttons`. Only `drake` overlaps. Every template
tile, chip and manual-render slot field is driven by the loaded manifests at
runtime, so the "all 4" chip reads "all 5" today and stays correct as the
library changes. This is what the handoff's own data mapping asks for.

**The model registry is half static, half live.** A checked-in `models.json`
lists Anthropic model ids with their annotations (`default`, `slower`,
`cheap`). For `ollama` the server calls `/api/tags` on the configured host and
lists what is actually pulled, which is the only honest answer for local models.
There is no free-text model field, per the design.

**Verbose captures always, filters on toggle.** The handler runs at DEBUG for
the whole run; the toggle filters what the client renders and what the stream
sends. Flipping it works retroactively on lines already captured, which is what
anyone toggling it mid-run wants. Mapping it literally to `--verbose` — a level
set once at startup — would mean turning it on shows nothing until the next
line arrives.

**Thumbnails are generated, not scaled.** 96px thumbnails written beside each
PNG at render time, by the same code path that writes the render. The Runs list
draws renders at 34px; sending 800KB per thumbnail would not.

## Testing

Backend testing follows the discipline already in the repository: hermetic, no
network, every model call through `FakeLLMProvider`, and `conftest.py`
stripping every environment variable `Settings` reads.

- `tests/run_factory.py`, built the way `tests/template_factory.py` and commit
  0a057d2 established — fixtures constructed through the real models, never
  hand-written dicts — writing genuine artifacts into `tmp_path`. Read-model
  and API tests run against artifacts the pipeline could actually have
  produced.
- `rebuild-index` is tested by building several run directories with the
  factory, indexing them, and asserting the read model matches — then indexing
  a second time and asserting the result is identical, since idempotence is the
  property the whole "database is a cache" claim rests on. A deliberately
  half-written directory asserts it is skipped and reported rather than
  aborting the rebuild.
- A `RecordingObserver`, the progress analogue of `FakeLLMProvider`: run the
  pipeline against fakes and assert the event sequence, including that
  `topic_distilled` fires per topic rather than once at the end.
- Cancellation: a token that trips after N topics, asserting the checkpoint is
  written and the run is genuinely resumable afterwards.
- The API layer via FastAPI's `TestClient` with `Settings` overridden onto
  `tmp_path`, including the SSE stream.

Frontend testing is Vitest with Testing Library, and MSW mocking at the network
layer using handlers typed from the generated OpenAPI types — so a backend
contract change breaks frontend tests rather than surfacing in the browser.
Tests target behaviour, not pixels: follow and release, optimistic render
tiles, the inline delete confirm, provider-to-model list swapping, the queue
notice, the below-the-cut generate link. The design is not snapshot-tested;
high-fidelity CSS is not meaningfully unit-testable, and fidelity is a human
review against the mockups.

The Definition of Done in `CLAUDE.md` grows from four commands to seven:

```bash
uv run ruff check .
uv run ruff format --check .
uv run ty check
uv run pytest
npm --prefix web run lint
npm --prefix web run typecheck
npm --prefix web test
```

OpenAPI type regeneration is folded into `typecheck`, so contract drift fails
there. The Stop hook and CI run all seven.

## Phases

Each phase gets its own implementation plan.

**A — Run records and the read API.** `Topic.trend_status`; `RunRecord`,
`StageRecord` and `RenderRecord`; `run.json` and `renders.json` written by the
pipeline; the renders directory and thumbnails; schema version 3 and the four
new tables; `rebuild-index`; the FastAPI app and every read endpoint; image
serving. No UI. Ends with `uv run zeitgeist run` producing a directory that
`rebuild-index` indexes and the API serves correctly over HTTP — which is also
the point at which `output/` and `data/zeitgeist.db` are cleared, since the
first run under the new models is the first one the API can read.

**B — Frontend shell and read-only screens.** Vite scaffold, `tokens.css`,
generated client, router and layout, the sidebar, and the merged Topics screen,
Runs list, Run detail (completed and failed) and Topic detail. Ends with any
run the CLI has produced browsable end to end.

**C — Run execution.** `RunObserver` and `CancelToken`; the DEBUG log
statements; log capture; the queue and worker; run lifecycle and startup
reconciliation; the write and SSE endpoints; `config/options`; the New run
screen and the in-flight run detail states; the sidebar card and run strip.
Ends with a run startable and watchable from the browser.

**D — Renders as first-class entities.** On-demand generation, model-written
and hand-written; briefing a topic that was never ranked, which is what the
below-the-cut `generate ↗` needs; deletion; the two generation panels and the
rendered grid with its three tile states.

Order matters: B depends on A's endpoints, C on A's records, and D on C's
executor. A and B could overlap once the response models are fixed.

## Deferred

Flagged by the handoff as not yet designed, and deliberately not improvised
here:

- **The full-size meme view.** The largest gap. Memes appear only as
  thumbnails, so there is no screen for a PNG at real scale, the brief and slot
  text behind it, or downloading it.
- **Empty and first-run states.** No runs, no topics, no memes — the first
  screen anyone sees.
- **Failure states beyond the failed run row**: the abort confirmation, a
  partial-failure run, and a source outage where ingest returns nothing. The
  renderer fails per-meme, so partial failure is real.
- **A settings screen** for the `.env` values cut from the New run screen.
- **Mobile layouts.**
- **A "jump to latest" affordance** when the log releases follow. The mocks
  draw the indicator but no way back to the bottom.

Also out of scope, and worth naming so it is a decision rather than an
oversight: cancellation inside the Bluesky fetch, fuzzy cross-run topic
matching, and a global lock serialising the pipeline against on-demand
generation on local Ollama.
