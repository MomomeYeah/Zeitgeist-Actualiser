import threading
from dataclasses import dataclass, field
from pathlib import Path

from fastapi.testclient import TestClient

from tests.api_factory import SeededRun, api_settings, seed_run, seeded_client
from tests.run_factory import make_render_record, make_topic
from tests.template_factory import make_manifest, make_slot, write_library
from zeitgeist.api import create_app
from zeitgeist.generation import GenerationJob
from zeitgeist.store import Store

TEMPLATE = "shape_alpha"
SLOTS = {"rejected": "queueing forever", "preferred": "the airport cat"}
RUN = "20260901T120000Z"


@dataclass
class RecordingGenerate:
    jobs: list[GenerationJob] = field(default_factory=list)

    def __call__(self, job: GenerationJob, store: Store) -> None:
        self.jobs.append(job)


def _library(tmp_path) -> Path:
    return write_library(
        tmp_path / "templates",
        make_manifest(
            TEMPLATE,
            slots=[
                make_slot("rejected", box=(10, 10, 190, 90)),
                make_slot("preferred", box=(10, 110, 190, 190)),
            ],
        ),
    )


def _client(tmp_path, *, topics=None, generate=None, renders=()):
    """A client whose app can accept an `llm` request.

    `anthropic_api_key` is set because `submit` builds a provider on the
    request thread before the injected `generate` seam is ever reached;
    without it every `mode: "llm"` post comes back 400 instead of 202. No
    network call is made — see `api_settings`.
    """
    return seeded_client(
        tmp_path,
        runs=[
            SeededRun(
                run_id=RUN,
                topics=topics if topics is not None else [make_topic("airport-cat")],
                renders=list(renders),
            )
        ],
        generate=generate or RecordingGenerate(),
        templates_dir=_library(tmp_path),
        anthropic_api_key="key",
    )


def _url(topic_id: str = "airport-cat") -> str:
    return f"/api/runs/{RUN}/topics/{topic_id}/renders"


def test_a_model_written_request_is_accepted_and_returns_generating_rows(tmp_path):
    """202 and the tiles' real ids, so the client can draw them
    immediately and they survive a refresh."""
    client = _client(tmp_path)

    response = client.post(
        _url(), json={"mode": "llm", "template_id": TEMPLATE, "count": 2}
    )

    assert response.status_code == 202
    body = response.json()
    assert len(body) == 2
    assert {row["status"] for row in body} == {"generating"}
    assert {row["origin"]["provenance"] for row in body} == {"auto"}


def test_a_hand_written_request_returns_the_captions_that_were_posted(tmp_path):
    client = _client(tmp_path)

    body = client.post(
        _url(),
        json={"mode": "manual", "template_id": TEMPLATE, "caption_slots": SLOTS},
    ).json()

    assert len(body) == 1
    assert body[0]["caption_slots"] == SLOTS
    assert body[0]["origin"] == {"provenance": "manual"}


def test_the_new_renders_appear_on_topic_detail(tmp_path):
    """The endpoint's whole point: the grid the panel sits above reads
    them back from the run's topic detail."""
    client = _client(tmp_path)

    created = client.post(_url(), json={"mode": "llm", "template_id": TEMPLATE}).json()
    detail = client.get(f"/api/runs/{RUN}/topics/airport-cat").json()

    assert [r["id"] for r in detail["renders"]] == [created[0]["id"]]


def test_generating_a_topic_that_was_never_ranked(tmp_path):
    """The below-the-cut `generate` link posts here for a topic the
    evaluate stage did not keep."""
    client = _client(
        tmp_path, topics=[make_topic("airport-cat"), make_topic("below-the-cut")]
    )

    response = client.post(
        _url("below-the-cut"), json={"mode": "llm", "template_id": TEMPLATE}
    )

    assert response.status_code == 202
    assert response.json()[0]["topic_id"] == "below-the-cut"


def test_an_unknown_run_is_a_404(tmp_path):
    client = _client(tmp_path)

    response = client.post(
        "/api/runs/nope/topics/airport-cat/renders",
        json={"mode": "llm", "template_id": TEMPLATE},
    )

    assert response.status_code == 404


