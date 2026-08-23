# Wikimedia Pageviews Source and Per-Platform Trend Scoring

**Date:** 2026-08-22
**Status:** Draft

## Purpose

The project has one working platform. Lemmy runs; Reddit is implemented and
unit-tested but unusable, because Reddit's Data API is no longer self-serve
and `client_id`/`client_secret` cannot be obtained (see the 2026-08-18 spec).
`CompositeSource` has therefore never fanned out across two live platforms.

This spec also **removes** `RedditSource`. That reverses the 2026-08-18
decision to keep it "intact and working for if or when access is granted",
because the cost of that decision changes here — see "Removing Reddit" below.

This spec adds Wikimedia pageviews as a second working source. Doing so forces
a change the project has been deferring: Wikimedia has no comments, no
communities, and no per-item creation date, so the single shared scorer in
`analysis/score.py` cannot rank it. Scoring becomes a per-platform strategy,
each normalising within its own platform before results are combined.

That redesign is the cross-platform normalisation work the previous spec
deferred, arrived at from the opposite direction. Rather than calibrating
absolute magnitudes between platforms, every platform emits a score already
scaled to itself, so "rank 3 of what Wikipedia saw" and "rank 7 of what Lemmy
saw" are directly comparable. Rank-relative normalisation is scale-free and
distribution-free, which is why it sidesteps the magnitude problem entirely.

## Scope

- Removing `RedditSource`, its tests, its configuration, and the `praw`
  dependency.
- `WikipediaSource`, fetching the Wikimedia pageviews top-articles listing.
- Replacing `Post` with `Item`, carrying a discriminated union of
  platform-specific metrics models, and renaming `Topic.post_ids` to
  `Topic.item_ids` to match.
- A scorer registry under `analysis/scorers/`, one strategy per platform.
- Reducing `analysis/score.py` to a coordinator that dispatches to scorers and
  combines their output.
- A content-bearing/corroboration-only distinction between sources, and
  dropping topics that no content-bearing platform saw.
- A `topic_scores` table holding per-platform sub-scores across runs, and a
  `PRAGMA user_version` guard that fails fast on a stale database.
- Updating `README.md` and `.env.example`.

### Out of scope

- Hacker News, Bluesky, YouTube, Mastodon. The registry keeps each a new file.
- Fetching Wikipedia article summaries. See "Decisions" below.
- Multiple Wikipedia language projects. `en.wikipedia` only.
- Database migration. The project is early; the guard tells the user to delete
  `data/zeitgeist.db` and re-run.
- Any change to the LLM providers or the media stages (`brief.py`,
  `render.py`, `templates.py`). The `Item` envelope keeps those untouched.

### Correction: the analysis stages are *not* untouched

An earlier draft claimed `extract.py`, `consolidate.py` and `sentiment.py`
needed no changes. Reading them disproves it:

- `extract.py:70` builds its prompt from `post.channel`, which no longer
  exists on the envelope and has no Wikipedia equivalent.
- `consolidate.py:74-88` constructs `Topic(post_ids=...)`.
- `sentiment.py:90` reads `len(topic.post_ids)`.

The envelope keeps these changes *small* — none of them touch the LLM contract
or the stage boundaries — but "untouched" was wrong.

`extract.py` needs a per-platform hint to replace `channel`. Each metrics
model gains a `context` property, delegated through `Item.context`:

| Platform | `context` |
|---|---|
| Lemmy | the channel, e.g. `"technology@lemmy.world"` |
| Wikipedia | `f"{views:,} views"` |

So the extraction prompt line becomes
`f"- id={item.source_id} | {item.context} | {item.title}"`, keeping the same
shape while giving each platform a hint that is meaningful for it.

## Removing Reddit

The 2026-08-18 spec kept `RedditSource` on the reasoning that it was written,
tested, and cost nothing to leave in place. Two of those three stop being true
here.

