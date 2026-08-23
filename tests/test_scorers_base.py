"""The blend helpers shared by every scorer.

Extracted from lemmy.py and wikipedia.py, which carried the same delta block
verbatim. These tests pin the behaviour that duplication encoded, so a future
edit to one scorer cannot quietly change the other.
"""

import pytest

from zeitgeist.analysis.scorers.base import blend, historical_delta


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
