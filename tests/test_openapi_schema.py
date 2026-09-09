"""The checked-in OpenAPI document must still be the app's own.

`web/openapi.json` is what `openapi-typescript` generates the client types
from, and the frontend gate reads it from disk rather than from a running
server. That makes it a copy, and a copy of a contract is only useful while
something proves it is current. This is that proof: change a response model
without re-running `scripts/dump_openapi.py` and `uv run pytest` goes red
here, before the drift can reach a screen.
"""

import json
from pathlib import Path

from zeitgeist.api import create_app
from zeitgeist.config import Settings

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "web" / "openapi.json"


def test_checked_in_openapi_matches_the_app(tmp_path):
    app = create_app(Settings(db_path=tmp_path / "z.db", output_dir=tmp_path / "out"))

    assert SCHEMA_PATH.is_file(), (
        f"{SCHEMA_PATH} is missing. Run: uv run python scripts/dump_openapi.py"
    )
    assert json.loads(SCHEMA_PATH.read_text(encoding="utf-8")) == app.openapi(), (
        "web/openapi.json is stale. Regenerate it with "
        "`uv run python scripts/dump_openapi.py`, then regenerate the client "
        "types with `npm --prefix web run generate:types`."
    )


def test_every_endpoint_this_phase_reads_is_present():
    """The nine read endpoints phase 5 builds against.

    A guard against the schema being regenerated from an app that failed to
    mount a router: `create_app` imports its routers inside its own body, so
    a broken import would produce a smaller but perfectly valid document,
    and the equality test above would happily accept it.
    """
    paths = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))["paths"]

    for path in (
        "/api/runs",
        "/api/runs/{run_id}",
        "/api/runs/{run_id}/topics",
        "/api/runs/{run_id}/topics/{topic_id}",
        "/api/runs/{run_id}/log",
        "/api/topics",
        "/api/renders/{render_id}",
        "/api/renders/{render_id}/image",
        "/api/settings",
    ):
        assert path in paths, f"{path} is missing from the schema"
        assert "get" in paths[path], f"{path} has no GET operation"
