from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from zeitgeist.models import (
    REGISTER_DEFINITIONS,
    SENTIMENT_DEFINITIONS,
    BlueskyMetrics,
    Dossier,
    Item,
    LemmyMetrics,
    MediaBrief,
    Phrase,
    PostEvidence,
    Register,
    Reply,
    ScoredTopic,
    Sentiment,
    Topic,
    TrendEvidence,
    TrendInfo,
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
        (
            BlueskyMetrics,
            {
                "platform",
                "like_count",
                "reply_count",
                "repost_count",
                "trend",
                "status",
                "created_at",
            },
        ),
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


def test_topic_defaults_leave_room_for_the_scoring_stage():
    """score_topics fills these in later; the defaults are what let a topic
    exist between consolidation and scoring.
    """
    topic = Topic(id="cats", label="Cats", summary="Cat things.", item_ids=["abc123"])
    assert topic.trend_score == 0.0
    assert topic.score_components == {}


def test_scored_topic_defaults_leave_room_for_the_selection_stage():
    scored = _scored()
    assert scored.final_rank == 0


def test_scored_topic_accepts_every_field_of_a_topic():
    """`select` constructs ScoredTopic(**topic.model_dump(), final_rank=...).
    If the two models drift apart, that call breaks — here rather than
    mid-run.
    """
    topic = Topic(
        id="cats",
        label="Cats",
        summary="Cat things.",
        item_ids=["abc123"],
        trend_score=0.7,
        score_components={"base": 0.7},
    )
    scored = ScoredTopic(**topic.model_dump(), final_rank=1)
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


def test_trend_info_defaults_description_and_category_to_empty():
    """getTrends is an unspecced endpoint: absent fields degrade, not crash."""
    trend = TrendInfo(
        topic_id="14d072d9",
        display_name="Canada announces retaliatory tariffs",
        post_count=4298,
        started_at=datetime(2026, 8, 26, tzinfo=UTC),
        status="stale",
    )
    assert trend.description == ""
    assert trend.category == ""


def test_trend_evidence_round_trips_through_json(sample_items):
    evidence = TrendEvidence(
        trend=TrendInfo(
            topic_id="t1",
            display_name="A trend",
            description="what happened",
            category="politics",
            post_count=10,
            started_at=datetime(2026, 8, 26, tzinfo=UTC),
            status="trending",
        ),
        posts=[
            PostEvidence(
                item=sample_items[0],
                replies=[
                    Reply(
                        text="what a mess",
                        like_count=4,
                        created_at=datetime(2026, 8, 26, tzinfo=UTC),
                        author_key="ab12cd34",
                    )
                ],
            )
        ],
    )
    restored = TrendEvidence.model_validate_json(evidence.model_dump_json())
    assert restored == evidence


@pytest.mark.parametrize("field", ["author", "handle", "did", "display_name"])
def test_reply_rejects_identifying_fields(field):
    """author_key is a one-way hash and the only identity-adjacent field
    allowed. A raw handle or DID creeping in must fail loudly.
    """
    with pytest.raises(ValidationError):
        Reply(
            text="hi",
            like_count=0,
            created_at=datetime(2026, 8, 26, tzinfo=UTC),
            author_key="ab12cd34",
            **{field: "someone.bsky.social"},
        )


@pytest.mark.parametrize(
    "model,want",
    [
        (
            TrendInfo,
            {
                "topic_id",
                "display_name",
                "description",
                "category",
                "post_count",
                "started_at",
                "status",
            },
        ),
        (Reply, {"text", "like_count", "created_at", "author_key"}),
        (PostEvidence, {"item", "replies"}),
        (TrendEvidence, {"trend", "posts"}),
        (Phrase, {"text", "occurrences", "distinct_authors"}),
        (
            Dossier,
            {
                "what_happened",
                "key_entities",
                "conversation_summary",
                "conversation_register",
                "secondary_registers",
                "event_sentiment",
                "valence",
                "meme_potential",
                "recurring_phrases",
            },
        ),
    ],
)
def test_evidence_models_carry_exactly_the_specified_fields(model, want):
    """getTrends returns an `actors` list of handles, display names and
    avatars, and postView an `author` block. Neither may reach a model, so
    the field sets are written out by hand: adding one fails here.
    """
    assert set(model.model_fields) == want


def _dossier(**overrides: Any) -> Dossier:
    base: dict[str, Any] = {
        "what_happened": "Canada imposed retaliatory tariffs on $30B of US goods.",
        "key_entities": ["Canada", "Mark Carney"],
        "conversation_summary": "People are treating it as overdue.",
        "conversation_register": Register.DUNKING,
        "secondary_registers": [Register.RESIGNATION],
        "event_sentiment": Sentiment.SCHADENFREUDE,
        "valence": -0.2,
        "meme_potential": 0.8,
        "recurring_phrases": [],
    }
    return Dossier(**{**base, **overrides})


def test_topic_dossier_defaults_to_none():
    """The dormant path produces topics with no dossier."""
    topic = Topic(id="t", label="A trend", summary="s", item_ids=["i1"])
    assert topic.dossier is None


def test_topic_carries_a_dossier_through_json():
    topic = Topic(
        id="t",
        label="A trend",
        summary="s",
        item_ids=["i1"],
        dossier=_dossier(
            recurring_phrases=[
                Phrase(text="elbows up", occurrences=41, distinct_authors=33)
            ]
        ),
    )
    restored = Topic.model_validate_json(topic.model_dump_json())
    assert restored.dossier is not None
    assert restored.dossier.recurring_phrases[0].text == "elbows up"
    assert restored.dossier.conversation_register is Register.DUNKING


def test_dossier_rejects_valence_outside_the_scale():
    with pytest.raises(ValidationError):
        _dossier(valence=-1.5)


def test_dossier_rejects_meme_potential_outside_the_scale():
    with pytest.raises(ValidationError):
        _dossier(meme_potential=1.5)


@pytest.mark.parametrize("valence", [-1.0, 0.0, 1.0])
def test_dossier_accepts_the_valence_boundaries(valence):
    """-1.0 is what a thoroughly negative event scores, and the prompt asks
    for it. `gt` instead of `ge` would drop exactly those trends, and a
    rejection-only test passes either way.
    """
    assert _dossier(valence=valence).valence == valence


@pytest.mark.parametrize("meme_potential", [0.0, 1.0])
def test_dossier_accepts_the_meme_potential_boundaries(meme_potential):
    assert _dossier(meme_potential=meme_potential).meme_potential == meme_potential


@pytest.mark.parametrize("member", list(Sentiment))
def test_every_sentiment_member_is_defined(member):
    """A member with no definition reaches the model as a bare word, and the
    model then picks it without meaning it — the failure this mapping exists
    to prevent. Adding a member without a definition must fail here rather
    than silently degrade the judgement.
    """
    assert SENTIMENT_DEFINITIONS[member].strip()


@pytest.mark.parametrize("member", list(Register))
def test_every_register_member_is_defined(member):
    assert REGISTER_DEFINITIONS[member].strip()


@pytest.mark.parametrize(
    "definitions,enum",
    [(SENTIMENT_DEFINITIONS, Sentiment), (REGISTER_DEFINITIONS, Register)],
)
def test_no_definition_survives_its_member_being_removed(definitions, enum):
    """The other drift direction: a stale definition for a member that no
    longer exists would be rendered into the prompt as a phantom option.
    """
    assert set(definitions) == set(enum)
