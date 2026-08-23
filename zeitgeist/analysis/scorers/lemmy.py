"""Lemmy trend scoring: velocity, spread, and movement against last run.

Pure Python on purpose: reproducible and unit-testable, which an LLM's
numeric judgment is not.
"""

from datetime import datetime

from zeitgeist.analysis.scorers.base import (
    LemmyWeights,
    ScoreWeights,
    blend,
    historical_delta,
    normalise,
)
from zeitgeist.models import LemmyMetrics

MIN_AGE_HOURS = 0.5


class LemmyScorer:
    platform = "lemmy"

    def __init__(self, weights: ScoreWeights, now: datetime) -> None:
        self._weights = weights.for_platform("lemmy", LemmyWeights)
        self._now = now

    def score(
        self, per_topic: list[list[LemmyMetrics]], previous: list[float | None]
    ) -> list[float]:
        weights = self._weights

        raw_uv = [self._mean_velocity(g, "score") for g in per_topic]
        raw_cv = [self._mean_velocity(g, "comment_count") for g in per_topic]
        raw_cs = [float(len({m.channel for m in g})) for g in per_topic]

        uv, cv, cs = normalise(raw_uv), normalise(raw_cv), normalise(raw_cs)

        base_total = (
            weights.upvote_velocity + weights.comment_velocity + weights.channel_spread
        )
        bases = [
            (
                weights.upvote_velocity * uv[i]
                + weights.comment_velocity * cv[i]
                + weights.channel_spread * cs[i]
            )
            / base_total
            if base_total
            else 0.0
            for i in range(len(per_topic))
        ]

        deltas = historical_delta(bases, previous)
        return blend(bases, deltas, weights.rank_delta)

    def _mean_velocity(self, group: list[LemmyMetrics], attribute: str) -> float:
        values = []
        for metrics in group:
            hours = (self._now - metrics.created_at).total_seconds() / 3600.0
            values.append(getattr(metrics, attribute) / max(hours, MIN_AGE_HOURS))
        return sum(values) / len(values)
