"""Reduce stage: merge the tag vocabulary into canonical topics.

Only the vocabulary goes to the model, never the posts themselves. That is
what keeps this pass inside a small local model's context window.
"""

import logging
import re
from collections import Counter

from pydantic import BaseModel

from zeitgeist.llm.base import LLMProvider
from zeitgeist.models import Topic

log = logging.getLogger(__name__)

# Every canonical topic must echo its input tags verbatim, so this is
# the one reply in the pipeline whose size grows with the run: ~300
# posts yield ~700 distinct tags and ~6k output tokens, well past the
# provider default. Budgets above 16k must be streamed, which the
# Anthropic provider always does.
CONSOLIDATE_MAX_TOKENS = 32768

CONSOLIDATE_SYSTEM = (
    "You merge a messy vocabulary of topic tags into a clean set of canonical "
    "topics. Fold synonyms, near-duplicates, plurals, and differing "
    "specificity into a single topic. Every canonical topic must list the "
    "exact input tags that folded into it, copied verbatim. Do not invent "
    "tags that were not given to you. Aim for topics that are specific enough "
    "to be interesting but broad enough to gather several tags."
)


class ConsolidatedTopic(BaseModel):
    """One canonical topic and the input tags it absorbed."""

    label: str
    summary: str
    tags: list[str]


class Consolidation(BaseModel):
    """The full canonical topic set."""

    topics: list[ConsolidatedTopic]


def consolidate(
    tags_by_post: dict[str, list[str]], provider: LLMProvider
) -> list[Topic]:
    """Turn a post-to-tags map into canonical topics carrying post ids."""
    if not tags_by_post:
        return []

    vocabulary = Counter(tag for tags in tags_by_post.values() for tag in tags)

    try:
        consolidation = provider.complete(
            _build_prompt(vocabulary),
            Consolidation,
            system=CONSOLIDATE_SYSTEM,
            max_tokens=CONSOLIDATE_MAX_TOKENS,
        )
    except Exception as exc:
        log.warning("Tag consolidation failed; no topics produced: %s", exc)
        return []

    topics: list[Topic] = []
    used_ids: set[str] = set()

    for entry in consolidation.topics:
        wanted = {tag.strip().lower() for tag in entry.tags}
        post_ids = sorted(
            post_id
            for post_id, tags in tags_by_post.items()
            if wanted & {t.strip().lower() for t in tags}
        )
        if not post_ids:
            log.debug("Dropping topic %r: no posts matched its tags", entry.label)
            continue

        topics.append(
            Topic(
                id=_unique_slug(entry.label, used_ids),
                label=entry.label,
                summary=entry.summary,
                post_ids=post_ids,
            )
        )

    return topics


def _build_prompt(vocabulary: Counter) -> str:
    lines = [f"- {tag} ({count} posts)" for tag, count in vocabulary.most_common()]
    listing = "\n".join(lines)
    return (
        "Merge this tag vocabulary into canonical topics.\n\n"
        f"{listing}\n\n"
        "Return each canonical topic with a short label, a one or two "
        "sentence summary, and the exact input tags it absorbed."
    )


def slugify(label: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", label.strip().lower()).strip("-")
    return slug or "topic"


def _unique_slug(label: str, used: set[str]) -> str:
    base = slugify(label)
    candidate = base
    suffix = 2
    while candidate in used:
        candidate = f"{base}-{suffix}"
        suffix += 1
    used.add(candidate)
    return candidate
