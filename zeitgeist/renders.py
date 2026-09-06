"""Where a render's two files live, and how a render is removed.

The database is authoritative for whether a render exists — but a render is
a row *and* a pair of PNGs, and two callers need all three gone together:
`DELETE /api/renders/{id}`, and the re-run that clears a topic's previous
model-written attempts. One function rather than two copies of
`unlink(missing_ok=True)`.

Separate from `store.py`, which knows rows and deliberately nothing about
the filesystem, and from `api/renders.py`, which is the HTTP layer over
this. Nothing here imports `zeitgeist.api`.
"""

import logging
from dataclasses import dataclass
from pathlib import Path

from zeitgeist.records import RenderRecord
from zeitgeist.store import Store

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class RenderPaths:
    """A render's two files. `thumb` is the 96px copy the Runs list and the
    topic grid draw; `full` is what the meme view shows."""

    full: Path
    thumb: Path


def render_paths(output_dir: Path, run_id: str, render_id: str) -> RenderPaths:
    """`output/<run_id>/renders/<render_id>.png` and its thumbnail.

    The single definition of that layout. `_render_all`, the on-demand
    executor, image serving and deletion all resolve a render's files
    through here, so swapping the local directory for real object storage
    later touches one function.
    """
    directory = Path(output_dir) / run_id / "renders"
    return RenderPaths(
        full=directory / f"{render_id}.png",
        thumb=directory / f"{render_id}.thumb.png",
    )


def delete_render(store: Store, output_dir: Path, record: RenderRecord) -> bool:
    """Remove the row and both files. False means the row had already gone.

    The row goes first, deliberately. A crash between the two leaves two
    orphaned PNGs that nothing references — invisible, and reclaimed by
    deleting the run directory. The other order would leave a row pointing
    at files that no longer exist, which topic detail draws as a broken
    tile forever.

    A missing PNG is not an error: the row is what makes a render exist,
    and `missing_ok=True` reaches the same end state either way.
    """
    removed = store.delete_render(record.id)
    paths = render_paths(output_dir, record.run_id, record.id)
    paths.full.unlink(missing_ok=True)
    paths.thumb.unlink(missing_ok=True)
    return removed


def clear_auto_renders(
    store: Store, output_dir: Path, run_id: str, topic_id: str
) -> int:
    """Remove this run's model-written renders for one topic, returning how
    many went. Hand-written renders are never touched.

    This is what makes a re-run of `generate` replace its previous attempt
    rather than pile a second one on top of it — the behaviour the old
    CLI's fixed `{position:02d}-{topic_id}.png` filename had by accident,
    restored deliberately now that there is a deletion path to do it
    properly. Without it the tuning loop leaves three renders behind one
    topic after three passes, and the meme count reads 3 where the screen
    shows the latest.

    `manual` is exempt because a person made it. The model's output is
    reproducible by running again; a hand-written caption is not.
    """
    doomed = [
        record
        for record in store.renders_for_topic(run_id, topic_id)
        if record.origin.provenance == "auto"
    ]
    for record in doomed:
        delete_render(store, output_dir, record)
    if doomed:
        log.debug(
            "Cleared %d previous auto render(s) for %s/%s",
            len(doomed),
            run_id,
            topic_id,
        )
    return len(doomed)
