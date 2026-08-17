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
