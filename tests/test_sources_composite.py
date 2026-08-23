import logging
from datetime import UTC, date, datetime

import pytest

from zeitgeist.config import KNOWN_SOURCES
from zeitgeist.models import Item, LemmyMetrics, Metrics, WikipediaMetrics
from zeitgeist.sources import BUILDERS
from zeitgeist.sources.base import SourceError
from zeitgeist.sources.composite import CompositeSource
from zeitgeist.sources.lemmy import LemmySource


def _item(platform: str, source_id: str, channel: str = "cats@lemmy.world") -> Item:
    """Dispatches on platform so each item carries its own metrics class.
    Every test in this file builds items through here, so the union is
    exercised by the whole file rather than by one dedicated test.

    The two branches take different keyword sets on purpose: WikipediaMetrics
    has no score, comments or channel, and STRICT would reject them.
    """
    metrics: Metrics
    if platform == "lemmy":
        metrics = LemmyMetrics(
            score=10,
            comment_count=2,
            channel=channel,
            created_at=datetime(2026, 8, 16, 9, 0, tzinfo=UTC),
        )
    elif platform == "wikipedia":
        metrics = WikipediaMetrics(views=1000, rank=7, measured_on=date(2026, 8, 16))
    else:
        raise AssertionError(f"no metrics class for platform {platform!r}")
    return Item(
        source_id=source_id,
        title=f"Post {source_id}",
        permalink=f"https://example.com/{source_id}",
        fetched_at=datetime(2026, 8, 16, 12, 0, tzinfo=UTC),
        metrics=metrics,
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


class BuggySource:
    """Raises something other than SourceError, e.g. a mapping bug."""

    name = "buggy"

    def fetch(self, limit):
        raise KeyError("posts")


class StubLemmyClient:
    """Returns a payload missing 'posts', the same shape a changed Lemmy API
    would send. Mirrors StubClient/StubResponse in tests/test_sources_lemmy.py.
    """

    def get(self, url, params):
        return _MalformedResponse()


class _MalformedResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {"unexpected": []}


def test_combines_posts_from_every_source():
    composite = CompositeSource(
        [
            StubSource("lemmy", [_item("lemmy", "l1")]),
            StubSource("wikipedia", [_item("wikipedia", "r1")]),
        ]
    )
    platforms = {post.platform for post in composite.fetch(limit=10)}
    assert platforms == {"lemmy", "wikipedia"}


def test_divides_the_budget_across_sources():
    """A single source must not spend the whole POST_LIMIT and starve the
    others of their share.
    """
    first = StubSource("lemmy", [_item("lemmy", f"l{n}") for n in range(20)])
    second = StubSource("wikipedia", [_item("wikipedia", f"r{n}") for n in range(20)])
    CompositeSource([first, second]).fetch(limit=10)
    assert first.requested_limit == 5
    assert second.requested_limit == 5


def test_respects_the_limit():
    sources = [
        StubSource("lemmy", [_item("lemmy", f"l{n}") for n in range(20)]),
        StubSource("wikipedia", [_item("wikipedia", f"r{n}") for n in range(20)]),
    ]
    assert len(CompositeSource(sources).fetch(limit=6)) == 6


def test_same_id_on_different_platforms_is_not_a_duplicate():
    """source_id is only unique within a platform: Lemmy uses URLs and
    Wikipedia uses page titles, but nothing guarantees they never collide.
    """
    sources = [
        StubSource("lemmy", [_item("lemmy", "shared")]),
        StubSource("wikipedia", [_item("wikipedia", "shared")]),
    ]
    assert len(CompositeSource(sources).fetch(limit=10)) == 2


def test_a_failing_source_is_skipped_and_others_still_yield_posts(caplog):
    """One platform being down must not lose the other's posts."""
    composite = CompositeSource(
        [FailingSource(), StubSource("lemmy", [_item("lemmy", "l1")])]
    )
    with caplog.at_level(logging.WARNING):
        posts = composite.fetch(limit=10)

    assert [post.source_id for post in posts] == ["l1"]
    assert "broken" in caplog.text


def test_all_sources_failing_raises_source_error():
    with pytest.raises(SourceError, match="No source"):
        CompositeSource([FailingSource(), FailingSource()]).fetch(limit=10)


def test_a_non_source_error_propagates_rather_than_being_swallowed():
    """Only SourceError means 'this platform is down'. Anything else is a
    bug in that source (e.g. a mapping error) and must crash the run, not
    be logged as an unreachable platform and skipped like FailingSource is.
    """
    composite = CompositeSource(
        [BuggySource(), StubSource("lemmy", [_item("lemmy", "l1")])]
    )
    with pytest.raises(KeyError):
        composite.fetch(limit=10)


def test_malformed_payload_from_a_real_source_crashes_through_the_composite():
    """The gap between the two unit suites: LemmySource alone is proven to
    crash on a malformed payload (test_sources_lemmy.py), and CompositeSource
    alone is proven to only catch SourceError (above) — but nothing proved
    the two compose correctly until now. build_source always wraps even a
    single source in a CompositeSource, so this is the path a real run takes.
    """
    lemmy = LemmySource(instance="https://lemmy.world", client=StubLemmyClient())
    composite = CompositeSource([lemmy])
    with pytest.raises(KeyError):
        composite.fetch(limit=10)


def test_every_source_returning_nothing_raises_source_error():
    with pytest.raises(SourceError, match="No source"):
        CompositeSource([StubSource("lemmy", [])]).fetch(limit=10)


def test_building_with_no_sources_is_rejected():
    with pytest.raises(ValueError, match="at least one"):
        CompositeSource([])


def test_every_known_source_has_a_builder():
    """Settings validates SOURCES against KNOWN_SOURCES while build_source
    indexes BUILDERS. If they drift, a name accepted at startup raises a
    KeyError once the run is already under way.
    """
    assert set(BUILDERS) == set(KNOWN_SOURCES)
