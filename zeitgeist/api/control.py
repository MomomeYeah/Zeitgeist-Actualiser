"""Starting, watching and stopping runs.

Split from `runs.py`, which is five endpoints of read-only history: these
mutate execution, fail differently, and phase 4 adds two more of its own.
"""

from fastapi import APIRouter, Depends, HTTPException, status

from zeitgeist.api.app import get_runner, get_store
from zeitgeist.api.runs import _run_or_404, resume_stage
from zeitgeist.api.schemas import ResumeBody, StartRunBody
from zeitgeist.runner import ActiveRuns, QueuedRun, RunRequest, RunService
from zeitgeist.store import Store

router = APIRouter(prefix="/api/runs", tags=["control"])


@router.post("", response_model=QueuedRun, status_code=status.HTTP_202_ACCEPTED)
def start_run(
    body: StartRunBody, runner: RunService = Depends(get_runner)
) -> QueuedRun:
    """202 rather than 201: the run is queued, and for a queued one there is
    nothing at its URL yet."""
    try:
        return runner.enqueue(
            RunRequest(
                template_ids=body.template_ids,
                overrides=body.overrides,
            )
        )
    except ValueError as exc:
        # The allowlist refused a field. That is the request's fault, not the
        # server's, and letting it escape as a 500 would say the opposite.
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/active", response_model=ActiveRuns)
def read_active(runner: RunService = Depends(get_runner)) -> ActiveRuns:
    return runner.active()


@router.post(
    "/{run_id}/resume",
    response_model=QueuedRun,
    status_code=status.HTTP_202_ACCEPTED,
)
def resume_run(
    run_id: str,
    body: ResumeBody,
    store: Store = Depends(get_store),
    runner: RunService = Depends(get_runner),
) -> QueuedRun:
    _run_or_404(store, run_id)
    stage = body.stage or resume_stage(store, run_id)
    if stage is None:
        # `resume_stage` returns None when nothing was written at all, which
        # is what a source outage looks like. Enqueuing anyway would start a
        # run that fails on its first checkpoint read, and the user would see
        # a second failure instead of a refusal.
        raise HTTPException(
            status_code=409,
            detail=f"Run {run_id} wrote no checkpoints; there is nothing to "
            "resume from.",
        )
    return runner.enqueue(
        RunRequest(
            run_id=run_id,
            start_at=stage,
            template_ids=body.template_ids,
        )
    )


@router.post("/{run_id}/stop", status_code=status.HTTP_202_ACCEPTED)
def stop_run(run_id: str, runner: RunService = Depends(get_runner)) -> dict[str, str]:
    """Finish the current stage, write its checkpoint, then end. The run
    stays resumable, which is what the button promises."""
    if not runner.stop(run_id):
        raise HTTPException(status_code=404, detail=f"Run {run_id} is not running")
    return {"run_id": run_id, "requested": "stop"}


@router.post("/{run_id}/abort", status_code=status.HTTP_202_ACCEPTED)
def abort_run(run_id: str, runner: RunService = Depends(get_runner)) -> dict[str, str]:
    """End now. Ingest is the exception: `fetch_evidence` is one opaque
    `asyncio.run()` with no interior checkpoint, so an abort during it takes
    effect when the fetch returns — which is what the UI's "aborting…" state
    is for."""
    if not runner.abort(run_id):
        raise HTTPException(status_code=404, detail=f"Run {run_id} is not running")
    return {"run_id": run_id, "requested": "abort"}
