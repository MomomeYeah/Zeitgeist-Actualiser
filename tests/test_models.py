from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from zeitgeist.models import MediaBrief, Post, ScoredTopic, Sentiment, Topic

# The complete specified field set. Written out by hand rather than derived
# from the model, so that a change to the model fails this test.
POST_FIELDS = {
    "platform",
    "source_id",
    "title",
    "body_excerpt",
    "permalink",
    "score",
    "comment_count",
    "created_at",
    "fetched_at",
    "channel",
}


def _post(**overrides: Any) -> Post:
    defaults: dict[str, Any] = dict(
        platform="reddit",
        source_id="abc123",
        title="Cat learns to open door",
        body_excerpt=None,
        permalink="https://reddit.com/r/cats/abc123",
        score=4200,
        comment_count=311,
        created_at=datetime(2026, 8, 16, 9, 0, tzinfo=UTC),
        fetched_at=datetime(2026, 8, 16, 12, 0, tzinfo=UTC),
        channel="cats",
    )
    return Post(**{**defaults, **overrides})


def _scored(**overrides: Any) -> ScoredTopic:
    defaults: dict[str, Any] = dict(
        id="cats",
        label="Cats",
        summary="Cat things.",
        post_ids=["abc123"],
        primary_sentiment=Sentiment.CUTE,
        valence=0.5,
        meme_potential=0.5,
    )
    return ScoredTopic(**{**defaults, **overrides})


def test_post_carries_exactly_the_specified_fields():
    """Catches two breaks at once: a PII field such as `author` creeping in,
    and a field the checkpoint format depends on quietly disappearing.
    """
    assert set(Post.model_fields) == POST_FIELDS


@pytest.mark.parametrize("field", ["author", "username", "user_id", "titel"])
def test_post_rejects_undeclared_fields(field):
    """Without extra="forbid", Pydantic silently drops unknown keys — so a
    typo'd field name or an author slipped in by a new source would pass
    unnoticed rather than failing loudly.
    """
    with pytest.raises(ValidationError):
        _post(**{field: "somebody"})


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
    topic = Topic(id="cats", label="Cats", summary="Cat things.", post_ids=["abc123"])
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
        post_ids=["abc123"],
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
