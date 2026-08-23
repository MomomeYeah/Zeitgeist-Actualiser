# Bluesky Source and Per-Platform Score Weights

**Date:** 2026-08-23
**Status:** Draft

## Purpose

The project has two working platforms. Lemmy is content-bearing; Wikimedia
corroborates. The 2026-08-22 spec built the machinery for combining them and
noted that its value "rises sharply once a broader third source (YouTube,
Bluesky) lands". This spec lands Bluesky.

Bluesky is chosen for one reason above the others: it is conversational. Its
posts are people saying things, which is what the caption stages need and what
Wikimedia structurally cannot supply. Lemmy already provides that, but only
for a fediverse-and-technical audience. Bluesky is the same *kind* of signal
from a far wider one.

Adding it forces a change the previous spec deliberately deferred. That spec
kept `ScoreWeights` a single flat model and said so explicitly:

> The model stays a single `ScoreWeights` rather than fragmenting per
> platform — with one content-bearing scorer there is nothing to
> differentiate, and splitting it speculatively would add configuration
> surface for nobody.

That reasoning was correct then and expires here. Bluesky is a second
content-bearing scorer, it reads a metric no other platform has (reposts), and
it does not read two that Lemmy does. The flat model already sits awkwardly —
`WikipediaScorer` accepts a `ScoreWeights` and uses one field of it — and a
third platform makes the awkwardness structural rather than cosmetic.

## Scope

- `PlatformWeights`, a base holding the one genuinely shared weight, with a
  per-platform subclass discriminated on `platform`, mirroring the existing
  `Metrics` union.
- `ScoreWeights` reduced to the coordinator's own weight plus a per-platform
  mapping.
- Hoisting the rank-delta blend, currently duplicated verbatim between the
  Lemmy and Wikipedia scorers, into shared helpers in `scorers/base.py`.
- `BlueskySource`, fetching trends and the posts behind them.
- `BlueskyMetrics` in the `Metrics` union.
- `BlueskyScorer`, reading like, reply and repost velocity, and using
  Bluesky's own trend status as its movement term.
- Registry entries in `KNOWN_SOURCES`, `BUILDERS` and `SCORERS`.
- Updating `README.md` and `.env.example`.

### Out of scope

- **Wiring weights to `Settings`.** The refactor makes per-platform weights
  *expressible*; it does not make them configurable. `score_topics` continues
  to construct defaults. See "Deferred".
- **Filtering Bluesky by category.** The source ingests every trend it is
  given. See "The politics tilt" below.
- YouTube, Mastodon, Hacker News. The registry keeps each a new file.
- Authenticated Bluesky access. Nothing in this spec needs credentials.
- Bluesky's firehose. Trend-scoped polling is enough and vastly cheaper.
- Any change to the LLM providers, the media stages, or `Store`.

## Platform selection

The 2026-08-22 spec surveyed candidates and ruled Bluesky out on the grounds
that its "endpoints sit in the `unspecced` namespace". That concern is real
but was overweighted, and the survey's shortlist is otherwise still accurate.

The two live candidates were Bluesky and YouTube. They differ in kind, not
just in quality:

| | Bluesky | YouTube |
|---|---|---|
| Signal | what people are **saying** | what the mainstream is **watching** |
| Text | user-authored posts | uploader-authored title and description |
| Credentials | none | self-serve key, 1 quota unit/call |
| Audience skew | US politics, heavy | broad; music, sport, gaming |
| Stability | `unspecced` namespace | stable, versioned |

YouTube has the better breadth and the better stability. Bluesky was chosen
anyway, because YouTube's text is marketing copy rather than conversation.
A trending video's title tells you what is being promoted, not what anyone
thinks about it — which places it closer to Wikimedia's attention signal than
to Lemmy's. The project already has an attention source. It needs a second
voice, not a second thermometer.

YouTube remains the natural fourth source and this spec changes nothing about
its viability.

### The politics tilt

Recorded because it is a known, accepted defect rather than an oversight.
The live top-25 trends on 2026-08-23, by category:

```
politics 12    culture 4    entertainment 3    other 2    sports 2    science-tech 1
```

All three highest-`postCount` trends were politics. `DEFAULT_SENTIMENT_WEIGHTS`
puts `OUTRAGE` at 0.60, so the pipeline will actively push down much of what
this source surfaces.

