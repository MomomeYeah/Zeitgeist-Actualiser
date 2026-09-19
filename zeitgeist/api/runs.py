"""Everything scoped to one run: the list, the detail, the ranking, one
topic's dossier, the log — and deleting it.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from zeitgeist.api.app import get_generator, get_runner, get_settings, get_store
from zeitgeist.api.schemas import (
    RankedTopic,
    ReplyOut,
    RunDetail,
    RunPage,
    RunSummary,
    TopicDetail,
    TopicRecurrence,
)
from zeitgeist.config import Settings
from zeitgeist.generation import GenerationService, RunBusy
from zeitgeist.models import Topic, TrendEvidence
from zeitgeist.records import ORDER, LogLine, RunRecordRow, Stage
from zeitgeist.renders import delete_run_files
from zeitgeist.runner import RunAlreadyActive, RunService
from zeitgeist.store import MissingCheckpoint, Store, UnknownRun, run_cursor

router = APIRouter(prefix="/api/runs", tags=["runs"])

# The Runs list draws three rows in the sidebar strip and pages beyond that.
DEFAULT_PAGE = 25


def _run_or_404(store: Store, run_id: str) -> RunRecordRow:
    """Every run-scoped handler's preamble: the run, or the 404 naming it.

    Phase 3 adds /resume, /stop and /abort to this same router, each
    needing the same check — collapsing it here is what stops a fourth and
    fifth copy of the message drifting from these.
    """
    run = store.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"No such run: {run_id}")
    return run


@router.get("", response_model=RunPage)
def list_runs(
    limit: int = Query(default=DEFAULT_PAGE, ge=1, le=100),
    cursor: str | None = None,
    store: Store = Depends(get_store),
) -> RunPage:
    rows = store.list_runs(limit=limit, cursor=cursor)
    # Three queries for the page, not `1 + 2 × limit`. Read per row — a
    # `run_topics` and a `renders_for_run` inside the comprehension — the
    # default page cost 51 queries to draw 25 rows, each one paying
    # `Store`'s lock and the API thread pool's hop for a handful of
    # columns. The two batch reads return the same rows in the same order,
    # so the response is byte-identical to what the loop produced.
    run_ids = [row.run_id for row in rows]
    labels = store.topic_labels_for_runs(run_ids)
    render_ids = store.render_ids_for_runs(run_ids)
    summaries = [
        RunSummary(
            run=row,
            topic_labels=labels.get(row.run_id, []),
            render_ids=render_ids.get(row.run_id, []),
        )
        for row in rows
    ]
    # A short page is the last page. Reporting a cursor here would hand the
    # client one more request that always comes back empty.
    next_cursor = run_cursor(rows[-1]) if len(rows) == limit else None
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
    run = _run_or_404(store, run_id)
    return RunDetail(
        run=run,
        stages=store.stages_for_run(run_id),
        resume_stage=resume_stage(store, run_id),
        render_count=sum(store.render_counts(run_id).values()),
    )


@router.delete("/{run_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_run(
    run_id: str,
    runner: RunService = Depends(get_runner),
    generator: GenerationService = Depends(get_generator),
    settings: Settings = Depends(get_settings),
) -> Response:
    """204 and no body. The row goes first, cascading to everything that
    hangs off it, then the run's directory.

    Refused with a 409 while anything is still writing to the run: the run
    worker, if it is executing or queued, or an on-demand generation job.
    `excluding` holds new generation jobs off for as long as the row delete
    takes; `RunService.delete` does the liveness check and the delete under
    the lock `enqueue` takes, so a resume cannot interleave. The directory
    is removed after both are released — the run no longer exists by then,
    so nothing can write to it again.
    """
    try:
        with generator.excluding(run_id):
            runner.delete(run_id)
    except UnknownRun as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (RunAlreadyActive, RunBusy) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    delete_run_files(settings.output_dir, run_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{run_id}/topics", response_model=list[RankedTopic])
def read_ranking(run_id: str, store: Store = Depends(get_store)) -> list[RankedTopic]:
    run = _run_or_404(store, run_id)
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
    _run_or_404(store, run_id)
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
        renders=store.renders_for_topic(run_id, topic_id),
        recurrence=TopicRecurrence(run_count=count, first_seen_run_id=first_seen),
    )


@router.get("/{run_id}/log", response_model=list[LogLine])
def read_log(
    run_id: str, verbose: bool = False, store: Store = Depends(get_store)
) -> list[LogLine]:
    """One run's whole log, every time.

    No `since_seq`. Phase 2 left the question open because incremental
    polling was the only way a live log could have worked; phase 3's
    `GET /api/runs/{id}/events` settled it by making this endpoint the
    *other* half of a pair. The stream carries a live run's lines, keyed on
    exactly the `seq` a `since_seq` here would have taken, and the client
    enables the two exclusively — `RunDetailPage` opens the stream while
    the run's status is `running` and only calls this once it is not.

    So the one caller asks a finished run for its whole log, once, and a
    `since_seq` would be a parameter nothing passes: a second cursor
    protocol, a second set of tests, and a second way for the log to arrive
    with a hole in it. A finished run's log is bounded by the run, and the
    verbose toggle filters what is *returned* rather than what was
    captured, which is what lets flipping it work retroactively — that only
    holds while the endpoint serves the whole thing.
    """
    _run_or_404(store, run_id)
    return store.log_lines(run_id, verbose=verbose)
