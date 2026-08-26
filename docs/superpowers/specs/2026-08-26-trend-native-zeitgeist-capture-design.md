# Trend-Native Zeitgeist Capture

**Date:** 2026-08-26
**Status:** Draft

## Purpose

The memes are generic. They name the category a story sits in rather than the
story, they miss the vocabulary people are using, and they fit their templates
poorly. The instinct is to blame the caption prompt. The prompt is not the
cause.

Trace one caption backwards through the pipeline as it stands:

1. `BlueskySource` receives a **trend** from Bluesky — an already-correct,
   already-specific cluster carrying a name, a one-sentence description of the
   actual event, a category, a post count and a start time. It keeps
   `displayName` and `status` and discards the rest.
2. `extract.py` discards the cluster too, re-deriving it as topic tags of "two
   or three words at most". `Canada announces retaliatory tariffs` becomes
   `tariffs`, `canada`, `trade war`.
3. `consolidate.py` merges those tags into broader ones. Its docstring is
   explicit that only the vocabulary is sent, never the items — so
   `Topic.summary`, the field every later stage depends on, is written by a
   model that has seen roughly seven hundred disembodied words and no
   sentences. It is not a summary. It is a confabulation about a word cluster,
   and it is where "US Politics and Policy" comes from.
4. `sentiment.py` judges feeling from that label, that summary, and an item
   count.
5. `brief.py` writes the meme from a label, a confabulated summary, one enum
   member and a float.

No fact about the world survives to the caption. The model is not failing to
write a good meme about the news; it is being asked to write a meme about a
phrase, and doing that roughly as well as anyone could.

Two further gaps compound it. `reply_count` is stored as an integer and the
replies themselves are never fetched — the one place where people say what
they think is counted and never read. And sentiment is judged of the *event*
only, so a conversation whose posture contradicts its subject is invisible. On
2026-08-26 the top live trend was `Dolly Parton passes away`, which the current
pipeline would score `SAD` and suppress at weight 0.60. The replies are
tributes, gratitude and Jolene jokes. The fifth trend, `Landmarks light pink
for Dolly Parton`, is an outright celebration. The event is sad; the room is
warm. Which of those two facts should drive a meme is not a close question,
and today the pipeline cannot see the second one.

This spec changes what flows down the pipe.

## Scope

- The Bluesky trend becomes the unit of analysis. `extract` and `consolidate`
  leave the path entirely.
- `TrendInfo` preserving every field `getTrends` returns.
- A `TrendSource` protocol alongside the existing `Source`, returning evidence
  rather than a flat item list.
- Reply ingestion via `getPostThread`, with the verbatim text persisted.
- Concurrent HTTP fan-out across trends, feeds and threads.
- `analysis/slug.py`, holding the slug helpers currently in `consolidate.py`.
- `items.json` replaced by `evidence.json` as the ingest checkpoint.
- `analysis/phrases.py`: deterministic mining of recurring phrases, counted by
  distinct author.
- `analysis/distil.py`: one LLM call per trend producing a `Dossier` — what
  happened, what people are saying, the conversation's register, and the
  event's sentiment.
- `Register`, a taxonomy of conversational posture, alongside the existing
  `Sentiment` taxonomy of how an event feels.
- `Topic` gains a `dossier`; `ScoredTopic` loses its sentiment fields.
- Selection flattened: rank on `trend_score` alone.
- `brief.py` rewired to read the dossier.
- Lemmy and Wikipedia made dormant but intact.

### Out of scope

- Richer `shape` fields on the template manifests.
- Brief-prompt craft: rhetorical shapes, how to use a template well.
  `brief.py` is *wired* to the dossier here because it must be, but improving
  what it says is separate work — now with something worth writing about.
- Lemmy's consolidation phase. This spec records the contract it must satisfy;
  it does not build it.
- Any change to `Store`, whose schema works on `Topic` and is unaffected.

## Architecture

The pipeline keeps its four stages and its checkpointing. What changes is the
currency flowing between them.

```
Stage A  INGEST     Bluesky -> evidence.json        HTTP, concurrent, ~1 min
Stage B  ANALYSE    evidence -> topics.json         LLM, 1 call/trend, slow
Stage C  EVALUATE   rank and select -> ranked.json  pure Python, instant
Stage D  GENERATE   briefs, render PNGs             LLM, cheap, re-run often
```

