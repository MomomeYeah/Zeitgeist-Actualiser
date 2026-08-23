"""Wikipedia trend scoring: position, and movement against last run.

Pageviews carry no comments, no channel, and no per-item age, so velocity is
undefined here. Position and delta are the whole signal.
"""

from datetime import datetime

from zeitgeist.analysis.scorers.base import ScoreWeights, normalise
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

        # Defaulting to the topic's own base, not 0.0: an unseen topic has
        # not risen, so its delta must be zero rather than full marks.
        # `prior` is bound to a local so ty can narrow away the `None` in the
        # `is not None` branch — narrowing does not carry across repeated
        # subscript expressions like `previous[i]`.
        raw_delta = []
        for i in range(len(per_topic)):
            prior = previous[i]
            raw_delta.append(bases[i] - (prior if prior is not None else bases[i]))
        delta = normalise(raw_delta)

        w = self._weights.rank_delta
        return [(1.0 - w) * bases[i] + w * delta[i] for i in range(len(per_topic))]
