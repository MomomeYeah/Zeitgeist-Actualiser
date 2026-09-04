"""The console entry point: `uv run zeitgeist`.

No subcommands. The web UI is the interface, so the one thing this command
does is start the server. `--reload` is off by default deliberately:
uvicorn's reloader kills the worker thread phase 3 adds if a file is saved
while a pipeline is in flight, and losing a run to an editor autosave is a
worse default than restarting by hand.
"""

import argparse
import sys

import uvicorn

from zeitgeist.api import create_app
from zeitgeist.config import Settings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="zeitgeist")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Restart on file changes. Off by default: the reloader kills an "
        "in-flight run.",
    )
    args = parser.parse_args(argv)

    uvicorn.run(
        create_app(Settings()),
        host=args.host,
        port=args.port,
        reload=args.reload,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
