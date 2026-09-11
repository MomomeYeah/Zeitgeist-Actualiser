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

**The web UI replaces the CLI.** The CLI was the first implementation, built
for fast iteration, and this work deletes it rather than maintaining it
alongside the UI. That is what licences moving the stage checkpoints off the
filesystem, which the CLI's documented output contract would otherwise have
made too invasive to justify. See "The CLI is removed" for what happens to each
command, and for how a run is produced before the API can start one.

## Scope

In:

- A FastAPI server exposing REST endpoints over runs, topics and renders.
- A React SPA reproducing the handoff's screens.
- Per-run records the design needs and the pipeline does not currently write:
  frozen config, stage timings, failure detail, a record per render.
- Moving the four stage checkpoints out of `output/<run-id>/*.json` and into
  SQLite, which becomes the source of truth for everything except rendered
  images. See "Data model".
- Clearing `data/zeitgeist.db` and `output/`. Runs written before this work are
  discarded rather than migrated, so the new models can require the fields they
  always populate.
- Progress and cancellation seams in the pipeline, defaulting to no-ops so a
  direct caller need not construct them.
- Deleting `zeitgeist/cli.py`. See "The CLI is removed".
- A run execution service: a queue, a worker thread, live log capture, and
  stop/abort.
- On-demand meme generation, both model-written and hand-written, and render
  deletion.
- The five screens and states the handoff flags as not yet designed: the
  full-size meme view, empty and first-run states, failure and abort states,
  and a settings screen. Designed against the same token table; see "Screens
  the handoff did not design".

Out:

- Authentication and multi-user support. This is a single-user tool on
  localhost.
- Production deployment. Development runs Vite and uvicorn as two processes;
  mounting the built SPA from `serve` is a later addition of about ten lines.
- Mobile layouts, explicitly undesigned in the handoff and deliberately not
  inferred from the desktop ones. See "Deferred".

## Decisions

| Area | Choice | Why |
| --- | --- | --- |
| Backend | FastAPI + uvicorn | Pydantic 2 is already a dependency, so domain models serialise to responses with no translation layer. `ty`-clean. Its OpenAPI schema generates the TypeScript client types. |
| Pipeline execution | A worker thread, never the event loop | A run takes minutes and the UI polls throughout it. Sharing a loop would stall request handling on every CPU-bound moment inside the run. See "Why a thread, not the event loop". |
| Frontend | React + TypeScript + Vite | Largest ecosystem for the pieces this design needs — React Router for six routes, TanStack Query for fetch-on-navigation plus the polled active run. |
| Styling | CSS custom properties + CSS Modules | The handoff's token table maps 1:1 onto `:root` custom properties. The design is bespoke rather than systematic (radii of 11–12px, eight text opacities), so a utility framework's config would be a translation layer the handoff has to be read through. |
| Live updates | SSE for the log, query invalidation for state | The log is the only thing that genuinely streams. A progress tick on the stream invalidates the run queries rather than a timer polling blindly. `EventSource` reconnects on its own and degrades to polling. |
| Storage | SQLite for everything but images | One store for structured data, the filesystem for binaries — Postgres-and-a-bucket, with `output/` as the bucket. Checkpoints and index commit in one transaction, so they cannot disagree. |
| Migrations | None; delete and start again | The codebase is in active development and data loss is acceptable. `SCHEMA_VERSION` and `StoreSchemaError` already refuse a mismatched schema and say to delete — that *is* the strategy. |
| Client types | `openapi-typescript`, checked in | One source of truth for the contract. Regeneration drift fails the gate. |
| Fonts | `@fontsource` | A local tool should not need the network to render correctly. |
| Layout | `web/` in this repo | Dev: Vite proxying `/api` to uvicorn. No CORS, one repository, one contract. |

## What the design assumes the pipeline does not record

Each of these is a display the mockups make and the codebase cannot currently
satisfy. They are the reason phases 1 and 2 exist.

**Per-run config.** Run detail's config line (sources, `trend_limit`,
`posts_per_trend`, `top_count`, model id) and the "Re-run config" action need
the settings frozen at run time. `store.runs` holds `run_id`, `started_at`,
`finished_at`, `status` and `item_count`. Nothing else. Configuration is read
from the ambient environment at each invocation and never persisted, so it is
not recoverable after the fact.

**Per-stage timing and status.** The four stage cards want a name, a duration,
a one-line summary and an artifact with its size. Nothing records stage
boundaries at all, so durations do not exist to be read.

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
on `TrendInfo.status` in the ingest evidence. `Topic` gains a `trend_status`
field, populated in `distil.py` where the `TrendEvidence` is already in hand.
Adding the field is preferable to joining back through the ingest checkpoint on
every read: it is a property of the topic, and the data is present at the point
the topic is constructed.

The field is **required** — `trend_status: TrendStatus`, no default. Every
`TrendEvidence` carries a status, so a topic without one is a bug rather than a
state. See "Data is disposable" for why this needs no migration concession.

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

### Everything lives in SQLite except the images

One store for structured data, the filesystem for binaries — the shape a
production deployment would use with Postgres and object storage, with
`output/` standing in for the bucket.

SQLite is the source of truth. The four stage checkpoints become rows rather
than files, and `run.json` and `renders.json` — which earlier drafts of this
spec invented to keep the filesystem authoritative — are gone. Rendered PNGs
and their thumbnails stay on disk at
`output/<run-id>/renders/<render_id>.png`, because image bytes belong behind a
static file server or a CDN and never in a database. Swapping the local
directory for real object storage later touches one module.

The consequence to hold onto: the database is authoritative for *whether a
render exists*. A PNG deleted out from under it renders as a failed tile, not
a crash.

### Data is disposable

Until stated otherwise, deleting `data/zeitgeist.db` and starting again is an
acceptable answer to any schema problem. No migration code is written.

`SCHEMA_VERSION` and `StoreSchemaError` stay exactly as they are and become
the whole migration strategy: a mismatched schema refuses to open and tells
you to delete the file. That is the right behaviour under this stance, because
it turns silently wrong data into a clear instruction.

Two things follow. Runs written before this work are discarded rather than
migrated, which is what lets `Topic.trend_status` be required rather than
carrying a `| None` that describes a historical accident. And new fields are
required wherever the pipeline always populates them: **optionality expresses
a real state, never a migration concession.** A field is `| None` only where
there genuinely is no value — a stage that has not started, a run that has not
finished, a render that has not failed.

