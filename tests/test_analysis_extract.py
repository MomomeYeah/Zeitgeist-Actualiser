import logging
from datetime import UTC, datetime

import pytest

from zeitgeist.analysis.extract import (
    ItemTags,
    TagExtraction,
    _build_prompt,
    extract_tags,
)
from zeitgeist.llm.base import FakeLLMProvider, LLMError
from zeitgeist.models import Item, LemmyMetrics


def test_returns_tags_keyed_by_item_id(sample_items):
    items = sample_items[:2]
    provider = FakeLLMProvider(
        [
            TagExtraction(
                assignments=[
                    ItemTags(item_id=items[0].source_id, tags=["cats", "pets"]),
                    ItemTags(item_id=items[1].source_id, tags=["dogs"]),
                ]
            )
        ]
    )
    tags = extract_tags(items, provider, batch_size=40)
    assert tags[items[0].source_id] == ["cats", "pets"]
    assert tags[items[1].source_id] == ["dogs"]


def test_splits_into_batches(sample_items):
    provider = FakeLLMProvider(
        [TagExtraction(assignments=[]), TagExtraction(assignments=[])]
    )
    extract_tags(sample_items[:6], provider, batch_size=3)
    assert len(provider.calls) == 2


def test_prompt_carries_the_title_and_the_id_the_model_must_echo(sample_items):
    """The model keys its answers by item id, so dropping the id from the
    prompt makes every assignment unmatchable and silently yields no tags.
    """
    item = sample_items[0]
    provider = FakeLLMProvider([TagExtraction(assignments=[])])
    extract_tags([item], provider, batch_size=40)

    prompt = provider.calls[0].prompt
    assert item.title in prompt
    assert item.source_id in prompt
    assert item.metrics.channel in prompt


def test_prompt_renders_the_id_context_and_title_on_one_line():
    """The prompt previously carried post.channel. Wikipedia has no channel,
    so it carries item.context — which for Lemmy is still the channel. The
    expected line is written out by hand rather than built from
    `item.context`: deriving it would let an emptied context satisfy both
    sides of the assertion, which is the break this test exists to catch.
    """
    item = Item(
        source_id="p999",
        title="Test Lemmy post",
        permalink="https://lemmy.world/post/999",
        fetched_at=datetime(2026, 8, 16, 12, 0, tzinfo=UTC),
        metrics=LemmyMetrics(
            score=100,
            comment_count=5,
            channel="memes@lemmy.world",
            created_at=datetime(2026, 8, 16, 9, 0, tzinfo=UTC),
        ),
    )

    prompt = _build_prompt([item])

    assert "- id=p999 | memes@lemmy.world | Test Lemmy post" in prompt


def test_channel_rendered_without_platform_prefix():
    """Platform-neutral context rendering: Lemmy items show as
    memes@lemmy.world, not r/memes@lemmy.world. A platform-specific prefix
    would be misleading now that context is shared across platforms.
    """
    item = Item(
        source_id="p1",
        title="A post",
        permalink="https://lemmy.world/post/1",
        fetched_at=datetime(2026, 8, 16, 12, 0, tzinfo=UTC),
        metrics=LemmyMetrics(
            score=1,
            comment_count=1,
            channel="memes@lemmy.world",
            created_at=datetime(2026, 8, 16, 9, 0, tzinfo=UTC),
        ),
    )

    assert "| memes@lemmy.world |" in _build_prompt([item])
    assert "r/memes" not in _build_prompt([item])


def test_caps_tags_per_item(sample_items):
    """Bounds the vocabulary handed to the reduce stage; an uncapped model
    response would inflate the consolidation prompt without limit.
    """
    items = sample_items[:1]
    provider = FakeLLMProvider(
        [
            TagExtraction(
                assignments=[
                    ItemTags(
                        item_id=items[0].source_id,
                        tags=["one", "two", "three", "four", "five"],
                    )
                ]
            )
        ]
    )
    assert extract_tags(items, provider, batch_size=40) == {
        items[0].source_id: ["one", "two", "three"]
    }


def test_failed_batch_is_skipped_not_fatal(sample_items):
    items = sample_items[:6]
    provider = FakeLLMProvider(
        [
            LLMError("batch one exploded"),
            TagExtraction(
                assignments=[ItemTags(item_id=items[3].source_id, tags=["kept"])]
            ),
        ]
    )
    tags = extract_tags(items, provider, batch_size=3)
    assert tags == {items[3].source_id: ["kept"]}


def test_failed_batch_logs_the_exception_detail(sample_items, caplog):
    """A static 'skipping' message with no exception text gives no clue
    whether a failure during a live run was auth, schema, or timeout.
    """
    items = sample_items[:6]
    provider = FakeLLMProvider(
        [
            LLMError("batch one exploded"),
            TagExtraction(assignments=[]),
        ]
    )
    with caplog.at_level(logging.WARNING):
        extract_tags(items, provider, batch_size=3)
    assert "batch one exploded" in caplog.text


def test_prompt_formatting_bug_is_not_swallowed_as_a_failed_batch(
    sample_items, monkeypatch
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
        extract_tags(sample_items[:3], provider, batch_size=40)


def test_unknown_item_ids_from_model_are_discarded(sample_items):
    items = sample_items[:1]
    provider = FakeLLMProvider(
        [
            TagExtraction(
                assignments=[
                    ItemTags(item_id=items[0].source_id, tags=["real"]),
                    ItemTags(item_id="hallucinated", tags=["fake"]),
                ]
            )
        ]
    )
    tags = extract_tags(items, provider, batch_size=40)
    assert tags == {items[0].source_id: ["real"]}


def test_tags_are_lowercased_and_deduplicated(sample_items):
    items = sample_items[:1]
    provider = FakeLLMProvider(
        [
            TagExtraction(
                assignments=[
                    ItemTags(item_id=items[0].source_id, tags=["Cats", "cats", "PETS"])
                ]
            )
        ]
    )
    assert extract_tags(items, provider, batch_size=40) == {
        items[0].source_id: ["cats", "pets"]
    }


def test_empty_input_makes_no_calls():
    provider = FakeLLMProvider()
    assert extract_tags([], provider) == {}
    assert provider.calls == []
