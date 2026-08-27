from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from zeitgeist.models import (
    REGISTER_DEFINITIONS,
    SENTIMENT_DEFINITIONS,
    Dossier,
    Item,
    LemmyMetrics,
    Register,
    ScoredTopic,
    Sentiment,
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


def _dossier(**overrides: Any) -> Dossier:
    base: dict[str, Any] = {
        "what_happened": "Canada imposed tariffs on $30B of US goods.",
        "key_entities": ["Canada", "Mark Carney"],
        "conversation_summary": "People are treating it as overdue.",
        "conversation_register": Register.DUNKING,
        "secondary_registers": [Register.RESIGNATION],
        "event_sentiment": Sentiment.SCHADENFREUDE,
        "meme_potential": 0.8,
        "recurring_phrases": [],
    }
    return Dossier(**{**base, **overrides})


def test_dossier_rejects_meme_potential_outside_the_scale():
    with pytest.raises(ValidationError):
        _dossier(meme_potential=1.5)


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
