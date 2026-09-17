"""Runtime configuration, loaded from environment and `.env`."""

from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import (
    BaseSettings,
    NoDecode,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

from zeitgeist.settings_source import SettingsTableSource

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


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

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
    llm_model: str = Field(
        "claude-sonnet-5", json_schema_extra={"scope": "run"}
    )
    # 127.0.0.1, not localhost: on the machine this was measured on, httpx
    # resolves localhost to ::1 first and IPv6-first resolution cost more
    # (2.16-2.28s) than the model registry's whole 2.0s timeout, so New run's
    # options fetch showed "Loading..." for over two seconds and came close
    # to failing outright. 127.0.0.1 answered in 0.19s.
    ollama_host: str = Field(
        "http://127.0.0.1:11434", json_schema_extra={"scope": "global"}
    )

    # NoDecode: pydantic-settings otherwise JSON-decodes any list-typed env
    # value before validators run, so a plain CSV string like
    # "lemmy,wikipedia" raises SettingsError before `_split_csv` ever sees it.
    sources: Annotated[list[str], NoDecode] = Field(
        ["bluesky"], json_schema_extra={"scope": "run"}
    )
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
            raise ValueError(f"SOURCES must name exactly one of: {valid}")

        name = self.sources[0]
        if name in ITEM_SOURCES:
            raise ValueError(
                f"Source {name!r} is dormant: it has no trend clustering, so "
                f"it cannot produce dossiers. Use one of: {valid}"
            )
        if name not in TREND_SOURCES:
            raise ValueError(f"Unknown source: {name!r}. Valid: {valid}")

        return self

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Slot the settings table between the environment and `.env`.

        Order is precedence, highest first.
        """
        return (
            init_settings,
            env_settings,
            SettingsTableSource(settings_cls),
            dotenv_settings,
            file_secret_settings,
        )


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
