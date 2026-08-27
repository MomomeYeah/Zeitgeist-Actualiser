"""Final selection.

Ranking blends two things on the same scale. `trend_score` is how much
attention a topic is getting, computed by the platform scorers — pure
arithmetic over engagement, deliberately free of any model judgement.
`meme_potential` is the dossier's read on whether the topic yields a joke
that would land on someone who has not read the posts.

The blend lives here rather than in a scorer on purpose. A scorer sees
`Metrics`, not dossiers; `score.py` states that keeping its arithmetic free
of LLM output is deliberate, because that is what makes it reproducible; and
`score_components` is persisted and compared across runs, so it should stay
a record of platform attention rather than a mixture of attention and taste.

A weighted average, not a product. The original code multiplied, which
annihilates: a large trend the model scored 0.05 for meme potential came out
near zero however many people were talking about it. An average reorders
without excluding, which is the intended behaviour — nothing here should
decide a topic is unworthy before there is evidence that suppression helps.

Sentiment weighting used to live here too, favouring cheerful topics. It is
gone: it suppressed topics on a judgement made from a label rather than from
what people actually said.
"""

from zeitgeist.models import ScoredTopic, Topic


def rank_score(topic: Topic, meme_potential_weight: float) -> float:
    """Blend attention with meme potential.

    A topic with no usable `meme_potential` ranks on `trend_score` alone. A
    missing judgement is not evidence of a bad topic — the model may simply
    have returned an unusable number — so it must not be read as a zero,
    which would bury the topic.
    """
    dossier = topic.dossier
    potential = None if dossier is None else dossier.meme_potential
    if potential is None:
        return topic.trend_score
    return (
        1.0 - meme_potential_weight
    ) * topic.trend_score + meme_potential_weight * potential


def select(
    scored: list[Topic], top_n: int, meme_potential_weight: float
) -> list[ScoredTopic]:
    """Rank by the blended score and keep the top N."""
    ranked = sorted(
        scored,
        key=lambda topic: rank_score(topic, meme_potential_weight),
        reverse=True,
    )
    return [
        ScoredTopic(**topic.model_dump(), final_rank=position)
        for position, topic in enumerate(ranked[:top_n], start=1)
    ]
