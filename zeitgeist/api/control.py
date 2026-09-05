"""Starting, watching and stopping runs.

Split from `runs.py`, which is five endpoints of read-only history: these
mutate execution, fail differently, and phase 4 adds two more of its own.
"""

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from zeitgeist.api.app import get_runner, get_store
from zeitgeist.api.runs import _run_or_404, resume_stage
from zeitgeist.api.schemas import ResumeBody, StartRunBody
from zeitgeist.records import ORDER
from zeitgeist.runner import (
    ActiveRuns,
    QueuedRun,
    RunAlreadyActive,
    RunRequest,
    RunService,
)
from zeitgeist.store import Store

router = APIRouter(prefix="/api/runs", tags=["control"])

POLL_SECONDS = 0.25


def _sse(name: str, data: str) -> str:
    return f"event: {name}\ndata: {data}\n\n"


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
    except RunAlreadyActive as exc:
        # A fresh run always gets a fresh id from new_run_id(), so this can
        # only fire if id generation somehow collided with a run still in
        # flight — a conflict, not a malformed request, so this must not
        # fall into the generic ValueError branch below and come out a 400.
        raise HTTPException(status_code=409, detail=str(exc)) from exc
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
    if body.stage is not None:
        # `resume_stage`'s own return is honourable by construction — it is
        # the first stage with no checkpoint, so everything earlier already
        # has one. A stage the *client* names carries no such guarantee:
        # resuming at generate with only an ingest checkpoint would enqueue a
        # run whose generate branch reads a missing analyse or evaluate
        # checkpoint and fails on the worker thread — well after the 202 the
        # client already got.
        written = store.written_stages(run_id)
        for earlier in ORDER[: ORDER.index(body.stage)]:
            if earlier not in written:
                raise HTTPException(
                    status_code=409,
                    detail=f"Run {run_id} has no {earlier.value} checkpoint; "
                    f"cannot resume at {body.stage.value}.",
                )
    try:
        return runner.enqueue(
            RunRequest(
                run_id=run_id,
                start_at=stage,
                template_ids=body.template_ids,
            )
        )
    except RunAlreadyActive as exc:
        # Distinct from the 409s above: those mean the run has nothing to
        # resume from, this means it does not need resuming at all right
        # now — a double-clicked Resume button, or a second tab racing the
        # first. A client that cannot tell the two apart cannot render two
        # different messages for them.
        raise HTTPException(status_code=409, detail=str(exc)) from exc


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


@router.get("/{run_id}/events")
def stream_events(
    run_id: str,
    store: Store = Depends(get_store),
    runner: RunService = Depends(get_runner),
) -> StreamingResponse:
    """Log lines and progress ticks, until the run ends.

    Polls the run's buffer rather than being pushed to. A quarter-second of
    latency on a log line is invisible, and polling keeps the logging handler
    free of any reference to the event loop — which is what lets the same
    handler work under `TestClient` and under the dev harness.

    A tick carries no payload. The observer has already written
    `run_records`, `run_stages` and `run_topics` from the worker thread, so
    the client refetches rather than being handed the same data twice.
    """
    _run_or_404(store, run_id)

    async def generate() -> AsyncIterator[str]:
        seq = 0
        while True:
            buffer = runner.buffer(run_id)
            executing = runner.active().current == run_id
            if buffer is not None:
                lines = buffer.since(seq)
                if lines:
                    seq = lines[-1].seq
                    yield _sse(
                        "log",
                        json.dumps(
                            [
                                {
                                    "seq": line.seq,
                                    "logged_at": line.logged_at.isoformat(),
                                    "level": line.level,
                                    "logger": line.logger,
                                    "message": line.message,
                                }
                                for line in lines
                            ]
                        ),
                    )
            yield _sse("tick", json.dumps({"seq": seq}))
            if not executing and buffer is None:
                # The worker drops the buffer when the run ends, so this is
                # the run being over *and* its last lines already drained.
                # A stream that stayed open would hold a connection per
                # watched run for the life of the process.
                return
            await asyncio.sleep(POLL_SECONDS)

    return StreamingResponse(generate(), media_type="text/event-stream")
