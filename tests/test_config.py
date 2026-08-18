import pytest

from zeitgeist.config import DEFAULT_SENTIMENT_WEIGHTS, Settings
from zeitgeist.models import Sentiment


def _settings(**overrides) -> Settings:
    defaults = dict(
        reddit_client_id="id",
        reddit_client_secret="secret",
        anthropic_api_key="key",
    )
    return Settings(**{**defaults, **overrides})


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("cats,aww", ["cats", "aww"]),
        ("cats, aww ,mildlyinteresting", ["cats", "aww", "mildlyinteresting"]),
        ("cats,,aww,", ["cats", "aww"]),
        ("  ", []),
        ("", []),
        (["cats", "aww"], ["cats", "aww"]),
    ],
)
def test_subreddits_parse_from_env_strings(raw, expected):
    """Env vars arrive as strings; the validator has to survive the messy
    ways a human writes a list into a .env file.
    """
    assert _settings(subreddits=raw).subreddits == expected


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
    """No .env, no Reddit credentials — a fresh checkout's starting point."""
    return Settings(_env_file=None, anthropic_api_key="key", **overrides)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("lemmy", ["lemmy"]),
        ("lemmy,reddit", ["lemmy", "reddit"]),
        ("lemmy, reddit ", ["lemmy", "reddit"]),
        ("LEMMY,Reddit", ["lemmy", "reddit"]),
        (["lemmy"], ["lemmy"]),
    ],
)
def test_sources_parse_from_env_strings(raw, expected):
    """SOURCES arrives from .env as one string, and the names are registry
    keys, so case must not decide whether a platform runs.
    """
    assert _settings(sources=raw).sources == expected


def test_sources_defaults_to_lemmy_only():
    """Reddit's Data API needs approved access, so a fresh checkout must
    produce a working run without any credentials at all.
    """
    assert _bare_settings().sources == ["lemmy"]


def test_enabling_reddit_without_credentials_is_rejected():
    """The failure has to name the missing variables: 'validation error' on
    a field the user never set is not an actionable message.
    """
    with pytest.raises(ValueError) as err:
        _bare_settings(sources="reddit")
    message = str(err.value)
    assert "REDDIT_CLIENT_ID" in message
    assert "REDDIT_CLIENT_SECRET" in message


def test_enabling_reddit_with_credentials_is_accepted():
    settings = _settings(sources="lemmy,reddit")
    assert settings.sources == ["lemmy", "reddit"]


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
