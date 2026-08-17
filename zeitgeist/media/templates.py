"""Meme template manifests: loading and validation.

At twenty-four hand-measured manifests, a mis-measured box will not be caught
by eye. The validator is the gate.
"""

import json
from pathlib import Path

from PIL import Image
from pydantic import BaseModel, ValidationError


class TemplateError(Exception):
    """Raised when the template library cannot be loaded at all."""


class Slot(BaseModel):
    """One text box. `box` is [left, top, right, bottom] in pixels."""

    name: str
    box: tuple[int, int, int, int]
    max_chars: int


class TemplateManifest(BaseModel):
    """A meme template and the rhetorical shape it expresses."""

    id: str
    image: str
    shape: str
    slots: list[Slot]


def load_templates(directory: Path) -> dict[str, TemplateManifest]:
    directory = Path(directory)
    if not directory.is_dir():
        raise TemplateError(f"Template directory not found: {directory}")

    templates: dict[str, TemplateManifest] = {}
    for path in sorted(directory.glob("*.json")):
        try:
            manifest = TemplateManifest.model_validate_json(
                path.read_text(encoding="utf-8")
            )
        except (ValidationError, json.JSONDecodeError) as exc:
            raise TemplateError(f"Could not parse {path.name}: {exc}") from exc
        templates[manifest.id] = manifest

    if not templates:
        raise TemplateError(f"No template manifests found in {directory}")
    return templates


def validate_templates(directory: Path) -> list[str]:
    """Return every problem found, newest-engineer-readable. Empty means good."""
    directory = Path(directory)
    if not directory.is_dir():
        return [f"Template directory not found: {directory}"]

    problems: list[str] = []
    for path in sorted(directory.glob("*.json")):
        try:
            manifest = TemplateManifest.model_validate_json(
                path.read_text(encoding="utf-8")
            )
        except (ValidationError, json.JSONDecodeError) as exc:
            problems.append(f"{path.name}: could not parse manifest ({exc})")
            continue

        if manifest.id != path.stem:
            problems.append(f"{path.name}: id {manifest.id!r} does not match filename")

        image_path = directory / manifest.image
        if not image_path.is_file():
            problems.append(f"{path.name}: image {manifest.image!r} not found")
            continue

        with Image.open(image_path) as image:
            width, height = image.size

        seen: set[str] = set()
        for slot in manifest.slots:
            if slot.name in seen:
                problems.append(f"{path.name}: duplicate slot name {slot.name!r}")
            seen.add(slot.name)

            left, top, right, bottom = slot.box
            if right <= left or bottom <= top:
                problems.append(f"{path.name}: slot {slot.name!r} box is inverted")
            elif not (0 <= left < right <= width and 0 <= top < bottom <= height):
                problems.append(
                    f"{path.name}: slot {slot.name!r} box falls outside image "
                    f"bounds ({width}x{height})"
                )

            if slot.max_chars <= 0:
                problems.append(
                    f"{path.name}: slot {slot.name!r} has non-positive max_chars"
                )

    return problems
