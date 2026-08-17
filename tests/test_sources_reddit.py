from datetime import UTC, datetime

import pytest

from zeitgeist.sources.base import SourceError
from zeitgeist.sources.reddit import RedditSource


class StubSubmission:
    def __init__(self, sid, title, score=100, comments=10, sub="cats", selftext=""):
        self.id = sid
        self.title = title
        self.score = score
        self.num_comments = comments
        self.selftext = selftext
        self.permalink = f"/r/{sub}/comments/{sid}/"
        self.created_utc = datetime(2026, 8, 16, 9, 0, tzinfo=UTC).timestamp()
        self.subreddit = type("S", (), {"display_name": sub})()


class StubListing:
    def __init__(self, submissions):
        self._submissions = submissions

    def hot(self, limit=None):
        return iter(self._submissions[:limit])

    def rising(self, limit=None):
        return iter(self._submissions[:limit])


class StubReddit:
    def __init__(self, by_name):
        self._by_name = by_name
        self.requested = []

    def subreddit(self, name):
        self.requested.append(name)
        return self._by_name[name]


def _source(by_name, subreddits=()):
    return RedditSource(
        client_id="id",
        client_secret="secret",
        user_agent="ua",
        subreddits=list(subreddits),
        reddit=StubReddit(by_name),
    )


def test_maps_submissions_onto_posts():
    """Every downstream stage reads these fields. A crossed assignment —
    comment_count into score, or fetched_at into created_at — would skew
    every velocity calculation while breaking nothing visibly.
    """
    listing = StubListing(
        [StubSubmission("a1", "Cat opens door", score=1234, comments=56)]
    )
    post = _source({"all": listing}).fetch(limit=10)[0]

    assert post.platform == "reddit"
    assert post.source_id == "a1"
    assert post.title == "Cat opens door"
    assert post.channel == "cats"
    assert post.score == 1234
    assert post.comment_count == 56
    assert post.permalink == "https://www.reddit.com/r/cats/comments/a1/"
    assert post.created_at == datetime(2026, 8, 16, 9, 0, tzinfo=UTC)
    assert post.fetched_at > post.created_at


def test_deduplicates_across_hot_and_rising():
    listing = StubListing([StubSubmission("a1", "Same post")])
    posts = _source({"all": listing}).fetch(limit=10)
    assert len(posts) == 1


def test_includes_configured_subreddits():
    all_listing = StubListing([StubSubmission("a1", "From all")])
    cats_listing = StubListing([StubSubmission("c1", "From cats", sub="cats")])
    source = _source({"all": all_listing, "cats": cats_listing}, subreddits=["cats"])
    ids = {post.source_id for post in source.fetch(limit=10)}
    assert ids == {"a1", "c1"}


def test_respects_the_limit():
    submissions = [StubSubmission(f"id{n}", f"Title {n}") for n in range(50)]
    posts = _source({"all": StubListing(submissions)}).fetch(limit=5)
    assert len(posts) == 5


def test_truncates_long_body_to_the_leading_excerpt():
    """Keeps prompt size bounded. Asserting the content, not just the
    length, catches a slice taken from the wrong end.
    """
    body = "".join(str(n % 10) for n in range(900))
    listing = StubListing([StubSubmission("a1", "T", selftext=body)])
    posts = _source({"all": listing}).fetch(limit=10)
    assert posts[0].body_excerpt == body[:500]


@pytest.mark.parametrize("selftext", ["", "   ", "\n\t "])
def test_blank_body_becomes_none_rather_than_empty_string(selftext):
    """Link posts have no selftext. An empty string would put a pointless
    'Body:' line into every extraction prompt.
    """
    listing = StubListing([StubSubmission("a1", "T", selftext=selftext)])
    posts = _source({"all": listing}).fetch(limit=10)
    assert posts[0].body_excerpt is None


def test_no_posts_raises_source_error():
    with pytest.raises(SourceError, match="no posts"):
        _source({"all": StubListing([])}).fetch(limit=10)


def test_fixture_meets_the_preconditions_later_tests_assume(sample_posts):
    """Not a test of production code — a guard on the shared fixture. The
    analysis tests are only meaningful if the fixture spans several channels
    and subject areas, so trimming posts.json must fail loudly here rather
    than quietly weakening clustering tests three files away.
    """
    assert len(sample_posts) >= 10
    assert len({post.channel for post in sample_posts}) >= 5
    assert all(post.created_at.tzinfo is not None for post in sample_posts)
    assert len({post.source_id for post in sample_posts}) == len(sample_posts)
