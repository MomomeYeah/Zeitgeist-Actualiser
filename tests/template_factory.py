"""Builders for template manifests and the on-disk libraries tests load.

Every manifest the suite needs is built through the real models here, so a
change to `Slot` or `TemplateManifest` surfaces as a type error at one site
rather than as a `ValidationError` raised from inside dozens of unrelated
tests. Passing slots as plain dicts would defeat that: pydantic coerces them
at runtime and ty never checks them against `Slot`.

Defaults exist so a test states only the values it actually asserts on. A
test that cares about box geometry or a character budget passes it; the rest
say nothing and get something valid.
"""

from collections.abc import Sequence
from pathlib import Path

from PIL import Image

from zeitgeist.media.templates import Slot, TemplateManifest

# Fits inside DEFAULT_SIZE with room to spare, so the validator accepts a
# default manifest and out-of-bounds cases have to ask for it explicitly.
DEFAULT_BOX = (10, 10, 190, 90)
DEFAULT_SIZE = (200, 200)


def make_slot(
    name: str = "top",
    *,
    meaning: str = "top",
    box: tuple[int, int, int, int] = DEFAULT_BOX,
    max_chars: int = 40,
) -> Slot:
    return Slot(name=name, meaning=meaning, box=box, max_chars=max_chars)


def make_manifest(
    tid: str = "shape_alpha",
    *,
    image: str | None = None,
    shape: str | None = None,
    slots: Sequence[Slot] | None = None,
) -> TemplateManifest:
    """A valid manifest for `tid`, overridable field by field.

    `image` defaults to `{tid}.png`, which is what `write_library` paints.
    Override it only to describe a manifest whose image is somewhere else,
    as the id-mismatch case does.
    """
    return TemplateManifest(
        id=tid,
        image=image if image is not None else f"{tid}.png",
        shape=shape if shape is not None else f"the {tid} shape",
        slots=list(slots) if slots is not None else [make_slot()],
    )


def write_library(
    directory: Path,
    *manifests: TemplateManifest,
    size: tuple[int, int] = DEFAULT_SIZE,
) -> Path:
    """Write each manifest as `{id}.json` beside a blank image of `size`.

    Serialising through `model_dump_json` rather than a hand-built dict keeps
    the on-disk shape derived from the model, so renaming a field cannot
    leave a stale key behind in a fixture.
    """
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    for manifest in manifests:
        Image.new("RGB", size, "white").save(directory / manifest.image)
        (directory / f"{manifest.id}.json").write_text(
            manifest.model_dump_json(), encoding="utf-8"
        )
    return directory