The source ingests trends unfiltered regardless. `getTrends` returns a
`category` field, so filtering at ingestion is available and cheap, but doing
it would mean the source decides what the zeitgeist is allowed to contain
while the sentiment stage exists precisely to make that judgement with more
context. Two filters disagreeing about the same thing is worse than one filter
doing its job. If the sentiment weights prove insufficient in practice,
category filtering is a one-field change.

### What was verified

All of the following was verified live on 2026-08-23 against
`https://api.bsky.app`, unauthenticated, with no credentials of any kind:

- `app.bsky.unspecced.getTrends?limit=25` → `200`. Each trend carries
  `displayName`, `description`, `link`, `startedAt`, `postCount`, `status`
  and `category`.
- **`limit` caps at 25.** `limit=50` and `limit=100` both return `400`. This
  is a hard ceiling on the source, not a tuning parameter.
- `status` takes three values across a single response: `trending`,
  `cooling`, `stale`.
- Every one of 25 `link` values had the shape `/profile/{did}/feed/{rkey}`.
  No other shape occurred.
- `app.bsky.feed.getFeed` against the `at://{did}/app.bsky.feed.generator/
  {rkey}` built from each link → `200` for **25 of 25** trends. Posts carry
  `record.text`, `record.createdAt`, `record.langs`, `indexedAt`, `likeCount`,
  `replyCount`, `repostCount`, `quoteCount`, `bookmarkCount` and `labels`.
- `getFeed?limit=100` → `200`, so the source ceiling is 25 × 100 = 2500 posts,
  comfortably above `post_limit`'s default of 500.
- Across 240 posts drawn from 12 trend feeds: **240 unique URIs, zero
  duplicates** across feeds; 210 `en`, 16 with no `langs`, and a tail of `de`,
  `uk`, `nl`, `zh`; **zero** posts carrying labels.
- `record.createdAt` minus `indexedAt` over those 240 posts: median −1.1s,
  max +2.7s, min −834s. No post claimed a `createdAt` more than 60s ahead of
  its indexing.
- `public.api.bsky.app/xrpc/app.bsky.feed.searchPosts` → **`403`**, while the
  same call against `api.bsky.app` → `200`. The cached public host is no
  longer interchangeable. This spec uses `api.bsky.app` throughout and does
  not use `searchPosts`, but the distinction is recorded so a future change
  does not rediscover it.

**Not verified**, and to be confirmed on first real runs: how often
consolidation merges posts drawn from *different* Bluesky trends into one
topic. This drives the "Dropped: trend spread" decision below.

## Weights model

`scorers/base.py` gains the union. It mirrors `Metrics` in `models.py`
deliberately — same discriminator field, same reason for having one.

Both models take `models.STRICT` (`extra="forbid"`), which today's flat
`ScoreWeights` does not. That is a deliberate addition rather than an
oversight: once weights arrive as a nested mapping, a key typed against the
wrong platform — `upvote_velocity` under `bluesky` — would otherwise be
dropped in silence. `models.py` imports nothing from `analysis`, so importing
`STRICT` the other way is not a cycle.

```python
class PlatformWeights(BaseModel):
    """Weights every scorer has, because every scorer blends the same way."""

    model_config = STRICT

    rank_delta: float = 0.25


class LemmyWeights(PlatformWeights):
    platform: Literal["lemmy"] = "lemmy"

    upvote_velocity: float = 0.4
    comment_velocity: float = 0.3
    channel_spread: float = 0.3


class WikipediaWeights(PlatformWeights):
    """No fields of its own. Pageviews carry no velocity and no spread, so
    position and movement are the whole signal — which the base already
    covers. An empty subclass states that, where the flat model left
    `WikipediaScorer` silently ignoring three weights it was handed.
    """

    platform: Literal["wikipedia"] = "wikipedia"


class BlueskyWeights(PlatformWeights):
    platform: Literal["bluesky"] = "bluesky"

    like_velocity: float = 0.35
    reply_velocity: float = 0.30
    repost_velocity: float = 0.35


PlatformWeightsUnion = Annotated[
    LemmyWeights | WikipediaWeights | BlueskyWeights,
    Field(discriminator="platform"),
]


class ScoreWeights(BaseModel):
    model_config = STRICT

    # The one weight the coordinator itself reads. Not a platform's opinion,
    # so it does not belong in the per-platform mapping.
    corroboration_bonus: float = 0.25
    platforms: dict[str, PlatformWeightsUnion] = Field(
        default_factory=lambda: {
            "lemmy": LemmyWeights(),
            "wikipedia": WikipediaWeights(),
            "bluesky": BlueskyWeights(),
        }
    )
```

