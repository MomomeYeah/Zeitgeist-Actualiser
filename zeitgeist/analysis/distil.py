"""Evidence to topic: one LLM call per trend.

Replaces the extract-then-consolidate pair. Those two stages spent LLM calls
reconstructing a clustering Bluesky had already done, and lost every specific
fact on the way — consolidation never saw a sentence, only a tag vocabulary,
so the summaries it wrote were confabulations about word clusters.

This stage does the opposite. It sees the trend's own description of the
event, the posts, and what people said underneath them, and its output is the
first thing in the pipeline that knows what actually happened.
"""

import logging
from concurrent.futures import ThreadPoolExecutor

from pydantic import BaseModel, Field

from zeitgeist.analysis.phrases import mine_phrases
from zeitgeist.analysis.slug import unique_slug
from zeitgeist.config import Settings
from zeitgeist.llm.base import LLMProvider
from zeitgeist.models import (
    BlueskyMetrics,
    Dossier,
    Phrase,
    PostEvidence,
    Register,
    Reply,
    Sentiment,
    Topic,
    TrendEvidence,
)

log = logging.getLogger(__name__)


class DistilError(Exception):
    """Raised when evidence was supplied but every trend failed to distil.

    An empty run is a failure rather than a result (see the design spec's
    "Failure handling"): the ingest side already raises SourceError when no
    trend yields usable posts, and this is the analyse-side counterpart, so
    the realistic failure mode of a local model that cannot hold the
    response schema surfaces as `Run failed: ...` rather than a silent,
    empty `topics.json`.
    """


DISTIL_SYSTEM = (
    "You analyse a trending conversation on social media and report what is "
    "actually going on in it.\n\n"
    "You are given a trend, the posts driving it, and replies to those "
    "posts. The posts are often links or headlines; the replies are what "
    "people think. Both matter, and they are not the same thing.\n\n"
    "Report two judgements separately and do not let one contaminate the "
    "other. `event_sentiment` is how the event itself feels. "
    "`conversation_register` is the posture people are taking toward it. "
    "These frequently disagree, and "
    "the disagreement is the most useful thing you can tell us: a death met "
    "with warm tribute is not the same conversation as a death met with "
    "grief, and neither is the same as one met with jokes.\n\n"
    "Be specific. Name the people, places and organisations involved. "
    "'US politics' is not an answer; 'Canada imposed retaliatory tariffs "
    "after trade talks collapsed' is. If you cannot say concretely what "
    "happened, say what the replies suggest happened rather than retreating "
    "to the category the story belongs to."
)

_PHRASE_GUIDANCE = (
    "These phrases were each used by the stated number of DISTINCT accounts, "
    "counted mechanically. They are the vocabulary this conversation has "
    "converged on. Use them to judge the register, and let them inform how "
    "you write — but your summary must stand on its own. Restating a phrase "
    "is not a summary."
)


class DossierDraft(BaseModel):
    """What the model returns. `recurring_phrases` is not here on purpose:
    it is measured, and a model asked for catchphrases invents them.
    """

    what_happened: str
    key_entities: list[str] = Field(default_factory=list)
    conversation_summary: str
    conversation_register: Register
    secondary_registers: list[Register] = Field(default_factory=list)
    event_sentiment: Sentiment
    valence: float = Field(ge=-1.0, le=1.0)
    meme_potential: float = Field(ge=0.0, le=1.0)


