from datetime import UTC, datetime
from typing import Literal

import pytest
from pydantic import ValidationError

from zeitgeist.analysis.score import score_topics
from zeitgeist.analysis.scorers import build_scorer
from zeitgeist.analysis.scorers.base import BlueskyWeights, ScoreWeights
from zeitgeist.models import BlueskyMetrics, Item, Topic

NOW = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)

# Aliased because `status: str` does not type-check against the model's
# Literal field, and ty covers tests/ as part of the definition of done.
Status = Literal["trending", "cooling", "stale"]


def _m(
    *,
    likes: int = 100,
    replies: int = 10,
    reposts: int = 20,
    age_hours: float = 2.0,
    trend: str = "a trend",
    status: Status = "trending",
) -> BlueskyMetrics:
    return BlueskyMetrics(
        like_count=likes,
        reply_count=replies,
        repost_count=reposts,
        trend=trend,
        status=status,
        created_at=datetime.fromtimestamp(NOW.timestamp() - age_hours * 3600, tz=UTC),
    )


def _score(per_topic, previous=None):
    scorer = build_scorer("bluesky", ScoreWeights(), NOW)
    return scorer.score(
        per_topic=per_topic, previous=previous or [None] * len(per_topic)
    )


def test_faster_like_velocity_scores_higher():
    """One axis at a time: replies, reposts, age and status are all equal."""
    scores = _score([[_m(likes=10000)], [_m(likes=10)]])

    assert scores[0] > scores[1]


def test_faster_reply_velocity_scores_higher():
    scores = _score([[_m(replies=10000)], [_m(replies=10)]])

    assert scores[0] > scores[1]


def test_faster_repost_velocity_scores_higher():
    """Reposts are Bluesky's spread signal, replacing Lemmy's channel_spread.
    Without a repost term this pair is indistinguishable.
    """
    scores = _score([[_m(reposts=10000)], [_m(reposts=10)]])

    assert scores[0] > scores[1]


def test_velocity_is_per_hour_rather_than_absolute():
    """The older topic has twice the raw engagement and a fifth the rate.
    Summing raw counts would invert this.
    """
    scores = _score(
        [
            [_m(likes=100, replies=100, reposts=100, age_hours=10)],
            [_m(likes=50, replies=50, reposts=50, age_hours=1)],
        ]
    )

    assert scores[1] > scores[0]


def test_a_topic_averages_its_posts_rather_than_summing_them():
    """Summing would let a topic climb on post count alone: five ordinary
    posts would outrank one genuinely fast-moving post.
    """
    scores = _score(
        [
            [_m(likes=100, replies=10, reposts=20, age_hours=1) for _ in range(5)],
            [_m(likes=400, replies=40, reposts=80, age_hours=1)],
        ]
    )

    assert scores[1] > scores[0]


@pytest.mark.parametrize(
    "higher,lower",
    [("trending", "cooling"), ("cooling", "stale"), ("trending", "stale")],
)
def test_status_orders_topics_with_an_identical_base(higher, lower):
    """Every engagement figure is equal, so the status term is the only thing
    that can separate these.
    """
    scores = _score([[_m(status=higher)], [_m(status=lower)]])

    assert scores[0] > scores[1]


def test_a_topic_spanning_trending_and_stale_scores_as_trending():
    """Max, not mean. Under mean, topic 0 averages to 0.5 and ties with the
    two cooling posts, so this pair is exactly what discriminates them.
    """
    scores = _score(
        [
            [_m(status="trending", trend="x"), _m(status="stale", trend="y")],
            [_m(status="cooling", trend="p"), _m(status="cooling", trend="q")],
        ]
    )

    assert scores[0] > scores[1]


def test_a_uniformly_trending_run_outscores_a_uniformly_stale_one():
    """The regression test for NOT normalising the status term.

    Min-max over a list where every entry is equal returns zeros by design,
    so under normalisation these two runs would produce identical scores and
    the axis would fall silent exactly when every trend agrees. Ranking cannot
    catch this — only the values can.
    """
    trending = _score([[_m(likes=100)], [_m(likes=50)]])
    stale = _score([[_m(likes=100, status="stale")], [_m(likes=50, status="stale")]])

    assert trending[0] > stale[0]
    assert trending[1] > stale[1]


def test_previous_sub_scores_are_ignored():
    """Bluesky reports its own movement, so history is redundant. Passing
    wildly different histories must not move the output at all.
    """
    per_topic = [[_m(likes=100)], [_m(likes=50)]]

    assert _score(per_topic, previous=[None, None]) == _score(
        per_topic, previous=[0.0, 1.0]
    )


def test_scores_stay_within_the_unit_interval():
    """The whole cross-platform comparison rests on this range."""
    scores = _score(
        [
            [_m(likes=500000, replies=90000, reposts=90000, age_hours=0.1)],
            [_m(likes=1, replies=0, reposts=0, age_hours=500, status="stale")],
            [_m(likes=50, replies=5, reposts=5, age_hours=10, status="cooling")],
        ]
    )

    assert all(0.0 <= s <= 1.0 for s in scores)