`rank_delta` sits on the base rather than on each subclass because it is
structural, not platform-specific: every scorer computes a base from its own
metrics and then blends that base against a movement term. The duplication
proves it — `lemmy.py` and `wikipedia.py` currently carry the same eight-line
delta block and the same four-line explanatory comment, character for
character.

### Keeping the registry uniform

`SCORERS` maps platform names to builders of a single `Callable` type. The
obvious refactor — giving `LemmyScorer.__init__` a `LemmyWeights` parameter —
breaks that, because narrowing a parameter type is a contravariance violation
and ty will reject the assignment into the `SCORERS` dict.

Scorers therefore keep taking the whole `ScoreWeights` and pull their own
slice out of it:

```python
class ScoreWeights(BaseModel):
    ...

    def for_platform[W: PlatformWeights](self, platform: str, expected: type[W]) -> W:
        """This platform's weights, narrowed to the type its scorer needs.

        The isinstance check is a registry-drift guard, not a cast: reaching
        it means `SCORERS` and `platforms` disagree about what a platform is,
        which is a bug in this package rather than bad input. Same spirit as
        `build_scorer`'s KeyError.
        """
        weights = self.platforms[platform]
        if not isinstance(weights, expected):
            raise TypeError(
                f"{platform} weights are {type(weights).__name__}, "
                f"expected {expected.__name__}"
            )
        return weights
```

Used as `self._weights = weights.for_platform("lemmy", LemmyWeights)`. PEP 695
generics per the project's Python 3.14 convention. `ScorerBuilder` and
`build_scorer` keep their current signatures unchanged.

A missing platform key raises `KeyError` from the `self.platforms[platform]`
subscript. That is the correct failure: `build_scorer` already raises
`KeyError` for an unregistered platform, so both halves of the same drift bug
fail the same way.

### Shared blend helpers

Two functions move into `scorers/base.py` alongside `normalise`:

```python
def historical_delta(bases: list[float], previous: list[float | None]) -> list[float]:
    """Normalised movement against each topic's own prior sub-score.

    An unseen topic defaults to its own base, not to 0.0: it has not risen,
    so its delta must be zero rather than full marks.
    """


def blend(bases: list[float], deltas: list[float], weight: float) -> list[float]:
    """(1 - weight) * base + weight * delta, elementwise."""
```

`historical_delta` absorbs the duplicated block from both existing scorers
verbatim, including the `prior`-bound-to-a-local shape that makes ty narrow
`float | None` correctly. `blend` absorbs the final line of all three scorers.

`LemmyScorer` and `WikipediaScorer` use both. `BlueskyScorer` uses `blend`
only — see below. That asymmetry is the honest outcome, not a sign the
abstraction is wrong: two of three platforms infer movement from history, and
one is told it directly.

## `BlueskySource`

`sources/bluesky.py`. No credentials. Base URL `https://api.bsky.app`.

```
1. GET app.bsky.unspecced.getTrends?limit=25
2. for each trend:
     link "/profile/{did}/feed/{rkey}"  ->  "at://{did}/app.bsky.feed.generator/{rkey}"
     GET app.bsky.feed.getFeed?feed=<uri>&limit=<per_trend>
3. filter, dedup, map to Item
```

`per_trend` is `max(1, ceil(limit / len(trends)))`, matching how `LemmySource`
splits its budget across sorts. As there, `limit` is an upper bound rather
than a target: the loop returns early once `limit` unique items are collected.

A `link` that does not match the `/profile/{did}/feed/{rkey}` shape is logged
and skipped rather than raising. 25 of 25 matched when verified, but the field
is a UI path and not a documented contract, so a future variant should cost
one trend rather than the run.

### Filtering

Two filters, both applied per post:

- **Language.** Keep posts whose `record.langs` contains `en`, or which
  declare no `langs` at all. 210 of 240 sampled posts were `en` and 16
  declared nothing; the rest were `de`, `uk`, `nl`, `zh`. The pipeline's other
  sources are English (`wikipedia_project` defaults to `en.wikipedia`), and a
  post the extraction prompt cannot read contributes noise rather than signal.
  Posts with no declared language are kept because the field is optional and
  client-set, so absence means unknown rather than non-English.
- **Labels.** Skip posts with a non-empty `labels` array. Zero of 240 sampled
  posts carried labels — trend feeds appear to filter already — so this
  changes nothing today and exists so that a change upstream does not put
  graphic or adult content into a meme. This is the Bluesky counterpart of
  `LEMMY_INCLUDE_NSFW`, but without a setting: there is no use case for
  turning it off.

