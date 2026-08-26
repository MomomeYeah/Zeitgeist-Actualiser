"""BlueskySource fetches in three steps: getTrends, getFeed per trend, and
getPostThread per post.

The fake client routes on endpoint rather than replaying a queue, because the
three endpoints return different shapes and the source calls each of them
many times per run, concurrently under a semaphore.
"""

import asyncio
import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from zeitgeist.config import Settings
from zeitgeist.models import BlueskyMetrics, Item, TrendEvidence
from zeitgeist.sources.base import SourceError
from zeitgeist.sources.bluesky import BlueskySource

TREND_DID = "did:plc:trendingservice"
AUTHOR_DID = "did:plc:someauthor"

THREAD_VIEW = "app.bsky.feed.defs#threadViewPost"


def _metrics(item: Item) -> BlueskyMetrics:
    """Narrows `Item.metrics` from the platform union down to Bluesky's own
    shape, for ty: every field the tests below read is Bluesky-specific.
    """
    assert isinstance(item.metrics, BlueskyMetrics)
    return item.metrics


def _trend(rkey: str, name: str, status: str = "trending") -> dict:
    return {
        "topic": rkey,
        "displayName": name,
        "description": "a description",
        "link": f"/profile/{TREND_DID}/feed/{rkey}",
        "startedAt": "2026-08-23T04:00:00.000Z",
        "postCount": 100,
        "status": status,
        "category": "politics",
        "actors": [],
    }


def _post(
    rkey: str,
    text: str = "something happened",
    *,
    likes: int = 10,
    replies: int = 2,
    reposts: int = 3,
    indexed: str = "2026-08-23T10:00:00.000Z",
    created: str = "2026-08-23T09:59:59.000Z",
    langs: list[str] | None = None,
    labels: list[dict] | None = None,
    did: str = AUTHOR_DID,
) -> dict:
    record: dict = {
        "$type": "app.bsky.feed.post",
        "text": text,
        "createdAt": created,
    }
    if langs is not None:
        record["langs"] = langs
    return {
        "post": {
            "uri": f"at://{did}/app.bsky.feed.post/{rkey}",
            "cid": "bafyreiexample",
            # `author`, `quoteCount` and `bookmarkCount` are present because
            # the real postView always carries them, and deliberately never
            # read: no model in this project holds an author, and
            # tests/test_models.py guards that. Trimming a fixture to what
            # the code reads today lets a later change reference a field
            # that was never in the test data. `viewer` is deliberately
            # absent rather than trimmed: this source sends no credentials
            # (see the module docstring), and the live unauthenticated API
            # never returns a `viewer` block at all.
            "author": {
                "did": did,
                "handle": "someone.bsky.social",
                "displayName": "Someone",
                "avatar": "https://cdn.bsky.app/img/avatar/plain/abc@jpeg",
                "createdAt": "2024-01-01T00:00:00.000Z",
                "labels": [],
            },
            "record": record,
            "likeCount": likes,
            "replyCount": replies,
            "repostCount": reposts,
            "quoteCount": 0,
            "bookmarkCount": 0,
            "indexedAt": indexed,
            "labels": labels or [],
        }
    }


def _reply_node(
    text: str,
    *,
    did: str = "did:plc:replier",
    likes: int = 1,
    indexed: str = "2026-08-23T11:00:00.000Z",
    labels: list[dict] | None = None,
    children: list[dict] | None = None,
    node_type: str = THREAD_VIEW,
) -> dict:
    """Mirrors a real threadViewPost completely, including the fields the
    source never reads — same standard as `_post` above: `author` and
    `record.reply` are kept even though nothing here reads them, so a later
    change cannot reference a field that was never in the test data.
    `record.langs` is the live example: `_is_usable` already filters posts by
    language, and extending that to replies is an obvious next step
    (non-English replies pollute phrase mining). Written against a fixture
    with no `langs`, that change would pass its tests and drop real replies
    in production. `record.reply` is what distinguishes a reply from a root
    post, and is equally absent from a trimmed fixture. Unlike `_post`, this
    carries `author.associated` and omits `viewer`: both are genuinely what
    the live, unauthenticated `getPostThread` response looks like.
    """
    rkey = f"r-{abs(hash(text)) % 10**6}"
    parent_ref = {
        "cid": "bafyreiparentexample",
        "uri": "at://did:plc:someauthor/app.bsky.feed.post/p1",
    }
    return {
        "$type": node_type,
        "post": {
            "uri": f"at://{did}/app.bsky.feed.post/{rkey}",
            "cid": "bafyreiexample",
            "author": {
                "did": did,
                "handle": "replier.bsky.social",
                "displayName": "A Replier",
                "avatar": "https://cdn.bsky.app/img/avatar/plain/abc@jpeg",
                "associated": {"chat": {"allowIncoming": "all"}},
                "labels": [],
                "createdAt": "2024-01-01T00:00:00.000Z",
            },
            "record": {
                "$type": "app.bsky.feed.post",
                "text": text,
                "createdAt": "2026-08-23T10:59:58.000Z",
                "langs": ["en"],
                "reply": {"parent": parent_ref, "root": parent_ref},
            },
            "likeCount": likes,
            "replyCount": len(children or []),
            "repostCount": 0,
            "quoteCount": 0,
            "bookmarkCount": 0,
            "indexedAt": indexed,
            "labels": labels or [],
        },
        "replies": children or [],
        "threadContext": {},
    }


