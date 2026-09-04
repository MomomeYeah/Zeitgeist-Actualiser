"""Check every template manifest against its image.

Deliberately builds no Settings: checking the shipped templates should work
before anyone has written a .env.

    uv run python scripts/validate_templates.py [directory]
"""

import sys
from pathlib import Path

from zeitgeist.config import PACKAGE_ROOT
from zeitgeist.media.templates import validate_templates


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    directory = Path(args[0]) if args else PACKAGE_ROOT / "media" / "templates"
    problems = validate_templates(directory)
    if not problems:
        print(f"All templates in {directory} are valid.")
        return 0
    for problem in problems:
        print(problem)
    return 1


if __name__ == "__main__":
    sys.exit(main())
