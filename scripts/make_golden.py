"""Regenerates the committed golden render. Run after intentional layout changes."""

import shutil
import tempfile
from pathlib import Path

from PIL import Image

from zeitgeist.media.render import render_meme
from zeitgeist.media.templates import TemplateManifest
from zeitgeist.models import MediaBrief

MANIFEST = TemplateManifest(
    id="test",
    image="test.png",
    shape="a shape",
    slots=[
        {"name": "top", "box": (10, 10, 390, 190), "max_chars": 60},
        {"name": "bottom", "box": (10, 210, 390, 390), "max_chars": 60},
    ],
)


def main() -> None:
    out = Path("tests/fixtures/golden/test_meme.png")
    out.parent.mkdir(parents=True, exist_ok=True)

    scratch = Path(tempfile.mkdtemp())
    try:
        Image.new("RGB", (400, 400), "white").save(scratch / "test.png")
        render_meme(
            MediaBrief(
                topic_id="t",
                template_id="test",
                caption_slots={
                    "top": "Trending topic",
                    "bottom": "Obvious punchline",
                },
                rationale="because",
            ),
            MANIFEST,
            scratch,
            out,
            None,
        )
    finally:
        shutil.rmtree(scratch, ignore_errors=True)

    print(f"wrote {out}")


if __name__ == "__main__":
    main()
