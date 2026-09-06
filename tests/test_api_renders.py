from PIL import Image

from tests.api_factory import SeededRun, seeded_client
from tests.run_factory import make_render_record
from zeitgeist.records import AutoOrigin, ManualOrigin


def _write_png(tmp_path, run_id: str, render_id: str, suffix: str = "") -> None:
    directory = tmp_path / "output" / run_id / "renders"
    directory.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (40, 20), "white").save(directory / f"{render_id}{suffix}.png")


def test_a_render_carries_the_brief_that_produced_it(tmp_path):
    """The full-size view shows the slot text and the reasoning, so the
    record has to be addressable rather than only embedded in topic
    detail."""
    client = seeded_client(
        tmp_path,
        runs=[
            SeededRun(
                renders=[
                    make_render_record(
                        "rnd1",
                        caption_slots={"rejected": "a", "preferred": "b"},
                        origin=AutoOrigin(rationale="it fits"),
                    )
                ]
            )
        ],
    )

    body = client.get("/api/renders/rnd1").json()

    assert body["caption_slots"] == {"rejected": "a", "preferred": "b"}
    assert body["origin"]["provenance"] == "auto"
    assert body["origin"]["rationale"] == "it fits"


def test_a_hand_written_render_carries_no_rationale(tmp_path):
    """The union makes it unrepresentable rather than empty, and that has
    to survive serialisation."""
    client = seeded_client(
        tmp_path,
        runs=[SeededRun(renders=[make_render_record("rnd2", origin=ManualOrigin())])],
    )

    body = client.get("/api/renders/rnd2").json()

    assert body["origin"] == {"provenance": "manual"}


def test_an_unknown_render_is_a_404(tmp_path):
    client = seeded_client(tmp_path)

    assert client.get("/api/renders/nope").status_code == 404


def test_the_full_image_is_served(tmp_path):
    client = seeded_client(
        tmp_path, runs=[SeededRun(renders=[make_render_record("rnd1")])]
    )
    _write_png(tmp_path, "20260901T120000Z", "rnd1")

    response = client.get("/api/renders/rnd1/image")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"


def test_the_requested_size_maps_to_the_matching_file(tmp_path):
    """The Runs list draws these at 34px, so serving the full PNG there
    would ship 800KB per tile. Asserting the two merely differ would pass a
    swapped suffix mapping, which is the mistake actually available here."""
    client = seeded_client(
        tmp_path, runs=[SeededRun(renders=[make_render_record("rnd1")])]
    )
    _write_png(tmp_path, "20260901T120000Z", "rnd1")
    directory = tmp_path / "output" / "20260901T120000Z" / "renders"
    Image.new("RGB", (96, 48), "black").save(directory / "rnd1.thumb.png")

    full = client.get("/api/renders/rnd1/image", params={"size": "full"})
    thumb = client.get("/api/renders/rnd1/image", params={"size": "thumb"})

    assert full.content == (directory / "rnd1.png").read_bytes()
    assert thumb.content == (directory / "rnd1.thumb.png").read_bytes()


def test_a_render_whose_file_is_gone_is_a_404(tmp_path):
    """The database is authoritative for whether a render exists. A PNG
    deleted underneath the row is a 404 with a reason, not a 500."""
    client = seeded_client(
        tmp_path, runs=[SeededRun(renders=[make_render_record("rnd1")])]
    )

    response = client.get("/api/renders/rnd1/image")

    assert response.status_code == 404


def test_an_unknown_size_is_rejected(tmp_path):
    """Not a test of FastAPI's validation, despite appearances. If `size`
    were typed `str` rather than the literal union, an unknown value would
    reach `_image_path`, fall down its `else` branch, and silently serve the
    thumbnail for any query string anyone typed."""
    client = seeded_client(
        tmp_path, runs=[SeededRun(renders=[make_render_record("rnd1")])]
    )

    assert (
        client.get("/api/renders/rnd1/image", params={"size": "enormous"}).status_code
        == 422
    )


def test_deleting_a_render_removes_the_row(tmp_path):
    client = seeded_client(
        tmp_path, runs=[SeededRun(renders=[make_render_record("rnd1")])]
    )

    response = client.delete("/api/renders/rnd1")

    assert response.status_code == 204
    assert client.get("/api/renders/rnd1").status_code == 404


def test_deleting_a_render_removes_both_files(tmp_path):
    """Row and files go together. An orphaned PNG is invisible; an
    orphaned row draws as a broken tile forever."""
    client = seeded_client(
        tmp_path, runs=[SeededRun(renders=[make_render_record("rnd1")])]
    )
    _write_png(tmp_path, "20260901T120000Z", "rnd1")
    _write_png(tmp_path, "20260901T120000Z", "rnd1", suffix=".thumb")

    client.delete("/api/renders/rnd1")

    directory = tmp_path / "output" / "20260901T120000Z" / "renders"
    assert not (directory / "rnd1.png").exists()
    assert not (directory / "rnd1.thumb.png").exists()


def test_deleting_a_render_whose_png_is_already_gone_still_succeeds(tmp_path):
    """The row is what makes a render exist, so a missing file cannot turn
    a delete into a 500."""
    client = seeded_client(
        tmp_path, runs=[SeededRun(renders=[make_render_record("rnd1")])]
    )

    assert client.delete("/api/renders/rnd1").status_code == 204


def test_deleting_an_unknown_render_is_a_404(tmp_path):
    client = seeded_client(tmp_path, runs=[SeededRun()])

    assert client.delete("/api/renders/nope").status_code == 404


def test_a_deleted_render_leaves_the_topics_others_alone(tmp_path):
    client = seeded_client(
        tmp_path,
        runs=[
            SeededRun(renders=[make_render_record("keep"), make_render_record("drop")])
        ],
    )

    client.delete("/api/renders/drop")

    detail = client.get("/api/runs/20260901T120000Z/topics/airport-cat").json()
    assert [r["id"] for r in detail["renders"]] == ["keep"]


def test_deleting_a_render_lowers_the_topics_meme_count(tmp_path):
    """The count is COUNT(*) over renders at query time, which is the
    whole reason it is not a column somebody has to keep correct here."""
    client = seeded_client(
        tmp_path,
        runs=[SeededRun(renders=[make_render_record("a"), make_render_record("b")])],
    )

    client.delete("/api/renders/a")

    rows = client.get("/api/runs/20260901T120000Z/topics").json()
    assert rows[0]["render_count"] == 1