Today's flow loses information at every arrow. This one adds at every arrow: a
trend gains its posts, its posts gain their replies, and the whole gains a
distilled understanding of what was said.

### The checkpoint boundary

Everything expensive — scraping and understanding — lands on the ingest side
of `topics.json`. Template-shape and brief-prompt tuning, the next two pieces
of work, re-run from Stage D against frozen dossiers in seconds.
`run_pipeline` already supports this through `start_at`; only the contents
change.

`evidence.json` holds a verbatim corpus of public posts and replies. It is a
local working file and is not committed.

### Stage A: evidence gathering

Three levels of fan-out:

1. `getTrends?limit=25` — one call. Twenty-five is a hard ceiling; the
   endpoint returns 400 above it.
2. Per trend, `getFeed` — twenty-five concurrent calls, ten posts each.
3. Per post, `getPostThread?depth=2` — around two hundred and fifty concurrent
   calls.

Measured against the live API on 2026-08-26: a feed page returns in ~0.9s, a
depth-2 thread in ~2.7s and yielded 59 replies in a single call. Comments cost
one request per post, not one per comment, which is what makes this affordable
at all. Roughly 275 requests per run, well inside Bluesky's public limits, and
under a semaphore of 8 the whole stage lands near a minute.

#### The source interface

A trend-native source returns evidence, not a flat item list, so the existing
`Source` protocol cannot describe it. `sources/base.py` gains a second
protocol alongside the first:

```python
class TrendSource(Protocol):
    name: str

    def fetch_evidence(self, settings: Settings) -> list[TrendEvidence]: ...
```

`Source` is unchanged and continues to describe the dormant platforms.
`BlueskySource` implements `TrendSource` only; `run_pipeline` calls
`fetch_evidence`. There is no `limit` argument — the fan-out is bounded by
`bluesky_trend_limit` and `bluesky_posts_per_trend`, which is a two-dimensional
budget that a single integer cannot express. `CompositeSource` implements
`Source` and therefore goes dormant with the platforms it fans out to; nothing
composes trend sources while there is one.

`fetch_evidence` stays **synchronous**, running an `httpx.AsyncClient` and
`asyncio.gather` internally. That keeps the async boundary entirely inside the
source: no stage above it becomes a coroutine, and tests continue to drive it
synchronously with a fake client — no `pytest-asyncio`, no async test
infrastructure.

### Stage B: distillation

One LLM call per trend, fanned out across a thread pool. Two things happen
before that call, deterministically, because a model asked to do them would
invent rather than measure: phrase mining and evidence budgeting, both
specified below.

## Data model

### New models

```python
class TrendInfo(BaseModel):
    """Bluesky's own cluster, kept whole. All but two of these fields are
    discarded by the current source."""
    topic_id: str          # Bluesky's `topic` uuid, stable while the trend lives
    display_name: str      # "Canada announces retaliatory tariffs"
    description: str = ""  # the specific event, in one sentence
    category: str = ""     # culture | politics | business | entertainment | ...
    post_count: int
    started_at: datetime
    status: TrendStatus

class Reply(BaseModel):
    text: str
    like_count: int
    created_at: datetime
    author_key: str        # truncated hash of the DID

class PostEvidence(BaseModel):
    item: Item             # Item is unchanged, so dormant sources still use it
    replies: list[Reply]

class TrendEvidence(BaseModel):
    trend: TrendInfo
    posts: list[PostEvidence]
```

`description` and `category` default to empty rather than raising on absence.
`getTrends` lives under `app.bsky.unspecced`, so nothing it returns is a
contract; this follows the reasoning already written into `_normalise_status` —
degrade with a warning, do not kill the run.

`author_key` exists for exactly one purpose: counting how many distinct
accounts are behind a repeated phrase. Forty uses from three accounts is a
dogpile, not a zeitgeist, and without that count "frequently repeated" means
nothing. The handle itself has no downstream use, so a truncated hash is stored
instead of the DID.

### The register taxonomy

