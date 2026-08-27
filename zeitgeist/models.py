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


class Register(StrEnum):
    """The posture people are taking, distinct from how the event feels.

    `Sentiment` answers "how does this event feel"; `Register` answers "what
    is the room doing about it". The two can point in opposite directions,
    and the gap is the signal: a grim event discussed in GALLOWS yields a
    very particular meme, while the same event in MOURNING means do not make
    a joke at all.

    The three warm registers are easily confused, so they are defined
    against each other. DELIGHT is a cat knocking something off a table, or
    an overlooked person finally getting their due: broad, warm, no side to
    take. AWE is impressive rather than endearing. TRIBUTE is appreciation
    prompted by loss or a milestone.
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


class TrendInfo(BaseModel):
    """Bluesky's own cluster, kept whole.

    The current source keeps `displayName` and `status` and discards the
    rest — including `description`, which states the specific event in one
    sentence and is the single most useful field the API returns.

    `description` and `category` default to empty rather than raising:
    getTrends lives under `app.bsky.unspecced`, so nothing it returns is a
    contract. Same reasoning as `_normalise_status` in sources/bluesky.py —
    degrade with a warning, do not kill the run.
    """

    model_config = STRICT

    # Bluesky's own `topic` uuid, stable while the trend lives. Kept for
    # cross-run identification; NOT used as Topic.id, which needs to be
    # readable because render output filenames are built from it.
    topic_id: str
    display_name: str
    description: str = ""
    category: str = ""
    post_count: int = 0
    started_at: datetime
    status: TrendStatus


class Reply(BaseModel):
    """One reply beneath a post. The conversation, as opposed to the news.

    `author_key` is a truncated one-way hash of the poster's DID and exists
    for exactly one purpose: counting how many distinct accounts are behind
    a repeated phrase. Forty uses from three accounts is a dogpile, not a
    zeitgeist. The handle itself has no downstream use and is never stored.
    """

    model_config = STRICT

    text: str
    like_count: int
    created_at: datetime
    author_key: str


class PostEvidence(BaseModel):
    """A post together with what people said underneath it."""

    model_config = STRICT

    item: Item
    # Empty when the thread fetch failed. A post without replies is still
    # evidence of what was posted, so it is kept rather than dropped.
    replies: list[Reply] = Field(default_factory=list)


class TrendEvidence(BaseModel):
    """Everything one trend contributed to a run.

    This is the ingest checkpoint's unit, replacing the flat `Item` list.
    """

    model_config = STRICT

    trend: TrendInfo
    posts: list[PostEvidence] = Field(default_factory=list)


# score_components carries this alongside the real platform sub-scores. It is
# a multiplier, not a platform's opinion, so it must never reach topic_scores
# or be counted as a platform contributing to a topic.
NON_PLATFORM_COMPONENTS = frozenset({"corroboration"})


# Rendered into the distillation prompt. They live here, beside the members
# they define, because a definition that drifts from its enum is worse than
# none — and `test_every_taxonomy_member_is_defined` fails the moment a
# member is added without one.
#
# These are not decoration. Ollama compiles a JSON schema into a grammar:
# the enum values constrain which strings are emittable, but neither the
# member list nor any schema `description` is shown to the model to reason
# about. A taxonomy that lives only in the schema is invisible, and the
# model picks whatever satisfies the grammar. Measured against qwen3.5, a
# death came back `gross` until these reached the prompt.
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


class Phrase(BaseModel):
    """Text that several people independently converged on.

    Mined deterministically, never model-generated. Asked for catchphrases a
    model returns plausible ones; the point of this field is that its counts
    are true, because that is what licenses quoting it in a caption.
    """

    model_config = STRICT

    text: str
    occurrences: int
    distinct_authors: int


class Dossier(BaseModel):
    """What a trend is actually about, and what the room is doing about it.

    Replaces the label-and-summary pair that every caption used to be
    written from. `summary` on the old path was written by a model that had
    seen a tag vocabulary and no sentences; `what_happened` here is written
    from the trend description, the posts and the replies.
    """

    model_config = STRICT

    what_happened: str
    key_entities: list[str] = Field(default_factory=list)
    conversation_summary: str
    conversation_register: Register
    secondary_registers: list[Register] = Field(default_factory=list)
    event_sentiment: Sentiment
    # None when the model returned no usable number. A grammar cannot
    # enforce a numeric range, so an out-of-range value is always
    # possible; nothing downstream reads either field, so losing the
    # whole dossier over one would trade real content for nothing.
    valence: Annotated[float, Field(ge=-1.0, le=1.0)] | None = None
    # Recorded for inspection, deliberately NOT applied to ranking. It was
    # suppressing topics before there was evidence that suppression helps.
    meme_potential: Annotated[float, Field(ge=0.0, le=1.0)] | None = None
    # Attached after the model call, not returned by it.
    recurring_phrases: list[Phrase] = Field(default_factory=list)


class Topic(BaseModel):
    """A cluster of items about the same thing."""

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
    """Instructions for rendering one piece of media."""

    model_config = STRICT

    topic_id: str
    template_id: str
    caption_slots: dict[str, str]
    rationale: str
