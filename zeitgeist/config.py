"""Runtime configuration, read from the `settings` table.

There is no environment layer and no `.env`: a value is either stored in the
database, supplied by the caller that constructed the object, or the field's
declared default. `load_settings` and `resolve_settings` at the bottom of
this module are the two ways anything gets one.
"""

from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

if TYPE_CHECKING:
    # Under TYPE_CHECKING because the runtime import would close a cycle:
    # `store.py` imports `records.py`, which imports `Settings` from here for
    # `RunConfig.freeze`. Python 3.14 does not evaluate annotations, so the
    # two functions below can name `Store` without it.
    from typing import Any

    from zeitgeist.store import Store

PACKAGE_ROOT = Path(__file__).parent

# Registry keys live here rather than in zeitgeist/sources/__init__.py:
# that module imports Settings, so importing it back would be a cycle.
# tests/test_sources_composite.py guards the two against drifting.
# Platforms that yield a flat item list and need clustering downstream.
# Dormant: no live pipeline stage consumes them (see the 2026-08-26 spec).
ITEM_SOURCES: tuple[str, ...] = ("lemmy", "wikipedia")
# Platforms that cluster posts into trends themselves and yield evidence.
TREND_SOURCES: tuple[str, ...] = ("bluesky",)
KNOWN_SOURCES: tuple[str, ...] = ITEM_SOURCES + TREND_SOURCES


