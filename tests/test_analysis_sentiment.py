"""Selection. Sentiment judgement now happens during distillation, where it
has the replies in front of it instead of a label.
"""

from typing import Any

from zeitgeist.analysis.sentiment import select
from zeitgeist.models import Dossier, Register, Sentiment, Topic


def _topic(topic_id: str, score: float) -> Topic:
    return Topic(
        id=topic_id, label=topic_id, summary="s", item_ids=["i"], trend_score=score
    )


def _dossier(**overrides: Any) -> Dossier:
    base: dict[str, Any] = {
        "what_happened": "Canada imposed tariffs on $30B of US goods.",
        "key_entities": ["Canada"],
        "conversation_summary": "People treat it as overdue.",
        "conversation_register": Register.DUNKING,
        "event_sentiment": Sentiment.SCHADENFREUDE,
        "valence": -0.2,
        "meme_potential": 0.8,
    }
    return Dossier(**(base | overrides))


def test_topics_are_ranked_by_trend_score():
    ranked = select([_topic("low", 0.2), _topic("high", 0.9)], top_n=2)
    assert [topic.id for topic in ranked] == ["high", "low"]


def test_final_rank_is_one_based_and_in_order():
    ranked = select([_topic("a", 0.9), _topic("b", 0.5), _topic("c", 0.1)], top_n=3)
    assert [topic.final_rank for topic in ranked] == [1, 2, 3]


def test_only_the_top_n_survive():
    ranked = select([_topic("a", 0.9), _topic("b", 0.5), _topic("c", 0.1)], top_n=2)
    assert [topic.id for topic in ranked] == ["a", "b"]


def test_a_grim_topic_outranks_a_cheerful_one_on_trend_score_alone():
    """Weights are deliberately gone, and so is the meme_potential multiplier.
    Both topics carry a dossier here: without one this test is
    indistinguishable from test_topics_are_ranked_by_trend_score and could not
    notice either factor being reintroduced — there would be nothing for the
    reintroduced factor to read. Under the old formula cheerful wins twice
    over, on the sentiment weight and on meme potential alike.
    """
    grim = _topic("grim", 0.9).model_copy(
        update={
            "dossier": _dossier(
                conversation_register=Register.MOURNING,
                event_sentiment=Sentiment.SAD,
                valence=-0.9,
                meme_potential=0.2,
            )
        }
    )
    cheerful = _topic("cheerful", 0.8).model_copy(
        update={
            "dossier": _dossier(
                conversation_register=Register.DELIGHT,
                event_sentiment=Sentiment.CUTE,
                valence=0.9,
                meme_potential=0.9,
            )
        }
    )
    assert [t.id for t in select([cheerful, grim], top_n=2)] == ["grim", "cheerful"]


def test_the_dossier_survives_selection():
    """Compared by value, not identity: `select` rebuilds each topic as a
    ScoredTopic, so the dossier is revalidated rather than passed through.
    An identity check would also pass vacuously when both are None.
    """
    topic = _topic("a", 0.9)
    topic = topic.model_copy(update={"dossier": _dossier()})
    [ranked] = select([topic], top_n=1)
    assert ranked.dossier == topic.dossier
    assert ranked.dossier is not None


def test_no_topics_yields_no_selection():
    assert select([], top_n=5) == []
