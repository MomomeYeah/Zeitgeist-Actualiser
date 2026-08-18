# Pluggable Sources Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the enabled platforms configurable, add Lemmy as a working source, and switch Reddit off without deleting it.

**Architecture:** A `SOURCES` config list selects platforms. A registry maps each name to a builder, and `CompositeSource` wraps the enabled set behind the existing `Source` protocol so `run_pipeline` is untouched. `RedditSource` stays exactly as it is; only its credentials become optional.

**Tech Stack:** Python 3.14, pydantic + pydantic-settings, httpx (already a dependency), pytest, uv, ruff.

**Spec:** `docs/superpowers/specs/2026-08-18-pluggable-sources-design.md`

## Global Constraints

- Line length 88; ruff lint rules `E, F, I, UP, B, SIM`. Run `uv run ruff check .` and `uv run ruff format .` before every commit.
- No test may touch the network. Every source takes an injectable client.
- `zeitgeist/models.py` uses `extra="forbid"`. A misspelled `Post` field raises rather than being dropped — do not add fields to `Post`.
- Network I/O is wrapped in try/except; pure mapping is not. A mapping bug must crash, never be logged as an unreachable platform. This is the pattern already in `RedditSource.fetch` (commit 08ba833) and it is deliberate.
- Comments explain *why*, not *what*. Match the existing density — most functions have none; non-obvious decisions get a short block.
- Do not modify `zeitgeist/pipeline.py` or any analysis stage. Cross-platform score normalisation is explicitly deferred by the spec.

---

## File Structure

| File | Responsibility |
|---|---|
| `zeitgeist/config.py` (modify) | `KNOWN_SOURCES`, the `sources` list, Lemmy settings, optional Reddit credentials, startup validation |
| `zeitgeist/sources/lemmy.py` (create) | `LemmySource` — Lemmy v3 API ingestion and mapping to `Post` |
| `zeitgeist/sources/composite.py` (create) | `CompositeSource` — fans one fetch across many sources |
| `zeitgeist/sources/__init__.py` (modify) | `BUILDERS` registry and `build_source()` |
| `zeitgeist/cli.py` (modify) | Call `build_source` instead of hard-coding `RedditSource` |
| `tests/test_config.py` (modify) | Source selection and credential validation |
| `tests/test_sources_lemmy.py` (create) | Mapping, paging, dedup, NSFW, failure behaviour |
| `tests/test_sources_composite.py` (create) | Fan-out, isolation, registry wiring |
| `README.md`, `.env.example` (modify) | Setup no longer routes through `/prefs/apps` |

`zeitgeist/sources/reddit.py` is **not** modified.

---

### Task 1: Config — source selection and optional Reddit credentials

Nothing else can be built first: `reddit_client_id: str` currently has no default, so pydantic-settings rejects any config lacking it and the CLI cannot start without Reddit credentials.

**Files:**
- Modify: `zeitgeist/config.py:32-70`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `KNOWN_SOURCES: tuple[str, ...]` (module-level in `config.py`); `Settings.sources: list[str]`, `Settings.lemmy_instance: str`, `Settings.lemmy_include_nsfw: bool`; `Settings.reddit_client_id` / `reddit_client_secret` now default to `""`.

`KNOWN_SOURCES` lives in `config.py`, not in the registry, on purpose: `zeitgeist/sources/__init__.py` imports `Settings`, so importing the registry from `config.py` would be a circular import. Task 4 adds a test asserting the two never drift apart.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_config.py`. `_bare_settings` disables `.env` loading:
these tests assert what a *fresh checkout* does, so a developer's local
`.env` naming other sources must not decide whether they pass.

```python
def _bare_settings(**overrides) -> Settings:
    """No .env, no Reddit credentials — a fresh checkout's starting point."""
    return Settings(_env_file=None, anthropic_api_key="key", **overrides)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("lemmy", ["lemmy"]),
        ("lemmy,reddit", ["lemmy", "reddit"]),
        ("lemmy, reddit ", ["lemmy", "reddit"]),
        ("LEMMY,Reddit", ["lemmy", "reddit"]),
        (["lemmy"], ["lemmy"]),
    ],
)
def test_sources_parse_from_env_strings(raw, expected):
    """SOURCES arrives from .env as one string, and the names are registry
    keys, so case must not decide whether a platform runs.
    """
    assert _settings(sources=raw).sources == expected


def test_sources_defaults_to_lemmy_only():
    """Reddit's Data API needs approved access, so a fresh checkout must
    produce a working run without any credentials at all.
    """
    assert _bare_settings().sources == ["lemmy"]


def test_enabling_reddit_without_credentials_is_rejected():
    """The failure has to name the missing variables: 'validation error' on
    a field the user never set is not an actionable message.
    """
    with pytest.raises(ValueError) as err:
        _bare_settings(sources="reddit")
    message = str(err.value)
    assert "REDDIT_CLIENT_ID" in message
    assert "REDDIT_CLIENT_SECRET" in message


def test_enabling_reddit_with_credentials_is_accepted():
    settings = _settings(sources="lemmy,reddit")
    assert settings.sources == ["lemmy", "reddit"]


def test_unknown_source_is_rejected_with_the_valid_names():
    with pytest.raises(ValueError, match="mastodon"):
        _bare_settings(sources="mastodon")


