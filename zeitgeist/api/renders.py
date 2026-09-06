"""One render's record, and its image.

The record endpoint exists because the full-size view is deep-linkable: a
render has to be addressable on its own rather than only arriving embedded
in topic detail, and the view shows the slot text and — for an auto render —
the rationale behind the template choice.

Deletion lives here rather than beside `POST .../renders` in
`api/generate.py`, because it is addressed by render id and belongs under
this prefix. `zeitgeist.renders.delete_render` is the row-and-files unit
both the endpoint and a re-run of the generate stage go through.

The database is authoritative for whether a render exists. A PNG deleted out
from under its row is a 404 that says so, never a 500.
"""

from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import FileResponse

from zeitgeist.api.app import get_settings, get_store
from zeitgeist.config import Settings
from zeitgeist.records import RenderRecord
from zeitgeist.renders import delete_render, render_paths
from zeitgeist.store import Store

router = APIRouter(prefix="/api/renders", tags=["renders"])

ImageSize = Literal["full", "thumb"]


def _image_path(settings: Settings, record: RenderRecord, size: ImageSize) -> Path:
    """The layout lives in `zeitgeist.renders`, which the deletion path and
    the pipeline resolve through too — one definition, several callers."""
    paths = render_paths(settings.output_dir, record.run_id, record.id)
    return paths.full if size == "full" else paths.thumb


def _render_or_404(store: Store, render_id: str) -> RenderRecord:
    """Both handlers' preamble: the render record, or the 404 naming it."""
    record = store.get_render(render_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"No such render: {render_id}")
    return record


@router.get("/{render_id}", response_model=RenderRecord)
def read_render(render_id: str, store: Store = Depends(get_store)) -> RenderRecord:
    return _render_or_404(store, render_id)


@router.get("/{render_id}/image")
def read_image(
    render_id: str,
    size: ImageSize = "full",
    store: Store = Depends(get_store),
    settings: Settings = Depends(get_settings),
) -> FileResponse:
    record = _render_or_404(store, render_id)
    path = _image_path(settings, record, size)
    if not path.is_file():
        raise HTTPException(
            status_code=404,
            detail=f"Render {render_id} has no {size} image on disk",
        )
    return FileResponse(path, media_type="image/png")


@router.delete("/{render_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_render(
    render_id: str,
    store: Store = Depends(get_store),
    settings: Settings = Depends(get_settings),
) -> Response:
    """204 and no body. The row goes first, then both files.

    A render whose PNG is already missing still deletes cleanly: the row is
    what makes it exist, and the end state is the same either way.

    The meme count every screen shows is `COUNT(*)` over `renders` at query
    time, so nothing else has to be told this happened — which is the
    reason that count is not a column.
    """
    record = _render_or_404(store, render_id)
    delete_render(store, settings.output_dir, record)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