def _thread(*nodes: dict) -> dict:
    """`threadgate` is genuinely optional — observed present on one live
    thread and absent on another — so its absence here is accurate rather
    than trimmed.
    """
    return {
        "thread": {
            "$type": THREAD_VIEW,
            "post": _post("p1")["post"],
            "replies": list(nodes),
            "threadContext": {},
        }
    }


class _Response:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        # Plain HTTPError rather than HTTPStatusError: the latter requires
        # real Request and Response objects, and the source only ever
        # catches the base class.
        if self.status_code >= 400:
            raise httpx.HTTPError(f"status {self.status_code}")

    def json(self) -> dict:
        return self._payload


class _FakeAsyncClient:
    """Routes on endpoint. Each mapping value is a payload, an Exception to
    raise, or a list of payloads/Exceptions consumed one per call (used to
    exercise retry).
    """

    def __init__(
        self,
        trends: dict | Exception,
        feeds: Mapping[str, object],
        threads: Mapping[str, object] | None = None,
    ) -> None:
        self._trends = trends
        self._feeds = feeds
        self._threads = threads or {}
        self.calls: list[tuple[str, dict]] = []
        self.closed = False
        self.in_flight = 0
        self.max_in_flight = 0

    async def get(self, url: str, params: dict | None = None) -> _Response:
        params = params or {}
        self.calls.append((url, params))
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            # Yields control so overlapping requests actually overlap, which
            # is what makes max_in_flight meaningful.
            await asyncio.sleep(0)
            if "getTrends" in url:
                return _resolve(self._trends)
            if "getFeed" in url:
                rkey = str(params["feed"]).rsplit("/", 1)[-1]
                return _resolve(self._feeds[rkey])
            if "getPostThread" in url:
                rkey = str(params["uri"]).rsplit("/", 1)[-1]
                return _resolve(self._threads.get(rkey, _thread()))
            raise AssertionError(f"unexpected URL {url}")
        finally:
            self.in_flight -= 1

    async def aclose(self) -> None:
        self.closed = True


def _resolve(entry: object) -> _Response:
    """A mapping value may be a payload dict, an Exception, a prebuilt
    _Response (for status codes such as 429), or a list of those consumed
    one per call.
    """
    if isinstance(entry, list):
        entry = entry.pop(0)
    if isinstance(entry, Exception):
        raise entry
    if isinstance(entry, _Response):
        return entry
    assert isinstance(entry, dict)
    return _Response(entry)


def _settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "sources": ["bluesky"],
        "bluesky_trend_limit": 25,
        "bluesky_posts_per_trend": 10,
        "bluesky_fetch_concurrency": 8,
    }
    return Settings(**{**base, **overrides})


def _source(
    trends: dict | Exception,
    feeds: Mapping[str, object],
    threads: Mapping[str, object] | None = None,
) -> tuple[BlueskySource, _FakeAsyncClient]:
    client = _FakeAsyncClient(trends, feeds, threads)
    return BlueskySource(client_factory=lambda: client), client


