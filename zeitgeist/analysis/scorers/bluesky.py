"""Bluesky trend scoring: engagement velocity, and the platform's own status.

Pure Python on purpose: reproducible and unit-testable, which an LLM's
numeric judgment is not.
"""

from datetime import datetime

from zeitgeist.analysis.scorers.base import (
    BlueskyWeights,
    ScoreWeights,
    blend,
    normalise,
)
from zeitgeist.models import BlueskyMetrics

MIN_AGE_HOURS = 0.5

# Bluesky reports movement directly, so unlike the other scorers this one
# never consults the previous run.
STATUS_MOVEMENT = {"trending": 1.0, "cooling": 0.5, "stale": 0.0}


class BlueskyScorer:
    platform = "bluesky"

    def __init__(self, weights: ScoreWeights, now: datetime) -> None:
        self._weights = weights.for_platform("bluesky", BlueskyWeights)
        self._now = now

    def score(
        self, per_topic: list[list[BlueskyMetrics]], previous: list[float | None]
    ) -> list[float]:
        """`previous` is unused: Bluesky supplies its own movement term, which
        is better informed than a diff of our normalised scores and works on a
        first run when there is no history. WikipediaScorer likewise ignores
        `now`; the protocol offers both to every scorer and using them is
        optional.
        """
        weights = self._weights

        lv = normalise([self._mean_velocity(g, "like_count") for g in per_topic])
        rv = normalise([self._mean_velocity(g, "reply_count") for g in per_topic])
        pv = normalise([self._mean_velocity(g, "repost_count") for g in per_topic])

        base_total = (
            weights.like_velocity + weights.reply_velocity + weights.repost_velocity
        )
        bases = [
            (
                weights.like_velocity * lv[i]
                + weights.reply_velocity * rv[i]
                + weights.repost_velocity * pv[i]
            )
            / base_total
            if base_total
            else 0.0
            for i in range(len(per_topic))
        ]

        # Max rather than mean: a topic appearing in one trending and one
        # stale trend is trending.
        #
        # Deliberately NOT normalised, unlike every other movement term here.
        # 0.0/0.5/1.0 mean fixed things, and all 25 trends can share a status
        # — in which case min-max returns zeros and the axis falls silent
        # exactly when it has the most to say.
        movement = [max(STATUS_MOVEMENT[m.status] for m in g) for g in per_topic]

        return blend(bases, movement, weights.rank_delta)

    def _mean_velocity(self, group: list[BlueskyMetrics], attribute: str) -> float:
        values = []
        for metrics in group:
            hours = (self._now - metrics.created_at).total_seconds() / 3600.0
            values.append(getattr(metrics, attribute) / max(hours, MIN_AGE_HOURS))
        return sum(values) / len(values)
