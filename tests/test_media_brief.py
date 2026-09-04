from typing import Any

import pytest

from tests.template_factory import make_manifest, make_slot
from zeitgeist.llm.base import FakeLLMProvider, LLMError
from zeitgeist.media.brief import (
    BriefChoice,
    BriefError,
    generate_brief,
    generate_briefs,
)
from zeitgeist.media.templates import TemplateManifest
from zeitgeist.models import Dossier, Phrase, Register, ScoredTopic, Sentiment


def _templates() -> dict[str, TemplateManifest]:
    """Shapes and budgets are spelled out because the prompt tests assert on
    them; the boxes are arbitrary, since nothing here renders.
    """
    manifests = (
        make_manifest(
            "drake",
            shape="rejecting option A in favour of preferred option B",
            slots=[
                make_slot("rejected", box=(0, 0, 10, 10), max_chars=60),
                make_slot("preferred", box=(0, 10, 10, 20), max_chars=60),
            ],
        ),
        make_manifest(
            "this_is_fine",
            shape="insisting all is well amid visible disaster",
            slots=[
                make_slot("situation", box=(0, 0, 10, 10), max_chars=60),
                make_slot("denial", box=(0, 10, 10, 20), max_chars=60),
            ],
        ),
    )
    return {manifest.id: manifest for manifest in manifests}


def _scored_topic(
    *,
    phrases: list[Phrase] | None = None,
    conversation_summary: str = "People treat it as overdue.",
    key_entities: list[str] | None = None,
    **overrides: Any,
) -> ScoredTopic:
    base: dict[str, Any] = dict(
        id="cats",
        label="Cats",
        summary="About cats.",
        item_ids=["p1"],
        trend_status="trending",
        trend_score=0.8,
        dossier=Dossier(
            what_happened="Canada imposed tariffs on $30B of US goods.",
            conversation_summary=conversation_summary,
            key_entities=key_entities or [],
            conversation_register=Register.DUNKING,
            event_sentiment=Sentiment.SCHADENFREUDE,
            meme_potential=0.8,
            recurring_phrases=phrases or [],
        ),
    )
    return ScoredTopic(**(base | overrides))


def _choice(**overrides: Any) -> BriefChoice:
    defaults: dict[str, Any] = dict(
        template_id="drake",
        caption_slots={"rejected": "Dogs", "preferred": "Cats"},
        rationale="Preference structure fits.",
    )
    return BriefChoice(**{**defaults, **overrides})


def _last_prompt(provider: FakeLLMProvider) -> str:
    return provider.calls[-1].prompt


def test_returns_a_brief_with_the_topic_id_attached():
    provider = FakeLLMProvider([_choice()])
    brief = generate_brief(_scored_topic(), _templates(), provider)
    assert brief.topic_id == "cats"
    assert brief.template_id == "drake"
    assert brief.caption_slots["preferred"] == "Cats"
    # The spec keeps the rationale specifically for debugging bad captions.
    assert brief.rationale == "Preference structure fits."


def test_captions_are_stripped_before_rendering():
    """Leading newlines are common in model output and would shift the text
    off-centre inside its box.
    """
    provider = FakeLLMProvider(
        [_choice(caption_slots={"rejected": "  Dogs ", "preferred": "Cats\n"})]
    )
    brief = generate_brief(_scored_topic(), _templates(), provider)
    assert brief.caption_slots == {"rejected": "Dogs", "preferred": "Cats"}


def test_prompt_lists_every_template_id_shape_and_slots():
    provider = FakeLLMProvider([_choice()])
    generate_brief(_scored_topic(), _templates(), provider)
    prompt = provider.calls[0].prompt
    assert "drake" in prompt and "this_is_fine" in prompt
    assert "rejecting option A" in prompt
    assert "rejected" in prompt and "preferred" in prompt


def test_prompt_tells_the_model_each_slots_max_chars_budget():
    """max_chars is validated on the manifest and enforced by the renderer,
    but the model is never told the budget unless the prompt says so — it
    can only guess at a length that will fit.
    """
    provider = FakeLLMProvider([_choice()])
    generate_brief(_scored_topic(), _templates(), provider)
    prompt = provider.calls[0].prompt
    assert "rejected" in prompt and "60" in prompt
    # Confirms the number is attached to its slot, not just present anywhere.
    rejected_index = prompt.index("rejected")
    nearby = prompt[rejected_index : rejected_index + 40]
    assert "60" in nearby


def test_hallucinated_template_id_triggers_retry():
    provider = FakeLLMProvider([_choice(template_id="invented"), _choice()])
    brief = generate_brief(_scored_topic(), _templates(), provider)
    assert brief.template_id == "drake"
    assert len(provider.calls) == 2
    assert "invented" in provider.calls[1].prompt


def test_missing_slot_triggers_retry():
    bad = _choice(caption_slots={"rejected": "Dogs"})
    provider = FakeLLMProvider([bad, _choice()])
    assert generate_brief(_scored_topic(), _templates(), provider).template_id == (
        "drake"
    )