def test_a_trend_keeps_every_field_the_api_returns():
    """The whole point of this change: `description` states the specific
    event and the old source discarded it. `status` and `startedAt` are
    asserted too — `_normalise_status` maps the former ("hot" is not a
    TrendStatus), and nothing else in this file would notice either being
    hard-coded or defaulted to now().
    """
    source, _ = _source(
        {"trends": [_trend("t1", "Canada announces retaliatory tariffs", "hot")]},
        {"t1": {"feed": [_post("p1")]}},
    )
    [evidence] = source.fetch_evidence(_settings())
    assert evidence.trend.display_name == "Canada announces retaliatory tariffs"
    assert evidence.trend.description == "a description"
    assert evidence.trend.category == "politics"
    assert evidence.trend.post_count == 100
    assert evidence.trend.topic_id == "t1"
    assert evidence.trend.status == "trending"
    assert evidence.trend.started_at == datetime(2026, 8, 23, 4, 0, tzinfo=UTC)


def test_the_trend_listing_is_requested_at_the_configured_limit():
    """The two fan-out settings are adjacent in the same call chain, so the
    posts-per-trend budget reaching getTrends is a live copy-paste risk.
    Distinct values here are what tell the two apart.
    """
    source, client = _source(
        {"trends": [_trend("t1", "A trend")]},
        {"t1": {"feed": [_post("p1")]}},
    )
    source.fetch_evidence(_settings(bluesky_trend_limit=7, bluesky_posts_per_trend=4))
    trend_calls = [params for url, params in client.calls if "getTrends" in url]
    assert trend_calls[0]["limit"] == 7


def test_feed_requests_never_exceed_the_api_page_cap():
    """getFeed rejects a limit above 100. Without the cap every feed call
    400s and the whole run looks like an outage — a bug this test was
    originally written for, now reachable by setting the value directly.
    """
    source, client = _source(
        {"trends": [_trend("t1", "A trend")]},
        {"t1": {"feed": [_post("p1")]}},
    )
    source.fetch_evidence(_settings(bluesky_posts_per_trend=500))
    feed_calls = [params for url, params in client.calls if "getFeed" in url]
    assert feed_calls[0]["limit"] == 100


@pytest.mark.parametrize("absent", ["description", "category"])
def test_a_trend_missing_an_optional_field_degrades_rather_than_crashing(absent):
    """getTrends is unspecced, so absence is legal. Every one of the 25 live
    trends currently carries both fields, so reading them as `trend[key]`
    would pass every manual check and raise KeyError the first time Bluesky
    omits one. The model default alone does not cover this: it never fires
    if the source subscripts the payload directly.
    """
    trend = _trend("t1", "A trend")
    del trend[absent]
    source, _ = _source({"trends": [trend]}, {"t1": {"feed": [_post("p1")]}})

    [evidence] = source.fetch_evidence(_settings())
    assert getattr(evidence.trend, absent) == ""


def test_reply_threads_are_requested_two_levels_deep():
    """A reply-to-a-reply is still people talking about the trend, and depth
    costs nothing — it is a parameter of the same single request. depth=0
    would silently halve the corpus that phrase mining runs on, and the fake
    ignores the parameter, so nothing else here would notice.
    """
    source, client = _source(
        {"trends": [_trend("t1", "A trend")]},
        {"t1": {"feed": [_post("p1")]}},
        {"p1": _thread(_reply_node("what a mess"))},
    )
    source.fetch_evidence(_settings())
    thread_calls = [params for url, params in client.calls if "getPostThread" in url]
    assert thread_calls[0]["depth"] == 2


def test_replies_are_attached_to_their_post():
    source, _ = _source(
        {"trends": [_trend("t1", "A trend")]},
        {"t1": {"feed": [_post("p1")]}},
        {"p1": _thread(_reply_node("what a mess"), _reply_node("about time"))},
    )
    [evidence] = source.fetch_evidence(_settings())
    assert [reply.text for reply in evidence.posts[0].replies] == [
        "what a mess",
        "about time",
    ]


def test_nested_replies_are_flattened():
    source, _ = _source(
        {"trends": [_trend("t1", "A trend")]},
        {"t1": {"feed": [_post("p1")]}},
        {"p1": _thread(_reply_node("top", children=[_reply_node("nested")]))},
    )
    [evidence] = source.fetch_evidence(_settings())
    assert {reply.text for reply in evidence.posts[0].replies} == {"top", "nested"}


def test_blocked_and_missing_reply_nodes_are_skipped():
    """`replies` is a union: notFoundPost and blockedPost have no record."""
    source, _ = _source(
        {"trends": [_trend("t1", "A trend")]},
        {"t1": {"feed": [_post("p1")]}},
        {
            "p1": _thread(
                _reply_node("real"),
                {"$type": "app.bsky.feed.defs#blockedPost", "uri": "at://x/y/z"},
                {"$type": "app.bsky.feed.defs#notFoundPost", "uri": "at://x/y/w"},
            )
        },
    )
    [evidence] = source.fetch_evidence(_settings())
    assert [reply.text for reply in evidence.posts[0].replies] == ["real"]


