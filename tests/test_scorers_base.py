"""The blend helpers shared by every scorer.

Extracted from lemmy.py and wikipedia.py, which carried the same delta block
verbatim. These tests pin the behaviour that duplication encoded, so a future
edit to one scorer cannot quietly change the other.
"""

import pytest
from pydantic import ValidationError

from zeitgeist.analysis.scorers.base import (
    BlueskyWeights,
    LemmyWeights,
    ScoreWeights,
    WikipediaWeights,
    blend,
    historical_delta,
)


def test_historical_delta_defaults_an_unseen_topic_to_its_own_base():
    """The tempting `previous[i] or 0.0` would read an unseen topic as having
    risen from nothing, handing every first-run topic full marks. Both topics
    here are flat, so a correct implementation returns a degenerate range and
    `normalise` yields zeros. Under `or 0.0` the second topic's raw delta
    becomes 1.0 and the two separate.
    """
    assert historical_delta([0.5, 1.0], [0.5, None]) == [0.0, 0.0]


def test_historical_delta_ranks_a_riser_above_a_faller():
    """Sign and direction: subtracting in the wrong order would invert this."""
    deltas = historical_delta([1.0, 0.0], [0.0, 1.0])

    assert deltas[0] > deltas[1]


def test_historical_delta_normalises_to_the_unit_interval():
    """Every sub-score the coordinator averages must share one scale."""
    deltas = historical_delta([0.9, 0.5, 0.1], [0.1, 0.5, 0.9])

    assert min(deltas) == 0.0
    assert max(deltas) == 1.0


@pytest.mark.parametrize(
    "bases,deltas,weight,want",
    [
        # Exact values rather than an ordering: a swapped pair of arguments
        # still produces a plausible ordering but the wrong numbers.
        ([1.0, 0.0], [0.0, 1.0], 0.25, [0.75, 0.25]),
        # The two boundaries, where one term has to vanish entirely.
        ([0.3, 0.7], [1.0, 1.0], 0.0, [0.3, 0.7]),
        ([0.3, 0.7], [1.0, 0.0], 1.0, [1.0, 0.0]),
    ],
)
def test_blend_weights_base_against_delta(bases, deltas, weight, want):
    assert blend(bases, deltas, weight) == want


def test_for_platform_rejects_a_mismatched_pairing():
    """A registry-drift guard: reaching this means SCORERS and `platforms`
    disagree about what a platform is, which is a bug in this package rather
    than bad input.
    """
    with pytest.raises(TypeError):
        ScoreWeights().for_platform("lemmy", WikipediaWeights)


def test_for_platform_raises_for_an_unregistered_platform():
    """Matches build_scorer, so both halves of the same drift bug fail alike."""
    with pytest.raises(KeyError):
        ScoreWeights().for_platform("myspace", LemmyWeights)


def test_platforms_are_weighted_independently():
    """The point of the split. One platform's rank_delta must be settable
    without touching another's — impossible under the flat model, where the
    two shared one field.
    """
    weights = ScoreWeights(
        platforms={
            "lemmy": LemmyWeights(rank_delta=0.9),
            "wikipedia": WikipediaWeights(rank_delta=0.1),
        }
    )

    assert weights.for_platform("lemmy", LemmyWeights).rank_delta == 0.9
    assert weights.for_platform("wikipedia", WikipediaWeights).rank_delta == 0.1


def test_platform_weights_reject_a_weight_belonging_to_another_platform():
    """STRICT on the weights models. Without extra="forbid", `upvote_velocity`
    mistyped under wikipedia would be dropped in silence and the run would
    score with defaults nobody chose.
    """
    with pytest.raises(ValidationError):
        WikipediaWeights(upvote_velocity=0.5)


def test_score_weights_reject_the_per_platform_fields_they_used_to_carry():
    """The migration hazard this split creates. `upvote_velocity` and its three
    neighbours moved off ScoreWeights onto LemmyWeights; without extra="forbid"
    a call site left on the old flat shape is accepted, its value dropped in
    silence, and the run scores with defaults nobody chose.
    """
    with pytest.raises(ValidationError):
        ScoreWeights(upvote_velocity=0.0)


def test_the_default_mapping_covers_every_registered_scorer():
    """A platform with a scorer but no default weights is a KeyError partway
    through a run, after the fetch has already been paid for.
    """
    from zeitgeist.analysis.scorers import SCORERS

    assert set(SCORERS) <= set(ScoreWeights().platforms)


def test_a_partial_platform_override_is_filled_from_the_defaults():
    """Without this, `platforms={"bluesky": ...}` would silently drop lemmy
    and wikipedia's defaults, surfacing later as a KeyError mid-run — after
    the fetch that run needed is already paid for.
    """
    weights = ScoreWeights(platforms={"bluesky": BlueskyWeights(like_velocity=0.9)})

    assert weights.for_platform("lemmy", LemmyWeights) == LemmyWeights()
    assert weights.for_platform("bluesky", BlueskyWeights).like_velocity == 0.9


def test_a_platform_key_disagreeing_with_its_discriminator_is_rejected():
    """`{"lemmy": {"platform": "bluesky"}}` is bad input, not a gap to fill —
    letting it through would mean `for_platform("lemmy", LemmyWeights)`
    raises TypeError deep inside a scorer instead of at construction.
    """
    with pytest.raises(ValidationError):
        ScoreWeights(platforms={"lemmy": BlueskyWeights()})
