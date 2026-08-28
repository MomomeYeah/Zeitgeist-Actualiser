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
    """How a given topic of event feels, separate from specific reactions to it.

    Fixed taxonomy so results are comparable across runs.
    """

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


# Concise definitions for each sentiment, to be rendered into the distillation prompt.
# This allows the model to reason about the meaning of each sentiment and choose the
# most appropriate one for a given topic.
#
# Ollama compiles a JSON schema into a grammar: the enum values constrain which strings
# are emittable, but neither the member list nor any schema `description` is shown to
# the model to reason about.
SENTIMENT_DEFINITIONS: dict[Sentiment, str] = {
    Sentiment.CUTE: "small, endearing, harmless",
    Sentiment.HEARTWARMING: "someone was helped, recognised, or came good",
    Sentiment.FUNNY: "inherently absurd or comic",
    Sentiment.AWE: "impressive in scale, skill, beauty or achievement",
    Sentiment.SCHADENFREUDE: "someone powerful or deserving came unstuck",
    Sentiment.OUTRAGE: "injustice, abuse of power, betrayal of trust",
    Sentiment.SAD: "loss, death, grief, decline, suffering",
    Sentiment.SCARY: "danger, threat, disaster, violence",
    Sentiment.GROSS: (
        "physically disgusting - bodily, filthy, nauseating. NOT morally "
        "objectionable, which is outrage"
    ),
    Sentiment.CRINGE: "embarrassing, socially painful, secondhand shame",
    Sentiment.MUNDANE: "ordinary, procedural, low-stakes",
}


class Register(StrEnum):
    """The posture people are taking towards an event.

    This is distinct from how the event itself feels. A grim event can be treated with
    gallows humor or with sincere mourning, and the register captures that difference.
    """

    TRIBUTE = "tribute"
    MOURNING = "mourning"
    DELIGHT = "delight"
    OUTRAGE = "outrage"
    DUNKING = "dunking"
    GALLOWS = "gallows"
    RIFFING = "riffing"
    AWE = "awe"
    ALARM = "alarm"
    DEBATE = "debate"
    RESIGNATION = "resignation"


# Concise definitions for each register, to be rendered into the distillation prompt.
# This allows the model to reason about the meaning of each register and choose the
# most appropriate one for a given topic.
REGISTER_DEFINITIONS: dict[Register, str] = {
    Register.TRIBUTE: "earnest appreciation, mourning as celebration",
    Register.MOURNING: "undiluted grief",
    Register.DELIGHT: "uncomplicated shared enjoyment, nothing to argue about",
    Register.OUTRAGE: "sincere anger, calls to act",
    Register.DUNKING: "piling onto a target",
    Register.GALLOWS: "joking precisely because it is grim",
    Register.RIFFING: "in-jokes, wordplay, escalating bits",
    Register.AWE: "sincere wonder",
    Register.ALARM: "fear, warning, this-is-not-normal",
    Register.DEBATE: "genuine disagreement",
    Register.RESIGNATION: 'weary "of course this happened"',
}


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


class TrendInfo(BaseModel):
    """Metadata information for a single trending topic"""

    model_config = STRICT

    topic_id: str
    display_name: str
    description: str = ""
    category: str = ""
    post_count: int = 0
    started_at: datetime
    status: TrendStatus


class Reply(BaseModel):
    """A single reply to a post.

    `author_key` is used to count the number of distinct accounts behind a repeated
    phrase: forty uses from three accounts is a dogpile, not a zeitgeist. The handle
    itself has no downstream use and is never stored, so can be calculated differently
    per-platform.
    """

    model_config = STRICT

    text: str
    like_count: int
    created_at: datetime
    author_key: str


class PostEvidence(BaseModel):
    """A post together with it's replies."""

    model_config = STRICT

    item: Item
    # Empty when the thread fetch failed. A post without replies is still
    # evidence of what was posted, so it is kept rather than dropped.
    replies: list[Reply] = Field(default_factory=list)


class TrendEvidence(BaseModel):
    """All data for a trend, including it's metadata and all posts and replies."""

    model_config = STRICT

    trend: TrendInfo
    posts: list[PostEvidence] = Field(default_factory=list)


class Phrase(BaseModel):
    """A repeated phrase detected in items relating to a trending topic.

    A phrase is stored alongside the number of times it was used and the number of
    distinct authors that used it. This is calculated deterministically, rather than
    being model-generated, to avoid unnecessary hallucinations.

    The more times a phrase is used in a topic, the more likely it is to be a specific
    part of the zeitgeist, and therefore the more likely it is to be either part of a
    caption, or a meme in its own right.
    """

    model_config = STRICT

    text: str
    occurrences: int
    distinct_authors: int


class Dossier(BaseModel):
    """A model-generated, distilled summary of a trend"""

    model_config = STRICT

    what_happened: str
    key_entities: list[str] = Field(default_factory=list)
    conversation_summary: str
    conversation_register: Register
    secondary_registers: list[Register] = Field(default_factory=list)
    event_sentiment: Sentiment

    # None when the model returned no usable number. A grammar cannot
    # enforce a numeric range, so an out-of-range value is always
    # possible.
    meme_potential: Annotated[float, Field(ge=0.0, le=1.0)] | None = None

    # Attached after the model call, not returned by it.
    recurring_phrases: list[Phrase] = Field(default_factory=list)


class Topic(BaseModel):
    """Dossier and scoring information about a trending topic."""

    model_config = STRICT

    id: str
    label: str
    summary: str
    item_ids: list[str]
    trend_score: float = 0.0
    score_components: dict[str, float] = Field(default_factory=dict)
    # None on the dormant path, which has no evidence to distil.
    dossier: Dossier | None = None


class ScoredTopic(Topic):
    """A topic with its final ranking attached.

    Sentiment used to live here. It now lives on `Topic.dossier`, judged
    with the replies in front of it rather than from a label, so there is
    one source of truth and no projection to drift.
    """

    final_rank: int = 0


class MediaBrief(BaseModel):
    """LLM instructions for rendering a piece of media."""

    model_config = STRICT

    topic_id: str
    template_id: str
    caption_slots: dict[str, str]
    rationale: str
