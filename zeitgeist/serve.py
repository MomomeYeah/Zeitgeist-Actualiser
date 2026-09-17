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
from fastapi import FastAPI

from zeitgeist.api import create_app
from zeitgeist.config import StoredSettingError
from zeitgeist.store import StoreSchemaError


def _app() -> FastAPI:
    """Built lazily, on demand, by uvicorn's reloader.

    Reload needs an import string it can re-invoke after each restart, not
    an app instance built once up front — passing an instance disables
    `--reload` outright (uvicorn refuses it at startup). Naming this factory
    keeps that requirement satisfied without building the app before we know
    whether reload was even asked for.

    No `Settings` argument: `create_app` resolves every scoped field from
    the store itself now, which is what lets a value saved on the settings
    screen survive a reload without this factory doing anything special.
    """
    return create_app()


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

    if args.reload:
        # Import string + factory=True: the reloader re-imports and rebuilds
        # the app itself on every change, in a subprocess it manages. Nothing
        # is opened in this process on this path.
        uvicorn.run(
            "zeitgeist.serve:_app",
            factory=True,
            host=args.host,
            port=args.port,
            reload=True,
        )
        return 0

    try:
        app = create_app()
    except (StoreSchemaError, StoredSettingError) as error:
        # Both exceptions' own messages already say what to do about it —
        # "delete it and re-run" for a stale schema, the offending key for a
        # stored value that no longer validates — so a bare traceback would
        # bury that as the first thing anyone running this command against a
        # broken database sees. Nothing else here is caught: a genuine bug
        # should still surface as a traceback.
        print(str(error), file=sys.stderr)
        return 1

    uvicorn.run(app, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
