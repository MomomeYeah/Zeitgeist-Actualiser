# Zeitgeist Actualiser

Scrapes social platforms, works out what is trending, and generates memes about it.

## Setup

Install [uv](https://docs.astral.sh/uv/), then:

```bash
uv sync
```

That creates `.venv/`, installs the exact versions in `uv.lock`, and fetches
the Python version named in `.python-version` if you do not have it. Then copy
the config template:

```bash
copy .env.example .env
```

Fill in `.env`. The only value you must supply is `ANTHROPIC_API_KEY` (or
switch to Ollama, below). `SOURCES` picks the platforms to scrape.

### Sources

`SOURCES=bluesky` is the default and needs no credentials — the AT Protocol
AppView answers these endpoints unauthenticated. `SOURCES` must currently
name exactly one platform: `lemmy` and `wikipedia` are dormant (kept in the
codebase, but rejected at startup) until a consolidation phase exists that
can build dossiers from a flat item list rather than from Bluesky's own
trend clusters.

`LEMMY_INSTANCE` chooses the Lemmy instance to query; because instances
federate, one already returns posts from across the network.
`LEMMY_INCLUDE_NSFW` maps to the API's own `show_nsfw` flag and is off by
default.

`wikipedia` adds Wikimedia pageviews — the top 1000 most-viewed articles for
the most recent day with data. It needs no credentials. Unlike Lemmy it
measures *attention* rather than conversation: articles carry no comments and
no body text, so a topic Wikipedia alone found is dropped rather than
ranked. Its role is corroboration — a topic trending on Lemmy *and*
spiking on Wikipedia outranks one trending on Lemmy alone.

`WIKIPEDIA_CONTACT` is interpolated into the User-Agent. Wikimedia's API
policy asks for contact information and may rate-limit or block generic
agents, so set it to your own repository or contact URL if you fork this.

`bluesky` adds Bluesky posts and needs no credentials — the AT Protocol
AppView answers these endpoints unauthenticated. Ingest fetches Bluesky's own
trends, then each trend's posts, then the reply threads under those posts,
concurrently. Bluesky maintains a live feed for every trend, so the ranking
within a topic is the platform's own rather than ours.

Unlike Lemmy its audience is general rather than technical, which is the
reason it is here. Two caveats worth knowing: trending skews heavily toward
US politics; and trend discovery uses an endpoint in Bluesky's `unspecced`
namespace, which is explicitly not a stable API. Reading the posts and
threads themselves uses stable endpoints.

`BLUESKY_API_BASE` exists to point at a mirror and should not normally be
changed. Note that `public.api.bsky.app` is not a valid substitute — it
returns 403 on parts of the API.

The fan-out budget is explicit rather than a single number, because "how
many trends" and "how many posts per trend" cannot be expressed by one
`limit`: `BLUESKY_TREND_LIMIT` (default 25, the `getTrends` ceiling, not a
preference) bounds how many trends are fetched, `BLUESKY_POSTS_PER_TREND`
(default 10) bounds how many posts per trend, and
`BLUESKY_FETCH_CONCURRENCY` (default 8) bounds how many of those requests
run at once.

Each platform scores its own contribution to a topic, normalised within that
platform, before results across platforms are combined. `SOURCES` currently
allows only one platform at a time (above) — `Settings` rejects anything
else at startup — so that combination step has only one input today. The
split still buys something with a single platform live: each scorer's
sub-scores are normalised within that platform alone, rather than lumped
into one cross-platform ranking, and `score_components` records what each
platform contributed. See
`docs/superpowers/specs/2026-08-26-trend-native-zeitgeist-capture-design.md`,
section "Dormant platforms", for the contract `lemmy` and `wikipedia` must
meet to rejoin — in short, producing a `Dossier` per cluster rather than a
label and a summary.

## Running

```bash
uv run python scripts/run_pipeline.py
```

The pipeline runs four stages, each checkpointed before the next begins:

1. **Ingest** — fetches Bluesky's own trends, then each trend's posts, then
   the reply threads under those posts, concurrently.
2. **Analyse** — mines recurring phrases deterministically (a phrase counts
   once `PHRASE_MIN_AUTHORS` distinct accounts have used it), then makes one
   LLM call per trend producing a dossier: what happened, what people are
   saying, how the event feels, and what posture the conversation is taking.
3. **Evaluate** — ranks topics on trend score alone and keeps the top
   `TOPIC_COUNT`.
4. **Generate** — writes captions and renders one PNG per selected topic.

Stage checkpoints are written to SQLite at `data/zeitgeist.db`; rendered
memes land in `output/<run-id>/renders/`, one PNG and one 96px thumbnail
per meme. Read a checkpoint back with:

```bash
sqlite3 data/zeitgeist.db "select payload from checkpoints where run_id='...' and stage='analyse'" | jq
```

Resuming a run from a later stage — the loop for tuning meme templates and
the caption prompt without re-scraping or re-paying for distillation — is
not available from this harness; it arrives with the API in phase 3.

Check the template library after editing a manifest:

```bash
uv run python scripts/validate_templates.py
```

## Running a local model

Install Ollama, and run a model locally:

```
ollama run qwen3.5
```

To view model details, run:

```
$ ollama show qwen3.5
  Model
    architecture        qwen35    
    parameters          9.7B      
    context length      262144    
    embedding length    4096      
    quantization        Q4_K_M    
    requires            0.17.1    

  Capabilities
    completion    
    vision        
    tools         
    thinking      

  Parameters
    presence_penalty    1.5     
    temperature         1       
    top_k               20      
    top_p               0.95    

  License
    Apache License               
    Version 2.0, January 2004    
    ...
```

## Using a local model

Install Ollama, pull a model, then set in `.env`:

```
LLM_PROVIDER=ollama
LLM_MODEL=qwen2.5:14b
```

Nothing else changes. Comparing the two backends on identical input is the
point of the provider abstraction.

The analyse stage's per-trend distillation call is tunable independently of
the provider:

- `DISTIL_CHAR_BUDGET` (default 24000) is the reply characters sent per
  call. A single trend can yield hundreds of replies; a small-context local
  model truncates silently well before that, so lower this for one and raise
  it for a hosted provider with a larger window.
- `DISTIL_CONCURRENCY` (default 4) is how many distillation calls run in
  parallel. Local Ollama serialises on one GPU, so 1-2 is right there; a
  hosted provider benefits from the default.

## The web UI

The pipeline is driven through a web UI rather than a CLI; see
`docs/superpowers/specs/2026-09-02-web-ui-design.md` for its design. This
phase ships the read-only API behind it:

```bash
uv run zeitgeist
```

That serves on `127.0.0.1:8000` by default. `--host` and `--port` change
where it binds; `--reload` restarts the server on file changes and is off
by default, deliberately — uvicorn's reloader kills a run in flight, and
phase 3 adds runs that can be in flight.

The API documents itself: `http://127.0.0.1:8000/docs` for the interactive
schema, `http://127.0.0.1:8000/openapi.json` for the raw one.

Phase 2 served reads only. Phase 3 adds starting, watching and stopping a
run over HTTP:

- **Runs are now startable over HTTP.** `POST /api/runs` queues one.
  `scripts/run_pipeline.py`, above, still works and is still the harness for
  a scripted run — the endpoint is an alternative way in, not a replacement.
- **One run at a time.** A second `POST` queues behind the first; the
  response's `position` says how far back (`0` means executing now).
  `GET /api/runs/active` reports the executing run and the queue behind it.
  The queue is in-memory, so a restart loses what was queued — deliberately,
  rather than persisting a job table for a single-user tool.
- **Stop versus abort.** `POST /api/runs/{id}/stop` finishes the current
  stage, writes its checkpoint, then ends — the run stays resumable.
  `POST /api/runs/{id}/abort` ends now. Both land on the same status,
  `aborted`; there is no separate "stopped" status, because they differ in
  what was preserved, not in the label. Aborting during ingest takes effect
  when the fetch returns, because `fetch_evidence` is one opaque
  `asyncio.run()` with no interior checkpoint to interrupt.
- **Resume, and the tuning loop.** `POST /api/runs/{id}/resume` reuses the
  run's checkpoints, defaulting to the computed resume stage. Its optional
  `template_ids` narrows the template library for that resume, which is
  what replaces the old `--resume-from generate --templates drake` loop.
- **A run interrupted by a restart** is marked `interrupted` on the next
  startup and resumes like any other run. This is why `--reload` stays off
  by default: uvicorn's reloader kills a run in flight.
- **The live log.** `GET /api/runs/{id}/events` streams `log` and `tick`
  events over SSE while a run executes; `GET /api/runs/{id}/log?verbose=`
  serves the history afterwards. The server always captures at DEBUG and
  `verbose` only filters what is returned, so flipping it works
  retroactively on lines already recorded.
- **Settings.** `GET /api/config/options` reports the providers and their
  models, which platforms are enabled, the template library and its slots,
  the `.env` defaults, and whether an API key is set — never the key itself.
  `PUT /api/settings` writes the seven tunables; an empty value clears the
  row so `.env` applies again. Changes apply to new runs — a run already in
  flight keeps the config it froze when it started.

Phase 4 completes the API. Memes can now be generated for a topic on
demand, long after its run ended:

- **Two ways to make a meme.** `POST /api/runs/{id}/topics/{topic_id}/renders`
  takes either `{"mode": "llm", "template_id": ..., "count": N}` — the model
  writes the captions for the template you name, up to four at a time — or
  `{"mode": "manual", "template_id": ..., "caption_slots": {...}}`, which
  draws captions you wrote yourself. It answers 202 with the render rows
  already created and `status: "generating"`; poll the topic to watch them
  finish.
- **Any topic, not just the ranked ones.** A topic the evaluate stage left
  below the cut can still be generated for: the request reads the run's
  `analyse` checkpoint, which holds every topic.
- **Generation runs off the run worker.** A second, single-threaded
  executor, so a meme can be generated while a run is in flight. On
  Anthropic that is free; against a local Ollama the two contend for one
  GPU and simply take longer.
- **Deleting a render.** `DELETE /api/renders/{id}` removes the row, the
  PNG and the thumbnail. Meme counts are a `COUNT(*)` at query time, so
  they follow immediately.
- **Re-running `generate` now replaces rather than appends.** A resume from
  the generate stage clears each topic's previous *model-written* renders
  once the new one is on disk, which is what the old CLI's fixed filenames
  used to do. Renders you wrote by hand are never touched — the model's
  output is reproducible by running again, and yours is not.
- **A re-render that fails clears nothing.** If your edited prompt produces
  a caption too long for its box, the previous render stays where it is and
  the failure appears beside it, so you can see both. On-demand generation
  is the other exception and always appends, because it is something you
  asked for on top of what is already there.

Starting a run and watching it, from the shell:

```bash
RUN=$(curl -s -XPOST localhost:8000/api/runs -H 'content-type: application/json' -d '{}' | jq -r .run_id)
curl -sN "localhost:8000/api/runs/$RUN/events"
```

The API contract is complete as of this phase.

Phase 5 adds the browser half. Development is two processes:

```bash
uv run zeitgeist
```

```bash
npm --prefix web run dev
```

Vite serves the SPA and proxies `/api` to uvicorn on 8000, so the app is
same-origin in development and there is no CORS anywhere in the project.
Open the URL Vite prints.

Five screens, all read-only in this phase: Topics (`/`), Runs (`/runs`), run
detail (`/runs/<id>`), topic detail (`/topics/<run>/<topic>`) and the
full-size meme view (`/runs/<run>/renders/<id>`). Starting a run, the live
log and the settings screen are phase 6; generating a meme from the browser
is phase 7. Until then a run is started with `scripts/run_pipeline.py` or
`POST /api/runs`, and the UI shows what it produced.

The client's TypeScript types are generated from the API's own OpenAPI
schema and checked in. After changing any response model, regenerate both:

```bash
uv run python scripts/dump_openapi.py
```

```bash
npm --prefix web run generate:types
```

`uv run pytest` fails if `web/openapi.json` no longer matches the app, and
`npm --prefix web run typecheck` fails if `web/src/api/schema.ts` no longer
matches `web/openapi.json`. Between them there is no way to change the
contract on one side and not the other without the gate saying so.

## Tests

```bash
uv run pytest
```

```bash
npm --prefix web test
```

No test touches the network. Every LLM call goes through `FakeLLMProvider`,
and the frontend's requests are intercepted by MSW with handlers typed from
the generated OpenAPI types — so a backend contract change breaks frontend
tests rather than surfacing in the browser.
