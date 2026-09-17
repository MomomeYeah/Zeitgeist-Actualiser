import pytest
from pydantic import ValidationError

from zeitgeist.config import GLOBAL_KEYS, RUN_KEYS, SECRET_KEYS, Settings


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


@pytest.mark.parametrize("field", ["bluesky_fetch_concurrency", "distil_concurrency"])
def test_zero_concurrency_is_rejected(field):
    """A semaphore or thread pool of 0 workers blocks the run forever with
    no diagnostic. Rejecting it at startup turns a silent hang into an
    immediate, readable configuration error.
    """
    with pytest.raises(ValidationError):
        _bare_settings(**{field: 0})


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


def test_the_unscoped_fields_are_the_ones_no_screen_offers():
    """Derived from the live model, so a field added without a scope shows up
    here as a failure rather than being silently unsettable."""
    unscoped = frozenset(Settings.model_fields) - GLOBAL_KEYS - RUN_KEYS
    assert unscoped == frozenset(
        {
            "output_dir",
            "templates_dir",
            "bluesky_api_base",
            "wikipedia_project",
            "wikipedia_contact",
            "lemmy_instance",
            "lemmy_include_nsfw",
        }
    )


def test_the_api_key_is_the_only_secret_and_it_is_global():
    assert frozenset({"anthropic_api_key"}) == SECRET_KEYS
    assert SECRET_KEYS <= GLOBAL_KEYS


def test_run_keys_match_the_keys_a_frozen_config_replays():
    """`RunConfig.as_overrides` is what a resume reposts, and `enqueue` will
    validate those keys against `RUN_KEYS` from Task 4 on. If the two sets
    ever differ, a resume of a perfectly ordinary run is refused as naming a
    key no run may set — so they are pinned equal here, against a real frozen
    config rather than a literal list.
    """
    from tests.run_factory import make_run_config

    assert frozenset(make_run_config().as_overrides()) == RUN_KEYS
