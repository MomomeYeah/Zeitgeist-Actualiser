"""Everything scoped to one run: the list, the detail, the ranking, one
topic's dossier, and the log.
"""

from fastapi import APIRouter, Depends, HTTPException, Query

from zeitgeist.api.app import get_store
from zeitgeist.api.schemas import (
    RankedTopic,
    ReplyOut,
    RunDetail,
    RunPage,
    RunSummary,
    TopicDetail,
    TopicRecurrence,
)
from zeitgeist.models import Topic, TrendEvidence
from zeitgeist.records import ORDER, LogLine, Stage
from zeitgeist.store import MissingCheckpoint, Store

router = APIRouter(prefix="/api/runs", tags=["runs"])

# The Runs list draws three rows in the sidebar strip and pages beyond that.
DEFAULT_PAGE = 25


@router.get("", response_model=RunPage)
def list_runs(
    limit: int = Query(default=DEFAULT_PAGE, ge=1, le=100),
    cursor: str | None = None,
    store: Store = Depends(get_store),
) -> RunPage:
    rows = store.list_runs(limit=limit, cursor=cursor)
    summaries = [
        RunSummary(
            run=row,
            topic_labels=[t.label for t in store.run_topics(row.run_id)],
            render_ids=[r.id for r in store.renders_for_run(row.run_id)],
        )
        for row in rows
    ]
    # A short page is the last page. Reporting a cursor here would hand the
    # client one more request that always comes back empty.
    next_cursor = rows[-1].started_at.isoformat() if len(rows) == limit else None
    return RunPage(runs=summaries, next_cursor=next_cursor)


def resume_stage(store: Store, run_id: str) -> Stage | None:
    """The first stage with no checkpoint, or None if that is ingest.

    Nothing written at all means the run has to start over rather than
    resume, which is what a source outage looks like. Every checkpoint
    present means generate: re-rendering a frozen ranking is always
    available, and is the template-tuning loop.
    """
    written = store.written_stages(run_id)
    for stage in ORDER:
        if stage not in written:
            return None if stage is Stage.INGEST else stage
    return Stage.GENERATE


@router.get("/{run_id}", response_model=RunDetail)
def read_run(run_id: str, store: Store = Depends(get_store)) -> RunDetail:
    run = store.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"No such run: {run_id}")
    return RunDetail(
        run=run,
        stages=store.stages_for_run(run_id),
        resume_stage=resume_stage(store, run_id),
    )


@router.get("/{run_id}/topics", response_model=list[RankedTopic])
def read_ranking(run_id: str, store: Store = Depends(get_store)) -> list[RankedTopic]:
    run = store.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"No such run: {run_id}")
    counts = store.render_counts(run_id)
    return [
        RankedTopic(
            topic=row,
            render_count=counts.get(row.topic_id, 0),
            above_cut=row.final_rank <= run.config.top_count,
        )
        # Already ordered by final_rank. The endpoint sorts by nothing of
        # its own: rank_score is the single place the blend is defined.
        for row in store.run_topics(run_id)
    ]


# A topic can carry hundreds of replies and the card list is not paginated.
# Most-liked first: the design shows the conversation, not all of it.
MAX_REPLIES = 20


def _replies_for(store: Store, run_id: str, item_ids: set[str]) -> list[ReplyOut]:
    """Replies under this topic's own posts, most-liked first.

    A missing ingest checkpoint is not an error: it is the biggest payload
    in the database and a later phase may prune it. A dossier without
    replies is still a dossier.
    """
    try:
        evidence = store.read_checkpoint(run_id, Stage.INGEST, TrendEvidence)
    except MissingCheckpoint:
        return []
    replies = [
        reply
        for entry in evidence
        for post in entry.posts
        if post.item.source_id in item_ids
        for reply in post.replies
    ]
    replies.sort(key=lambda reply: reply.like_count, reverse=True)
    return [
        ReplyOut(
            text=reply.text,
            like_count=reply.like_count,
            created_at=reply.created_at,
        )
        for reply in replies[:MAX_REPLIES]
    ]


@router.get("/{run_id}/topics/{topic_id}", response_model=TopicDetail)
def read_topic(
    run_id: str, topic_id: str, store: Store = Depends(get_store)
) -> TopicDetail:
    row = next((r for r in store.run_topics(run_id) if r.topic_id == topic_id), None)
    if row is None:
        raise HTTPException(
            status_code=404, detail=f"No such topic in {run_id}: {topic_id}"
        )

    try:
        topics = store.read_checkpoint(run_id, Stage.ANALYSE, Topic)
    except MissingCheckpoint:
        topics = []
    topic = next((t for t in topics if t.id == topic_id), None)

    count, first_seen = store.topic_recurrence(row.label_slug)
    return TopicDetail(
        topic=row,
        dossier=None if topic is None else topic.dossier,
        score_components={} if topic is None else topic.score_components,
        replies=_replies_for(store, run_id, set(topic.item_ids) if topic else set()),
        renders=[
            render
            for render in store.renders_for_run(run_id)
            if render.topic_id == topic_id
        ],
        recurrence=TopicRecurrence(run_count=count, first_seen_run_id=first_seen),
    )


@router.get("/{run_id}/log", response_model=list[LogLine])
def read_log(
    run_id: str, verbose: bool = False, store: Store = Depends(get_store)
) -> list[LogLine]:
    if store.get_run(run_id) is None:
        raise HTTPException(status_code=404, detail=f"No such run: {run_id}")
    return store.log_lines(run_id, verbose=verbose)
