# Zeitgeist Actualiser — Pipeline Design

**Date:** 2026-08-16
**Status:** Approved

## Purpose

Scrape social media, identify what is currently trending, and automatically
generate media based on those topics.

The project's goal is hands-on experience building agentic systems: LLM
pipeline design, structured outputs, multi-stage chaining, and comparing model
backends on identical tasks. Design decisions favour learning value and
inspectability over raw throughput.

## Scope

This spec covers a **one-off CLI run**:

```
python -m zeitgeist run
```

It scrapes Reddit, identifies trending topics, ranks them by sentiment, and
writes image memes to `output/<run-id>/`.

### Out of scope

Deferred to later specs. None require changing the interfaces defined here.

- Web application and scheduled runs
- Songs, video, or any non-image media
- Platforms beyond Reddit (TikTok, Twitter, Instagram, Google Trends)
- Generative imagery (Flux / SDXL)
- Embedding-based clustering

## Architecture

Four stages in a linear pipeline. Each takes a typed input, returns a typed
output, and checkpoints that output as JSON into the run directory.

```
Sources ──▶ [A ingest] ──▶ posts.json
                              │
                              ▼
                        [B analyse] ──▶ topics.json    (LLM map-reduce + pure scoring)
                              │
                              ▼
                        [C evaluate] ──▶ ranked.json   (LLM sentiment + selection)
                              │
                              ▼
                        [D generate] ──▶ briefs.json + *.png
```

Checkpointing is deliberate. Stage D can be re-run repeatedly against a frozen
`ranked.json` while tuning caption prompts, without re-scraping or re-paying for
stages B and C. It also means a crash leaves partial artifacts to inspect.

## Data model

Pydantic models in `models.py`, doubling as the LLM structured-output schemas.

### Post

| Field | Type | Notes |
|---|---|---|
| `platform` | `str` | e.g. `"reddit"` |
| `source_id` | `str` | Platform-native ID, used for dedup |
| `title` | `str` | |
| `body_excerpt` | `str \| None` | Truncated to 500 chars |
| `permalink` | `str` | |
| `score` | `int` | Upvotes or platform equivalent |
| `comment_count` | `int` | |
| `created_at` | `datetime` | UTC |
| `fetched_at` | `datetime` | UTC |
| `channel` | `str` | Subreddit or platform equivalent |

`Post` has no author field. Usernames are not needed by any downstream stage,
and not collecting them keeps the project clear of storing personal data about
real people.

### Topic

| Field | Type | Notes |
|---|---|---|
| `id` | `str` | Slug derived from label; a numeric suffix is appended on collision within a run |
| `label` | `str` | Short canonical name |
| `summary` | `str` | One or two sentences |
| `post_ids` | `list[str]` | Contributing `Post.source_id` values |
| `trend_score` | `float` | Composite, 0–1 |
| `score_components` | `dict[str, float]` | Individual normalised terms |

### ScoredTopic

Extends `Topic` with:

| Field | Type | Notes |
|---|---|---|
| `primary_sentiment` | `Sentiment` | Fixed enum |
| `secondary_sentiments` | `list[Sentiment]` | Zero or more |
| `valence` | `float` | −1 to 1 |
| `meme_potential` | `float` | 0 to 1 |
| `final_rank` | `int` | Assigned after weighting |

### MediaBrief

| Field | Type | Notes |
|---|---|---|
| `topic_id` | `str` | |
| `template_id` | `str` | Must match a known template |
| `caption_slots` | `dict[str, str]` | Keyed by the template's slot names |
| `rationale` | `str` | Why this template fits this topic |

## Persistence

SQLite at `data/zeitgeist.db`, two tables.

- `runs` — `run_id`, `started_at`, `finished_at`, `status`, `post_count`
- `topics` — `run_id`, `label`, `trend_score`, `created_at`

This is the minimum needed for cross-run rise and fall. Stage B queries
`topics` for prior appearances of a label. On the first run it finds nothing
and the delta component contributes zero.

## Stage A — Ingestion

### Source interface

```python
class Source(Protocol):
    name: str
    def fetch(self, limit: int) -> list[Post]: ...
```

This is the whole extension point. Adding a platform means adding a file in
`sources/` that implements `fetch` and normalises into `Post`.

### RedditSource

Uses PRAW in read-only mode — client ID and secret only, no user login
required.

Pulls from:

- `r/all` **hot** — what is currently large
- `r/all` **rising** — Reddit's own early-signal feed, so the scorer sees things
  that have not already peaked
- A configurable list of specific subreddits

Deduped by `source_id`. Default total limit: 500 posts.

### Failure behaviour

Stage A failing is **fatal**. With no posts there is nothing to analyse, so the
run aborts with a clear error.

## Stage B — Trend analysis

Two LLM passes plus one pure function.

### Map (`analysis/extract.py`)

