"""Map stage: each batch of posts becomes a set of topic tags.

Batches are independent, so a failure loses one batch rather than the run.
"""

import logging

from pydantic import BaseModel

from zeitgeist.llm.base import LLMProvider
from zeitgeist.models import Post

log = logging.getLogger(__name__)

BATCH_SIZE = 40
MAX_TAGS_PER_POST = 3

EXTRACT_SYSTEM = (
    "You label social media posts with the topics they are about. "
    "Topic tags are short noun phrases in lower case, two or three words at "
    "most, describing the subject rather than the reaction to it. Prefer "
    "specific tags over generic ones: 'shelter dog adoption' beats 'animals'. "
    f"Give each post at most {MAX_TAGS_PER_POST} tags."
)


class PostTags(BaseModel):
    """Topic tags for one post."""

    post_id: str
    tags: list[str]


class TagExtraction(BaseModel):
    """Tags for every post in one batch."""

    assignments: list[PostTags]


def extract_tags(
    posts: list[Post], provider: LLMProvider, *, batch_size: int = BATCH_SIZE
) -> dict[str, list[str]]:
    """Map every post to its topic tags. Failed batches are skipped."""
    known_ids = {post.source_id for post in posts}
    tags: dict[str, list[str]] = {}

    for start in range(0, len(posts), batch_size):
        batch = posts[start : start + batch_size]
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
            if assignment.post_id not in known_ids:
                continue
            tags[assignment.post_id] = _clean(assignment.tags)

    return tags


def _build_prompt(batch: list[Post]) -> str:
    lines = [
        f"- id={post.source_id} | r/{post.channel} | {post.title}" for post in batch
    ]
    listing = "\n".join(lines)
    return (
        "Label each of these posts with its topics.\n\n"
        f"{listing}\n\n"
        "Return one entry per post, using the exact id given."
    )


def _clean(tags: list[str]) -> list[str]:
    seen: list[str] = []
    for tag in tags:
        normalised = tag.strip().lower()
        if normalised and normalised not in seen:
            seen.append(normalised)
    return seen[:MAX_TAGS_PER_POST]