Dedup on post `uri`. Zero duplicates occurred across 12 trend feeds, so this
is defensive rather than load-bearing — but trends can overlap in principle,
and first-seen-wins mirrors `LemmySource`. A post kept from the first trend it
appeared in keeps that trend's name and status.

### Item mapping

```python
Item(
    source_id=post["uri"],          # at:// URI, canonical and stable
    title=text,                     # posts cap at 300 graphemes, so no truncation needed
    body_excerpt=None,              # a Bluesky post has no body distinct from its text
    permalink=f"https://bsky.app/profile/{did}/post/{rkey}",
    fetched_at=fetched_at,
    metrics=BlueskyMetrics(...),
)
```

`permalink` is constructed rather than copied, unlike Lemmy's `ap_id` which is
already a browsable URL. An `at://` URI is an identifier, not an address, so
`source_id` and `permalink` diverge here for the first time. The `did` and
`rkey` are parsed back out of the `uri`.

A post whose `record.text` is empty after stripping is skipped: `Item.title`
would be blank, and the extraction prompt would have nothing to label.

### `BlueskyMetrics`

```python
class BlueskyMetrics(BaseModel):
    """Engagement as Bluesky reports it, plus the trend the post came from."""

    model_config = STRICT

    platform: Literal["bluesky"] = "bluesky"
    content_bearing: ClassVar[bool] = True

    like_count: int
    reply_count: int
    repost_count: int
    # Trend-level, duplicated onto every post from that trend — as Lemmy's
    # `channel` is community-level. `trend` gives the extraction prompt the
    # referent a short post usually omits; `status` is the scorer's movement
    # term.
    trend: str
    status: Literal["trending", "cooling", "stale"]
    created_at: datetime

    @property
    def context(self) -> str:
        return self.trend
```

Added to the `Metrics` union in `models.py`.

**`created_at` comes from `indexedAt`, not `record.createdAt`.** `createdAt`
is client-supplied and unverified; the scorer divides engagement by age, so a
future-dated post yields a negative denominator, saved only by the
`MIN_AGE_HOURS` clamp and silently distorted. `indexedAt` is assigned by the
relay. Measured skew between the two across 240 posts was a median of −1.1s
and a maximum of +2.7s, so the choice costs nothing in fidelity and removes
the failure mode entirely.

`context` returning the trend name is what makes short posts legible to
`extract.py`, whose prompt is one line per item. A verified example:

```
- id=at://... | Ghent University suspends Nathan Cofnas | Gotta love the Belgian bureaucratic reason in all of this: "you were r...
```

Without the trend name that post is unlabellable.

## `BlueskyScorer`

```python
STATUS_MOVEMENT = {"trending": 1.0, "cooling": 0.5, "stale": 0.0}
MIN_AGE_HOURS = 0.5
```

Base, from three normalised velocities weighted and rescaled by their total,
exactly as `LemmyScorer` does with its three:

```
like_velocity    mean(like_count / hours_since_indexed)
reply_velocity   mean(reply_count / hours_since_indexed)
repost_velocity  mean(repost_count / hours_since_indexed)
```

Movement, per topic, is `max(STATUS_MOVEMENT[m.status] for m in group)` — max
rather than mean because a topic appearing in one trending and one stale trend
is trending. Then `blend(bases, movement, weights.rank_delta)`.

`BlueskyScorer` ignores its `previous` argument entirely, as `WikipediaScorer`
already ignores `now`. The protocol supplies both to every scorer; using them
is optional.

### The status term is deliberately not normalised

Every other movement term in this codebase passes through `normalise`, because
a historical diff has no meaningful absolute scale. `STATUS_MOVEMENT` does:
`0.0`, `0.5` and `1.0` mean fixed things.

Min-maxing it would be actively wrong. All 25 trends can share a status —
`trending` is the common case shortly after a run of new trends appears — and
`normalise` over a constant list returns all zeros by design. The axis would
then contribute nothing, on precisely the runs where it has the most to say.

Uniform status across topics should shift every score by the same amount and
leave the ranking untouched, which the raw scalar achieves and the normalised
one does not. This is worth an explicit test.

### Dropped: trend spread

An earlier draft gave `BlueskyWeights` a fourth axis, `trend_spread`, counting
distinct trends per topic as the analogue of Lemmy's `channel_spread`. It was
dropped.