Disposable is not free, though, and nothing here should read as licence to
delete casually. A run costs minutes and real model calls to reproduce — the
economics that made resuming from `generate` worth building in the first
place.

### Checkpoints

The four stage artifacts move into one table, holding exactly the JSON
`_write` produces today:

```sql
CREATE TABLE checkpoints (
    run_id     TEXT NOT NULL,
    stage      TEXT NOT NULL,   -- ingest | analyse | evaluate | generate
    payload    TEXT NOT NULL,   -- JSON array of model_dump(mode="json")
    written_at TEXT NOT NULL,
    PRIMARY KEY (run_id, stage)
);
```

Whole documents rather than normalised tables, and that is deliberate.
`evidence` is `list[TrendEvidence]`, which is a `TrendInfo` plus
`list[PostEvidence]`, each of which is an `Item` carrying a discriminated
`Metrics` union plus `list[Reply]`. Normalising that means five or six related
tables and reassembling exact pydantic instances on read so resuming a run
still round-trips. Nothing queries *inside* evidence except "the replies for
this topic's items", so the schema work buys nothing while the models are
still moving. `model_validate_json` round-trips a payload perfectly.

`pipeline._write` and `_read` become `store.write_checkpoint(run_id, stage,
models)` and `store.read_checkpoint(run_id, stage, schema)`. `run_pipeline`
already takes a `Store`, so the seam exists; `FileNotFoundError` becomes a
`MissingCheckpoint` carrying the same meaning.

Size is bounded and known: `evidence` is ~1.3MB per run and the other three
are small, so roughly 1.5MB per run. A thousand runs is 1.5GB in one file,
which SQLite handles without complaint. Because evidence is read only for
topic detail's replies, pruning it later is a `DELETE` rather than a
file-management script.

### Tables

Two of the three tables `store.py` has today are absorbed rather than kept
alongside the new ones. `runs` holds run id, timings, status and item count,
which is a strict subset of `run_records`; `topics` holds a run's label slug
and trend score, which is a strict subset of `run_topics`. Keeping either pair
would mean two tables to write, two to keep agreeing, and two places to look.
`topic_scores` survives unchanged: per-platform sub-scores have no home in
`run_topics`, and `previous_sub_scores` is the one query that needs them. It
joins to `run_records` instead of `runs`.

Alongside `checkpoints` and `topic_scores`, then:

- `run_records` — one row per run: status, timings, the frozen `RunConfig` as
  JSON, error class and stage, item count, and the counts the Runs list shows
  (trends fetched, topics kept, phrases found). Absorbs `runs`.
- `run_stages` — one row per stage per run: status, timings, artifact size,
  summary line.
- `renders` — one row per render. Source of truth, and mutable: deleting a
  render is a `DELETE` here plus unlinking two files.
- `log_lines` — one row per captured line: run id, timestamp, level, logger
  name, message.
- `settings` — `key`, `value`, `updated_at`. One row per tuning field the
  settings screen has overridden; absent means fall through to `.env`. See
  "Settings storage".
- `run_topics` — one row per topic per run, holding what the topics index and
  ranking lists filter or sort on: `trend_status`, `event_sentiment`,
  `conversation_register`, `meme_potential`, `trend_score`, `final_score`,
  `final_rank`, `post_count`, `label_slug`, and the top recurring phrase with
  its author count. Absorbs `topics`.

  Meme counts are **not** a column here. They are
  `COUNT(*) FROM renders WHERE run_id = ? AND topic_id = ?`, joined at query
  time. A denormalised `render_count` would have to be kept correct on every
  render insert, failure and delete — including from the separate on-demand
  executor — to save a join over a table holding single digits per run.

  The counts on `run_records` are a deliberate exception to that, not an
  inconsistency: trends fetched, topics kept and phrases found are written once
  in the transaction that completes the run, from data that never changes
  afterwards. Renders are created and deleted long after a run ends, from a
  second executor. Immutable-after-write is safe to denormalise;
  mutable-after-write is not.

`SCHEMA_VERSION` goes to 3.

`run_topics` holds nothing that is not in the `analyse` and `evaluate`
payloads — it is those payloads flattened into columns you can filter, sort and
join on. It is a real table rather than a view over `json_each(payload)`
because the cross-run queries (recurrence, the stale bucket, pagination) would
otherwise parse every run's `analyse` payload on every request: at a thousand
runs, a hundred megabytes of JSON per page load.

It is written in the same transaction as the checkpoint it flattens, so the two
cannot disagree. That transaction is what the filesystem design could not
offer, and it is why nothing in this spec needs a command to repair the two
against each other.

Dossier prose, entities, the full phrase list and replies are not projected.
Topic detail reads the `analyse` and `ingest` payloads for the one topic being
viewed.

### Re-running generate appends, it does not replace

The old CLI wrote renders to a deterministic `{position:02d}-{topic_id}.png`,
so re-running it overwrote the previous attempt. `run_pipeline` mints a fresh
`uuid4` per brief instead, so resuming a run with `start_at=Stage.GENERATE` —
the tuning loop this design documents under "The tuning loop" — inserts a new
`renders` row and a new pair of files alongside the old ones rather than
replacing them. Three tuning passes over one topic leave three renders behind
it, and the meme count this spec derives as `COUNT(*) FROM renders` reads 3,
not 1. This is not fixed here: a correct fix needs a render-deletion path —
the row, the PNG and the thumbnail — and render deletion is a later phase's
work (see `DELETE /api/renders/{id}` above). When that phase lands, it must
decide whether a re-run first clears the run's prior `auto` renders for the
topic, and it must leave `manual` renders untouched regardless.

**Answered in phase 4.** It does clear them, on one condition. A re-run of
`generate` removes each topic's prior `auto` renders — row, PNG and
thumbnail — once the replacement is on disk *and rendered successfully*,
and never touches a `manual` render. A pass whose render fails clears
nothing, so a prompt edit that overflows a caption box leaves the previous
render in place beside the failure rather than destroying the output being
tuned against. On-demand generation through `POST .../renders` is the other
exception and always appends, because it is an additive action somebody
took rather than a stage re-running. See
`zeitgeist/renders.py:clear_auto_renders` and
`docs/superpowers/plans/2026-09-06-web-ui-generation-backend.md`.

### Models

