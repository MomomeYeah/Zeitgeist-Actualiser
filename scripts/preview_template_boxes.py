"""Renders every template's text boxes onto a copy of its image.

Each slot is filled with filler text exactly `max_chars` long and drawn
through the production renderer, then the box outlines and slot labels are
overlaid on top. Run it while re-measuring boxes or re-wording shapes:

    uv run python scripts/preview_template_boxes.py

Previews land in output/template-boxes/, which is gitignored. The list of
templates whose character budget will not fit is the real output; the PNGs
are how you work out why.
"""

import argparse
from itertools import cycle
from pathlib import Path
from typing import cast

from PIL import Image, ImageDraw, ImageFont

from zeitgeist.config import PACKAGE_ROOT
from zeitgeist.media.render import RenderError, render_meme
from zeitgeist.media.templates import TemplateError, TemplateManifest, load_templates
from zeitgeist.models import MediaBrief

# Bright enough that black label text stays readable on every one of them.
PALETTE = ("#FF00FF", "#00FFFF", "#FFFF00", "#00FF7F", "#FF7F00", "#FF4040")

FILLER_WORDS = (
    "the",
    "internet",
    "has",
    "decided",
    "that",
    "this",
    "is",
    "the",
    "funniest",
    "thing",
    "anyone",
    "posted",
    "today",
    "and",
    "nobody",
    "can",
    "explain",
    "why",
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Draw each template's text boxes onto a copy of its image."
    )
    parser.add_argument("--dir", default=None, help="Template directory to preview")
    parser.add_argument(
        "--out", default="output/template-boxes", help="Where previews are written"
    )
    parser.add_argument(
        "--font",
        default=None,
        help="TTF to preview with, e.g. C:/Windows/Fonts/impact.ttf. Whether a "
        "budget fits depends entirely on this; the default is the font Pillow "
        "ships, matching an unset FONT_PATH.",
    )
    args = parser.parse_args()

    templates_dir = Path(args.dir) if args.dir else PACKAGE_ROOT / "media" / "templates"
    out_dir = Path(args.out)
    font_path = Path(args.font) if args.font else None

    try:
        templates = load_templates(templates_dir)
    except TemplateError as exc:
        print(f"Could not load templates: {exc}")
        return 1

    out_dir.mkdir(parents=True, exist_ok=True)

    written = 0
    problems: list[str] = []
    for manifest in templates.values():
        drawn, problem = _preview(
            manifest, templates_dir, out_dir / f"{manifest.id}.png", font_path
        )
        written += drawn
        if problem is not None:
            problems.append(problem)

    print(f"Wrote {written} of {len(templates)} previews to {out_dir}")
    if problems:
        print(f"\n{len(problems)} template(s) need attention:")
        for problem in problems:
            print(f"  {problem}")
    return 0


def _preview(
    manifest: TemplateManifest,
    templates_dir: Path,
    out_path: Path,
    font_path: Path | None,
) -> tuple[bool, str | None]:
    """Write one annotated preview.

    Returns whether a PNG was written, and a problem to report or None. A
    caption that will not fit is a finding rather than a failure: the boxes
    still get drawn, over the bare template, so the measurement can be seen.
    """
    brief = MediaBrief(
        topic_id="preview",
        template_id=manifest.id,
        caption_slots={slot.name: _filler(slot.max_chars) for slot in manifest.slots},
        rationale="box preview",
    )

    problem: str | None = None
    try:
        render_meme(brief, manifest, templates_dir, out_path, font_path)
    except RenderError as exc:
        problem = f"{manifest.id}: {exc}"
        image_path = templates_dir / manifest.image
        if not image_path.is_file():
            return False, problem
        with Image.open(image_path) as source:
            source.convert("RGB").save(out_path, format="PNG")

    with Image.open(out_path) as rendered:
        canvas = rendered.convert("RGB")
    _draw_boxes(canvas, manifest)
    canvas.save(out_path, format="PNG")
    return True, problem


def _draw_boxes(canvas: Image.Image, manifest: TemplateManifest) -> None:
    """Overlay each slot's box and label, drawn over any caption beneath."""
    draw = ImageDraw.Draw(canvas)
    scale = max(canvas.width, canvas.height)
    thickness = max(2, scale // 300)
    # load_default is typed FreeTypeFont | ImageFont because it returns the
    # bitmap face when size is omitted; passing size selects the scalable one.
    font = cast(
        ImageFont.FreeTypeFont, ImageFont.load_default(size=max(11, scale // 55))
    )

    for index, slot in enumerate(manifest.slots):
        colour = PALETTE[index % len(PALETTE)]
        left, top, right, bottom = slot.box
        draw.rectangle((left, top, right, bottom), outline=colour, width=thickness)
        _draw_label(
            draw,
            f"{slot.name} ({slot.max_chars} chars)",
            slot.box,
            colour,
            font,
            (canvas.width, canvas.height),
            thickness,
        )


def _draw_label(
    draw: ImageDraw.ImageDraw,
    label: str,
    box: tuple[int, int, int, int],
    colour: str,
    font: ImageFont.FreeTypeFont,
    canvas_size: tuple[int, int],
    padding: int,
) -> None:
    """Tag a box, keeping the tag clear of the caption inside it where possible.

    Above the box is preferred, below it is the fallback, and only a box with
    room for neither gets its tag laid over its own first line of text.
    """
    text_left, text_top, text_right, text_bottom = draw.textbbox(
        (0, 0), label, font=font
    )
    width = text_right - text_left + padding * 2
    height = text_bottom - text_top + padding * 2

    box_left, box_top, _, box_bottom = box
    canvas_width, canvas_height = canvas_size

    if box_top - height >= 0:
        top = box_top - height
    elif box_bottom + height <= canvas_height:
        top = box_bottom
    else:
        top = box_top
    left = max(0, min(box_left, canvas_width - width))

    draw.rectangle((left, top, left + width, top + height), fill=colour)
    draw.text(
        (left + padding - text_left, top + padding - text_top),
        label,
        font=font,
        fill="black",
    )


def _filler(length: int) -> str:
    """Filler text exactly `length` characters long.

    Exactness is the point. The preview answers whether a slot's max_chars
    budget fits its box, so filler that stopped a few characters short of the
    budget would answer a slightly easier question than the one asked.
    """
    if length <= 0:
        return ""

    words = cycle(FILLER_WORDS)
    text = next(words)[:length]
    while len(text) < length:
        text = f"{text} {next(words)}"[:length]

    # Truncating onto a separator leaves a trailing space, and the renderer
    # strips those — one character under the budget being tested.
    return text if not text.endswith(" ") else f"{text[:-1]}x"


if __name__ == "__main__":
    raise SystemExit(main())
