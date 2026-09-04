import pytest
from PIL import Image, ImageChops, ImageStat

from tests.template_factory import make_manifest, make_slot, write_library
from zeitgeist.config import PACKAGE_ROOT
from zeitgeist.media.render import (
    THUMBNAIL_PX,
    RenderError,
    render_meme,
    write_thumbnail,
)
from zeitgeist.models import MediaBrief

FONT = None  # Pillow's bundled scalable font; see resolve_font


@pytest.fixture
def template_dir(tmp_path):
    """Kept identical to MANIFEST in scripts/make_golden.py, which renders
    the committed golden. Drift in the boxes or the canvas size shows up as
    a test_matches_the_golden_image failure.
    """
    manifest = make_manifest(
        "test",
        shape="a shape",
        slots=[
            make_slot("top", box=(10, 10, 390, 190), max_chars=60),
            make_slot("bottom", box=(10, 210, 390, 390), max_chars=60),
        ],
    )
    write_library(tmp_path, manifest, size=(400, 400))
    return tmp_path, manifest


def _brief(**slots) -> MediaBrief:
    return MediaBrief(
        topic_id="t", template_id="test", caption_slots=slots, rationale="because"
    )


def test_writes_a_png_of_the_template_size(tmp_path, template_dir):
    directory, manifest = template_dir
    out = tmp_path / "out.png"
    result = render_meme(
        _brief(top="Hello", bottom="World"), manifest, directory, out, FONT
    )
    assert result == out
    with Image.open(out) as image:
        assert image.size == (400, 400)


def test_drawing_changes_the_image(tmp_path, template_dir):
    directory, manifest = template_dir
    out = tmp_path / "out.png"
    render_meme(_brief(top="Hello", bottom="World"), manifest, directory, out, FONT)
    with Image.open(out) as rendered, Image.open(directory / "test.png") as blank:
        difference = ImageChops.difference(rendered.convert("RGB"), blank)
        assert ImageStat.Stat(difference).sum[0] > 0


def test_long_text_stays_inside_its_box(tmp_path, template_dir):
    directory, manifest = template_dir
    out = tmp_path / "out.png"
    render_meme(
        _brief(top="word " * 80, bottom="short"), manifest, directory, out, FONT
    )
    with Image.open(out) as rendered:
        below = rendered.convert("RGB").crop((0, 195, 400, 205))
        assert ImageStat.Stat(below).stddev[0] == pytest.approx(0.0, abs=1.0)


def test_caption_that_cannot_fit_even_at_minimum_font_size_raises(
    tmp_path, template_dir
):
    """An absurdly long caption (well past max_chars) must fail loudly
    rather than draw outside its box. Previously a 2000-character caption on
    this 380x180 box would render ~34 lines spanning y = -124..324 — off
    the box and off the top of the image — with no error and no log line.
    """
    directory, manifest = template_dir
    out = tmp_path / "out.png"
    with pytest.raises(RenderError, match="top"):
        render_meme(
            _brief(top="word " * 400, bottom="short"), manifest, directory, out, FONT
        )


def test_missing_slot_raises(tmp_path, template_dir):
    directory, manifest = template_dir
    with pytest.raises(RenderError, match="bottom"):
        render_meme(
            _brief(top="only one"), manifest, directory, tmp_path / "o.png", FONT
        )


def test_unknown_slot_raises(tmp_path, template_dir):
    directory, manifest = template_dir
    with pytest.raises(RenderError, match="middle"):
        render_meme(
            _brief(top="a", bottom="b", middle="c"),
            manifest,
            directory,
            tmp_path / "o.png",
            FONT,
        )


def test_missing_image_raises(tmp_path, template_dir):
    directory, manifest = template_dir
    (directory / "test.png").unlink()
    with pytest.raises(RenderError, match="image"):
        render_meme(
            _brief(top="a", bottom="b"), manifest, directory, tmp_path / "o.png", FONT
        )


def test_blank_caption_leaves_that_area_untouched(tmp_path, template_dir):
    """Exercises the early return. Without it, a whitespace caption draws a
    stroke-outlined blank onto the template.
    """
    directory, manifest = template_dir
    out = tmp_path / "out.png"
    render_meme(_brief(top="   ", bottom="\n"), manifest, directory, out, FONT)
    with Image.open(out) as rendered, Image.open(directory / "test.png") as blank:
        difference = ImageChops.difference(rendered.convert("RGB"), blank)
        assert ImageStat.Stat(difference).sum[0] == 0


def test_output_is_reproducible(tmp_path, template_dir):
    directory, manifest = template_dir
    brief = _brief(top="Same input", bottom="Same output")
    first, second = tmp_path / "1.png", tmp_path / "2.png"
    render_meme(brief, manifest, directory, first, FONT)
    render_meme(brief, manifest, directory, second, FONT)
    assert first.read_bytes() == second.read_bytes()


def test_matches_the_golden_image(tmp_path, template_dir):
    """Regenerate with: uv run python scripts/make_golden.py"""
    directory, manifest = template_dir
    golden = PACKAGE_ROOT.parent / "tests" / "fixtures" / "golden" / "test_meme.png"
    out = tmp_path / "out.png"
    render_meme(
        _brief(top="Trending topic", bottom="Obvious punchline"),
        manifest,
        directory,
        out,
        FONT,
    )
    with Image.open(out) as rendered, Image.open(golden) as expected:
        assert rendered.size == expected.size
        difference = ImageChops.difference(
            rendered.convert("RGB"), expected.convert("RGB")
        )
        assert ImageStat.Stat(difference).mean[0] < 2.0


def test_a_thumbnail_fits_inside_the_box_and_keeps_its_aspect(tmp_path):
    source = tmp_path / "meme.png"
    Image.new("RGB", (1180, 590), "white").save(source)

    out = write_thumbnail(source, tmp_path / "meme.thumb.png")

    with Image.open(out) as image:
        # Derived from the constant rather than pinned at 96, so raising
        # THUMBNAIL_PX stays a decision rather than a test failure. What is
        # asserted is the 2:1 source keeping its shape.
        assert image.size == (THUMBNAIL_PX, THUMBNAIL_PX // 2)


def test_a_thumbnail_of_a_tall_image_is_bounded_by_its_height(tmp_path):
    source = tmp_path / "tall.png"
    Image.new("RGB", (300, 1200), "white").save(source)

    out = write_thumbnail(source, tmp_path / "tall.thumb.png")

    with Image.open(out) as image:
        assert image.size == (THUMBNAIL_PX // 4, THUMBNAIL_PX)


def test_a_thumbnail_is_never_larger_than_its_source(tmp_path):
    """A 34px tile has nothing to gain from an upscaled 40px meme."""
    source = tmp_path / "small.png"
    Image.new("RGB", (40, 20), "white").save(source)

    out = write_thumbnail(source, tmp_path / "small.thumb.png")

    with Image.open(out) as image:
        assert image.size == (40, 20)
