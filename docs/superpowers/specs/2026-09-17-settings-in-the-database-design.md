# Settings in the database

Configuration lives in two places today: a `settings` table holding seven
tunable fields, and a `.env` file holding the rest — including the
Anthropic API key, the LLM provider and model, and the source selection.
This design moves everything into the database, deletes `.env`, and makes
the distinction the split was obscuring — global settings versus per-run
settings — explicit in the field declarations themselves.

## What is wrong with the split

`Settings` is a `pydantic-settings` `BaseSettings` with a five-layer
precedence chain: constructor arguments, environment variables, the
`settings` table, `.env`, then field defaults. `SettingsTableSource` slots
the table into that chain.

Three problems follow.

**The layering is invisible and leaks into every consumer.** A value read
off `app.state.settings` is frozen at startup, so a setting changed in the
browser does not reach code that reads that object. Two endpoints have
already been fixed for this separately, each with its own workaround and
its own paragraph of docstring: `read_settings` builds a fresh `Settings()`
rather than reading `app.state.settings`, and `read_options` calls
`resolve_settings(app_settings, {})` for the same reason. `resolve_settings`
itself exists largely to *exclude* run-settable fields from the snapshot so
they re-resolve through the chain. The mechanism is correct and the
comments explaining it are good, but a reader has to hold five layers in
mind to see why any of it is there.

**The taxonomy is real but undeclared.** Two frozensets, in two modules,
hand-maintained against a field list in a third: `WRITABLE_KEYS` in
`zeitgeist/settings_source.py` names the seven fields the settings screen
may write, and `RUN_OVERRIDE_KEYS` in `zeitgeist/runner.py` is that set
plus `llm_provider`, `llm_model`, `sources` and `topic_count`. Nothing
connects either to `config.py`, so a new field is silently unscoped and a
removed one leaves a dangling key.

**The bootstrap is circular, and worked around by hand.** The table source
cannot ask `Settings` where the database is — that is the object being
constructed. So `settings_source.py` carries `_db_path()` and
`_dotenv_value()`: a hand-rolled single-key `.env` parser, with a docstring
explaining why a real dotenv parser would be machinery to import for a
partition on `=`. The parser is justified given the constraint. The
constraint is what this design removes.

A fourth cost is borne by the test suite. `tests/conftest.py` strips nineteen
environment variables before every test and repoints `DB_PATH` into
`tmp_path`, because `Settings(_env_file=None)` disables `.env` but not
`os.environ`, and because a real `data/zeitgeist.db` left by a local run
would otherwise feed its tuned rows into every `Settings()` the suite
builds. Hermeticity is enforced by a fixture rather than guaranteed by the
design.

## Decisions

These were settled in brainstorming and the rest of the document follows
from them.

1. **The database is the only source.** No environment layer, no `.env`.
2. **`data/zeitgeist.db` is a constant.** Not a setting, not an environment
   variable, not overridable. Opinionated on purpose. `create_app(db_path=...)`
   remains as a test seam, the same concession the unscoped fields get.
3. **One database file.** Settings share the run database and share its
   fate: bumping `SCHEMA_VERSION` still means deleting the file, and now
   that costs the API key too. Accepted rather than mitigated with a second
   file or a settings-only migration path.
4. **Only changeable fields become settings.** Fields nobody would edit are
   demoted rather than given a row and a widget.
5. **New run keeps its four cards.** The tunables are set globally and
   apply to runs started afterwards. The API keeps accepting all ten
   per-run keys as overrides.

## Scope: three buckets

The scope is declared on the field, in `config.py`, next to the comment
explaining what the field does:

```python
llm_provider: Literal["anthropic", "ollama"] = Field(
    "anthropic", json_schema_extra={"scope": "run"}
)
anthropic_api_key: str = Field(
    "", json_schema_extra={"scope": "global", "secret": True}
)
templates_dir: Path = PACKAGE_ROOT / "media" / "templates"  # no scope
```

`GLOBAL_KEYS` and `RUN_KEYS` derive from `Settings.model_fields` at import
time. `WRITABLE_KEYS` and `RUN_OVERRIDE_KEYS` are deleted. A field with no
`scope` is in neither set, so it cannot be written through the API and
cannot be named as a per-run override — the refusal is the default, and a
new field has to opt in to being settable rather than be remembered into
two frozensets in two other modules.

