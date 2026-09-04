"""Selection. Sentiment judgement happens during distillation, where it has
the replies in front of it instead of a label.
"""

from typing import Any

import pytest

from zeitgeist.analysis.sentiment import select
from zeitgeist.models import Dossier, Register, Sentiment, Topic


def _dossier(**overrides: Any) -> Dossier:
    base: dict[str, Any] = {
        "what_happened": "Canada imposed tariffs on $30B of US goods.",
        "key_entities": ["Canada"],
        "conversation_summary": "People treat it as overdue.",
        "conversation_register": Register.DUNKING,
        "event_sentiment": Sentiment.SCHADENFREUDE,
        "meme_potential": 0.5,
    }
    return Dossier(**{**base, **overrides})


def _topic(topic_id: str, score: float, meme: float | None = None) -> Topic:
    return Topic(
        id=topic_id,
        label=topic_id,
        summary="s",
        item_ids=["i"],
        trend_status="trending",
        trend_score=score,
        dossier=None if meme is None else _dossier(meme_potential=meme),
    )


def _order(topics: list[Topic], weight: float = 0.3) -> list[str]:
    return [
        t.id for t in select(topics, top_n=len(topics), meme_potential_weight=weight)
    ]


def test_topics_are_ranked_by_the_blended_score():
    assert _order([_topic("low", 0.2, 0.2), _topic("high", 0.9, 0.9)]) == [
        "high",
        "low",
    ]


def test_final_rank_is_one_based_and_in_order():
    ranked = select(
        [_topic("a", 0.9), _topic("b", 0.5), _topic("c", 0.1)],
        top_n=3,
        meme_potential_weight=0.3,
    )
    assert [topic.final_rank for topic in ranked] == [1, 2, 3]


def test_only_the_top_n_survive():
    ranked = select(
        [_topic("a", 0.9), _topic("b", 0.5), _topic("c", 0.1)],
        top_n=2,
        meme_potential_weight=0.3,
    )
    assert [topic.id for topic in ranked] == ["a", "b"]


def test_meme_potential_can_overturn_a_stronger_trend():
    """The point of blending at all. At weight 0.3: the loud dull topic
    scores 0.7*0.9 + 0.3*0.05 = 0.645, the quieter funny one
    0.7*0.7 + 0.3*0.95 = 0.775. Ranking on trend alone would invert this.
    """
    assert _order([_topic("loud_dull", 0.9, 0.05), _topic("funny", 0.7, 0.95)]) == [
        "funny",
        "loud_dull",
    ]


def test_a_big_trend_is_not_annihilated_by_low_meme_potential():
    """A weighted average, never a product. Multiplying — what the original
    code did — would score the big topic 0.9*0.05 = 0.045 and bury it under
    a topic a fifth its size. Averaging reorders without excluding.
    """
    assert _order([_topic("big", 0.9, 0.05), _topic("tiny", 0.2, 0.6)]) == [
        "big",
        "tiny",
    ]


def test_weight_zero_ranks_on_trend_score_alone():
    assert _order(
        [_topic("loud_dull", 0.9, 0.05), _topic("funny", 0.7, 0.95)], weight=0.0
    ) == ["loud_dull", "funny"]


def test_weight_one_ranks_on_meme_potential_alone():
    assert _order(
        [_topic("loud_dull", 0.9, 0.05), _topic("funny", 0.7, 0.95)], weight=1.0
    ) == ["funny", "loud_dull"]


def test_a_missing_judgement_ranks_on_trend_score_rather_than_as_zero():
    """The model can return an unusable number, and the dormant path has no
    dossier at all. Reading either as 0.0 would bury a topic for a fault
    that says nothing about it: at weight 0.3 a 0.9 trend would drop to
    0.63 and lose to a 0.7 trend scoring 0.775.
    """
    assert _order([_topic("nojudgement", 0.9, None), _topic("judged", 0.7, 0.95)]) == [
        "nojudgement",
        "judged",
    ]


def test_a_dossier_whose_meme_potential_is_none_is_treated_the_same():
    topic = _topic("t", 0.9)
    topic = topic.model_copy(update={"dossier": _dossier(meme_potential=None)})
    assert _order([topic, _topic("judged", 0.7, 0.95)]) == ["t", "judged"]


def test_the_dossier_survives_selection():
    topic = _topic("a", 0.9, 0.5)
    [ranked] = select([topic], top_n=1, meme_potential_weight=0.3)
    assert ranked.dossier == topic.dossier
    assert ranked.dossier is not None


def test_no_topics_yields_no_selection():
    assert select([], top_n=5, meme_potential_weight=0.3) == []


@pytest.mark.parametrize("weight", [0.0, 0.3, 1.0])
def test_selection_is_stable_for_a_single_topic(weight):
    [ranked] = select([_topic("only", 0.4, 0.4)], top_n=5, meme_potential_weight=weight)
    assert ranked.final_rank == 1
