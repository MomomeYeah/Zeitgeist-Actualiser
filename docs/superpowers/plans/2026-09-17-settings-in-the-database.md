# Settings in the Database Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move every piece of configuration into the SQLite `settings` table, delete `.env` and the five-layer `pydantic-settings` precedence chain, and declare the global-versus-per-run distinction on the `Settings` fields themselves.

**Architecture:** `Settings` stops being a `BaseSettings` and becomes a plain `pydantic.BaseModel`, loaded by an explicit `load_settings(store)`. Scope is declared per field via `json_schema_extra={"scope": ...}`, from which `GLOBAL_KEYS` and `RUN_KEYS` derive — replacing the two hand-maintained frozensets in `settings_source.py` and `runner.py`. The database path becomes the constant `DB_PATH` in `store.py`, passed to `create_app` rather than read off `Settings`.

**Tech Stack:** Python 3.14, pydantic v2, FastAPI, SQLite via `sqlite3`, pytest, ruff, ty; React 19 + TypeScript + Vitest + React Testing Library on the web side.

**Spec:** `docs/superpowers/specs/2026-09-17-settings-in-the-database-design.md`

## Global Constraints

- **Definition of Done.** No task is complete, and nothing is committed, until all seven pass:
  ```
  uv run ruff check .
  uv run ruff format --check .
  uv run ty check
  uv run pytest
  npm --prefix web run lint
  npm --prefix web run typecheck
  npm --prefix web test
  ```
- `npm --prefix web run typecheck` regenerates `web/src/api/schema.ts` from `web/openapi.json` and fails if the checked-in file differs. `uv run pytest` asserts `web/openapi.json` still matches the FastAPI app. Any task changing an API model must regenerate both — run `uv run python scripts/dump_openapi.py` then `npm --prefix web run typecheck`, and commit both files.
- Python 3.14: use PEP 695 generics (`def f[T: Bound](...)`), never `typing.TypeVar`.
- ruff rules `E, F, I, UP, B, SIM`, line length 88.
- No blanket `# type: ignore`. A narrow suppression needs a comment explaining why.
- `SCHEMA_VERSION` stays **6**. No task in this plan changes DDL. If you find yourself wanting to, stop and re-read the spec's "Storage" section.
- Tests use a real `Store` on `tmp_path`, never a mock or a fake. The suite's hermeticity comes from the design after Task 3, not from a fixture.
- Commit after every task, once the seven gates pass.

---

### Task 1: The database path becomes a constant

Removes `Settings.db_path` and hands the path to `create_app` instead. Done first because it shrinks `Settings` before Task 2 starts classifying its fields, and because `SettingsTableSource` never read `Settings.db_path` anyway — its docstring says so — meaning nothing about the current precedence chain changes here.

