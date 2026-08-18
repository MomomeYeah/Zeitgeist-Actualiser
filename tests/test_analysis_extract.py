import logging
from datetime import UTC, datetime

import pytest

from zeitgeist.analysis.extract import (
    PostTags,
    TagExtraction,
    _build_prompt,
    extract_tags,
)
from zeitgeist.llm.base import FakeLLMProvider, LLMError
from zeitgeist.models import Post


def test_returns_tags_keyed_by_post_id(sample_posts):
    posts = sample_posts[:2]
    provider = FakeLLMProvider(
        [
            TagExtraction(
                assignments=[
                    PostTags(post_id=posts[0].source_id, tags=["cats", "pets"]),
                    PostTags(post_id=posts[1].source_id, tags=["dogs"]),
                ]
            )
        ]
    )
    tags = extract_tags(posts, provider, batch_size=40)
    assert tags[posts[0].source_id] == ["cats", "pets"]
    assert tags[posts[1].source_id] == ["dogs"]


def test_splits_into_batches(sample_posts):
    provider = FakeLLMProvider(
        [TagExtraction(assignments=[]), TagExtraction(assignments=[])]
    )
    extract_tags(sample_posts[:6], provider, batch_size=3)
    assert len(provider.calls) == 2


def test_prompt_carries_the_title_and_the_id_the_model_must_echo(sample_posts):
    """The model keys its answers by post id, so dropping the id from the
    prompt makes every assignment unmatchable and silently yields no tags.
    """
    post = sample_posts[0]
    provider = FakeLLMProvider([TagExtraction(assignments=[])])
    extract_tags([post], provider, batch_size=40)

    prompt = provider.calls[0].prompt
    assert post.title in prompt
    assert post.source_id in prompt
    assert post.channel in prompt


def test_channel_rendered_without_platform_prefix():
    """Platform-neutral channel rendering: Lemmy posts show as memes@lemmy.world,
    not r/memes@lemmy.world. A platform-specific prefix would be misleading.
    """
    post = Post(
        platform="lemmy",
        source_id="p999",
        title="Test Lemmy post",
        body_excerpt=None,
        permalink="https://lemmy.world/c/memes",
        score=100,
        comment_count=5,
        created_at=datetime(2026, 8, 16, 12, 0, tzinfo=UTC),
        fetched_at=datetime(2026, 8, 16, 12, 0, tzinfo=UTC),
        channel="memes@lemmy.world",
    )
    prompt = _build_prompt([post])
    assert "memes@lemmy.world" in prompt
    assert "r/memes@lemmy.world" not in prompt


def test_caps_tags_per_post(sample_posts):
    """Bounds the vocabulary handed to the reduce stage; an uncapped model
    response would inflate the consolidation prompt without limit.
    """
    posts = sample_posts[:1]
    provider = FakeLLMProvider(
        [
            TagExtraction(
                assignments=[
                    PostTags(
                        post_id=posts[0].source_id,
                        tags=["one", "two", "three", "four", "five"],
                    )
                ]
            )
        ]
    )
    assert extract_tags(posts, provider, batch_size=40) == {
        posts[0].source_id: ["one", "two", "three"]
    }


def test_failed_batch_is_skipped_not_fatal(sample_posts):
    posts = sample_posts[:6]
    provider = FakeLLMProvider(
        [
            LLMError("batch one exploded"),
            TagExtraction(
                assignments=[PostTags(post_id=posts[3].source_id, tags=["kept"])]
            ),
        ]
    )
    tags = extract_tags(posts, provider, batch_size=3)
    assert tags == {posts[3].source_id: ["kept"]}


def test_failed_batch_logs_the_exception_detail(sample_posts, caplog):
    """A static 'skipping' message with no exception text gives no clue
    whether a failure during a live run was auth, schema, or timeout.
    """
    posts = sample_posts[:6]
    provider = FakeLLMProvider(
        [
            LLMError("batch one exploded"),
            TagExtraction(assignments=[]),
        ]
    )
    with caplog.at_level(logging.WARNING):
        extract_tags(posts, provider, batch_size=3)
    assert "batch one exploded" in caplog.text


def test_prompt_formatting_bug_is_not_swallowed_as_a_failed_batch(
    sample_posts, monkeypatch
):
    """_build_prompt must run outside the try/except around the provider
    call, so a bug in prompt formatting is a real crash rather than being
    misreported as just another failed batch.
    """

    def boom(batch):
        raise ValueError("prompt bug")

    monkeypatch.setattr("zeitgeist.analysis.extract._build_prompt", boom)
    provider = FakeLLMProvider([TagExtraction(assignments=[])])
    with pytest.raises(ValueError, match="prompt bug"):
        extract_tags(sample_posts[:3], provider, batch_size=40)


def test_unknown_post_ids_from_model_are_discarded(sample_posts):
    posts = sample_posts[:1]
    provider = FakeLLMProvider(
        [
            TagExtraction(
                assignments=[
                    PostTags(post_id=posts[0].source_id, tags=["real"]),
                    PostTags(post_id="hallucinated", tags=["fake"]),
                ]
            )
        ]
    )
    tags = extract_tags(posts, provider, batch_size=40)
    assert tags == {posts[0].source_id: ["real"]}


def test_tags_are_lowercased_and_deduplicated(sample_posts):
    posts = sample_posts[:1]
    provider = FakeLLMProvider(
        [
            TagExtraction(
                assignments=[
                    PostTags(post_id=posts[0].source_id, tags=["Cats", "cats", "PETS"])
                ]
            )
        ]
    )
    assert extract_tags(posts, provider, batch_size=40) == {
        posts[0].source_id: ["cats", "pets"]
    }


def test_empty_input_makes_no_calls():
    provider = FakeLLMProvider()
    assert extract_tags([], provider) == {}
    assert provider.calls == []