def test_empty_sources_is_rejected():
    """An empty list would otherwise reach CompositeSource, which cannot
    build anything, and fail further from the cause.
    """
    with pytest.raises(ValueError, match="at least one"):
        _bare_settings(sources="")


def test_lemmy_settings_have_usable_defaults():
    settings = _bare_settings()
    assert settings.lemmy_instance == "https://lemmy.world"
    assert settings.lemmy_include_nsfw is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_config.py -v`

Expected: FAIL. The `sources` tests error with pydantic `extra_forbidden`/unexpected-keyword or `AttributeError`, and `test_sources_defaults_to_lemmy_only` fails because `Settings(anthropic_api_key="key")` raises a missing-field error for `reddit_client_id`.

- [ ] **Step 3: Add the constant and widen the imports**

In `zeitgeist/config.py`, change the pydantic import line and add the constant below `PACKAGE_ROOT`:

```python
from pydantic import field_validator, model_validator
```

```python
# Registry keys live here rather than in zeitgeist/sources/__init__.py:
# that module imports Settings, so importing it back would be a cycle.
# tests/test_sources_composite.py guards the two against drifting.
KNOWN_SOURCES: tuple[str, ...] = ("lemmy", "reddit")
```

- [ ] **Step 4: Make the Reddit credentials optional and add the new fields**

Replace the credential and list fields inside `Settings`:

```python
    reddit_client_id: str = ""
    reddit_client_secret: str = ""
    reddit_user_agent: str = "zeitgeist-actualiser/0.1 (by u/anonymous)"

    lemmy_instance: str = "https://lemmy.world"
    lemmy_include_nsfw: bool = False
```

and add `sources` alongside `subreddits`:

```python
    sources: list[str] = ["lemmy"]
    subreddits: list[str] = []
