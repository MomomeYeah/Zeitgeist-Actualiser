# Type Checking Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Adopt `ty` as this project's type checker, fix all 59 existing type diagnostics at their root cause, and make passing type checks a mechanical precondition for task completion.

**Architecture:** One pinned toolchain serves the editor, the agent gate, and CI. `ruff` and `ty` are dev dependencies pinned by `uv.lock`; their VSCode extensions run those same binaries via `importStrategy: "fromEnvironment"`; a Stop hook and a GitHub Actions workflow run the identical four commands. Pylance stays for IntelliSense with its type diagnostics off, because it ships no CLI and therefore cannot participate in an editor/CI parity guarantee.

**Tech Stack:** Python 3.14, uv, ruff, ty, pytest, pydantic, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-08-20-type-checking-gate-design.md`

## Global Constraints

- Python `>=3.14`; `target-version = "py314"`. Use PEP 695 generics (`def f[T: Bound](...)`), not `typing.TypeVar`.
- `ty` must be pinned `>=0.0.73,<0.1`. It is pre-1.0 and its rule defaults shift between releases.
- ruff line length 88; lint rules `E, F, I, UP, B, SIM`. Import order is enforced (`I`) — stdlib group first, alphabetical.
- Fix at the root cause. No blanket `# type: ignore`. Any suppression must be narrow and carry a comment explaining why.
- No test behaviour may change. All 243 tests pass before and after; the edits are annotations and narrowing only.
- The four Definition of Done commands, referenced identically by CLAUDE.md, the Stop hook, and CI:
  ```
  uv run ruff check .
  uv run ruff format --check .
  uv run ty check
  uv run pytest
  ```
- Baseline verified 2026-08-20: `ty check` reports exactly **59** diagnostics, both with and without `possibly-unresolved-reference` enabled.

## File Structure

**Created:**
- `.vscode/settings.json` — points the editor at the lockfile-pinned binaries; silences Pylance type diagnostics
- `.vscode/extensions.json` — recommends the ruff and ty extensions
- `CLAUDE.md` — Definition of Done plus toolchain rationale
- `.claude/settings.json` — Stop hook enforcing the Definition of Done
- `.github/workflows/ci.yml` — the same checks on push and PR

**Modified:**
- `pyproject.toml` — add `ty` to dev deps; add `[tool.ty.rules]`
- `.gitignore` — add `.claude/worktrees/`
- `zeitgeist/pipeline.py` — `Sequence` parameter; PEP 695 generic `_read`
- `zeitgeist/media/render.py` — narrow the Pillow union return
- `zeitgeist/sources/composite.py` — `Sequence[Source]` parameter
- `tests/test_models.py`, `tests/test_config.py`, `tests/test_media_brief.py` — typed factories
- `tests/test_llm_ollama.py`, `tests/test_store.py`, `tests/test_sources_composite.py`, `tests/test_sources_lemmy.py` — remaining narrowing fixes

**Diagnostic accounting** (must total 59):

| Task | Root cause | Count |
|---|---|---|
| 2 | Source-code signatures (`pipeline.py` 5, `render.py` 1, `composite.py` → 2 test sites) | 8 |
| 3 | Untyped test factories | 44 |
| 4 | Remaining test narrowing | 7 |
| | **Total** | **59** |

---

### Task 1: Adopt and configure ty

**Files:**
- Modify: `pyproject.toml`

**Interfaces:**
- Consumes: nothing
- Produces: `uv run ty check` available to every later task as the verification command; `[tool.ty.rules]` block that later tasks rely on being read.

- [ ] **Step 1: Add ty to the dev dependency group**

In `pyproject.toml`, replace:

```toml
[dependency-groups]
dev = ["pytest>=8.3", "ruff>=0.8"]
```

with:

```toml
[dependency-groups]
# ty is pre-1.0 and its rule defaults shift between releases; the upper bound
# plus uv.lock makes a version change a deliberate, reviewable act rather
# than something a routine `uv sync` can spring on a green tree.
dev = ["pytest>=8.3", "ruff>=0.8", "ty>=0.0.73,<0.1"]
```

- [ ] **Step 2: Add the rule configuration**

Append to the end of `pyproject.toml`:

