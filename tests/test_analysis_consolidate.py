import logging

import pytest

from zeitgeist.analysis.consolidate import (
    CONSOLIDATE_MAX_TOKENS,
    ConsolidatedTopic,
    Consolidation,
    consolidate,
    slugify,
)
from zeitgeist.llm.base import FakeLLMProvider, LLMError


@pytest.mark.parametrize(
    "label,expected",
    [
        ("Shelter Dog Adoption", "shelter-dog-adoption"),
        ("  Spaced   Out  ", "spaced-out"),
        ("Punctuation! Everywhere?", "punctuation-everywhere"),
        ("", "topic"),
    ],
)
def test_slugify(label, expected):
    assert slugify(label) == expected


def test_groups_posts_by_their_tags():
    tags_by_post = {"p1": ["cats"], "p2": ["kittens"], "p3": ["telescope"]}
    provider = FakeLLMProvider(
        [
            Consolidation(
                topics=[
                    ConsolidatedTopic(
                        label="Cats", summary="Cat things.", tags=["cats", "kittens"]
                    ),
                    ConsolidatedTopic(
                        label="Space", summary="Space things.", tags=["telescope"]
                    ),
                ]
            )
        ]
    )
    topics = consolidate(tags_by_post, provider)

    assert [t.label for t in topics] == ["Cats", "Space"]
    assert sorted(topics[0].post_ids) == ["p1", "p2"]
    assert topics[1].post_ids == ["p3"]


def test_assigns_slug_ids():
    provider = FakeLLMProvider(
        [
            Consolidation(
                topics=[
                    ConsolidatedTopic(label="Shelter Dogs", summary="", tags=["dogs"])
                ]
            )
        ]
    )
    topics = consolidate({"p1": ["dogs"]}, provider)
    assert topics[0].id == "shelter-dogs"


def test_duplicate_slugs_get_numeric_suffixes():
    provider = FakeLLMProvider(
        [
            Consolidation(
                topics=[
                    ConsolidatedTopic(label="Cats", summary="", tags=["a"]),
                    ConsolidatedTopic(label="cats", summary="", tags=["b"]),
                ]
            )
        ]
    )
    topics = consolidate({"p1": ["a"], "p2": ["b"]}, provider)
    assert [t.id for t in topics] == ["cats", "cats-2"]


def test_topics_with_no_matching_posts_are_dropped():
    provider = FakeLLMProvider(
        [
            Consolidation(
                topics=[
                    ConsolidatedTopic(label="Real", summary="", tags=["cats"]),
                    ConsolidatedTopic(label="Phantom", summary="", tags=["nothing"]),
                ]
            )
        ]
    )
    topics = consolidate({"p1": ["cats"]}, provider)
    assert [t.label for t in topics] == ["Real"]


def test_prompt_carries_the_vocabulary_and_not_the_posts():
    """Sending only the tag vocabulary is what keeps this pass inside a small
    local model's context. Leaking post ids back in would defeat that, so the
    ids here are distinctive enough that a substring match cannot pass by luck.
    """
    provider = FakeLLMProvider([Consolidation(topics=[])])
    consolidate({"zzqq-alpha": ["cats"], "zzqq-beta": ["telescope"]}, provider)
    prompt = provider.calls[0].prompt
    assert "cats" in prompt
    assert "telescope" in prompt
    assert "zzqq" not in prompt


def test_matches_returned_tags_case_insensitively():
    """Models routinely title-case their echo of an input tag. Matching
    exactly would drop every post from the topic and the topic with it.
    """
    provider = FakeLLMProvider(
        [
            Consolidation(
                topics=[
                    ConsolidatedTopic(label="Cats", summary="", tags=["Cats", " CATS "])
                ]
            )
        ]
    )
    topics = consolidate({"p1": ["cats"]}, provider)
    assert topics[0].post_ids == ["p1"]

    # Also test the reverse: stored tags that are not normalized,
    # with model echoing lowercase.
    provider = FakeLLMProvider(
        [
            Consolidation(
                topics=[ConsolidatedTopic(label="Cats", summary="", tags=["cats"])]
            )
        ]
    )
    topics = consolidate({"p1": ["Cats"], "p2": [" CATS "]}, provider)
    assert sorted(topics[0].post_ids) == ["p1", "p2"]


def test_failure_returns_empty_list():
    provider = FakeLLMProvider([LLMError("reduce failed")])
    assert consolidate({"p1": ["cats"]}, provider) == []


def test_failure_logs_the_exception_detail(caplog):
    """A static warning with no exception text gives no clue whether the
    reduce stage failed on auth, schema, or timeout.
    """
    provider = FakeLLMProvider([LLMError("reduce failed")])
    with caplog.at_level(logging.WARNING):
        consolidate({"p1": ["cats"]}, provider)
    assert "reduce failed" in caplog.text


def test_empty_input_makes_no_calls():
    provider = FakeLLMProvider()
    assert consolidate({}, provider) == []
    assert provider.calls == []


def test_asks_for_a_token_budget_that_fits_the_whole_vocabulary():
    """Every canonical topic echoes its input tags verbatim, so the reply
    grows with the vocabulary — a 300-post run needs several thousand output
    tokens. On the provider default the reply is cut off, the truncated tool
    call arrives as an empty object, and the run produces no topics at all.
    """
    provider = FakeLLMProvider([Consolidation(topics=[])])
    consolidate({"p1": ["dogs"]}, provider)
    assert provider.calls[0].max_tokens == CONSOLIDATE_MAX_TOKENS
