"""Command-line entry point."""

import argparse
import logging
import sys
from pathlib import Path

from zeitgeist.config import PACKAGE_ROOT, Settings
from zeitgeist.llm.factory import build_provider
from zeitgeist.media.templates import validate_templates
from zeitgeist.pipeline import Stage, new_run_id, run_pipeline
from zeitgeist.sources.reddit import RedditSource
from zeitgeist.store import Store


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="zeitgeist")
    subparsers = parser.add_subparsers(dest="command")
    # Bare `zeitgeist` means `zeitgeist run`, so the top-level parser must
    # carry every attribute `_run` reads — not just `command`.
    parser.set_defaults(
        command="run",
        run_id=None,
        resume_from=Stage.INGEST.value,
        verbose=False,
    )

    run = subparsers.add_parser("run", help="Scrape, analyse, and generate memes")
    run.add_argument("--run-id", default=None, help="Reuse an existing run directory")
    run.add_argument(
        "--resume-from",
        choices=[stage.value for stage in Stage],
        default=Stage.INGEST.value,
        help="Skip earlier stages and reuse their checkpoints",
    )
    run.add_argument("--verbose", action="store_true")

    check = subparsers.add_parser(
        "validate-templates", help="Check every template manifest"
    )
    check.add_argument("--dir", default=None, help="Template directory to check")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "validate-templates":
        return _validate(args, parser)
    return _run(args, parser)


def _validate(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    # Deliberately does not build Settings: checking the shipped templates
    # should work before anyone has written a .env.
    directory = Path(args.dir) if args.dir else PACKAGE_ROOT / "media" / "templates"
    problems = validate_templates(directory)
    if not problems:
        print(f"All templates in {directory} are valid.")
        return 0
    for problem in problems:
        print(problem)
    return 1


def _run(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    start_at = Stage(args.resume_from)
    if start_at is not Stage.INGEST and not args.run_id:
        parser.error("--resume-from requires --run-id")

    settings = _settings_or_exit(parser)
    store = Store(settings.db_path)
    store.init_schema()

    try:
        run_dir = run_pipeline(
            settings=settings,
            source=RedditSource.from_settings(settings),
            provider=build_provider(settings),
            store=store,
            run_id=args.run_id or new_run_id(),
            start_at=start_at,
        )
        summary = store.run_summary(args.run_id or run_dir.name)
    finally:
        store.close()

    memes = len(list(run_dir.glob("*.png")))
    posts = (summary or {}).get("post_count", 0)
    print(f"Run complete: {run_dir} ({posts} posts, {memes} memes)")
    return 0


def _settings_or_exit(parser: argparse.ArgumentParser) -> Settings:
    try:
        return Settings()
    except Exception as exc:
        parser.error(f"Configuration error: {exc}\nCopy .env.example to .env.")


if __name__ == "__main__":
    sys.exit(main())
