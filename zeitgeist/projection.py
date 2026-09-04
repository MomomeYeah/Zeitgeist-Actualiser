"""The analyse and evaluate payloads, flattened into columns.

`run_topics` holds nothing that is not already in those payloads — it is
them, in a shape you can filter, sort and join on. A view over
`json_each(payload)` would always agree with its source and never need
rewriting, but the cross-run queries would then parse every run's analyse
payload on every request: at a thousand runs, a hundred megabytes of JSON
per page load.

Pure. No store, no I/O. It is written in the same transaction as the
checkpoint it flattens, which is what keeps the two from disagreeing.
"""

from pydantic import BaseModel

from zeitgeist.analysis.sentiment import rank_score
from zeitgeist.analysis.slug import slugify
from zeitgeist.models import STRICT, Topic, TrendStatus


class TopicRow(BaseModel):
    """One row of `run_topics`."""

    model_config = STRICT

    run_id: str
    topic_id: str
    label: str
    label_slug: str
    trend_status: TrendStatus
    # None where the topic has no dossier — the dormant path, or a stale
    # checkpoint. The topic was still ranked, so the row still exists.
    event_sentiment: str | None
    conversation_register: str | None
    meme_potential: float | None
    trend_score: float
    final_score: float
    final_rank: int
    post_count: int
    top_phrase: str | None
    top_phrase_authors: int | None


def flatten(
    run_id: str, topics: list[Topic], meme_potential_weight: float
) -> list[TopicRow]:
    """Rank every topic and flatten it.

    Every topic, not just the kept ones: the ranking screen draws
    below-the-cut rows with their ranks and scores before dimming them, and
    the evaluate checkpoint holds only the top `top_count`.

    Ranks with `sentiment.rank_score`, which is the same function `select()`
    ranks with, so the first `top_count` rows agree with the evaluate
    checkpoint by construction. A second implementation of the blend here
    would drift from it silently.
    """
    ranked = sorted(
        topics,
        key=lambda topic: rank_score(topic, meme_potential_weight),
        reverse=True,
    )
    return [
        _row(run_id, topic, position, meme_potential_weight)
        for position, topic in enumerate(ranked, start=1)
    ]


def _row(
    run_id: str, topic: Topic, rank: int, meme_potential_weight: float
) -> TopicRow:
    dossier = topic.dossier
    # The phrase the most separate people reached for, not the most repeated:
    # forty uses from three accounts is a dogpile, not a zeitgeist.
    top = (
        max(dossier.recurring_phrases, key=lambda p: p.distinct_authors)
        if dossier is not None and dossier.recurring_phrases
        else None
    )
    return TopicRow(
        run_id=run_id,
        topic_id=topic.id,
        label=topic.label,
        # The cross-run key, normalised the same way topic_scores keys its
        # rows, so recurrence finds a match across runs.
        label_slug=slugify(topic.label),
        trend_status=topic.trend_status,
        event_sentiment=None if dossier is None else dossier.event_sentiment.value,
        conversation_register=(
            None if dossier is None else dossier.conversation_register.value
        ),
        meme_potential=None if dossier is None else dossier.meme_potential,
        trend_score=topic.trend_score,
        final_score=rank_score(topic, meme_potential_weight),
        final_rank=rank,
        post_count=len(topic.item_ids),
        top_phrase=None if top is None else top.text,
        top_phrase_authors=None if top is None else top.distinct_authors,
    )
