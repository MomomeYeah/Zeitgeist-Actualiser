"""One render's record, and its image.

The record endpoint exists because the full-size view is deep-linkable: a
render has to be addressable on its own rather than only arriving embedded
in topic detail, and the view shows the slot text and — for an auto render —
the rationale behind the template choice.

The database is authoritative for whether a render exists. A PNG deleted out
from under its row is a 404 that says so, never a 500.
"""

from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from zeitgeist.api.app import get_settings, get_store
from zeitgeist.config import Settings
from zeitgeist.records import RenderRecord
from zeitgeist.store import Store

router = APIRouter(prefix="/api/renders", tags=["renders"])

ImageSize = Literal["full", "thumb"]


def _image_path(settings: Settings, record: RenderRecord, size: ImageSize) -> Path:
    suffix = ".png" if size == "full" else ".thumb.png"
    return (
        Path(settings.output_dir) / record.run_id / "renders" / f"{record.id}{suffix}"
    )


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