| Scope | Fields |
| --- | --- |
| `run` | `llm_provider`, `llm_model`, `sources`, `topic_count`, `bluesky_trend_limit`, `bluesky_posts_per_trend`, `meme_potential_weight`, `phrase_min_authors`, `distil_char_budget`, `distil_concurrency` |
| `global` | `anthropic_api_key`, `ollama_host`, `bluesky_fetch_concurrency`, `font_path` |
| none | `output_dir`, `templates_dir`, `bluesky_api_base`, `wikipedia_project`, `wikipedia_contact`, `lemmy_instance`, `lemmy_include_nsfw` |

A `run` field has one stored value, which is the default every new run
starts from, and a run may override it for itself. A `global` field has one
stored value and no override. An unscoped field is not stored at all.

**Demoted does not mean module constant.** Every unscoped field stays a
`Settings` field with a constant default, because every one of them is
constructed in tests: `templates_dir` in eight places, pointed at a fixture
library; `output_dir` in nine, pointed inside `tmp_path`; the five
platform-endpoint fields at test doubles, which is what their existing
comments already say they exist for. They are absent from the database,
from the settings screen and from per-run overrides, and settable only by
construction. `db_path` is the one field that becomes a true constant,
because `create_app(db_path=...)` gives tests a lever the others have no
equivalent for.

**`bluesky_fetch_concurrency` moves from per-run to global**, and that is
the one reclassification rather than a straight port. It is currently in
`WRITABLE_KEYS` but has no field on `RunConfig`, so a resume cannot replay
it — the one tunable a resume does not freeze, documented in
`RunConfig.as_overrides` and mirrored in
`web/src/features/newrun/frozen.ts`. It describes the machine and the
network rather than a choice about a run. Calling it global makes the
asymmetry disappear instead of needing two comments to explain it, and makes
the ten keys `RunConfig.as_overrides` emits exactly `RUN_KEYS`.

## Loading

`Settings` stops being a `BaseSettings` and becomes a plain
`pydantic.BaseModel` — the same fields, validators and comments.
`settings_customise_sources` goes with the base class, and
`zeitgeist/settings_source.py` is deleted entire: the table source, the
`_db_path()` bootstrap, the hand-rolled `_dotenv_value()` parser and
`WRITABLE_KEYS`.

Loading becomes one function, in `config.py`:

```python
def load_settings(store: Store) -> Settings:
    """Every scoped field's stored value; unstored fields take their
    default."""
    return Settings(**store.get_settings())
```

**A stored value that fails validation raises.** `SettingsTableSource._load`
currently swallows every `sqlite3.Error` on the reasoning that "Settings
failing to load would be a worse outcome than ignoring overrides." That was
true when `.env` held the real configuration and the table was an overlay
on top of it. Once the table *is* the configuration, silently substituting
a default for a value someone deliberately set is the mystery-bug outcome —
a run quietly using `distil_concurrency` 4 because the stored 0 failed
`ge=1`. It fails at startup instead, naming the key, the way
`StoreSchemaError` already does for a stale schema. Writes are validated
before they land (below), so the only way to reach this state is a
hand-edited database.

A key in the table that is not a `Settings` field is ignored rather than
raising: that is what a field removed in a later version leaves behind, and
it is not a corrupt value.

## Precedence

`resolve_settings` becomes a three-layer merge, and moves to `config.py`
beside `load_settings` — it is a configuration concern that `runner.py` and
`generation.py` both consume, not a runner concern:

```python
def resolve_settings(
    store: Store, base: Settings, overrides: dict[str, str]
) -> Settings:
    """Settings for one unit of work: base, then what the store holds, then
    this request's per-run overrides. Highest precedence last."""
    return Settings(**(base.model_dump() | store.get_settings() | overrides))
```

Three layers rather than five, merged in one visible expression rather than
assembled by a framework hook.

This is a fix as well as a simplification. The store wins over `base` for
every field it holds, so a value changed in the browser reaches the next
run and the next on-demand generation without either endpoint's workaround:
`read_settings` and `read_options` both call `load_settings(store)` or
`resolve_settings(store, ...)` directly, and the paragraphs explaining why
they must not read `app.state.settings` go away. It also closes the same
staleness hole for *global* fields, which no workaround covered — changing
the API key mid-process previously left every consumer on the startup
snapshot.

`base` survives for exactly one reason: it is where tests inject the
unscoped fields, and it is what carries a programmatic `Settings` the API
was constructed with. In production it is loaded from the same store it is
then merged under, so it contributes only defaults.

