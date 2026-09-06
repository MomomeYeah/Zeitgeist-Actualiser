"""Builders for run bookkeeping records and the topics tests store.

Built through the real models for the same reason `template_factory` is: a
change to `RunConfig` or `RenderRecord` surfaces as a type error at one site
rather than as a ValidationError raised from inside dozens of unrelated
tests. Passing these as plain dicts would defeat that — pydantic coerces
them at runtime and ty never checks them.

Defaults exist so a test states only what it asserts on. A test that cares
about a topic's sentiment passes one; the rest say nothing and get something
valid.
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Literal

from zeitgeist.models import (
    BlueskyMetrics,
    Dossier,
    Item,
    Phrase,
    PostEvidence,
    Register,
    Reply,
    ScoredTopic,
    Sentiment,
    Topic,
    TrendEvidence,
    TrendInfo,
    TrendStatus,
)
from zeitgeist.records import (
    AutoOrigin,
    Origin,
    RenderRecord,
    RunConfig,
    Stage,
    StageRecord,
    StageStatus,
)


class _Unset:
    """Distinguishes "caller didn't pass this" from "caller passed None".

    `dossier` is itself `Dossier | None` on the model — None is dormant-path
    data, not "use the default". A bare `= None` default can't tell the two
    apart, so a caller asking for `dossier=None` would silently get
    `make_dossier()` instead.
    """


_UNSET = _Unset()

FIXED_TIME = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


def make_run_config(
    *,
    sources: list[str] | None = None,
    trend_limit: int = 25,
    posts_per_trend: int = 10,
    top_count: int = 5,
    meme_potential_weight: float = 0.3,
    phrase_min_authors: int = 3,
    distil_char_budget: int = 24000,
    distil_concurrency: int = 4,
    llm_provider: str = "anthropic",
    llm_model: str = "claude-sonnet-5",
    template_ids: list[str] | None = None,
) -> RunConfig:
    return RunConfig(
        sources=sources if sources is not None else ["bluesky"],
        trend_limit=trend_limit,
        posts_per_trend=posts_per_trend,
        top_count=top_count,
        meme_potential_weight=meme_potential_weight,
        phrase_min_authors=phrase_min_authors,
        distil_char_budget=distil_char_budget,
        distil_concurrency=distil_concurrency,
        llm_provider=llm_provider,
        llm_model=llm_model,
        template_ids=template_ids,
    )


def make_stage_record(
    stage: Stage = Stage.INGEST,
    *,
    status: StageStatus = "ok",
    started_at: datetime | None = FIXED_TIME,
    finished_at: datetime | None = FIXED_TIME,
    payload_bytes: int | None = 1024,
    summary: str = "25 trends",
) -> StageRecord:
    return StageRecord(
        stage=stage,
        status=status,
        started_at=started_at,
        finished_at=finished_at,
        payload_bytes=payload_bytes,
        summary=summary,
    )


def make_render_record(
    rid: str = "rnd1",
    *,
    run_id: str = "20260901T120000Z",
    topic_id: str = "airport-cat",
    template_id: str = "drake",
    caption_slots: dict[str, str] | None = None,
    origin: Origin | None = None,
    status: Literal["generating", "ready", "failed"] = "ready",
    error: str | None = None,
    created_at: datetime = FIXED_TIME,
) -> RenderRecord:
    return RenderRecord(
        id=rid,
        run_id=run_id,
        topic_id=topic_id,
        template_id=template_id,
        caption_slots=(
            caption_slots
            if caption_slots is not None
            else {"rejected": "a", "preferred": "b"}
        ),
        origin=origin if origin is not None else AutoOrigin(rationale="it fits"),
        status=status,
        error=error,
        created_at=created_at,
    )


def make_dossier(
    *,
    event_sentiment: Sentiment = Sentiment.FUNNY,
    conversation_register: Register = Register.RIFFING,
    meme_potential: float | None = 0.86,
    phrases: list[Phrase] | None = None,
) -> Dossier:
    return Dossier(
        what_happened="A cat got into an airport.",
        key_entities=["Heathrow"],
        conversation_summary="Everyone is delighted.",
        conversation_register=conversation_register,
        event_sentiment=event_sentiment,
        meme_potential=meme_potential,
        recurring_phrases=(
            phrases
            if phrases is not None
            else [Phrase(text="airport cat", occurrences=48, distinct_authors=31)]
        ),
    )


def make_topic(
    tid: str = "airport-cat",
    *,
    label: str | None = None,
    trend_status: TrendStatus = "trending",
    trend_score: float = 0.91,
    item_ids: list[str] | None = None,
    dossier: Dossier | None | _Unset = _UNSET,
    score_components: dict[str, float] | None = None,
) -> Topic:
    return Topic(
        id=tid,
        label=label if label is not None else tid.replace("-", " ").title(),
        summary="A cat got into an airport.",
        item_ids=item_ids if item_ids is not None else ["at://post/1"],
        trend_status=trend_status,
        trend_score=trend_score,
        score_components=(
            score_components
            if score_components is not None
            else {"bluesky": 0.91, "corroboration": 1.0}
        ),
        dossier=make_dossier() if isinstance(dossier, _Unset) else dossier,
    )


def make_scored_topic(
    tid: str = "airport-cat",
    *,
    rank: int = 1,
    label: str | None = None,
    trend_status: TrendStatus = "trending",
    trend_score: float = 0.91,
    item_ids: list[str] | None = None,
    dossier: Dossier | None | _Unset = _UNSET,
    score_components: dict[str, float] | None = None,
) -> ScoredTopic:
    """A ScoredTopic with the same defaults as `make_topic`, plus a rank."""
    topic = make_topic(
        tid,
        label=label,
        trend_status=trend_status,
        trend_score=trend_score,
        item_ids=item_ids,
        dossier=dossier,
        score_components=score_components,
    )
    return ScoredTopic(**topic.model_dump(), final_rank=rank)


def make_evidence(
    source_ids: list[str],
    *,
    name: str = "A trend",
    replies: Sequence[Reply] = (),
    status: TrendStatus = "trending",
) -> TrendEvidence:
    """One trend's evidence, for tests that need an ingest checkpoint.

    `source_ids` are the post ids the topic's `item_ids` will match against,
    which is what makes a seeded run's topic detail able to find its replies.
    """
    return TrendEvidence(
        trend=TrendInfo(
            topic_id=f"id-{name}",
            display_name=name,
            description="Something happened.",
            category="news",
            post_count=len(source_ids),
            started_at=FIXED_TIME,
            status=status,
        ),
        posts=[
            PostEvidence(
                item=Item(
                    source_id=source_id,
                    title="a post",
                    permalink=f"https://bsky.app/profile/x/post/{source_id}",
                    fetched_at=FIXED_TIME,
                    metrics=BlueskyMetrics(
                        like_count=1,
                        reply_count=len(replies),
                        repost_count=0,
                        trend=name,
                        status=status,
                        created_at=FIXED_TIME,
                    ),
                ),
                replies=list(replies),
            )
            for source_id in source_ids
        ],
    )
