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
