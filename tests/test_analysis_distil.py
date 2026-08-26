"""Distillation: one LLM call per trend, producing a topic and its dossier."""

from datetime import UTC, datetime
from typing import Any

import pytest

from zeitgeist.analysis.distil import DistilError, DossierDraft, distil_topics
from zeitgeist.config import Settings
from zeitgeist.llm.base import FakeLLMProvider, LLMError
from zeitgeist.models import (
    BlueskyMetrics,
    Item,
    PostEvidence,
    Register,
    Reply,
    Sentiment,
    TrendEvidence,
    TrendInfo,
)

NOW = datetime(2026, 8, 26, tzinfo=UTC)


def _settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "sources": ["bluesky"],
        "distil_concurrency": 1,
        "phrase_min_authors": 3,
    }
    return Settings(**(base | overrides))


def _item(source_id: str, text: str = "something happened") -> Item:
    return Item(
        source_id=source_id,
        title=text,
        permalink=f"https://bsky.app/profile/x/post/{source_id}",
        fetched_at=NOW,
        metrics=BlueskyMetrics(
            like_count=10,
            reply_count=2,
            repost_count=1,
            trend="A trend",
            status="trending",
            created_at=NOW,
        ),
    )


def _reply(text: str, author: str = "a", likes: int = 1) -> Reply:
    return Reply(text=text, like_count=likes, created_at=NOW, author_key=author)


def _evidence(
    name: str = "Canada announces retaliatory tariffs",
    *,
    replies: list[Reply] | None = None,
    posts: int = 1,
) -> TrendEvidence:
    return TrendEvidence(
        trend=TrendInfo(
            topic_id=f"id-{name}",
            display_name=name,
            description="Canada hits back after trade talks collapsed.",
            category="business",
            post_count=4298,
            started_at=NOW,
            status="stale",
        ),
        posts=[
            PostEvidence(item=_item(f"p{i}"), replies=replies or [])
            for i in range(posts)
        ],
    )


def _draft(**overrides: Any) -> DossierDraft:
    base: dict[str, Any] = {
        "what_happened": "Canada imposed tariffs on $30B of US goods.",
        "key_entities": ["Canada"],
        "conversation_summary": "People treat it as overdue.",
        "conversation_register": Register.DUNKING,
        "secondary_registers": [],
        "event_sentiment": Sentiment.SCHADENFREUDE,
        "valence": -0.2,
        "meme_potential": 0.8,
    }
    return DossierDraft(**(base | overrides))


def test_a_trend_becomes_a_topic_carrying_its_dossier():
    provider = FakeLLMProvider(responses=[_draft()])
    [topic] = distil_topics([_evidence()], provider, _settings())

    assert topic.label == "Canada announces retaliatory tariffs"
    assert topic.id == "canada-announces-retaliatory-tariffs"
    assert topic.item_ids == ["p0"]
    assert topic.dossier is not None
    assert topic.dossier.conversation_register is Register.DUNKING


def test_the_summary_is_what_happened_not_a_tag_confabulation():
    """The whole point: `summary` used to be written from a bag of tags."""
    provider = FakeLLMProvider(responses=[_draft()])
    [topic] = distil_topics([_evidence()], provider, _settings())
    assert topic.summary == "Canada imposed tariffs on $30B of US goods."


def test_mined_phrases_are_attached_rather_than_taken_from_the_model():
    replies = [_reply("elbows up", author=a) for a in ("a", "b", "c", "d")]
    provider = FakeLLMProvider(responses=[_draft()])
    [topic] = distil_topics([_evidence(replies=replies)], provider, _settings())

    assert topic.dossier is not None
    assert [p.text for p in topic.dossier.recurring_phrases] == ["elbows up"]
    assert topic.dossier.recurring_phrases[0].distinct_authors == 4


def test_the_prompt_carries_the_trend_description_and_the_replies():
    replies = [_reply("what a mess", author=a) for a in ("a", "b", "c")]
    provider = FakeLLMProvider(responses=[_draft()])
    distil_topics([_evidence(replies=replies)], provider, _settings())

    prompt = provider.calls[0].prompt
    assert "Canada hits back after trade talks collapsed." in prompt
    assert "what a mess" in prompt


def test_the_prompt_carries_each_posts_engagement():
    """The spec asks for posts "with their engagement". The trend name was
    being repeated in a bracket instead — a constant already stated on the
    prompt's first line, carrying no information — so this must assert the
    actual like/repost/reply counts reach the prompt, not merely that the
    post appears at all.
    """
    provider = FakeLLMProvider(responses=[_draft()])
    distil_topics([_evidence()], provider, _settings())

    prompt = provider.calls[0].prompt
    assert "10 likes, 1 reposts, 2 replies" in prompt


