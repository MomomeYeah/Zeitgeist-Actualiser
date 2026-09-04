"""Everything scoped to one run: the list, the detail, the ranking, one
topic's dossier, and the log.
"""

from fastapi import APIRouter, Depends, HTTPException, Query

from zeitgeist.api.app import get_store
from zeitgeist.api.schemas import RankedTopic, RunDetail, RunPage, RunSummary
from zeitgeist.records import ORDER, Stage
from zeitgeist.store import Store

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