`RunConfig` is the frozen settings subset that run detail's config line and
"Re-run config" need: `sources`, `trend_limit`, `posts_per_trend`,
`top_count`, `meme_potential_weight`, `phrase_min_authors`,
`distil_char_budget`, `distil_concurrency`, `llm_provider`, `llm_model`,
`template_ids`. A copy, not a reference to live `Settings`.

```python
class StageRecord(BaseModel):
    model_config = STRICT

    stage: Stage
    status: Literal["queued", "running", "ok", "failed", "skipped"]
    started_at: datetime | None
    finished_at: datetime | None
    artifact_bytes: int | None
    summary: str                  # "25 trends, 214 posts, 3,318 replies"


class AutoOrigin(BaseModel):
    """A render the model briefed: it chose the template and said why."""

    model_config = STRICT
    provenance: Literal["auto"] = "auto"
    rationale: str


class ManualOrigin(BaseModel):
    """A render written by hand. No model call, so no choice to explain."""

    model_config = STRICT
    provenance: Literal["manual"] = "manual"


Origin = Annotated[AutoOrigin | ManualOrigin, Field(discriminator="provenance")]


class RenderRecord(BaseModel):
    model_config = STRICT

    id: str                       # uuid4 hex, and the PNG's filename
    run_id: str
    topic_id: str
    template_id: str
    caption_slots: dict[str, str]
    origin: Origin
    status: Literal["generating", "ready", "failed"]
    error: str | None             # set only when status is "failed"
    created_at: datetime
```

Every `| None` above is a real state: a queued stage has not started, a
running one has not finished, a failed one wrote no artifact, a ready render
has no error.

`rationale` lives on `AutoOrigin` rather than on `RenderRecord` because a
hand-written render has no template choice to justify — the person made it.
Holding it as `rationale: str` with `""` for manual renders, or as
`rationale: str | None` beside a separate `provenance` flag, both make
`provenance="manual"` with a non-empty rationale representable and
meaningless. This is the discriminated-union shape `Metrics` already uses in
`models.py`, for the same reason: the row deserialises back to the concrete
class rather than to whichever union member happens to validate.

`StageRecord` is deliberately **not** split the same way, even though its
status and its timestamps co-vary. A render is created as one kind and never
changes; a stage moves `queued → running → ok`, so a union would mean the
record changing class as it progresses — a worse model of a mutable in-flight
record than four honest optionals. The rule is unrepresentable-invalid-states
where a value is fixed at creation, not everywhere a `Literal` appears.

### No rebuild command

There is deliberately none. Earlier drafts of this spec carried one, and it
does not survive the move to SQLite.

Its consistency justification is gone: `run_topics` is written in the same
transaction as the checkpoint it flattens, so it cannot drift. Its convenience
justification was self-defeating: a schema change to `run_topics` bumps
`SCHEMA_VERSION`, which means deleting the database, which deletes the
`checkpoints` rows a rebuild would need as its source. And resume needs
nothing, because resuming from `generate` does not rewrite the `analyse`
checkpoint, so the rows flattened from it are still correct.

The one case that survives — a bug in the flattening logic, with checkpoints
intact — is a handful of lines against the store when it happens, not a command
with an entry point and tests. Worth stating that it is absent by decision
rather than oversight, because a derived table invites one.

## Pipeline changes

Both seams default to no-ops, so a caller wanting neither — a test, or the dev
harness — constructs neither.

### RunObserver

A new `zeitgeist/progress.py`:

```python
class RunObserver(Protocol):
    def stage_started(self, stage: Stage) -> None: ...
    def stage_progress(
        self, stage: Stage, done: int, total: int, detail: str
    ) -> None: ...
    def stage_finished(self, stage: Stage, payload_bytes: int | None) -> None: ...
    def topic_distilled(self, topic: Topic) -> None: ...
    def render_finished(self, render: RenderRecord) -> None: ...
```

`stage_finished` reports the checkpoint's payload size rather than a path,
because checkpoints are rows now; `None` is a stage that wrote none, which is a
failed or skipped one. `render_finished` carries the whole `RenderRecord`
rather than a brief and a path, since the record already holds the outcome —
including `status="failed"` and its error, which is how a per-meme
`RenderError` reaches the UI as a tile with a message instead of vanishing.

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
run at a time. It writes two sinks: the `log_lines` table, which is what makes
the post-mortem block work for a run that failed last week, and a bounded
in-memory ring buffer, which is what the SSE stream reads.

Rows rather than a file because the verbose toggle becomes `WHERE level >= ?`
and the log endpoint gets real pagination, neither of which a flat file does
well. Lines are inserted in batches drained from the same deque that feeds the
stream, not a row per `emit` — a DEBUG run emits several hundred lines and a
transaction each would be gratuitous.

That buffer is the seam between the worker thread and the event loop, and it is
the one place the thread boundary needs care. It is a `collections.deque` with
a `maxlen` — `append` and `popleft` are atomic under the GIL, so no lock is
needed — written by the handler on the worker thread and drained by the SSE
generator with `await asyncio.sleep(0.25)` between polls. Polling rather than
`loop.call_soon_threadsafe` into an `asyncio.Queue` because a quarter-second of
latency on a log line is invisible, and it keeps the logging handler free of
any reference to the loop, which matters because the same handler has to work
under `TestClient` and under the dev harness.

Progress events cross the same boundary the same way: the observer writes
`run_records`, `run_stages` and `run_topics` from the worker thread, and the
SSE generator
emits a tick that tells the client to invalidate. No pipeline code ever touches
the loop.

At present the pipeline emits four INFO lines per run plus warnings, and
nothing at DEBUG on the live path — the only `log.debug` is in
`consolidate.py`, which left the pipeline in the 2026-08-26 rework. The verbose
toggle would therefore do nothing. Phase 3 adds DEBUG statements: per-trend
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

## The CLI is removed

`zeitgeist/cli.py` is deleted in phase 1. The web UI is the interface; a
second,
parallel product surface for the same pipeline is not maintained.

`zeitgeist` remains the one console entry point, but it takes no subcommands —
bare invocation starts the server, with `--host`, `--port` and `--reload` as
its only flags. Everything `argparse` currently parses moves into the API:
`--run-id` and `--resume-from` become `POST /api/runs/{id}/resume`,
`--templates` becomes a field on that request and on `POST /api/runs`, and
`--verbose` stops existing as a startup flag at all, because the server always
captures at DEBUG and the toggle filters.