Per-run overrides are still validated by construction, not by
`model_copy`, so `"9"` arrives as an `int` and an invalid one raises here.
`RunService.enqueue` still rejects any override outside `RUN_KEYS` before a
run id is issued.

## Bootstrap

`DB_PATH = Path("data") / "zeitgeist.db"` is exported from `store.py`.

`create_app` takes the path rather than reading it off `Settings`, and
loads settings itself when none are passed:

```python
def create_app(
    settings: Settings | None = None,
    *,
    db_path: Path = DB_PATH,
    execute: ExecuteFn | None = None,
    generate: GenerateFn | None = None,
) -> FastAPI:
```

It already opens the store and calls `init_schema()` before anything else,
so that is where settings can first be read. `serve.py` calls `create_app()`
with no arguments on both its paths, and `_app()` — the factory uvicorn's
reloader re-invokes — does the same.

`Settings.db_path` is deleted. The two worker-thread call sites that used it
open their own connection from `store.path`, the read-only property that
already exists for exactly this purpose: `RunService`'s `worker_store`
default, and `GenerationService._run_job`. The latter currently reads
`job.settings.db_path` with a docstring explaining that the job's own
settings are preferred over the service's snapshot; that reasoning applies
to settings, not to the database location, which is now the same for
everyone.

## Storage

The `settings` table is unchanged — `key TEXT PRIMARY KEY`, `value TEXT NOT
NULL`, `updated_at TEXT NOT NULL`. Only the set of keys it may hold
broadens, from seven tunables to the fourteen scoped fields.

**`SCHEMA_VERSION` stays 6.** No DDL changes, so nothing forces a delete and
no run history is lost to this change. An existing database is valid as it
stands: it holds whatever tunable rows the settings screen wrote, and every
other field falls to its default.

`Store.get_settings`, `set_setting` and `clear_setting` keep their
signatures. `get_settings` no longer filters by `WRITABLE_KEYS` — that
filter belonged to the pydantic source, and `load_settings` now ignores
unknown keys itself.

The API key is stored in plaintext, at the same trust level `.env` held it
at; `data/` is gitignored. Encrypting it against a key that would have to
sit beside it on the same disk would be theatre.

## API

**`GET /api/settings`** returns every `global` and `run` field.
`SettingField` changes shape:

```python
SettingSource = Literal["settings", "default"]

class SettingField(BaseModel):
    key: str
    value: str | float | int | bool | None
    scope: Literal["global", "run"]
    source: SettingSource
    secret: bool
```

`SettingSource` collapses from four values to two: `environment` and
`dotenv` name layers that no longer exist. `value` widens from `float | int`
because the set now includes a provider name, a model name and a host URL.

**A secret field never reports its value.** `anthropic_api_key` comes back
with `secret: true` and `value: null` always, while `source` still
distinguishes a stored key from an unset one — enough for the screen to
render SET or NOT SET, and to offer replace and clear. The key does not
leave the server in any response, which is the stance
`ConfigOptions.anthropic_key_present` already takes, preserved rather than
relaxed now that the key is settable from the browser.

**`PUT /api/settings`** keeps its request shape and its all-or-nothing
validation: a candidate `Settings` is constructed from the merge before
anything is written, so a request naming one good field and one bad one
writes neither. It now accepts `GLOBAL_KEYS | RUN_KEYS` and rejects
anything else with the 400 it already raises. An empty string still clears
the row; its meaning changes from "fall back to `.env`" to "revert to the
field default", which for `anthropic_api_key` means no key.

**`GET /api/config/options`** is unchanged in shape. `defaults` is keyed by
`RUN_KEYS` — the same ten keys as today's `RUN_OVERRIDE_KEYS`, since
`bluesky_fetch_concurrency` leaves and nothing joins.
`anthropic_key_present` stays and resolves from the store.

**`POST /api/runs`** is unchanged. Overrides are validated against
`RUN_KEYS`.

## Screens

### Settings

The screen grows a second section, because with `.env` gone `llm_provider`,
`llm_model`, `sources` and `topic_count` have no other home and would
otherwise be pinned at their defaults for good.

- **Global** — API key, Ollama host, fetch concurrency, font path.
- **Defaults for new runs** — provider, model, platform and meme count,
  then the Fan-out, Ranking and Distillation cards unchanged.

The first four of those are already built, as `ModelCard`, `PlatformCard`
and `CountCard` under `features/newrun/`. They move to `features/config/`
and both screens import them, rather than the settings screen growing a
second rendering of the same four choices that must be kept in step with
the first. `frozen.ts` stays with New run: it is about replaying a
`RunConfig`, not about rendering a choice.

