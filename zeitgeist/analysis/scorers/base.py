"""Shared scoring vocabulary.

`ScoreWeights` lives here rather than in `score.py` because every scorer
needs it and `score.py` imports the scorers — the other direction would be a
cycle.
"""

from typing import Annotated, Literal, Protocol

from pydantic import BaseModel, Field

from zeitgeist.models import STRICT


class PlatformWeights(BaseModel):
    """Weights every scorer has, because every scorer blends the same way.

    `rank_delta` sits here rather than on each subclass because it is
    structural: a scorer computes a base from its own metrics, then blends
    that base against a movement term. The duplication this replaced is the
    evidence.

    STRICT (`extra="forbid"`) is deliberate. Once weights arrive as a nested
    mapping, a key typed against the wrong platform — `upvote_velocity` under
    `wikipedia` — would otherwise be dropped in silence.
    """

    model_config = STRICT

    rank_delta: float = 0.25


class LemmyWeights(PlatformWeights):
    platform: Literal["lemmy"] = "lemmy"

    upvote_velocity: float = 0.4
    comment_velocity: float = 0.3
    channel_spread: float = 0.3


class WikipediaWeights(PlatformWeights):
    """No fields of its own. Pageviews carry no velocity and no spread, so
    position and movement are the whole signal — which the base already
    covers.
    """

    platform: Literal["wikipedia"] = "wikipedia"


PlatformWeightsUnion = Annotated[
    LemmyWeights | WikipediaWeights,
    Field(discriminator="platform"),
]


class ScoreWeights(BaseModel):
    model_config = STRICT

    # The one weight the coordinator itself reads. Not a platform's opinion,
    # so it does not belong in the per-platform mapping.
    corroboration_bonus: float = 0.25
    platforms: dict[str, PlatformWeightsUnion] = Field(
        default_factory=lambda: {
            "lemmy": LemmyWeights(),
            "wikipedia": WikipediaWeights(),
        }
    )

    def for_platform[W: PlatformWeights](self, platform: str, expected: type[W]) -> W:
        """This platform's weights, narrowed to the type its scorer needs.

        Scorers take the whole ScoreWeights and narrow here rather than
        declaring a narrowed parameter type: SCORERS holds builders of one
        uniform Callable type, and narrowing a parameter is a contravariance
        violation that ty rejects on assignment into that dict.

        The isinstance check is a registry-drift guard, not a cast. Reaching
        it means SCORERS and `platforms` disagree about what a platform is,
        which is a bug in this package rather than bad input — same spirit as
        build_scorer's KeyError, which the subscript below raises for a
        platform that has no entry at all.
        """
        weights = self.platforms[platform]
        if not isinstance(weights, expected):
            raise TypeError(
                f"{platform} weights are {type(weights).__name__}, "
                f"expected {expected.__name__}"
            )
        return weights


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
