"""BlueskySource fetches in two steps: getTrends, then getFeed per trend.

The fake client routes on endpoint rather than replaying a queue, because the
two endpoints return different shapes and the source calls one of them 25
times.
"""

import logging
from collections.abc import Mapping
from datetime import UTC, datetime

import httpx
import pytest

from zeitgeist.config import Settings
from zeitgeist.models import BlueskyMetrics, Item
from zeitgeist.sources.base import SourceError
from zeitgeist.sources.bluesky import BlueskySource

TREND_DID = "did:plc:trendingservice"
AUTHOR_DID = "did:plc:someauthor"


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
            # Present because the real postView always carries it, and
            # deliberately never read: no model in this project holds an
            # author, and tests/test_models.py guards that. Trimming a fixture
            # to what the code reads today lets a later change reference a
            # field that was never in the test data.
            "author": {
                "did": did,
                "handle": "someone.bsky.social",
                "displayName": "Someone",
                "avatar": "https://cdn.bsky.app/img/avatar/plain/abc@jpeg",
                "createdAt": "2024-01-01T00:00:00.000Z",
                "labels": [],
                "viewer": {"muted": False, "blockedBy": False},
            },
            "record": record,
            "likeCount": likes,
            "replyCount": replies,
            "repostCount": reposts,
            "quoteCount": 0,
            "bookmarkCount": 0,
            "indexedAt": indexed,
            "viewer": {"threadMuted": False, "embeddingDisabled": False},
            "labels": labels or [],
        }
    }


class _Response:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class _FakeClient:
    """`trends` is a payload or an Exception. `feeds` maps rkey to either."""

    def __init__(
        self, trends: dict | Exception, feeds: Mapping[str, dict | Exception]
    ) -> None:
        self._trends = trends
        self._feeds = feeds
        self.calls: list[tuple[str, dict]] = []

    def get(self, url: str, params: dict | None = None, **kwargs: object) -> _Response:
        params = params or {}
        self.calls.append((url, params))
        if "getTrends" in url:
            # Bound to a local so ty can narrow away the Exception arm;
            # narrowing does not carry across repeated attribute reads.
            trends = self._trends
            if isinstance(trends, Exception):
                raise trends
            return _Response(trends)
        if "getFeed" in url:
            rkey = str(params["feed"]).rsplit("/", 1)[-1]
            result = self._feeds[rkey]
            if isinstance(result, Exception):
                raise result
            return _Response(result)
        raise AssertionError(f"unexpected URL {url}")


def _source(
    trends: dict | Exception, feeds: Mapping[str, dict | Exception]
) -> BlueskySource:
    return BlueskySource(client=_FakeClient(trends, feeds))


def _one_trend_one_post(**post_kwargs) -> BlueskySource:
    return _source(
        {"trends": [_trend("t1", "A trend")]},
        {"t1": {"feed": [_post("p1", **post_kwargs)]}},
    )


def test_a_post_becomes_an_item_carrying_its_trend():
    """`trend` is what extract.py reads as `context`, and a short Bluesky post
    is often incomprehensible without it.
    """
    items = _one_trend_one_post().fetch(limit=10)

    assert len(items) == 1
    assert items[0].title == "something happened"
    assert _metrics(items[0]).trend == "A trend"
    assert items[0].context == "A trend"


def test_engagement_counts_are_carried_through():
    items = _one_trend_one_post(likes=41, replies=7, reposts=13).fetch(limit=10)

    assert _metrics(items[0]).like_count == 41
    assert _metrics(items[0]).reply_count == 7
    assert _metrics(items[0]).repost_count == 13


def test_a_post_missing_engagement_counts_defaults_to_zero():
    """likeCount/replyCount/repostCount are all optional in postView — a post
    with no engagement yet omits them rather than sending 0. A missing key
    here is the contract as published, not a changed payload.
    """
    post = _post("p1")
    del post["post"]["likeCount"]
    del post["post"]["replyCount"]
    del post["post"]["repostCount"]
    source = _source({"trends": [_trend("t1", "A trend")]}, {"t1": {"feed": [post]}})

    items = source.fetch(limit=10)

    assert _metrics(items[0]).like_count == 0
    assert _metrics(items[0]).reply_count == 0
    assert _metrics(items[0]).repost_count == 0


def test_the_trend_status_is_carried_onto_every_post():
    source = _source(
        {"trends": [_trend("t1", "A cooling trend", status="cooling")]},
        {"t1": {"feed": [_post("p1"), _post("p2")]}},
    )

    items = source.fetch(limit=10)

    assert [_metrics(item).status for item in items] == ["cooling", "cooling"]