def test_labelled_replies_are_dropped():
    source, _ = _source(
        {"trends": [_trend("t1", "A trend")]},
        {"t1": {"feed": [_post("p1")]}},
        {
            "p1": _thread(
                _reply_node("fine"),
                _reply_node("nasty", labels=[{"val": "porn"}]),
            )
        },
    )
    [evidence] = source.fetch_evidence(_settings())
    assert [reply.text for reply in evidence.posts[0].replies] == ["fine"]


def test_the_same_author_yields_the_same_key_and_a_different_one_differs():
    source, _ = _source(
        {"trends": [_trend("t1", "A trend")]},
        {"t1": {"feed": [_post("p1")]}},
        {
            "p1": _thread(
                _reply_node("one", did="did:plc:aaa"),
                _reply_node("two", did="did:plc:aaa"),
                _reply_node("three", did="did:plc:bbb"),
            )
        },
    )
    [evidence] = source.fetch_evidence(_settings())
    first, second, third = evidence.posts[0].replies
    assert first.author_key == second.author_key
    assert first.author_key != third.author_key


def test_the_author_key_is_not_the_did():
    """It is a hash. A raw DID on disk would be an identifier we have no use
    for; the count of distinct accounts is the only thing needed.
    """
    source, _ = _source(
        {"trends": [_trend("t1", "A trend")]},
        {"t1": {"feed": [_post("p1")]}},
        {"p1": _thread(_reply_node("hi", did="did:plc:aaa"))},
    )
    [evidence] = source.fetch_evidence(_settings())
    assert "did:plc:aaa" not in evidence.posts[0].replies[0].author_key


def test_a_failing_thread_leaves_the_post_without_replies():
    source, _ = _source(
        {"trends": [_trend("t1", "A trend")]},
        {"t1": {"feed": [_post("p1")]}},
        {"p1": httpx.ConnectError("boom")},
    )
    [evidence] = source.fetch_evidence(_settings())
    assert evidence.posts[0].replies == []
    assert evidence.posts[0].item.source_id.endswith("p1")


def test_a_failing_feed_skips_only_that_trend():
    source, _ = _source(
        {"trends": [_trend("t1", "First"), _trend("t2", "Second")]},
        {"t1": httpx.ConnectError("boom"), "t2": {"feed": [_post("p2")]}},
    )
    evidence = source.fetch_evidence(_settings())
    assert [e.trend.display_name for e in evidence] == ["Second"]


def test_a_trend_with_no_usable_posts_is_skipped():
    source, _ = _source(
        {"trends": [_trend("t1", "First"), _trend("t2", "Second")]},
        {"t1": {"feed": [_post("p1", text="   ")]}, "t2": {"feed": [_post("p2")]}},
    )
    evidence = source.fetch_evidence(_settings())
    assert [e.trend.display_name for e in evidence] == ["Second"]


def test_unreachable_trends_endpoint_is_fatal():
    source, _ = _source(httpx.ConnectError("boom"), {})
    with pytest.raises(SourceError, match="trends unavailable"):
        source.fetch_evidence(_settings())


def test_an_empty_trends_list_is_fatal():
    """Distinct from `test_no_usable_trends_at_all_is_fatal` below: this
    exercises the early `if not trends:` guard, straight off the getTrends
    payload, rather than the later `if not evidence:` guard after every
    trend has been fetched and filtered. The two raise different messages,
    and this is the only test that pins the first one's.
    """
    source, _ = _source({"trends": []}, {})
    with pytest.raises(SourceError, match="no trends"):
        source.fetch_evidence(_settings())


def test_no_usable_trends_at_all_is_fatal():
    source, _ = _source(
        {"trends": [_trend("t1", "First")]},
        {"t1": httpx.ConnectError("boom")},
    )
    with pytest.raises(SourceError, match="no usable"):
        source.fetch_evidence(_settings())


def test_a_rate_limited_request_is_retried(monkeypatch):
    monkeypatch.setattr("zeitgeist.sources.bluesky.RETRY_BASE_DELAY", 0)
    source, client = _source(
        {"trends": [_trend("t1", "A trend")]},
        {"t1": [_Response({}, status_code=429), {"feed": [_post("p1")]}]},
    )
    [evidence] = source.fetch_evidence(_settings())
    assert len(evidence.posts) == 1
    assert sum(1 for url, _ in client.calls if "getFeed" in url) == 2


