"""Write the app's OpenAPI document to `web/openapi.json`.

The one command that carries the contract across the language boundary.
The frontend generates its TypeScript from the file rather than from a
running server, so `npm --prefix web run typecheck` needs nothing listening
on port 8000 — a gate that needs a server running is a gate that fails for
the wrong reason.

Run it after any change to a response model, then regenerate the client
types:

    uv run python scripts/dump_openapi.py
    npm --prefix web run generate:types
"""

import json
import sys
import tempfile
from pathlib import Path

from zeitgeist.api import create_app
from zeitgeist.config import Settings

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "web" / "openapi.json"


def main() -> int:
    # A throwaway database: building the app opens a store and initialises a
    # schema, and dumping a schema must not touch the real one — nor create
    # it as a side effect on a machine that has never run the tool.
    with tempfile.TemporaryDirectory() as tmp:
        scratch = Path(tmp)
        app = create_app(
            Settings(db_path=scratch / "openapi.db", output_dir=scratch / "out")
        )
        document = app.openapi()
        # create_app opens its Store immediately, not inside the lifespan,
        # and nothing here runs that lifespan to close it — TestClient
        # would, but this script never builds one. Close it explicitly so
        # the temp directory's own cleanup below doesn't trip over a file
        # sqlite still has open, which is fatal on Windows.
        app.state.store.close()

    TARGET.parent.mkdir(parents=True, exist_ok=True)
    # indent=2 and a trailing newline so a regeneration produces a reviewable
    # diff rather than one very long changed line. newline="\n" so the
    # checked-in artifact uses LF on every platform, matching what
    # json.dumps and openapi-typescript both produce.
    TARGET.write_text(
        json.dumps(document, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"Wrote {TARGET.relative_to(ROOT)} ({len(document['paths'])} paths)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
