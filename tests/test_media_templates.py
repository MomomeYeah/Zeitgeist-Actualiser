import json

import pytest
from PIL import Image

from zeitgeist.media.templates import (
    TemplateError,
    load_templates,
    validate_templates,
)


def _write_template(directory, tid, box=(10, 10, 90, 90), size=(100, 100), image=None):
    directory.mkdir(parents=True, exist_ok=True)
    image_name = image if image is not None else f"{tid}.png"
    if image is None:
        Image.new("RGB", size, "white").save(directory / image_name)
    manifest = {
        "id": tid,
        "image": image_name,
        "shape": "a shape",
        "slots": [{"name": "top", "box": list(box), "max_chars": 40}],
    }
    (directory / f"{tid}.json").write_text(json.dumps(manifest), encoding="utf-8")


def test_loads_manifests_keyed_by_id(tmp_path):
    _write_template(tmp_path, "drake")
    templates = load_templates(tmp_path)
    assert templates["drake"].shape == "a shape"
    assert templates["drake"].slots[0].name == "top"


def test_missing_directory_raises(tmp_path):
    with pytest.raises(TemplateError):
        load_templates(tmp_path / "absent")


def test_directory_with_no_manifests_raises(tmp_path):
    tmp_path.mkdir(exist_ok=True)
    with pytest.raises(TemplateError):
        load_templates(tmp_path)


def test_manifest_id_must_match_filename(tmp_path):
    _write_template(tmp_path, "drake")
    (tmp_path / "drake.json").write_text(
        json.dumps(
            {
                "id": "mismatch",
                "image": "drake.png",
                "shape": "s",
                "slots": [{"name": "t", "box": [0, 0, 10, 10], "max_chars": 10}],
            }
        ),
        encoding="utf-8",
    )
    assert any("filename" in problem for problem in validate_templates(tmp_path))


def test_validator_passes_a_good_directory(tmp_path):
    _write_template(tmp_path, "drake")
    assert validate_templates(tmp_path) == []


def test_validator_reports_missing_image(tmp_path):
    _write_template(tmp_path, "drake")
    (tmp_path / "drake.png").unlink()
    assert any("image" in problem for problem in validate_templates(tmp_path))


def test_validator_reports_box_outside_image_bounds(tmp_path):
    _write_template(tmp_path, "drake", box=(10, 10, 500, 500), size=(100, 100))
    assert any("bounds" in problem for problem in validate_templates(tmp_path))


def test_validator_reports_inverted_box(tmp_path):
    _write_template(tmp_path, "drake", box=(90, 90, 10, 10))
    assert any("inverted" in problem for problem in validate_templates(tmp_path))


def test_validator_reports_duplicate_slot_names(tmp_path):
    _write_template(tmp_path, "drake")
    manifest = json.loads((tmp_path / "drake.json").read_text(encoding="utf-8"))
    manifest["slots"].append({"name": "top", "box": [0, 0, 10, 10], "max_chars": 10})
    (tmp_path / "drake.json").write_text(json.dumps(manifest), encoding="utf-8")
    assert any("duplicate" in problem for problem in validate_templates(tmp_path))


def test_validator_reports_non_positive_max_chars(tmp_path):
    """A zero max_chars is a silent trap: the manifest loads, and the model
    is told it may write no characters at all.
    """
    _write_template(tmp_path, "drake")
    manifest = json.loads((tmp_path / "drake.json").read_text(encoding="utf-8"))
    manifest["slots"][0]["max_chars"] = 0
    (tmp_path / "drake.json").write_text(json.dumps(manifest), encoding="utf-8")
    assert any("max_chars" in problem for problem in validate_templates(tmp_path))


def test_validator_reports_unparseable_manifest(tmp_path):
    tmp_path.mkdir(exist_ok=True)
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")
    assert any("parse" in problem for problem in validate_templates(tmp_path))


def test_shipped_templates_are_all_valid():
    from zeitgeist.config import PACKAGE_ROOT

    assert validate_templates(PACKAGE_ROOT / "media" / "templates") == []


def test_shipped_templates_number_twenty_four():
    from zeitgeist.config import PACKAGE_ROOT

    assert len(load_templates(PACKAGE_ROOT / "media" / "templates")) == 24