def test_concurrency_matches_the_configured_bound():
    """Equality, not an upper bound: `<= 3` also passes when the fan-out
    silently serialises, which is the failure this whole rewrite exists to
    avoid. The fake yields inside `get`, so three permits deterministically
    produce three overlapping requests.
    """
    trends = [_trend(f"t{i}", f"Trend {i}") for i in range(10)]
    feeds = {
        f"t{i}": {"feed": [_post(f"p{i}-{j}") for j in range(5)]} for i in range(10)
    }
    source, client = _source({"trends": trends}, feeds)
    source.fetch_evidence(_settings(bluesky_fetch_concurrency=3))
    assert client.max_in_flight == 3


def test_a_persistently_rate_limited_feed_skips_only_that_trend(monkeypatch):
    """The last 429 falls through to raise_for_status and the per-trend guard
    treats it as any other transport failure. Without that fall-through `_get`
    runs off the end of its loop into AssertionError, killing the run rather
    than costing one trend. Also pins the retry count: an unbounded loop or a
    fourth attempt fails the call count.
    """
    monkeypatch.setattr("zeitgeist.sources.bluesky.RETRY_BASE_DELAY", 0)
    source, client = _source(
        {"trends": [_trend("t1", "Throttled"), _trend("t2", "Fine")]},
        {
            "t1": [_Response({}, status_code=429) for _ in range(3)],
            "t2": {"feed": [_post("p2")]},
        },
    )
    evidence = source.fetch_evidence(_settings())
    assert [e.trend.display_name for e in evidence] == ["Fine"]
    assert sum(1 for url, _ in client.calls if "getFeed" in url) == 4


def test_posts_per_trend_bounds_the_feed_request():
    source, client = _source(
        {"trends": [_trend("t1", "A trend")]},
        {"t1": {"feed": [_post("p1")]}},
    )
    source.fetch_evidence(_settings(bluesky_posts_per_trend=4))
    feed_calls = [params for url, params in client.calls if "getFeed" in url]
    assert feed_calls[0]["limit"] == 4


def test_the_client_is_closed_even_when_the_run_fails():
    source, client = _source(httpx.ConnectError("boom"), {})
    with pytest.raises(SourceError):
        source.fetch_evidence(_settings())
    assert client.closed


def test_evidence_survives_a_json_round_trip():
    """It is the ingest checkpoint, so it has to serialise."""
    source, _ = _source(
        {"trends": [_trend("t1", "A trend")]},
        {"t1": {"feed": [_post("p1")]}},
        {"p1": _thread(_reply_node("what a mess"))},
    )
    [evidence] = source.fetch_evidence(_settings())
    assert TrendEvidence.model_validate_json(evidence.model_dump_json()) == evidence


# --- Coverage carried forward from the pre-rewrite fetch()/list[Item] tests.
# Same assertions, now read through fetch_evidence()/evidence[0].posts[0].item.


def test_a_post_becomes_an_item_carrying_its_trend():
    """`trend` is what extract.py reads as `context`, and a short Bluesky post
    is often incomprehensible without it.
    """
    source, _ = _source(
        {"trends": [_trend("t1", "A trend")]},
        {"t1": {"feed": [_post("p1")]}},
    )
    [evidence] = source.fetch_evidence(_settings())
    item = evidence.posts[0].item
    assert item.title == "something happened"
    assert _metrics(item).trend == "A trend"
    assert item.context == "A trend"


def test_engagement_counts_are_carried_through():
    source, _ = _source(
        {"trends": [_trend("t1", "A trend")]},
        {"t1": {"feed": [_post("p1", likes=41, replies=7, reposts=13)]}},
    )
    [evidence] = source.fetch_evidence(_settings())
    metrics = _metrics(evidence.posts[0].item)
    assert metrics.like_count == 41
    assert metrics.reply_count == 7
    assert metrics.repost_count == 13


def test_a_post_missing_engagement_counts_defaults_to_zero():
    """likeCount/replyCount/repostCount are all optional in postView — a post
    with no engagement yet omits them rather than sending 0. A missing key
    here is the contract as published, not a changed payload.
    """
    post = _post("p1")
    del post["post"]["likeCount"]
    del post["post"]["replyCount"]
    del post["post"]["repostCount"]
    source, _ = _source({"trends": [_trend("t1", "A trend")]}, {"t1": {"feed": [post]}})

    [evidence] = source.fetch_evidence(_settings())
    metrics = _metrics(evidence.posts[0].item)
    assert metrics.like_count == 0
    assert metrics.reply_count == 0
    assert metrics.repost_count == 0