def test_unknown_slot_triggers_retry():
    bad = _choice(caption_slots={"rejected": "a", "preferred": "b", "extra": "c"})
    provider = FakeLLMProvider([bad, _choice()])
    assert generate_brief(_scored_topic(), _templates(), provider).template_id == (
        "drake"
    )


def test_second_failure_raises_brief_error():
    provider = FakeLLMProvider(
        [_choice(template_id="nope"), _choice(template_id="also-nope")]
    )
    with pytest.raises(BriefError):
        generate_brief(_scored_topic(), _templates(), provider)


def test_provider_error_raises_brief_error():
    provider = FakeLLMProvider([LLMError("down")])
    with pytest.raises(BriefError):
        generate_brief(_scored_topic(), _templates(), provider)


def test_generate_briefs_skips_failures_and_keeps_the_rest():
    provider = FakeLLMProvider([LLMError("down"), _choice(), _choice()])
    briefs = generate_briefs(
        [_scored_topic(id="dropped"), _scored_topic(id="kept")],
        _templates(),
        provider,
    )
    assert [brief.topic_id for brief in briefs] == ["kept"]


def test_blank_caption_triggers_retry():
    provider = FakeLLMProvider(
        [_choice(caption_slots={"rejected": "  ", "preferred": "Cats"}), _choice()]
    )
    assert generate_brief(_scored_topic(), _templates(), provider).template_id == (
        "drake"
    )


def test_the_prompt_carries_what_happened_not_just_the_label():
    """The failure this whole change exists to fix: the caption stage used
    to see a label and a confabulated summary.
    """
    topic = _scored_topic()
    provider = FakeLLMProvider(responses=[_choice()])
    generate_brief(topic, _templates(), provider)
    prompt = _last_prompt(provider)
    assert "Canada imposed tariffs on $30B of US goods." in prompt


def test_the_prompt_carries_the_register_and_the_event_sentiment():
    topic = _scored_topic()
    provider = FakeLLMProvider(responses=[_choice()])
    generate_brief(topic, _templates(), provider)
    prompt = _last_prompt(provider)
    assert "dunking" in prompt
    assert "schadenfreude" in prompt


def test_the_prompt_offers_recurring_phrases_with_their_counts():
    topic = _scored_topic(
        phrases=[Phrase(text="elbows up", occurrences=41, distinct_authors=33)]
    )
    provider = FakeLLMProvider(responses=[_choice()])
    generate_brief(topic, _templates(), provider)
    prompt = _last_prompt(provider)
    assert "elbows up" in prompt
    assert "33" in prompt


def test_the_prompt_carries_what_people_are_saying():
    """The other half of the fix this whole change exists for: a caption
    written from the event alone, with no view of the conversation, is the
    old failure mode by half. Asserting the summary text itself, not the
    "What people are saying" label, catches a regression that drops the
    line while some other line still happens to carry the word "saying".
    """
    topic = _scored_topic(
        conversation_summary="Half the replies are just the word 'finally'."
    )
    provider = FakeLLMProvider(responses=[_choice()])
    generate_brief(topic, _templates(), provider)
    prompt = _last_prompt(provider)
    assert "Half the replies are just the word 'finally'." in prompt


def test_the_prompt_carries_every_key_entity():
    """Two entities, not one, so a regression that only interpolates the
    first item of the list (rather than joining all of them) still fails
    this.
    """
    topic = _scored_topic(key_entities=["Mark Carney", "Doug Ford"])
    provider = FakeLLMProvider(responses=[_choice()])
    generate_brief(topic, _templates(), provider)
    prompt = _last_prompt(provider)
    assert "Mark Carney" in prompt
    assert "Doug Ford" in prompt


def test_the_prompt_omits_entities_when_there_are_none():
    """key_entities is only rendered when non-empty. A topic with no named
    entities must still produce a prompt, not a stray "People and
    organisations: " line with nothing after the colon.
    """
    topic = _scored_topic(key_entities=[])
    provider = FakeLLMProvider(responses=[_choice()])
    generate_brief(topic, _templates(), provider)
    prompt = _last_prompt(provider)
    assert "People and organisations" not in prompt


def test_a_topic_without_a_dossier_falls_back_to_its_summary():
    """The dormant path leaves `dossier` None. Briefing must degrade rather
    than raise — and the summary has to actually reach the prompt, or the
    caption is written from a bare label. Asserting only that a brief comes
    back passes even when the context block degrades to an empty string.
    """
    topic = ScoredTopic(
        id="t",
        label="A trend",
        summary="Cats knocked something over.",
        item_ids=["i"],
        trend_status="trending",
    )
    provider = FakeLLMProvider(responses=[_choice()])
    brief = generate_brief(topic, _templates(), provider)
    assert brief.topic_id == "t"
    assert "Cats knocked something over." in provider.calls[-1].prompt
