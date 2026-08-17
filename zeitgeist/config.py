"""Runtime configuration, loaded from environment and `.env`."""

from pathlib import Path
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from zeitgeist.models import Sentiment

PACKAGE_ROOT = Path(__file__).parent

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

    reddit_client_id: str
    reddit_client_secret: str
    reddit_user_agent: str = "zeitgeist-actualiser/0.1 (by u/anonymous)"

    anthropic_api_key: str = ""
    llm_provider: Literal["anthropic", "ollama"] = "anthropic"
    llm_model: str = "claude-sonnet-5"
    ollama_host: str = "http://localhost:11434"

    subreddits: list[str] = []
    post_limit: int = 500
    topic_count: int = 5

    sentiment_weights: dict[Sentiment, float] = DEFAULT_SENTIMENT_WEIGHTS

    font_path: Path = PACKAGE_ROOT / "media" / "fonts" / "DejaVuSans-Bold.ttf"
    templates_dir: Path = PACKAGE_ROOT / "media" / "templates"
    output_dir: Path = Path("output")
    db_path: Path = Path("data") / "zeitgeist.db"

    @field_validator("subreddits", mode="before")
    @classmethod
    def _split_subreddits(cls, value: object) -> object:
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return value

    def weight_for(self, sentiment: Sentiment) -> float:
        """Weight for a sentiment, defaulting to neutral when unconfigured."""
        return self.sentiment_weights.get(sentiment, 1.0)
