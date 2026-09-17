from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from zeitgeist.config import (
    GLOBAL_KEYS,
    RUN_KEYS,
    SECRET_KEYS,
    Settings,
    StoredSettingError,
    load_settings,
    resolve_settings,
)
from zeitgeist.store import Store


@pytest.fixture
def store(tmp_path):
    store = Store(tmp_path / "z.db")
    store.init_schema()
    yield store
    store.close()


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
    raise IndexError instead of a readable validation error — a cleared
    `sources` row produces exactly it. The validator folds it into the
    length check rather than giving it a branch, so it needs its own case.
    """
    with pytest.raises(ValidationError, match=message):
        Settings(sources=raw)


def test_bluesky_is_accepted():
    assert Settings(sources="bluesky").sources == ["bluesky"]


def test_a_source_name_is_folded_to_lower_case_and_stripped():
    """The name is a registry key, so neither case nor stray whitespace
    around a stored value may decide whether a platform runs."""
    assert Settings(sources=" BLUESKY ").sources == ["bluesky"]


def test_sources_defaults_to_bluesky_only():
    """A fresh checkout must produce a working run without any credentials
    at all.
    """
    assert Settings().sources == ["bluesky"]


def test_lemmy_settings_have_usable_defaults():
    settings = Settings()
    assert settings.lemmy_instance == "https://lemmy.world"
    assert settings.lemmy_include_nsfw is False


@pytest.mark.parametrize("field", ["bluesky_fetch_concurrency", "distil_concurrency"])
def test_zero_concurrency_is_rejected(field):
    """A semaphore or thread pool of 0 workers blocks the run forever with
    no diagnostic. Rejecting it at startup turns a silent hang into an
    immediate, readable configuration error.
    """
    # dict[str, Any]: `field` is a parametrized key, so a plain `{field: 0}`
    # infers `dict[str, int]` and the type checker offers that `int` to
    # every field the splat could land on, including the `str`- and
    # `Path`-typed ones this test never touches.
    overrides: dict[str, Any] = {field: 0}
    with pytest.raises(ValidationError):
        Settings(**overrides)


def test_wikipedia_settings_have_usable_defaults():
    """Enabling it must never require credentials — this is the property
    that keeps the project runnable with no credentials at all, which is why
    Wikimedia was chosen. Checked against the field defaults directly:
    Settings no longer accepts wikipedia as a live source selection at all
    (it is dormant; see test_unusable_source_selections_are_rejected), so
    there is no longer a `sources=` spelling of this guard.
    """
    settings = Settings()
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
    """`RunConfig.as_overrides` is what a resume reposts, and `enqueue`
    validates those keys against `RUN_KEYS`. If the two sets
    ever differ, a resume of a perfectly ordinary run is refused as naming a
    key no run may set — so they are pinned equal here, against a real frozen
    config rather than a literal list.
    """
    from tests.run_factory import make_run_config

    assert frozenset(make_run_config().as_overrides()) == RUN_KEYS


def test_load_settings_reads_every_scoped_field_back_in_its_real_type(store):
    """The table is all TEXT, so each field's declared type is what turns a
    row back into a usable value. Covers one of each shape that needs
    coercing — int, float, the CSV list, a Path and a plain string — because
    a loader that returned the raw strings would still satisfy an int-only
    assertion under Python's truthiness.
    """
    store.set_setting("topic_count", "9")
    store.set_setting("meme_potential_weight", "0.75")
    store.set_setting("sources", "bluesky")
    store.set_setting("font_path", "C:/Windows/Fonts/impact.ttf")
    store.set_setting("llm_model", "qwen3.5")

    settings = load_settings(store)

    assert settings.topic_count == 9
    assert settings.meme_potential_weight == 0.75
    assert settings.sources == ["bluesky"]
    assert settings.font_path == Path("C:/Windows/Fonts/impact.ttf")
    assert settings.llm_model == "qwen3.5"


def test_only_the_stored_fields_move_off_their_defaults(store):
    """The contrast, not the defaulting.

    `Settings(**{})` returning declared defaults is pydantic's behaviour, not
    this project's, and asserting a bare `== 24000` would be a test of the
    framework that fails the day someone legitimately retunes the default.
    What is ours is the merge: exactly the stored keys move, and a field
    beside them in the same load is untouched. A `load_settings` that
    splatted the whole table over every field, or that dropped the table
    entirely, breaks one half or the other.
    """
    before = load_settings(store)
    store.set_setting("distil_char_budget", "8000")

    after = load_settings(store)

    assert (before.distil_char_budget, after.distil_char_budget) == (24000, 8000)
    assert after.distil_concurrency == before.distil_concurrency


def test_a_stored_value_that_fails_validation_raises_and_names_the_key(store):
    """`distil_concurrency` is `ge=1`; a stored 0 would make every
    distillation block forever. Loading must refuse rather than quietly
    substitute the default of 4, which is the mystery-bug outcome the spec
    rejects. The key has to appear in the message, because the only way to
    fix it is to know which row to edit.
    """
    store.set_setting("distil_concurrency", "0")

    with pytest.raises(StoredSettingError, match="distil_concurrency"):
        load_settings(store)


def test_a_stored_key_that_is_no_longer_a_field_is_ignored(store):
    """What a field removed in a later version leaves behind. Not a corrupt
    value, so not a refusal to start."""
    store.set_setting("retired_knob", "whatever")

    assert load_settings(store).topic_count == 5


def test_the_store_beats_the_base_snapshot(store):
    """The staleness class this replaces: `app.state.settings` is frozen at
    startup, so a value saved in the browser has to outrank it or it never
    reaches the next run.
    """
    base = Settings(topic_count=5)
    store.set_setting("topic_count", "9")

    assert resolve_settings(store, base, {}).topic_count == 9


def test_a_per_run_override_beats_the_store(store):
    store.set_setting("topic_count", "9")

    assert resolve_settings(store, Settings(), {"topic_count": "2"}).topic_count == 2


def test_an_unscoped_field_survives_from_the_base_untouched(store):
    """`output_dir` is never stored, so the only thing that can carry a
    test's tmp_path through `resolve_settings` is `base`. A merge that
    rebuilt Settings from the store alone would silently reset it to
    `output/` and start writing PNGs into the working tree.
    """
    base = Settings(output_dir=Path("/tmp/somewhere"))
    store.set_setting("topic_count", "9")

    resolved = resolve_settings(store, base, {})

    assert resolved.output_dir == Path("/tmp/somewhere")
    assert resolved.topic_count == 9


def test_an_invalid_override_raises_rather_than_being_coerced_silently(store):
    """`model_copy(update=...)` would leave `"nonsense"` sitting in an int
    field with no error raised anywhere. Construction is what makes a bad
    override a refusal on the request thread.

    Narrowed to `ValidationError` and to the offending key: plain
    `ValueError` is also what `_check_sources` raises, so the wide form
    would be satisfied by a failure that had nothing to do with the
    override.
    """
    with pytest.raises(ValidationError) as caught:
        resolve_settings(store, Settings(), {"topic_count": "nonsense"})

    assert "topic_count" in str(caught.value)


def test_settings_no_longer_reads_the_environment(monkeypatch):
    """The whole point of the change, asserted directly. `monkeypatch.setenv`
    rather than a stripped fixture: this must fail if anyone reintroduces an
    env layer, and there is no longer a conftest fixture hiding the effect.
    """
    monkeypatch.setenv("TOPIC_COUNT", "42")

    assert Settings().topic_count == 5


def test_settings_no_longer_reads_a_dotenv_file(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("TOPIC_COUNT=42\n", encoding="utf-8")

    assert Settings().topic_count == 5
