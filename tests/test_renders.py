from PIL import Image

from tests.run_factory import make_render_record
from zeitgeist.records import ManualOrigin
from zeitgeist.renders import clear_auto_renders, delete_render, render_paths
from zeitgeist.store import Store


def _store(tmp_path) -> Store:
    store = Store(tmp_path / "z.db")
    store.init_schema()
    return store


def _write_files(output_dir, run_id: str, render_id: str) -> None:
    paths = render_paths(output_dir, run_id, render_id)
    paths.full.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (40, 20), "white").save(paths.full)
    Image.new("RGB", (8, 4), "white").save(paths.thumb)


def test_render_paths_puts_both_files_under_the_runs_render_directory(tmp_path):
    paths = render_paths(tmp_path, "run-1", "abc")

    assert paths.full == tmp_path / "run-1" / "renders" / "abc.png"
    assert paths.thumb == tmp_path / "run-1" / "renders" / "abc.thumb.png"


def test_delete_render_removes_the_row_and_both_files(tmp_path):
    store = _store(tmp_path)
    record = make_render_record("rnd1", run_id="run-1")
    store.add_render(record)
    _write_files(tmp_path / "output", "run-1", "rnd1")

    assert delete_render(store, tmp_path / "output", record) is True

    paths = render_paths(tmp_path / "output", "run-1", "rnd1")
    assert store.get_render("rnd1") is None
    assert not paths.full.exists()
    assert not paths.thumb.exists()


def test_delete_render_succeeds_when_the_png_is_already_gone(tmp_path):
    """The row is what makes a render exist. A PNG deleted out from under
    it must not turn a delete into a crash."""
    store = _store(tmp_path)
    record = make_render_record("rnd1", run_id="run-1")
    store.add_render(record)

    assert delete_render(store, tmp_path / "output", record) is True
    assert store.get_render("rnd1") is None


def test_delete_render_reports_a_row_that_had_already_gone(tmp_path):
    """Two tabs racing the same delete: the second must be able to tell
    that it removed nothing."""
    store = _store(tmp_path)
    record = make_render_record("rnd1", run_id="run-1")

    assert delete_render(store, tmp_path / "output", record) is False


def test_clear_auto_renders_removes_the_topics_model_written_renders(tmp_path):
    store = _store(tmp_path)
    for rid in ("a", "b"):
        store.add_render(make_render_record(rid, run_id="run-1", topic_id="cat"))
        _write_files(tmp_path / "output", "run-1", rid)

    cleared = clear_auto_renders(store, tmp_path / "output", "run-1", "cat")

    assert cleared == 2
    assert store.renders_for_topic("run-1", "cat") == []
    assert not render_paths(tmp_path / "output", "run-1", "a").full.exists()
    assert not render_paths(tmp_path / "output", "run-1", "b").thumb.exists()


def test_clear_auto_renders_never_touches_a_hand_written_render(tmp_path):
    """The model's output is reproducible by running again; a caption
    somebody typed is not. That asymmetry is the whole reason the origin
    union has two members."""
    store = _store(tmp_path)
    store.add_render(make_render_record("auto", run_id="run-1", topic_id="cat"))
    store.add_render(
        make_render_record(
            "hand", run_id="run-1", topic_id="cat", origin=ManualOrigin()
        )
    )
    _write_files(tmp_path / "output", "run-1", "hand")

    cleared = clear_auto_renders(store, tmp_path / "output", "run-1", "cat")

    assert cleared == 1
    assert [r.id for r in store.renders_for_topic("run-1", "cat")] == ["hand"]
    assert render_paths(tmp_path / "output", "run-1", "hand").full.exists()


def test_clear_auto_renders_leaves_another_topic_alone(tmp_path):
    store = _store(tmp_path)
    store.add_render(make_render_record("cat1", run_id="run-1", topic_id="cat"))
    store.add_render(make_render_record("dog1", run_id="run-1", topic_id="dog"))

    clear_auto_renders(store, tmp_path / "output", "run-1", "cat")

    assert [r.id for r in store.renders_for_topic("run-1", "dog")] == ["dog1"]


def test_clear_auto_renders_leaves_the_same_topic_in_another_run_alone(tmp_path):
    """Renders belong to the run that made them. Re-running one run must
    not reach into another run's output."""
    store = _store(tmp_path)
    store.add_render(make_render_record("old", run_id="run-0", topic_id="cat"))
    store.add_render(make_render_record("new", run_id="run-1", topic_id="cat"))

    clear_auto_renders(store, tmp_path / "output", "run-1", "cat")

    assert [r.id for r in store.renders_for_topic("run-0", "cat")] == ["old"]
