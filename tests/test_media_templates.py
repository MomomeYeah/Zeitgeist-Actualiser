import pytest

from tests.template_factory import make_manifest, make_slot, write_library
from zeitgeist.media.templates import (
    TemplateError,
    load_templates,
    select_templates,
    validate_templates,
)


def test_loads_manifests_keyed_by_id(tmp_path):
    manifest = make_manifest("drake")
    write_library(tmp_path, manifest)
    assert load_templates(tmp_path) == {"drake": manifest}


def test_missing_directory_raises(tmp_path):
    with pytest.raises(TemplateError):
        load_templates(tmp_path / "absent")


def test_directory_with_no_manifests_raises(tmp_path):
    tmp_path.mkdir(exist_ok=True)
    with pytest.raises(TemplateError):
        load_templates(tmp_path)


def test_manifest_id_must_match_filename(tmp_path):
    write_library(tmp_path, make_manifest("drake"))
    (tmp_path / "drake.json").write_text(
        make_manifest("mismatch", image="drake.png").model_dump_json(),
        encoding="utf-8",
    )
    assert any("filename" in problem for problem in validate_templates(tmp_path))


def test_validator_passes_a_good_directory(tmp_path):
    write_library(tmp_path, make_manifest("drake"))
    assert validate_templates(tmp_path) == []


def test_validator_reports_missing_image(tmp_path):
    write_library(tmp_path, make_manifest("drake"))
    (tmp_path / "drake.png").unlink()
    assert any("image" in problem for problem in validate_templates(tmp_path))


def test_validator_reports_box_outside_image_bounds(tmp_path):
    write_library(
        tmp_path,
        make_manifest("drake", slots=[make_slot(box=(10, 10, 500, 500))]),
        size=(100, 100),
    )
    assert any("bounds" in problem for problem in validate_templates(tmp_path))


def test_validator_reports_inverted_box(tmp_path):
    write_library(
        tmp_path, make_manifest("drake", slots=[make_slot(box=(90, 90, 10, 10))])
    )
    assert any("inverted" in problem for problem in validate_templates(tmp_path))


def test_validator_reports_duplicate_slot_names(tmp_path):
    write_library(
        tmp_path, make_manifest("drake", slots=[make_slot("top"), make_slot("top")])
    )
    assert any("duplicate" in problem for problem in validate_templates(tmp_path))


def test_validator_reports_non_positive_max_chars(tmp_path):
    """A zero max_chars is a silent trap: the manifest loads, and the model
    is told it may write no characters at all.
    """
    write_library(tmp_path, make_manifest("drake", slots=[make_slot(max_chars=0)]))
    assert any("max_chars" in problem for problem in validate_templates(tmp_path))


def test_validator_reports_unparseable_manifest(tmp_path):
    """The one manifest written by hand rather than dumped from the model:
    text the model could never produce is the whole subject of the test.
    """
    tmp_path.mkdir(exist_ok=True)
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")
    assert any("parse" in problem for problem in validate_templates(tmp_path))


def test_shipped_templates_are_all_valid():
    from zeitgeist.config import PACKAGE_ROOT

    assert validate_templates(PACKAGE_ROOT / "media" / "templates") == []


def test_select_narrows_the_library_to_the_named_ids(tmp_path):
    write_library(
        tmp_path,
        *(make_manifest(tid) for tid in ("drake", "two_buttons", "this_is_fine")),
    )
    selected = select_templates(load_templates(tmp_path), ["drake", "this_is_fine"])
    assert sorted(selected) == ["drake", "this_is_fine"]


def test_select_keeps_library_order_regardless_of_argument_order(tmp_path):
    """`_build_prompt` iterates the dict to list the library, so ordering by
    the flag would make the prompt text depend on how the ids were typed.
    """
    write_library(tmp_path, *(make_manifest(tid) for tid in ("aaa", "bbb", "ccc")))
    selected = select_templates(load_templates(tmp_path), ["ccc", "aaa"])
    assert list(selected) == ["aaa", "ccc"]


def test_select_rejects_an_unknown_id_naming_it_and_the_alternatives(tmp_path):
    """Silently dropping a typo'd id would leave a narrowed run looking like
    a successful one, which is the whole failure this guards against.
    """
    write_library(tmp_path, *(make_manifest(tid) for tid in ("drake", "two_buttons")))
    with pytest.raises(TemplateError) as error:
        select_templates(load_templates(tmp_path), ["drake", "two_button"])
    message = str(error.value)
    assert "two_button" in message
    assert "two_buttons" in message


def test_select_rejects_an_empty_id_list(tmp_path):
    write_library(tmp_path, make_manifest("drake"))
    with pytest.raises(TemplateError):
        select_templates(load_templates(tmp_path), [])