def test_the_trend_status_is_carried_onto_every_post():
    source, _ = _source(
        {"trends": [_trend("t1", "A cooling trend", status="cooling")]},
        {"t1": {"feed": [_post("p1"), _post("p2")]}},
    )
    [evidence] = source.fetch_evidence(_settings())
    assert [_metrics(p.item).status for p in evidence.posts] == ["cooling", "cooling"]


def test_a_trend_with_hot_status_maps_to_trending():
    """ "hot" is the one value the lexicon actually documents (`knownValues`),
    but the model's Literal only knows trending/saturating/cooling/stale —
    observed live — so "hot" must be mapped onto "trending" rather than
    rejected.
    """
    source, _ = _source(
        {"trends": [_trend("t1", "A trend", status="hot")]},
        {"t1": {"feed": [_post("p1")]}},
    )
    [evidence] = source.fetch_evidence(_settings())
    assert _metrics(evidence.posts[0].item).status == "trending"
    assert evidence.trend.status == "trending"


def test_a_saturating_trend_passes_through_without_warning(caplog):
    """`saturating` is undocumented but real: 2 of 25 live trends carried it on
    2026-08-23. It means still large with growth flattening, so it is a known
    value with its own place on the scale, not an unrecognised one — and it
    must not spend the warning that exists to surface genuinely new values.
    """
    source, _ = _source(
        {"trends": [_trend("t1", "A trend", status="saturating")]},
        {"t1": {"feed": [_post("p1")]}},
    )

    with caplog.at_level(logging.WARNING):
        [evidence] = source.fetch_evidence(_settings())

    assert _metrics(evidence.posts[0].item).status == "saturating"
    assert caplog.records == []


def test_a_trend_with_no_status_defaults_to_cooling_and_warns(caplog):
    """status is optional in trendView — a missing value is the contract as
    published, not a changed payload, so it must not crash. It maps to the
    neutral middle of the scorer's scale rather than a silent default, which
    is why this also warns: the warning is how a future enum widening
    actually gets noticed.
    """
    trend = _trend("t1", "A trend")
    del trend["status"]
    source, _ = _source({"trends": [trend]}, {"t1": {"feed": [_post("p1")]}})

    with caplog.at_level(logging.WARNING):
        [evidence] = source.fetch_evidence(_settings())

    assert _metrics(evidence.posts[0].item).status == "cooling"
    assert evidence.trend.status == "cooling"
    assert "None" in caplog.text


def test_a_trend_with_an_unrecognised_status_defaults_to_cooling_and_warns(caplog):
    """`knownValues` is explicitly non-exhaustive in AT Protocol, so a fifth
    value must survive rather than crash the whole run — but still be
    logged, which is how a future enum widening actually gets noticed.
    """
    source, _ = _source(
        {"trends": [_trend("t1", "A trend", status="smouldering")]},
        {"t1": {"feed": [_post("p1")]}},
    )

    with caplog.at_level(logging.WARNING):
        [evidence] = source.fetch_evidence(_settings())

    assert _metrics(evidence.posts[0].item).status == "cooling"
    assert "smouldering" in caplog.text


def test_created_at_comes_from_indexed_at_not_the_client_clock():
    """record.createdAt is client-supplied and unverified; the scorer divides
    engagement by age, so a back-dated post would report a false velocity.
    The two values are a year and a half apart here, so a source reading the
    wrong field cannot pass by coincidence.
    """
    source, _ = _source(
        {"trends": [_trend("t1", "A trend")]},
        {
            "t1": {
                "feed": [
                    _post(
                        "p1",
                        indexed="2026-08-23T10:00:00.000Z",
                        created="2025-01-01T00:00:00.000Z",
                    )
                ]
            }
        },
    )
    [evidence] = source.fetch_evidence(_settings())
    assert _metrics(evidence.posts[0].item).created_at == datetime(
        2026, 8, 23, 10, 0, tzinfo=UTC
    )


