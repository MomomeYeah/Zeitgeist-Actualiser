"""Pillow compositing. Fully deterministic: no model involvement at all."""

import logging
import math
import textwrap
import unicodedata
from pathlib import Path
from typing import cast

from PIL import Image, ImageDraw, ImageFont

from zeitgeist.media.templates import Slot, TemplateManifest
from zeitgeist.models import MediaBrief

log = logging.getLogger(__name__)

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
        # load_default is typed FreeTypeFont | ImageFont because it returns
        # the bitmap ImageFont when size is omitted. Passing size selects the
        # scalable FreeType face, which is what the return type promises and
        # what draw.textlength needs.
        return cast(ImageFont.FreeTypeFont, ImageFont.load_default(size=size))
    try:
        return ImageFont.truetype(str(font_path), size)
    except OSError as exc:
        raise RenderError(f"Could not load font {font_path}: {exc}") from exc


# Stand-ins for characters a font has no glyph for. Only consulted when the
# glyph is missing: Pillow's bundled font is a subset that has curly quotes
# but no dashes, and a real .ttf may have both.
_FALLBACKS = {
    "\u00a0": " ",  # no-break space
    "\u2010": "-",  # hyphen
    "\u2011": "-",  # non-breaking hyphen
    "\u2012": "-",  # figure dash
    "\u2013": "-",  # en dash
    "\u2014": "-",  # em dash
    "\u2015": "-",  # horizontal bar
    "\u2212": "-",  # minus sign
    "\u2018": "'",
    "\u2019": "'",
    "\u201c": '"',
    "\u201d": '"',
    "\u2026": "...",
    "\u2022": "*",  # bullet
}

# A noncharacter: no font maps it, so it draws as the font's .notdef glyph.
_NOTDEF = "\uffff"


def _glyph(font: ImageFont.FreeTypeFont, char: str) -> tuple[tuple[int, int], bytes]:
    left, top, right, bottom = font.getbbox(char)
    width = max(math.ceil(right) - math.floor(left), 1)
    height = max(math.ceil(bottom) - math.floor(top), 1)
    image = Image.new("L", (width, height))
    ImageDraw.Draw(image).text((-left, -top), char, font=font, fill=255)
    return image.size, image.tobytes()


def _drawable(text: str, font: ImageFont.FreeTypeFont) -> str:
    """`text` with every character the font would draw as .notdef replaced.

    Pillow draws a missing glyph as the font's .notdef box rather than
    falling back to another font, so an em dash in a caption came out as a
    box in the middle of the meme. A missing character is swapped for its
    entry in `_FALLBACKS`, else for its accent-stripped base letter, else
    dropped — a gap reads better than a box.
    """
    notdef = _glyph(font, _NOTDEF)
    cache: dict[str, bool] = {}

    def has(char: str) -> bool:
        if char.isascii():
            return True
        if char not in cache:
            cache[char] = _glyph(font, char) != notdef
        return cache[char]

    out: list[str] = []
    dropped: list[str] = []
    for char in text:
        if has(char):
            out.append(char)
        elif char in _FALLBACKS:
            out.append(_FALLBACKS[char])
        elif (base := _strip_accents(char)) and all(map(has, base)):
            out.append(base)
        else:
            dropped.append(char)
    if dropped:
        log.warning("Dropped characters the font cannot draw: %s", " ".join(dropped))
    return "".join(out)


def _strip_accents(char: str) -> str:
    return "".join(
        part
        for part in unicodedata.normalize("NFKD", char)
        if not unicodedata.combining(part)
    )


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
    # Glyph coverage does not depend on size, so one probe serves the fit.
    text = _drawable(text, resolve_font(font_path, MAX_FONT_SIZE)).strip()
    if not text:
        return

    for size in range(MAX_FONT_SIZE, MIN_FONT_SIZE - 1, -2):
        font = resolve_font(font_path, size)
        lines = _wrap(draw, text, font, width)
        line_height = size * LINE_SPACING
        if line_height * len(lines) <= height:
            break

    log.debug("Slot %s fitted at %dpt", slot.name, size)

    block_height = line_height * len(lines)
    if block_height > height:
        # max_chars is meant to keep captions short enough to fit, but the
        # model is only ever told the budget (see _build_prompt in
        # media/brief.py) — nothing stops it exceeding it. Failing loudly
        # here matches the project's contract everywhere else: _render_all
        # catches RenderError per brief, so one over-long caption costs one
        # meme rather than silently drawing outside the box.
        raise RenderError(
            f"Caption for slot {slot.name!r} does not fit within its "
            f"{width}x{height} box even at the minimum font size "
            f"({MIN_FONT_SIZE}px); needs {len(lines)} lines of height "
            f"{line_height:.1f}px"
        )

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


# The Runs list draws renders at 34px and topic detail at 42. 96 covers both
# on a 2x display without shipping 800KB per tile.
THUMBNAIL_PX = 96


def write_thumbnail(source: Path, out_path: Path) -> Path:
    """Write a bounded-box copy of `source` beside the render.

    `Image.thumbnail` preserves aspect ratio and never upscales, which is
    what we want on both counts: a stretched meme looks broken, and a 34px
    tile gains nothing from an enlarged small source.
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as image:
        copy = image.convert("RGB")
        copy.thumbnail((THUMBNAIL_PX, THUMBNAIL_PX))
        copy.save(out_path, format="PNG")
    return out_path
