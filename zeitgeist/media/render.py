"""Pillow compositing. Fully deterministic: no model involvement at all."""

import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from zeitgeist.media.templates import Slot, TemplateManifest
from zeitgeist.models import MediaBrief

MAX_FONT_SIZE = 64
MIN_FONT_SIZE = 12
STROKE_WIDTH = 2
LINE_SPACING = 1.1


class RenderError(Exception):
    """Raised when a brief cannot be drawn onto its template."""


def resolve_font(font_path: Path | None, size: int) -> ImageFont.FreeTypeFont:
    """Load the caption font at `size`.

    `None` means the scalable font Pillow ships with, which keeps the repo
    free of a vendored binary and keeps golden renders reproducible because
    uv.lock pins the Pillow version. A supplied path overrides it — set
    FONT_PATH to a real .ttf for a different look.
    """
    if font_path is None:
        return ImageFont.load_default(size=size)
    try:
        return ImageFont.truetype(str(font_path), size)
    except OSError as exc:
        raise RenderError(f"Could not load font {font_path}: {exc}") from exc


def render_meme(
    brief: MediaBrief,
    manifest: TemplateManifest,
    templates_dir: Path,
    out_path: Path,
    font_path: Path | None = None,
) -> Path:
    slot_names = {slot.name for slot in manifest.slots}
    given = set(brief.caption_slots)

    if missing := sorted(slot_names - given):
        raise RenderError(f"Brief is missing slots: {', '.join(missing)}")
    if extra := sorted(given - slot_names):
        raise RenderError(f"Brief has unknown slots: {', '.join(extra)}")

    image_path = Path(templates_dir) / manifest.image
    if not image_path.is_file():
        raise RenderError(f"Template image not found: {image_path}")

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with Image.open(image_path) as source:
        canvas = source.convert("RGB")
        draw = ImageDraw.Draw(canvas)
        for slot in manifest.slots:
            _draw_slot(draw, slot, brief.caption_slots[slot.name], font_path)
        canvas.save(out_path, format="PNG")

    return out_path


def _draw_slot(
    draw: ImageDraw.ImageDraw, slot: Slot, text: str, font_path: Path | None
) -> None:
    left, top, right, bottom = slot.box
    width, height = right - left, bottom - top
    text = text.strip()
    if not text:
        return

    for size in range(MAX_FONT_SIZE, MIN_FONT_SIZE - 1, -2):
        font = resolve_font(font_path, size)
        lines = _wrap(draw, text, font, width)
        line_height = size * LINE_SPACING
        if line_height * len(lines) <= height:
            break

    block_height = line_height * len(lines)
    y = top + (height - block_height) / 2

    for line in lines:
        line_width = draw.textlength(line, font=font)
        draw.text(
            (left + (width - line_width) / 2, y),
            line,
            font=font,
            fill="white",
            stroke_width=STROKE_WIDTH,
            stroke_fill="black",
        )
        y += line_height


def _wrap(
    draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, width: int
) -> list[str]:
    """Wrap by measured pixel width, narrowing until every line fits."""
    for chars in range(60, 4, -2):
        lines = textwrap.wrap(text, width=chars) or [text]
        if all(draw.textlength(line, font=font) <= width for line in lines):
            return lines
    return textwrap.wrap(text, width=6) or [text]