**It is not tested in the way that matters.** `tests/test_sources_reddit.py`
holds ten tests against hand-built `StubReddit`, `StubListing` and
`StubSubmission` fakes — mapping, dedup across hot and rising, budget limits,
body truncation, per-subreddit failure isolation. As unit tests they are
sound. But no run has ever confirmed the stubs resemble PRAW: they encode
assumptions about `submission.subreddit.display_name`, `created_utc` and
`num_comments` that nothing has checked against a real response. The suite
proves internal consistency and nothing else, which is worse than no coverage
in one specific way — it looks like coverage.

**It stops costing nothing.** Per-platform scoring means Reddit no longer
rides along on Lemmy's scorer. Keeping it through this spec costs a
`RedditMetrics` union member, a `scorers/reddit.py` that is a hand-copied
duplicate of the Lemmy algorithm, a test file for that duplicate, entries in
three registries, and a credential branch in `_check_sources`. This spec would
not preserve Reddit; it would *port* Reddit into an architecture it cannot
run in.

**Preservation was the point, and porting defeats it.** The value of keeping
the code was that it would be ready if access were granted. By the end of this
spec that code is `Item`-shaped, metrics-union-shaped and scorer-registry-
shaped — rewritten throughout against an API still nobody has tested it
against. Access being granted would mean verifying every line against real
PRAW responses regardless, so the ported code saves no work. `git show`
recovers the original just as well, and dropping it removes `praw>=7.8` — a
23.8 MB sdist — from the dependency tree.

The one real loss: Lemmy becomes the only content-bearing platform, so nothing
exercises two content-bearing sources corroborating each other. That path
matters when a second one lands (YouTube, Hacker News), but it does not exist
today either, and covering it through Reddit's unverified stubs would be
theatre rather than protection.

## Platform selection

Recorded because the evaluation cost real effort and the runners-up matter for
what comes next.