Lemmy's `channel_spread` discriminates because Lemmy has thousands of
communities and a topic genuinely can appear across several. Bluesky caps at
25 trends *and has already clustered posts into them* — the clusters are the
platform's own topic model, and they are close to disjoint. Most consolidated
topics will therefore draw from exactly one trend, `normalise` over a
near-constant list returns zeros, and the weight would sit in the config
looking meaningful while contributing nothing measurable.

Repost velocity covers what spread was reaching for. A repost is a post
travelling beyond the audience that first saw it, which is the same property
`channel_spread` approximates by counting communities — measured directly
rather than inferred from bucket counts.

If first runs show consolidation routinely merging posts from different
trends, this is one field and one term to add back.

## Failure behaviour

- `getTrends` fails or returns no trends → `SourceError`. Without trends there
  is no way into the content, so there is no partial result to salvage.
- One trend's `getFeed` raises `httpx.HTTPError` → log a warning and continue
  to the next trend, mirroring how `LemmySource` tolerates one failed sort.
- One trend's `link` does not parse → log a warning and skip that trend.
- A `KeyError` from a changed payload propagates. That is a contract break,
  not an outage, and the project's convention is that it crashes.
- Every trend fails, or every post is filtered out → `SourceError`.

## Configuration

`config.py`:

```python
KNOWN_SOURCES: tuple[str, ...] = ("lemmy", "wikipedia", "bluesky")

    bluesky_api_base: str = "https://api.bsky.app"
```

One setting, and it exists so the host can be pointed at a mirror or a test
double rather than because anyone is expected to change it. Note that
`public.api.bsky.app` is **not** a valid substitute; it returns 403 on parts
of the API.

No trend-count setting: the API caps at 25 and the source always asks for the
maximum. No credentials. No NSFW toggle — see "Filtering".

`.env.example` and the README's Sources section gain a Bluesky paragraph
covering the lack of credentials, the `unspecced` caveat, and the politics
tilt.

## Testing

Following the existing source and scorer tests, against fakes rather than the
network.

`tests/test_sources_bluesky.py`:

- Trends and feeds map to `Item`s with the expected fields; `permalink` is
  built correctly from an `at://` URI; `context` is the trend name.
- `created_at` comes from `indexedAt`, **not** from `record.createdAt` — the
  fake supplies deliberately divergent values, so a scorer reading the wrong
  field fails rather than passing on coincidence.
- Non-English `langs` are dropped; absent `langs` are kept.
- Labelled posts are dropped.
- Empty-text posts are dropped.
- A duplicate `uri` across two trend feeds yields one item, keeping the first
  trend's name.
- A malformed `link` skips one trend and keeps the others.
- One failing `getFeed` skips one trend and keeps the others.
- A failing `getTrends` raises `SourceError`; so does every-trend-failing.
- The budget splits across trends and `limit` is respected as an upper bound.

`tests/test_scorers_bluesky.py`:

- Higher like/reply/repost velocity ranks higher, one axis at a time.
- Velocity is per hour, not absolute: an older post with more likes can rank
  below a newer one with fewer.
- `status` ordering: `trending` outranks `cooling` outranks `stale`, holding
  the base equal.
- A topic spanning `trending` and `stale` scores as `trending` (max, not
  mean).
- **Uniform status across all topics leaves the ranking unchanged** — the
  regression test for not normalising the status term.
- `previous` is ignored: passing different histories does not change output.

`tests/test_scorers_base.py` (new):

- `for_platform` returns the narrowed subclass.
- `for_platform` raises `TypeError` on a mismatched pairing.
- `for_platform` raises `KeyError` for an unregistered platform.
- `historical_delta` defaults an unseen topic to zero movement, not to full
  marks.

Existing tests: `test_scorers_registry.py` and `test_sources_composite.py`
guard the registries against drift and will require the Bluesky entries.
`test_analysis_score.py`, `test_scorers_lemmy.py` and
`test_scorers_wikipedia.py` need updating for the new weights construction.
Lemmy and Wikipedia scoring output must be **unchanged** by phases 1 and 2 —
worth asserting directly, as the previous spec did for its own refactor.

## Implementation sequence

Three phases, each leaving the four Definition of Done commands passing.

1. **Shared blend helpers.** Add `historical_delta` and `blend` to
   `scorers/base.py` and rewrite the Lemmy and Wikipedia scorers to use them.
   No model changes, no new platform. Output is bit-identical; the existing
   scorer tests are the proof and should not need editing.
