from typing import Any

import pytest

from zeitgeist.config import DEFAULT_SENTIMENT_WEIGHTS, Settings
from zeitgeist.models import Sentiment


def _settings(**overrides: Any) -> Settings:
    defaults: dict[str, Any] = dict(
        anthropic_api_key="key",
    )
    return Settings(**{**defaults, **overrides})


def test_every_sentiment_has_a_default_weight():
    """A sentiment added to the enum without a weight would silently score
    as neutral, quietly defeating the preference for positive topics.
    """
    assert set(DEFAULT_SENTIMENT_WEIGHTS) == set(Sentiment)


def test_weight_for_falls_back_to_neutral_when_unconfigured():
    """A user who overrides SENTIMENT_WEIGHTS with a partial map must not
    crash the run on the sentiments they left out.
    """
    settings = _settings(sentiment_weights={Sentiment.CUTE: 2.0})
    assert settings.weight_for(Sentiment.CUTE) == 2.0
    assert settings.weight_for(Sentiment.SAD) == 1.0


def _bare_settings(**overrides) -> Settings:
    """No .env — a fresh checkout's starting point."""
    return Settings(_env_file=None, anthropic_api_key="key", **overrides)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("lemmy", ["lemmy"]),
        (" lemmy ", ["lemmy"]),
        ("LEMMY", ["lemmy"]),
        ("lemmy,,", ["lemmy"]),
        (["lemmy"], ["lemmy"]),
    ],
)
def test_sources_parse_from_env_strings(raw, expected):
    """SOURCES arrives from .env as one string, and the names are registry
    keys, so case and stray separators must not decide whether a platform runs.
    """
    assert _settings(sources=raw).sources == expected


def test_sources_parse_from_a_real_env_var(monkeypatch):
    """pydantic-settings JSON-decodes list-typed fields before validators run
    when the value comes from a real env var, so a plain CSV string here
    raises SettingsError unless the field opts out via NoDecode. The
    kwargs-based tests above go through InitSettingsSource, which never
    JSON-decodes, so they cannot catch a regression here.
    """
    monkeypatch.setenv("SOURCES", "lemmy")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "key")
    assert Settings(_env_file=None).sources == ["lemmy"]


def test_a_multi_source_env_var_splits_on_the_comma(monkeypatch):
    """Two names in one env var is the shape a real .env carries, and the
    only shape where the CSV split can be told apart from a no-op.
    """
    monkeypatch.setenv("SOURCES", "lemmy,wikipedia")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "key")

    assert Settings(_env_file=None).sources == ["lemmy", "wikipedia"]


def test_sources_defaults_to_lemmy_only():
    """A fresh checkout must produce a working run without any credentials
    at all.
    """
    assert _bare_settings().sources == ["lemmy"]


def test_unknown_source_is_rejected_with_the_valid_names():
    with pytest.raises(ValueError, match="mastodon"):
        _bare_settings(sources="mastodon")


def test_empty_sources_is_rejected():
    """An empty list would otherwise reach CompositeSource, which cannot
    build anything, and fail further from the cause.
    """
    with pytest.raises(ValueError, match="at least one"):
        _bare_settings(sources="")


def test_lemmy_settings_have_usable_defaults():
    settings = _bare_settings()
    assert settings.lemmy_instance == "https://lemmy.world"
    assert settings.lemmy_include_nsfw is False


def test_wikipedia_needs_no_credentials():
    """Enabling it must not raise at startup — this is the property that
    keeps the project runnable with no credentials at all, which is why
    Wikimedia was chosen. Fails if _check_sources ever grows a credential
    branch for wikipedia, as it once had for reddit.
    """
    settings = Settings(_env_file=None, sources=["lemmy", "wikipedia"])

    assert settings.sources == ["lemmy", "wikipedia"]
