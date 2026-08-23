"""Scorer registry. A new platform is a new file plus one entry here.

Parallel to `sources/__init__.py`'s BUILDERS: a platform needs an entry in
both, and `tests/test_scorers_registry.py` guards them against drifting.
"""

from collections.abc import Callable
from datetime import datetime

from zeitgeist.analysis.scorers.base import ScoreWeights, TrendScorer
from zeitgeist.analysis.scorers.lemmy import LemmyScorer
from zeitgeist.analysis.scorers.wikipedia import WikipediaScorer

ScorerBuilder = Callable[[ScoreWeights, datetime], TrendScorer]

SCORERS: dict[str, ScorerBuilder] = {
    "lemmy": LemmyScorer,
    "wikipedia": WikipediaScorer,
}


def build_scorer(platform: str, weights: ScoreWeights, now: datetime) -> TrendScorer:
    """Raises KeyError for an unregistered platform — a drift bug, not input."""
    return SCORERS[platform](weights, now)