class Settings(BaseModel):
    # extra="ignore" so a row for a field this version no longer declares is
    # skipped rather than raising. A typo'd key cannot reach here: the API
    # validates against the scoped key sets below before writing, and
    # `enqueue` validates overrides against RUN_KEYS before a run id is
    # issued.
    model_config = ConfigDict(extra="ignore")

    lemmy_instance: str = "https://lemmy.world"
    lemmy_include_nsfw: bool = False

    wikipedia_project: str = "en.wikipedia"
    wikipedia_contact: str = "https://github.com/MomomeYeah/Zeitgeist-Actualiser"

    # Exists so the host can be pointed at a mirror or a test double, not
    # because anyone is expected to change it. `public.api.bsky.app` is NOT a
    # valid substitute: it returns 403 on parts of the API.
    bluesky_api_base: str = "https://api.bsky.app"
    # 25 is the API's ceiling, not a tuning parameter: getTrends returns 400
    # above it. The other two are the real fan-out budget, which is why
    # fetch_evidence takes no single `limit` argument — one integer cannot
    # express trends-by-posts.
    bluesky_trend_limit: int = Field(25, json_schema_extra={"scope": "run"})
    bluesky_posts_per_trend: int = Field(10, json_schema_extra={"scope": "run"})
    # ge=1: a semaphore of 0 blocks every fetch forever with no diagnostic.
    bluesky_fetch_concurrency: int = Field(
        default=8, ge=1, json_schema_extra={"scope": "global"}
    )

    anthropic_api_key: str = Field(
        "", json_schema_extra={"scope": "global", "secret": True}
    )
    llm_provider: Literal["anthropic", "ollama"] = Field(
        "anthropic", json_schema_extra={"scope": "run"}
    )
    llm_model: str = Field("claude-sonnet-5", json_schema_extra={"scope": "run"})
    # 127.0.0.1, not localhost: on the machine this was measured on, httpx
    # resolves localhost to ::1 first and IPv6-first resolution cost more
    # (2.16-2.28s) than the model registry's whole 2.0s timeout, so New run's
    # options fetch showed "Loading..." for over two seconds and came close
    # to failing outright. 127.0.0.1 answered in 0.19s.
    ollama_host: str = Field(
        "http://127.0.0.1:11434", json_schema_extra={"scope": "global"}
    )

    sources: list[str] = Field(["bluesky"], json_schema_extra={"scope": "run"})
    topic_count: int = Field(5, json_schema_extra={"scope": "run"})

    # Distinct accounts a phrase needs before it counts as recurring. Below
    # this, a repeated phrase is one person or a small ring, not a zeitgeist.
    phrase_min_authors: int = Field(3, json_schema_extra={"scope": "run"})

    # Share of the ranking given to the dossier's meme_potential, the
    # rest going to trend score. Both are on [0, 1], so this is a plain
    # weighted average. At the default a strongly trending but unfunny
    # topic still outranks a mildly trending very funny one; raise it to
    # favour what will actually make a meme over what is merely loud.
    meme_potential_weight: float = Field(
        default=0.3, ge=0.0, le=1.0, json_schema_extra={"scope": "run"}
    )

    # Reply characters sent per distillation call. A single trend can yield
    # six hundred replies; a 32k-context local model truncates silently well
    # before that, so the budget is explicit rather than discovered.
    distil_char_budget: int = Field(24000, json_schema_extra={"scope": "run"})
    # Parallel distillation calls. Local Ollama serialises on one GPU, so 1-2
    # is right there; a hosted provider benefits from the default. ge=1: a
    # ThreadPoolExecutor of 0 workers blocks every distillation forever.
    distil_concurrency: int = Field(default=4, ge=1, json_schema_extra={"scope": "run"})

    # None means "use the scalable font Pillow ships"; set it to a real .ttf
    # (e.g. C:/Windows/Fonts/impact.ttf) for the authentic meme look.
    font_path: Path | None = Field(None, json_schema_extra={"scope": "global"})
    # No scope: absent from the database, from the settings screen and from
    # per-run overrides. Each is either a constant nobody would edit or a
    # seam a test points at a double — which is the only thing that still
    # sets them, by construction.
    templates_dir: Path = PACKAGE_ROOT / "media" / "templates"
    output_dir: Path = Path("output")

    @field_validator("sources", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        """`sources` arrives as one CSV string from both of the places a
        value can come from now: a `settings` row, which is TEXT, and a
        per-run override, which is a form field."""
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return value

    @model_validator(mode="after")
    def _check_sources(self) -> Settings:
        """Reject an unusable source selection at startup rather than after
        the pipeline has already created a run directory.

        Only trend sources feed the live pipeline. Lemmy and Wikipedia are
        dormant: their code and tests remain, but nothing consumes a flat
        item list until a consolidation phase exists to build dossiers from
        one. See docs/superpowers/specs/2026-08-26-trend-native-zeitgeist-
        capture-design.md, "Dormant platforms".
        """
        self.sources = [name.lower() for name in self.sources]
        valid = ", ".join(TREND_SOURCES)

        if len(self.sources) != 1:
            raise ValueError(f"sources must name exactly one of: {valid}")

        name = self.sources[0]
        if name in ITEM_SOURCES:
            raise ValueError(
                f"Source {name!r} is dormant: it has no trend clustering, so "
                f"it cannot produce dossiers. Use one of: {valid}"
            )
        if name not in TREND_SOURCES:
            raise ValueError(f"Unknown source: {name!r}. Valid: {valid}")

        return self


def _keys_with(scope: str) -> frozenset[str]:
    """The fields declaring `scope`, read off the model itself.

    Derived rather than listed, so a new field is unscoped — invisible to
    the settings screen and to per-run overrides — until someone says
    otherwise, and a deleted field takes its key with it. The two
    hand-maintained frozensets this replaced named fields in modules that
    had no connection to the field list they were describing, and drifted
    from it.
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


class StoredSettingError(ValueError):
    """A row in the `settings` table does not validate.

    Substituting the default for a value someone deliberately set is the
    outcome nobody can diagnose — a run quietly using `distil_concurrency` 4
    because the stored 0 failed `ge=1`. Now that the table *is* the
    configuration rather than an overlay on something else, refusing to load
    is the smaller harm. Writes are validated before they land, so the only
    way to reach this is a hand-edited database.
    """


def format_validation_errors(exc: ValidationError) -> str:
    """`exc.errors()` as one readable string naming every offending field,
    rather than the list of objects pydantic hands back.

    Shared with `zeitgeist.api.settings._validation_detail`, which needs
    the identical rendering for an HTTP `detail` string: every other 400
    among the project's endpoints uses a plain string there, and a
    generated TypeScript client would otherwise see `detail` as `string`
    everywhere except that one endpoint. Defined here, the lower module,
    rather than in `api/settings.py`, which already imports from this one
    — the reverse import would be a cycle.
    """
    return "; ".join(
        f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
        for error in exc.errors()
    )


def load_settings(store: Store) -> Settings:
    """Every stored value; every unstored field at its declared default."""
    try:
        # `dict[str, Any]`: every row is TEXT, and it is pydantic that turns
        # each one back into its field's real type — or raises, below —
        # not this function. Splatting the `dict[str, str]` `get_settings`
        # actually returns would type-check each field against `str`,
        # producing one diagnostic per non-string field for a mismatch the
        # runtime validation below exists precisely to catch.
        stored: dict[str, Any] = store.get_settings()
        return Settings(**stored)
    except ValidationError as exc:
        raise StoredSettingError(
            "Stored settings are invalid: " + format_validation_errors(exc)
        ) from exc


def resolve_settings(
    store: Store, base: Settings, overrides: dict[str, str]
) -> Settings:
    """Settings for one unit of work: `base`, then what the store holds, then
    this request's per-run overrides. Highest precedence last.

    Three layers, merged in one expression a reader can see.

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