def test_a_trend_with_no_status_defaults_to_cooling_and_warns(caplog):
    """status is optional in trendView — a missing value is the contract as
    published, not a changed payload, so it must not crash. It maps to the
    neutral middle of the scorer's scale rather than a silent default, which
    is why this also warns: the warning is how a future enum widening
    actually gets noticed.
    """
    trend = _trend("t1", "A trend")
    del trend["status"]
    source = _source({"trends": [trend]}, {"t1": {"feed": [_post("p1")]}})

    with caplog.at_level(logging.WARNING):
        items = source.fetch(limit=10)

    assert _metrics(items[0]).status == "cooling"
    assert "None" in caplog.text


def test_a_trend_with_hot_status_maps_to_trending():
    """ "hot" is the one value the lexicon actually documents (`knownValues`),
    but the model's Literal only knows trending/cooling/stale — observed
    live — so "hot" must be mapped onto "trending" rather than rejected.
    """
    source = _source(
        {"trends": [_trend("t1", "A trend", status="hot")]},
        {"t1": {"feed": [_post("p1")]}},
    )

    items = source.fetch(limit=10)

    assert _metrics(items[0]).status == "trending"


def test_a_saturating_trend_passes_through_without_warning(caplog):
    """`saturating` is undocumented but real: 2 of 25 live trends carried it on
    2026-08-23. It means still large with growth flattening, so it is a known
    value with its own place on the scale, not an unrecognised one — and it
    must not spend the warning that exists to surface genuinely new values.
    """
    source = _source(
        {"trends": [_trend("t1", "A trend", status="saturating")]},
        {"t1": {"feed": [_post("p1")]}},
    )

    with caplog.at_level(logging.WARNING):
        items = source.fetch(limit=10)

    assert _metrics(items[0]).status == "saturating"
    assert caplog.records == []


def test_a_trend_with_an_unrecognised_status_defaults_to_cooling_and_warns(caplog):
    """`knownValues` is explicitly non-exhaustive in AT Protocol, so a fifth
    value must survive rather than crash the whole run — but still be
    logged, which is how a future enum widening actually gets noticed.
    """
    source = _source(
        {"trends": [_trend("t1", "A trend", status="smouldering")]},
        {"t1": {"feed": [_post("p1")]}},
    )

    with caplog.at_level(logging.WARNING):
        items = source.fetch(limit=10)

    assert _metrics(items[0]).status == "cooling"
    assert "smouldering" in caplog.text


def test_created_at_comes_from_indexed_at_not_the_client_clock():
    """record.createdAt is client-supplied and unverified; the scorer divides
    engagement by age, so a back-dated post would report a false velocity.
    The two values are a year and a half apart here, so a source reading the
    wrong field cannot pass by coincidence.
    """
    items = _one_trend_one_post(
        indexed="2026-08-23T10:00:00.000Z",
        created="2025-01-01T00:00:00.000Z",
    ).fetch(limit=10)

    assert _metrics(items[0]).created_at == datetime(2026, 8, 23, 10, 0, tzinfo=UTC)


def test_created_at_is_timezone_aware_when_the_payload_omits_the_zone():
    """`_parse_timestamp` has a naive-datetime fallback, and untested
    defensive code is worse than none. The scorer subtracts created_at from an
    aware `now`, so a naive value raises there — three stages downstream —
    rather than here. Mirrors the same guard on LemmySource.
    """
    items = _one_trend_one_post(indexed="2026-08-23T10:00:00").fetch(limit=10)

    assert _metrics(items[0]).created_at == datetime(2026, 8, 23, 10, 0, tzinfo=UTC)


def test_permalink_is_built_from_the_at_uri():
    """An at:// URI is an identifier, not an address, so unlike Lemmy's ap_id
    it cannot be used as the permalink directly.
    """
    items = _one_trend_one_post().fetch(limit=10)

    assert items[0].source_id == f"at://{AUTHOR_DID}/app.bsky.feed.post/p1"
    assert items[0].permalink == f"https://bsky.app/profile/{AUTHOR_DID}/post/p1"


def test_the_feed_is_requested_by_at_uri_built_from_the_trend_link():
    """The link is a web UI path; getFeed needs a record address. The `feed`
    segment of the path becomes the lexicon name.
    """
    source = _source(
        {"trends": [_trend("t1", "A trend")]},
        {"t1": {"feed": [_post("p1")]}},
    )

    source.fetch(limit=10)

    feed_calls = [p for url, p in source._client.calls if "getFeed" in url]
    assert feed_calls[0]["feed"] == (f"at://{TREND_DID}/app.bsky.feed.generator/t1")


