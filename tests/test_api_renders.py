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