```toml
[tool.ty.rules]
# ty ships this rule disabled by default, citing false-positive volume.
# Enabling it adds zero findings to this codebase and closes the one gap
# Pylance covered that ty otherwise would not. See the design spec.
possibly-unresolved-reference = "error"
```

- [ ] **Step 3: Sync and confirm ty resolves from the locked environment**

Run: `uv sync`
Then: `uv run ty --version`
Expected: prints a `ty 0.0.x` version. If `uv run ty` is not found, the dependency group edit did not take.

- [ ] **Step 4: Establish the baseline**

Run: `uv run ty check --output-format concise`
Expected: ends with `Found 59 diagnostics`.

This is the pre-fix baseline, not a pass. If the number differs from 59, stop and reconcile against the spec's accounting table before making any fixes — a different number means the codebase moved since the plan was written.

- [ ] **Step 5: Prove the rule config is actually read**

Create a throwaway file `_rulecheck.py` in the project root:

```python
def f(xs: list[int]) -> int:
    for x in xs:
        y = x * 2
    return y
```

Run: `uv run ty check --output-format concise _rulecheck.py`
Expected: a line containing `error[possibly-unresolved-reference]`.

If it reports nothing, `[tool.ty.rules]` is not being read — check the table name spelling before continuing.

- [ ] **Step 6: Delete the throwaway file**