`pyproject.toml`'s `[project.scripts]` entry names `zeitgeist.cli:main`, so it
goes in the same commit — leaving the package with no console entry point until
phase 2 restores it pointing at the server. Deleting the module while
`pyproject.toml` still names it fails `uv sync --locked`, which is CI's first
step, so everything behind it fails too.

`validate-templates` moves to `scripts/validate_templates.py`, beside the
`preview_template_boxes.py`, `make_golden.py` and `capture_bluesky_fixtures.py`
already there. It builds no `Settings` and calls
`media.templates.validate_templates`, which does not move — only its entry
point does. `tests/test_cli.py` goes with the module it tests.

### Running the pipeline before the worker exists

Deleting the CLI in phase 1 leaves nothing able to start a run until
`POST /api/runs` lands in phase 3, and nothing able to produce data for the
screens until then either.

So phase 1 also adds `scripts/run_pipeline.py`: a dev harness that builds
`Settings`, a source, a provider and a `Store`, then calls `run_pipeline`.
Fifteen lines, no `argparse`, no console entry point, no README mention.

It stays for the life of the project, because scripted and repeated runs during
development stay useful after the API can start one, and it costs nothing to
keep. This is deliberately not the CLI under another name: a CLI is a product
surface — installed, documented, argued about, tested as a contract — and this
is a developer's harness that happens to call the same function.

### The tuning loop

The loop this replaces is `--resume-from generate --templates drake`: edit a
prompt or a manifest, re-render the same frozen topics, look at the output. Two
things make the UI version work, and one of them is an addition.

Template manifests are re-read per run by `load_templates`, so editing box
coordinates needs no restart. Prompt edits live in Python and need one, which
`--reload` gives — but uvicorn's reloader kills the worker thread mid-run if a
file is saved while a pipeline is in flight. The run is reconciled to
`interrupted` on restart so nothing corrupts, but it is lost. `serve` therefore
does **not** reload by default; `--reload` is an explicit opt-in for when
nothing is running.

The addition: the design's "Resume from &lt;stage&gt;" button takes no options,
so there is no way to resume with the template library narrowed — which is
exactly the loop. `POST /api/runs/{id}/resume` accepts an optional
`template_ids`, and the button gets a template selector beside it. Phase 7's
topic-detail panel is the better loop for a single topic; this covers the
whole-run case the button already implies.

The one unrecoverable loss is `jq` over a checkpoint file. It is a one-liner,
not a missing capability:

```bash
sqlite3 data/zeitgeist.db "select payload from checkpoints where run_id='...' and stage='analyse'" | jq '.[] | {label, trend_score}'
```

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
| analyse | checkpoint and `run_topics` write — `sqlite3` | ms |
| ingest | 1.3MB checkpoint write, pydantic over thousands of models | hundreds of ms |
| generate | `generate_briefs` — a sequential loop, one blocking call per topic | minutes |
| generate | `_render_all` — Pillow decode, font fitting, PNG encode | ~100–300ms × N, CPU-bound |

Both providers are synchronous: `anthropic.py` constructs `Anthropic`, not
`AsyncAnthropic`, and `ollama.py` uses `httpx.Client()`. `distil.py` wraps them
in a thread pool precisely because they block. So making ingest loop-native
leaves the two stages that dominate wall-clock time still unable to run there.

Converting the whole pipeline would mean async providers, `gather` plus a
semaphore in place of the `ThreadPoolExecutor`, `run_in_executor` for Pillow
regardless because it is CPU-bound, the same for `sqlite3`, and `run_pipeline`
becoming `async def` with its callers wrapping it in `asyncio.run`. That is a
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
- **The database opens in WAL mode.** The worker writes while the API reads;
  without WAL those reads block behind the writes, surfacing as the in-flight
  poll hitching every time a stage checkpoints.

### Queue and lifecycle

A single worker thread with a FIFO queue, at most one run executing — which is
what the New run screen's "queues it behind …" notice describes.

- `POST /api/runs` enqueues. If the queue is empty and the worker idle, it
  starts immediately; otherwise the response says what it is behind.
- The worker constructs `Settings` from `.env` with the request's overrides
  applied, freezes it into `RunConfig`, inserts a `run_records` row with status
  `running`, and calls `run_pipeline` with an observer that updates the record,
  `run_topics` and the SSE buffer.
- On completion, failure or abort it writes the terminal status and detaches
  the log handler.
- On server startup, any run still marked `running` in `run_records` is
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
| 2 | `GET /api/runs?limit&cursor` | Runs list: status, timings, `25 trends → 5 kept`, phrase count, topic labels, thumbnails; for a failure the error, its stage, and what survived |
| 2 | `GET /api/runs/{id}` | Frozen config, `stages[]`, error, computed `resume_stage` |
| 2 | `GET /api/runs/{id}/topics` | Full ranking including below the cut |
| 2 | `GET /api/runs/{id}/topics/{topic_id}` | Dossier, entities, `score_components`, phrases, replies, renders, recurrence |
| 2 | `GET /api/runs/{id}/log?verbose=` | Historical log for a completed or failed run |
| 2 | `GET /api/topics?window=6&status=` | Cross-run deduplicated index, recurrence, per-status bucket totals, and the sentiment distribution with its previous-run delta |
| 2 | `GET /api/renders/{id}` | One render with its `caption_slots` and, for an auto render, its `rationale`. Deep-links the full-size view |
| 2 | `GET /api/renders/{id}/image?size=full\|thumb` | PNG serving |
| 2 | `GET /api/settings` | Every tunable field with its value and which layer supplied it |
| 3 | `PUT /api/settings` | Writes the `settings` table. Rejects any field outside the seven tunables |
| 3 | `GET /api/runs/active` | The in-flight run and the queue |
| 3 | `GET /api/config/options` | Providers, per-provider models, platforms with enabled flags, templates with slots, `.env` defaults, key-present booleans |
| 3 | `POST /api/runs` | Start or queue a run; "Re-run config" posts the old run's frozen config |
| 3 | `POST /api/runs/{id}/resume` | `{stage, template_ids?}` — reuses the run's existing checkpoints; `template_ids` narrows the library, which is the tuning loop |
| 3 | `POST /api/runs/{id}/stop`, `POST /api/runs/{id}/abort` | Stop after this stage; abort now |
| 3 | `GET /api/runs/{id}/events` | SSE: log lines and progress ticks |
| 4 | `POST /api/runs/{id}/topics/{topic_id}/renders` | `{mode: "llm", template_id, count}` or `{mode: "manual", template_id, caption_slots}`; also what the below-the-cut `generate ↗` calls |
| 4 | `DELETE /api/renders/{id}` | Deletes the `renders` row, the PNG and the thumbnail |

