import logging

from zeitgeist.analysis.sentiment import SentimentJudgement, judge_topics, select
from zeitgeist.config import DEFAULT_SENTIMENT_WEIGHTS
from zeitgeist.llm.base import FakeLLMProvider, LLMError
from zeitgeist.models import ScoredTopic, Sentiment, Topic


def _topic(tid: str, score: float = 0.5) -> Topic:
    return Topic(
        id=tid,
        label=tid.title(),
        summary=f"About {tid}.",
        post_ids=["p1"],
        trend_score=score,
    )


def _judgement(sentiment: Sentiment, meme: float = 0.8) -> SentimentJudgement:
    return SentimentJudgement(
        primary_sentiment=sentiment,
        secondary_sentiments=[],
        valence=0.5,
        meme_potential=meme,
    )


def _scored(tid: str, sentiment: Sentiment, trend: float, meme: float = 1.0):
    return ScoredTopic(
        id=tid,
        label=tid.title(),
        summary="",
        post_ids=["p1"],
        trend_score=trend,
        primary_sentiment=sentiment,
        valence=0.0,
        meme_potential=meme,
    )


def test_carries_every_judgement_field_onto_the_scored_topic():
    """valence and meme_potential are distinct values here on purpose: if
    the mapping crosses them, selection silently ranks by the wrong number
    and nothing else in the suite notices.
    """
    judgement = SentimentJudgement(
        primary_sentiment=Sentiment.CUTE,
        secondary_sentiments=[Sentiment.FUNNY],
        valence=0.25,
        meme_potential=0.75,
    )
    scored = judge_topics([_topic("cats", 0.5)], FakeLLMProvider([judgement]))[0]

    assert scored.primary_sentiment == Sentiment.CUTE
    assert scored.secondary_sentiments == [Sentiment.FUNNY]
    assert scored.valence == 0.25
    assert scored.meme_potential == 0.75


def test_preserves_the_topic_it_was_given():
    """The trend score computed in the previous stage must survive into
    selection; recomputing or defaulting it would discard the scoring work.
    """
    provider = FakeLLMProvider([_judgement(Sentiment.CUTE)])
    scored = judge_topics([_topic("cats", 0.75)], provider)[0]
    assert scored.id == "cats"
    assert scored.trend_score == 0.75
    assert scored.summary == "About cats."


def test_calls_provider_once_per_topic():
    provider = FakeLLMProvider([_judgement(Sentiment.FUNNY)] * 3)
    judge_topics([_topic("a"), _topic("b"), _topic("c")], provider)
    assert len(provider.calls) == 3


def test_prompt_contains_label_and_summary():
    provider = FakeLLMProvider([_judgement(Sentiment.AWE)])
    judge_topics([_topic("cats")], provider)
    assert "Cats" in provider.calls[0].prompt
    assert "About cats." in provider.calls[0].prompt


def test_failed_topic_is_dropped_and_run_continues():
    provider = FakeLLMProvider([LLMError("nope"), _judgement(Sentiment.CUTE)])
    scored = judge_topics([_topic("dropped"), _topic("kept")], provider)
    assert [t.id for t in scored] == ["kept"]


def test_score_components_survive_onto_the_scored_topic():
    """score_components crosses Topic -> ScoredTopic via
    **topic.model_dump(); a refactor to manual field listing would drop the
    entire scoring stage's output silently, since nothing else checks it.
    """
    topic = _topic("cats").model_copy(
        update={"score_components": {"base": 0.5, "rank_delta": 0.1}}
    )
    provider = FakeLLMProvider([_judgement(Sentiment.CUTE)])
    scored = judge_topics([topic], provider)[0]
    assert scored.score_components == {"base": 0.5, "rank_delta": 0.1}


def test_select_handles_a_weights_dict_missing_some_sentiments():
    """weights.get(sentiment, 1.0) is the live partial-weights safety net.
    The only existing coverage of that fallback is Settings.weight_for,
    which production code never calls — select is what actually runs.
    """
    topics = [
        _scored("has_weight", Sentiment.FUNNY, trend=0.5),
        _scored("no_weight", Sentiment.SAD, trend=0.5),
    ]
    partial_weights = {Sentiment.FUNNY: 2.0}  # SAD deliberately absent
    picked = select(topics, partial_weights, top_n=2)
    assert len(picked) == 2
    # SAD falls back to neutral (1.0); FUNNY's weight of 2.0 ranks it first.
    assert picked[0].id == "has_weight"


def test_failed_topic_logs_the_exception_detail(caplog):
    """A static 'dropping' message with no exception text gives no clue
    whether the judgement call failed on auth, schema, or timeout.
    """
    provider = FakeLLMProvider([LLMError("sentiment call failed")])
    with caplog.at_level(logging.WARNING):
        judge_topics([_topic("dropped")], provider)
    assert "sentiment call failed" in caplog.text


def test_select_prefers_positive_sentiment_at_equal_trend():
    topics = [
        _scored("grim", Sentiment.OUTRAGE, trend=0.8),
        _scored("sweet", Sentiment.HEARTWARMING, trend=0.8),
    ]
    picked = select(topics, DEFAULT_SENTIMENT_WEIGHTS, top_n=2)
    assert [t.id for t in picked] == ["sweet", "grim"]


def test_strongly_trending_negative_topic_still_wins():
    topics = [
        _scored("grim", Sentiment.OUTRAGE, trend=1.0),
        _scored("sweet", Sentiment.HEARTWARMING, trend=0.4),
    ]
    picked = select(topics, DEFAULT_SENTIMENT_WEIGHTS, top_n=2)
    assert picked[0].id == "grim"


def test_no_sentiment_is_excluded_outright():
    topics = [_scored(s.value, s, trend=0.5) for s in Sentiment]
    picked = select(topics, DEFAULT_SENTIMENT_WEIGHTS, top_n=len(topics))
    assert len(picked) == len(topics)


def test_select_truncates_to_top_n_and_ranks_from_one():
    topics = [
        _scored("a", Sentiment.FUNNY, trend=0.9),
        _scored("b", Sentiment.FUNNY, trend=0.5),
        _scored("c", Sentiment.FUNNY, trend=0.1),
    ]
    picked = select(topics, DEFAULT_SENTIMENT_WEIGHTS, top_n=2)
    assert [t.id for t in picked] == ["a", "b"]
    assert [t.final_rank for t in picked] == [1, 2]


def test_meme_potential_affects_ordering():
    topics = [
        _scored("dull", Sentiment.FUNNY, trend=0.9, meme=0.1),
        _scored("punchy", Sentiment.FUNNY, trend=0.6, meme=1.0),
    ]
    picked = select(topics, DEFAULT_SENTIMENT_WEIGHTS, top_n=2)
    assert picked[0].id == "punchy"


def test_select_on_empty_input_returns_empty():
    assert select([], DEFAULT_SENTIMENT_WEIGHTS, top_n=5) == []
