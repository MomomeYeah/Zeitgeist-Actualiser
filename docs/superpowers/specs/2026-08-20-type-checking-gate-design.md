# Type Checking Gate — Astral Toolchain and Editor/CI Parity

**Date:** 2026-08-20
**Status:** Draft

## Purpose

VSCode shows type errors that no automated check enforces. `uv run pytest`
and `uv run ruff check .` both pass on a tree that Pylance marks up in red,
so nothing stops an agent declaring a task complete while the editor
disagrees. There is no CLAUDE.md, no CI, and no hook — the only thing
enforcing anything today is habit.

This spec adopts `ty` as the project's type checker, fixes every existing
diagnostic, and makes passing type checks a mechanical precondition for task
completion rather than an advisory one.

The governing requirement is that **diagnostics shown in the editor must be
exactly the diagnostics enforced by automation.** A gate that disagrees with
the editor trains people to ignore one or the other.

## Findings that shaped this design

Investigated on 2026-08-20, against `ty` 0.0.73 and `basedpyright` (the
open-source fork of the engine Pylance ships).

### Pylance cannot participate in a parity guarantee

Pylance's extension manifest declares `"bin": null` and
`"main": "./dist/extension.bundle.js"`. It is a language-server bundle with
no command-line entry point, and it is closed-source. No CI runner or hook
can invoke it. Any workflow built on Pylance is permanently an
approximation of what the editor shows.

Both Astral tools avoid this by construction: `ruff server` and `ty server`
are LSP modes of the identical binaries run on the command line. One pinned
artifact serves the editor and the gate.

### The reported `render.py` errors are false positives

`zeitgeist/media/render.py` lines 85, 96, 97, 102, 103, and 112 read `font`,
`lines`, and `line_height`, all bound inside the loop at line 78. Pylance
reports all six as possibly unbound. The loop header is:

```python
for size in range(MAX_FONT_SIZE, MIN_FONT_SIZE - 1, -2):
```

which is `range(64, 11, -2)` — 27 iterations, never empty. The variables are
always bound. The code is correct as written.

Three cases distinguish the tools:

| Case | Ground truth | ty (rule enabled) | basedpyright |
|---|---|---|---|
| `for x in xs:` (unknown length) | possibly unbound | `possibly-unresolved-reference` | possibly unbound |
| `for i in range(64, 11, -2):` | always bound | silent — correct | false positive |
| `for i in range(0):` | never bound; certain `NameError` | `unresolved-reference` | "possibly unbound" — understated |

`ty` evaluates the range bounds. `reportPossiblyUnbound` is a pure
control-flow check that does not. On this class of diagnostic `ty` is the
more precise tool, not the weaker one.

### `ty` has the rule; it ships disabled

`possibly-unresolved-reference` exists and is marked stable, with
`Default level: ignore` — the documentation cites false-positive volume.
Enabling it as an error surfaces **zero** additional findings across this
codebase, so it costs nothing and closes the gap that prompted this work.

`ruff` genuinely cannot cover this class: `--select ALL` reports nothing on
either loop case, and `PLE0601` (used-before-assignment) is not implemented.
Type checking and linting are separate responsibilities here.

### Current diagnostic inventory

`ty` reports 59 diagnostics; `basedpyright` reports 81. The difference is
almost entirely `basedpyright`'s stricter defaults plus the false positives
above. The 59 reduce to six root causes; a single pattern in three test
files accounts for 44 of them.

## Scope

- Add `ty` as a pinned dev dependency and configure it in `pyproject.toml`
- Commit `.vscode/` settings that point the editor at the pinned binaries
- Fix all 59 `ty` diagnostics at their root cause
- Add `CLAUDE.md` with a Definition of Done
- Add a blocking Stop hook in `.claude/settings.json`
- Move `.claude/worktrees/` from `.git/info/exclude` into `.gitignore`

### Out of scope

- **GitHub Actions CI.** Considered and deliberately deferred. The Stop hook
  covers agent work, which is the stated problem. CI remains the obvious
  next step if human commits start bypassing the gate.
- **pre-commit.** Same reasoning; it would duplicate the hook for now.
- **basedpyright.** Rejected: it splits the toolchain, and its false
  positives on `render.py` would become gate failures requiring suppression
  comments on correct code.
- **Adopting `ty`'s non-default rules beyond `possibly-unresolved-reference`.**
  Left for a later pass once the baseline is green.

## Tooling configuration

### pyproject.toml

Add to the existing dev group:

```toml
[dependency-groups]
dev = ["pytest>=8.3", "ruff>=0.8", "ty>=0.0.73,<0.1"]
```

The upper bound matters. `ty` is pre-1.0 and its rule defaults shift between
releases; an unbounded spec means a routine `uv sync` can turn a green tree
red. With the bound plus `uv.lock`, upgrades become a deliberate, reviewable
act.