def test_an_unknown_topic_is_a_404(tmp_path):
    client = _client(tmp_path)

    response = client.post(
        _url("no-such-topic"), json={"mode": "llm", "template_id": TEMPLATE}
    )

    assert response.status_code == 404


def test_an_unknown_template_is_a_400_naming_the_library(tmp_path):
    client = _client(tmp_path)

    response = client.post(_url(), json={"mode": "llm", "template_id": "nope"})

    assert response.status_code == 400
    assert TEMPLATE in response.json()["detail"]


def test_captions_that_do_not_fit_the_template_are_a_400(tmp_path):
    """A bad request, not a failed tile: nothing is written."""
    client = _client(tmp_path)

    response = client.post(
        _url(),
        json={
            "mode": "manual",
            "template_id": TEMPLATE,
            "caption_slots": {"rejected": "only one"},
        },
    )

    assert response.status_code == 400
    assert client.get(f"/api/runs/{RUN}/topics/airport-cat").json()["renders"] == []


def test_a_count_above_the_cap_is_a_422(tmp_path):
    """The bound is on the model, so it reaches phase 5 through the
    OpenAPI schema rather than as a rule the client has to know."""
    client = _client(tmp_path)

    response = client.post(
        _url(), json={"mode": "llm", "template_id": TEMPLATE, "count": 99}
    )

    assert response.status_code == 422


def test_an_unknown_mode_is_a_422(tmp_path):
    client = _client(tmp_path)

    response = client.post(_url(), json={"mode": "telepathy", "template_id": TEMPLATE})

    assert response.status_code == 422


def test_a_run_that_never_analysed_is_a_409(tmp_path):
    """A run that died in ingest has nothing to brief from. Saying "no
    such topic" would send the user looking for the wrong problem."""
    client = seeded_client(
        tmp_path,
        runs=[SeededRun(run_id=RUN, topics=[])],
        generate=RecordingGenerate(),
        templates_dir=_library(tmp_path),
    )

    response = client.post(_url(), json={"mode": "llm", "template_id": TEMPLATE})

    assert response.status_code == 409


def test_posting_does_not_disturb_the_topics_existing_renders(tmp_path):
    """On-demand generation appends. The render being compared against
    must still be there afterwards, alongside the new one.

    The new render's id is asserted too, and the post's status code
    checked: without both, a `submit` that did nothing at all would leave
    `older` in place and pass this test.
    """
    client = _client(
        tmp_path,
        renders=[make_render_record("older", run_id=RUN, topic_id="airport-cat")],
    )

    response = client.post(_url(), json={"mode": "llm", "template_id": TEMPLATE})
    assert response.status_code == 202
    created_id = response.json()[0]["id"]

    detail = client.get(f"/api/runs/{RUN}/topics/airport-cat").json()
    ids = {r["id"] for r in detail["renders"]}
    assert ids == {"older", created_id}


def test_the_generation_pool_does_not_outlive_the_app(tmp_path):
    """`ThreadPoolExecutor`'s workers are not daemon threads, and the pool
    spawns one on first use. An app whose lifespan forgets
    `generator.shutdown()` leaks that thread per app, which surfaces as a
    test suite or a server that will not exit.

    Built and entered by hand rather than through `seeded_client`, which
    defers the lifespan's exit to `conftest`'s autouse fixture — this test
    has to observe the world *after* shutdown, inside its own body.
    """
    settings = api_settings(
        tmp_path, templates_dir=_library(tmp_path), anthropic_api_key="key"
    )
    store = Store(settings.db_path)
    store.init_schema()
    seed_run(store, SeededRun(run_id=RUN, topics=[make_topic("airport-cat")]))
    store.close()

    with TestClient(create_app(settings, generate=RecordingGenerate())) as client:
        assert (
            client.post(
                _url(), json={"mode": "llm", "template_id": TEMPLATE}
            ).status_code
            == 202
        )

    assert not [
        thread
        for thread in threading.enumerate()
        if thread.name.startswith("zeitgeist-generate")
    ]