`GET /api/runs/{id}/topics` returns the **full** ordering, not just the kept
topics, because the ranking list draws below-the-cut rows with ranks and scores
before dimming them. The `evaluate` checkpoint holds only the top `top_count`,
so the full ordering is computed once when `run_topics` rows are written, by
ranking every topic in the `analyse` payload with `sentiment.rank_score` under
the run's frozen `meme_potential_weight`. That is the same function `select()`
ranks with, so
the first `top_count` rows agree with the `evaluate` checkpoint by
construction; that checkpoint supplies the cut line and nothing else. The
endpoint then queries `run_topics` and does no sorting of its own. Ranks past
the cut exist only in `run_topics`, never in a checkpoint.

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
  components/   Chip, StatusPill, StageBar, MemeTile, SectionLabel, RankRow,
                EmptyState, InlineConfirm
  features/
    topics/     TopicsPage, TopicCard, MoodBar, TopicDetailPage, GeneratePanels
    runs/       RunsPage, RunRow, InFlightCard, RunDetailPage, StageCards,
                RankingList, LiveLog
    renders/    RenderDetailPage
    newrun/     NewRunPage and the four config cards
    settings/   SettingsPage and its three cards
  app/          router, AppLayout (Sidebar), providers
```

Routes: `/`, `/runs`, `/runs/new`, `/runs/:runId`, `/topics/:runId/:topicId`,
`/runs/:runId/renders/:renderId`, `/settings`.

`EmptyState` and `InlineConfirm` are shared primitives rather than per-screen
code because both appear in several places and both are patterns rather than
one-offs: the empty block on Runs, Topics and Topic detail, and the swap-in-place
confirm on the render tile, the abort button and the meme view's delete.

Topic detail is run-scoped because the dossier, replies and renders all belong
to one run, and because generating a meme needs an unambiguous run to
attach to. The breadcrumb still reads `Topics / <topic id> · first seen <run
id>` as designed, with "first seen" computed from `run_topics`. The topics
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

## Screens the handoff did not design

The handoff flags five gaps and asks that they be designed rather than
improvised. They are designed here, against the same token table, and they are
in scope. Mobile is the one exception and stays out — see "Deferred".

Two rules govern all of it, both taken from the handoff rather than invented:
**no modals**, because the design confirms a render deletion by swapping the
tile footer in place and says so explicitly; and **no new tokens**, because
anything needing a colour the table does not have is a sign the screen is
fighting the design rather than extending it.

### Full-size meme view

Route `/runs/:runId/renders/:renderId`, `content-width` 1000px. Deep-linkable,
which is why `GET /api/renders/{id}` exists rather than renders arriving only
embedded in topic detail.

Breadcrumb `Topics / <topic title> / <template id>`, the template id in mono.
Header: the topic title in Outfit 800/28/1.12/`-.03em`, matching topic detail,
with a chip row beneath — template id (mono, `accent-tint`) and `auto` or
`manual` (white 8%). A metadata line in mono 400/10.5 carries
`<run id> · <created> · <width>×<height> · <size>`.

Body is `1fr 320px`, 14px gap:

- **The image.** `surface-log` fill so a pale meme has something to sit
  against, radius 14, 1px `border`, 18px padding, the PNG centred at
  `max-height: 70vh` and `object-fit: contain`. Never upscaled past its natural
  size — these are 1180px templates and a stretched meme looks broken.
- **The brief.** A `surface` card, radius 9, 16px padding. Section label THE
  BRIEF, then one block per slot: the slot's real name in mono 700/9.5/`.12em`
  uppercase `text-40`, the caption beneath in Outfit 400/13/1.55, blocks
  separated by `divider` hairlines. For an auto render, a second section label
  WHY THIS TEMPLATE and the rationale in Outfit 400/13 `text-70`. For a manual
  render that section is absent entirely — replaced by `written by hand` in
  mono 400/10 `text-35`. The `AutoOrigin`/`ManualOrigin` split is what makes
  that a presence check rather than an empty-string check.
- Footer of the brief card: an accent pill **Download PNG**, and a ghost
  **Delete** carrying the same inline confirm as the tile.

### Empty states

One pattern, two weights. The distinction is whether the emptiness is the
app's condition or the user's own doing.

**A genuinely empty app** gets a centred block inside the normal content area —
header and sidebar stay, so nothing looks broken. `surface` fill, 1px dashed
`border-strong`, radius 14, 40px padding, `max-width: 420px`, centred.
Headline Outfit 700/15 `text`; body Outfit 400/12.5/1.5 `text-70`, two lines at
most; then an accent pill button when there is an obvious next step.

| Where | Headline | Body | Action |
| --- | --- | --- | --- |
| Runs and Topics, no runs at all | Nothing has run yet | A run reads Bluesky, works out what is trending, and generates memes about it. The first one takes a few minutes. | **New run** |
| Topics, runs exist but nothing current | No topics in the last 6 runs | Everything has gone stale. Start a run to see what is trending now. | **New run** |
| Topic detail, nothing rendered | — | A dashed tile row reading `Nothing rendered yet — use the panel above` in mono 10.5 `text-35`, in place of the grid | — |

The no-runs state is the first screen anyone sees, which is why it is the one
place the app explains what it does.

**A filter that matched nothing** gets a single line, not a card: `No topics
with this status.` in Outfit 400/12.5 `text-35`, 24px vertical padding,
centred. Lighter on purpose — the user did this to themselves and the remedy is
one click away in the chip row above.

**A run whose generate stage produced nothing** is not an empty screen at all;
the ranking is still there. A line sits above it in mono 400/10.5
`contrast-light` — `No memes were rendered — every brief failed` — and every
row shows `generate ↗` where its thumbnails would be.

### Failure and abort states

**Abort confirmation** swaps in place, exactly as the render tile's delete
does. The ghost **Abort** button becomes `contrast` at 10% fill with a
`rgba(61,99,230,.35)` border, reading `Abort run?` in `contrast-light` with
`yes` / `no` in mono 700/10 separated by a `·`. 150ms ease-out. Reverts on
`no`, on `Escape`, or on blur. **Stop after this stage** needs no confirm — it
is not destructive.

**A partially failed run** needs no new status. The run completed, so
`RunRecord.status` stays `ok`, and "partial" is derived from `renders` where
status is `failed`:

- Runs list: the pill reads `OK · 3 of 5`, the `3 of 5` in `contrast-light`
  against the usual `accent-tint` fill.
- Run detail: the generate stage card keeps its accent bar — the stage did run
  — but its summary reads `3 of 5 rendered · 2 failed`, and the failed rows in
  the ranking show a dashed `rgba(61,99,230,.35)` tile with `failed` in mono
  9.5 `contrast-light` where the thumbnail would be.

**A source outage** — ingest returning nothing — is a failed run with one
distinguishing feature: there is no checkpoint, so there is nothing to resume.
`resume_stage` is `None`, and the UI must not offer a resume it cannot honour.
The run row reads `SourceError in ingest — no trends returned` in column two,
`nothing written` in column three, and column four shows `re-run ↗` in
`contrast-light` rather than a resume command. On run detail the **Resume
from** button is absent, not disabled, and **Re-run config** carries the action
alone.

### Settings

Route `/settings`, reached from a third sidebar nav item beneath Runs. This is
the one place these screens change the handoff's own layout rather than
extending it; the in-flight card still pins to the bottom via `margin-top:
auto`, so nothing else moves.

Layout mirrors New run: `1fr 320px`, 18px gap, `content-width` 1000px, cards of
`surface` at radius 12 and `17px 19px` padding, 16px between them.

Three cards — **FAN-OUT** (`trend_limit`, `posts_per_trend`,
`bluesky_fetch_concurrency`), **RANKING** (`meme_potential_weight`,
`phrase_min_authors`), **DISTILLATION** (`distil_char_budget`,
`distil_concurrency`). Each field is a row: name in mono 600/11.5, a 72px input
right-aligned in mono 600/12 on `surface-log` with a 1px `border` at radius 8,
and one line of explanation beneath in Outfit 400/11.5 `text-55` — lifted from
the comments already in `config.py`, which explain every one of these better
than new copy would. `trend_limit` carries the hint `max 25 · API ceiling`,
because 25 is the endpoint's limit rather than a preference.

Every field shows where its value came from, as a mono 9.5/`.12em` chip:
`SET HERE` in `accent-tint`, `FROM .env` in white 8%, or `DEFAULT` in
`text-30`. Making the layering visible is the point — a settings screen that
hides which layer won is worse than no settings screen.

Right column: an accent **Save** button full-width at 14px padding and radius
9, a ghost **Reset to .env** beneath it that deletes the row so the fallback
applies, and a mono 10.5 `text-35` note — `Changes apply to new runs. A run in
flight keeps the config it froze.` That is true rather than reassuring:
`RunConfig` is frozen per run.

### Jump to latest

When the live log releases follow, the accent `following` indicator becomes a
button: the same 6px dot plus `jump to latest` in mono 600/9.5 accent on an
`accent-tint` fill, radius 20, `4px 9px`. Clicking scrolls to the bottom and
re-engages following. This is the one addition of my own rather than one the
handoff asked for — the mocks draw the indicator but no way back.

### Settings storage

A `settings` table — `key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at
TEXT NOT NULL` — and a custom `pydantic-settings` source that reads it.

Precedence, highest first: constructor arguments, then environment variables,
then the `settings` table, then `.env`, then field defaults. A shell variable
beats the UI because an explicit `TREND_LIMIT=10` in front of a command should
still win; the UI beats `.env` because the table is the more recent, more
deliberate act.

Two traps worth stating, because both are easy to walk into:

- **The source cannot read `Settings.db_path`.** Resolving the database
  location from the object being constructed is circular. The source reads
  `DB_PATH` from the environment and `.env` directly, defaulting to
  `data/zeitgeist.db`, independent of the instance.
- **Only the seven tuning fields are writable.** `db_path`, `output_dir`,
  `templates_dir`, `font_path`, `anthropic_api_key`, `ollama_host`,
  `llm_provider`, `llm_model` and `sources` are not exposed and the endpoint
  rejects them. A UI that can rewrite where the database lives, or that stores
  an API key in a table, is a different and worse thing than a tuning screen.

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
anyone toggling it mid-run wants. The handoff maps this control to the CLI's
`--verbose`; with the CLI gone there is nothing to map to, and the toggle is
purely a filter over what the server has already captured.

**New run's metadata line changes.** The handoff has it read `defaults come
from .env · changes apply to this run only`. With a settings screen writing a
table that layers over `.env`, that is no longer where the defaults come from.
It becomes `defaults come from settings · changes apply to this run only`, with
Settings a link. The second clause is unchanged and still true.

**Thumbnails are generated, not scaled.** 96px thumbnails written beside each
PNG at render time, by the same code path that writes the render. The Runs list
draws renders at 34px; sending 800KB per thumbnail would not.

**Artifact filenames lose their extensions.** The design draws the artifact
name on each stage card (`evidence.json`, `topics.json`, `ranked.json`,
`briefs.json`) and uses one in the failed run row's copy, "ranked.json intact".
Those are no longer files. Showing a filename for a database row would be a
small lie on a screen whose whole job is telling you what a run actually did.

The names themselves are worth keeping — `evidence`, `topics`, `ranked`,
`briefs` are the pipeline's own vocabulary and appear in the resume request,
log lines and this spec. So the extension goes and the name stays: stage cards read
`evidence · 1.3 MB`, and the failed row reads `ranked checkpoint intact`. Sizes
come from the payload length rather than `stat`.

**The ranking row shows a meme count, not thumbnails.** The design draws
42px tiles in the ranking's fifth column. `GET /api/runs/{id}/topics`
returns `render_count` — `Store.render_counts`, ready renders only — and no
render ids, and addressing an image needs an id. Drawing the tiles would
mean one extra request per row to show what topic detail shows one click
away, so the row states the count.

**The Runs pill drops the `3 of 5` partial form.** `RunSummary.render_ids`
comes from `Store.renders_for_run`, which filters on nothing and so counts
`ready`, `generating` and `failed` alike. Partial failure is shown where the
contract carries it: run detail's generate stage card renders
`StageRecord.summary`, which the pipeline already writes as `3 of 5
rendered`, and a thumbnail whose PNG is missing renders as the designed
failed tile.

**The mood line reports sentiment only.** The handoff has it cover register
skew and average meme potential against the previous run. `TopicIndex`
carries neither, so the line names the leading sentiment, its share of the
window, and its change against the previous run. The comparison is dropped
rather than shown as zero when there is no previous run.

**The Runs metadata line counts the page, and names every status.** `GET
/api/runs` is cursor-paginated and returns no archive totals, so `27 total ·
24 ok · 3 failed` becomes `25 shown · 22 ok · 2 failed · 1 aborted`. The
handoff's `ok · failed` pair does not fit a `RunStatus` with five members:
grouping everything-not-ok under "failed" calls an aborted run a failure,
and counting only those two prints a total the parts do not add up to.
Every distinct source across the page is named rather than one claimed.

**The secondary chip shows secondary registers.** The design's `2nd:
delight, awe` is labelled as secondary sentiments. `Dossier` has no such
field and does have `secondary_registers`, so the chip shows what the
pipeline actually records.

**`RenderDetailPage` grows the missing-image state `MemeTile` already
designed.** The handoff's full-size meme view assumes the PNG behind it
always exists. A real run walked in a real browser found a render whose PNG
had been deleted — the half-succeeded case this phase's contract already
carries — and the raw `<img>` there showed the browser's native
broken-image icon while still offering a "Download PNG" link for a URL that
404s. Fixtures could not catch this: every MSW-served render in this phase's
tests points at an image URL nothing ever asks the browser to resolve. The
fix gives the full-size image the same `onError` treatment `MemeTile`
already has — a styled failed state using `--contrast-border` and
`--contrast-light`, with the download link withdrawn rather than left
pointing at a 404 — so the one screen designed to be deep-linked is also the
one most likely to meet a missing file, and now does so without a broken
image or a dead link.

## Testing

Backend testing follows the discipline already in the repository: hermetic, no
network, every model call through `FakeLLMProvider`, and `conftest.py`
stripping every environment variable `Settings` reads.

- `tests/run_factory.py`, built the way `tests/template_factory.py` and commit
  0a057d2 established — fixtures constructed through the real models, never
  hand-written dicts — writing whole runs into a `Store` backed by `tmp_path`.
  Store and API tests then run against rows the pipeline could actually have
  written, through the same `write_checkpoint` the pipeline calls.
- The flattening logic directly: known `analyse` and `evaluate` payloads in,
  expected `run_topics` rows out. It is a pure function, so this needs neither
  a pipeline nor a store.
- Checkpoint round-tripping: write each stage's models through
  `write_checkpoint`, read them back with `read_checkpoint`, assert equality.
  This is what resuming a run depends on, and a blob that does not round-trip
  breaks resume silently rather than loudly.
- Transactional coupling: a checkpoint write that raises partway leaves
  neither the payload nor its `run_topics` rows behind.
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

**It grows in phase 5, not before.** `web/` does not exist until then, so
adding the three npm commands to `CLAUDE.md`, the Stop hook and the CI workflow
any earlier turns every phase 1–4 pull request red for a directory that is not
supposed to exist yet. Phase 5's plan owns that change, alongside the Vite
scaffold that makes the commands runnable.

## Phases

Seven phases, each its own implementation plan. Backend first, frontend second.

That grouping is deliberate. Building screens against a growing API means the
OpenAPI schema changes under code already written — types regenerate, response
shapes shift, and frontend work gets redone for reasons that have nothing to do
with the frontend. Fixing the contract once, before any screen exists, removes
that entirely.

It is normally the wrong trade, because you usually need a screen in front of
you to learn what its endpoint should return. It works here because the handoff
specifies every field on every screen in high fidelity, so the response models
can be derived from the mockups rather than discovered by building against
them.

The cost is that nothing is visible until phase 5. Phases 1–4 are verified by
tests and by `curl`.

**1 — Storage.** `Topic.trend_status`; the `settings` table and its
`pydantic-settings` source; schema version 3 and the new tables,
absorbing `runs` and `topics`; `store.write_checkpoint`/`read_checkpoint`
replacing `pipeline._write`/`_read`; `RunConfig`, `StageRecord` and
`RenderRecord`; renders written to `output/<run-id>/renders/` with thumbnails;
the flattening into `run_topics`; deleting `cli.py`, `tests/test_cli.py` and
`pyproject.toml`'s `[project.scripts]` entry;
`scripts/validate_templates.py` and `scripts/run_pipeline.py`; the README's
usage sections. No HTTP. Ends with `scripts/run_pipeline.py` persisting a
complete run entirely through the store, and `data/zeitgeist.db` and `output/`
cleared of everything that came before.

**2 — Read API.** The FastAPI app, every read endpoint including
`GET /api/renders/{id}` and `GET /api/settings`, image serving, and
`zeitgeist` restored as a console entry point that starts the server.

TypeScript type generation moves to phase 5, with the Vite scaffold. Phase 2
exposes FastAPI's OpenAPI schema and documents the command to generate from
it, but the checked-in `.ts` lands where a toolchain exists to lint and
typecheck it — before that there is no `package.json` to run
`openapi-typescript` from and no gate command covering the result. The
contract is still fixed by the end of phase 4, which is what the
backend-first ordering was for.

`GET /api/runs/{id}/log` is built here even though `log_lines` stays empty
until phase 3 adds log capture: the endpoint and its `verbose` filter are
part of the contract phase 5 builds against, and phase 3 then adds only the
writer. Its tests seed the table directly.
Ends with a run produced by the harness served correctly over HTTP.

**3 — Execution backend.** `RunObserver` and `CancelToken`; the DEBUG log
statements; log capture into `log_lines` and the ring buffer; the queue and
worker thread; run lifecycle and startup reconciliation; `POST /api/runs`,
resume, stop, abort; the SSE endpoint; `config/options` and the model registry;
`PUT /api/settings`. Ends with a run startable, watchable and stoppable over
HTTP, with no UI.

**4 — Generation backend.** The on-demand executor; briefing a topic that was
never ranked, which is what the below-the-cut `generate ↗` needs; the
model-written and hand-written render paths; `POST .../renders` and
`DELETE /api/renders/{id}`. Ends with the API contract complete — the last
point at which a response model changes before a screen consumes it.

**5 — Design system and read-only screens.** Vite scaffold, `tokens.css`, the
shared primitives, the TypeScript types generated from the now-complete
OpenAPI schema, the typed client, router, layout and sidebar; then the
merged Topics screen, Runs list, Run detail (completed and failed) and Topic
detail; the full-size meme view; the empty states and the filter-matched-nothing
line; the partial-failure and source-outage presentations. Ends with any run the
harness has produced browsable end to end, including one that failed and one
that half-succeeded.

Every screen was built and reviewed against MSW fixtures, then walked once
more against a real run — live Bluesky trends distilled by a local Ollama
model, browsed in an actual browser rather than a test environment. That
walk is what found the three defects fixtures structurally could not catch:
`RenderDetailPage`'s missing `onError` fallback, `MemeTile`'s image
collapsing to a zero-size box while unloaded, and the unpluralised "1
memes" on the landing screen. Each is fixed with a test that would have
caught it.

**6 — Run control screens.** The New run screen and its four config cards; the
two in-flight run-detail states; the live log with its follow behaviour and
jump-to-latest; the inline abort confirmation; the sidebar in-flight card and
the run strip; the settings screen and its third nav item. Ends with a run
startable, watchable and abortable from the browser.

Walked, as phase 5 was, against real runs — live Bluesky trends distilled by
a local Ollama model, started, watched, stopped, aborted, queued behind one
another and resumed from an actual browser. The walk found five defects the
fixtures structurally could not catch, each now fixed with a test that fails
without the fix:

- **The API's one SQLite connection raced itself.** A live run's page asks
  for the run's detail and its ranking in the same instant, once a second,
  and both handlers call `get_run` on the `Store` the app shares across
  FastAPI's thread pool. `sqlite3.threadsafety == 3` protects SQLite's own
  state, not the `sqlite3` module's statement cache or its one transaction
  per connection, so the page intermittently read "No such run." for a run
  that existed and the server logged 500s carrying `InterfaceError`. Phase 5
  made a few concurrent requests per page load; phase 6's tick-driven
  refresh makes three a second for a run's whole duration. MSW answers each
  request alone, so no fixture could race. Every public `Store` method now
  holds a per-store lock.
- **Resuming a run failed on its own log.** A resume reuses the run's id,
  and the resumed attempt numbered its log lines from 1 again, colliding
  with the first attempt's on `(run_id, seq)`. The run was recorded as
  failed in generate after generate had rendered every meme. The numbering
  now continues from the run's last recorded line.
- **New run's defaults were frozen at startup.** `GET /api/config/options`
  read `app.state.settings`, so with `bluesky_trend_limit` lowered to 4 on
  the settings screen, New run still said "of 25 trends analysed" for a run
  that analysed 4 — the bug `GET /api/settings` had already been fixed for,
  one endpoint over. It now resolves settings the way the next run will, and
  saving settings invalidates the options the client holds.
- **A finished run offered "New run" where the handoff draws "Re-run
  config".** Two accent pills side by side, one indistinguishable from the
  header button that starts from settings. It is now the ghost **Re-run
  config** pill the handoff specifies.
- **Escape, or either answer, on the inline abort confirm dropped keyboard
  focus** to the top of the document, because the focused button unmounts.
  Focus now returns to the trigger.

Two things the design asks for are not built in this phase, deliberately.
"Decisions" below means that section of the phase 6 plan,
`docs/superpowers/plans/2026-09-10-web-ui-run-control-screens.md`.

- **Ranking rows appending mid-analyse.** Persisting a row needs a
  `run_topics` row, and `TopicRow` requires a trend score, final score and
  rank that do not exist until every topic is distilled and scored. A
  mid-analyse row is a different, rank-less shape — a new response model and
  a second endpoint, which is a contract change with its own storage
  questions rather than screen work. The ranking section says the final
  order is set in evaluate, and the live log carries per-topic progress
  instead. "Decisions", 2.
- **`~4m left`.** An estimate needs a rate, and the only one available —
  elapsed over items done — is meaningless for the first item and wrong
  whenever the remaining work is unlike the work already done. A running
  card's artifact line shows the checkpoint name alone. "Decisions", 1.

Two are flagged back to the designer:

- **Model annotations** (`default` / `slower` / `cheap`). Nothing records
  them — the registry holds bare ids, and Ollama's list is whatever is pulled
  on this machine — so model rows show the id alone rather than an editorial
  claim nothing verifies. They need a real source, or removing from the
  design. "Decisions", 3.
- **The fourth settings source chip, `FROM ENV`.** The design drew three
  because it did not know the environment outranks the settings table. It
  is a real answer, and the one state where Save cannot change what the next
  run uses, so the screen draws four and gives `FROM ENV` the stronger fill.
  "Decisions", 5.

**7 — Generation screens.** The two generation panels on topic detail, the
rendered grid with its three tile states, the inline delete confirm, the
below-the-cut `generate ↗` link, and the nothing-rendered-yet state. Ends with
the design built.

### Landing the work

One branch and one pull request per phase, each off main, merged before the
next begins. A single branch carrying all seven would produce a pull request
spanning a storage rewrite, a REST API and a React application, with no green
checkpoint anywhere inside it. The usual argument against small PRs — rebase
churn from a moving main — does not apply, because nothing else moves main.

Every phase must land green under the Definition of Done as it stands at that
point, which is the four Python commands until phase 5 and seven after.

The spec itself merges first, on its own, so that every phase branch starts
from a main that already contains it.

Dependencies run in order, with two exceptions worth knowing. Phase 5's design
system — `tokens.css` and the primitives (`Chip`, `StatusPill`, `StageBar`,
`SectionLabel`, `MemeTile`) — depends on nothing but the handoff's token table
and could be built at any point, including first or in a parallel session. And
phase 4 depends on phase 3 only for the executor; its render paths could be
written earlier if that proved convenient.

## Deferred

Everything else the handoff flags as undesigned is now in scope and specified
in "Screens the handoff did not design". Two things are not:

- **Mobile layouts.** Not a missing screen but a second layout for every screen
  in the app, and the sidebar, the 4-up grids, the ranking grid and the
  two-column generation panels each need rethinking rather than reflowing. The
  handoff's own turn-1 mobile exploration was rejected, and it asks that mobile
  be treated as undesigned rather than inferred from the desktop layouts.
- **Music output.** The topic-detail grid has a dashed "Track — not built yet"
  tile marking where a second output type would live. There is no pipeline
  behind it, so there is nothing to build against.

Also out of scope, and worth naming so it is a decision rather than an
oversight: cancellation inside the Bluesky fetch, fuzzy cross-run topic
matching, and a global lock serialising the pipeline against on-demand
generation on local Ollama.