Batches of ~40 posts go to the LLM, which returns 1–3 topic tags per post.
Batches are independent, so they run concurrently and a failed batch is skipped
with a warning rather than failing the run.

### Reduce (`analysis/consolidate.py`)

The accumulated tag vocabulary — a few hundred strings, **not** the posts — goes
to the LLM, which merges synonyms and near-duplicates into canonical topics
with a label and summary, and reports which tags folded into which topic.

Passing only the vocabulary rather than the posts is what keeps this pass small
enough to run on a local model with a limited context window.

### Score (`analysis/score.py`)

Pure Python, no LLM. This is deliberate: a numeric judgment made by an LLM is
neither reproducible nor testable, whereas this function is both.

`trend_score` is a weighted composite of four normalised components:

| Component | Definition |
|---|---|
| `upvote_velocity` | `score ÷ hours_since_post`, averaged across the topic's posts |
| `comment_velocity` | `comment_count ÷ hours_since_post`, averaged |
| `channel_spread` | Count of distinct channels carrying the topic |
| `rank_delta` | Improvement in trend score vs. the **most recent prior run** containing this label; zero if the label has never appeared |

Each component is min-max normalised across the run's topics before weighting.
Where every topic shares the same value for a component, its normalised value is
zero for all of them rather than undefined.

Weights are configurable. `score_components` is stored alongside the total so
that a surprising result can be traced to the term that caused it.

## Stage C — Sentiment and selection

One LLM call per topic, run concurrently.

### Sentiment enum

Fixed, not free text, so results are comparable across runs:

```
cute, heartwarming, funny, awe, schadenfreude,
outrage, sad, scary, gross, cringe, mundane
```

Each call returns a primary sentiment, zero or more secondary sentiments, a
valence float from −1 to 1, and a `meme_potential` score from 0 to 1.

### Selection

Final ranking is `trend_score × sentiment_weight × meme_potential`.

Sentiment weights favour positive labels but do not exclude any of them. A
sufficiently strong trend score can carry a negatively-flavoured topic into the
final selection, which is the intended behaviour — the zeitgeist is not always
cheerful, and a tool that only ever sees the cheerful half is not measuring it.

Default weights, applied to the **primary** sentiment and configurable via
`SENTIMENT_WEIGHTS`:

| Sentiment | Weight |
|---|---|
| `heartwarming` | 1.30 |
| `cute` | 1.25 |
| `funny` | 1.25 |
| `awe` | 1.20 |
| `schadenfreude` | 1.00 |
| `cringe` | 0.90 |
| `mundane` | 0.70 |
| `gross` | 0.70 |
| `sad` | 0.60 |
| `scary` | 0.60 |
| `outrage` | 0.60 |

The spread is deliberately moderate. At these values a negative topic needs
roughly double the combined trend and meme-potential score of a positive one to
outrank it — a real thumb on the scale, but not a veto.

The top N topics (default 5) proceed to stage D.

### Failure behaviour

A topic whose sentiment call fails twice is dropped with a warning. The run
continues with the remaining topics.

## Stage D — Media generation

### Templates

`media/templates/` holds **24** classic meme template images, each with a JSON
manifest describing its rhetorical shape and text box geometry:

```json
{
  "id": "drake",
  "image": "drake.png",
  "shape": "rejecting option A in favour of preferred option B",
  "slots": [
    {"name": "rejected",  "box": [340, 20, 640, 300], "max_chars": 60},
    {"name": "preferred", "box": [340, 320, 640, 600], "max_chars": 60}
  ]
}
```

`box` is `[left, top, right, bottom]` in pixels, measured against that specific
image file.

The library should span a range of **rhetorical shapes**, not just a range of
pictures — comparison, escalation, contrast, reveal, overconfidence,
understatement, labelled-parts, and so on. Selection quality depends on the
model finding a shape that genuinely fits the topic, so twenty-four templates
covering eight shapes is worth more than twenty-four variations on comparison.

Manifests are hand-authored: each one needs its boxes measured against its own
image. Building the library is therefore a distinct chunk of implementation
work, and the plan should treat it as such rather than folding it into the
renderer step. A `validate-templates` CLI subcommand checks that every manifest
parses, references an existing image, and has boxes falling inside that image's
bounds — cheap to build and the fastest way to catch a mis-measured box.

### Brief generation (`media/brief.py`)

The LLM receives the topic (label, summary, sentiment) plus every manifest's
`id`, `shape`, and slot names, and returns a `MediaBrief`. Twenty-four
manifests is on the order of 2,000 tokens, so this stays a single call even on
a local model with a modest context window.

Because the model can only select from supplied `id`s and fill named slots, the
output is fully validatable: a hallucinated template ID or a missing slot fails
Pydantic validation rather than reaching the renderer. Validation failure
triggers one retry with the error appended, then the topic is skipped.

The `rationale` field is retained deliberately — reading why the model chose a
given template is the primary tool for debugging poor captions.

### Rendering (`media/render.py`)