**Files:**
- Modify: `zeitgeist/store.py` (add `DB_PATH` beside the `Store` class)
- Modify: `zeitgeist/config.py:94` (delete `db_path`)
- Modify: `zeitgeist/api/app.py:46-65` (`create_app` signature and store construction)
- Modify: `zeitgeist/runner.py:259` (`_worker_store` default)
- Modify: `zeitgeist/generation.py:489` (`_run_job`'s own connection)
- Modify: `zeitgeist/serve.py:31,58` (both `create_app` calls)
- Modify: `tests/api_factory.py:120-170,269` (`api_settings` and `seeded_client`)
- Modify: `tests/test_api_app.py:17`, `tests/test_openapi_schema.py:21`
- Test: `tests/test_api_app.py`, `tests/test_runner.py`, `tests/test_generation.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `zeitgeist.store.DB_PATH: Path` — the value `Path("data") / "zeitgeist.db"`.
  - `create_app(settings: Settings, *, db_path: Path = DB_PATH, execute: ExecuteFn | None = None, generate: GenerateFn | None = None) -> FastAPI`
  - `Settings` no longer has a `db_path` attribute. Any later task reading a database location reads `store.path` or `DB_PATH`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_api_app.py`:

```python
def test_create_app_opens_its_database_at_the_path_it_is_given(tmp_path):
    """The path is a parameter of the factory, not a field of Settings.

    `nested/` does not exist beforehand: `Store.__init__` creates the parent,
    and a test that pre-created it would pass even if the path were ignored
    in favour of the `data/` default.
    """
    path = tmp_path / "nested" / "z.db"
    app = create_app(Settings(_env_file=None), db_path=path)
    try:
        assert app.state.store.path == path
        assert path.is_file()
    finally:
        app.state.store.close()


def test_create_app_defaults_to_the_database_the_constant_names(tmp_path, monkeypatch):
    """No `db_path` argument, so the factory must resolve `DB_PATH` itself.

    `DB_PATH` is relative, so `chdir` keeps this hermetic while still
    exercising the real default. Asserted on the file that appears rather
    than on the signature object: a factory that declared the default and
    then opened somewhere else leaves `tmp_path/data/zeitgeist.db` missing,
    which introspecting `inspect.signature` would never notice.
    """
    monkeypatch.chdir(tmp_path)

    app = create_app(Settings(_env_file=None))
    try:
        assert app.state.store.path == DB_PATH
        assert (tmp_path / "data" / "zeitgeist.db").is_file()
    finally:
        app.state.store.close()
```

Add to `tests/test_runner.py`:

```python
def test_the_worker_opens_its_own_connection_to_the_services_database(tmp_path):
    """RunService's worker thread needs a connection of its own — sqlite3
    handles are thread-bound — but it must be to the same file, which is now
    read from the store rather than from Settings.

    Asserts on a second, distinct Store object pointed at the same path, not
    merely on `is not`: a default that returned `self._store` would be a
    thread-safety bug that an identity check alone would let through.
    """
    store = Store(tmp_path / "z.db")
    store.init_schema()
    service = RunService(Settings(_env_file=None), store)
    worker = service._worker_store()
    try:
        assert worker is not store
        assert worker.path == store.path
    finally:
        worker.close()
        store.close()
```

Add to `tests/test_generation.py`:

Uses the helpers already in `tests/test_generation.py` — `_store`, `_service`,
`_seed_topics`, `TEMPLATE`, `SLOTS` — and `make_topic` from
`tests/run_factory.py`. `submit` takes `(run_id, topic_id, request)`, and it
refuses before queuing if the analyse checkpoint is missing, so the seeding is
load-bearing rather than decorative.

```python
def test_a_generation_job_opens_the_services_database(tmp_path):
    """`_run_job` used to find its database through `job.settings.db_path`.
    With that field gone it must reach the same file through the service's
    own store. Pinned on the path the worker's `Store` actually carries, so
    a job opening a different file fails on substance.
    """
    store = _store(tmp_path)
    _seed_topics(store, make_topic("airport-cat"))
    opened: list[Path] = []

    def generate(job: GenerationJob, job_store: Store) -> None:
        opened.append(job_store.path)

    service = _service(tmp_path, store, generate=generate)
    service.submit(
        "run-1",
        "airport-cat",
        ManualGeneration(template_id=TEMPLATE, caption_slots=SLOTS),
    )
    service.shutdown()

    assert opened == [store.path]
    store.close()
```

- [ ] **Step 2: Run them to verify they fail**

```bash
uv run pytest tests/test_api_app.py tests/test_runner.py tests/test_generation.py -v
```

Expected: `TypeError: create_app() got an unexpected keyword argument 'db_path'` from all three files.

- [ ] **Step 3: Add the constant**

In `zeitgeist/store.py`, above the `Store` class:

```python
# Where the database lives. A constant rather than a setting: it is the one
# thing that cannot be read out of the database it names, and a tool with one
# database has nothing to gain from making its location configurable. Tests
# reach past it through `create_app(db_path=...)`.
DB_PATH = Path("data") / "zeitgeist.db"
```

Add `"DB_PATH"` to `__all__` at `zeitgeist/store.py:31`.

- [ ] **Step 4: Thread the path through the factory**

In `zeitgeist/api/app.py`, change the signature and the store construction:

```python
def create_app(
    settings: Settings,
    *,
    db_path: Path = DB_PATH,
    execute: ExecuteFn | None = None,
    generate: GenerateFn | None = None,
) -> FastAPI:
```

```python
    store = Store(db_path, check_same_thread=False)
```

Add `from pathlib import Path` and `from zeitgeist.store import DB_PATH, Store`. Update the module docstring's first paragraph: the factory takes the path rather than reading it off `Settings`, and the hermeticity sentence about `conftest` is no longer the reason — it is now that the path is an explicit argument.

- [ ] **Step 5: Point the two worker connections at `store.path`**

`zeitgeist/runner.py:259`:

```python
        self._worker_store = worker_store or (lambda: Store(store.path))
```

`zeitgeist/generation.py:489`:

```python
        store = Store(self._store.path)
```

Replace that method's `job.settings rather than self._settings` paragraph: the job's settings still win for *settings*, but the database location is the same for every job and now comes from the service's own store.

- [ ] **Step 6: Delete the field and fix the callers**

Delete `db_path: Path = Path("data") / "zeitgeist.db"` from `zeitgeist/config.py:94`.

`zeitgeist/serve.py`: both `create_app(Settings())` calls stay as they are — the default argument covers them.

`tests/api_factory.py`: drop `"db_path"` from the `kwargs` dict and the `os` import if it is now unused; rewrite the docstring paragraph about `DB_PATH` to say the path is passed to `create_app`. In `seeded_client`:

```python
    db_path = Path(os.environ["DB_PATH"])
    store = Store(db_path)
    store.init_schema()
    for spec in runs:
        seed_run(store, spec)
    store.close()
    client = TestClient(
        create_app(settings, db_path=db_path, execute=execute, generate=generate)
    )
```

`DB_PATH` is still read from the environment here because `conftest`'s fixture still sets it and `SettingsTableSource` still reads it. Task 3 removes both together.

`tests/test_api_app.py:17` and `tests/test_openapi_schema.py:21`: move `db_path=...` out of the `Settings(...)` call and into `create_app(..., db_path=...)`.

- [ ] **Step 7: Run the full suite**

```bash
uv run pytest
```

Expected: PASS. Then the other six gates.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "Make the database path a constant rather than a setting"
```

---

### Task 2: Declare scope on the fields

Purely additive: the new key sets exist but nothing consumes them yet, so the suite stays green and a reviewer can judge the classification on its own.

**Files:**
- Modify: `zeitgeist/config.py` (14 field declarations, plus `GLOBAL_KEYS` / `RUN_KEYS`)
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: Task 1's `Settings` without `db_path`.
- Produces:
  - `zeitgeist.config.GLOBAL_KEYS: frozenset[str]`
  - `zeitgeist.config.RUN_KEYS: frozenset[str]`
  - `zeitgeist.config.SECRET_KEYS: frozenset[str]`
  - A field is scoped by `Field(..., json_schema_extra={"scope": "global" | "run"})`, and marked secret by adding `"secret": True` to that same dict.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_config.py`:

```python
from zeitgeist.config import GLOBAL_KEYS, RUN_KEYS, SECRET_KEYS, Settings


def test_run_keys_are_exactly_the_fields_a_run_may_set():
    assert RUN_KEYS == frozenset(
        {
            "llm_provider",
            "llm_model",
            "sources",
            "topic_count",
            "bluesky_trend_limit",
            "bluesky_posts_per_trend",
            "meme_potential_weight",
            "phrase_min_authors",
            "distil_char_budget",
            "distil_concurrency",
        }
    )


def test_global_keys_are_exactly_the_fields_set_once_for_the_install():
    assert GLOBAL_KEYS == frozenset(
        {
            "anthropic_api_key",
            "ollama_host",
            "bluesky_fetch_concurrency",
            "font_path",
        }
    )


def test_the_unscoped_fields_are_the_ones_no_screen_offers():
    """Derived from the live model, so a field added without a scope shows up
    here as a failure rather than being silently unsettable."""
    unscoped = frozenset(Settings.model_fields) - GLOBAL_KEYS - RUN_KEYS
    assert unscoped == frozenset(
        {
            "output_dir",
            "templates_dir",
            "bluesky_api_base",
            "wikipedia_project",
            "wikipedia_contact",
            "lemmy_instance",
            "lemmy_include_nsfw",
        }
    )


def test_the_api_key_is_the_only_secret_and_it_is_global():
    assert SECRET_KEYS == frozenset({"anthropic_api_key"})
    assert SECRET_KEYS <= GLOBAL_KEYS


def test_run_keys_match_the_keys_a_frozen_config_replays():
    """`RunConfig.as_overrides` is what a resume reposts, and `enqueue` will
    validate those keys against `RUN_KEYS` from Task 4 on. If the two sets
    ever differ, a resume of a perfectly ordinary run is refused as naming a
    key no run may set — so they are pinned equal here, against a real frozen
    config rather than a literal list.
    """
    from tests.run_factory import make_run_config

    assert frozenset(make_run_config().as_overrides()) == RUN_KEYS
```

- [ ] **Step 2: Run them to verify they fail**

```bash
uv run pytest tests/test_config.py -v
```

Expected: `ImportError: cannot import name 'GLOBAL_KEYS' from 'zeitgeist.config'`.

- [ ] **Step 3: Annotate the fields**

In `zeitgeist/config.py`, add `json_schema_extra` to the fourteen scoped fields. Every existing comment stays exactly where it is — the annotation goes on the declaration, the prose above it is untouched. Fields that already use `Field(...)` gain the argument; fields that do not are wrapped. For example:

```python
    anthropic_api_key: str = Field(
        "", json_schema_extra={"scope": "global", "secret": True}
    )
    llm_provider: Literal["anthropic", "ollama"] = Field(
        "anthropic", json_schema_extra={"scope": "run"}
    )
    ollama_host: str = Field(
        "http://127.0.0.1:11434", json_schema_extra={"scope": "global"}
    )
    bluesky_fetch_concurrency: int = Field(
        default=8, ge=1, json_schema_extra={"scope": "global"}
    )
    sources: Annotated[list[str], NoDecode] = Field(
        ["bluesky"], json_schema_extra={"scope": "run"}
    )
    meme_potential_weight: float = Field(
        default=0.3, ge=0.0, le=1.0, json_schema_extra={"scope": "run"}
    )
    font_path: Path | None = Field(None, json_schema_extra={"scope": "global"})
```

Apply the same treatment to `llm_model`, `topic_count`, `bluesky_trend_limit`, `bluesky_posts_per_trend`, `phrase_min_authors`, `distil_char_budget` and `distil_concurrency`, all `scope: "run"`.

Leave `templates_dir`, `output_dir`, `bluesky_api_base`, `wikipedia_project`, `wikipedia_contact`, `lemmy_instance` and `lemmy_include_nsfw` exactly as they are. Add one comment above that group:

```python
    # No scope: absent from the database, from the settings screen and from
    # per-run overrides. Each is either a constant nobody would edit or a
    # seam a test points at a double — which is the only thing that still
    # sets them, by construction.
```

- [ ] **Step 4: Derive the key sets**

Below the class, in `zeitgeist/config.py`:

```python
def _keys_with(scope: str) -> frozenset[str]:
    """The fields declaring `scope`, read off the model itself.

    Two hand-maintained frozensets in two other modules are what this
    replaces — `WRITABLE_KEYS` in settings_source.py and `RUN_OVERRIDE_KEYS`
    in runner.py — neither of which anything connected to the field list they
    were describing. Derived here, a new field is unscoped by default and a
    deleted one takes its key with it.
    """
    return frozenset(
        name
        for name, field in Settings.model_fields.items()
        if isinstance(field.json_schema_extra, dict)
        and field.json_schema_extra.get("scope") == scope
    )


GLOBAL_KEYS = _keys_with("global")
RUN_KEYS = _keys_with("run")
SECRET_KEYS = frozenset(
    name
    for name, field in Settings.model_fields.items()
    if isinstance(field.json_schema_extra, dict)
    and field.json_schema_extra.get("secret") is True
)
```

- [ ] **Step 5: Run the tests**

```bash
uv run pytest tests/test_config.py -v
```

Expected: PASS. `test_run_keys_match_the_keys_a_frozen_config_replays` is the one to watch — it passes only because `bluesky_fetch_concurrency` is global. Then the other six gates.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "Declare global and per-run scope on the Settings fields"
```

---

### Task 3: One source of truth

The atomic change. `BaseSettings` goes, `.env` goes, `settings_source.py` goes, and the `conftest` hermeticity fixture goes with them — all at once, because each of the four is what makes the others safe to remove.

**Files:**
- Modify: `zeitgeist/config.py` (base class, `load_settings`, `resolve_settings`)
- Delete: `zeitgeist/settings_source.py`
- Delete: `tests/test_settings_source.py`
- Delete: `.env.example`
- Modify: `zeitgeist/runner.py` (drop `RUN_OVERRIDE_KEYS` and `resolve_settings`, import from config)
- Modify: `zeitgeist/generation.py:332`, `zeitgeist/api/options.py:30`, `zeitgeist/api/settings.py`
- Modify: `tests/conftest.py` (delete `_clean_settings_env`)
- Modify: `tests/api_factory.py`, and every test passing `_env_file=None`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: Task 2's `GLOBAL_KEYS`, `RUN_KEYS`.
- Produces:
  - `zeitgeist.config.load_settings(store: Store) -> Settings`
  - `zeitgeist.config.resolve_settings(store: Store, base: Settings, overrides: dict[str, str]) -> Settings`
  - `zeitgeist.config.StoredSettingError(ValueError)` — raised when a stored value fails validation.
  - `zeitgeist.runner.RUN_OVERRIDE_KEYS` and `zeitgeist.runner.resolve_settings` no longer exist. Import `RUN_KEYS` and `resolve_settings` from `zeitgeist.config`.
  - `Settings(...)` still takes the same keyword arguments; `_env_file` is no longer among them.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_config.py`:

```python
import pytest

from zeitgeist.config import (
    RUN_KEYS,
    Settings,
    StoredSettingError,
    load_settings,
    resolve_settings,
)
from zeitgeist.store import Store


@pytest.fixture
def store(tmp_path):
    store = Store(tmp_path / "z.db")
    store.init_schema()
    yield store
    store.close()


def test_load_settings_reads_every_scoped_field_back_in_its_real_type(store):
    """The table is all TEXT, so each field's declared type is what turns a
    row back into a usable value. Covers one of each shape that needs
    coercing — int, float, the CSV list, a Path and a plain string — because
    a loader that returned the raw strings would still satisfy an int-only
    assertion under Python's truthiness.
    """
    store.set_setting("topic_count", "9")
    store.set_setting("meme_potential_weight", "0.75")
    store.set_setting("sources", "bluesky")
    store.set_setting("font_path", "C:/Windows/Fonts/impact.ttf")
    store.set_setting("llm_model", "qwen3.5")

    settings = load_settings(store)

    assert settings.topic_count == 9
    assert settings.meme_potential_weight == 0.75
    assert settings.sources == ["bluesky"]
    assert settings.font_path == Path("C:/Windows/Fonts/impact.ttf")
    assert settings.llm_model == "qwen3.5"


def test_only_the_stored_fields_move_off_their_defaults(store):
    """The contrast, not the defaulting.

    `Settings(**{})` returning declared defaults is pydantic's behaviour, not
    this project's, and asserting a bare `== 24000` would be a test of the
    framework that fails the day someone legitimately retunes the default.
    What is ours is the merge: exactly the stored keys move, and a field
    beside them in the same load is untouched. A `load_settings` that
    splatted the whole table over every field, or that dropped the table
    entirely, breaks one half or the other.
    """
    before = load_settings(store)
    store.set_setting("distil_char_budget", "8000")

    after = load_settings(store)

    assert (before.distil_char_budget, after.distil_char_budget) == (24000, 8000)
    assert after.distil_concurrency == before.distil_concurrency


def test_a_stored_value_that_fails_validation_raises_and_names_the_key(store):
    """`distil_concurrency` is `ge=1`; a stored 0 would make every
    distillation block forever. Loading must refuse rather than quietly
    substitute the default of 4, which is the mystery-bug outcome the spec
    rejects. The key has to appear in the message, because the only way to
    fix it is to know which row to edit.
    """
    store.set_setting("distil_concurrency", "0")

    with pytest.raises(StoredSettingError, match="distil_concurrency"):
        load_settings(store)


def test_a_stored_key_that_is_no_longer_a_field_is_ignored(store):
    """What a field removed in a later version leaves behind. Not a corrupt
    value, so not a refusal to start."""
    store.set_setting("retired_knob", "whatever")

    assert load_settings(store).topic_count == 5


def test_the_store_beats_the_base_snapshot(store):
    """The staleness class this replaces: `app.state.settings` is frozen at
    startup, so a value saved in the browser has to outrank it or it never
    reaches the next run.
    """
    base = Settings(topic_count=5)
    store.set_setting("topic_count", "9")

    assert resolve_settings(store, base, {}).topic_count == 9


def test_a_per_run_override_beats_the_store(store):
    store.set_setting("topic_count", "9")

    assert resolve_settings(store, Settings(), {"topic_count": "2"}).topic_count == 2


def test_an_unscoped_field_survives_from_the_base_untouched(store):
    """`output_dir` is never stored, so the only thing that can carry a
    test's tmp_path through `resolve_settings` is `base`. A merge that
    rebuilt Settings from the store alone would silently reset it to
    `output/` and start writing PNGs into the working tree.
    """
    base = Settings(output_dir=Path("/tmp/somewhere"))
    store.set_setting("topic_count", "9")

    resolved = resolve_settings(store, base, {})

    assert resolved.output_dir == Path("/tmp/somewhere")
    assert resolved.topic_count == 9


def test_an_invalid_override_raises_rather_than_being_coerced_silently(store):
    """`model_copy(update=...)` would leave `"nonsense"` sitting in an int
    field with no error raised anywhere. Construction is what makes a bad
    override a refusal on the request thread.

    Narrowed to `ValidationError` and to the offending key: plain
    `ValueError` is also what `_check_sources` raises, so the wide form
    would be satisfied by a failure that had nothing to do with the
    override.
    """
    with pytest.raises(ValidationError) as caught:
        resolve_settings(store, Settings(), {"topic_count": "nonsense"})

    assert "topic_count" in str(caught.value)


def test_settings_no_longer_reads_the_environment(monkeypatch):
    """The whole point of the change, asserted directly. `monkeypatch.setenv`
    rather than a stripped fixture: this must fail if anyone reintroduces an
    env layer, and there is no longer a conftest fixture hiding the effect.
    """
    monkeypatch.setenv("TOPIC_COUNT", "42")

    assert Settings().topic_count == 5


def test_settings_no_longer_reads_a_dotenv_file(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("TOPIC_COUNT=42\n", encoding="utf-8")

    assert Settings().topic_count == 5
```

- [ ] **Step 2: Run them to verify they fail**

```bash
uv run pytest tests/test_config.py -v
```

Expected: `ImportError: cannot import name 'load_settings'`, and the two environment tests failing with `42 == 5` because `BaseSettings` is still reading them.

- [ ] **Step 3: Make `Settings` a plain model**

In `zeitgeist/config.py`, replace the imports and the base class:

```python
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Settings(BaseModel):
    # extra="ignore" so a row for a field this version no longer declares is
    # skipped rather than raising. A typo'd key cannot reach here: the API
    # validates against GLOBAL_KEYS | RUN_KEYS before writing, and `enqueue`
    # validates overrides against RUN_KEYS before a run id is issued.
    model_config = ConfigDict(extra="ignore")
```

Delete `settings_customise_sources` entirely, along with the `pydantic_settings` and `zeitgeist.settings_source` imports. `NoDecode` goes with them — it exists only because pydantic-settings JSON-decodes list-typed env values before validators run, which is no longer a thing that happens. `sources` becomes:

```python
    sources: list[str] = Field(["bluesky"], json_schema_extra={"scope": "run"})
```

Keep `_split_csv`: `resolve_settings` still receives `sources` as a CSV string from a per-run override and from the table.

Update the module docstring: configuration is read from the `settings` table, and there is no environment or `.env` layer.

- [ ] **Step 4: Add the loader and the resolver**

At the end of `zeitgeist/config.py`:

```python
class StoredSettingError(ValueError):
    """A row in the `settings` table does not validate.

    `SettingsTableSource` used to swallow this, on the reasoning that failing
    to load was worse than ignoring an override. That held while `.env` was
    the real configuration and the table was an overlay on it. Now that the
    table *is* the configuration, substituting a default for a value someone
    deliberately set is the outcome nobody can diagnose — a run quietly using
    `distil_concurrency` 4 because the stored 0 failed `ge=1`. Writes are
    validated before they land, so the only way to reach this is a
    hand-edited database.
    """


def load_settings(store: Store) -> Settings:
    """Every stored value; every unstored field at its declared default."""
    try:
        return Settings(**store.get_settings())
    except ValidationError as exc:
        raise StoredSettingError(
            "Stored settings are invalid: "
            + "; ".join(
                f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
                for error in exc.errors()
            )
        ) from exc


def resolve_settings(
    store: Store, base: Settings, overrides: dict[str, str]
) -> Settings:
    """Settings for one unit of work: `base`, then what the store holds, then
    this request's per-run overrides. Highest precedence last.

    Three layers rather than the five `settings_customise_sources` assembled,
    and merged in one expression a reader can see rather than by a framework
    hook.

    The store outranks `base` deliberately. `base` is `app.state.settings`,
    frozen when the app was built, so a value saved on the settings screen
    would otherwise never reach a run started afterwards — the bug
    `read_settings` and `read_options` each carried their own workaround for.
    `base` survives to supply the unscoped fields, which are never stored and
    which a test sets by construction.

    Constructing rather than `model_copy(update=...)`, which bypasses
    validation entirely: `"9"` would stay the string `"9"` for `topic_count`
    with no error raised anywhere.
    """
    return Settings(**(base.model_dump() | store.get_settings() | overrides))
```

Import `ValidationError` from pydantic and `Store` from `zeitgeist.store`. `store.py` imports nothing from `config.py`, so this direction adds no cycle — check with `uv run python -c "import zeitgeist.config"`.

- [ ] **Step 5: Delete the source module and move the callers**

```bash
git rm zeitgeist/settings_source.py tests/test_settings_source.py .env.example
```

In `zeitgeist/runner.py`: delete `RUN_OVERRIDE_KEYS`, delete the whole `resolve_settings` function, and change the imports to `from zeitgeist.config import RUN_KEYS, Settings, resolve_settings`. `enqueue` becomes:

```python
        unknown = sorted(set(request.overrides) - RUN_KEYS)
```

`_build_settings` becomes:

```python
    def _build_settings(self, overrides: dict[str, str]) -> Settings:
        """This service's own settings, layered with the request's
        overrides. See `resolve_settings`."""
        return resolve_settings(self._store, self._settings, overrides)
```

`zeitgeist/generation.py:332`: `resolve_settings(self._store, self._settings, {})`, importing from `zeitgeist.config`.

`zeitgeist/api/options.py`: import `RUN_KEYS` and `resolve_settings` from `zeitgeist.config`, add `store: Store = Depends(get_store)` to `read_options`, call `resolve_settings(store, app_settings, {})`, and key `defaults` by `RUN_KEYS`. The comment about `app.state.settings` being frozen stays — it is still why this resolves rather than reads.

`zeitgeist/api/settings.py`: delete the `_source` function's `environment` and `dotenv` branches and the `os` and `_dotenv_value` imports. Task 4 rewrites this module properly; here, do the minimum that keeps it importing — `_source` returns `"settings"` if the key is stored, else `"default"` — and change `Settings()` in `read_settings` to `load_settings(store)`.

- [ ] **Step 6: Delete the hermeticity fixture**

In `tests/conftest.py`, delete `_SETTINGS_ENV_VARS` and the entire `_clean_settings_env` fixture. Leave `_close_seeded_clients`, `sample_items` and `fixture_now`.

In `tests/api_factory.py`: `seeded_client` no longer reads `os.environ["DB_PATH"]`. It chooses the path itself:

```python
    db_path = tmp_path / "zeitgeist.db"
```

and passes it to both the seeding `Store` and `create_app`. Rewrite `api_settings`'s docstring: the first paragraph about `DB_PATH` and `SettingsTableSource` describes machinery that no longer exists — replace it with a sentence saying the factory supplies only the unscoped fields a test needs to own, because everything else now comes from the store.

- [ ] **Step 7: Strip `_env_file` across the suite**

```bash
grep -rln '_env_file' tests/
```

Remove the argument from all 36 occurrences. It is a `BaseSettings` keyword and a plain `BaseModel` rejects it. Most are `Settings(_env_file=None)` becoming `Settings()`.

- [ ] **Step 8: Run the full suite**

```bash
uv run pytest
```

Expect failures in `tests/test_runner.py` around lines 828-856, which construct a `Store` from `os.environ["DB_PATH"]` to exercise the old table source, and in `tests/test_api_settings.py:210`. Rewrite each to build its own `Store` on `tmp_path` and pass it to `resolve_settings` — the behaviour they assert (the table beats the base, an override beats the table) is exactly what Task 3's new tests cover, so delete any that have become duplicates rather than keeping two spellings of one assertion.

Then the other six gates. `uv run python scripts/dump_openapi.py` is not needed yet — no API model has changed shape.

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "Read settings only from the database"
```

---

### Task 4: The settings API over both scopes

**Files:**
- Modify: `zeitgeist/api/schemas.py:31-50` (`SettingSource`, `SettingField`)
- Modify: `zeitgeist/api/settings.py` (both endpoints)
- Modify: `web/openapi.json`, `web/src/api/schema.ts` (regenerated)
- Test: `tests/test_api_settings.py`, `tests/test_api_options.py`

**Interfaces:**
- Consumes: `GLOBAL_KEYS`, `RUN_KEYS`, `SECRET_KEYS`, `load_settings`.
- Produces:
  - `SettingField(key: str, value: str | float | int | bool | None, scope: Literal["global", "run"], source: Literal["settings", "default"], secret: bool)`
  - `GET /api/settings` returns one entry per key in `GLOBAL_KEYS | RUN_KEYS`, sorted by key.
  - `PUT /api/settings` accepts those same keys; `""` clears a row.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_api_settings.py`:

```python
def test_the_read_returns_every_scoped_field_in_key_order(tmp_path):
    """The fourteen keys written out rather than `GLOBAL_KEYS | RUN_KEYS`:
    the endpoint builds its list from that same union, so comparing against
    it asserts only that a set equals itself, and a field that silently lost
    its scope annotation would vanish from both sides at once.

    Compared as a list, because the contract says sorted by key.
    """
    client = seeded_client(tmp_path)

    fields = client.get("/api/settings").json()

    assert [field["key"] for field in fields] == [
        "anthropic_api_key",
        "bluesky_fetch_concurrency",
        "bluesky_posts_per_trend",
        "bluesky_trend_limit",
        "distil_char_budget",
        "distil_concurrency",
        "font_path",
        "llm_model",
        "llm_provider",
        "meme_potential_weight",
        "ollama_host",
        "phrase_min_authors",
        "sources",
        "topic_count",
    ]


def test_each_field_reports_the_scope_it_was_declared_with(tmp_path):
    client = seeded_client(tmp_path)

    by_key = {field["key"]: field for field in client.get("/api/settings").json()}

    assert by_key["anthropic_api_key"]["scope"] == "global"
    assert by_key["topic_count"]["scope"] == "run"


def test_a_stored_value_is_reported_as_stored_and_an_unstored_one_as_default(
    tmp_path,
):
    """Both halves in one test because `source` is only meaningful as a
    contrast: an implementation returning "settings" unconditionally would
    pass either assertion alone."""
    client = seeded_client(tmp_path)
    client.put("/api/settings", json={"values": {"topic_count": "9"}})

    by_key = {field["key"]: field for field in client.get("/api/settings").json()}

    assert by_key["topic_count"] == {
        "key": "topic_count",
        "value": 9,
        "scope": "run",
        "source": "settings",
        "secret": False,
    }
    assert by_key["distil_char_budget"]["source"] == "default"


def test_the_api_key_never_comes_back_in_any_form(tmp_path):
    """Asserted over the whole serialised body, not just the key's own row:
    the value must not reach the client through `defaults`, an error message
    or anything else either."""
    client = seeded_client(tmp_path)
    client.put(
        "/api/settings", json={"values": {"anthropic_api_key": "sk-ant-secret"}}
    )

    settings_body = client.get("/api/settings").text
    options_body = client.get("/api/config/options").text

    assert "sk-ant-secret" not in settings_body
    assert "sk-ant-secret" not in options_body


def test_the_api_key_reports_that_it_is_set_without_reporting_what_it_is(
    tmp_path,
):
    client = seeded_client(tmp_path)
    client.put(
        "/api/settings", json={"values": {"anthropic_api_key": "sk-ant-secret"}}
    )

    by_key = {field["key"]: field for field in client.get("/api/settings").json()}

    assert by_key["anthropic_api_key"] == {
        "key": "anthropic_api_key",
        "value": None,
        "scope": "global",
        "source": "settings",
        "secret": True,
    }


def test_clearing_the_api_key_leaves_the_run_screen_saying_no_key_is_present(
    tmp_path,
):
    """The two endpoints have to agree: a cleared key must not leave New run
    still advertising one."""
    client = seeded_client(tmp_path)
    client.put("/api/settings", json={"values": {"anthropic_api_key": "sk-ant-x"}})
    assert client.get("/api/config/options").json()["anthropic_key_present"] is True

    client.put("/api/settings", json={"values": {"anthropic_api_key": ""}})

    assert client.get("/api/config/options").json()["anthropic_key_present"] is False


def test_a_path_valued_field_round_trips_as_the_string_the_put_accepts(tmp_path):
    """`font_path` is a `Path` on the model and has no JSON form: returned
    raw it fails `SettingField`'s union outright, and returned as anything
    but the string the `PUT` takes back it cannot be re-saved. Nothing else
    in this task stores a Path, so without this the `isinstance(value, Path)`
    branch of `_display` can be deleted with the suite staying green.

    A bare filename rather than an absolute one, because `str(Path(...))`
    rewrites separators per platform and a Windows run would turn
    "C:/Windows/..." into backslashes. "impact.ttf" is its own `str`
    everywhere, so the expected value stays a hand-derived literal.
    """
    client = seeded_client(tmp_path)

    response = client.put(
        "/api/settings", json={"values": {"font_path": "impact.ttf"}}
    )

    assert response.status_code == 200
    by_key = {field["key"]: field for field in client.get("/api/settings").json()}
    assert by_key["font_path"] == {
        "key": "font_path",
        "value": "impact.ttf",
        "scope": "global",
        "source": "settings",
        "secret": False,
    }
    # The other declared type with no JSON form: joined, not returned as a
    # list, because `SettingsUpdate` takes it back as a CSV string.
    assert by_key["sources"]["value"] == "bluesky"


def test_a_global_field_is_writable_here(tmp_path):
    client = seeded_client(tmp_path)

    response = client.put(
        "/api/settings", json={"values": {"ollama_host": "http://10.0.0.2:11434"}}
    )

    assert response.status_code == 200
    by_key = {field["key"]: field for field in response.json()}
    assert by_key["ollama_host"]["value"] == "http://10.0.0.2:11434"


def test_an_unscoped_field_is_refused(tmp_path):
    client = seeded_client(tmp_path)

    response = client.put(
        "/api/settings", json={"values": {"templates_dir": "/tmp/mine"}}
    )

    assert response.status_code == 400
    assert "templates_dir" in response.json()["detail"]


def test_a_rejected_request_writes_none_of_its_fields(tmp_path):
    """All-or-nothing, pinned on the side effect rather than the status: a
    handler that validated after writing would still answer 400 here while
    having already saved the good field."""
    client = seeded_client(tmp_path)

    client.put(
        "/api/settings",
        json={"values": {"topic_count": "7", "meme_potential_weight": "2.0"}},
    )

    by_key = {field["key"]: field for field in client.get("/api/settings").json()}
    assert by_key["topic_count"]["source"] == "default"
    assert by_key["topic_count"]["value"] == 5


def test_a_global_field_is_not_accepted_as_a_per_run_override(tmp_path):
    """`bluesky_fetch_concurrency` is global now: a run may not set it.

    `execute` is supplied even though nothing should reach it. Under the
    very mutation this test names — `enqueue` keyed on `GLOBAL_KEYS |
    RUN_KEYS` rather than `RUN_KEYS` — the request is accepted, and without
    a seam the real pipeline would start against the live Bluesky API on
    whoever's machine is running the suite. The empty `started` list is the
    second half of the assertion, and the detail check keeps an unrelated
    400 from satisfying this.
    """
    started: list[str] = []

    def execute(settings, request, store, observer, token):
        started.append(request.run_id or "")

    client = seeded_client(tmp_path, execute=execute)

    response = client.post(
        "/api/runs", json={"overrides": {"bluesky_fetch_concurrency": "2"}}
    )

    assert response.status_code == 400
    assert "bluesky_fetch_concurrency" in response.json()["detail"]
    assert started == []


def test_a_value_saved_here_is_used_by_a_run_started_afterwards(tmp_path):
    """The staleness class that produced two separate endpoint workarounds,
    pinned against the mechanism: what the worker actually froze, not what a
    second GET reported.
    """
    frozen: list[int] = []

    def execute(settings, request, store, observer, token):
        frozen.append(settings.topic_count)

    client = seeded_client(tmp_path, execute=execute)
    client.put("/api/settings", json={"values": {"topic_count": "9"}})

    client.post("/api/runs", json={})
    wait_for_idle(client)  # existing helper in tests/test_api_control.py

    assert frozen == [9]
```

- [ ] **Step 2: Run them to verify they fail**

```bash
uv run pytest tests/test_api_settings.py -v
```

Expected: `KeyError: 'scope'` and assertion failures on the seven-key set.

- [ ] **Step 3: Reshape the response model**

In `zeitgeist/api/schemas.py`:

```python
SettingSource = Literal["settings", "default"]
SettingScope = Literal["global", "run"]


class SettingField(BaseModel):
    """One settable field, its effective value, and where that value came
    from.

    `value` is `None` for a secret field, always — `anthropic_api_key` is
    written through this endpoint and never read back out of it. `source`
    still distinguishes a stored key from an unset one, which is all the
    screen needs to render SET or NOT SET.
    """

    model_config = STRICT

    key: str
    value: str | float | int | bool | None
    scope: SettingScope
    source: SettingSource
    secret: bool
```

- [ ] **Step 4: Rewrite the endpoints**

`zeitgeist/api/settings.py`. `_source` collapses to two branches; add a display helper and widen the key set:

```python
SETTABLE_KEYS = GLOBAL_KEYS | RUN_KEYS


def _scope(key: str) -> SettingScope:
    return "global" if key in GLOBAL_KEYS else "run"


def _display(value: object) -> str | float | int | bool | None:
    """The field's value as JSON the client can round-trip back as a string.

    `Path` and `list` are the two declared types that have no JSON form the
    `PUT` would accept back: a bare `Path` is not serialisable at all, and a
    list would come back as a list where `SettingsUpdate` wants the CSV
    string `_split_csv` reads.
    """
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, list):
        return ",".join(str(part) for part in value)
    return value
```

`read_settings` builds from `load_settings(store)` and the store's own rows:

```python
@router.get("", response_model=list[SettingField])
def read_settings(store: Store = Depends(get_store)) -> list[SettingField]:
    """Built from `load_settings`, not from `app.state.settings`, which is
    frozen when the app is built — so a `PUT` is visible to the very next
    `GET`."""
    stored = store.get_settings()
    settings = load_settings(store)
    return [
        SettingField(
            key=key,
            value=None if key in SECRET_KEYS else _display(getattr(settings, key)),
            scope=_scope(key),
            source="settings" if key in stored else "default",
            secret=key in SECRET_KEYS,
        )
        for key in sorted(SETTABLE_KEYS)
    ]
```

`write_settings` changes only its allowlist and its validation base:

```python
    unknown = sorted(set(body.values) - SETTABLE_KEYS)
```

```python
    if proposed:
        try:
            Settings(**(load_settings(store).model_dump() | proposed))
        except ValidationError as exc:
            raise HTTPException(
                status_code=400, detail=_validation_detail(exc)
            ) from exc
```

Update the module docstring and `clear_setting`'s comment: an empty value now reverts to the field default, not to `.env`. Update `Store.clear_setting`'s docstring in `zeitgeist/store.py` for the same reason.

- [ ] **Step 5: Regenerate the contract**

```bash
uv run python scripts/dump_openapi.py
npm --prefix web run typecheck
```

Commit both `web/openapi.json` and `web/src/api/schema.ts`.

- [ ] **Step 6: Delete the resume caveat**

`bluesky_fetch_concurrency` is global now, so `RunConfig.as_overrides`'s final paragraph in `zeitgeist/records.py:100-103` describes a state that no longer exists. Delete it. Task 6 deletes its mirror in `frozen.ts`.

- [ ] **Step 7: Run the tests**

```bash
uv run pytest tests/test_api_settings.py tests/test_api_options.py tests/test_records.py -v
```

Expected: PASS. Then the full suite and the other six gates.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "Serve every settable field from the settings endpoints"
```

---

### Task 5: Move the shared run cards

A pure move with no behaviour change, so a reviewer can see it is a move. Task 6 is what consumes it.

**Files:**
- Move: `web/src/features/newrun/{ModelCard,PlatformCard,CountCard}.tsx` and their `.module.css` → `web/src/features/config/`
- Modify: `web/src/features/newrun/NewRunPage.tsx:10-13` (imports)
- Modify: any test importing those paths

**Interfaces:**
- Produces, unchanged in shape, from `@/features/config/`:
  - `ModelCard({ models, provider, model, keyPresent, onProvider, onModel })`
  - `PlatformCard({ platforms, selected, onSelect })`
  - `CountCard({ count, trendLimit, onCount })`

- [ ] **Step 1: Move the files**

```bash
mkdir -p web/src/features/config
git mv web/src/features/newrun/ModelCard.tsx web/src/features/config/
git mv web/src/features/newrun/ModelCard.module.css web/src/features/config/
git mv web/src/features/newrun/PlatformCard.tsx web/src/features/config/
git mv web/src/features/newrun/PlatformCard.module.css web/src/features/config/
git mv web/src/features/newrun/CountCard.tsx web/src/features/config/
git mv web/src/features/newrun/CountCard.module.css web/src/features/config/
```

`TemplateCard` stays in `newrun/` — the settings screen has no template default to offer, and `frozen.ts` stays with it.

- [ ] **Step 2: Fix the imports**

In `web/src/features/newrun/NewRunPage.tsx`, change the three imports to `@/features/config/...`. Then:

```bash
grep -rn 'features/newrun/\(Model\|Platform\|Count\)Card' web/src
```

Expected: no matches.

- [ ] **Step 3: Update `ModelCard`'s key line**

`ModelCard` says `"key present · ANTHROPIC_API_KEY"` and `"ANTHROPIC_API_KEY is not set · this run would fail"`. There is no such variable any more. Change them to `"key present · set in Settings"` and `"No API key · set one in Settings · this run would fail"`.

- [ ] **Step 4: Run the web gates**

```bash
npm --prefix web run lint
npm --prefix web run typecheck
npm --prefix web test
```

Expected: PASS. Fix any test asserting the old copy — the assertion is correct to update, because the variable it names no longer exists.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "Move the shared run cards into features/config"
```

---

### Task 6: The settings screen over both scopes

**Files:**
- Modify: `web/src/api/types.ts` (add `SettingScope`)
- Modify: `web/src/test/factories.ts:422-446` (`makeSettingField`, `makeSettingFields`)
- Modify: `web/src/features/settings/fields.ts` (two sections, new field specs, `SOURCE_LABELS`)
- Modify: `web/src/features/settings/SettingRow.tsx` (drop the environment branch, type-aware input)
- Create: `web/src/features/settings/SecretRow.tsx` and `SecretRow.module.css`
- Modify: `web/src/features/settings/SettingsPage.tsx` (two sections, `changedValues`, button copy)
- Modify: `web/src/features/newrun/frozen.ts` (delete the fetch-concurrency caveat)
- Test: `web/src/features/settings/SettingsPage.test.tsx`

**Interfaces:**
- Consumes: Task 4's `SettingField` with `scope` and `secret`; Task 5's cards at `@/features/config/`.
- Produces: `SecretRow({ field, draft, onDraft, onClear })` where `field: SettingField`, `draft: string | undefined`, `onDraft: (value: string) => void` and `onClear: () => void`.

- [ ] **Step 0: Widen the fixtures**

`SettingField` gained `scope` and `secret` in Task 4, `value` widened to
`string | number | boolean | null`, and the response went from seven keys to
fourteen. `web/src/test/factories.ts` still emits seven entries of
`{key, value, source}` with a `number`-only value, so every test below would
otherwise render against a payload the server can no longer produce — and a
screen that crashed on the real fourteen-key response, or that read `secret`,
found `undefined` and drew a `SettingRow` for the API key, would still pass.
Replace lines 422-446:

```ts
export function makeSettingField(
  options: Partial<SettingField> = {},
): SettingField {
  return {
    key: options.key ?? "phrase_min_authors",
    value: options.value ?? 3,
    scope: options.scope ?? "run",
    source: options.source ?? "default",
    secret: options.secret ?? false,
  };
}

/**
 * All fourteen, in the order `GET /api/settings` returns them: sorted by
 * key. Complete rather than trimmed to what a test reads — a screen that
 * mishandled a `null` secret, a string host or a CSV `sources` would
 * otherwise pass against a fixture that never contained one.
 */
export function makeSettingFields(
  overrides: Partial<Record<string, Partial<SettingField>>> = {},
): SettingField[] {
  const base: SettingField[] = [
    { key: "anthropic_api_key", value: null, scope: "global", source: "default", secret: true },
    { key: "bluesky_fetch_concurrency", value: 8, scope: "global", source: "default", secret: false },
    { key: "bluesky_posts_per_trend", value: 10, scope: "run", source: "default", secret: false },
    { key: "bluesky_trend_limit", value: 25, scope: "run", source: "default", secret: false },
    { key: "distil_char_budget", value: 24000, scope: "run", source: "default", secret: false },
    { key: "distil_concurrency", value: 4, scope: "run", source: "default", secret: false },
    { key: "font_path", value: null, scope: "global", source: "default", secret: false },
    { key: "llm_model", value: "claude-sonnet-5", scope: "run", source: "default", secret: false },
    { key: "llm_provider", value: "anthropic", scope: "run", source: "default", secret: false },
    { key: "meme_potential_weight", value: 0.3, scope: "run", source: "default", secret: false },
    { key: "ollama_host", value: "http://127.0.0.1:11434", scope: "global", source: "default", secret: false },
    { key: "phrase_min_authors", value: 3, scope: "run", source: "default", secret: false },
    { key: "sources", value: "bluesky", scope: "run", source: "default", secret: false },
    { key: "topic_count", value: 5, scope: "run", source: "default", secret: false },
  ];
  return base.map((field) => ({ ...field, ...(overrides[field.key] ?? {}) }));
}

export function apiKeyField(options: Partial<SettingField> = {}): SettingField {
  return makeSettingField({
    key: "anthropic_api_key",
    value: null,
    scope: "global",
    secret: true,
    ...options,
  });
}
```

- [ ] **Step 1: Write the failing tests**

In `web/src/features/settings/SettingsPage.test.tsx`. Three harness rules this
file already follows, and every test below obeys:

- The render helper is `renderWithProviders(ui, { route })` from
  `web/src/test/render.tsx`. There is no `renderWithClient`.
- `web/src/test/server.ts` registers **no default handlers**, by policy — a
  test that forgets one fails loudly on an unhandled request. So every test
  declares both `GET /api/settings` and `GET /api/config/options`, the second
  because the config cards read it.
- A `PUT` is in flight when the click returns, so every assertion on what was
  saved is wrapped in `await waitFor(...)`. A bare synchronous `expect` either
  races the request or passes vacuously.

Two local helpers carry the first two rules:

```tsx
function settingsHandler(fields: SettingField[]) {
  return [
    http.get("/api/settings", () => HttpResponse.json(fields)),
    http.get("/api/config/options", () => HttpResponse.json(makeConfigOptions())),
  ];
}

/** Every `PUT` body the screen sent, in order. */
function captureSaves(fields: SettingField[]): unknown[] {
  const saved: unknown[] = [];
  server.use(
    http.put("/api/settings", async ({ request }) => {
      saved.push(await request.json());
      return HttpResponse.json(fields);
    }),
  );
  return saved;
}
```

```tsx
it("draws global fields and run defaults under separate headings", async () => {
  server.use(...settingsHandler(makeSettingFields()));

  renderWithProviders(<SettingsPage />, { route: "/settings" });

  expect(
    await screen.findByRole("heading", { name: /global/i }),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("heading", { name: /defaults for new runs/i }),
  ).toBeInTheDocument();
});

it("shows an unset API key as not set, with no value in the document", async () => {
  server.use(...settingsHandler([apiKeyField({ source: "default" })]));

  renderWithProviders(<SettingsPage />, { route: "/settings" });

  expect(await screen.findByText(/not set/i)).toBeInTheDocument();
  expect(screen.getByLabelText("anthropic_api_key")).toHaveValue("");
});

it("sends a typed API key and does not send the untouched fields beside it", async () => {
  /* The bug this guards is the one the existing `changedValues` comment
     describes: sending every field writes a row for each, pinning values
     that were only ever defaults. */
  const user = userEvent.setup();
  const fields = makeSettingFields();
  server.use(...settingsHandler(fields));
  const saved = captureSaves(fields);

  renderWithProviders(<SettingsPage />, { route: "/settings" });

  await user.type(
    await screen.findByLabelText("anthropic_api_key"),
    "sk-ant-typed",
  );
  await user.click(screen.getByRole("button", { name: "Save" }));

  await waitFor(() =>
    expect(saved).toEqual([{ values: { anthropic_api_key: "sk-ant-typed" } }]),
  );
});

it("clears a stored API key", async () => {
  /* `changedValues` drops every empty draft, so a Clear routed through the
     draft map can never reach the wire — this is the test that says so.
     `onClear` must put the `""` into the payload by another route. */
  const user = userEvent.setup();
  const fields = [apiKeyField({ source: "settings" })];
  server.use(...settingsHandler(fields));
  const saved = captureSaves(fields);

  renderWithProviders(<SettingsPage />, { route: "/settings" });

  await user.click(await screen.findByRole("button", { name: "Clear" }));

  await waitFor(() =>
    expect(saved).toEqual([{ values: { anthropic_api_key: "" } }]),
  );
});

it("offers no Clear for a key that was never set", async () => {
  /* The negative half. A Clear rendered unconditionally would pass the test
     above while inviting a no-op click on a key there is nothing to clear. */
  server.use(...settingsHandler([apiKeyField({ source: "default" })]));

  renderWithProviders(<SettingsPage />, { route: "/settings" });

  expect(await screen.findByText(/not set/i)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Clear" })).not.toBeInTheDocument();
});

it("treats a reformatted number as unchanged but a real edit as changed", async () => {
  /* Both halves together: an implementation comparing raw strings passes
     the second assertion and fails the first, and one that never compares
     at all passes the first and fails the second. */
  const user = userEvent.setup();
  const fields = makeSettingFields();
  server.use(...settingsHandler(fields));
  const saved = captureSaves(fields);

  renderWithProviders(<SettingsPage />, { route: "/settings" });

  const input = await screen.findByLabelText("meme_potential_weight");
  await user.clear(input);
  await user.type(input, "0.30");
  expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();

  await user.clear(input);
  await user.type(input, "0.45");
  await user.click(screen.getByRole("button", { name: "Save" }));

  await waitFor(() =>
    expect(saved).toEqual([{ values: { meme_potential_weight: "0.45" } }]),
  );
});

it("compares a string field textually rather than numerically", async () => {
  /* `Number("http://...")` is NaN, so a numeric-only comparison would
     decide every host edit was unchanged and silently disable Save. */
  const user = userEvent.setup();
  const fields = makeSettingFields();
  server.use(...settingsHandler(fields));
  const saved = captureSaves(fields);

  renderWithProviders(<SettingsPage />, { route: "/settings" });

  const input = await screen.findByLabelText("ollama_host");
  await user.clear(input);
  await user.type(input, "http://10.0.0.2:11434");
  await user.click(screen.getByRole("button", { name: "Save" }));

  await waitFor(() =>
    expect(saved).toEqual([{ values: { ollama_host: "http://10.0.0.2:11434" } }]),
  );
});

it("saves the run defaults the config cards own, under their setting names", async () => {
  /* Four of the fourteen settable keys are reachable only through the cards,
     and `RunConfig` and `Settings` use different names for them —
     `top_count` against `topic_count`, `trend_limit` against
     `bluesky_trend_limit`. A card wired to the `RunConfig` vocabulary would
     `PUT` keys the endpoint rejects, so this asserts the wire format rather
     than the card's own state. */
  const user = userEvent.setup();
  const fields = makeSettingFields();
  server.use(...settingsHandler(fields));
  const saved = captureSaves(fields);

  renderWithProviders(<SettingsPage />, { route: "/settings" });

  await user.click(await screen.findByRole("button", { name: "ollama" }));
  await user.click(screen.getByRole("radio", { name: "qwen3.5:latest" }));
  await user.click(screen.getByRole("button", { name: "Save" }));

  await waitFor(() =>
    expect(saved).toEqual([
      { values: { llm_provider: "ollama", llm_model: "qwen3.5:latest" } },
    ]),
  );
});

it("seeds the cards from the stored run defaults rather than from their own defaults", async () => {
  /* A card that ignored the `GET` and started from its component default
     would show "anthropic / claude-sonnet-5" over a database saying
     otherwise, and Save would then be disabled on a screen that disagrees
     with what the next run will use. */
  server.use(
    ...settingsHandler(
      makeSettingFields({
        llm_provider: { value: "ollama", source: "settings" },
        llm_model: { value: "qwen3.5:latest", source: "settings" },
        topic_count: { value: 10, source: "settings" },
      }),
    ),
  );

  renderWithProviders(<SettingsPage />, { route: "/settings" });

  expect(await screen.findByRole("button", { name: "ollama" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  expect(screen.getByRole("radio", { name: "qwen3.5:latest" })).toHaveAttribute(
    "aria-checked",
    "true",
  );
  expect(screen.getByRole("button", { name: "10" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
});

it("resets every settable field except the API key", async () => {
  /* The keys written out, not an `every` over the values: `Object.values({})
     .every(...)` is `true`, so a Reset that sent an empty payload — or only
     the fields already drafted — would pass an `every` check while
     resetting nothing.

     Thirteen, not fourteen. `anthropic_api_key` is deliberately exempt:
     losing your key to a button labelled "Reset to defaults" is a trap, and
     the secret row's own Clear is the explicit way to do it. */
  const user = userEvent.setup();
  const fields = makeSettingFields();
  server.use(...settingsHandler(fields));
  const saved = captureSaves(fields);

  renderWithProviders(<SettingsPage />, { route: "/settings" });
  await screen.findByLabelText("phrase_min_authors");

  await user.click(screen.getByRole("button", { name: "Reset to defaults" }));

  await waitFor(() => expect(saved).toHaveLength(1));
  expect(saved[0]).toEqual({
    values: {
      bluesky_fetch_concurrency: "",
      bluesky_posts_per_trend: "",
      bluesky_trend_limit: "",
      distil_char_budget: "",
      distil_concurrency: "",
      font_path: "",
      llm_model: "",
      llm_provider: "",
      meme_potential_weight: "",
      ollama_host: "",
      phrase_min_authors: "",
      sources: "",
      topic_count: "",
    },
  });
});
```

- [ ] **Step 2: Run them to verify they fail**

```bash
npm --prefix web test -- SettingsPage
```

Expected: FAIL — no "Global" heading, no `anthropic_api_key` control.

- [ ] **Step 3: Restructure `fields.ts`**

Replace `CARDS` with two exported groups. `SettingCard` gains nothing; a new `SECTIONS` wraps them:

```ts
export interface SettingSection {
  label: string;
  blurb: string;
  cards: readonly SettingCard[];
}

export const SECTIONS: readonly SettingSection[] = [
  {
    label: "Global",
    blurb: "one value, used by everything",
    cards: [
      {
        label: "Provider",
        fields: [
          {
            key: "anthropic_api_key",
            explanation:
              "Your Anthropic key. Stored in this machine's database and never sent back to the browser — replace it or clear it, but you cannot read it here.",
          },
          {
            key: "ollama_host",
            explanation:
              "Where a local Ollama answers. 127.0.0.1 rather than localhost: IPv6-first resolution of localhost cost over two seconds on the machine this was measured on, close to the model registry's own timeout.",
          },
        ],
      },
      {
        label: "Machine",
        fields: [
          {
            key: "bluesky_fetch_concurrency",
            explanation:
              "Parallel fetches. A property of this machine and its network rather than a choice about a run, which is why it is set once here. A semaphore of zero blocks every fetch forever with no diagnostic, so the floor is one.",
          },
          {
            key: "font_path",
            explanation:
              "A .ttf for the meme text. Empty means the scalable font Pillow ships; set it to something like C:/Windows/Fonts/impact.ttf for the authentic look.",
          },
        ],
      },
    ],
  },
  {
    label: "Defaults for new runs",
    blurb: "what New run starts from · a run can override any of these",
    cards: [
      /* Fan-out, Ranking and Distillation exactly as they are today. */
    ],
  },
];

/**
 * What Reset clears: every settable key except the secret.
 *
 * The four card-driven keys are listed rather than derived, because they are
 * not `FieldSpec`s — deriving from `SECTIONS` alone would silently exempt
 * them and leave Reset doing three quarters of its job. `anthropic_api_key`
 * is exempt on purpose: losing a key to a button labelled "Reset to
 * defaults" is a trap, and `SecretRow`'s Clear is the explicit way to do it.
 */
export const RESETTABLE_KEYS: readonly string[] = [
  ...SECTIONS.flatMap((section) =>
    section.cards.flatMap((card) =>
      card.fields
        .map((field) => field.key)
        .filter((key) => key !== "anthropic_api_key"),
    ),
  ),
  "llm_provider",
  "llm_model",
  "sources",
  "topic_count",
];
```

`SOURCE_LABELS` loses two entries:

```ts
export const SOURCE_LABELS: Readonly<Record<SettingSource, string>> = {
  settings: "SET HERE",
  default: "DEFAULT",
};
```

Rewrite its doc comment: there were four because a shell variable outranked the table; there are two because nothing outranks it any more.

Provider, model, platform and meme count are rendered by the Task 5 cards inside the second section, driven by `useConfigOptions` for their option lists and saved through the same `PUT`. They are not `FieldSpec`s.

- [ ] **Step 4: Simplify `SettingRow`**

Delete `fromEnvironment`, `variable`, the `readOnly` prop, the `aria-describedby` and the whole `{fromEnvironment && ...}` block, along with the docstring paragraph about `BLUESKY_TREND_LIMIT=10`. The input's `type` follows the value:

```tsx
  const numeric = typeof field.value === "number";
```

```tsx
          type={numeric ? "number" : "text"}
          step={numeric ? "any" : undefined}
          value={draft ?? (field.value === null ? "" : String(field.value))}
```

- [ ] **Step 5: Add `SecretRow`**

```tsx
/**
 * The API key: a control with no current value to show.
 *
 * Not a `SettingRow`, whose whole premise is a draft compared against a
 * held value. The server returns `value: null` for a secret field always,
 * so there is nothing to compare and nothing to prefill — `source` is the
 * only thing that distinguishes a stored key from an unset one.
 */
export function SecretRow({
  field,
  draft,
  onDraft,
  onClear,
}: {
  field: SettingField;
  draft: string | undefined;
  onDraft: (value: string) => void;
  onClear: () => void;
}) {
  const present = field.source === "settings";
  return (
    <div className={styles.row}>
      <div className={styles.head}>
        <label className={styles.key} htmlFor={`setting-${field.key}`}>
          {field.key}
        </label>
        <span className={present ? styles.set : styles.unset}>
          {present ? "SET" : "NOT SET"}
        </span>
        <input
          id={`setting-${field.key}`}
          type="password"
          autoComplete="off"
          className={styles.input}
          placeholder={present ? "replace the stored key" : "paste a key"}
          value={draft ?? ""}
          onChange={(event) => onDraft(event.target.value)}
        />
      </div>
      {present && (
        <button type="button" className={styles.clear} onClick={onClear}>
          Clear
        </button>
      )}
    </div>
  );
}
```

- [ ] **Step 6: Rework `SettingsPage`**

`changedValues` switches on the held type:

```ts
function changedValues(
  fields: readonly SettingField[],
  drafts: Record<string, string>,
): Record<string, string> {
  const held = new Map(fields.map((field) => [field.key, field.value]));
  return Object.fromEntries(
    Object.entries(drafts).filter(([key, draft]) => {
      if (draft === "") return false;
      const current = held.get(key);
      // A secret reports `null` always, so there is nothing to compare: any
      // non-empty draft is a new key.
      if (current === null || current === undefined) return true;
      if (typeof current === "number") {
        const parsed = Number(draft);
        // Number("http://...") is NaN, which is why this branch is guarded
        // by the held type rather than by whether the draft parses.
        return Number.isFinite(parsed) && current !== parsed;
      }
      return String(current) !== draft;
    }),
  );
}
```

`onClear` must **not** write `""` into the draft map: `changedValues` filters
every empty draft, so a clear routed that way would be dropped before the
request and the button would silently do nothing at all. It calls the mutation
directly:

```ts
  function clearSecret(key: string) {
    save.mutate({ values: { [key]: "" } }, { onSuccess: () => setDrafts({}) });
  }
```

Render `SECTIONS` rather than `CARDS`, each with an `<h2>` of `section.label` and a `MetaLine` of `section.blurb`. Within a card, a field with `secret` gets a `SecretRow` and everything else a `SettingRow`. `Reset to .env` becomes `Reset to defaults` and maps over `RESETTABLE_KEYS` rather than `SETTING_KEYS`, and its comment's "so the `.env` fallback applies again" becomes "so the field default applies again". The header's `MetaLine` becomes `what every run starts from`.

- [ ] **Step 7: Delete the `frozen.ts` caveat**

The final paragraph of `frozenTunables`'s doc comment describes `bluesky_fetch_concurrency` having no `RunConfig` field. It is global now and no longer a per-run key at all, so the paragraph goes. The function body is unchanged.

- [ ] **Step 8: Run the web gates**

```bash
npm --prefix web test -- SettingsPage
npm --prefix web run lint
npm --prefix web run typecheck
npm --prefix web test
```

Expected: PASS, then the three Python gates.

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "Set global settings and run defaults from the settings screen"
```

---

### Task 7: Documentation

**Files:**
- Modify: `README.md`
- Modify: `CLAUDE.md`
- Modify: `docs/superpowers/specs/2026-09-02-web-ui-design.md:916`

- [ ] **Step 1: Rewrite the README's setup section**

Delete the `copy .env.example .env` block and the paragraph beginning "Fill in `.env`". Replace with:

```markdown
That creates `.venv/`, installs the exact versions in `uv.lock`, and fetches
the Python version named in `.python-version` if you do not have it.

Then start the server and open Settings:

```bash
uv run zeitgeist
```

Configuration lives in the database at `data/zeitgeist.db`, not in a file you
edit. The one value you must supply is your Anthropic API key, on the
Settings screen — or switch the provider to Ollama, below. Everything else
has a working default.
```

- [ ] **Step 2: Rewrite every variable reference**

```bash
grep -n '`[A-Z][A-Z_]*`' README.md
```

Every match naming a `Settings` field is now a settings-screen field. `SOURCES` becomes "the platform", `LEMMY_INSTANCE` becomes "the Lemmy instance", `BLUESKY_TREND_LIMIT` becomes `bluesky_trend_limit` (the key the screen shows), and so on. The "Using a local model" section's `.env` block becomes: set the provider to `ollama` and pick a model on the Settings screen, or on New run for one run only.

Add a short paragraph under Setup for anyone upgrading:

```markdown
Upgrading from a build that used `.env`: the file is no longer read. Your run
history and tuned values survive — the schema is unchanged — but the API key,
provider and model revert to their defaults until you re-enter them on the
Settings screen.
```

Also correct the stage list: stage 2's `PHRASE_MIN_AUTHORS` and stage 3's `TOPIC_COUNT` become `phrase_min_authors` and `topic_count`.

- [ ] **Step 3: Rewrite CLAUDE.md's hermeticity claim**

Replace:

> **pytest** runs the suite. Tests are hermetic: `tests/conftest.py` strips every environment variable `Settings` reads, so results never depend on a local `.env` or an ambient shell.

with:

> **pytest** runs the suite. Tests are hermetic by construction: `Settings` reads no environment variable and no `.env`, and every test that needs a database builds its own `Store` on `tmp_path`, so results never depend on a local install.

- [ ] **Step 4: Supersede the old storage section**

At `docs/superpowers/specs/2026-09-02-web-ui-design.md:916`, under the **Settings storage** heading, add:

```markdown
> **Superseded** by `docs/superpowers/specs/2026-09-17-settings-in-the-database-design.md`.
> The five-layer precedence chain, the `.env` fallback and the
> `pydantic-settings` source described below were removed; the database is
> now the only source. The section is kept as the record of what phase 6
> built.
```

Do not edit the section's body — it is a historical design.

- [ ] **Step 5: Verify nothing still points at a deleted file**

```bash
grep -rn '\.env' README.md CLAUDE.md zeitgeist/ tests/ web/src/ --include='*.md' --include='*.py' --include='*.ts' --include='*.tsx'
```

Expected: no match that implies the file is read. Historical references inside `docs/superpowers/specs/` are fine.

- [ ] **Step 6: Run all seven gates and commit**

```bash
git add -A
git commit -m "Document settings as database-backed"
```

---

## Self-Review

**Spec coverage.** Scope buckets → Task 2. Loading and `StoredSettingError` → Task 3. Precedence → Task 3. Bootstrap → Task 1. Storage (no schema bump, `clear_setting` docstring) → Tasks 3 and 4. API → Task 4. Settings screen → Tasks 5 and 6. New run unchanged → Task 5 touches only the key-line copy. Testing → the fixture deletion is Task 3 Step 6; every listed new test is placed. Migration → Task 7 Step 2. Documentation → Task 7. The `bluesky_fetch_concurrency` reclassification lands in Task 2 and its two stale comments are deleted in Task 4 Step 6 and Task 6 Step 7.

**Type consistency.** `resolve_settings(store, base, overrides)` has the same three-parameter order at all four call sites (Task 3 Step 5). `load_settings(store)` is one parameter everywhere. `SettingField`'s five fields are identical between the Task 4 model, the Task 4 test literals and the Task 6 `SecretRow`/`changedValues` consumers. `DB_PATH` is named the same in `store.py`, `create_app`'s default and Task 1's test.

**Gap found and closed during review.** `read_settings` returns `value` for `font_path` (a `Path`) and `sources` (a `list[str]`), neither of which is JSON-serialisable into the declared union, and a list would not round-trip through `SettingsUpdate`'s `dict[str, str]`. Task 4 Step 4 now defines `_display` for both.