def test_created_at_is_timezone_aware_when_the_payload_omits_the_zone():
    """`_parse_timestamp` has a naive-datetime fallback, and untested
    defensive code is worse than none. The scorer subtracts created_at from
    an aware `now`, so a naive value raises there — three stages downstream —
    rather than here. Mirrors the same guard on LemmySource.
    """
    source, _ = _source(
        {"trends": [_trend("t1", "A trend")]},
        {"t1": {"feed": [_post("p1", indexed="2026-08-23T10:00:00")]}},
    )
    [evidence] = source.fetch_evidence(_settings())
    assert _metrics(evidence.posts[0].item).created_at == datetime(
        2026, 8, 23, 10, 0, tzinfo=UTC
    )


def test_permalink_is_built_from_the_at_uri():
    """An at:// URI is an identifier, not an address, so unlike Lemmy's ap_id
    it cannot be used as the permalink directly.
    """
    source, _ = _source(
        {"trends": [_trend("t1", "A trend")]},
        {"t1": {"feed": [_post("p1")]}},
    )
    [evidence] = source.fetch_evidence(_settings())
    item = evidence.posts[0].item
    assert item.source_id == f"at://{AUTHOR_DID}/app.bsky.feed.post/p1"
    assert item.permalink == f"https://bsky.app/profile/{AUTHOR_DID}/post/p1"


def test_the_feed_is_requested_by_at_uri_built_from_the_trend_link():
    """The link is a web UI path; getFeed needs a record address. The `feed`
    segment of the path becomes the lexicon name.
    """
    source, client = _source(
        {"trends": [_trend("t1", "A trend")]},
        {"t1": {"feed": [_post("p1")]}},
    )
    source.fetch_evidence(_settings())
    feed_calls = [p for url, p in client.calls if "getFeed" in url]
    assert feed_calls[0]["feed"] == f"at://{TREND_DID}/app.bsky.feed.generator/t1"


def test_non_english_posts_are_dropped():
    source, _ = _source(
        {"trends": [_trend("t1", "A trend")]},
        {
            "t1": {
                "feed": [
                    _post("p1", "in English", langs=["en"]),
                    _post("p2", "auf Deutsch", langs=["de"]),
                ]
            }
        },
    )
    [evidence] = source.fetch_evidence(_settings())
    assert [p.item.title for p in evidence.posts] == ["in English"]


def test_a_post_declaring_no_language_is_kept():
    """`langs` is optional and client-set, so absence means unknown rather
    than non-English. Dropping these would discard a real share of every
    fetch.
    """
    source, _ = _source(
        {"trends": [_trend("t1", "A trend")]},
        {"t1": {"feed": [_post("p1", "no langs field", langs=None)]}},
    )
    [evidence] = source.fetch_evidence(_settings())
    assert [p.item.title for p in evidence.posts] == ["no langs field"]


def test_a_multilingual_post_including_english_is_kept():
    source, _ = _source(
        {"trends": [_trend("t1", "A trend")]},
        {"t1": {"feed": [_post("p1", "bilingual", langs=["de", "en"])]}},
    )
    [evidence] = source.fetch_evidence(_settings())
    assert [p.item.title for p in evidence.posts] == ["bilingual"]


def test_a_regional_language_tag_is_kept():
    """langs is BCP-47 (`format: "language"`), so "en-US" is a valid English
    tag that exact membership against "en" would otherwise drop.
    """
    source, _ = _source(
        {"trends": [_trend("t1", "A trend")]},
        {"t1": {"feed": [_post("p1", "regional", langs=["en-US"])]}},
    )
    [evidence] = source.fetch_evidence(_settings())
    assert [p.item.title for p in evidence.posts] == ["regional"]


def test_labelled_posts_are_dropped():
    """Trend feeds appear to filter already, so this changes nothing today and
    exists so a change upstream cannot put graphic content into a meme.
    """
    source, _ = _source(
        {"trends": [_trend("t1", "A trend")]},
        {
            "t1": {
                "feed": [
                    _post("p1", "clean"),
                    _post("p2", "graphic", labels=[{"val": "porn"}]),
                ]
            }
        },
    )
    [evidence] = source.fetch_evidence(_settings())
    assert [p.item.title for p in evidence.posts] == ["clean"]


def test_a_post_with_no_labels_key_is_kept():
    """`labels` is optional in postView; a post the labeler never touched
    omits the key rather than sending an empty list.
    """
    post = _post("p1", "clean")
    del post["post"]["labels"]
    source, _ = _source({"trends": [_trend("t1", "A trend")]}, {"t1": {"feed": [post]}})

    [evidence] = source.fetch_evidence(_settings())
    assert [p.item.title for p in evidence.posts] == ["clean"]