No LLM involvement, fully deterministic:

1. Load the template image
2. For each slot, word-wrap the caption and auto-shrink the font until it fits
   the box
3. Draw with a stroke outline for legibility on any background
4. Save as PNG into `output/<run-id>/`

## LLM provider abstraction

One narrow interface, because every stage needs the same thing — a validated
structured object.

```python
class LLMProvider(Protocol):
    name: str
    def complete(
        self,
        prompt: str,
        schema: type[BaseModel],
        *,
        system: str | None = None,
    ) -> BaseModel: ...
```

| Implementation | Mechanism |
|---|---|
| `AnthropicProvider` | Tool use, with the Pydantic schema as the tool's input schema — the most reliable structured-output path the API offers |
| `OllamaProvider` | Ollama's JSON-schema `format` parameter |

Both validate through Pydantic. On `ValidationError` they retry once with the
error text appended to the prompt, then raise.

Keeping the interface to a single method is what makes the local-versus-cloud
comparison honest: swapping backends changes one config value and nothing else,
so any observed quality difference is genuinely attributable to the model.

The Anthropic provider is the default. Ollama is implemented in this spec so the
comparison is available from the start.

## Configuration

`pydantic-settings` reading `.env`. `.env.example` is committed; `.env` is
gitignored.

| Key | Purpose |
|---|---|
| `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, `REDDIT_USER_AGENT` | PRAW read-only auth |
| `ANTHROPIC_API_KEY` | Anthropic provider |
| `LLM_PROVIDER` | `anthropic` or `ollama` |
| `LLM_MODEL` | Model identifier for the chosen provider |
| `OLLAMA_HOST` | Defaults to `http://localhost:11434` |
| `SUBREDDITS` | Comma-separated extra subreddits |
| `POST_LIMIT` | Default 500 |
| `TOPIC_COUNT` | Topics to generate media for; default 5 |
| `SENTIMENT_WEIGHTS` | JSON map of sentiment to multiplier |

## Error handling

Stage A is fatal on failure. Every stage after it degrades rather than dies:

- A failed map batch is logged and skipped
- A topic whose sentiment call fails is dropped
- A brief that fails validation twice is skipped

A run that produces three memes instead of five is a success. Every stage
writes its checkpoint before the next begins.

## Testing

pytest. No network access anywhere in the suite.

| Target | Approach |
|---|---|
| `FakeLLMProvider` | Returns queued canned responses and records received prompts. Every LLM-touching stage is tested against it. |
| Ingestion and analysis | A committed JSON fixture of ~50 real Reddit posts |
| `score.py` | Direct unit tests — known inputs, asserted outputs, including the first-run case where history is empty |
| `render.py` | Golden-image tests: render a fixture brief, compare against a committed PNG |
| End to end | One test wiring fake provider + fixture posts + a real template, asserting a PNG lands on disk |

`FakeLLMProvider` is what makes the pipeline testable at all, and is therefore
built before the stages that depend on it.

## Project layout

```
zeitgeist/
  __init__.py
  cli.py                 # argument parsing, run orchestration
  config.py              # pydantic-settings
  models.py              # Post, Topic, ScoredTopic, MediaBrief, Sentiment
  store.py               # SQLite persistence
  sources/
    base.py              # Source protocol
    reddit.py            # RedditSource
  llm/
    base.py              # LLMProvider protocol
    anthropic.py
    ollama.py
  analysis/
    extract.py           # map stage
    consolidate.py       # reduce stage
    score.py             # trend scoring, pure
    sentiment.py         # stage C
  media/
    brief.py             # topic -> template choice + captions
    render.py            # Pillow compositing
    templates/           # images + JSON manifests
tests/
docs/superpowers/specs/
output/                  # gitignored
data/                    # gitignored
```

Each module has one job. The directory that will grow fastest — `sources/` —
grows by gaining files rather than by any file getting larger.

## Decisions and rationale

| Decision | Rationale |
|---|---|
| Thin vertical slice A→D | Exercises every agent-shaped problem early and establishes real interface boundaries, rather than perfecting one stage in isolation |
| Pluggable provider, Anthropic default | Starting on a strong model prevents confusing pipeline bugs with model weakness; the local comparison is then a controlled experiment |
| LLM map-reduce for clustering | The archetypal agentic pattern; scales past any context limit and degrades gracefully onto a small local model |
| Velocity now, persist snapshots | Produces useful output on run one while accumulating the history that makes true rise-and-fall detection possible later, with no re-architecting |
| Template memes over generative | The interesting work is structured template-matching; output is reliably legible, and text rendering in image models is not |
| Scoring is pure Python | Reproducible and unit-testable, which an LLM's numeric judgment is not |
| Sentiment weights, no exclusions | Preference for positive output without blinding the tool to half the zeitgeist; a strong enough trend still surfaces a negative topic |
| No author field on `Post` | Not needed downstream, and avoids collecting personal data |
