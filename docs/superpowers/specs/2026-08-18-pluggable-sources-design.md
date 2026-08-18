# Pluggable Sources — Lemmy Ingestion and Source Toggling

**Date:** 2026-08-18
**Status:** Draft

## Purpose

Reddit's Data API is no longer self-serve. Reddit's
[Responsible Builder Policy](https://support.reddithelp.com/hc/en-us/articles/42728983564564-Responsible-Builder-Policy)
now states that "approval is required" before accessing any Reddit data
through the API, and the non-commercial signup route is a support ticket
reviewed against criteria a meme generator does not meet: the form asks what
benefit the app brings *Redditors and moderators*, and what is missing from
Devvit that prevents building on-platform.

Verified on 2026-08-18: `www.reddit.com/*.json` returns 403, `old.reddit.com`
redirects to login, and the HTML listing serves a JavaScript bot-challenge
rather than content. There is no free path to live Reddit engagement metrics.

This spec keeps `RedditSource` intact and working for if or when access is
granted, adds Lemmy as a second platform, and makes the enabled set
configurable so Reddit can be switched off without deleting it.

## Scope

- A `SOURCES` config toggle selecting which platforms run.
- `LemmySource`, a second implementation of the existing `Source` protocol.
- `CompositeSource`, aggregating enabled sources behind that same protocol.
- Making Reddit credentials optional, required only when Reddit is enabled.
- Updating `README.md` and `.env.example`, which currently instruct the reader
  to create a Reddit script app at `/prefs/apps` — a route that no longer
  exists. The setup section must describe Lemmy as the default and explain
  that Reddit needs approved API access.

### Out of scope

- Changes to any pipeline stage after ingestion. `run_pipeline` takes a single
  `Source` and keeps doing so.
- Applying for Reddit Data API access. Tracked by the user outside this spec.
- Cross-platform score normalisation. See "Deferred" below.
- Further platforms (Hacker News, Mastodon, Bluesky). The registry makes each
  a new file, exactly as `sources/base.py` promises.

## Architecture

```
Settings.sources ──► build_source() ──► CompositeSource ──► run_pipeline
                          │                    │
                          │                    ├── LemmySource
                          └── registry         └── RedditSource (disabled)
```

`CompositeSource` implements `Source`, so the pipeline signature is unchanged.
With one source enabled it is a thin pass-through; the fan-out only matters
once a second source is switched on.

The protocol requires a `name`. `CompositeSource.name` is the comma-joined
names of its children (`"lemmy"`, or `"lemmy,reddit"`), so a log line names
what actually ran. `Post.platform` is set by each child, so provenance
survives aggregation regardless.

## Configuration

New keys in `.env.example`:

```
SOURCES=lemmy
LEMMY_INSTANCE=https://lemmy.world
LEMMY_INCLUDE_NSFW=false
```

`Settings` changes:

| Field | Type | Default | Notes |
|---|---|---|---|
| `sources` | `list[str]` | `["lemmy"]` | Comma-split, reusing the `_split_subreddits` validator style |
| `lemmy_instance` | `str` | `https://lemmy.world` | Base URL, no trailing slash |
| `lemmy_include_nsfw` | `bool` | `False` | Passed through as the API's `show_nsfw` param |
| `reddit_client_id` | `str` | `""` | **Was required with no default** |
| `reddit_client_secret` | `str` | `""` | **Was required with no default** |

Making the Reddit credentials optional is load-bearing, not cosmetic: today
`reddit_client_id: str` has no default, so pydantic-settings rejects any
config lacking it and the CLI cannot start at all without Reddit credentials.
Disabling Reddit is impossible until this changes.

A `model_validator(mode="after")` on `Settings` enforces two rules, so bad
config fails at startup with a named cause rather than mid-run:

1. Every name in `sources` is a known source; otherwise list the valid names.
2. If `reddit` is enabled, both credentials are non-empty; otherwise name the
   missing variables and point at the Reddit access requirement.

## Source registry

A dict in `zeitgeist/sources/__init__.py` maps a config name to a builder:

```python
BUILDERS: dict[str, Callable[[Settings], Source]] = {
    "reddit": RedditSource.from_settings,
    "lemmy": LemmySource.from_settings,
}

def build_source(settings: Settings) -> Source:
    """Build the enabled sources and wrap them in a CompositeSource."""
```

`cli.py` calls `build_source(settings)` in place of the current hard-coded
`RedditSource.from_settings(settings)`. Adding a platform means writing one
file and adding one registry entry.

## LemmySource

Lemmy's API is public, unauthenticated, and needs no registration. Verified
against lemmy.world on 2026-08-18.

**Endpoint:** `GET {instance}/api/v3/post/list`

`/api/v4` returns 404 on lemmy.world; v3 is the live version.

**Parameters:** `type_=All`, `sort`, `limit`, `page`, `show_nsfw`.

**Listings.** Two sorts per run, mirroring the `hot`/`rising` pairing in
`RedditSource`:

- `Hot` — what is currently large.
- `Scaled` — Hot normalised by community size, so posts heating up in smaller
  communities surface. This is the closest analogue to Reddit's `rising`.

**Federation.** A `type_=All` query returns posts originating on other
instances (a lemmy.world response carried a post with `ap_id`
`https://lemmy.today/post/58566543`). One instance therefore already yields a
cross-instance firehose, and querying several would mostly duplicate. Hence a
single `LEMMY_INSTANCE` rather than a list.

**Firehose only.** No per-community configuration. `type_=All` is the `r/all`
analogue and is broad enough on its own; community targeting can be added
later if the topic mix disappoints.

**NSFW.** Anonymous requests exclude NSFW by default (0 of 50 posts), and
`show_nsfw=true` includes it (4 of 50). The config flag is passed straight
through to the API. No client-side filtering and no special casing: NSFW is a
broad category, and classifying that content is the sentiment stage's job via
the existing `GROSS`/`CRINGE` weights.

**Paging.** `limit` is capped at 50; `limit=100` returns
`{"error":"couldnt_get_posts"}`. Pages are 1-indexed and return distinct
results. Paginate each sort until the budget is met or a page comes back
empty.

**Deduplication.** Keyed on `ap_id`, the globally unique ActivityPub URL. Hot
and Scaled overlap heavily, as hot and rising do on Reddit.

**Field mapping** to `Post`:

| `Post` field | Lemmy source |
|---|---|
| `platform` | `"lemmy"` |
| `source_id` | `post.ap_id` |
| `title` | `post.name` |
| `body_excerpt` | `post.body`, trimmed to `BODY_EXCERPT_CHARS`, `None` if empty |
| `permalink` | `post.ap_id` (already a resolvable URL) |
| `score` | `counts.score` |
| `comment_count` | `counts.comments` |
| `created_at` | `post.published`, ISO-8601 parsed to an aware UTC datetime |
| `channel` | `name@host`, host taken from `community.actor_id` |

`channel` is qualified because a bare community name collides across federated
instances, and `channel_spread` in `analysis/score.py` counts distinct
channels — unqualified names would undercount the spread.

Lemmy returns `published` as `2026-08-18T07:15:08.419620Z`. Timestamps are
parsed to timezone-aware UTC: `Post.created_at` feeds `_mean_velocity`, which
subtracts it from an aware `now`, so a naive datetime would raise at scoring
time rather than at ingestion.

**Structure.** Network I/O stays separate from mapping, following the split
`RedditSource.fetch` already uses: the HTTP call is wrapped in try/except, a
module-level `_to_post` is pure. A mapping bug must crash rather than be
misreported as an unreachable instance. `httpx` is already a dependency; the
client is injectable for testing.

## Failure behaviour

`CompositeSource` isolates per-source failure the way `RedditSource` already
isolates per-subreddit failure: one source raising logs a warning and the run
continues on the others. Only "every source failed or returned nothing" raises
`SourceError`, which `cli.py` already handles.

The `limit` budget divides evenly across enabled sources, using the same
`math.ceil` approach as `RedditSource`. A source that under-delivers does not
have its shortfall redistributed — a second pass to top up would double the
request count for a marginal gain.

## Testing

Mirrors `tests/test_sources_reddit.py`: a stub client, no network, in a new
`tests/test_sources_lemmy.py` plus `tests/test_sources_composite.py`.

- Field mapping, including `channel` qualification and empty-body → `None`.
- Deduplication of a post appearing in both Hot and Scaled.
- Pagination stops on an empty page and respects the budget.
- `show_nsfw` reflects `lemmy_include_nsfw`.
- HTTP failure raises `SourceError`; a malformed payload crashes.
- Composite: one failing source does not abort the run; all failing raises.
- Config: unknown source name rejected; `reddit` enabled without credentials
  rejected; `reddit` disabled with no credentials accepted.

## Deferred

**Cross-platform score normalisation.** `_mean_velocity` in
`analysis/score.py` averages raw score-per-hour across a topic's posts.
Reddit scores run in the thousands and Lemmy's in the tens, so once both
sources are enabled, a topic's velocity becomes largely a measure of how much
Reddit it contains, and mixed-platform topics outrank single-platform ones for
that reason rather than on merit.

This is harmless while Lemmy runs alone and is deliberately deferred. It must
be addressed before Reddit is re-enabled alongside another source, not after —
the failure is silent and shows up as subtly wrong rankings, not an error.

## Decisions and rationale

- **Reddit code stays.** It is tested and correct; only its credentials are
  unobtainable. Keeping it means re-enabling is a config change.
- **Composite over a pipeline change.** Wrapping many sources in one `Source`
  keeps `run_pipeline` and every stage after it untouched.
- **Lemmy over Hacker News.** Lemmy maps almost one-to-one onto the existing
  model — communities are channels, and Hot/Scaled pair like hot/rising.
  Hacker News has no channel concept, so `channel_spread` would collapse to
  zero variance and that weight would silently stop contributing.
- **Not scraping Reddit.** Beyond the policy prohibiting unapproved scraping,
  the listing HTML is behind an active bot-challenge; defeating it is both a
  policy violation and an unbounded maintenance cost for a hobby project.
