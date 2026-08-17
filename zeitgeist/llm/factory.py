"""Chooses a provider from configuration."""

from zeitgeist.config import Settings
from zeitgeist.llm.anthropic import AnthropicProvider
from zeitgeist.llm.base import LLMProvider
from zeitgeist.llm.ollama import OllamaProvider


def build_provider(settings: Settings) -> LLMProvider:
    if settings.llm_provider == "ollama":
        return OllamaProvider(host=settings.ollama_host, model=settings.llm_model)
    if not settings.anthropic_api_key:
        raise ValueError("ANTHROPIC_API_KEY is required for the anthropic provider")
    return AnthropicProvider(
        api_key=settings.anthropic_api_key, model=settings.llm_model
    )
