"""Shared scoring vocabulary.

`ScoreWeights` lives here rather than in `score.py` because every scorer
needs it and `score.py` imports the scorers — the other direction would be a
cycle.
"""

from typing import Protocol

from pydantic import BaseModel


class ScoreWeights(BaseModel):
    # Within-platform weights, read by the individual scorers.
    upvote_velocity: float = 0.4
    comment_velocity: float = 0.3
    channel_spread: float = 0.3
    rank_delta: float = 0.25
    # Cross-platform weight, read only by the coordinator in score.py.
    corroboration_bonus: float = 0.25


def normalise(values: list[float]) -> list[float]:
    """Min-max normalise. A zero range yields zeros, never a division error."""
    low, high = min(values), max(values)
    if high - low == 0:
        return [0.0] * len(values)
    return [(value - low) / (high - low) for value in values]


def historical_delta(bases: list[float], previous: list[float | None]) -> list[float]:
    """Normalised movement of each topic against its own prior sub-score.

    Defaulting to the topic's own base, not 0.0: an unseen topic has not
    risen, so its delta must be zero rather than full marks.

    `prior` is bound to a local so ty can narrow away the `None` in the
    `is not None` branch — narrowing does not carry across repeated subscript
    expressions like `previous[i]`.
    """
    raw = []
    for i in range(len(bases)):
        prior = previous[i]
        raw.append(bases[i] - (prior if prior is not None else bases[i]))
    return normalise(raw)


def blend(bases: list[float], deltas: list[float], weight: float) -> list[float]:
    """`(1 - weight) * base + weight * delta`, elementwise."""
    return [(1.0 - weight) * bases[i] + weight * deltas[i] for i in range(len(bases))]


class TrendScorer[M: BaseModel](Protocol):
    """One platform's opinion of how much each topic is trending.

    `per_topic[i]` holds that platform's metrics within topic `i`, and is
    never empty: the coordinator passes only topics where this platform is
    present. `previous[i]` is the same topic's sub-score from the most recent
    prior run, or None if it has no history for this platform.

    The return value is normalised **within this platform** across the topics
    given, which is what makes different platforms' scores comparable.
    """

    platform: str

    def score(
        self, per_topic: list[list[M]], previous: list[float | None]
    ) -> list[float]: ...
