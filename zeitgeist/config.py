"""Runtime configuration, loaded from environment and `.env`."""

from pathlib import Path
from typing import Literal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from zeitgeist.models import Sentiment

PACKAGE_ROOT = Path(__file__).parent

# Registry keys live here rather than in zeitgeist/sources/__init__.py:
# that module imports Settings, so importing it back would be a cycle.
# tests/test_sources_composite.py guards the two against drifting.
KNOWN_SOURCES: tuple[str, ...] = ("lemmy", "reddit")

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

    reddit_client_id: str = ""
    reddit_client_secret: str = ""
    reddit_user_agent: str = "zeitgeist-actualiser/0.1 (by u/anonymous)"

    lemmy_instance: str = "https://lemmy.world"
    lemmy_include_nsfw: bool = False

    anthropic_api_key: str = ""
    llm_provider: Literal["anthropic", "ollama"] = "anthropic"
    llm_model: str = "claude-sonnet-5"
    ollama_host: str = "http://localhost:11434"

    sources: list[str] = ["lemmy"]
    subreddits: list[str] = []
    post_limit: int = 500
    topic_count: int = 5

    sentiment_weights: dict[Sentiment, float] = DEFAULT_SENTIMENT_WEIGHTS

    # None means "use the scalable font Pillow ships"; set it to a real .ttf
    # (e.g. C:/Windows/Fonts/impact.ttf) for the authentic meme look.
    font_path: Path | None = None
    templates_dir: Path = PACKAGE_ROOT / "media" / "templates"
    output_dir: Path = Path("output")
    db_path: Path = Path("data") / "zeitgeist.db"

    @field_validator("subreddits", "sources", mode="before")
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

        if "reddit" in self.sources:
            missing = [
                name
                for name, value in (
                    ("REDDIT_CLIENT_ID", self.reddit_client_id),
                    ("REDDIT_CLIENT_SECRET", self.reddit_client_secret),
                )
                if not value
            ]
            if missing:
                raise ValueError(
                    f"{' and '.join(missing)} must be set when 'reddit' is in "
                    "SOURCES. Reddit's Data API requires approved access; drop "
                    "'reddit' from SOURCES to run without it."
                )
        return self

    def weight_for(self, sentiment: Sentiment) -> float:
        """Weight for a sentiment, defaulting to neutral when unconfigured."""
        return self.sentiment_weights.get(sentiment, 1.0)
