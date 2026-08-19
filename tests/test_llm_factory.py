import pytest

from zeitgeist.config import Settings
from zeitgeist.llm.factory import build_provider
from zeitgeist.llm.ollama import OllamaProvider


def _settings(**overrides) -> Settings:
    return Settings(**overrides)


def test_builds_ollama_wired_to_the_configured_host_and_model():
    """Catches the classic factory bug: constructing the right class with
    arguments crossed or defaulted, which only shows up as a live API call
    against the wrong model.
    """
    settings = _settings(
        llm_provider="ollama",
        llm_model="qwen2.5:14b",
        ollama_host="http://gpu-box:11434",
    )
    provider = build_provider(settings)
    assert isinstance(provider, OllamaProvider)
    assert provider.model == "qwen2.5:14b"
    assert provider.host == "http://gpu-box:11434"


def test_anthropic_without_api_key_fails_before_any_request():
    """Without this the failure surfaces as a 401 partway through a run,
    after the scrape has already been paid for.
    """
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        build_provider(_settings(llm_provider="anthropic", anthropic_api_key=""))


def test_ollama_needs_no_anthropic_key():
    provider = build_provider(_settings(llm_provider="ollama", anthropic_api_key=""))
    assert isinstance(provider, OllamaProvider)
