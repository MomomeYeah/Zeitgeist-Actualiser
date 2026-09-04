from zeitgeist.config import Settings
from zeitgeist.settings_source import WRITABLE_KEYS
from zeitgeist.store import Store


def _store_with(tmp_path, **values) -> Store:
    store = Store(tmp_path / "zeitgeist.db")
    store.init_schema()
    for key, value in values.items():
        store.set_setting(key, str(value))
    store.close()
    return store


def test_a_stored_setting_is_used_when_the_environment_is_silent(tmp_path, monkeypatch):
    _store_with(tmp_path, bluesky_trend_limit=11)
    monkeypatch.setenv("DB_PATH", str(tmp_path / "zeitgeist.db"))

    settings = Settings(_env_file=None)

    assert settings.bluesky_trend_limit == 11


def test_an_environment_variable_beats_a_stored_setting(tmp_path, monkeypatch):
    """An explicit BLUESKY_TREND_LIMIT=10 in front of a command is the more
    deliberate act, so it wins over what the UI last saved."""
    _store_with(tmp_path, bluesky_trend_limit=11)
    monkeypatch.setenv("DB_PATH", str(tmp_path / "zeitgeist.db"))
    monkeypatch.setenv("BLUESKY_TREND_LIMIT", "10")

    settings = Settings(_env_file=None)

    assert settings.bluesky_trend_limit == 10


def test_clearing_a_setting_falls_back_to_the_default(tmp_path, monkeypatch):
    store = _store_with(tmp_path, bluesky_trend_limit=11)
    monkeypatch.setenv("DB_PATH", str(tmp_path / "zeitgeist.db"))

    store = Store(tmp_path / "zeitgeist.db")
    store.clear_setting("bluesky_trend_limit")
    store.close()

    assert Settings(_env_file=None).bluesky_trend_limit == 25


def test_a_stored_setting_beats_a_dotenv_value(tmp_path, monkeypatch):
    """The whole point of this source is *where* it sits. Every other test
    here passes _env_file=None, so dotenv never participates and the
    ordering bug the source exists to avoid - sitting after dotenv rather
    than before it - would pass all of them."""
    env_file = tmp_path / ".env"
    env_file.write_text("BLUESKY_TREND_LIMIT=7\n", encoding="utf-8")
    _store_with(tmp_path, bluesky_trend_limit=11)
    monkeypatch.setenv("DB_PATH", str(tmp_path / "zeitgeist.db"))

    settings = Settings(_env_file=env_file)

    assert settings.bluesky_trend_limit == 11


def test_a_dotenv_value_applies_once_the_override_is_cleared(tmp_path, monkeypatch):
    """The other half of the same ordering: Reset to .env has to reveal the
    file's value, not the field default."""
    env_file = tmp_path / ".env"
    env_file.write_text("BLUESKY_TREND_LIMIT=7\n", encoding="utf-8")
    _store_with(tmp_path, bluesky_trend_limit=11)
    monkeypatch.setenv("DB_PATH", str(tmp_path / "zeitgeist.db"))

    store = Store(tmp_path / "zeitgeist.db")
    store.clear_setting("bluesky_trend_limit")
    store.close()

    assert Settings(_env_file=env_file).bluesky_trend_limit == 7


def test_a_missing_database_is_not_an_error(tmp_path, monkeypatch):
    """Settings must load before anything has created the database - the
    harness builds Settings in order to find out where the database goes."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "absent.db"))

    assert Settings(_env_file=None).bluesky_trend_limit == 25


def test_only_the_tuning_fields_are_writable():
    """A UI that can rewrite where the database lives, or store an API key in
    a table, is a different and worse thing than a tuning screen."""
    assert "anthropic_api_key" not in WRITABLE_KEYS
    assert "db_path" not in WRITABLE_KEYS
    assert "output_dir" not in WRITABLE_KEYS
    assert {
        "bluesky_trend_limit",
        "bluesky_posts_per_trend",
        "bluesky_fetch_concurrency",
        "meme_potential_weight",
        "phrase_min_authors",
        "distil_char_budget",
        "distil_concurrency",
    } == WRITABLE_KEYS


def test_a_key_outside_the_writable_set_is_ignored_by_the_source(tmp_path, monkeypatch):
    """Defence in depth: the endpoint rejects these, and the source refuses
    to honour one that reached the table another way."""
    _store_with(tmp_path, anthropic_api_key="leaked")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "zeitgeist.db"))

    assert Settings(_env_file=None).anthropic_api_key == ""


def test_an_ambient_database_cannot_leak_into_settings(tmp_path, monkeypatch):
    """conftest points DB_PATH at a nonexistent file per test, because
    settings_source falls back to a relative data/zeitgeist.db when the
    variable is unset. Without that, running the app once locally would
    silently feed real tuned values into every Settings() in the suite."""
    ambient = tmp_path / "data"
    ambient.mkdir()
    store = Store(ambient / "zeitgeist.db")
    store.init_schema()
    store.set_setting("bluesky_trend_limit", "99")
    store.close()
    monkeypatch.chdir(tmp_path)

    assert Settings(_env_file=None).bluesky_trend_limit == 25
