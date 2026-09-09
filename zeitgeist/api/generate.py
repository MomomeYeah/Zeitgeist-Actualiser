"""On-demand generation: turning a topic into memes after its run ended.

Its own router rather than an addition to `control.py`, which owns run
execution. This drives a different service with a different lifecycle, and
its sibling `DELETE /api/renders/{id}` cannot live under the `/api/runs`
prefix at all — so "both of phase 4's endpoints in one module" was never
available, and splitting by responsibility keeps each router about one
thing.
"""

from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, status

from zeitgeist.api.app import get_generator, get_store
from zeitgeist.api.runs import _run_or_404
from zeitgeist.generation import GenerationRequest, GenerationService, UnknownTopic
from zeitgeist.records import RenderRecord
from zeitgeist.store import MissingCheckpoint, Store

router = APIRouter(prefix="/api/runs", tags=["generation"])


@router.post(
    "/{run_id}/topics/{topic_id}/renders",
    response_model=list[RenderRecord],
    status_code=status.HTTP_202_ACCEPTED,
)
def create_renders(
    run_id: str,
    topic_id: str,
    body: Annotated[GenerationRequest, Body(discriminator="mode")],
    store: Store = Depends(get_store),
    generator: GenerationService = Depends(get_generator),
) -> list[RenderRecord]:
    """202, and the rows come back `generating`.

    The rows are written before this returns rather than when the job
    finishes: the database is authoritative for whether a render exists,
    so a tile with no row behind it would vanish on the next reload. A
    `generating` row's `caption_slots` and — for an auto render — its
    rationale are not filled in yet and must not be read.

    A bare list rather than an envelope, per `api/schemas.py`: there are no
    aggregates to carry.
    """
    _run_or_404(store, run_id)
    try:
        return generator.submit(run_id, topic_id, body)
    except MissingCheckpoint as exc:
        # Distinct from the 404 below: the run exists and the topic may
        # well have too, but the run died before analyse wrote anything,
        # so there is no dossier to brief from. Answering "no such topic"
        # would send the user looking for the wrong problem.
        raise HTTPException(
            status_code=409,
            detail=f"Run {run_id} has no analyse checkpoint; there is nothing "
            "to brief from.",
        ) from exc
    except UnknownTopic as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        # GenerationRefused (an unknown template, captions that do not fit)
        # and build_provider's "ANTHROPIC_API_KEY is required" alike: both
        # are the request's fault against the current configuration, not
        # the server's, and a 500 would say the opposite. This must stay
        # last — GenerationRefused is a ValueError subclass.
        raise HTTPException(status_code=400, detail=str(exc)) from exc