Add the rule configuration:

```toml
[tool.ty.rules]
possibly-unresolved-reference = "error"
```

### .vscode/extensions.json

Recommends `charliermarsh.ruff` and `astral-sh.ty`, so anyone opening the
repo is prompted to install both.

### .vscode/settings.json

```json
{
  "python.analysis.typeCheckingMode": "off",
  "ruff.importStrategy": "fromEnvironment",
  "ty.importStrategy": "fromEnvironment",
  "[python]": {
    "editor.defaultFormatter": "charliermarsh.ruff",
    "editor.formatOnSave": true
  }
}
```

`typeCheckingMode: "off"` silences Pylance's *type* diagnostics only. Per
Pylance's own bundled description string, at `off` it still reports "invalid
syntax, unresolved imports, undefined variables", and completions, hover,
go-to-definition, and rename are unaffected. The setting's declared scope is
`"resource"`, so this is a legitimate per-workspace override; other Python
projects on the machine are untouched.

`importStrategy: "fromEnvironment"` makes each extension execute the
binary resolved from the project environment — the version pinned in
`uv.lock` — rather than the copy bundled inside the extension. This is the
single setting that makes the parity guarantee real rather than approximate.

Installing the ruff extension is a net gain: ruff's rules currently produce
no editor feedback at all, since no ruff extension is installed today.

## The 59 fixes

Every fix addresses the root cause. No blanket `# type: ignore`. If a
specific suppression proves genuinely necessary, it must be narrow and carry
a comment explaining why.

| Root cause | Count |
|---|---|
| Untyped test factories | 44 |
| `list` invariance | 7 |
| Optional subscript | 3 |
| Test stub attribute access | 3 |
| Bare `type` parameter | 1 |
| Pillow union return | 1 |
| **Total** | **59** |

### Untyped test factories — 44 diagnostics

`tests/test_models.py:25` (20), `tests/test_config.py:8` (21), and
`tests/test_media_brief.py:51` (3) all use this shape:

```python
def _post(**overrides) -> Post:
    defaults = dict(
        platform="reddit",
        score=4200,
        created_at=datetime(2026, 8, 16, 9, 0, tzinfo=UTC),
        ...
    )
    return Post(**{**defaults, **overrides})
```

`dict(...)` over heterogeneous values infers
`dict[str, str | None | int | datetime]`. Splatting that into the model
means every field is offered the entire union, producing one diagnostic per
field — ten from a single line. Bare `**overrides` compounds it as
`dict[str, Unknown]`.

Fix:

```python
def _post(**overrides: Any) -> Post:
    defaults: dict[str, Any] = dict(...)
    return Post(**{**defaults, **overrides})
```

`Any` is the honest annotation for a factory whose whole purpose is to
accept arbitrary field overrides — this is a correction, not a suppression.
Pydantic still validates every value at runtime, so test coverage is
unchanged.

### `list` invariance — 7 diagnostics

`zeitgeist/pipeline.py:123` declares `_write(path: Path, models: list[BaseModel])`
and is called with `list[Post]`, `list[Topic]`, `list[ScoredTopic]`, and
`list[MediaBrief]`. `list` is invariant, so none are accepted. `_write` only
iterates, so the parameter widens to `Sequence[BaseModel]`. (4)

`CompositeSource.__init__`, called from `tests/test_sources_composite.py:99`
and `:110`, has the same shape — `list[Source]` against `list[StubSource]` —
and the same fix. (2)

`tests/test_llm_ollama.py:162` passes a heterogeneous list literal, inferred
as `list[StubResponse | ErrorShapedResponse]`, to a parameter declared
`list[StubResponse]`. Same invariance, same fix. (1)

### Bare `type` parameter — 1 diagnostic

`zeitgeist/pipeline.py:132` calls `schema.model_validate(entry)` where
`schema` is annotated bare `type`, which carries no `model_validate`. A
`TypeVar` bound to `BaseModel` with `schema: type[T]` types it correctly and
improves the return type at every call site.

### Optional subscript — 3 diagnostics

`tests/test_store.py:122-124` index a value typed `T | None`. Narrow with an
assertion before indexing, which also gives a clearer failure message than
a `TypeError` when the value is unexpectedly absent.

### Pillow union return — 1 diagnostic

`zeitgeist/media/render.py:30` declares `-> ImageFont.FreeTypeFont`, but
`ImageFont.load_default(size=...)` is typed `FreeTypeFont | ImageFont`. At
runtime the `size` argument guarantees a `FreeTypeFont`. Resolve by
narrowing at the return with an explanatory comment, preferring not to widen
the signature — callers pass the result to `draw.textlength`, which needs
the concrete type.

