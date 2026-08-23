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
    mean_velocity,
    normalise,
)
from zeitgeist.models import LemmyMetrics


class LemmyScorer:
    platform = "lemmy"

    def __init__(self, weights: ScoreWeights, now: datetime) -> None:
        self._weights = weights.for_platform("lemmy", LemmyWeights)
        self._now = now

    def score(
        self, per_topic: list[list[LemmyMetrics]], previous: list[float | None]
    ) -> list[float]:
        weights = self._weights

        raw_uv = [mean_velocity(g, "score", self._now) for g in per_topic]
        raw_cv = [mean_velocity(g, "comment_count", self._now) for g in per_topic]
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
