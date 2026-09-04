"""Everything scoped to one run: the list, the detail, the ranking, one
topic's dossier, and the log.
"""

from fastapi import APIRouter, Depends, Query

from zeitgeist.api.app import get_store
from zeitgeist.api.schemas import RunPage, RunSummary
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
