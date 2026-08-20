from typing import Any

import pytest

from zeitgeist.llm.base import FakeLLMProvider, LLMError
from zeitgeist.media.brief import (
    BriefChoice,
    BriefError,
    generate_brief,
    generate_briefs,
)
from zeitgeist.media.templates import TemplateManifest
from zeitgeist.models import ScoredTopic, Sentiment


def _templates() -> dict[str, TemplateManifest]:
    return {
        "drake": TemplateManifest(
            id="drake",
            image="drake.png",
            shape="rejecting option A in favour of preferred option B",
            slots=[
                {"name": "rejected", "box": (0, 0, 10, 10), "max_chars": 60},
                {"name": "preferred", "box": (0, 10, 10, 20), "max_chars": 60},
            ],
        ),
        "this_is_fine": TemplateManifest(
            id="this_is_fine",
            image="this_is_fine.png",
            shape="insisting all is well amid visible disaster",
            slots=[
                {"name": "situation", "box": (0, 0, 10, 10), "max_chars": 60},
                {"name": "denial", "box": (0, 10, 10, 20), "max_chars": 60},
            ],
        ),
    }


def _topic(tid: str = "cats") -> ScoredTopic:
    return ScoredTopic(
        id=tid,
        label=tid.title(),
        summary=f"About {tid}.",
        post_ids=["p1"],
        trend_score=0.8,
        primary_sentiment=Sentiment.CUTE,
        valence=0.7,
        meme_potential=0.9,
    )


def _choice(**overrides: Any) -> BriefChoice:
    defaults: dict[str, Any] = dict(
        template_id="drake",
        caption_slots={"rejected": "Dogs", "preferred": "Cats"},
        rationale="Preference structure fits.",
    )
    return BriefChoice(**{**defaults, **overrides})


def test_returns_a_brief_with_the_topic_id_attached():
    provider = FakeLLMProvider([_choice()])
    brief = generate_brief(_topic(), _templates(), provider)
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
    brief = generate_brief(_topic(), _templates(), provider)
    assert brief.caption_slots == {"rejected": "Dogs", "preferred": "Cats"}


def test_prompt_lists_every_template_id_shape_and_slots():
    provider = FakeLLMProvider([_choice()])
    generate_brief(_topic(), _templates(), provider)
    prompt = provider.calls[0].prompt
    assert "drake" in prompt and "this_is_fine" in prompt
    assert "rejecting option A" in prompt
    assert "rejected" in prompt and "preferred" in prompt


def test_prompt_includes_topic_sentiment():
    provider = FakeLLMProvider([_choice()])
    generate_brief(_topic(), _templates(), provider)
    assert "cute" in provider.calls[0].prompt.lower()


def test_prompt_tells_the_model_each_slots_max_chars_budget():
    """max_chars is validated on the manifest and enforced by the renderer,
    but the model is never told the budget unless the prompt says so — it
    can only guess at a length that will fit.
    """
    provider = FakeLLMProvider([_choice()])
    generate_brief(_topic(), _templates(), provider)
    prompt = provider.calls[0].prompt
    assert "rejected" in prompt and "60" in prompt
    # Confirms the number is attached to its slot, not just present anywhere.
    rejected_index = prompt.index("rejected")
    nearby = prompt[rejected_index : rejected_index + 40]
    assert "60" in nearby


def test_hallucinated_template_id_triggers_retry():
    provider = FakeLLMProvider([_choice(template_id="invented"), _choice()])
    brief = generate_brief(_topic(), _templates(), provider)
    assert brief.template_id == "drake"
    assert len(provider.calls) == 2
    assert "invented" in provider.calls[1].prompt


def test_missing_slot_triggers_retry():
    bad = _choice(caption_slots={"rejected": "Dogs"})
    provider = FakeLLMProvider([bad, _choice()])
    assert generate_brief(_topic(), _templates(), provider).template_id == "drake"


def test_unknown_slot_triggers_retry():
    bad = _choice(caption_slots={"rejected": "a", "preferred": "b", "extra": "c"})
    provider = FakeLLMProvider([bad, _choice()])
    assert generate_brief(_topic(), _templates(), provider).template_id == "drake"


def test_second_failure_raises_brief_error():
    provider = FakeLLMProvider(
        [_choice(template_id="nope"), _choice(template_id="also-nope")]
    )
    with pytest.raises(BriefError):
        generate_brief(_topic(), _templates(), provider)


def test_provider_error_raises_brief_error():
    provider = FakeLLMProvider([LLMError("down")])
    with pytest.raises(BriefError):
        generate_brief(_topic(), _templates(), provider)


def test_generate_briefs_skips_failures_and_keeps_the_rest():
    provider = FakeLLMProvider([LLMError("down"), _choice(), _choice()])
    briefs = generate_briefs(
        [_topic("dropped"), _topic("kept")], _templates(), provider
    )
    assert [brief.topic_id for brief in briefs] == ["kept"]


def test_blank_caption_triggers_retry():
    provider = FakeLLMProvider(
        [_choice(caption_slots={"rejected": "  ", "preferred": "Cats"}), _choice()]
    )
    assert generate_brief(_topic(), _templates(), provider).template_id == "drake"