def test_the_age_floor_stops_a_minutes_old_post_dominating():
    """Without MIN_AGE_HOURS a post seconds old divides by nearly zero and
    swamps the run purely for being new. Three topics, so normalisation has a
    real range and the assertion cannot pass on all-zeros.
    """
    scores = _score(
        [
            [_m(likes=100, replies=10, reposts=20, age_hours=0.01)],
            [_m(likes=100, replies=10, reposts=20, age_hours=0.5)],
            [_m(likes=1000, replies=100, reposts=200, age_hours=1)],
        ]
    )

    assert scores[0] == scores[1]
    assert scores[2] > scores[0]


def test_weights_redirect_the_score_between_the_terms_they_name():
    """The defaults sum to 1.0, which makes the rescale a no-op and lets a
    swapped pair of weight fields go unnoticed. Zeroing likes and reposts
    means the heavily replied topic must win despite having neither.
    """
    weights = ScoreWeights(
        platforms={
            "bluesky": BlueskyWeights(
                like_velocity=0.0,
                reply_velocity=1.0,
                repost_velocity=0.0,
                rank_delta=0.0,
            )
        }
    )
    scorer = build_scorer("bluesky", weights, NOW)

    scores = scorer.score(
        per_topic=[
            [_m(likes=10000, replies=1, reposts=10000)],
            [_m(likes=1, replies=10000, reposts=1)],
        ],
        previous=[None, None],
    )

    assert scores == [0.0, 1.0]


@pytest.mark.parametrize(
    "like_w,reply_w,repost_w,want",
    [
        # Sum 3.0: without the rescale the winning topic's base is 3.0 and
        # blend carries the score straight out of the unit interval.
        (1.0, 1.0, 1.0, [1.0, 0.0]),
        # Sum 0.0: the `if base_total else 0.0` guard, otherwise a
        # ZeroDivisionError the moment all three velocities are zeroed.
        (0.0, 0.0, 0.0, [0.0, 0.0]),
    ],
)
def test_the_base_is_rescaled_by_the_weights_it_was_built_from(
    like_w, reply_w, repost_w, want
):
    """Every other weighting test uses weights summing to 1.0, which makes the
    rescale an exact no-op. These do not.
    """
    weights = ScoreWeights(
        platforms={
            "bluesky": BlueskyWeights(
                like_velocity=like_w,
                reply_velocity=reply_w,
                repost_velocity=repost_w,
                rank_delta=0.0,
            )
        }
    )
    scorer = build_scorer("bluesky", weights, NOW)

    scores = scorer.score(
        per_topic=[
            [_m(likes=1000, replies=1000, reposts=1000, age_hours=1)],
            [_m(likes=1, replies=1, reposts=1, age_hours=1)],
        ],
        previous=[None, None],
    )

    assert scores == want


def test_metrics_context_is_the_trend_name():
    """extract.py puts `context` in its prompt, and a Bluesky post is often
    incomprehensible without the trend that gives it its referent.
    """
    assert _m(trend="US-Canada trade talks collapse").context == (
        "US-Canada trade talks collapse"
    )


def test_a_bluesky_only_topic_survives_the_content_bearing_filter():
    """Unlike Wikipedia, a Bluesky post carries text a caption can be written
    from, so it must be able to originate a topic rather than only corroborate.
    Asserting the ClassVar restates the declaration one line below where it is
    written; this is the behaviour that depends on it — score_topics drops any
    topic no content-bearing platform saw.
    """
    items = [
        Item(
            source_id=f"at://did:plc:x/app.bsky.feed.post/{n}",
            title=f"post {n}",
            permalink=f"https://bsky.app/profile/did:plc:x/post/{n}",
            fetched_at=NOW,
            metrics=_m(likes=100 * (n + 1)),
        )
        for n in range(2)
    ]
    topics = [
        Topic(id=f"t{n}", label=f"T{n}", summary="", item_ids=[items[n].source_id])
        for n in range(2)
    ]

    scored = score_topics(topics, items, NOW, previous={})

    assert [topic.id for topic in scored] == ["t0", "t1"]


def test_metrics_reject_an_unknown_status():
    """`status` indexes STATUS_MOVEMENT directly, so a fourth value Bluesky
    starts sending must fail at the boundary rather than as a KeyError in the
    middle of a scoring run. model_validate rather than the constructor
    because ty rejects a bad Literal before pydantic ever sees it.
    """
    with pytest.raises(ValidationError):
        BlueskyMetrics.model_validate(
            {
                "platform": "bluesky",
                "like_count": 100,
                "reply_count": 10,
                "repost_count": 20,
                "trend": "a trend",
                "status": "smouldering",
                "created_at": "2026-08-23T10:00:00Z",
            }
        )
