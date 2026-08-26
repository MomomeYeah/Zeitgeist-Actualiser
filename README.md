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
run at once. `POST_LIMIT` does not apply here — it only bounds the dormant
`lemmy`/`wikipedia` path, below.

Each platform scores its own contribution to a topic, normalised within that
platform, before results across platforms are combined. `SOURCES` currently
allows only one platform at a time (above), so that combination step has
only one input today; it is what lets a second live trend source join
without changes elsewhere. See
`docs/superpowers/specs/2026-08-26-trend-native-zeitgeist-capture-design.md`,
section "Dormant platforms", for the contract `lemmy` and `wikipedia` must
meet to rejoin — in short, producing a `Dossier` per cluster rather than a
label and a summary.

## Running

```bash
uv run zeitgeist run
```

The pipeline runs four stages, each checkpointed to JSON before the next
begins:

1. **Ingest** — fetches Bluesky's own trends, then each trend's posts, then
   the reply threads under those posts, concurrently. Writes `evidence.json`.
2. **Analyse** — mines recurring phrases deterministically (a phrase counts
   once `PHRASE_MIN_AUTHORS` distinct accounts have used it), then makes one
   LLM call per trend producing a dossier: what happened, what people are
   saying, how the event feels, and what posture the conversation is taking.
   Writes `topics.json`.
3. **Evaluate** — ranks topics on trend score alone and keeps the top
   `TOPIC_COUNT`. Writes `ranked.json`.
4. **Generate** — writes captions and renders one PNG per selected topic.

Output lands in `output/<run-id>/`: the four stage checkpoints as JSON, plus
one PNG per selected topic.

Re-run only the meme generation against an existing run — this re-runs stage
4 against the frozen `ranked.json` from that run. Ingest and analysis are
skipped entirely, so there is no re-scraping and no re-paying for
distillation; caption writing itself still calls the model once per
selected topic, so this is not free with a hosted provider, just far
cheaper than a full run. It is the loop for tuning meme templates and the
caption prompt:

```bash
uv run zeitgeist run --run-id 20260816T120000Z --resume-from generate
```

Check the template library after editing a manifest:

```bash
uv run zeitgeist validate-templates
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

## Tests

```bash
uv run pytest
```

No test touches the network. Every LLM call goes through `FakeLLMProvider`.
