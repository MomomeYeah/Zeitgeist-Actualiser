from datetime import UTC, date, datetime

import pytest

from zeitgeist.analysis.scorers import build_scorer
from zeitgeist.analysis.scorers.base import ScoreWeights
from zeitgeist.models import WikipediaMetrics

NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)
DAY = date(2026, 8, 20)


def _m(rank: int, views: int = 1000) -> WikipediaMetrics:
    return WikipediaMetrics(views=views, rank=rank, measured_on=DAY)


def test_a_better_rank_scores_higher():
    """Rank 1 beats rank 500. Discriminates the negation from forgetting it,
    which would invert the entire ranking."""
    scorer = build_scorer("wikipedia", ScoreWeights(), NOW)

    scores = scorer.score(
        per_topic=[[_m(rank=1)], [_m(rank=500)]], previous=[None, None]
    )

    assert scores[0] > scores[1]


def test_a_topic_uses_its_best_ranked_article():
    """min(), not mean or first: a topic containing one rank-2 article and
    one rank-900 article is trending on the strength of the rank-2 one."""
    scorer = build_scorer("wikipedia", ScoreWeights(), NOW)

    scores = scorer.score(
        per_topic=[[_m(rank=900), _m(rank=2)], [_m(rank=400)]],
        previous=[None, None],
    )

    assert scores[0] > scores[1]


def test_a_perennial_topic_does_not_score_as_rising():
    """Two topics at identical ranks; one held that position last run, the
    other is new. This is what neutralises pages like Google that sit in the
    top ten every day, so the source does not need to denylist them."""
    scorer = build_scorer("wikipedia", ScoreWeights(), NOW)

    scores = scorer.score(
        per_topic=[[_m(rank=5)], [_m(rank=5)]],
        previous=[1.0, None],
    )

    assert scores[1] > scores[0]


def test_a_topic_with_no_history_is_not_treated_as_maximally_rising():
    """previous=None must default to the topic's own base, giving a delta of
    zero. Discriminates that from `previous or 0.0`, which hands every
    first-seen article a full-marks rise — the opposite of what rank-delta is
    for, since a brand new entry has not risen against anything.

    wikipedia.py carries its own copy of this default, so the equivalent
    Lemmy test does not cover it. Nonzero bases are essential: with every
    base at 0.0 the two implementations coincide, which is why
    test_a_perennial_topic_does_not_score_as_rising cannot tell them apart.
    """
    scorer = build_scorer("wikipedia", ScoreWeights(), NOW)
    groups = [[_m(rank=1)], [_m(rank=500)]]

    fresh = scorer.score(per_topic=groups, previous=[None, None])
    risen = scorer.score(per_topic=groups, previous=[0.0, None])

    assert fresh[0] == pytest.approx(0.75)
    assert risen[0] == pytest.approx(1.0)


def test_scores_stay_within_the_unit_interval():
    scorer = build_scorer("wikipedia", ScoreWeights(), NOW)

    scores = scorer.score(
        per_topic=[[_m(rank=1)], [_m(rank=1000)], [_m(rank=37)]],
        previous=[0.9, None, 0.1],
    )

    assert all(0.0 <= s <= 1.0 for s in scores)


@pytest.mark.parametrize(
    "views,rank,want",
    [(411486, 4, "411,486 views"), (1000, 999, "1,000 views")],
)
def test_context_reports_views_not_rank(views, rank, want):
    """The hint the extraction prompt carries for a Wikipedia item, standing
    where a Lemmy item carries its channel. Rank is deliberately the odd one
    out in each row: a context built from rank would render "4 views" and
    "999 views" and fail both.

    The thousands separator is pinned on purpose. It is there so the model
    reads the magnitude correctly in the prompt, which makes it behaviour
    rather than incidental formatting.
    """
    assert WikipediaMetrics(views=views, rank=rank, measured_on=DAY).context == want
