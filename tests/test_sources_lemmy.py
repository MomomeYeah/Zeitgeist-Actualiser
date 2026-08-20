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
    client = StubClient({("Hot", 1): [_view("a1", "T")]})
    source = LemmySource(instance="https://sh.itjust.works/", client=client)
    source.fetch(limit=1)
    assert client.urls[0] == "https://sh.itjust.works/api/v3/post/list"


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
    pages = {
        ("Hot", 1): [_view(f"h{n}", f"T{n}") for n in range(50)],
        ("Scaled", 1): [_view(f"s{n}", f"U{n}") for n in range(50)],
    }
    assert len(_source(pages).fetch(limit=5)) == 5


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