def test_the_prompt_states_how_many_people_used_each_phrase():
    """The counts are what license quoting, so they must reach the model with
    their meanings intact. The two numbers differ here — five uses from four
    accounts — so rendering one in place of the other fails. Equal counts
    would make the swap invisible, and a bare "4" also matches the post count.
    """
    replies = [_reply("elbows up", author=a) for a in ("a", "b", "c", "d")]
    replies.append(_reply("elbows up again", author="a"))
    provider = FakeLLMProvider(responses=[_draft()])
    distil_topics([_evidence(replies=replies)], provider, _settings())

    assert "4 distinct accounts, 5 uses" in provider.calls[0].prompt


def test_replies_are_truncated_to_the_character_budget():
    """Exactly two 500-character replies fit in a 1000-character budget. An
    upper bound alone would pass even if no replies were included at all.
    """
    replies = [_reply("x" * 500, author=f"a{i}") for i in range(50)]
    provider = FakeLLMProvider(responses=[_draft()])
    distil_topics(
        [_evidence(replies=replies)], provider, _settings(distil_char_budget=1000)
    )
    assert provider.calls[0].prompt.count("x" * 500) == 2


def test_the_most_liked_replies_are_the_ones_kept():
    replies = [
        _reply("unpopular take", author="a", likes=1),
        _reply("the one everyone saw", author="b", likes=900),
    ]
    provider = FakeLLMProvider(responses=[_draft()])
    distil_topics(
        [_evidence(replies=replies)], provider, _settings(distil_char_budget=30)
    )
    prompt = provider.calls[0].prompt
    assert "the one everyone saw" in prompt
    assert "unpopular take" not in prompt


def test_break_not_continue_stops_sampling_at_the_first_overflow():
    """`_sample` stops at the first reply that would overflow the budget
    (`break`), rather than skipping it and packing smaller replies from
    further down the list (`continue`). Both are defensible policies, but
    only `break` matches "take the top contiguous slice by likes" -- the
    intended one.

    Budget is 100. The most-liked reply is 40 chars and fits (spent -> 40).
    The second-most-liked is 80 chars, which would bring spent to 120 and
    overflow; under `break` sampling stops there. The third-most-liked is
    20 chars -- small enough that 40 + 20 = 60 <= 100, so it WOULD fit if
    scanning continued past the oversized second reply. Its absence from
    the prompt is what distinguishes the two policies; the first reply's
    presence rules out sampling returning nothing at all.
    """
    replies = [
        _reply("a" * 40, author="a", likes=100),
        _reply("b" * 80, author="b", likes=50),
        _reply("c" * 20, author="c", likes=10),
    ]
    provider = FakeLLMProvider(responses=[_draft()])
    distil_topics(
        [_evidence(replies=replies)], provider, _settings(distil_char_budget=100)
    )
    prompt = provider.calls[0].prompt
    assert "a" * 40 in prompt
    assert "c" * 20 not in prompt


def test_a_failing_trend_is_dropped_and_the_rest_survive():
    provider = FakeLLMProvider(responses=[LLMError("boom"), _draft()])
    topics = distil_topics(
        [_evidence("First"), _evidence("Second")], provider, _settings()
    )
    assert [topic.label for topic in topics] == ["Second"]


def test_every_trend_failing_raises_distil_error():
    """The design spec: "A run in which every trend fails raises, as an
    empty run is a failure rather than a result." Returning `[]` here would
    write empty topics.json/ranked.json/briefs.json and let the CLI print a
    green "Run complete" with 0 memes and no diagnostic — this is the
    realistic failure mode for a local model that cannot hold the response
    schema, since it fails every trend identically.
    """
    provider = FakeLLMProvider(responses=[LLMError("boom"), LLMError("boom")])
    with pytest.raises(DistilError):
        distil_topics([_evidence("First"), _evidence("Second")], provider, _settings())


def test_topic_ids_are_unique_when_two_trends_share_a_label():
    provider = FakeLLMProvider(responses=[_draft(), _draft()])
    topics = distil_topics(
        [_evidence("A trend"), _evidence("A trend")], provider, _settings()
    )
    assert {topic.id for topic in topics} == {"a-trend", "a-trend-2"}


def test_a_trend_with_no_replies_still_produces_a_topic():
    provider = FakeLLMProvider(responses=[_draft()])
    [topic] = distil_topics([_evidence(replies=[])], provider, _settings())
    assert topic.dossier is not None
    assert topic.dossier.recurring_phrases == []


def test_item_ids_cover_every_post_under_the_trend():
    provider = FakeLLMProvider(responses=[_draft()])
    [topic] = distil_topics([_evidence(posts=3)], provider, _settings())
    assert topic.item_ids == ["p0", "p1", "p2"]


def test_no_evidence_means_no_calls():
    provider = FakeLLMProvider(responses=[])
    assert distil_topics([], provider, _settings()) == []
    assert provider.calls == []
