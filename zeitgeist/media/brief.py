"""Topic to template choice and captions.

The model may only pick from supplied ids and fill named slots, so a
hallucinated template or a missing slot fails here rather than reaching the
renderer. The rationale is kept deliberately: reading why the model chose a
template is the main tool for debugging poor captions.
"""

import logging

from pydantic import BaseModel

from zeitgeist.llm.base import LLMProvider
from zeitgeist.media.templates import TemplateManifest
from zeitgeist.models import MediaBrief, ScoredTopic

log = logging.getLogger(__name__)

BRIEF_SYSTEM = (
    "You write memes. Given a trending topic and a library of meme templates, "
    "pick the template whose rhetorical shape genuinely fits the topic, then "
    "write the caption for every one of its slots. Captions are short, "
    "specific, and land for someone who has not read the source posts. Find "
    "the humane or absurd angle rather than punching down, and never make a "
    "joke at the expense of people who have been harmed. Use only template "
    "ids from the library and fill exactly the slots that template lists."
)


class BriefChoice(BaseModel):
    """The model's template choice and captions. `topic_id` is attached by us."""

    template_id: str
    caption_slots: dict[str, str]
    rationale: str


class BriefError(Exception):
    """Raised when no valid brief could be produced for a topic."""


def generate_brief(
    topic: ScoredTopic,
    templates: dict[str, TemplateManifest],
    provider: LLMProvider,
) -> MediaBrief:
    prompt = _build_prompt(topic, templates)
    attempt_prompt = prompt
    last_error: str | None = None

    for _ in range(2):
        try:
            choice = provider.complete(attempt_prompt, BriefChoice, system=BRIEF_SYSTEM)
        except Exception as exc:
            raise BriefError(f"Provider failed for {topic.label!r}: {exc}") from exc

        problem = _validate(choice, templates)
        if problem is None:
            return MediaBrief(
                topic_id=topic.id,
                template_id=choice.template_id,
                caption_slots={
                    name: text.strip() for name, text in choice.caption_slots.items()
                },
                rationale=choice.rationale,
            )

        last_error = problem
        attempt_prompt = (
            f"{prompt}\n\nYour previous answer was rejected: {problem}\n"
            "Return a corrected answer."
        )

    raise BriefError(f"No valid brief for {topic.label!r}: {last_error}")


def generate_briefs(
    topics: list[ScoredTopic],
    templates: dict[str, TemplateManifest],
    provider: LLMProvider,
) -> list[MediaBrief]:
    """Brief every topic. A topic that cannot be briefed is skipped."""
    briefs: list[MediaBrief] = []
    for topic in topics:
        try:
            briefs.append(generate_brief(topic, templates, provider))
        except BriefError as exc:
            log.warning("Skipping %r: %s", topic.label, exc)
    return briefs


def _validate(
    choice: BriefChoice, templates: dict[str, TemplateManifest]
) -> str | None:
    manifest = templates.get(choice.template_id)
    if manifest is None:
        return (
            f"template_id {choice.template_id!r} is not in the library; "
            f"choose one of: {', '.join(sorted(templates))}"
        )

    expected = {slot.name for slot in manifest.slots}
    given = set(choice.caption_slots)

    if missing := sorted(expected - given):
        return f"missing captions for slots: {', '.join(missing)}"
    if extra := sorted(given - expected):
        return f"unknown slots for {manifest.id!r}: {', '.join(extra)}"
    if blank := sorted(n for n, t in choice.caption_slots.items() if not t.strip()):
        return f"blank captions for slots: {', '.join(blank)}"
    return None


def _build_prompt(topic: ScoredTopic, templates: dict[str, TemplateManifest]) -> str:
    library = "\n".join(
        f"- id={manifest.id} | shape: {manifest.shape} | "
        "slots: "
        + ", ".join(
            f"{slot.name} (max {slot.max_chars} chars)" for slot in manifest.slots
        )
        for manifest in templates.values()
    )
    return (
        f"Topic: {topic.label}\n"
        f"Summary: {topic.summary}\n"
        f"Sentiment: {topic.primary_sentiment.value}\n"
        f"Meme potential: {topic.meme_potential:.2f}\n\n"
        f"Template library:\n{library}\n\n"
        "Pick the best-fitting template and write its captions."
    )
