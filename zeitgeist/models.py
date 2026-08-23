"""Domain models shared across every pipeline stage."""

from datetime import date, datetime
from enum import StrEnum
from typing import Annotated, ClassVar, Literal

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


class LemmyMetrics(BaseModel):
    """Engagement as Lemmy reports it."""

    model_config = STRICT

    platform: Literal["lemmy"] = "lemmy"
    # Whether this platform supplies text a caption can be written from.
    # Attention-measuring platforms set False and cannot originate topics.
    content_bearing: ClassVar[bool] = True

    score: int
    comment_count: int
    channel: str
    created_at: datetime

    @property
    def context(self) -> str:
        """One-line hint for the extraction prompt, meaningful per platform."""
        return self.channel


class WikipediaMetrics(BaseModel):
    """Attention as Wikimedia pageviews report it.

    Declared here, alongside Lemmy, even though no source produces it until
    Task 9: `Metrics` needs two members for the discriminator to be a union
    at all, and this is the second content shape the envelope exists for.

    No comments, no communities, and no per-item creation date — an article
    is years old while its spike is one day. `measured_on` is the day the
    measurement covers, which is the only temporal fact this platform
    actually supplies.
    """

    model_config = STRICT

    platform: Literal["wikipedia"] = "wikipedia"
    # No body text, so a Wikipedia-only topic gives the sentiment stage
    # nothing to judge. The coordinator drops such topics.
    content_bearing: ClassVar[bool] = False

    views: int
    rank: int
    measured_on: date

    @property
    def context(self) -> str:
        return f"{self.views:,} views"


# Named because the source, the model and the scorer all have to agree on
# this set. `saturating` is undocumented by Bluesky but real; see STATUS_MAP
# in sources/bluesky.py for how unknown values are handled at the boundary.
TrendStatus = Literal["trending", "saturating", "cooling", "stale"]


class BlueskyMetrics(BaseModel):
    """Engagement as Bluesky reports it, plus the trend the post came from."""

    model_config = STRICT

    platform: Literal["bluesky"] = "bluesky"
    # A post carries its own text, so Bluesky can originate topics.
    content_bearing: ClassVar[bool] = True

    like_count: int
    reply_count: int
    repost_count: int
    # Trend-level, duplicated onto every post from that trend — as Lemmy's
    # `channel` is community-level. `trend` gives the extraction prompt the
    # referent a short post usually omits; `status` is the scorer's movement
    # term, reported by Bluesky rather than inferred from our own history.
    trend: str
    status: TrendStatus
    # From the payload's `indexedAt`, never `record.createdAt`: the latter is
    # client-supplied, and the scorer divides engagement by age.
    created_at: datetime

    @property
    def context(self) -> str:
        return self.trend


# Discriminated on `platform`, so a checkpoint dict deserialises back to the
# concrete class rather than to whichever union member happens to validate.
Metrics = Annotated[
    LemmyMetrics | WikipediaMetrics | BlueskyMetrics,
    Field(discriminator="platform"),
]


class Item(BaseModel):
    """A single normalised observation from any platform.

    Deliberately carries no author or username: no downstream stage needs it,
    and omitting it keeps the project clear of storing personal data.

    Everything that differs between platforms lives in `metrics`, so no field
    on this envelope has to mean two different things depending on where it
    came from.
    """

    model_config = STRICT

    source_id: str
    title: str
    body_excerpt: str | None = None
    permalink: str
    fetched_at: datetime
    metrics: Metrics

    @property
    def platform(self) -> str:
        return self.metrics.platform

    @property
    def context(self) -> str:
        return self.metrics.context

    @property
    def content_bearing(self) -> bool:
        return self.metrics.content_bearing


# score_components carries this alongside the real platform sub-scores. It is
# a multiplier, not a platform's opinion, so it must never reach topic_scores
# or be counted as a platform contributing to a topic.
NON_PLATFORM_COMPONENTS = frozenset({"corroboration"})


class Topic(BaseModel):
    """A cluster of items about the same thing."""

    model_config = STRICT

    id: str
    label: str
    summary: str
    item_ids: list[str]
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