Run: `rm _rulecheck.py`
Then: `git status --short`
Expected: `_rulecheck.py` does not appear. Only `pyproject.toml` and `uv.lock` are modified.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "build: adopt ty as the project type checker"
```

---

### Task 2: Fix source-code type errors

**Files:**
- Modify: `zeitgeist/pipeline.py:8-14`, `zeitgeist/pipeline.py:123`, `zeitgeist/pipeline.py:128`
- Modify: `zeitgeist/media/render.py:1-6`, `zeitgeist/media/render.py:21-33`
- Modify: `zeitgeist/sources/composite.py:17`
- Test: existing `tests/test_pipeline.py`, `tests/test_media_render.py`, `tests/test_sources_composite.py`

**Interfaces:**
- Consumes: `uv run ty check` from Task 1
- Produces:
  - `_write(path: Path, models: Sequence[BaseModel]) -> None`
  - `_read[T: BaseModel](path: Path, schema: type[T]) -> list[T]` — now returns a precise element type, so `_read(p, Post)` is `list[Post]`
  - `CompositeSource.__init__(self, sources: Sequence[Source]) -> None`
  - `resolve_font(font_path: Path | None, size: int) -> ImageFont.FreeTypeFont` — signature unchanged, body narrowed

- [ ] **Step 1: Confirm the failing diagnostics**

Run: `uv run ty check --output-format concise zeitgeist/`
Expected: 6 diagnostics — `render.py:30` (`invalid-return-type`), `pipeline.py:65,77,87,92` (`invalid-argument-type`), `pipeline.py:132` (`unresolved-attribute`).

- [ ] **Step 2: Add the Sequence import to pipeline.py**

In `zeitgeist/pipeline.py`, replace:

```python
import json
import logging
from datetime import UTC, datetime
```

with:

```python
import json
import logging
from collections.abc import Sequence
from datetime import UTC, datetime
```

- [ ] **Step 3: Widen `_write` and make `_read` generic**

In `zeitgeist/pipeline.py`, replace:

```python
def _write(path: Path, models: list[BaseModel]) -> None:
    payload = [model.model_dump(mode="json") for model in models]
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _read(path: Path, schema: type) -> list:
    if not path.is_file():
        raise FileNotFoundError(f"Missing checkpoint: {path}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [schema.model_validate(entry) for entry in raw]
```

with:

```python
# Sequence rather than list: list is invariant, so a list[Post] is not a
# list[BaseModel] and every call site was rejected. _write only iterates.
def _write(path: Path, models: Sequence[BaseModel]) -> None:
    payload = [model.model_dump(mode="json") for model in models]
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _read[T: BaseModel](path: Path, schema: type[T]) -> list[T]:
    if not path.is_file():
        raise FileNotFoundError(f"Missing checkpoint: {path}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [schema.model_validate(entry) for entry in raw]
```

The bare `type` carried no `model_validate`. Binding `T` to `BaseModel` supplies it and makes the return type precise: `_read(path, Post)` is now `list[Post]` rather than a bare `list`.

- [ ] **Step 4: Narrow the Pillow union in render.py**

In `zeitgeist/media/render.py`, replace:

```python
import textwrap
from pathlib import Path
```

with:

```python
import textwrap
from pathlib import Path
from typing import cast
```

Then replace:

```python
    if font_path is None:
        return ImageFont.load_default(size=size)
```

with:

```python
    if font_path is None:
        # load_default is typed FreeTypeFont | ImageFont because it returns
        # the bitmap ImageFont when size is omitted. Passing size selects the
        # scalable FreeType face, which is what the return type promises and
        # what draw.textlength needs.
        return cast(ImageFont.FreeTypeFont, ImageFont.load_default(size=size))
```

- [ ] **Step 5: Widen the CompositeSource parameter**

In `zeitgeist/sources/composite.py`, replace:

```python
import logging
import math

from zeitgeist.models import Post
```

with:

```python
import logging
import math
from collections.abc import Sequence

from zeitgeist.models import Post
```

Then replace:

```python
    def __init__(self, sources: list[Source]) -> None:
```

with:

```python
    # Sequence, not list: list is invariant, so a list of any concrete
    # Source implementation was rejected at the call site.
    def __init__(self, sources: Sequence[Source]) -> None:
```

- [ ] **Step 6: Verify the source tree is clean**

Run: `uv run ty check --output-format concise zeitgeist/`
Expected: `All checks passed!`

Watch for a specific surprise here: making `_read` generic gives it a precise
return type where it previously returned a bare `list`, which can newly expose
a genuine mismatch if a variable is reassigned across incompatible types (for
instance `topics` at lines 71-80, or `ranked` at lines 81-89). If a *new*
diagnostic appears that was not in the Step 1 list, it is a real finding the
old bare `list` was hiding. Fix it at the root cause and note it — do not
revert the generic to make it disappear.

- [ ] **Step 7: Verify no behaviour changed**

Run: `uv run pytest -q`
Expected: `243 passed`.

Any failure here means an edit changed runtime behaviour rather than annotations — revert and re-read the step.

- [ ] **Step 8: Verify lint and formatting**

Run: `uv run ruff check . && uv run ruff format --check .`
Expected: no errors, and `49 files already formatted`.

- [ ] **Step 9: Commit**

```bash
git add zeitgeist/pipeline.py zeitgeist/media/render.py zeitgeist/sources/composite.py
git commit -m "fix: correct variance and generic signatures flagged by ty"
```

---

### Task 3: Type the test factories

**Files:**
- Modify: `tests/test_models.py:1-6`, `tests/test_models.py:24-25`, `tests/test_models.py:40-41`
- Modify: `tests/test_config.py:1-8`
- Modify: `tests/test_media_brief.py:1`, `tests/test_media_brief.py:50-51`

**Interfaces:**
- Consumes: `uv run ty check` from Task 1
- Produces: `_post(**overrides: Any) -> Post`, `_scored(**overrides: Any) -> ScoredTopic`, `_settings(**overrides: Any) -> Settings`, `_choice(**overrides: Any) -> BriefChoice` — call signatures unchanged for every existing caller.

**Why this is a fix, not a suppression:** `dict(...)` over heterogeneous values infers a union of every value type — `dict[str, str | None | int | datetime]` in `test_models.py`. Splatting that into a model offers every field the whole union, producing one diagnostic per field: ten from a single line. `Any` is the honest annotation for a factory whose purpose is accepting arbitrary field overrides, and pydantic still validates every value at runtime, so coverage is unchanged.

- [ ] **Step 1: Confirm the failing diagnostics**

Run: `uv run ty check --output-format concise tests/test_models.py tests/test_config.py tests/test_media_brief.py`
Expected: 44 diagnostics, all `invalid-argument-type`, clustered at `test_config.py:13`, `test_models.py:37`, `test_models.py:50`, and `test_media_brief.py:56`.

- [ ] **Step 2: Fix the test_models.py factories**

Replace:

```python
from datetime import UTC, datetime

import pytest
```

with:

```python
from datetime import UTC, datetime
from typing import Any

import pytest
```

Replace:

```python
def _post(**overrides) -> Post:
    defaults = dict(
```

with:

```python
def _post(**overrides: Any) -> Post:
    defaults: dict[str, Any] = dict(
```

Replace:

```python
def _scored(**overrides) -> ScoredTopic:
    defaults = dict(
```

with:

```python
def _scored(**overrides: Any) -> ScoredTopic:
    defaults: dict[str, Any] = dict(
```

- [ ] **Step 3: Fix the test_config.py factory**

Replace:

```python
import pytest

from zeitgeist.config import DEFAULT_SENTIMENT_WEIGHTS, Settings
```

with:

```python
from typing import Any

import pytest

from zeitgeist.config import DEFAULT_SENTIMENT_WEIGHTS, Settings
```

Replace:

```python
def _settings(**overrides) -> Settings:
    defaults = dict(
```

with:

```python
def _settings(**overrides: Any) -> Settings:
    defaults: dict[str, Any] = dict(
```

- [ ] **Step 4: Fix the test_media_brief.py factory**

Replace:

```python
import pytest
```

with:

```python
from typing import Any

import pytest
```

Replace:

```python
def _choice(**overrides) -> BriefChoice:
    defaults = dict(
```

with:

```python
def _choice(**overrides: Any) -> BriefChoice:
    defaults: dict[str, Any] = dict(
```

- [ ] **Step 5: Verify those three files are clean**

Run: `uv run ty check --output-format concise tests/test_models.py tests/test_config.py tests/test_media_brief.py`
Expected: `All checks passed!`

- [ ] **Step 6: Verify no behaviour changed**

Run: `uv run pytest -q`
Expected: `243 passed`.

- [ ] **Step 7: Verify lint and formatting**

Run: `uv run ruff check . && uv run ruff format --check .`
Expected: no errors. Note ruff's `I` rule enforces the import order shown above — if it reports `I001`, run `uv run ruff check --fix .` and re-check.

- [ ] **Step 8: Commit**

```bash
git add tests/test_models.py tests/test_config.py tests/test_media_brief.py
git commit -m "test: annotate model factories so overrides type-check"
```

---

### Task 4: Fix the remaining test diagnostics

**Files:**
- Modify: `tests/test_llm_ollama.py:47`
- Modify: `tests/test_store.py:121-124`
- Modify: `tests/test_sources_composite.py:180-182`, `tests/test_sources_composite.py:189-196`
- Modify: `tests/test_sources_lemmy.py:233-238`

**Interfaces:**
- Consumes: `CompositeSource` (already imported at `tests/test_sources_composite.py:10`); `Store.run_summary(run_id: str) -> dict | None`
- Produces: nothing consumed by later tasks. After this task `uv run ty check` passes on the whole repository.

- [ ] **Step 1: Confirm the failing diagnostics**

Run: `uv run ty check --output-format concise`
Expected: 7 diagnostics — `test_llm_ollama.py:162`, `test_store.py:122,123,124`, `test_sources_composite.py:182,196`, `test_sources_lemmy.py:238`.

- [ ] **Step 2: Widen the ollama StubClient parameter**

`tests/test_llm_ollama.py:162` passes `[ErrorShapedResponse(), _ok(...)]`, inferred as `list[StubResponse | ErrorShapedResponse]`, into a parameter declared `list[StubResponse]`. The stub's own docstring says it replays raw bodies so malformed output needs no subclassing — so the honest parameter type accepts any response-shaped object.

Add the import. Replace:

```python
import json

import pytest
```

with:

```python
import json
from collections.abc import Sequence
from typing import Any

import pytest
```

Replace:

```python
    def __init__(self, responses: list[StubResponse]):
```

with:

```python
    # Sequence[Any], not list[StubResponse]: tests stage malformed bodies
    # with purpose-built local classes, and list is invariant.
    def __init__(self, responses: Sequence[Any]):
```

- [ ] **Step 3: Narrow the Optional in test_store.py**

`Store.run_summary` returns `dict | None`, so subscripting it directly is unsound. Replace:

```python
    store.finish_run("run1", status="ok", post_count=42)
    summary = store.run_summary("run1")
    assert summary["status"] == "ok"
```

with:

```python
    store.finish_run("run1", status="ok", post_count=42)
    summary = store.run_summary("run1")
    assert summary is not None
    assert summary["status"] == "ok"
```

This also improves the failure message: a missing run now fails on the assertion naming the problem rather than on a `TypeError` about subscripting `None`.

- [ ] **Step 4: Narrow build_source's return type in test_sources_composite.py**

`build_source` is declared `-> Source`, and the `Source` protocol has no `_sources`. The tests know they get a `CompositeSource`; asserting it makes that explicit and narrows the type.

Replace:

```python
    settings = Settings(_env_file=None, anthropic_api_key="key", sources="lemmy")
    assert [type(source) for source in build_source(settings)._sources] == [LemmySource]
```

with:

```python
    settings = Settings(_env_file=None, anthropic_api_key="key", sources="lemmy")
    composite = build_source(settings)
    assert isinstance(composite, CompositeSource)
    assert [type(source) for source in composite._sources] == [LemmySource]
```

Replace:

```python
    names = [source.name for source in build_source(settings)._sources]
    assert names == ["lemmy", "reddit"]
```

with:

```python
    composite = build_source(settings)
    assert isinstance(composite, CompositeSource)
    names = [source.name for source in composite._sources]
    assert names == ["lemmy", "reddit"]
```

- [ ] **Step 5: Hold the stub reference in test_sources_lemmy.py**

`LemmySource.__init__` takes `client: Any` and assigns `client or httpx.Client(...)`, so `source._client` is `Any | httpx.Client` — and `httpx.Client` has no `urls`. Reading the attribute off the stub directly keeps its real type.

Replace:

```python
    source = LemmySource(
        instance="https://sh.itjust.works/",
        client=StubClient({("Hot", 1): [_view("a1", "T")]}),
    )
    source.fetch(limit=1)
    assert source._client.urls[0] == "https://sh.itjust.works/api/v3/post/list"
```

with:

```python
    client = StubClient({("Hot", 1): [_view("a1", "T")]})
    source = LemmySource(instance="https://sh.itjust.works/", client=client)
    source.fetch(limit=1)
    assert client.urls[0] == "https://sh.itjust.works/api/v3/post/list"
```

- [ ] **Step 6: Verify the whole repository is clean**

Run: `uv run ty check`
Expected: `All checks passed!`

This is the milestone the whole plan exists for. If any diagnostic remains, fix it at its root cause before continuing — do not suppress it to reach a green tree.

- [ ] **Step 7: Verify no behaviour changed**

Run: `uv run pytest -q`
Expected: `243 passed`.

- [ ] **Step 8: Verify the full Definition of Done**

Run: `uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest -q`
Expected: all four pass. This is the first moment the tree satisfies the gate that later tasks enforce.

- [ ] **Step 9: Commit**

```bash
git add tests/test_llm_ollama.py tests/test_store.py tests/test_sources_composite.py tests/test_sources_lemmy.py
git commit -m "test: narrow types at the remaining ty diagnostic sites"
```

---

### Task 5: Point the editor at the pinned binaries

**Files:**
- Create: `.vscode/settings.json`
- Create: `.vscode/extensions.json`

**Interfaces:**
- Consumes: the `ty` dev dependency from Task 1
- Produces: nothing consumed by later tasks

- [ ] **Step 1: Create the extension recommendations**

Create `.vscode/extensions.json`:

```json
{
  "recommendations": [
    "charliermarsh.ruff",
    "astral-sh.ty"
  ]
}
```

- [ ] **Step 2: Create the workspace settings**

Create `.vscode/settings.json`:

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

`typeCheckingMode: "off"` silences Pylance's *type* diagnostics only. Per Pylance's own bundled description it still reports "invalid syntax, unresolved imports, undefined variables", and completions, hover, go-to-definition and rename are unaffected. The setting's scope is `"resource"`, so this applies to this workspace alone.

`importStrategy: "fromEnvironment"` is the setting that makes parity real: each extension runs the binary from the project environment — the version in `uv.lock` — rather than the copy bundled in the extension.

- [ ] **Step 3: Validate both files are well-formed JSON**

Run: `python -c "import json; json.load(open('.vscode/settings.json')); json.load(open('.vscode/extensions.json')); print('ok')"`
Expected: `ok`

- [ ] **Step 4: Verify editor and CLI agree** (manual, requires VSCode)

Install both recommended extensions when VSCode prompts. Reload the window. Open `zeitgeist/media/render.py`.

Expected: no squiggles on lines 85, 96, 97, 102, 103, or 112. Those were Pylance false positives — the loop at line 78 is `range(64, 11, -2)`, which always runs, so the variables are always bound. The Problems panel should now match `uv run ty check` exactly.

If VSCode is unavailable in this environment, record the step as deferred and note it for the user rather than marking it done.

- [ ] **Step 5: Commit**

```bash
git add .vscode/settings.json .vscode/extensions.json
git commit -m "chore: run ruff and ty in the editor from the locked environment"
```

---

### Task 6: Document the Definition of Done

**Files:**
- Create: `CLAUDE.md`

**Interfaces:**
- Consumes: the four commands from Global Constraints
- Produces: the prose the Stop hook in Task 7 enforces mechanically

- [ ] **Step 1: Create CLAUDE.md**

Write exactly this content (the outer fence is four backticks so the inner
`bash` block survives — write the file with the inner three-backtick fences
intact and the outer four-backtick fence removed):

````markdown
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
````

- [ ] **Step 2: Verify the file reads correctly**

Run: `cat CLAUDE.md`
Expected: the file starts with `# Zeitgeist Actualiser` and contains exactly one fenced `bash` block holding the four commands. It must NOT start or end with a stray ```` ```markdown ```` fence — that fence delimits the plan, not the file.

- [ ] **Step 3: Confirm the documented commands actually pass**

Run: `uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest -q`
Expected: all four pass. Documentation naming a failing command would be worse than none.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: add CLAUDE.md with the definition of done"
```

---

### Task 7: Enforce the gate with a Stop hook

**Files:**
- Create: `.claude/settings.json`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: the four commands documented in Task 6
- Produces: nothing consumed by later tasks

- [ ] **Step 1: Add the worktree exclusion to .gitignore**

`.claude/worktrees/` is currently excluded only via `.git/info/exclude`, which is local to this clone and never shared. Committing `.claude/settings.json` means every other clone would otherwise see worktree directories as untracked noise.

Append to `.gitignore`:

```
.claude/worktrees/
```

- [ ] **Step 2: Create the Stop hook**

Create `.claude/settings.json`:

```json
{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "shell": "bash",
            "timeout": 300,
            "statusMessage": "Checking lint, format, types, tests",
            "command": "uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest -q || { echo 'Definition of Done failed. Fix the failures above before completing this task.' >&2; exit 2; }"
          }
        ]
      }
    ]
  }
}
```

Three details matter here:

`Stop` takes no `matcher` — it is not a tool event, so the entry has only a `hooks` array.

Exit code **2** is the blocking exit code; stderr is fed back to the model. A bare non-zero exit from ruff or pytest reports an error without necessarily blocking, so the `|| { ...; exit 2; }` wrapper is what converts any failure into a block.

`"shell": "bash"` is explicit because the command chains with `&&`, which Windows PowerShell 5.1 does not support. Without it, a contributor on Windows without Git Bash would get a parser error rather than a check.

- [ ] **Step 3: Validate the JSON and schema in one shot**

Run:

```bash
jq -e '.hooks.Stop[] | .hooks[] | select(.type == "command") | .command' .claude/settings.json
```

Expected: exit 0, and the command string is printed. Exit 5 means malformed JSON or wrong nesting. A broken `settings.json` silently disables every setting in the file, so do not proceed past a failure here.

- [ ] **Step 4: Pipe-test the raw command**

Run:

```bash
echo '{}' | bash -c "uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest -q"
```

Expected: exits 0 on the current clean tree. This proves the command itself works before trusting the hook wiring.

- [ ] **Step 5: Prove the hook blocks on a red tree**

Stop hooks fire outside the current turn, so this requires a restart. `.claude/` had no settings file when this session started, which means the settings watcher is not watching it yet — the hook will not load until Claude Code is restarted.

Tell the user:

> The Stop hook is written but will not load until you restart Claude Code. After restarting, I can verify it blocks.

After the restart, introduce a deliberate type error — add `q: int = "wrong"` at the end of `zeitgeist/pipeline.py` — and attempt to complete a trivial task.

Expected: completion is blocked and the failure message appears.
Then revert: `git checkout zeitgeist/pipeline.py`

An unverified hook is worse than no hook — it grants false confidence. If the restart is not possible in this environment, mark this step explicitly deferred rather than done.

- [ ] **Step 6: Commit**

```bash
git add .claude/settings.json .gitignore
git commit -m "chore: block task completion on a failing definition of done"
```

---

### Task 8: Add GitHub Actions CI

**Files:**
- Create: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: the four commands documented in Task 6; `uv.lock` from Task 1
- Produces: nothing consumed by later tasks

- [ ] **Step 1: Create the workflow**

Create `.github/workflows/ci.yml`:

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:

concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true

jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: astral-sh/setup-uv@v6
        with:
          enable-cache: true

      # --locked fails rather than silently relocking when uv.lock has
      # drifted from pyproject.toml. That is what makes the pinned pre-1.0
      # ty version a real guarantee: CI runs the editor's build, or it fails.
      - run: uv sync --locked

      - run: uv run ruff check .
      - run: uv run ruff format --check .
      - run: uv run ty check
      - run: uv run pytest
```

`uv` reads `.python-version` and provisions Python 3.14, so no `setup-python` step is needed. Every check runs through `uv run`, so CI executes the locked binaries rather than separately installed copies that could drift.

No secrets are configured because none are needed: `tests/conftest.py` strips every environment variable `Settings` reads, so a bare runner with no `.env` is the cleanest case rather than a broken one.

Runner is `ubuntu-latest`. Development happens on Windows, so Linux is the platform signal local work cannot provide.

- [ ] **Step 2: Validate the YAML parses**

Run: `python -c "import yaml,sys; yaml.safe_load(open('.github/workflows/ci.yml')); print('ok')"`
Expected: `ok`

If PyYAML is unavailable, run `uv run --with pyyaml python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml')); print('ok')"` instead.

- [ ] **Step 3: Confirm the lockfile guard works**

This proves `--locked` will actually catch drift rather than passing silently.

```bash
cp pyproject.toml /tmp/pyproject.backup
printf '\n[tool.zzz_drift_probe]\nx = 1\n' >> pyproject.toml
```

Run: `uv sync --locked`

Expected: a non-zero exit complaining the lockfile is out of date. A clean pass would mean the guard is inert.

Then restore:

```bash
cp /tmp/pyproject.backup pyproject.toml
uv sync --locked
```

Expected: succeeds, and `git status --short` shows `pyproject.toml` unmodified.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: run lint, format, type, and test checks on push and PR"
```

- [ ] **Step 5: Push and confirm CI goes green**

```bash
git push -u origin claude/pylance-type-errors-29f938
```

Then: `gh run watch` (or `gh run list --limit 3`)
Expected: the `check` job succeeds.

- [ ] **Step 6: Prove CI can go red**

A workflow never observed failing has not been shown to check anything.

```bash
printf '\nq: int = "wrong"\n' >> zeitgeist/pipeline.py
git add zeitgeist/pipeline.py
git commit -m "test: deliberate type error to verify CI fails"
git push
```

Then: `gh run watch`
Expected: the run fails at the `uv run ty check` step.

- [ ] **Step 7: Revert the deliberate failure**

```bash
git revert --no-edit HEAD
git push
```

Then: `gh run watch`
Expected: green again. Confirm `uv run ty check` passes locally too.

---

## Completion

After Task 8, verify the whole thing end to end from a cold environment:

```bash
rm -rf .venv
uv sync --locked
uv run ruff check . && uv run ruff format --check . && uv run ty check && uv run pytest -q
```

Expected: `243 passed`, and every check clean.

Then use superpowers:finishing-a-development-branch to decide how to integrate.

**Known deferrals to report to the user:**
- The Stop hook requires a Claude Code restart before it loads (Task 7, Step 5)
- Editor parity needs both VSCode extensions installed manually (Task 5, Step 4)
