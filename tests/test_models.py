from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from zeitgeist.models import (
    Item,
    LemmyMetrics,
    MediaBrief,
    ScoredTopic,
    Sentiment,
    Topic,
    WikipediaMetrics,
)


def _lemmy_item(**overrides: Any) -> Item:
    metrics = LemmyMetrics(
        score=10,
        comment_count=2,
        channel="technology@lemmy.world",
        created_at=datetime(2026, 8, 16, 9, 0, tzinfo=UTC),
    )
    fields: dict[str, Any] = {
        "source_id": "abc123",
        "title": "A post",
        "permalink": "https://lemmy.world/post/1",
        "fetched_at": datetime(2026, 8, 16, 12, 0, tzinfo=UTC),
        "metrics": metrics,
    }
    return Item(**{**fields, **overrides})


def _scored(**overrides: Any) -> ScoredTopic:
    defaults: dict[str, Any] = dict(
        id="cats",
        label="Cats",
        summary="Cat things.",
        item_ids=["abc123"],
        primary_sentiment=Sentiment.CUTE,
        valence=0.5,
        meme_potential=0.5,
    )
    return ScoredTopic(**{**defaults, **overrides})


def test_item_platform_reads_through_to_metrics():
    assert _lemmy_item().platform == "lemmy"


def test_item_context_is_the_channel_for_lemmy():
    """The extraction prompt uses `context` where it used to use `channel`.
    Asserting the value, not just that it exists, is what stops a future
    edit silently emptying the hint the model reads.
    """
    assert _lemmy_item().context == "technology@lemmy.world"


def test_metrics_union_dispatches_on_platform_discriminator():
    """A raw dict must deserialise to the right concrete metrics class.
    This is what makes the JSON checkpoints round-trip: without the
    discriminator Pydantic picks whichever member validates first, so a
    Wikipedia measurement could come back as something else entirely."""
    item = Item.model_validate(
        {
            "source_id": "en.wikipedia:Cats:2026-08-20",
            "title": "Cats",
            "permalink": "https://en.wikipedia.org/wiki/Cats",
            "fetched_at": "2026-08-16T12:00:00Z",
            "metrics": {
                "platform": "wikipedia",
                "views": 411486,
                "rank": 4,
                "measured_on": "2026-08-20",
            },
        }
    )
    assert isinstance(item.metrics, WikipediaMetrics)
    assert item.metrics.rank == 4


def test_metrics_union_rejects_an_unknown_platform():
    with pytest.raises(ValidationError):
        Item.model_validate(
            {
                "source_id": "x",
                "title": "A post",
                "permalink": "https://example.com/1",
                "fetched_at": "2026-08-16T12:00:00Z",
                "metrics": {"platform": "myspace", "score": 1},
            }
        )


def test_lemmy_metrics_reject_an_unknown_field():
    """STRICT must survive the move into the union — a field a future
    platform slips in should fail at the boundary, not vanish."""
    with pytest.raises(ValidationError):
        LemmyMetrics.model_validate(
            {
                "platform": "lemmy",
                "score": 1,
                "comment_count": 1,
                "channel": "c@h",
                "created_at": "2026-08-16T09:00:00Z",
                "author": "someone",
            }
        )


# The complete specified field set of each model, written out by hand rather
# than derived from the model, so that a change to a model fails this test.
# Catches two breaks at once: a PII field such as `author` creeping in, and a
# field the checkpoint format depends on quietly disappearing. `metrics` now
# carries the platform-specific half, so it needs the same guard as `Item`.
# Replaces the old POST_FIELDS / test_post_carries_exactly_the_specified_fields.
_ENGAGEMENT_FIELDS = {"platform", "score", "comment_count", "channel", "created_at"}


@pytest.mark.parametrize(
    "model,want",
    [
        (
            Item,
            {
                "source_id",
                "title",
                "body_excerpt",
                "permalink",
                "fetched_at",
                "metrics",
            },
        ),
        (LemmyMetrics, _ENGAGEMENT_FIELDS),
        (WikipediaMetrics, {"platform", "views", "rank", "measured_on"}),
    ],
)
def test_models_carry_exactly_the_specified_fields(model, want):
    assert set(model.model_fields) == want


@pytest.mark.parametrize("field", ["author", "username", "user_id", "titel"])
def test_item_rejects_undeclared_fields(field):
    """Without extra="forbid", Pydantic silently drops unknown keys — so a
    typo'd field name or an author slipped in by a new source would pass
    unnoticed rather than failing loudly.
    """
    with pytest.raises(ValidationError):
        _lemmy_item(**{field: "somebody"})


def test_topic_rejects_the_old_post_ids_field():
    """extra='forbid' means a stale checkpoint fails loudly rather than
    silently losing its item list. Named in the spec as intended behaviour."""
    with pytest.raises(ValidationError):
        Topic.model_validate(
            {"id": "cats", "label": "Cats", "summary": "", "post_ids": ["abc123"]}
        )


@pytest.mark.parametrize("valence", [-1.01, 1.01, 5.0, -5.0])
def test_valence_outside_minus_one_to_one_is_rejected(valence):
    with pytest.raises(ValidationError):
        _scored(valence=valence)


@pytest.mark.parametrize("valence", [-1.0, 0.0, 1.0])
def test_valence_accepts_its_boundaries(valence):
    assert _scored(valence=valence).valence == valence


@pytest.mark.parametrize("meme_potential", [-0.01, 1.01])
def test_meme_potential_outside_zero_to_one_is_rejected(meme_potential):
    with pytest.raises(ValidationError):
        _scored(meme_potential=meme_potential)


@pytest.mark.parametrize("meme_potential", [0.0, 1.0])
def test_meme_potential_accepts_its_boundaries(meme_potential):
    assert _scored(meme_potential=meme_potential).meme_potential == meme_potential


def test_topic_defaults_leave_room_for_the_scoring_stage():
    """score_topics fills these in later; the defaults are what let a topic
    exist between consolidation and scoring.
    """
    topic = Topic(id="cats", label="Cats", summary="Cat things.", item_ids=["abc123"])
    assert topic.trend_score == 0.0
    assert topic.score_components == {}


def test_scored_topic_defaults_leave_room_for_the_selection_stage():
    scored = _scored()
    assert scored.secondary_sentiments == []
    assert scored.final_rank == 0


def test_scored_topic_accepts_every_field_of_a_scored_topic():
    """judge_topics constructs ScoredTopic(**topic.model_dump(), ...). If the
    two models drift apart, that call breaks — here rather than mid-run.
    """
    topic = Topic(
        id="cats",
        label="Cats",
        summary="Cat things.",
        item_ids=["abc123"],
        trend_score=0.7,
        score_components={"base": 0.7},
    )
    scored = ScoredTopic(
        **topic.model_dump(),
        primary_sentiment=Sentiment.CUTE,
        valence=0.5,
        meme_potential=0.5,
    )
    assert scored.trend_score == 0.7
    assert scored.score_components == {"base": 0.7}


def test_media_brief_rejects_undeclared_fields():
    with pytest.raises(ValidationError):
        MediaBrief(
            topic_id="cats",
            template_id="drake",
            caption_slots={"rejected": "Dogs"},
            rationale="",
            image_url="http://example.com/not-a-real-field",
        )