def test_empty_text_posts_are_dropped():
    """Item.title would be blank and the extraction prompt would have nothing
    to label.
    """
    source, _ = _source(
        {"trends": [_trend("t1", "A trend")]},
        {"t1": {"feed": [_post("p1", "   "), _post("p2", "real text")]}},
    )
    [evidence] = source.fetch_evidence(_settings())
    assert [p.item.title for p in evidence.posts] == ["real text"]


def test_a_malformed_trend_link_skips_only_that_trend():
    """`link` is a UI path, not a documented contract, so a future variant
    must cost one trend rather than the run.
    """
    broken = _trend("t1", "Broken")
    broken["link"] = "/some/unexpected/shape"
    source, _ = _source(
        {"trends": [broken, _trend("t2", "Fine")]},
        {"t2": {"feed": [_post("p2", "survivor")]}},
    )
    evidence = source.fetch_evidence(_settings())
    assert [e.trend.display_name for e in evidence] == ["Fine"]


def test_a_malformed_post_uri_is_skipped(caplog):
    """A too-short uri would otherwise still collapse `parts[0]` and
    `parts[-1]` to the same value, producing a plausible-looking permalink
    that 404s instead of failing visibly.
    """
    broken = _post("p1")
    broken["post"]["uri"] = "at://did:plc:onlyanauthority"
    source, _ = _source(
        {"trends": [_trend("t1", "A trend")]},
        {"t1": {"feed": [broken, _post("p2", "survivor")]}},
    )

    with caplog.at_level(logging.WARNING):
        [evidence] = source.fetch_evidence(_settings())

    assert [p.item.title for p in evidence.posts] == ["survivor"]
    assert "malformed uri" in caplog.text


def test_a_changed_payload_shape_propagates_rather_than_being_swallowed():
    """A missing REQUIRED key is a contract break, not an outage, so it must
    crash rather than look like an empty platform. `displayName` is required
    by trendView, unlike `status`, which the lexicon marks optional.
    """
    trend = _trend("t1", "A trend")
    del trend["displayName"]
    source, _ = _source({"trends": [trend]}, {"t1": {"feed": [_post("p1")]}})

    with pytest.raises(KeyError):
        source.fetch_evidence(_settings())


def test_every_post_being_filtered_out_raises_source_error():
    source, _ = _source(
        {"trends": [_trend("t1", "A trend")]},
        {"t1": {"feed": [_post("p1", "auf Deutsch", langs=["de"])]}},
    )

    with pytest.raises(SourceError, match="no usable"):
        source.fetch_evidence(_settings())


def test_requests_go_to_the_configured_api_base():
    """The base URL is the one setting that decides which host is scraped,
    and __init__ strips a trailing slash off it. Neither fact shows up until
    a request is made: reading `_api_base` back passes even if the URL
    builders interpolate the module default and ignore it.
    """
    client = _FakeAsyncClient(
        {"trends": [_trend("t1", "A trend")]},
        {"t1": {"feed": [_post("p1")]}},
    )
    source = BlueskySource(
        api_base="https://mirror.example/", client_factory=lambda: client
    )

    source.fetch_evidence(_settings())

    urls = {url for url, _ in client.calls}
    assert urls == {
        "https://mirror.example/xrpc/app.bsky.unspecced.getTrends",
        "https://mirror.example/xrpc/app.bsky.feed.getFeed",
        "https://mirror.example/xrpc/app.bsky.feed.getPostThread",
    }


def test_from_settings_wires_the_api_base_into_the_request():
    """from_settings is plumbing, so it fails silently: a mis-assigned base
    only shows up in the request it produces.
    """
    settings = _settings(bluesky_api_base="https://mirror.example")
    source = BlueskySource.from_settings(settings)
    client = _FakeAsyncClient(
        {"trends": [_trend("t1", "A trend")]},
        {"t1": {"feed": [_post("p1")]}},
    )
    source._client_factory = lambda: client

    source.fetch_evidence(settings)

    assert client.calls[0][0] == (
        "https://mirror.example/xrpc/app.bsky.unspecced.getTrends"
    )


def test_bluesky_is_a_known_source():
    """Settings rejects unknown names, so without this SOURCES=bluesky fails
    at startup.
    """
    assert Settings(_env_file=None, sources="bluesky").sources == ["bluesky"]