```python
class Register(StrEnum):
    """The posture people are taking, distinct from how the event feels."""
    TRIBUTE     = "tribute"      # earnest appreciation; mourning as celebration
    MOURNING    = "mourning"     # undiluted grief
    DELIGHT     = "delight"      # uncomplicated shared enjoyment, no side to take
    OUTRAGE     = "outrage"      # sincere anger, calls to act
    DUNKING     = "dunking"      # piling onto a target; ratio energy
    GALLOWS     = "gallows"      # joking precisely because it is grim
    RIFFING     = "riffing"      # in-jokes, wordplay, escalating bits
    AWE         = "awe"          # sincere wonder
    ALARM       = "alarm"        # fear, warning, this-is-not-normal
    DEBATE      = "debate"       # genuine disagreement
    RESIGNATION = "resignation"  # weary "of course this happened"
```

The three warm registers are easily confused, so they are defined against each
other. **DELIGHT** is a cat knocking something off a table, or an overlooked
person finally getting their due: broad, warm, nothing to argue about. **AWE**
is impressive rather than endearing. **TRIBUTE** is appreciation prompted by
loss or a milestone.

`Sentiment` is untouched and keeps its existing job — how the *event* feels.
Dolly Parton then reads `event_sentiment=SAD, valence=-0.4, register=TRIBUTE`,
and the gap between those two values is itself the signal. Grim event plus
funny register is gallows humour and yields a very particular meme. Grim event
plus earnest register means do not make a joke at all. Collapsing the two
judgements into one would erase exactly that distinction.

### The dossier

```python
class Phrase(BaseModel):
    text: str
    occurrences: int
    distinct_authors: int

class Dossier(BaseModel):
    what_happened: str                  # concrete: who, what, when
    key_entities: list[str]             # named people, orgs, places
    conversation_summary: str           # what people are actually saying
    register: Register
    secondary_registers: list[Register]
    event_sentiment: Sentiment
    valence: float                      # -1.0 to 1.0
    meme_potential: float               # 0.0 to 1.0, recorded but not applied
    recurring_phrases: list[Phrase]     # computed, not model-generated
```

`recurring_phrases` is deliberately not something the model produces. Asked for
catchphrases, a model returns plausible ones. Mined deterministically, the
field is evidence, and the counts attached to it are true.

That distinction is what resolves the tension between quoting and distilling. A
phrase one person wrote is that person's joke; a phrase fifty people converged
on independently *is* the zeitgeist, and quoting it is capturing the thing
rather than dodging the work. The brief prompt can therefore say truthfully
that these phrases came from this many distinct people, permit a quotation, and
still require that the caption do more than quote — because the summary and
register sit beside the phrase list as separate fields, and a caption that uses
only one of them is visibly incomplete.

### Changes to existing models

```python
class Topic(BaseModel):
    ...
    dossier: Dossier | None = None      # None on the dormant path

class ScoredTopic(Topic):
    final_rank: int = 0                 # sentiment fields removed
```

`ScoredTopic` loses `primary_sentiment`, `secondary_sentiments`, `valence` and
`meme_potential`. Those now live on the dossier as the single source of truth,
with no projection to drift. The removal is clean because after the selection
change below, only two call sites read them: `select`, which stops using them,
and `brief._build_prompt`, which moves to the dossier.

Consequently `judge_topics` and `SENTIMENT_SYSTEM` are deleted — that judgement
folds into the single distillation call, where it has the replies in front of
it instead of a label — `select` reduces to ranking on `trend_score`, and
`sentiment_weights` leaves `Settings`.

`Item`, `BlueskyMetrics`, the `Metrics` union, the scorer registry and both
dormant sources are untouched.

## Recurring-phrase mining

`analysis/phrases.py`, a pure function over a trend's replies. Pure Python for
the reason already recorded in `scorers/bluesky.py`: reproducible and
unit-testable, which a model's numeric judgement is not.

1. Normalise each reply — lowercase, strip URLs, mentions and punctuation.
2. Emit n-grams for n in 2..6, **deduplicated within a reply**, so one person
   repeating a phrase contributes one occurrence.
3. Count `occurrences` and `distinct_authors` per n-gram.
4. Filter out:
   - n-grams below `phrase_min_authors` distinct authors (default 3);
   - n-grams wholly contained in the trend's `display_name` or `description` —
     "dolly parton" in two hundred replies is the subject, not a catchphrase;
   - n-grams composed entirely of stopwords.
