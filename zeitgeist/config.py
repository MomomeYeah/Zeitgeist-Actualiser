"""Runtime configuration, loaded from environment and `.env`."""

from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

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
    bluesky_trend_limit: int = 25
    bluesky_posts_per_trend: int = 10
    # ge=1: a semaphore of 0 blocks every fetch forever with no diagnostic.
    bluesky_fetch_concurrency: int = Field(default=8, ge=1)

    anthropic_api_key: str = ""
    llm_provider: Literal["anthropic", "ollama"] = "anthropic"
    llm_model: str = "claude-sonnet-5"
    ollama_host: str = "http://localhost:11434"

    # NoDecode: pydantic-settings otherwise JSON-decodes any list-typed env
    # value before validators run, so a plain CSV string like
    # "lemmy,wikipedia" raises SettingsError before `_split_csv` ever sees it.
    sources: Annotated[list[str], NoDecode] = ["bluesky"]
    topic_count: int = 5

    # Distinct accounts a phrase needs before it counts as recurring. Below
    # this, a repeated phrase is one person or a small ring, not a zeitgeist.
    phrase_min_authors: int = 3

    # Reply characters sent per distillation call. A single trend can yield
    # six hundred replies; a 32k-context local model truncates silently well
    # before that, so the budget is explicit rather than discovered.
    distil_char_budget: int = 24000
    # Parallel distillation calls. Local Ollama serialises on one GPU, so 1-2
    # is right there; a hosted provider benefits from the default. ge=1: a
    # ThreadPoolExecutor of 0 workers blocks every distillation forever.
    distil_concurrency: int = Field(default=4, ge=1)

    # None means "use the scalable font Pillow ships"; set it to a real .ttf
    # (e.g. C:/Windows/Fonts/impact.ttf) for the authentic meme look.
    font_path: Path | None = None
    templates_dir: Path = PACKAGE_ROOT / "media" / "templates"
    output_dir: Path = Path("output")
    db_path: Path = Path("data") / "zeitgeist.db"

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