def distil_topics(
    evidence: list[TrendEvidence], provider: LLMProvider, settings: Settings
) -> list[Topic]:
    """Distil every trend. A single trend whose call fails is dropped, not
    fatal — but if every trend fails, that is a failed run, not an empty
    result; see `DistilError`.
    """
    if not evidence:
        return []

    with ThreadPoolExecutor(max_workers=settings.distil_concurrency) as pool:
        drafts = list(
            pool.map(lambda one: _distil_one(one, provider, settings), evidence)
        )

    if all(result is None for result in drafts):
        raise DistilError(
            f"All {len(evidence)} trend(s) failed distillation; see the "
            "warnings above for each trend's error."
        )

    topics: list[Topic] = []
    used_ids: set[str] = set()
    for entry, result in zip(evidence, drafts, strict=True):
        if result is None:
            continue
        draft, phrases = result
        topics.append(
            Topic(
                id=unique_slug(entry.trend.display_name, used_ids),
                label=entry.trend.display_name,
                summary=draft.what_happened,
                item_ids=[post.item.source_id for post in entry.posts],
                dossier=Dossier(
                    **draft.model_dump(),
                    recurring_phrases=phrases,
                ),
            )
        )
    return topics


def _distil_one(
    entry: TrendEvidence, provider: LLMProvider, settings: Settings
) -> tuple[DossierDraft, list[Phrase]] | None:
    replies = [reply for post in entry.posts for reply in post.replies]
    phrases = mine_phrases(
        replies, entry.trend, min_authors=settings.phrase_min_authors
    )
    # Built outside the try: a bug here must crash loudly, not be misreported
    # as a failed trend and silently skipped.
    prompt = _build_prompt(entry, replies, phrases, settings.distil_char_budget)
    try:
        return provider.complete(prompt, DossierDraft, system=DISTIL_SYSTEM), phrases
    except Exception as exc:
        log.warning(
            "Distillation failed for %r; dropping: %s",
            entry.trend.display_name,
            exc,
        )
        return None


def _render_post(post: PostEvidence) -> str:
    """One post, with its engagement rather than its trend name — the trend
    name is already the prompt's first line, so repeating it there carried
    no information. `Item.metrics` is a union across platforms; every
    TrendEvidence is Bluesky's today (it is the only TrendSource), so the
    engagement counts are shown when the metrics are Bluesky's and omitted,
    rather than guessed, otherwise.
    """
    metrics = post.item.metrics
    if isinstance(metrics, BlueskyMetrics):
        engagement = (
            f"{metrics.like_count} likes, {metrics.repost_count} reposts, "
            f"{metrics.reply_count} replies"
        )
        return f"- [{engagement}] {post.item.title}"
    return f"- {post.item.title}"


def _build_prompt(
    entry: TrendEvidence,
    replies: list[Reply],
    phrases: list[Phrase],
    budget: int,
) -> str:
    trend = entry.trend
    posts = "\n".join(_render_post(post) for post in entry.posts)
    sample = "\n".join(f"- {reply.text}" for reply in _sample(replies, budget))
    phrase_lines = "\n".join(
        f"- {phrase.text!r} — {phrase.distinct_authors} distinct accounts, "
        f"{phrase.occurrences} uses"
        for phrase in phrases
    )

    # None marks a section this trend has nothing for; "" is a deliberate
    # blank line. Only the Nones are dropped.
    sections: list[str | None] = [
        f"Trend: {trend.display_name}",
        f"Description: {trend.description}" if trend.description else None,
        f"Category: {trend.category}" if trend.category else None,
        f"Volume: {trend.post_count} posts, currently {trend.status}",
        "",
        f"Posts driving it:\n{posts}",
        "",
        f"Replies:\n{sample}" if sample else "Replies: none available.",
    ]
    if phrase_lines:
        sections += ["", f"Recurring phrases:\n{phrase_lines}", "", _PHRASE_GUIDANCE]
    sections += [
        "",
        "Report what happened, what people are saying, the event's sentiment "
        "and the conversation's register.",
    ]
    return "\n".join(section for section in sections if section is not None)


def _sample(replies: list[Reply], budget: int) -> list[Reply]:
    """Most-liked first, up to the character budget.

    Sorting by likes biases toward the loudest replies. That is the intended
    bias: what resonated is the question being asked.
    """
    kept: list[Reply] = []
    spent = 0
    for reply in sorted(replies, key=lambda one: -one.like_count):
        if spent + len(reply.text) > budget:
            break
        kept.append(reply)
        spent += len(reply.text)
    return kept
