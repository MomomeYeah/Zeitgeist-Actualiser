"""Final selection.

Ranking is on trend score alone. Sentiment weighting used to sit here,
favouring cheerful topics, and `meme_potential` multiplied on top of it. Both
suppressed topics before there was any evidence that suppression helps, and
both operated on a judgement made from a label rather than from what people
said. `meme_potential` is still recorded on the dossier for inspection; it is
deliberately not applied.
"""

from zeitgeist.models import ScoredTopic, Topic


def select(scored: list[Topic], top_n: int) -> list[ScoredTopic]:
    """Rank by trend score and keep the top N."""
    ranked = sorted(scored, key=lambda topic: topic.trend_score, reverse=True)
    return [
        ScoredTopic(**topic.model_dump(), final_rank=position)
        for position, topic in enumerate(ranked[:top_n], start=1)
    ]