5. Collapse substrings. For any pair where one n-gram's tokens are a
   contiguous subsequence of another's, drop the shorter when
   `longer.distinct_authors >= 0.8 * shorter.distinct_authors`. Otherwise
   "imagination library" and "the imagination library" both surface and
   dilute the list. The threshold encodes the judgement directly: if almost
   everyone who said the short form said the long form, the long form is the
   phrase; if most did not, the short form is a genuinely separate and more
   widely used one, and the longer is one sub-community's variant.
6. Rank by `distinct_authors`, then by length. Keep the top fifteen.

Mining runs on replies only. Posts are frequently links or article summaries;
the replies are the conversation.

## Distillation

`analysis/distil.py`. One call per trend. The prompt carries, in order:

- trend name, description, category, post count, status;
- the top posts with their engagement;
- a budgeted sample of replies;
- the mined phrase list with its counts.

It returns every `Dossier` field except `recurring_phrases`, which is attached
afterwards.

**Evidence budgeting.** A single trend can yield six hundred replies. Local
Ollama models — the primary development target — will truncate silently well
before that. Replies are therefore selected top-liked-first up to
`distil_char_budget` characters. Sorting by likes biases toward the loudest
replies, which is the intended bias: what resonated is the question being
asked.

The prompt states what the phrase list is — text that a given number of
distinct people converged on independently — and permits quoting one, while
requiring the summary and register to stand on their own. That instruction has
teeth only because the counts behind it are measured rather than imagined.

## From evidence to topic

Stage B emits one `Topic` per successfully distilled trend. This is the point
where the new path rejoins the existing scorer and store, so the mapping is
fixed here rather than left to the implementer:

| `Topic` field      | Source                                             |
| ------------------ | -------------------------------------------------- |
| `id`               | slug of `trend.display_name`, uniquified            |
| `label`            | `trend.display_name`                                |
| `summary`          | `dossier.what_happened`                             |
| `item_ids`         | `source_id` of every post under the trend           |
| `dossier`          | the dossier                                         |
| `trend_score`      | `score_topics`, unchanged                           |
| `score_components` | `score_topics`, unchanged                           |

`summary` is now a description of a real event rather than a confabulation
over a bag of tags. That single substitution is the largest part of the fix.

`id` is a readable slug rather than Bluesky's `topic_id` uuid, because
`_render_all` builds output filenames from it and a uuid would make the run
directory unreadable. The uuid is retained on `TrendInfo` for reference and
cross-run identification. `slugify` and the uniquifying helper move from
`consolidate.py` into `analysis/slug.py` so the live path does not import from
a dormant module.

`score_topics` keeps its signature and receives the item list flattened out of
the evidence, grouped by topic through `item_ids` exactly as it is today.

### Checkpoint changes

`items.json` is replaced by `evidence.json` holding `list[TrendEvidence]`.
`run_pipeline` resumption reads the new name. `topics.json`, `ranked.json` and
`briefs.json` keep their names and their positions; only `topics.json` changes
shape, gaining the `dossier` field. Old run directories are not migrated —
they are working output, and a stale one simply fails to resume with the
existing `FileNotFoundError`.

## Concurrency

Two mechanisms, chosen deliberately rather than by inconsistency.

**HTTP fan-out uses `asyncio` and `gather`**, bounded by a semaphore
(`bluesky_fetch_concurrency`, default 8), inside a synchronous `fetch()`.
Bounded retry with backoff on HTTP 429.

**LLM fan-out uses a `ThreadPoolExecutor`** (`distil_concurrency`, default 4),
because `LLMProvider.complete` is synchronous. Converting the provider
interface to async would ripple through both providers, `brief.py` and every
provider test for no measurable gain — the calls are I/O-bound either way.
Local Ollama serialises on a single GPU regardless, so 1–2 is the right setting
there; Anthropic benefits from the default.

## Failure handling

Following the escalation rule already established in `sources/bluesky.py`:
transport failures degrade, contract violations crash.

| Failure                          | Result                                    |
| -------------------------------- | ----------------------------------------- |
| `getTrends` unreachable          | `SourceError`, fatal — nothing to analyse |
| One trend's `getFeed` fails      | Skip that trend, warn                     |
| One post's `getPostThread` fails | Keep the post with no replies, warn       |
| HTTP 429                         | Bounded retry with backoff                |
| One trend's distillation fails   | Drop that topic, warn                     |
| Trend with too few replies       | Distilled anyway; phrase list empty       |