def test_non_english_posts_are_dropped():
    source = _source(
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

    items = source.fetch(limit=10)

    assert [item.title for item in items] == ["in English"]


def test_a_post_declaring_no_language_is_kept():
    """`langs` is optional and client-set, so absence means unknown rather
    than non-English. Dropping these would discard 7% of a real fetch.
    """
    items = _one_trend_one_post(text="no langs field", langs=None).fetch(limit=10)

    assert [item.title for item in items] == ["no langs field"]


def test_a_multilingual_post_including_english_is_kept():
    items = _one_trend_one_post(text="bilingual", langs=["de", "en"]).fetch(limit=10)

    assert [item.title for item in items] == ["bilingual"]


def test_a_regional_language_tag_is_kept():
    """langs is BCP-47 (`format: "language"`), so "en-US" is a valid English
    tag that exact membership against "en" would otherwise drop.
    """
    items = _one_trend_one_post(text="regional", langs=["en-US"]).fetch(limit=10)

    assert [item.title for item in items] == ["regional"]


def test_labelled_posts_are_dropped():
    """Trend feeds appear to filter already, so this changes nothing today and
    exists so a change upstream cannot put graphic content into a meme.
    """
    source = _source(
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

    items = source.fetch(limit=10)

    assert [item.title for item in items] == ["clean"]


def test_a_post_with_no_labels_key_is_kept():
    """`labels` is optional in postView; a post the labeler never touched
    omits the key rather than sending an empty list.
    """
    post = _post("p1", "clean")
    del post["post"]["labels"]
    source = _source({"trends": [_trend("t1", "A trend")]}, {"t1": {"feed": [post]}})

    items = source.fetch(limit=10)

    assert [item.title for item in items] == ["clean"]


def test_empty_text_posts_are_dropped():
    """Item.title would be blank and the extraction prompt would have nothing
    to label.
    """
    source = _source(
        {"trends": [_trend("t1", "A trend")]},
        {"t1": {"feed": [_post("p1", "   "), _post("p2", "real text")]}},
    )

    items = source.fetch(limit=10)

    assert [item.title for item in items] == ["real text"]


def test_a_post_in_two_trends_yields_one_item_keeping_the_first_trend():
    source = _source(
        {"trends": [_trend("t1", "First trend"), _trend("t2", "Second trend")]},
        {
            "t1": {"feed": [_post("shared")]},
            "t2": {"feed": [_post("shared")]},
        },
    )

    items = source.fetch(limit=10)

    assert len(items) == 1
    assert _metrics(items[0]).trend == "First trend"


def test_a_malformed_trend_link_skips_only_that_trend():
    """`link` is a UI path, not a documented contract, so a future variant
    must cost one trend rather than the run.
    """
    broken = _trend("t1", "Broken")
    broken["link"] = "/some/unexpected/shape"
    source = _source(
        {"trends": [broken, _trend("t2", "Fine")]},
        {"t2": {"feed": [_post("p2", "survivor")]}},
    )

    items = source.fetch(limit=10)

    assert [item.title for item in items] == ["survivor"]


def test_a_malformed_post_uri_is_skipped(caplog):
    """A too-short uri would otherwise still collapse `parts[0]` and
    `parts[-1]` to the same value, producing a plausible-looking permalink
    that 404s instead of failing visibly.
    """
    broken = _post("p1")
    broken["post"]["uri"] = "at://did:plc:onlyanauthority"
    source = _source(
        {"trends": [_trend("t1", "A trend")]},
        {"t1": {"feed": [broken, _post("p2", "survivor")]}},
    )

    with caplog.at_level(logging.WARNING):
        items = source.fetch(limit=10)

    assert [item.title for item in items] == ["survivor"]
    assert "malformed uri" in caplog.text


def test_one_failing_feed_skips_only_that_trend():
    source = _source(
        {"trends": [_trend("t1", "Broken"), _trend("t2", "Fine")]},
        {
            "t1": httpx.ConnectError("boom"),
            "t2": {"feed": [_post("p2", "survivor")]},
        },
    )

    items = source.fetch(limit=10)

    assert [item.title for item in items] == ["survivor"]


def test_a_failing_trends_call_raises_source_error():
    """Without trends there is no way into the content, so there is no partial
    result to salvage.
    """
    with pytest.raises(SourceError):
        _source(httpx.ConnectError("boom"), {}).fetch(limit=10)


def test_no_trends_raises_source_error():
    with pytest.raises(SourceError):
        _source({"trends": []}, {}).fetch(limit=10)


def test_every_feed_failing_raises_source_error():
    source = _source(
        {"trends": [_trend("t1", "One"), _trend("t2", "Two")]},
        {"t1": httpx.ConnectError("boom"), "t2": httpx.ConnectError("boom")},
    )

    with pytest.raises(SourceError):
        source.fetch(limit=10)


def test_every_post_being_filtered_out_raises_source_error():
    source = _source(
        {"trends": [_trend("t1", "A trend")]},
        {"t1": {"feed": [_post("p1", "auf Deutsch", langs=["de"])]}},
    )

    with pytest.raises(SourceError):
        source.fetch(limit=10)


def test_a_changed_payload_shape_propagates_rather_than_being_swallowed():
    """A missing REQUIRED key is a contract break, not an outage, so it must
    crash rather than look like an empty platform. `displayName` is required
    by trendView, unlike `status`, which the lexicon marks optional.
    """
    trend = _trend("t1", "A trend")
    del trend["displayName"]
    source = _source({"trends": [trend]}, {"t1": {"feed": [_post("p1")]}})

    with pytest.raises(KeyError):
        source.fetch(limit=10)


def test_the_budget_splits_across_trends():
    """Four trends and a budget of 8 means 2 posts asked of each, rather than
    the first trend swallowing the run.
    """
    trends = [_trend(f"t{i}", f"Trend {i}") for i in range(4)]
    feeds = {f"t{i}": {"feed": [_post(f"p{i}")]} for i in range(4)}
    source = _source({"trends": trends}, feeds)

    source.fetch(limit=8)

    feed_calls = [p for url, p in source._client.calls if "getFeed" in url]
    assert len(feed_calls) == 4
    assert all(call["limit"] == 2 for call in feed_calls)


def test_limit_is_an_upper_bound_on_items_returned():
    trends = [_trend("t1", "One"), _trend("t2", "Two")]
    feeds = {
        "t1": {"feed": [_post(f"a{i}") for i in range(5)]},
        "t2": {"feed": [_post(f"b{i}") for i in range(5)]},
    }
    source = _source({"trends": trends}, feeds)

    assert len(source.fetch(limit=3)) == 3


def test_the_trend_listing_is_requested_at_the_api_cap():
    """getTrends returns 400 above 25, so the source always asks for exactly
    the maximum.
    """
    source = _one_trend_one_post()

    source.fetch(limit=10)

    trend_calls = [p for url, p in source._client.calls if "getTrends" in url]
    assert trend_calls[0]["limit"] == 25


def test_feed_requests_never_exceed_the_api_page_cap():
    """getFeed rejects a limit above 100. ceil(limit / len(trends)) overshoots
    whenever few trends come back — the default post_limit of 500 split across
    two trends asks for 250 — and every feed call 400s, so the whole run looks
    like an outage.
    """
    source = _source(
        {"trends": [_trend("t1", "One"), _trend("t2", "Two")]},
        {"t1": {"feed": [_post("a1")]}, "t2": {"feed": [_post("b1")]}},
    )

    source.fetch(limit=500)

    feed_calls = [p for url, p in source._client.calls if "getFeed" in url]
    assert [call["limit"] for call in feed_calls] == [100, 100]


def test_requests_go_to_the_configured_api_base():
    """The base URL is the one setting that decides which host is scraped,
    and __init__ strips a trailing slash off it. Neither fact shows up until
    a request is made: reading `_api_base` back passes even if the URL
    builders interpolate the module default and ignore it.
    """
    source = BlueskySource(
        api_base="https://mirror.example/",
        client=_FakeClient(
            {"trends": [_trend("t1", "A trend")]},
            {"t1": {"feed": [_post("p1")]}},
        ),
    )

    source.fetch(limit=10)

    assert [url for url, _ in source._client.calls] == [
        "https://mirror.example/xrpc/app.bsky.unspecced.getTrends",
        "https://mirror.example/xrpc/app.bsky.feed.getFeed",
    ]


def test_from_settings_wires_the_api_base_into_the_request():
    """from_settings is plumbing, so it fails silently: a mis-assigned base
    only shows up in the request it produces.
    """
    settings = Settings(_env_file=None, bluesky_api_base="https://mirror.example")
    source = BlueskySource.from_settings(settings)
    # from_settings builds a real httpx.Client; close it before the fake
    # replaces it so the test does not leak a live connection pool.
    source._client.close()
    source._client = _FakeClient(
        {"trends": [_trend("t1", "A trend")]},
        {"t1": {"feed": [_post("p1")]}},
    )

    source.fetch(limit=10)

    assert source._client.calls[0][0] == (
        "https://mirror.example/xrpc/app.bsky.unspecced.getTrends"
    )


def test_bluesky_is_a_known_source():
    """Settings rejects unknown names, so without this SOURCES=bluesky fails
    at startup.
    """
    assert Settings(_env_file=None, sources="bluesky").sources == ["bluesky"]