2. **Weights union.** `PlatformWeights` and its subclasses, `ScoreWeights`
   reduced to `corroboration_bonus` plus the mapping, `for_platform`, and both
   existing scorers switched to it. Still no new platform. `WikipediaWeights`
   being empty is the visible payoff. Scoring output unchanged again.
3. **Bluesky.** `BlueskyMetrics`, `BlueskySource`, `BlueskyScorer`,
   `BlueskyWeights`, the three registry entries, config, and documentation.

Phases 1 and 2 are refactors with no user-visible change; phase 3 is the
feature. Any phase boundary is a safe stopping point.

The ordering matters: doing the union first would mean rewriting the delta
duplication twice, and doing Bluesky first would mean writing a third copy of
a block that is about to be deleted.

## Risks

**`unspecced` instability.** `app.bsky.unspecced.getTrends` is documented by
Bluesky as not a stable API, and the namespace says so in its own name. It is
this source's only unspecced dependency, and it powers the live Bluesky app,
so it will not disappear without notice — but it can change shape faster than
`app.bsky.feed.*` will. Mitigation is structural rather than clever: a changed
payload raises `KeyError` and crashes loudly, and `getTrends` failing raises
`SourceError` that takes down one source rather than the run.
`app.bsky.unspecced.getTrendingTopics` is a lighter-weight fallback if the
richer endpoint goes away, at the cost of `status` and `category`.

**Politics tilt fights the sentiment weights.** Half of what this source
surfaces is material the pipeline is configured to suppress, so Bluesky may
contribute fewer selected topics than its volume suggests. Accepted
deliberately — see "The politics tilt". Measure the category mix of *selected*
topics on the first real runs; category filtering is the remedy if the
sentiment stage proves insufficient.

**25-trend ceiling.** The source cannot see more than 25 topics, whatever
`post_limit` says. Depth per trend is adjustable, breadth is not. This is
narrower than Lemmy's view and much narrower than Wikimedia's top-1000, so
Bluesky will corroborate less often than its size would suggest.

**Trend-scoped sampling is not a random sample.** Every Bluesky post the
pipeline sees was selected by Bluesky's own trend clustering. The source
inherits whatever that clustering favours, and cannot see a topic Bluesky has
not already decided is trending. This is a different bias from Lemmy's, whose
`Hot` and `Scaled` listings rank posts rather than pre-grouping them.

## Deferred

- **Configurable weights.** The refactor makes per-platform weights
  expressible and leaves them hardcoded. Wiring a `score_weights: ScoreWeights`
  field into `Settings`, set from a JSON environment variable exactly as
  `sentiment_weights` already is, is a small follow-up — and a much easier one
  against the union than against the flat model, which is part of the point.
- **A CLI weights override** (`--weights <file.json>`) for sweeping weightings
  across runs without editing `.env`.
- **Category filtering or down-weighting** for Bluesky.
- **YouTube** as a fourth source, for the mainstream breadth Bluesky does not
  provide.
- **`quoteCount` and `bookmarkCount`**, both available and both unused. Quotes
  are arguably a stronger engagement signal than reposts because they carry
  commentary. Left out to keep the axis count at three; worth revisiting once
  there is real scoring output to compare against.

## Decisions and rationale

**Bluesky over YouTube**, despite YouTube's better breadth and stability,
because YouTube's text is uploader marketing copy rather than conversation.
The project has an attention source already.

**Unfiltered ingestion**, despite the politics tilt, because the sentiment
stage exists to make exactly that judgement and two filters disagreeing is
worse than one.

**`rank_delta` on the base class** rather than on each subclass, because the
verbatim duplication between the two existing scorers demonstrates it is
structural.

**Scorers take the whole `ScoreWeights`** and narrow internally, rather than
declaring a narrowed parameter type, because the latter is a contravariance
violation that would break the uniform `SCORERS` registry.

**`indexedAt` over `record.createdAt`**, because `createdAt` is client-
supplied and the scorer divides by age.

**Status replaces the historical delta** for Bluesky rather than averaging
with it, because they are two estimates of the same quantity, the platform's
own is better informed, and it works on a first run when there is no history.

**Status is not normalised**, unlike every other movement term, because it has
a real absolute scale and min-maxing it would zero the axis exactly when every
trend shares a status.

**No `trend_spread`**, because Bluesky's 25 trends are its own disjoint topic
clusters, so the axis would be near-constant and silently contribute nothing.
