"""Wikipedia trend scoring: position, and movement against last run.

Pageviews carry no comments, no channel, and no per-item age, so velocity is
undefined here. Position and delta are the whole signal.
"""

from datetime import datetime

from zeitgeist.analysis.scorers.base import (
    ScoreWeights,
    blend,
    historical_delta,
    normalise,
)
from zeitgeist.models import WikipediaMetrics


class WikipediaScorer:
    platform = "wikipedia"

    def __init__(self, weights: ScoreWeights, now: datetime) -> None:
        self._weights = weights

    def score(
        self, per_topic: list[list[WikipediaMetrics]], previous: list[float | None]
    ) -> list[float]:
        # Negated rather than scaled against a total: normalise establishes
        # the range from what is present, so the maths does not depend on how
        # many articles the run kept or how many filtering removed.
        raw = [-float(min(m.rank for m in group)) for group in per_topic]
        bases = normalise(raw)

        deltas = historical_delta(bases, previous)
        return blend(bases, deltas, self._weights.rank_delta)
