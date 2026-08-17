"""Domain models shared across every pipeline stage."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

# Unknown keys are an error, not something to drop quietly. A misspelled field
# in a new Source, or an `author` slipped in by a future platform, should fail
# loudly at the boundary rather than vanish.
STRICT = ConfigDict(extra="forbid")


class Sentiment(StrEnum):
    """Fixed taxonomy so results are comparable across runs."""

    CUTE = "cute"
    HEARTWARMING = "heartwarming"
    FUNNY = "funny"
    AWE = "awe"
    SCHADENFREUDE = "schadenfreude"
    OUTRAGE = "outrage"
    SAD = "sad"
    SCARY = "scary"
    GROSS = "gross"
    CRINGE = "cringe"
    MUNDANE = "mundane"


class Post(BaseModel):
    """A single normalised item from any platform.

    Deliberately carries no author or username: no downstream stage needs it,
    and omitting it keeps the project clear of storing personal data.
    """

    model_config = STRICT

    platform: str
    source_id: str
    title: str
    body_excerpt: str | None = None
    permalink: str
    score: int
    comment_count: int
    created_at: datetime
    fetched_at: datetime
    channel: str


class Topic(BaseModel):
    """A cluster of posts about the same thing."""

    model_config = STRICT

    id: str
    label: str
    summary: str
    post_ids: list[str]
    trend_score: float = 0.0
    score_components: dict[str, float] = Field(default_factory=dict)


class ScoredTopic(Topic):
    """A topic with its sentiment judgement and final ranking attached."""

    primary_sentiment: Sentiment
    secondary_sentiments: list[Sentiment] = Field(default_factory=list)
    valence: float = Field(ge=-1.0, le=1.0)
    meme_potential: float = Field(ge=0.0, le=1.0)
    final_rank: int = 0


class MediaBrief(BaseModel):
    """Instructions for rendering one piece of media."""

    model_config = STRICT

    topic_id: str
    template_id: str
    caption_slots: dict[str, str]
    rationale: str