Ruled out on data access: TikTok, Instagram, Facebook and Threads (approval-
gated behind Meta app review or TikTok's researcher programme), Twitter/X
(paid tiers for meaningful read volume), Google Trends (no stable public API;
`pytrends` scrapes an internal endpoint), GitHub trending (HTML only),
Spotify, Tumblr, NewsAPI (free tier prohibits production use).

Serious candidates, all viable:

| Platform | Trending signal | Access | Why not now |
|---|---|---|---|
| **Wikimedia** | top-1000 by daily views | none needed | *chosen* |
| Hacker News | `topstories` | none needed | post-shaped, so it would not have forced the scoring redesign |
| YouTube | `chart=mostPopular` | self-serve key, 1 quota unit/call | best breadth; natural next source |
| Bluesky | `getTrendingTopics` | app password | endpoints sit in the `unspecced` namespace |
| Mastodon | `/api/v1/trends/statuses` | none needed | near-duplicate of Lemmy's audience |
| Stack Exchange | `sort=hot` | self-serve key | "hot" means popular questions, not zeitgeist |

Wikimedia was chosen over Hacker News deliberately. HN is the cheaper build
but it drops into the existing pipeline unchanged, which means it would
validate nothing about the design. Wikimedia is the awkward case, and
designing the scorer seam against a concrete awkward case beats abstracting
speculatively for one that has not arrived.

### What was verified

Verified live on 2026-08-22 against
`https://wikimedia.org/api/rest_v1/metrics/pageviews/top/en.wikipedia/all-access/2026/08/20`:
returns 1000 ranked articles, no authentication, JSON shape
`items[0].articles[] = {article, views, rank}`.

**Not verified**, and to be confirmed during implementation: how far behind
"today" the data lags. Later probes to every Wikimedia host returned an
empty-bodied 400 from HAProxy — including a URL that had succeeded minutes
before, while a control request to an unrelated host returned 200 — which
identifies the failure as sandbox egress restriction, not API behaviour. The
day walk-back below is designed so the answer does not matter.

## Data model

`Post` becomes `Item`. The universal fields stay in the envelope; everything
platform-specific moves into a discriminated union.

```python
class LemmyMetrics(BaseModel):
    model_config = STRICT
    platform: Literal["lemmy"] = "lemmy"
    content_bearing: ClassVar[bool] = True
    score: int
    comment_count: int
    channel: str
    created_at: datetime          # when the post was made

class WikipediaMetrics(BaseModel):
    model_config = STRICT
    platform: Literal["wikipedia"] = "wikipedia"
    content_bearing: ClassVar[bool] = False
    views: int
    rank: int
    measured_on: date             # the day the measurement covers

Metrics = Annotated[
    LemmyMetrics | WikipediaMetrics,
    Field(discriminator="platform"),
]

class Item(BaseModel):
    model_config = STRICT
    source_id: str
    title: str
    body_excerpt: str | None = None
    permalink: str
    fetched_at: datetime
    metrics: Metrics

    @property
    def platform(self) -> str:
        return self.metrics.platform
```

Three consequences worth stating explicitly:

**No field means two things.** `created_at` was ambiguous across platforms —
"when posted" for Lemmy, "when measured" for Wikipedia. Splitting the union
lets each carry the name that is true for it. Nothing is nullable and nothing
is filled with a placeholder zero.

**`ty` narrows the union.** Each scorer accesses only its own metrics type
with full checking. A free-form `dict[str, float]` would have shed type safety
at exactly the boundary the project deliberately keeps strict.

**`Item.platform` keeps existing call sites working.** `CompositeSource`'s
`(post.platform, post.source_id)` dedup key needs no change.

`Topic.post_ids` is renamed to `Topic.item_ids`, still holding `source_id`
values. Keeping the old name would leave the codebase referring to a `Post`
model that no longer exists, and "post" is already wrong for a Wikipedia
article-day — as it would be for a Twitch stream or a YouTube video under the
platforms this design is meant to accommodate.

The rename touches six production references across `models.py`,
`consolidate.py`, `score.py` and `sentiment.py`, plus tests. It is not
persisted, so the database is unaffected.

Two knock-on effects:

**A prompt string changes.** `sentiment.py:90` builds
`f"Appears in {len(topic.post_ids)} posts."` — text the model reads. "Posts"
becomes wrong once a count can include Wikipedia measurements, so it becomes
`f"Appears in {len(topic.item_ids)} items."` in phase 1: a pure rename that
leaves prompt semantics intact.

Extending it to name the platform count — `"across N platforms"`, which would
give the sentiment stage the corroboration signal it currently cannot see — is
a genuine improvement but changes model input and therefore output. It belongs
in phase 2 alongside the corroboration work, not bundled into a refactor whose
value is being provably behaviour-preserving.

**Old run directories stop resuming.** `Topic` is serialised into
`output/<run-id>/*.json`, and `--resume-from generate` reads it back. With
`extra="forbid"` on the model, a checkpoint containing `post_ids` will fail
validation rather than silently drop the field. That is the right failure —
loud, at the boundary — and old run directories are as disposable as the
database at this stage.

For the same reason the ingest checkpoint is renamed `posts.json` →
`items.json`, the `runs.post_count` column becomes `item_count`, and the CLI
line in `cli.py:102` reporting `"N posts"` becomes `"N items"`. Leaving these
as "post" would preserve exactly the confusion this rename exists to remove.

## WikipediaSource

```
GET https://wikimedia.org/api/rest_v1/metrics/pageviews/top/{project}/all-access/{Y}/{M}/{D}
```

One request per run. Walks back from today one day at a time until a day
returns data, up to `MAX_DAY_ATTEMPTS = 5`, then raises `SourceError`. This is
what makes the unverified lag irrelevant: whatever it is, the source finds the
most recent day that exists.

`source_id` is `"{project}:{article}:{date}"` — unique per measurement day, so
re-running on a later date does not collide with a stored earlier one.

`permalink` is `https://en.wikipedia.org/wiki/{article}`.

`title` is the article name with underscores replaced by spaces, which is what
`extract_tags` sends to the model.

`fetch(limit)` truncates to `limit` **after** structural filtering, so the
budget buys real articles rather than being spent on `Main_Page` and friends.
The API always returns 1000 regardless, so unlike Lemmy there is no paging and
a smaller `limit` saves no requests — only downstream LLM tokens.

### Structural filtering

Dropped by prefix: `Special:`, `Wikipedia:`, `Portal:`, `Help:`, `Category:`,
`Template:`, `File:`, `Talk:`. Dropped exactly: `Main_Page`. Dropped by
pattern: `Deaths_in_\d{4}`.

From the captured payload these account for ranks 1, 2, 3 and 7 — `Main_Page`
alone draws 6.6M views, roughly sixteen times the first real article — so
without this filter they would set the entire min-max range and flatten
everything genuine to near zero.

Perennially popular articles are **not** filtered. `Google` sits in the top
ten most days; it is neutralised by rank-delta scoring, which sees no change
and therefore scores it low. Maintaining a denylist of merely-popular topics
would be a guessing game the scorer already handles correctly.

## Scorer registry

New package `zeitgeist/analysis/scorers/`, with `base.py`, one module per
platform, and a registry mirroring `sources/__init__.py`'s `BUILDERS`.

```python
class TrendScorer[M: BaseModel](Protocol):
    platform: str
    def score(
        self, per_topic: list[list[M]], previous: dict[str, float]
    ) -> list[float]: ...
```

Given, for each topic, that platform's items within it, return one score in
`[0, 1]` per topic, normalised **within the platform** across that run's
topics. Normalising within the platform is what makes the outputs comparable
between platforms; it is the whole mechanism.

- **`lemmy.py`** keeps today's maths verbatim: upvote velocity, comment
  velocity, channel spread and rank delta, min-max normalised, blended as
  `(1 - rank_delta) * base + rank_delta * delta`.
- **`wikipedia.py`** scores position and delta only. Its inputs carry no
  comments, no channel, and no per-item age, so velocity is undefined.

Wikipedia's calculation, stated precisely because "rank delta" admits several
readings:

```
best_rank    = min(item.rank for item in topic's Wikipedia items)
raw          = -float(best_rank)          # negated: rank 1 is the largest
base[i]      = _normalise(raw across all topics)[i]
delta[i]     = _normalise(base[i] - previous.get(slug, base[i]))[i]
score[i]     = (1 - w.rank_delta) * base[i] + w.rank_delta * delta[i]
```

Negating the rank rather than scaling it against a total avoids needing to
know how many articles a run kept: `_normalise` establishes the range from
whatever is present, so the maths is independent of `limit` and of how many
articles structural filtering removed.

The shape deliberately mirrors Lemmy's so the two are comparable and the
existing `_normalise` helper is shared rather than duplicated. Defaulting the
lookup to `base[i]` — not `0.0` — means a topic with no history gets a delta
of zero rather than a spurious full-marks rise; this is the same subtlety
`tests/test_analysis_score.py:67` already pins for the current scorer, and it
is why a first run does not rank every topic as maximally rising.

### `ScoreWeights` after the split

The existing weights (`upvote_velocity`, `comment_velocity`, `channel_spread`,
`rank_delta`) describe *within-platform* maths and move with the scorers that
use them; `wikipedia.py` reads only `rank_delta` and ignores the rest.
`corroboration_bonus` is the one weight the coordinator itself uses. The model
stays a single `ScoreWeights` rather than fragmenting per platform — with one
content-bearing scorer there is nothing to differentiate, and splitting it
speculatively would add configuration surface for nobody.

## Score combination

`analysis/score.py` shrinks to a coordinator. Ordering matters and is the
subtlest part of this spec:

```
1. group each topic's items by platform
2. per-platform scorers ──> sub-scores        # normalise across ALL topics
3. drop topics no content-bearing platform saw
4. combine surviving topics' sub-scores
```

**Scoring precedes filtering.** If a platform contributed to six topics and
five are dropped for being corroboration-only, the scorer must still see all
six: they set the normalisation range, and the survivor's score means "of
everything Wikipedia noticed this run, how prominent was this?". Reversing
these steps hands the scorer a single value, min-max over which yields `0.0`,
so corroboration would *penalise* the topic it is meant to reward. This
ordering is load-bearing and has a test naming it.

Combination is the mean of a topic's sub-scores, multiplied by a corroboration
bonus growing with the number of platforms that saw it:

```
trend_score = mean(sub_scores) * (1 + k * (n_platforms - 1))
```

`k` joins `ScoreWeights` as `corroboration_bonus`, default `0.25`. So a topic
at 0.8 on two platforms (0.8 × 1.25 = 1.0) outranks one at 0.9 on a single
platform. A topic trending in several places at once is more genuinely
zeitgeist than one trending loudly in exactly one, and this is the only
mechanism expressing that.

**Degenerate case.** If a platform contributed to fewer than two topics in a
run, min-max carries no information. That platform's sub-score is excluded
from the mean but the platform still counts toward `n_platforms`, so the
corroboration signal survives without a fabricated number entering the
average. With 1000 Wikipedia articles per run this should effectively never
fire; it exists so that when it does, it fails safe.

`score_components` gains one entry per contributing platform plus
`corroboration`, so a run's JSON checkpoint explains its own ranking.

## Configuration

New keys in `.env.example`:

```
SOURCES=lemmy,wikipedia
WIKIPEDIA_PROJECT=en.wikipedia
WIKIPEDIA_CONTACT=https://github.com/MomomeYeah/Zeitgeist-Actualiser
```

`wikipedia` joins `KNOWN_SOURCES` in `config.py` and `BUILDERS` in
`sources/__init__.py`. It needs no credentials, so `_check_sources` gains no
new validation branch.

`WIKIPEDIA_CONTACT` is interpolated into the User-Agent. Wikimedia's API
policy requires an agent carrying contact information and warns that generic
agents may be rate-limited or blocked outright, so Lemmy's static
`zeitgeist-actualiser/0.1` would not satisfy it. The default is the project
repository URL; no personal email is baked into the codebase.

## Persistence

`store.py` gains:

```sql
CREATE TABLE IF NOT EXISTS topic_scores (
    run_id    TEXT NOT NULL,
    label     TEXT NOT NULL,
    platform  TEXT NOT NULL,
    sub_score REAL NOT NULL,
    PRIMARY KEY (run_id, label, platform)
);
```

`Store.previous_scores` is **replaced** by
`previous_sub_scores(platform, exclude_run_id)`, returning
`{label_slug: sub_score}` from the most recent prior run. Each scorer's
rank-delta now compares against its own platform's history rather than the
combined topic score, which mixes platforms and would make the delta
meaningless. `previous_scores` has exactly one call site — `pipeline.py:74`,
feeding the combined scorer — and that call site disappears with this change,
so the old method is deleted rather than kept alongside.

The `topics` table keeps storing the combined `trend_score`, which remains
useful for inspecting run history even though nothing reads it back.

`SCHEMA_VERSION = 2`, checked against `PRAGMA user_version` on open. A
mismatch raises with an actionable message naming `data/zeitgeist.db` and
telling the user to delete it. `CREATE TABLE IF NOT EXISTS` silently accepts a
stale schema and fails later with something cryptic; this converts that into
an obvious failure at startup.

## Failure behaviour

Follows the contract in `sources/base.py`: only recoverable failures become
`SourceError`; everything else propagates as a bug.

| Condition | Behaviour |
|---|---|
| Transport failure for one day | Log, try the next day back |
| All 5 attempts exhausted | `SourceError` |
| Empty listing after filtering | `SourceError` |
| Missing `items`/`articles` key | `KeyError` propagates — contract break, not an outage |
| No scorer registered for a platform | Fails at startup, not mid-run |

`CompositeSource` already catches `SourceError` and continues, so a Wikimedia
outage degrades to a Lemmy-only run rather than killing the pipeline.

## Testing

Hermetic throughout; no test touches the network. `WikipediaSource` accepts an
injected client, as `LemmySource` already does. The fixture is the real
1000-article payload captured on 2026-08-22, trimmed, not invented.

- **Day walk-back**: first two days fail, third returns data; assert the
  resulting `date` and that it does not over-attempt.
- **Exhaustion**: all five fail; assert `SourceError`.
- **Structural filtering**: `Main_Page`, `Special:Search`,
  `Wikipedia:Featured_pictures` and `Deaths_in_2026` dropped;
  `Hayden_Panettiere` survives — real titles and ranks from the payload.
- **Perennials survive the source**: `Google` is not filtered, and is instead
  scored low by rank-delta when its previous sub-score matches. Asserting both
  halves is what pins the division of responsibility.
- **Each scorer in isolation**: pure functions over constructed metrics.
- **Corroboration reorders**: a topic at 0.8 on two platforms outranks one at
  0.9 on one platform. This is the assertion that catches the bonus being
  silently zeroed.
- **Scoring precedes filtering**: a run where a platform sees six topics and
  five are corroboration-only must score the survivor using the full range.
  Written to fail against the reversed ordering.
- **Degenerate case**: a platform contributing to one topic is excluded from
  the mean but still counts toward `n_platforms`.
- **Registry drift**: every platform in the `Metrics` union has a registered
  scorer, mirroring the existing `BUILDERS`/`KNOWN_SOURCES` guard.

Per `CLAUDE.md`, the implementation plan's test code goes through the
`reviewing-plan-tests` skill before execution.

## Implementation sequence

This spec is larger than the previous two, so the plan should land it in five
phases, each leaving the four Definition of Done commands passing:

0. **Remove Reddit.** `sources/reddit.py`, `tests/test_sources_reddit.py`, the
   `reddit` entries in `KNOWN_SOURCES` and `BUILDERS`, the credential settings
   and their `_check_sources` branch, the `praw` dependency, and the README
   and `.env.example` sections. First rather than last: every later phase is
   smaller for it, and the alternative is porting Reddit through four phases
   in order to delete it.
1. **`Post` → `Item`.** The discriminated union, the `Topic.item_ids` rename,
   plus mechanical updates to Lemmy, `CompositeSource`, `extract.py`,
   `consolidate.py`, `sentiment.py`, `pipeline.py` and their tests. No
   behaviour change; `score.py` keeps reading the same values through the new
   envelope. This is the biggest diff and the least interesting, and isolating
   it keeps the review tractable.
2. **Scorer registry.** Move the existing maths into `scorers/lemmy.py`,
   reduce `score.py` to the coordinator, add the combination and the
   content-bearing filter, and extend the sentiment prompt to name the
   platform count. Still no new platform — with one content-bearing source
   enabled, scoring output should be identical to phase 1 apart from the
   corroboration factor being `1.0` throughout. That equivalence is worth
   asserting as a test.
3. **Persistence.** `topic_scores`, `previous_sub_scores`, the schema guard,
   and deleting `previous_scores`.
4. **`WikipediaSource`.** The new source, config keys, registry entries, and
   documentation.

Phase 0 removes a platform nobody can run; phases 1–3 are refactors with no
user-visible change; phase 4 is the feature.
If the work is interrupted, any phase boundary is a safe stopping point.

## Risks

**Thin overlap.** Wikipedia only ever amplifies topics another platform found.
Lemmy skews fediverse and technical; Wikipedia's top-1000 skews mainstream —
celebrities, films, sport, obituaries. The intersection may be small, so early
runs may show corroboration firing rarely. This is expected, not a defect: the
machinery is the deliverable, and its value rises sharply once a broader third
source (YouTube, Bluesky) lands. Worth measuring on the first real runs.

**Unverified lag.** If pageviews data proves to lag by several days, Wikipedia
corroborates yesterday's zeitgeist. The walk-back handles availability but
cannot make stale data fresh. Measure the actual gap on first run; if it is
large, weight Wikipedia's contribution down rather than removing it.

**Refactor breadth.** `Post` → `Item` touches 26 references across 8 modules
plus their tests, and lands before any Wikimedia code runs. It is the bulk of
the work and carries no user-visible benefit on its own.

## Deferred

- Article summaries, and therefore Wikipedia-originated topics.
- Multiple language projects. Would give `channel_spread` a natural meaning
  for Wikipedia (an article trending in five languages is bigger news than one
  trending in English), but needs cross-language title unification.
- **Corroboration combination semantics.** Sub-scores are combined as
  `mean(sub_scores) * (1 + 0.25 * (n_platforms - 1))`. Because each platform's
  sub-scores are min-max normalised across the topics *that platform* saw, the
  bottom of every platform's range is always exactly `0.0`, so a weak
  corroboration pulls the mean down faster than the bonus lifts it. Break-even
  is at `W > 0.6*L`: Lemmy 0.80 alone scores 0.800, but Lemmy 0.80 + Wikipedia
  0.15 scores 0.594 — a 26% demotion for being noticed by a second platform.
  No test catches this, because
  `test_corroboration_makes_two_platforms_beat_one_stronger_platform` picks
  `wikipedia = 0.75`, near the top of Wikipedia's range.

  This may be correct behaviour: a barely-ranked article is arguably evidence
  that a topic is *not* broadly trending, and the mean expresses that honestly.
  The open question is whether this section's claim that the bonus is "the only
  mechanism expressing" multi-platform zeitgeist matches what the arithmetic
  does. Two alternatives if corroboration should never demote:

  - `max(sub_scores) * (1 + k * (n - 1))` — rank on the strongest single-platform
    signal, so breadth only ever adds and a weak second platform is ignored
    rather than averaged in.
  - `max(mean(sub_scores) * bonus, strongest_content_bearing_sub_score)` — keep
    the mean's averaging behaviour but floor the result, so corroboration can
    never push a topic below what it scored alone.

  Revisit once real runs show how often Lemmy and Wikipedia actually overlap.
- Tuning `corroboration_bonus` against real runs. `0.25` is a starting point.
- **`STRUCTURAL_PREFIXES` is English-only.** `Special:`, `Wikipedia:`,
  `Portal:` and friends are the English namespace names, so a `de.wikipedia`
  run would not filter `Spezial:` and would let namespace pages set the
  min-max range — the exact failure the filter exists to prevent. `en.wikipedia`
  is the default and the only project this spec scopes to, but
  `WIKIPEDIA_PROJECT` is a configurable knob and `WikipediaSource`'s own tests
  make non-English projects a first-class path. Localise the prefix list before
  recommending any other project.
- Hacker News and YouTube, both now cheap to add.

## Decisions and rationale

**Discriminated union rather than optional fields.** Making `comment_count`
and `channel` nullable on a shared `Post` would model "Wikipedia has no
comments" as "this post's comment count is unknown", which is a different
claim. The union states what each platform actually has.

**Scorers are separate objects, not methods on `Source`.** `Source` is a
two-member Protocol and `score.py` documents itself as pure on purpose —
"reproducible and unit-testable, which an LLM's numeric judgment is not".
Putting scoring on sources would give each a second responsibility and
scatter the pure scoring logic across platform files, each one now mixing HTTP
with arithmetic. A parallel registry keeps both narrow.

**Titles only, no summaries.** A Wikipedia intro is evergreen, not topical:
the summary of an article explains a subject's biography, never why it spiked
that day. Fetching extracts would cost a request per article for background
that does not explain the trend.

**Corroboration-only sources cannot originate topics.** Following from the
above: with no body text, a Wikipedia-only topic is a bare title, giving the
sentiment stage nothing to judge and the caption writer nothing to work from.
Expressing this as a `content_bearing` property rather than a check for
`platform == "wikipedia"` means future attention-measuring sources — Google
Trends, if its API ever stabilises — need no change here.

**Rank-relative normalisation rather than magnitude calibration.** The
deferred problem was that Reddit's scores dwarf Lemmy's. Calibrating between
them requires per-platform constants that drift as platforms grow. Scoring
each platform against itself removes the question rather than answering it.
