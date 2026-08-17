"""Trend scoring. Pure Python on purpose: reproducible and unit-testable,
which an LLM's numeric judgment is not.
"""

from datetime import datetime

from pydantic import BaseModel

from zeitgeist.analysis.consolidate import slugify
from zeitgeist.models import Post, Topic

MIN_AGE_HOURS = 0.5


class ScoreWeights(BaseModel):
    upvote_velocity: float = 0.4
    comment_velocity: float = 0.3
    channel_spread: float = 0.3
    rank_delta: float = 0.25


def score_topics(
    topics: list[Topic],
    posts: list[Post],
    now: datetime,
    previous_scores: dict[str, float],
    weights: ScoreWeights | None = None,
) -> list[Topic]:
    """Attach a trend score and its component breakdown to each topic.

    `previous_scores` is keyed by ``slugify(label)`` (see
    ``Store.previous_scores``), not the raw label, so a topic relabelled
    with different case or punctuation across runs still finds its history.
    """
    weights = weights or ScoreWeights()
    by_id = {post.source_id: post for post in posts}

    live: list[tuple[Topic, list[Post]]] = []
    for topic in topics:
        matched = [by_id[pid] for pid in topic.post_ids if pid in by_id]
        if matched:
            live.append((topic, matched))

    if not live:
        return []

    raw_uv = [_mean_velocity(p, now, "score") for _, p in live]
    raw_cv = [_mean_velocity(p, now, "comment_count") for _, p in live]
    raw_cs = [float(len({post.channel for post in p})) for _, p in live]

    uv, cv, cs = _normalise(raw_uv), _normalise(raw_cv), _normalise(raw_cs)

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
        for i in range(len(live))
    ]

    raw_delta = [
        bases[i] - previous_scores.get(slugify(topic.label), bases[i])
        for i, (topic, _) in enumerate(live)
    ]
    delta = _normalise(raw_delta)

    scored: list[Topic] = []
    for i, (topic, _) in enumerate(live):
        trend = (1.0 - weights.rank_delta) * bases[i] + weights.rank_delta * delta[i]
        scored.append(
            topic.model_copy(
                update={
                    "trend_score": trend,
                    "score_components": {
                        "upvote_velocity": uv[i],
                        "comment_velocity": cv[i],
                        "channel_spread": cs[i],
                        "rank_delta": delta[i],
                        "base": bases[i],
                    },
                }
            )
        )
    return scored


def _mean_velocity(posts: list[Post], now: datetime, attribute: str) -> float:
    values = []
    for post in posts:
        hours = (now - post.created_at).total_seconds() / 3600.0
        values.append(getattr(post, attribute) / max(hours, MIN_AGE_HOURS))
    return sum(values) / len(values)


def _normalise(values: list[float]) -> list[float]:
    """Min-max normalise. A zero range yields zeros, never a division error."""
    low, high = min(values), max(values)
    if high - low == 0:
        return [0.0] * len(values)
    return [(value - low) / (high - low) for value in values]
