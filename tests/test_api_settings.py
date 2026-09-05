import os
from pathlib import Path

from tests.api_factory import api_settings, seeded_client
from zeitgeist.config import Settings
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


def test_a_written_value_is_stored_and_reported_as_set_here(tmp_path):
    """The screen's whole feedback loop: save, and the chip changes. A write
    that stored the value but reported the old source would leave the user
    unable to tell whether it took."""
    client = seeded_client(tmp_path)

    body = client.put(
        "/api/settings", json={"values": {"bluesky_trend_limit": "11"}}
    ).json()

    fields = {field["key"]: field for field in body}
    assert fields["bluesky_trend_limit"]["value"] == 11
    assert fields["bluesky_trend_limit"]["source"] == "settings"


def test_a_get_after_a_put_reports_the_new_value(tmp_path):
    """`GET /api/settings` used to report `getattr` on `app.state.settings`
    — frozen once at startup — rather than the live table, so a `PUT` was
    invisible to every `GET` after it for the rest of the process's life:
    the chip would say "settings" while showing the pre-write value, naming
    the very layer that just won as the source of a value it did not
    produce. Both requests share the same `TestClient`, and so the same
    `app.state.settings`, which is exactly what would have served the stale
    value here.
    """
    client = seeded_client(tmp_path)

    client.put("/api/settings", json={"values": {"bluesky_trend_limit": "11"}})
    body = {field["key"]: field for field in client.get("/api/settings").json()}

    assert body["bluesky_trend_limit"]["value"] == 11
    assert body["bluesky_trend_limit"]["source"] == "settings"


def test_a_written_value_survives_into_a_new_settings_object(tmp_path):
    """The point of the table: the next run picks the value up. A write that
    only touched the response would change the screen and nothing else.

    Asserted on a freshly built `Settings` rather than on `GET /api/settings`
    — which now also reports it, per the test above — because that is what
    "the next run" actually is: the worker constructs one per run and
    `SettingsTableSource` reads the table at construction, independently of
    whatever `GET /api/settings` happens to do.
    """
    client = seeded_client(tmp_path)

    client.put("/api/settings", json={"values": {"phrase_min_authors": "7"}})

    assert Settings(_env_file=None).phrase_min_authors == 7


def test_an_empty_value_clears_the_row_so_the_fallback_applies(tmp_path):
    """ "Reset to .env" deletes the row rather than writing a default —
    writing the default back would pin the value and make a later `.env`
    edit invisible, which is the opposite of what the button says."""
    client = seeded_client(tmp_path)
    client.put("/api/settings", json={"values": {"phrase_min_authors": "7"}})

    body = client.put(
        "/api/settings", json={"values": {"phrase_min_authors": ""}}
    ).json()

    # Compared against a freshly built Settings rather than the literal 3:
    # that literal is the field's default, which the code is free to change,
    # so a test pinning it would fail for a decision rather than a bug.
    fields = {field["key"]: field for field in body}
    assert fields["phrase_min_authors"]["value"] == (
        Settings(_env_file=None).phrase_min_authors
    )
    assert fields["phrase_min_authors"]["source"] != "settings"


def test_a_field_outside_the_seven_is_refused(tmp_path):
    """A UI that can rewrite where the database lives is a different and
    worse thing than a tuning screen."""
    client = seeded_client(tmp_path)

    response = client.put(
        "/api/settings", json={"values": {"db_path": "/tmp/elsewhere.db"}}
    )

    assert response.status_code == 400


def test_the_api_key_cannot_be_written(tmp_path):
    """Named separately because this is the one the allowlist exists for:
    storing a key in the settings table would put it in the database in
    plain text, and `GET /api/settings` would then have to know to hide a
    field it otherwise reports."""
    client = seeded_client(tmp_path)

    response = client.put(
        "/api/settings", json={"values": {"anthropic_api_key": "sk-ant-nope"}}
    )

    assert response.status_code == 400


def test_a_refused_field_writes_nothing_at_all(tmp_path):
    """A request naming one good field and one bad one must write neither.
    Applying the valid half would leave the screen showing a partial save
    with a 400 beside it, and no way to tell which half landed.

    Asserted against the settings table directly rather than through
    `GET /api/settings`: the endpoint now builds a fresh `Settings` per
    request, so it would also fail this test if it wrote the good half, but
    checking the table is still the more direct assertion of "wrote
    nothing" and does not depend on that read path at all.
    """
    client = seeded_client(tmp_path)

    response = client.put(
        "/api/settings",
        json={"values": {"phrase_min_authors": "7", "db_path": "/tmp/x.db"}},
    )

    assert response.status_code == 400
    store = Store(Path(os.environ["DB_PATH"]))
    try:
        assert store.get_settings() == {}
    finally:
        store.close()


def test_a_value_that_settings_would_reject_is_refused(tmp_path):
    """`meme_potential_weight` is `ge=0.0, le=1.0`. Stored unvalidated, 2.0
    would be written happily and then fail when the *next run* built its
    Settings — surfacing as a broken run rather than a rejected save.
    """
    client = seeded_client(tmp_path)

    response = client.put(
        "/api/settings", json={"values": {"meme_potential_weight": "2.0"}}
    )

    assert response.status_code == 400


def test_a_non_numeric_value_is_refused(tmp_path):
    """Same failure mode, cruder input. The form is a text box."""
    client = seeded_client(tmp_path)

    response = client.put(
        "/api/settings", json={"values": {"bluesky_trend_limit": "banana"}}
    )

    assert response.status_code == 400
