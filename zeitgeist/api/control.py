"""Starting, watching and stopping runs.

Split from `runs.py`, which is five endpoints of read-only history: these
mutate execution, fail differently, and phase 4 adds two more of its own.
"""

from fastapi import APIRouter, Depends, HTTPException, status

from zeitgeist.api.app import get_runner
from zeitgeist.api.schemas import StartRunBody
from zeitgeist.runner import ActiveRuns, QueuedRun, RunRequest, RunService

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
