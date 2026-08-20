# Zeitgeist Actualiser

Scrapes social platforms, works out what is trending, and generates memes
about it. See README.md for setup and usage.

## Definition of Done

A task is not complete until all four of these pass:

```bash
uv run ruff check .
uv run ruff format --check .
uv run ty check
uv run pytest
```

Do not report a task as finished, and do not open a pull request, until you
have run them and seen them pass. A Stop hook enforces this, and CI runs the
same four commands on every push and pull request.

## Toolchain

- **uv** manages the environment. `uv.lock` pins exact versions; run
  `uv sync` after changing dependencies.
- **ruff** does linting and formatting. Rules `E, F, I, UP, B, SIM`, line
  length 88, configured in `pyproject.toml`.
- **ty** does type checking, configured in `pyproject.toml`. It is pre-1.0
  and pinned `<0.1` deliberately — upgrade it as a deliberate change, not as
  a side effect.
- **pytest** runs the suite. Tests are hermetic: `tests/conftest.py` strips
  every environment variable `Settings` reads, so results never depend on a
  local `.env` or an ambient shell.

Python 3.14, so use PEP 695 generics (`def f[T: Bound](...)`) rather than
`typing.TypeVar`.

## Type checking

The editor and the command line run the same binaries. `.vscode/settings.json`
sets both extensions to `importStrategy: "fromEnvironment"`, so what you see
as you type is what the gate enforces.

Pylance's own type checking is off. It has no CLI and is closed-source, so no
hook or CI runner can reproduce its diagnostics — keeping it on would mean
the editor and the gate could disagree, which is the problem this setup
exists to prevent. Pylance still provides completions, hover, go-to-definition
and rename.

Fix type errors at the root cause. No blanket `# type: ignore`; a narrow
suppression needs a comment explaining why.

Rationale for these choices, including the measurements behind them, is in
`docs/superpowers/specs/2026-08-20-type-checking-gate-design.md`.
