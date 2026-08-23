from datetime import UTC, datetime

from zeitgeist.analysis.scorers import build_scorer
from zeitgeist.analysis.scorers.base import ScoreWeights, normalise
from zeitgeist.models import LemmyMetrics

NOW = datetime(2026, 8, 16, 12, 0, tzinfo=UTC)


def _m(score: int, comments: int, channel: str, age_hours: float) -> LemmyMetrics:
    return LemmyMetrics(
        score=score,
        comment_count=comments,
        channel=channel,
        created_at=datetime.fromtimestamp(NOW.timestamp() - age_hours * 3600, tz=UTC),
    )


def test_normalise_maps_min_to_zero_and_max_to_one():
    assert normalise([2.0, 4.0, 6.0]) == [0.0, 0.5, 1.0]


def test_normalise_returns_zeros_for_a_flat_range():
    """Never a division error, and never NaN reaching the ranking."""
    assert normalise([3.0, 3.0]) == [0.0, 0.0]


def test_faster_upvote_velocity_scores_higher():
    """Two topics, same age and comments; only score differs."""
    scorer = build_scorer("lemmy", ScoreWeights(), NOW)

    scores = scorer.score(
        per_topic=[
            [_m(score=1000, comments=10, channel="a@h", age_hours=2)],
            [_m(score=10, comments=10, channel="b@h", age_hours=2)],
        ],
        previous=[None, None],
    )

    assert scores[0] > scores[1]


def test_wider_channel_spread_scores_higher():
    """Same velocity in both topics; only the number of distinct channels
    differs. Discriminates channel_spread from a count of items."""
    scorer = build_scorer("lemmy", ScoreWeights(), NOW)

    scores = scorer.score(
        per_topic=[
            [
                _m(score=100, comments=10, channel="a@h", age_hours=2),
                _m(score=100, comments=10, channel="b@h", age_hours=2),
            ],
            [
                _m(score=100, comments=10, channel="c@h", age_hours=2),
                _m(score=100, comments=10, channel="c@h", age_hours=2),
            ],
        ],
        previous=[None, None],
    )

    assert scores[0] > scores[1]


def test_a_topic_with_no_history_is_not_treated_as_maximally_rising():
    """previous=None must default to the topic's own base, giving a delta of
    zero. Discriminates that from the tempting `previous or 0.0`, which would
    hand every first-run topic a full-marks rise."""
    scorer = build_scorer("lemmy", ScoreWeights(), NOW)

    risen = scorer.score(
        per_topic=[
            [_m(score=100, comments=10, channel="a@h", age_hours=2)],
            [_m(score=50, comments=10, channel="b@h", age_hours=2)],
        ],
        previous=[0.0, None],
    )
    fresh = scorer.score(
        per_topic=[
            [_m(score=100, comments=10, channel="a@h", age_hours=2)],
            [_m(score=50, comments=10, channel="b@h", age_hours=2)],
        ],
        previous=[None, None],
    )

    assert risen[0] > fresh[0]


def test_scores_stay_within_the_unit_interval():
    """The whole cross-platform comparison rests on this range."""
    scorer = build_scorer("lemmy", ScoreWeights(), NOW)

    scores = scorer.score(
        per_topic=[
            [_m(score=100000, comments=9000, channel="a@h", age_hours=0.1)],
            [_m(score=1, comments=0, channel="b@h", age_hours=500)],
            [_m(score=50, comments=5, channel="c@h", age_hours=10)],
        ],
        previous=[None, None, None],
    )

    assert all(0.0 <= s <= 1.0 for s in scores)


def test_the_age_floor_stops_a_minutes_old_item_dominating():
    """Ported from test_analysis_score.py, which Task 6 rewrites. Without
    MIN_AGE_HOURS an item seconds old divides by nearly zero and swamps the
    run purely for being new. Three topics, so normalisation has a real range
    and the assertion cannot pass on all-zeros: with the floor the first two
    are indistinguishable, without it the first takes the top of the range
    away from the genuinely busy topic.
    """
    scorer = build_scorer("lemmy", ScoreWeights(), NOW)

    scores = scorer.score(
        per_topic=[
            [_m(score=100, comments=10, channel="a@h", age_hours=0.01)],
            [_m(score=100, comments=10, channel="b@h", age_hours=0.5)],
            [_m(score=1000, comments=100, channel="c@h", age_hours=1)],
        ],
        previous=[None, None, None],
    )

    assert scores[0] == scores[1]
    assert scores[2] > scores[0]


def test_a_topic_averages_its_items_rather_than_summing_them():
    """Ported from test_analysis_score.py. Summing would let a topic climb on
    item count alone: five ordinary items would outrank one genuinely
    fast-moving item.
    """
    scorer = build_scorer("lemmy", ScoreWeights(), NOW)

    scores = scorer.score(
        per_topic=[
            [_m(score=100, comments=10, channel="a@h", age_hours=1) for _ in range(5)],
            [_m(score=400, comments=40, channel="b@h", age_hours=1)],
        ],
        previous=[None, None],
    )

    assert scores[1] > scores[0]


def test_weights_redirect_the_score_between_the_terms_they_name():
    """Ported from test_weights_are_configurable. Each weight must multiply
    the term it is named after. The defaults sum to 1.0, which makes
    `/ base_total` a no-op and lets a swapped pair of weight fields go
    unnoticed — so this run zeroes the upvote weight, and the heavily
    discussed topic must win despite having none of the upvotes.
    """
    weights = ScoreWeights(
        upvote_velocity=0.0,
        comment_velocity=1.0,
        channel_spread=0.0,
        rank_delta=0.0,
    )
    scorer = build_scorer("lemmy", weights, NOW)

    scores = scorer.score(
        per_topic=[
            [_m(score=10000, comments=1, channel="a@h", age_hours=1)],
            [_m(score=1, comments=10000, channel="b@h", age_hours=1)],
        ],
        previous=[None, None],
    )

    assert scores == [0.0, 1.0]


def test_registry_rejects_an_unregistered_platform():
    import pytest

    with pytest.raises(KeyError):
        build_scorer("myspace", ScoreWeights(), NOW)
