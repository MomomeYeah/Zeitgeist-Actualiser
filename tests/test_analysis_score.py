from datetime import UTC, datetime, timedelta

from zeitgeist.analysis.score import ScoreWeights, score_topics
from zeitgeist.models import Post, Topic

NOW = datetime(2026, 8, 16, 12, 0, tzinfo=UTC)


def _post(pid: str, score: int, comments: int, channel: str, hours: float) -> Post:
    return Post(
        platform="reddit",
        source_id=pid,
        title=f"Post {pid}",
        permalink=f"https://reddit.com/{pid}",
        score=score,
        comment_count=comments,
        created_at=NOW - timedelta(hours=hours),
        fetched_at=NOW,
        channel=channel,
    )


def _topic(tid: str, post_ids: list[str]) -> Topic:
    return Topic(id=tid, label=tid.title(), summary="", post_ids=post_ids)


def test_faster_topic_scores_higher():
    posts = [
        _post("a", 1000, 100, "cats", hours=1),
        _post("b", 1000, 100, "dogs", hours=20),
    ]
    topics = [_topic("fast", ["a"]), _topic("slow", ["b"])]
    scored = {t.id: t for t in score_topics(topics, posts, NOW, {})}
    assert scored["fast"].trend_score > scored["slow"].trend_score


def test_components_are_recorded():
    posts = [_post("a", 100, 10, "cats", hours=2)]
    scored = score_topics([_topic("t", ["a"])], posts, NOW, {})
    assert set(scored[0].score_components) == {
        "upvote_velocity",
        "comment_velocity",
        "channel_spread",
        "rank_delta",
        "base",
    }


def test_identical_topics_normalise_to_zero_not_nan():
    posts = [
        _post("a", 100, 10, "cats", hours=2),
        _post("b", 100, 10, "cats", hours=2),
    ]
    scored = score_topics([_topic("x", ["a"]), _topic("y", ["b"])], posts, NOW, {})
    for topic in scored:
        assert topic.score_components["upvote_velocity"] == 0.0
        assert topic.trend_score == 0.0


def test_no_history_gives_zero_rank_delta():
    posts = [_post("a", 100, 10, "cats", hours=2)]
    scored = score_topics([_topic("t", ["a"])], posts, NOW, previous_scores={})
    assert scored[0].score_components["rank_delta"] == 0.0


def test_rising_topic_beats_falling_topic_with_equal_base():
    posts = [
        _post("a", 100, 10, "cats", hours=2),
        _post("b", 100, 10, "dogs", hours=2),
    ]
    topics = [_topic("riser", ["a"]), _topic("faller", ["b"])]
    previous = {"Riser": 0.0, "Faller": 1.0}
    scored = {t.id: t for t in score_topics(topics, posts, NOW, previous)}
    assert scored["riser"].trend_score > scored["faller"].trend_score


def test_wider_channel_spread_scores_higher():
    posts = [
        _post("a", 100, 10, "cats", hours=2),
        _post("b", 100, 10, "dogs", hours=2),
        _post("c", 100, 10, "aww", hours=2),
    ]
    topics = [_topic("wide", ["a", "b"]), _topic("narrow", ["c"])]
    scored = {t.id: t for t in score_topics(topics, posts, NOW, {})}
    assert scored["wide"].trend_score > scored["narrow"].trend_score


def test_age_floor_stops_a_minutes_old_post_dominating():
    """Without MIN_AGE_HOURS a post seconds old divides by nearly zero and
    swamps the run purely for being new. Three topics, so normalisation has
    a real range and the assertion cannot pass on all-zeros.
    """
    posts = [
        _post("a", 100, 10, "cats", hours=0.01),
        _post("b", 100, 10, "cats", hours=0.5),
        _post("c", 1000, 100, "cats", hours=1),
    ]
    topics = [
        _topic("brandnew", ["a"]),
        _topic("halfhour", ["b"]),
        _topic("big", ["c"]),
    ]
    scored = {t.id: t for t in score_topics(topics, posts, NOW, {})}

    assert scored["brandnew"].trend_score == scored["halfhour"].trend_score
    assert scored["big"].trend_score > scored["brandnew"].trend_score


def test_a_topic_averages_its_posts_rather_than_summing_them():
    """Summing would let a topic climb on post count alone: five ordinary
    posts would outrank one genuinely fast-moving post.
    """
    posts = [_post(f"m{n}", 100, 10, "cats", hours=1) for n in range(5)]
    posts.append(_post("f", 400, 40, "dogs", hours=1))
    topics = [
        _topic("many", [f"m{n}" for n in range(5)]),
        _topic("fast", ["f"]),
    ]
    scored = {t.id: t for t in score_topics(topics, posts, NOW, {})}
    assert scored["fast"].trend_score > scored["many"].trend_score


def test_topics_with_no_known_posts_are_dropped():
    posts = [_post("a", 100, 10, "cats", hours=2)]
    topics = [_topic("real", ["a"]), _topic("ghost", ["missing"])]
    assert [t.id for t in score_topics(topics, posts, NOW, {})] == ["real"]


def test_empty_input_returns_empty():
    assert score_topics([], [], NOW, {}) == []


def test_weights_are_configurable():
    posts = [
        _post("a", 10000, 1, "cats", hours=1),
        _post("b", 1, 10000, "dogs", hours=1),
    ]
    topics = [_topic("upvoted", ["a"]), _topic("discussed", ["b"])]
    weights = ScoreWeights(
        upvote_velocity=0.0, comment_velocity=1.0, channel_spread=0.0, rank_delta=0.0
    )
    scored = {t.id: t for t in score_topics(topics, posts, NOW, {}, weights)}
    assert scored["discussed"].trend_score > scored["upvoted"].trend_score