```

- [ ] **Step 5: Share the CSV splitter and add the startup validator**

Rename `_split_subreddits` to `_split_csv` and point it at both fields:

```python
    @field_validator("subreddits", "sources", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return value

    @model_validator(mode="after")
    def _check_sources(self) -> Settings:
        """Reject an unusable source selection at startup rather than after
        the pipeline has already created a run directory.
        """
        self.sources = [name.lower() for name in self.sources]
        valid = ", ".join(KNOWN_SOURCES)
        if not self.sources:
            raise ValueError(f"SOURCES is empty; enable at least one of: {valid}")

        unknown = [name for name in self.sources if name not in KNOWN_SOURCES]
        if unknown:
            raise ValueError(f"Unknown source(s): {', '.join(unknown)}. Valid: {valid}")

        if "reddit" in self.sources:
            missing = [
                name
                for name, value in (
                    ("REDDIT_CLIENT_ID", self.reddit_client_id),
                    ("REDDIT_CLIENT_SECRET", self.reddit_client_secret),
                )
                if not value
            ]
            if missing:
                raise ValueError(
                    f"{' and '.join(missing)} must be set when 'reddit' is in "
                    "SOURCES. Reddit's Data API requires approved access; drop "
                    "'reddit' from SOURCES to run without it."
                )
        return self
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/test_config.py -v`
Expected: PASS, including the pre-existing subreddit and sentiment-weight tests.

- [ ] **Step 7: Run the whole suite**

Run: `uv run pytest`
Expected: PASS. Nothing else reads these fields yet.

- [ ] **Step 8: Lint and commit**

```bash
uv run ruff check . && uv run ruff format .
git add zeitgeist/config.py tests/test_config.py
git commit -m "feat: select enabled sources from config"
```

---

### Task 2: LemmySource

**Files:**
- Create: `zeitgeist/sources/lemmy.py`
- Test: `tests/test_sources_lemmy.py`

**Interfaces:**
- Consumes: `Settings.lemmy_instance`, `Settings.lemmy_include_nsfw` (Task 1); `Post` from `zeitgeist/models.py`; `SourceError` from `zeitgeist/sources/base.py`.
- Produces: `LemmySource(instance: str, include_nsfw: bool, client: Any)`, `LemmySource.from_settings(settings) -> LemmySource`, `LemmySource.name == "lemmy"`, `LemmySource.fetch(limit: int) -> list[Post]`, and module-level `_to_post(view: dict, fetched_at: datetime) -> Post`.

API facts verified against lemmy.world on 2026-08-18 — do not re-derive them:
`GET {instance}/api/v3/post/list` with `type_=All`, `sort`, `limit`, `page`, `show_nsfw`. `limit` above 50 returns `{"error":"couldnt_get_posts"}`. Pages are 1-indexed. `/api/v4` is 404. Anonymous requests exclude NSFW unless `show_nsfw=true`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_sources_lemmy.py`:

```python
import logging
from datetime import UTC, datetime
from unittest.mock import patch

import httpx
import pytest

from zeitgeist.config import Settings
from zeitgeist.sources.base import SourceError
from zeitgeist.sources.lemmy import LemmySource


# Safely in the past. A fixture dated "today" makes the
# `fetched_at > created_at` assertion pass or fail depending on the hour
# the suite happens to run.
PUBLISHED = "2026-01-15T09:00:00.123456Z"


def _view(ap_id, title, score=10, comments=2, community="cats", body=""):
    """Mirrors a real lemmy.world post view, including fields the mapper
    ignores. Captured from the live API on 2026-08-18.

    Trimming this to only what `_to_post` reads today would let a later
    change reference a field that was never in the test data — the tests
    would pass while the real payload broke.
    """
    return {
        "post": {
            "id": 50804462,
            "name": title,
            "url": "https://i.example.test/photo.jpeg",
            "body": body,
            "creator_id": 1234,
            "community_id": 99,
            "removed": False,
            "locked": False,
            "published": PUBLISHED,
            "deleted": False,
            "nsfw": False,
            "ap_id": f"https://lemmy.world/post/{ap_id}",
            "local": True,
            "language_id": 37,
            "featured_community": False,
            "featured_local": False,
            "url_content_type": "image/jpeg",
            "thumbnail_url": "https://lemmy.world/pictrs/image/abc.webp",
        },
        "creator": {"id": 1234, "name": "someone", "local": True},
        "community": {
            "id": 99,
            "name": community,
            "title": community.title(),
            "removed": False,
            "published": PUBLISHED,
            "deleted": False,
            "nsfw": False,
            "actor_id": f"https://lemmy.world/c/{community}",
            "local": True,
            "hidden": False,
            "posting_restricted_to_mods": False,
            "instance_id": 1,
            "visibility": "Public",
        },
        "counts": {
            "post_id": 50804462,
            "comments": comments,
            "score": score,
            "upvotes": score + 2,
            "downvotes": 2,
            "published": PUBLISHED,
            "newest_comment_time": PUBLISHED,
        },
        "subscribed": "NotSubscribed",
        "saved": False,
        "read": False,
        "hidden": False,
        "creator_banned_from_community": False,
        "banned_from_community": False,
        "creator_is_moderator": False,
        "creator_is_admin": False,
        "creator_blocked": False,
        "unread_comments": 0,
    }


class StubResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class StubClient:
    """Serves one canned page per (sort, page); anything unlisted is empty."""

    # Without the empty-page break, _fetch_sort loops forever: the suite
    # would hang rather than fail, and a hang names no cause. Turn it into
    # an assertion failure that does.
    RUNAWAY_CALLS = 20

    def __init__(self, pages):
        self._pages = pages
        self.calls = []
        self.urls = []

    def get(self, url, params):
        if len(self.calls) >= self.RUNAWAY_CALLS:
            raise AssertionError(
                "runaway paging: _fetch_sort never breaks on an empty page"
            )
        self.calls.append(params)
        self.urls.append(url)
        page = self._pages.get((params["sort"], params["page"]), [])
        return StubResponse({"posts": page})


class FailingClient:
    def get(self, url, params):
        raise httpx.ConnectError("connection refused")


def _source(pages, include_nsfw=False):
    return LemmySource(
        instance="https://lemmy.world",
        include_nsfw=include_nsfw,
        client=StubClient(pages),
    )


def test_maps_views_onto_posts():
    """Every downstream stage reads these fields. A crossed assignment —
    comments into score, or published into fetched_at — would skew every
    velocity calculation while breaking nothing visibly.
    """
    pages = {("Hot", 1): [_view("a1", "Cat opens door", score=99, comments=7)]}
    post = _source(pages).fetch(limit=10)[0]

    assert post.platform == "lemmy"
    assert post.source_id == "https://lemmy.world/post/a1"
    assert post.title == "Cat opens door"
    assert post.score == 99
    assert post.comment_count == 7
    assert post.permalink == "https://lemmy.world/post/a1"
    assert post.created_at == datetime(2026, 1, 15, 9, 0, 0, 123456, tzinfo=UTC)
    assert post.fetched_at > post.created_at


def test_channel_is_qualified_by_instance_host():
    """A bare community name collides across federated instances, and
    channel_spread in the scorer counts distinct channels — unqualified
    names would undercount the spread.
    """
    pages = {("Hot", 1): [_view("a1", "T", community="memes")]}
    assert _source(pages).fetch(limit=10)[0].channel == "memes@lemmy.world"


def test_created_at_is_timezone_aware_when_the_instance_omits_the_zone():
    """The scorer subtracts created_at from an aware `now`; a naive value
    would raise there instead of here.
    """
    view = _view("a1", "T")
    view["post"]["published"] = "2026-01-15T09:00:00"
    post = _source({("Hot", 1): [view]}).fetch(limit=10)[0]
    assert post.created_at == datetime(2026, 1, 15, 9, 0, tzinfo=UTC)


def test_deduplicates_across_hot_and_scaled():
    """The two listings overlap heavily, as hot and rising do on Reddit."""
    same = _view("a1", "Same post")
    pages = {("Hot", 1): [same], ("Scaled", 1): [same]}
    assert len(_source(pages).fetch(limit=10)) == 1


def test_pulls_from_both_listings():
    pages = {("Hot", 1): [_view("a1", "Hot")], ("Scaled", 1): [_view("s1", "Rising")]}
    ids = {post.source_id for post in _source(pages).fetch(limit=10)}
    assert ids == {"https://lemmy.world/post/a1", "https://lemmy.world/post/s1"}


def test_pages_until_the_budget_is_met():
    """limit=120 is 60 per listing, so each must page past the 50-post cap.
    A source that stopped at page 1 would silently return 100.
    """
    pages = {
        ("Hot", 1): [_view(f"h{n}", f"T{n}") for n in range(50)],
        ("Hot", 2): [_view(f"i{n}", f"U{n}") for n in range(50)],
        ("Scaled", 1): [_view(f"s{n}", f"V{n}") for n in range(50)],
        ("Scaled", 2): [_view(f"t{n}", f"W{n}") for n in range(50)],
    }
    source = _source(pages)
    posts = source.fetch(limit=120)
    assert len(posts) == 120
    assert 2 in {params["page"] for params in source._client.calls}


def test_stops_paging_on_an_empty_page():
    """A listing shorter than the budget must end the loop, not keep asking.
    Exact counts, hand-derived: Hot serves one post then an empty page (2
    calls), Scaled is empty from the start (1 call).
    """
    source = _source({("Hot", 1): [_view("a1", "Only one")]})
    posts = source.fetch(limit=500)
    assert len(posts) == 1
    assert len(source._client.calls) == 3


def test_requests_go_to_the_configured_instance():
    """The instance is the one piece of config that decides which network
    is scraped; a dropped or double-slashed base URL is invisible until a
    real request is made.
    """
    source = LemmySource(
        instance="https://sh.itjust.works/",
        client=StubClient({("Hot", 1): [_view("a1", "T")]}),
    )
    source.fetch(limit=1)
    assert source._client.urls[0] == "https://sh.itjust.works/api/v3/post/list"


def test_from_settings_wires_config_into_the_request():
    """from_settings is plumbing, so it fails silently: a dropped
    include_nsfw or a mis-assigned instance only shows up in the request.
    """
    settings = Settings(
        _env_file=None,
        anthropic_api_key="key",
        sources="lemmy",
        lemmy_instance="https://lemmy.ml",
        lemmy_include_nsfw=True,
    )
    source = LemmySource.from_settings(settings)
    source._client = StubClient({("Hot", 1): [_view("a1", "T")]})
    source.fetch(limit=1)

    assert source._client.urls[0] == "https://lemmy.ml/api/v3/post/list"
    assert source._client.calls[0]["show_nsfw"] == "true"


def test_respects_the_limit():
    """Both listings are seeded: the per-listing budget is a real cap, so a
    single populated listing could not reach the limit on its own.
    """
    pages = {
        ("Hot", 1): [_view(f"h{n}", f"T{n}") for n in range(50)],
        ("Scaled", 1): [_view(f"s{n}", f"U{n}") for n in range(50)],
    }
    assert len(_source(pages).fetch(limit=5)) == 5


def test_budget_split_holds_even_when_a_page_overshoots_it():
    """60 is not a multiple of 50, so each listing's second page overshoots
    its share by 10. Without a per-listing cap, a well-stocked Hot would
    consume that overshoot into the global limit before Scaled is asked for
    its share — crowding out the rising signal Scaled exists to surface.
    """
    pages = {
        ("Hot", 1): [_view(f"h{n}", f"T{n}") for n in range(50)],
        ("Hot", 2): [_view(f"h{n}", f"T{n}") for n in range(50, 100)],
        ("Scaled", 1): [_view(f"s{n}", f"V{n}") for n in range(50)],
        ("Scaled", 2): [_view(f"s{n}", f"V{n}") for n in range(50, 100)],
    }
    posts = _source(pages).fetch(limit=120)
    from_hot = sum(1 for post in posts if "/post/h" in post.source_id)
    from_scaled = sum(1 for post in posts if "/post/s" in post.source_id)
    assert (from_hot, from_scaled) == (60, 60)


def test_requests_never_exceed_the_page_size_cap():
    """limit=100 returns {"error":"couldnt_get_posts"} from real instances."""
    source = _source({("Hot", 1): [_view("a1", "T")]})
    source.fetch(limit=500)
    assert all(params["limit"] <= 50 for params in source._client.calls)


@pytest.mark.parametrize("include,expected", [(True, "true"), (False, "false")])
def test_nsfw_flag_is_passed_through_to_the_api(include, expected):
    """Anonymous requests exclude NSFW by default; the toggle is the API's
    own parameter, not client-side filtering.
    """
    source = _source({("Hot", 1): [_view("a1", "T")]}, include_nsfw=include)
    source.fetch(limit=1)
    assert source._client.calls[0]["show_nsfw"] == expected


@pytest.mark.parametrize("body", ["", "   ", "\n\t "])
def test_blank_body_becomes_none_rather_than_empty_string(body):
    """Link posts have no body. An empty string would put a pointless
    'Body:' line into every extraction prompt.
    """
    pages = {("Hot", 1): [_view("a1", "T", body=body)]}
    assert _source(pages).fetch(limit=10)[0].body_excerpt is None


def test_truncates_long_body_to_the_leading_excerpt():
    body = "".join(str(n % 10) for n in range(900))
    pages = {("Hot", 1): [_view("a1", "T", body=body)]}
    assert _source(pages).fetch(limit=10)[0].body_excerpt == body[:500]


def test_no_posts_raises_source_error():
    with pytest.raises(SourceError, match="no posts"):
        _source({}).fetch(limit=10)


def test_network_failure_raises_source_error():
    source = LemmySource(instance="https://lemmy.world", client=FailingClient())
    with pytest.raises(SourceError, match="no posts"):
        source.fetch(limit=10)


def test_one_failing_listing_still_yields_the_other(caplog):
    """Mirrors the per-subreddit isolation in RedditSource: Stage A is fatal
    only when nothing worked.
    """

    class HalfFailingClient(StubClient):
        def get(self, url, params):
            if params["sort"] == "Hot":
                raise httpx.ConnectError("connection refused")
            return super().get(url, params)

    source = LemmySource(
        instance="https://lemmy.world",
        client=HalfFailingClient({("Scaled", 1): [_view("s1", "Survived")]}),
    )
    with caplog.at_level(logging.WARNING):
        posts = source.fetch(limit=10)

    assert [post.source_id for post in posts] == ["https://lemmy.world/post/s1"]
    assert "Hot" in caplog.text


def test_malformed_payload_crashes_rather_than_looking_like_an_outage():
    """A response missing 'posts' is a contract change, not a network blip.
    Reporting it as an unreachable instance would hide it behind a warning.
    """

    class MalformedClient:
        def get(self, url, params):
            return StubResponse({"unexpected": []})

    source = LemmySource(instance="https://lemmy.world", client=MalformedClient())
    with pytest.raises(KeyError):
        source.fetch(limit=10)


def test_mapping_bug_in_to_post_propagates_not_swallowed():
    """A genuine bug in the mapping path must crash loudly, not be caught,
    logged as a listing skip, and silently return fewer posts.
    """
    source = _source({("Hot", 1): [_view("a1", "T")]})
    with patch("zeitgeist.sources.lemmy._to_post") as mock_to_post:
        mock_to_post.side_effect = ValueError("simulated mapping bug")
        with pytest.raises(ValueError, match="simulated mapping bug"):
            source.fetch(limit=10)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_sources_lemmy.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'zeitgeist.sources.lemmy'`.

- [ ] **Step 3: Write the implementation**

Create `zeitgeist/sources/lemmy.py`:

```python
"""Lemmy ingestion via the public v3 API.

Needs no credentials: Lemmy's API is open and unauthenticated. Pulls `Hot`
(what is currently large) and `Scaled` (Hot normalised by community size, so
posts climbing in smaller communities surface), mirroring the hot/rising pair
the Reddit source uses.
"""

import logging
import math
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

import httpx

from zeitgeist.config import Settings
from zeitgeist.models import Post
from zeitgeist.sources.base import SourceError

log = logging.getLogger(__name__)

BODY_EXCERPT_CHARS = 500
# Instances reject anything larger: limit=100 returns couldnt_get_posts.
PAGE_SIZE = 50
SORTS = ("Hot", "Scaled")
TIMEOUT_SECONDS = 30.0


class LemmySource:
    name = "lemmy"

    def __init__(
        self,
        instance: str = "https://lemmy.world",
        include_nsfw: bool = False,
        client: Any = None,
    ) -> None:
        self._instance = instance.rstrip("/")
        self._include_nsfw = include_nsfw
        self._client = client or httpx.Client(timeout=TIMEOUT_SECONDS)

    @classmethod
    def from_settings(cls, settings: Settings) -> LemmySource:
        return cls(
            instance=settings.lemmy_instance,
            include_nsfw=settings.lemmy_include_nsfw,
        )

    def fetch(self, limit: int) -> list[Post]:
        # Divide the budget across listings, not listing *pairs*: Hot and
        # Scaled overlap heavily, so halving again would undersample.
        per_sort = max(1, math.ceil(limit / len(SORTS)))
        fetched_at = datetime.now(UTC)

        seen: dict[str, Post] = {}
        for sort in SORTS:
            # Only transport failure is tolerated. A KeyError from a changed
            # payload propagates: that is a contract break, not an outage.
            try:
                views = self._fetch_sort(sort, per_sort)
            except httpx.HTTPError as exc:
                log.warning("Skipping Lemmy %s listing: %s", sort, exc)
                continue

            # Mapping is pure: a bug here must crash, not look like an
            # unreachable instance.
            for view in views:
                post = _to_post(view, fetched_at)
                if post.source_id in seen:
                    continue
                seen[post.source_id] = post
                if len(seen) >= limit:
                    return list(seen.values())

        if not seen:
            raise SourceError("Lemmy returned no posts")
        return list(seen.values())

    def _fetch_sort(self, sort: str, budget: int) -> list[dict[str, Any]]:
        """Page through one listing until the budget is met or it runs dry."""
        collected: list[dict[str, Any]] = []
        page = 1
        while len(collected) < budget:
            response = self._client.get(
                f"{self._instance}/api/v3/post/list",
                params={
                    "type_": "All",
                    "sort": sort,
                    "limit": PAGE_SIZE,
                    "page": page,
                    "show_nsfw": "true" if self._include_nsfw else "false",
                },
            )
            response.raise_for_status()
            views = response.json()["posts"]
            # A short page means the listing is exhausted; without this the
            # loop would keep requesting until the budget was met.
            if not views:
                break
            collected.extend(views)
            page += 1
        return collected[:budget]


def _to_post(view: dict[str, Any], fetched_at: datetime) -> Post:
    post = view["post"]
    counts = view["counts"]
    body = (post.get("body") or "").strip()
    return Post(
        platform="lemmy",
        source_id=post["ap_id"],
        title=post["name"],
        body_excerpt=body[:BODY_EXCERPT_CHARS] or None,
        # ap_id is the canonical URL of the post on its home instance.
        permalink=post["ap_id"],
        score=counts["score"],
        comment_count=counts["comments"],
        created_at=_parse_published(post["published"]),
        fetched_at=fetched_at,
        channel=_channel(view["community"]),
    )


def _channel(community: dict[str, Any]) -> str:
    """`name@host`. Community names collide across federated instances, and
    channel_spread counts distinct channels, so bare names would undercount.
    """
    host = urlsplit(community["actor_id"]).netloc
    return f"{community['name']}@{host}"


def _parse_published(raw: str) -> datetime:
    """Instances send `2026-08-18T09:00:00.123456Z`; some omit the zone.
    The scorer subtracts this from an aware `now`, so a naive value would
    raise three stages later rather than here.
    """
    parsed = datetime.fromisoformat(raw)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_sources_lemmy.py -v`
Expected: PASS, all tests.

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check . && uv run ruff format .
git add zeitgeist/sources/lemmy.py tests/test_sources_lemmy.py
git commit -m "feat: add Lemmy source"
```

---

### Task 3: CompositeSource

**Files:**
- Create: `zeitgeist/sources/composite.py`
- Test: `tests/test_sources_composite.py`

**Interfaces:**
- Consumes: `Source` and `SourceError` from `zeitgeist/sources/base.py`; `Post` from `zeitgeist/models.py`.
- Produces: `CompositeSource(sources: list[Source])`, `CompositeSource.name` (comma-joined child names), `CompositeSource.fetch(limit: int) -> list[Post]`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_sources_composite.py`:

```python
import logging
from datetime import UTC, datetime

import pytest

from zeitgeist.models import Post
from zeitgeist.sources.base import SourceError
from zeitgeist.sources.composite import CompositeSource


def _post(platform, source_id, channel="cats"):
    return Post(
        platform=platform,
        source_id=source_id,
        title=f"Title {source_id}",
        permalink=f"https://example.test/{source_id}",
        score=10,
        comment_count=2,
        created_at=datetime(2026, 8, 18, 9, 0, tzinfo=UTC),
        fetched_at=datetime(2026, 8, 18, 12, 0, tzinfo=UTC),
        channel=channel,
    )


class StubSource:
    def __init__(self, name, posts):
        self.name = name
        self._posts = posts
        self.requested_limit = None

    def fetch(self, limit):
        self.requested_limit = limit
        return self._posts[:limit]


class FailingSource:
    name = "broken"

    def fetch(self, limit):
        raise SourceError("platform unreachable")


def test_combines_posts_from_every_source():
    composite = CompositeSource(
        [
            StubSource("lemmy", [_post("lemmy", "l1")]),
            StubSource("reddit", [_post("reddit", "r1")]),
        ]
    )
    platforms = {post.platform for post in composite.fetch(limit=10)}
    assert platforms == {"lemmy", "reddit"}


def test_divides_the_budget_across_sources():
    """A single source must not spend the whole POST_LIMIT and starve the
    others of their share.
    """
    first = StubSource("lemmy", [_post("lemmy", f"l{n}") for n in range(20)])
    second = StubSource("reddit", [_post("reddit", f"r{n}") for n in range(20)])
    CompositeSource([first, second]).fetch(limit=10)
    assert first.requested_limit == 5
    assert second.requested_limit == 5


def test_respects_the_limit():
    sources = [
        StubSource("lemmy", [_post("lemmy", f"l{n}") for n in range(20)]),
        StubSource("reddit", [_post("reddit", f"r{n}") for n in range(20)]),
    ]
    assert len(CompositeSource(sources).fetch(limit=6)) == 6


def test_same_id_on_different_platforms_is_not_a_duplicate():
    """source_id is only unique within a platform: Lemmy uses URLs and
    Reddit uses short base36 ids, but nothing guarantees they never collide.
    """
    sources = [
        StubSource("lemmy", [_post("lemmy", "shared")]),
        StubSource("reddit", [_post("reddit", "shared")]),
    ]
    assert len(CompositeSource(sources).fetch(limit=10)) == 2


def test_a_failing_source_is_skipped_and_others_still_yield_posts(caplog):
    """One platform being down must not lose the other's posts — the same
    isolation RedditSource applies per subreddit.
    """
    composite = CompositeSource(
        [FailingSource(), StubSource("lemmy", [_post("lemmy", "l1")])]
    )
    with caplog.at_level(logging.WARNING):
        posts = composite.fetch(limit=10)

    assert [post.source_id for post in posts] == ["l1"]
    assert "broken" in caplog.text


def test_all_sources_failing_raises_source_error():
    with pytest.raises(SourceError, match="No source"):
        CompositeSource([FailingSource(), FailingSource()]).fetch(limit=10)


def test_every_source_returning_nothing_raises_source_error():
    with pytest.raises(SourceError, match="No source"):
        CompositeSource([StubSource("lemmy", [])]).fetch(limit=10)


def test_building_with_no_sources_is_rejected():
    with pytest.raises(ValueError, match="at least one"):
        CompositeSource([])
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_sources_composite.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'zeitgeist.sources.composite'`.

- [ ] **Step 3: Write the implementation**

Create `zeitgeist/sources/composite.py`:

```python
"""Fans one fetch out across every enabled source.

Implements Source itself, so the pipeline stays single-source: adding a
platform never changes run_pipeline.
"""

import logging
import math

from zeitgeist.models import Post
from zeitgeist.sources.base import Source, SourceError

log = logging.getLogger(__name__)


class CompositeSource:
    def __init__(self, sources: list[Source]) -> None:
        if not sources:
            raise ValueError("CompositeSource needs at least one source")
        self._sources = sources
        # Names what actually ran, so a log line distinguishes a Lemmy-only
        # run from a Lemmy+Reddit one.
        self.name = ",".join(source.name for source in sources)

    def fetch(self, limit: int) -> list[Post]:
        per_source = max(1, math.ceil(limit / len(self._sources)))

        # Keyed by platform as well as id: source_id is only unique within a
        # platform, and a shortfall is not redistributed — a second pass to
        # top up would double the request count for a marginal gain.
        seen: dict[tuple[str, str], Post] = {}
        for source in self._sources:
            # A source can raise anything its client library defines, so the
            # guard is broad. One platform down must not lose the others.
            try:
                posts = source.fetch(limit=per_source)
            except Exception as exc:
                log.warning("Skipping source %s: %s", source.name, exc)
                continue

            for post in posts:
                key = (post.platform, post.source_id)
                if key in seen:
                    continue
                seen[key] = post
                if len(seen) >= limit:
                    return list(seen.values())

        if not seen:
            raise SourceError("No source returned any posts")
        return list(seen.values())
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_sources_composite.py -v`
Expected: PASS, all tests.

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check . && uv run ruff format .
git add zeitgeist/sources/composite.py tests/test_sources_composite.py
git commit -m "feat: aggregate enabled sources behind one Source"
```

---

### Task 4: Registry and CLI wiring

This is the task that actually switches Reddit off. Until now nothing reads `Settings.sources`.

**Files:**
- Modify: `zeitgeist/sources/__init__.py` (currently empty)
- Modify: `zeitgeist/cli.py:12` (import) and `zeitgeist/cli.py:92` (the `source=` argument)
- Modify: `tests/test_sources_composite.py` (append), `tests/test_cli.py:47-53`

**Interfaces:**
- Consumes: `KNOWN_SOURCES` and `Settings` (Task 1), `LemmySource` (Task 2), `CompositeSource` (Task 3), `RedditSource` (unchanged).
- Produces: `BUILDERS: dict[str, Callable[[Settings], Source]]` and `build_source(settings: Settings) -> Source` in `zeitgeist.sources`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_sources_composite.py`:

```python
from zeitgeist.config import KNOWN_SOURCES, Settings
from zeitgeist.sources import BUILDERS, build_source
from zeitgeist.sources.lemmy import LemmySource


def test_every_known_source_has_a_builder():
    """Settings validates SOURCES against KNOWN_SOURCES while build_source
    indexes BUILDERS. If they drift, a name accepted at startup raises a
    KeyError once the run is already under way.
    """
    assert set(BUILDERS) == set(KNOWN_SOURCES)


def test_build_source_builds_only_the_enabled_sources():
    """A disabled platform must not be constructed at all: RedditSource's
    __init__ builds a praw client, so building it anyway would demand
    credentials the user was told they do not need.
    """
    # _env_file=None so a local .env enabling reddit cannot change the result.
    settings = Settings(_env_file=None, anthropic_api_key="key", sources="lemmy")
    assert [type(source) for source in build_source(settings)._sources] == [LemmySource]


def test_build_source_preserves_the_configured_order():
    """The budget is split per source in order, so a registry that reordered
    them would silently change which platform gets the remainder.
    """
    settings = Settings(
        _env_file=None,
        anthropic_api_key="key",
        reddit_client_id="id",
        reddit_client_secret="secret",
        sources="lemmy,reddit",
    )
    names = [source.name for source in build_source(settings)._sources]
    assert names == ["lemmy", "reddit"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_sources_composite.py -v`
Expected: FAIL — `ImportError: cannot import name 'BUILDERS' from 'zeitgeist.sources'`.

- [ ] **Step 3: Write the registry**

Replace the empty `zeitgeist/sources/__init__.py`:

```python
"""Source registry. A new platform is a new file plus one entry here."""

from collections.abc import Callable

from zeitgeist.config import Settings
from zeitgeist.sources.base import Source
from zeitgeist.sources.composite import CompositeSource
from zeitgeist.sources.lemmy import LemmySource
from zeitgeist.sources.reddit import RedditSource

BUILDERS: dict[str, Callable[[Settings], Source]] = {
    "lemmy": LemmySource.from_settings,
    "reddit": RedditSource.from_settings,
}


def build_source(settings: Settings) -> Source:
    """Build every enabled source and wrap them in one Source.

    Settings has already rejected unknown names, so a KeyError here would
    mean BUILDERS and KNOWN_SOURCES had drifted apart.
    """
    return CompositeSource([BUILDERS[name](settings) for name in settings.sources])
```

- [ ] **Step 4: Wire the CLI**

In `zeitgeist/cli.py`, replace the import:

```python
from zeitgeist.sources import build_source
```

(delete `from zeitgeist.sources.reddit import RedditSource`), and inside `_run` replace the `source=` argument:

```python
                source=build_source(settings),
```

- [ ] **Step 5: Make the CLI test independent of the developer's .env**

In `tests/test_cli.py`, replace `_set_minimal_settings_env` so the test does not depend on whichever sources the developer has enabled locally:

```python
def _set_minimal_settings_env(monkeypatch, tmp_path):
    monkeypatch.setenv("SOURCES", "lemmy")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "key")
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "output"))
    monkeypatch.setenv("DB_PATH", str(tmp_path / "data" / "z.db"))
```

- [ ] **Step 6: Run the whole suite**

Run: `uv run pytest`
Expected: PASS, every test in every file.

- [ ] **Step 7: Verify Reddit is genuinely optional end to end**

Run:

```bash
uv run python -c "from zeitgeist.config import Settings; from zeitgeist.sources import build_source; s = Settings(anthropic_api_key='k', sources='lemmy'); print(build_source(s).name)"
```

Expected: prints `lemmy`, with no Reddit credentials set anywhere. If this raises a validation error, Task 1 Step 4 was not applied.

- [ ] **Step 8: Lint and commit**

```bash
uv run ruff check . && uv run ruff format .
git add zeitgeist/sources/__init__.py zeitgeist/cli.py tests/test_sources_composite.py tests/test_cli.py
git commit -m "feat: build sources from config instead of hard-coding Reddit"
```

---

### Task 5: Documentation

`README.md` currently tells the reader to create a script app at `https://www.reddit.com/prefs/apps`, a route that no longer grants access. Leaving it is worse than no instructions: it sends a new user down a path that dead-ends.

**Files:**
- Modify: `.env.example`
- Modify: `README.md:12-24` (the Setup section)

**Interfaces:**
- Consumes: the config keys from Task 1. No code changes.

- [ ] **Step 1: Rewrite `.env.example`**

```
SOURCES=lemmy

LEMMY_INSTANCE=https://lemmy.world
LEMMY_INCLUDE_NSFW=false

# Only needed if you add `reddit` to SOURCES, which requires approved
# access to Reddit's Data API.
REDDIT_CLIENT_ID=
REDDIT_CLIENT_SECRET=
REDDIT_USER_AGENT=zeitgeist-actualiser/0.1 (by u/yourname)
SUBREDDITS=aww,mildlyinteresting,nextfuckinglevel

ANTHROPIC_API_KEY=sk-ant-...

LLM_PROVIDER=anthropic
LLM_MODEL=claude-sonnet-5
OLLAMA_HOST=http://localhost:11434

POST_LIMIT=500
TOPIC_COUNT=5
```

- [ ] **Step 2: Replace the Setup credentials paragraph in `README.md`**

Replace the paragraph beginning "Fill in `.env`. Reddit credentials come from" with:

````markdown
Fill in `.env`. The only value you must supply is `ANTHROPIC_API_KEY` (or
switch to Ollama, below). `SOURCES` picks the platforms to scrape.

### Sources

`SOURCES=lemmy` is the default and needs no credentials — Lemmy's API is
public and unauthenticated. `LEMMY_INSTANCE` chooses the instance to query;
because instances federate, one already returns posts from across the
network. `LEMMY_INCLUDE_NSFW` maps to the API's own `show_nsfw` flag and is
off by default.

Reddit is implemented and tested but ships disabled. Reddit's
[Responsible Builder Policy](https://support.reddithelp.com/hc/en-us/articles/42728983564564-Responsible-Builder-Policy)
requires approved access before using the Data API, and the self-serve route
at `/prefs/apps` no longer issues credentials. If you are granted access, set
`REDDIT_CLIENT_ID` and `REDDIT_CLIENT_SECRET` and add it to the list:

```
SOURCES=lemmy,reddit
```

Enabling `reddit` without both credentials fails at startup with a message
naming the missing variables.
````

- [ ] **Step 3: Verify the documented default actually works**

Run:

```bash
uv run python -c "from zeitgeist.config import Settings; s = Settings(anthropic_api_key='k'); print(s.sources, s.lemmy_instance, s.lemmy_include_nsfw)"
```

Expected: `['lemmy'] https://lemmy.world False` — matching what the README and `.env.example` claim.

- [ ] **Step 4: Run the whole suite once more**

Run: `uv run pytest`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add README.md .env.example
git commit -m "docs: document source selection and Reddit's access requirement"
```

---

## Manual verification

The suite never touches the network, so one real run is worth doing once Task 5 is complete. This hits lemmy.world and costs LLM tokens:

```bash
uv run zeitgeist run --verbose
```

Expect `Fetched N posts` with N near `POST_LIMIT`, then output in `output/<run-id>/`. Inspect `posts.json` and confirm `platform` is `lemmy` throughout, `channel` values look like `name@instance`, and `score`/`comment_count` are non-zero and varied — all-zero scores would mean the mapping picked the wrong keys and every velocity would collapse.

## Deferred, not forgotten

The spec defers cross-platform score normalisation. `_mean_velocity` in `analysis/score.py` averages raw score-per-hour, and Reddit's scores run orders of magnitude above Lemmy's. Nothing in this plan addresses it because nothing needs to while Lemmy runs alone. **Do not enable a second source alongside Reddit without handling it first** — the symptom is subtly wrong rankings, not an error.