A trend that yields no usable posts is skipped rather than distilled from
nothing. A run in which every trend fails raises, as an empty run is a failure
rather than a result.

## Settings

Added:

| Setting                     | Default | Purpose                           |
| --------------------------- | ------- | --------------------------------- |
| `bluesky_trend_limit`       | 25      | Trends per run; 25 is the API max  |
| `bluesky_posts_per_trend`   | 10      | Posts fetched per trend            |
| `bluesky_fetch_concurrency` | 8       | HTTP semaphore bound               |
| `distil_char_budget`        | 24000   | Reply characters per LLM call      |
| `distil_concurrency`        | 4       | Parallel distillation calls        |
| `phrase_min_authors`        | 3       | Distinct authors for a phrase      |

Removed: `sentiment_weights` and `DEFAULT_SENTIMENT_WEIGHTS`.

`post_limit` no longer bounds the Bluesky path — `bluesky_trend_limit ×
bluesky_posts_per_trend` does — but stays for the dormant sources.

`_check_sources` gains a clear error when any source other than `bluesky` is
selected, so a stale `SOURCES=lemmy` fails at startup rather than producing
garbage.

## Selection

`trend_score` continues to come from the existing engagement-velocity and
trend-status logic, regrouped from "items sharing a tag" to "posts under a
trend". The scorer's arithmetic survives intact.

Ranking is on `trend_score` alone. All sentiment weighting is removed and
`meme_potential` is recorded in the checkpoint but not applied. Both were
suppressing topics before there was any evidence that suppression helps, and
the point of this work is to stop discarding signal. Reintroducing a weight
later is a small change against a dossier that will, by then, be worth
weighting.

## Dormant platforms

Lemmy and Wikipedia keep their sources, scorers, metrics and tests exactly as
they are. They cannot feed the new path, and selecting them errors clearly.
Nothing is deleted; nothing is maintained in two shapes. `extract.py` and
`consolidate.py` likewise remain with their tests, off the path.

Some of this code will be dead for a while, and dead code rots. The mitigation
is that its tests keep running, so it cannot break silently, and that this
section records what it must eventually do.

**The rejoining contract: a platform rejoins the pipeline by producing
dossiers.** A platform with native trend clustering can do so directly. A
platform without one — Lemmy — needs a consolidation phase whose output is a
`Dossier` per cluster, not a label and a summary. Wikipedia cannot produce
dossiers at all, having no text, and remains a corroboration signal only.

Stating the contract this way keeps "topic" meaning exactly one thing across
the codebase. Running two topic-construction pipelines side by side would mean
two definitions of the central noun, and would double the cost of every later
change to it.

## Testing

Hermetic, as the suite already is. `tests/conftest.py` continues to strip every
environment variable `Settings` reads.

- **Source:** a fake async client replaying recorded payloads. Because
  `fetch()` stays synchronous, tests call it directly and need no async test
  infrastructure. Covers the three-level fan-out, per-trend and per-post
  failure isolation, 429 retry, and the semaphore bound.
- **Phrase mining:** table-driven tests over a pure function. The two cases
  that carry the design are 40 occurrences from 3 authors being excluded, and
  substring collapse selecting the maximal phrase. Also: within-reply
  deduplication, trend-name filtering, and an empty reply set.
- **Distillation:** a fake provider. Covers budget truncation, phrase
  attachment, and a failing trend being dropped rather than crashing the run.
- **Models:** `Register` round-tripping, `Topic.dossier` defaulting to None,
  and `TrendEvidence` rejecting unknown keys under `STRICT`.

`scripts/make_golden.py` is extended to capture one real `getTrends` response
plus a few feeds and threads into `tests/data/`, so fixtures are real payload
shapes rather than assumptions about them.

Per `CLAUDE.md`, the implementation plan's test code is audited with the
`reviewing-plan-tests` skill before execution, and the four Definition of Done
commands gate completion.

## What this does not fix

The two remaining causes of poor memes are untouched by design, and both become
tractable only once this lands:

- Template `shape` fields are too thin to guide template choice.
- The brief prompt does not explain what a meme is or how a rhetorical shape
  works.

Each is its own piece of work. Attempting them first would have meant
sharpening a knife with nothing to cut.
