from tests.api_factory import api_db_path, seed_settings, seeded_client
from zeitgeist.api.settings import WRITABLE_KEYS
from zeitgeist.config import Settings, load_settings
from zeitgeist.store import Store


def test_every_tunable_field_is_reported(tmp_path):
    """The settings screen renders one row per field, so a field missing
    from the response is a row the screen cannot draw."""
    client = seeded_client(tmp_path)

    body = client.get("/api/settings").json()

    assert {field["key"] for field in body} == set(WRITABLE_KEYS)


def test_a_stored_override_reports_itself_as_set_here(tmp_path):
    seed_settings(tmp_path, bluesky_trend_limit="11")
    client = seeded_client(tmp_path)

    body = {field["key"]: field for field in client.get("/api/settings").json()}

    assert body["bluesky_trend_limit"]["value"] == 11
    assert body["bluesky_trend_limit"]["source"] == "settings"


def test_an_untouched_field_reports_the_default(tmp_path):
    """The other half of the chip: a field with no row behind it must say so,
    or "set here" would be the only thing the screen could ever show."""
    client = seeded_client(tmp_path)

    body = {field["key"]: field for field in client.get("/api/settings").json()}

    assert body["phrase_min_authors"]["value"] == 3
    assert body["phrase_min_authors"]["source"] == "default"


def test_the_api_key_is_never_in_the_response(tmp_path):
    """It is not a tunable field, and a settings endpoint that leaked one
    would be a different and worse thing than a tuning screen. Seeded into
    the table, which is where a key lives now, so the response is built from
    a `Settings` that really is carrying it.
    """
    seed_settings(tmp_path, anthropic_api_key="sk-ant-secret")
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

    Asserted through `load_settings` against a separate connection rather
    than on `GET /api/settings` — which now also reports it, per the test
    above — because that is what "the next run" actually is: the run builds
    its own `Settings` off the table, independently of whatever
    `GET /api/settings` happens to do.
    """
    client = seeded_client(tmp_path)

    client.put("/api/settings", json={"values": {"phrase_min_authors": "7"}})

    store = Store(api_db_path(tmp_path))
    try:
        assert load_settings(store).phrase_min_authors == 7
    finally:
        store.close()


def test_an_empty_value_clears_the_row_so_the_default_applies(tmp_path):
    """Reset deletes the row rather than writing the default into it. A
    stored default would read back as a deliberate choice, and the screen
    could no longer tell it from a field nobody has touched."""
    client = seeded_client(tmp_path)
    client.put("/api/settings", json={"values": {"phrase_min_authors": "7"}})

    body = client.put(
        "/api/settings", json={"values": {"phrase_min_authors": ""}}
    ).json()

    # Compared against a freshly built Settings rather than the literal 3:
    # that literal is the field's default, which the code is free to change,
    # so a test pinning it would fail for a decision rather than a bug.
    fields = {field["key"]: field for field in body}
    assert fields["phrase_min_authors"]["value"] == (Settings().phrase_min_authors)
    assert fields["phrase_min_authors"]["source"] != "settings"


def test_a_field_outside_the_seven_is_refused(tmp_path):
    """A real `Settings` field, but not one this screen offers: a UI that
    can point every run at another directory is a different and worse thing
    than a tuning screen."""
    client = seeded_client(tmp_path)

    response = client.put(
        "/api/settings", json={"values": {"output_dir": "/tmp/elsewhere"}}
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
        json={"values": {"phrase_min_authors": "7", "output_dir": "/tmp/x"}},
    )

    assert response.status_code == 400
    store = Store(api_db_path(tmp_path))
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


def test_a_validation_failures_detail_is_a_string_naming_the_field(tmp_path):
    """`detail` used to be `exc.errors()` — pydantic's list of error objects
    — the one 400 among the project's fifteen endpoints that was not a
    plain string. A generated TypeScript client would see `string |
    ValidationError[]` for this path alone. It must read as a string, and
    it must still say which field was rejected — collapsing it to a fixed
    message would lose the very thing a user needs to fix.
    """
    client = seeded_client(tmp_path)

    response = client.put(
        "/api/settings", json={"values": {"meme_potential_weight": "2.0"}}
    )

    detail = response.json()["detail"]
    assert isinstance(detail, str)
    assert "meme_potential_weight" in detail


def test_a_non_numeric_value_is_refused(tmp_path):
    """Same failure mode, cruder input. The form is a text box."""
    client = seeded_client(tmp_path)

    response = client.put(
        "/api/settings", json={"values": {"bluesky_trend_limit": "banana"}}
    )

    assert response.status_code == 400
