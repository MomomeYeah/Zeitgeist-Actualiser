import json

import pytest
from PIL import Image

from zeitgeist.media.templates import (
    TemplateError,
    load_templates,
    select_templates,
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


def test_select_narrows_the_library_to_the_named_ids(tmp_path):
    for tid in ("drake", "two_buttons", "this_is_fine"):
        _write_template(tmp_path, tid)
    selected = select_templates(load_templates(tmp_path), ["drake", "this_is_fine"])
    assert sorted(selected) == ["drake", "this_is_fine"]


def test_select_keeps_library_order_regardless_of_argument_order(tmp_path):
    """`_build_prompt` iterates the dict to list the library, so ordering by
    the flag would make the prompt text depend on how the ids were typed.
    """
    for tid in ("aaa", "bbb", "ccc"):
        _write_template(tmp_path, tid)
    selected = select_templates(load_templates(tmp_path), ["ccc", "aaa"])
    assert list(selected) == ["aaa", "ccc"]


def test_select_rejects_an_unknown_id_naming_it_and_the_alternatives(tmp_path):
    """Silently dropping a typo'd id would leave a narrowed run looking like
    a successful one, which is the whole failure this guards against.
    """
    for tid in ("drake", "two_buttons"):
        _write_template(tmp_path, tid)
    with pytest.raises(TemplateError) as error:
        select_templates(load_templates(tmp_path), ["drake", "two_button"])
    message = str(error.value)
    assert "two_button" in message
    assert "two_buttons" in message


def test_select_rejects_an_empty_id_list(tmp_path):
    _write_template(tmp_path, "drake")
    with pytest.raises(TemplateError):
        select_templates(load_templates(tmp_path), [])