### Test stub attribute access — 3 diagnostics

`tests/test_sources_composite.py:182,196` reach for `_sources` on a value
typed `Source`; `tests/test_sources_lemmy.py:238` accesses `urls` on
`Any | Client`. Both are stubs whose declared types are narrower than what
the tests actually use. Type the stubs to match their real shape.

### Explicitly unchanged

`render.py` lines 85, 96, 97, 102, 103, and 112 need no change. They are
correct code that Pylance mis-flags, and `ty` agrees they are correct. Once
Pylance's type diagnostics are off, the squiggles disappear without the code
being contorted to satisfy a false positive.

## Enforcement

### CLAUDE.md

The repo has no CLAUDE.md. It gains one, whose core is a Definition of Done:

```
A task is not complete until all three pass:

    uv run ruff check .
    uv run ty check
    uv run pytest
```

Also documents the toolchain choice, points at this spec for rationale, and
carries the existing `ruff format` convention from the earlier plan docs so
the conventions live in one discoverable place.

### Stop hook

`.claude/settings.json` gains a Stop hook running those three commands and
blocking completion on a non-zero exit. Measured cost: ruff 0.5s, ty 0.6s,
pytest 12.2s across 243 tests — roughly 14s, cheap enough to run on every
task.

The hook is the mechanical half and CLAUDE.md is the explanatory half.
Neither replaces the other: the hook cannot say *why*, and the instruction
cannot enforce.

Scope note: the gate covers lint and tests as well as types. A gate that
lets an agent declare success on failing tests is the wrong shape, and all
three together cost 14s.

### .gitignore

`.claude/worktrees/` is currently excluded via `.git/info/exclude`, which is
local to this clone and never shared. Committing `.claude/settings.json`
requires that entry move into `.gitignore`, or every other clone will see
worktree directories as untracked noise.

## Testing

The tooling is configuration, so it is verified by observing its behaviour
rather than by unit tests.

1. **Baseline.** From a cold `uv sync`, confirm `uv run ruff check .`,
   `uv run ty check`, and `uv run pytest` all pass.
2. **The rule is actually on.** Confirm `ty` reads `[tool.ty.rules]` from
   `pyproject.toml` — add a deliberate possibly-unbound reference, confirm
   it is reported as an *error*, then revert.
3. **The hook actually blocks.** Introduce a type error, confirm the Stop
   hook blocks completion rather than merely printing a warning, then
   revert. An unverified hook is worse than no hook: it grants false
   confidence.
4. **Editor and CLI agree.** With both extensions installed, confirm the
   editor's Problems panel matches `ty check` output on a file with a known
   error.
5. **No behaviour change.** All 243 tests pass before and after the fixes.
   The changes are annotations and narrowing; any test change signals an
   accidental behaviour change.

## Risks

**`ty` is v0.0.73.** Rule defaults and diagnostics will change. Mitigated by
the `<0.1` bound plus `uv.lock`, which makes every upgrade explicit. The
review that accompanies an upgrade is the point, not an inconvenience.

**Pylance's unique diagnostics go quiet.** Turning off its type checking
loses its checks wholesale, not selectively. The one class identified as
genuinely unique — possibly-unbound — is recovered by enabling
`possibly-unresolved-reference`, and `ty` handles it more precisely. Other
divergences may surface later; the fallback is enabling more `ty` rules, or
reconsidering `basedpyright`.

**`Any` in test factories reduces type coverage in tests.** Accepted
deliberately: these functions exist to accept arbitrary overrides, and
pydantic validates at runtime regardless. The alternative — a `TypedDict`
with `total=False` per model — adds maintenance at every schema change for
little benefit in test code.

## Decisions and rationale

**Why `ty` over `basedpyright`.** Editor/CI parity was the governing
requirement, and both tools can deliver it. `ty` wins on toolchain
coherence — the project already runs `ruff` and `uv`, so one vendor and one
config file covers lint, format, and types — and on precision for the
specific diagnostics that prompted this work. `basedpyright` is more mature
and catches strictly more, but adopting it would mean adding suppression
comments to correct code in `render.py`.

**Why not keep Pylance as the type checker.** Not a preference. It has no
CLI and is closed-source, so the parity requirement is unsatisfiable by
construction.

**Why a hook rather than CI first.** The stated problem is agents declaring
tasks complete on a red tree. A Stop hook addresses that directly and gives
feedback in seconds. CI addresses a different, real problem — human commits
— and is the natural follow-up rather than a competitor.

**Why fix rather than suppress.** 43 of 59 came from three lines, and the
fix is a more accurate annotation. Suppressing would have hidden the real
`list` invariance and bare-`type` issues in `pipeline.py`, which are genuine
signatures worth correcting.
