import pytest
from pydantic import ValidationError

from zeitgeist.config import Settings


def _bare_settings(**overrides) -> Settings:
    """No .env — a fresh checkout's starting point."""
    return Settings(_env_file=None, anthropic_api_key="key", **overrides)


@pytest.mark.parametrize(
    "raw,message",
    [
        ("", "exactly one"),
        ("bluesky,wikipedia", "exactly one"),
        ("lemmy", "dormant"),
        ("mastodon", "Unknown source"),
    ],
)
def test_unusable_source_selections_are_rejected(raw, message):
    """The empty case is the one that would otherwise reach `sources[0]` and
    raise IndexError instead of a readable validation error — `SOURCES=` in a
    .env produces exactly it. The old validator had a dedicated empty branch;
    the new one folds it into the length check, so it needs its own case.
    """
    with pytest.raises(ValidationError, match=message):
        Settings(_env_file=None, sources=raw)


def test_bluesky_is_accepted():
    assert Settings(_env_file=None, sources="bluesky").sources == ["bluesky"]


def test_a_source_name_from_a_real_env_var_is_parsed_without_json_decoding(
    monkeypatch,
):
    """pydantic-settings JSON-decodes list-typed fields before validators run
    when the value comes from a real env var, so a plain string raises
    SettingsError unless the field opts out via NoDecode. The kwargs-based
    tests go through InitSettingsSource, which never JSON-decodes, so they
    cannot catch a regression here. Case and stray whitespace are folded in:
    the name is a registry key, so neither may decide whether a platform runs.
    """
    monkeypatch.setenv("SOURCES", " BLUESKY ")
    assert Settings(_env_file=None).sources == ["bluesky"]


def test_sources_defaults_to_bluesky_only():
    """A fresh checkout must produce a working run without any credentials
    at all.
    """
    assert _bare_settings().sources == ["bluesky"]


def test_lemmy_settings_have_usable_defaults():
    settings = _bare_settings()
    assert settings.lemmy_instance == "https://lemmy.world"
    assert settings.lemmy_include_nsfw is False


def test_wikipedia_settings_have_usable_defaults():
    """Enabling it must never require credentials — this is the property
    that keeps the project runnable with no credentials at all, which is why
    Wikimedia was chosen. Checked against the field defaults directly:
    Settings no longer accepts wikipedia as a live source selection at all
    (it is dormant; see test_unusable_source_selections_are_rejected), so
    there is no longer a `sources=` spelling of this guard.
    """
    settings = _bare_settings()
    assert settings.wikipedia_project == "en.wikipedia"
    assert settings.wikipedia_contact == (
        "https://github.com/MomomeYeah/Zeitgeist-Actualiser"
    )
