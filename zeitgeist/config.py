"""Runtime configuration, loaded from environment and `.env`."""

from pathlib import Path
from typing import Annotated, Literal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from zeitgeist.models import Sentiment

PACKAGE_ROOT = Path(__file__).parent

# Registry keys live here rather than in zeitgeist/sources/__init__.py:
# that module imports Settings, so importing it back would be a cycle.
# tests/test_sources_composite.py guards the two against drifting.
KNOWN_SOURCES: tuple[str, ...] = ("lemmy", "wikipedia", "bluesky")

# Favours positive output without excluding anything. The spread is moderate
# on purpose: a negative topic needs roughly double the combined trend and
# meme-potential score to outrank a positive one, which is a thumb on the
# scale rather than a veto.
DEFAULT_SENTIMENT_WEIGHTS: dict[Sentiment, float] = {
    Sentiment.HEARTWARMING: 1.30,
    Sentiment.CUTE: 1.25,
    Sentiment.FUNNY: 1.25,
    Sentiment.AWE: 1.20,
    Sentiment.SCHADENFREUDE: 1.00,
    Sentiment.CRINGE: 0.90,
    Sentiment.MUNDANE: 0.70,
    Sentiment.GROSS: 0.70,
    Sentiment.SAD: 0.60,
    Sentiment.SCARY: 0.60,
    Sentiment.OUTRAGE: 0.60,
}


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

    anthropic_api_key: str = ""
    llm_provider: Literal["anthropic", "ollama"] = "anthropic"
    llm_model: str = "claude-sonnet-5"
    ollama_host: str = "http://localhost:11434"

    # NoDecode: pydantic-settings otherwise JSON-decodes any list-typed env
    # value before validators run, so a plain CSV string like
    # "lemmy,wikipedia" raises SettingsError before `_split_csv` ever sees it.
    sources: Annotated[list[str], NoDecode] = ["lemmy"]
    post_limit: int = 500
    topic_count: int = 5

    sentiment_weights: dict[Sentiment, float] = DEFAULT_SENTIMENT_WEIGHTS

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
        """
        self.sources = [name.lower() for name in self.sources]
        valid = ", ".join(KNOWN_SOURCES)
        if not self.sources:
            raise ValueError(f"SOURCES is empty; enable at least one of: {valid}")

        unknown = [name for name in self.sources if name not in KNOWN_SOURCES]
        if unknown:
            raise ValueError(f"Unknown source(s): {', '.join(unknown)}. Valid: {valid}")

        return self

    def weight_for(self, sentiment: Sentiment) -> float:
        """Weight for a sentiment, defaulting to neutral when unconfigured."""
        return self.sentiment_weights.get(sentiment, 1.0)
