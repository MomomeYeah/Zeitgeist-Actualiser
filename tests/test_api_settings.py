from tests.api_factory import api_settings, seeded_client
from zeitgeist.settings_source import WRITABLE_KEYS
from zeitgeist.store import Store


def test_every_tunable_field_is_reported(tmp_path):
    """The settings screen renders one row per field, so a field missing
    from the response is a row the screen cannot draw."""
    client = seeded_client(tmp_path)

    body = client.get("/api/settings").json()

    assert {field["key"] for field in body} == set(WRITABLE_KEYS)


def test_a_stored_override_reports_itself_as_set_here(tmp_path):
    settings = api_settings(tmp_path)
    store = Store(settings.db_path)
    store.init_schema()
    store.set_setting("bluesky_trend_limit", "11")
    store.close()
    client = seeded_client(tmp_path)

    body = {field["key"]: field for field in client.get("/api/settings").json()}

    assert body["bluesky_trend_limit"]["value"] == 11
    assert body["bluesky_trend_limit"]["source"] == "settings"


def test_an_untouched_field_reports_the_default(tmp_path, monkeypatch):
    """`chdir` because `_dotenv_value` reads `Path(".env")` relative to the
    process, not the `_env_file` `api_settings` passes. Without it this
    test's answer depends on whether the checked-out repo's own `.env`
    happens to set this key — the ambient-file hazard `conftest` already
    guards against for `DB_PATH`.
    """
    monkeypatch.chdir(tmp_path)
    client = seeded_client(tmp_path)

    body = {field["key"]: field for field in client.get("/api/settings").json()}

    assert body["phrase_min_authors"]["value"] == 3
    assert body["phrase_min_authors"]["source"] == "default"


def test_a_shell_variable_is_reported_as_environment(tmp_path, monkeypatch):
    """A shell variable outranks the settings table, so a screen showing
    'SET HERE' for a value the environment is actually supplying would be
    lying about which layer won."""
    monkeypatch.setenv("PHRASE_MIN_AUTHORS", "7")
    client = seeded_client(tmp_path)

    body = {field["key"]: field for field in client.get("/api/settings").json()}

    assert body["phrase_min_authors"]["value"] == 7
    assert body["phrase_min_authors"]["source"] == "environment"


def test_a_shell_variable_beats_a_stored_override(tmp_path, monkeypatch):
    """Both layers set the same key here, which no other test does. Every
    other case leaves the layer it is not testing empty, so swapping the
    first two branches of `_source` would pass all of them."""
    settings = api_settings(tmp_path)
    store = Store(settings.db_path)
    store.init_schema()
    store.set_setting("bluesky_trend_limit", "11")
    store.close()
    monkeypatch.setenv("BLUESKY_TREND_LIMIT", "9")
    client = seeded_client(tmp_path)

    body = {field["key"]: field for field in client.get("/api/settings").json()}

    assert body["bluesky_trend_limit"]["value"] == 9
    assert body["bluesky_trend_limit"]["source"] == "environment"


def test_the_api_key_is_never_in_the_response(tmp_path, monkeypatch):
    """It is not a tunable field, and a settings endpoint that leaked one
    would be a different and worse thing than a tuning screen."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-secret")
    client = seeded_client(tmp_path)

    raw = client.get("/api/settings").text

    assert "sk-ant-secret" not in raw
    assert "anthropic_api_key" not in raw
