"""Sentiment judgement and final selection.

Weights favour positive output without excluding anything: a sufficiently
strong trend carries a negatively-flavoured topic into the selection, which
is intended. The zeitgeist is not always cheerful, and a tool that only ever
sees the cheerful half is not measuring it.
"""

import logging

from pydantic import BaseModel, Field

from zeitgeist.llm.base import LLMProvider
from zeitgeist.models import ScoredTopic, Sentiment, Topic

log = logging.getLogger(__name__)

SENTIMENT_SYSTEM = (
    "You judge the emotional flavour of a trending topic. Choose the single "
    "primary sentiment that best describes how people feel about it, plus any "
    "secondary sentiments that also apply. Valence runs from -1 (thoroughly "
    "negative) to 1 (thoroughly positive). Meme potential runs from 0 to 1 and "
    "measures how readily the topic yields a joke that would land with people "
    "who have not read the source posts."
)


class SentimentJudgement(BaseModel):
    """The model's read on how a topic feels."""

    primary_sentiment: Sentiment
    secondary_sentiments: list[Sentiment] = Field(default_factory=list)
    valence: float = Field(ge=-1.0, le=1.0)
    meme_potential: float = Field(ge=0.0, le=1.0)


def judge_topics(topics: list[Topic], provider: LLMProvider) -> list[ScoredTopic]:
    """Judge each topic. A topic whose call fails is dropped, not fatal."""
    scored: list[ScoredTopic] = []

    for topic in topics:
        try:
            judgement = provider.complete(
                _build_prompt(topic), SentimentJudgement, system=SENTIMENT_SYSTEM
            )
        except Exception:
            log.warning("Sentiment judgement failed for %r; dropping", topic.label)
            continue

        scored.append(
            ScoredTopic(
                **topic.model_dump(),
                primary_sentiment=judgement.primary_sentiment,
                secondary_sentiments=judgement.secondary_sentiments,
                valence=judgement.valence,
                meme_potential=judgement.meme_potential,
            )
        )

    return scored


def select(
    scored: list[ScoredTopic],
    weights: dict[Sentiment, float],
    top_n: int,
) -> list[ScoredTopic]:
    """Rank by trend x sentiment weight x meme potential, keep the top N."""
    ranked = sorted(
        scored,
        key=lambda topic: (
            topic.trend_score
            * weights.get(topic.primary_sentiment, 1.0)
            * topic.meme_potential
        ),
        reverse=True,
    )
    return [
        topic.model_copy(update={"final_rank": position})
        for position, topic in enumerate(ranked[:top_n], start=1)
    ]


def _build_prompt(topic: Topic) -> str:
    return (
        f"Topic: {topic.label}\n"
        f"Summary: {topic.summary}\n"
        f"Appears in {len(topic.post_ids)} posts.\n\n"
        "Judge this topic's sentiment and meme potential."
    )