The API key row is its own control rather than a `SettingRow`: a password
input, a SET or NOT SET chip driven by `source`, and a clear action. It has
no current value to show and no draft to compare, which is the entire
premise `SettingRow` is built on.

`changedValues` switches on the held value's type — numeric comparison for
numbers, preserving the reason it is numeric today (a reformatted `"0.30"`
must not count as a change over a stored `0.3`), string comparison
otherwise. **Reset to .env** becomes **Reset to defaults**. `SOURCE_LABELS`
loses its `environment` and `dotenv` entries. The header's "the seven
fields a run can be tuned with" is rewritten.

### New run

Unchanged. Four cards seeded from the stored defaults, overriding for that
run only — which is what the web UI design already describes: "defaults come
from settings · changes apply to this run only".

The first-run state matters more than it did, because a fresh database has
no API key where `.env` previously had one. `anthropic_key_present` already
exists on `ConfigOptions` for this; the screen's handling of it carries over
unchanged and simply becomes load-bearing.

## Testing

**The hermeticity fixture is deleted.** All of `_clean_settings_env`: the
nineteen-name `_SETTINGS_ENV_VARS` tuple, the `DB_PATH` repointing into
`tmp_path`, and the docstring explaining why an ambient file is as much a
threat as an ambient variable. With no environment layer and no `.env`,
there is nothing ambient left to strip. Hermeticity stops being enforced
per-test and becomes a property of the design — which is the clearest
single signal that the consolidation worked.

`tests/api_factory.py` stops reading `os.environ["DB_PATH"]` and passes
`db_path` through `create_app`. The 36 `_env_file=None` arguments across the
suite go with `BaseSettings`; the 42 `Settings(...)` constructions keep
working unchanged otherwise, since a plain `BaseModel` takes the same
keyword arguments.

`tests/test_settings_source.py` is deleted, with whatever survives the
deletion of its subject absorbed into `tests/test_config.py`.

New coverage:

- `load_settings` round-trips every scoped field through the store,
  including types the table stringifies (`bool`, `float`, `Path`, the
  `sources` CSV).
- A stored value that fails validation raises at load, naming the key; a
  stored key that is not a `Settings` field is ignored.
- `resolve_settings` precedence: the store beats `base`, an override beats
  the store, and an unscoped field survives from `base` untouched.
- A value written through `PUT /api/settings` is used by a run started
  afterwards — the staleness class that produced two separate endpoint
  fixes, pinned against the mechanism rather than the workaround.
- `GLOBAL_KEYS` and `RUN_KEYS` derive from `Settings.model_fields`, so a
  field added without a scope appears in neither and a scoped one appears
  in exactly one. This is what replaces the drift risk between the two
  frozensets, so it is asserted against the live model rather than against
  a hardcoded list.
- `RUN_KEYS` and the keys `RunConfig.as_overrides` emits are the same set,
  which is only true once `bluesky_fetch_concurrency` is global.
  `template_ids` is excluded on both sides: `RunRequest` carries it as its
  own field rather than as an override.
- `PUT` rejects an unscoped key, and rejects a global key named as a
  per-run override.
- `anthropic_api_key` appears in no response body: not in
  `GET /api/settings`, not in `GET /api/config/options`, not in a run's
  frozen config.

## Migration

One paragraph in the README: start the server, open Settings, paste your
key. No schema bump, so an existing `data/zeitgeist.db` keeps its run
history and its tuned rows; everything that lived in `.env` reverts to its
default until re-entered. A one-shot `.env` importer was considered and
rejected — it would be used once, and would leave a confusing state where
the file is present but inert.

## Documentation

- `.env.example` is deleted.
- README loses the `copy .env.example .env` step and every `VARIABLE`-shaped
  reference in the Sources, local-model and web UI prose, which is rewritten
  to name settings-screen fields.
- CLAUDE.md's "Tests are hermetic: `tests/conftest.py` strips every
  environment variable `Settings` reads" is rewritten: hermeticity now
  follows from there being no ambient source.
- `docs/superpowers/specs/2026-09-02-web-ui-design.md`'s **Settings storage**
  section is superseded; a pointer to this document is added there rather
  than editing the historical design.
- `web/openapi.json` and `web/src/api/schema.ts` regenerate. The Definition
  of Done gates both.
