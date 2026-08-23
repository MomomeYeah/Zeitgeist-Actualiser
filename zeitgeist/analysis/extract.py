"""Map stage: each batch of items becomes a set of topic tags.

Batches are independent, so a failure loses one batch rather than the run.
"""

import logging

from pydantic import BaseModel

from zeitgeist.llm.base import LLMProvider
from zeitgeist.models import Item

log = logging.getLogger(__name__)

BATCH_SIZE = 40
MAX_TAGS_PER_POST = 3

EXTRACT_SYSTEM = (
    "You label social media items with the topics they are about. "
    "Topic tags are short noun phrases in lower case, two or three words at "
    "most, describing the subject rather than the reaction to it. Prefer "
    "specific tags over generic ones: 'shelter dog adoption' beats 'animals'. "
    f"Give each item at most {MAX_TAGS_PER_POST} tags."
)


class ItemTags(BaseModel):
    """Topic tags for one item."""

    item_id: str
    tags: list[str]


class TagExtraction(BaseModel):
    """Tags for every item in one batch."""

    assignments: list[ItemTags]


def extract_tags(
    items: list[Item], provider: LLMProvider, *, batch_size: int = BATCH_SIZE
) -> dict[str, list[str]]:
    """Map every item to its topic tags. Failed batches are skipped."""
    known_ids = {item.source_id for item in items}
    tags: dict[str, list[str]] = {}

    for start in range(0, len(items), batch_size):
        batch = items[start : start + batch_size]
        # Built outside the try: a bug here must crash loudly, not be
        # misreported as a failed batch and silently skipped.
        prompt = _build_prompt(batch)
        try:
            extraction = provider.complete(prompt, TagExtraction, system=EXTRACT_SYSTEM)
        except Exception as exc:
            log.warning(
                "Tag extraction failed for batch starting at %d: %s", start, exc
            )
            continue

        for assignment in extraction.assignments:
            if assignment.item_id not in known_ids:
                continue
            tags[assignment.item_id] = _clean(assignment.tags)

    return tags


def _build_prompt(batch: list[Item]) -> str:
    lines = [f"- id={item.source_id} | {item.context} | {item.title}" for item in batch]
    listing = "\n".join(lines)
    return (
        "Label each of these items with its topics.\n\n"
        f"{listing}\n\n"
        "Return one entry per item, using the exact id given."
    )


def _clean(tags: list[str]) -> list[str]:
    seen: list[str] = []
    for tag in tags:
        normalised = tag.strip().lower()
        if normalised and normalised not in seen:
            seen.append(normalised)
    return seen[:MAX_TAGS_PER_POST]
