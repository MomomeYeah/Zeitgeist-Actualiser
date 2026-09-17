from tests.api_factory import api_db_path, seed_settings, seeded_client
from tests.test_api_control import wait_for_idle
from zeitgeist.config import Settings, load_settings
from zeitgeist.store import Store


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


def test_a_field_outside_settable_keys_is_refused(tmp_path):
    """A real `Settings` field, but not one either scope declares: a UI that
    can point every run at another directory is a different and worse thing
    than a tuning screen."""
    client = seeded_client(tmp_path)

    response = client.put(
        "/api/settings", json={"values": {"output_dir": "/tmp/elsewhere"}}
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


def test_the_read_returns_every_scoped_field_in_key_order(tmp_path):
    """The fourteen keys written out rather than `GLOBAL_KEYS | RUN_KEYS`:
    the endpoint builds its list from that same union, so comparing against
    it asserts only that a set equals itself, and a field that silently lost
    its scope annotation would vanish from both sides at once.

    Compared as a list, because the contract says sorted by key.
    """
    client = seeded_client(tmp_path)

    fields = client.get("/api/settings").json()

    assert [field["key"] for field in fields] == [
        "anthropic_api_key",
        "bluesky_fetch_concurrency",
        "bluesky_posts_per_trend",
        "bluesky_trend_limit",
        "distil_char_budget",
        "distil_concurrency",
        "font_path",
        "llm_model",
        "llm_provider",
        "meme_potential_weight",
        "ollama_host",
        "phrase_min_authors",
        "sources",
        "topic_count",
    ]


def test_each_field_reports_the_scope_it_was_declared_with(tmp_path):
    client = seeded_client(tmp_path)

    by_key = {field["key"]: field for field in client.get("/api/settings").json()}

    assert by_key["anthropic_api_key"]["scope"] == "global"
    assert by_key["topic_count"]["scope"] == "run"


def test_a_stored_value_is_reported_as_stored_and_an_unstored_one_as_default(
    tmp_path,
):
    """Both halves in one test because `source` is only meaningful as a
    contrast: an implementation returning "settings" unconditionally would
    pass either assertion alone."""
    client = seeded_client(tmp_path)
    client.put("/api/settings", json={"values": {"topic_count": "9"}})

    by_key = {field["key"]: field for field in client.get("/api/settings").json()}

    assert by_key["topic_count"] == {
        "key": "topic_count",
        "value": 9,
        "scope": "run",
        "source": "settings",
        "secret": False,
    }
    assert by_key["distil_char_budget"]["source"] == "default"


def test_the_api_key_never_comes_back_in_any_form(tmp_path):
    """Asserted over the whole serialised body, not just the key's own row:
    the value must not reach the client through `defaults`, an error message
    or anything else either."""
    client = seeded_client(tmp_path)
    client.put("/api/settings", json={"values": {"anthropic_api_key": "sk-ant-secret"}})

    settings_body = client.get("/api/settings").text
    options_body = client.get("/api/config/options").text

    assert "sk-ant-secret" not in settings_body
    assert "sk-ant-secret" not in options_body


def test_the_api_key_reports_that_it_is_set_without_reporting_what_it_is(
    tmp_path,
):
    client = seeded_client(tmp_path)
    client.put("/api/settings", json={"values": {"anthropic_api_key": "sk-ant-secret"}})

    by_key = {field["key"]: field for field in client.get("/api/settings").json()}

    assert by_key["anthropic_api_key"] == {
        "key": "anthropic_api_key",
        "value": None,
        "scope": "global",
        "source": "settings",
        "secret": True,
    }


def test_clearing_the_api_key_leaves_the_run_screen_saying_no_key_is_present(
    tmp_path,
):
    """The two endpoints have to agree: a cleared key must not leave New run
    still advertising one."""
    client = seeded_client(tmp_path)
    client.put("/api/settings", json={"values": {"anthropic_api_key": "sk-ant-x"}})
    assert client.get("/api/config/options").json()["anthropic_key_present"] is True

    client.put("/api/settings", json={"values": {"anthropic_api_key": ""}})

    assert client.get("/api/config/options").json()["anthropic_key_present"] is False


def test_a_path_valued_field_round_trips_as_the_string_the_put_accepts(tmp_path):
    """`font_path` is a `Path` on the model and has no JSON form: returned
    raw it fails `SettingField`'s union outright, and returned as anything
    but the string the `PUT` takes back it cannot be re-saved. Nothing else
    in this task stores a Path, so without this the `isinstance(value, Path)`
    branch of `_display` can be deleted with the suite staying green.

    A bare filename rather than an absolute one, because `str(Path(...))`
    rewrites separators per platform and a Windows run would turn
    "C:/Windows/..." into backslashes. "impact.ttf" is its own `str`
    everywhere, so the expected value stays a hand-derived literal.
    """
    client = seeded_client(tmp_path)

    response = client.put("/api/settings", json={"values": {"font_path": "impact.ttf"}})

    assert response.status_code == 200
    by_key = {field["key"]: field for field in client.get("/api/settings").json()}
    assert by_key["font_path"] == {
        "key": "font_path",
        "value": "impact.ttf",
        "scope": "global",
        "source": "settings",
        "secret": False,
    }
    # The other declared type with no JSON form: joined, not returned as a
    # list, because `SettingsUpdate` takes it back as a CSV string.
    assert by_key["sources"]["value"] == "bluesky"


def test_a_global_field_is_writable_here(tmp_path):
    client = seeded_client(tmp_path)

    response = client.put(
        "/api/settings", json={"values": {"ollama_host": "http://10.0.0.2:11434"}}
    )

    assert response.status_code == 200
    by_key = {field["key"]: field for field in response.json()}
    assert by_key["ollama_host"]["value"] == "http://10.0.0.2:11434"


def test_an_unscoped_field_is_refused(tmp_path):
    client = seeded_client(tmp_path)

    response = client.put(
        "/api/settings", json={"values": {"templates_dir": "/tmp/mine"}}
    )

    assert response.status_code == 400
    assert "templates_dir" in response.json()["detail"]


def test_a_rejected_request_writes_none_of_its_fields(tmp_path):
    """All-or-nothing, pinned on the side effect rather than the status: a
    handler that validated after writing would still answer 400 here while
    having already saved the good field."""
    client = seeded_client(tmp_path)

    client.put(
        "/api/settings",
        json={"values": {"topic_count": "7", "meme_potential_weight": "2.0"}},
    )

    by_key = {field["key"]: field for field in client.get("/api/settings").json()}
    assert by_key["topic_count"]["source"] == "default"
    assert by_key["topic_count"]["value"] == 5


def test_a_global_field_is_not_accepted_as_a_per_run_override(tmp_path):
    """`bluesky_fetch_concurrency` is global now: a run may not set it.

    `execute` is supplied even though nothing should reach it. Under the
    very mutation this test names — `enqueue` keyed on `GLOBAL_KEYS |
    RUN_KEYS` rather than `RUN_KEYS` — the request is accepted, and without
    a seam the real pipeline would start against the live Bluesky API on
    whoever's machine is running the suite. The empty `started` list is the
    second half of the assertion, and the detail check keeps an unrelated
    400 from satisfying this.
    """
    started: list[str] = []

    def execute(settings, request, store, observer, token):
        started.append(request.run_id or "")

    client = seeded_client(tmp_path, execute=execute)

    response = client.post(
        "/api/runs", json={"overrides": {"bluesky_fetch_concurrency": "2"}}
    )

    assert response.status_code == 400
    assert "bluesky_fetch_concurrency" in response.json()["detail"]
    assert started == []


def test_a_value_saved_here_is_used_by_a_run_started_afterwards(tmp_path):
    """The staleness class that produced two separate endpoint workarounds,
    pinned against the mechanism: what the worker actually froze, not what a
    second GET reported.
    """
    frozen: list[int] = []

    def execute(settings, request, store, observer, token):
        frozen.append(settings.topic_count)

    client = seeded_client(tmp_path, execute=execute)
    client.put("/api/settings", json={"values": {"topic_count": "9"}})

    client.post("/api/runs", json={})
    wait_for_idle(client)  # existing helper in tests/test_api_control.py

    assert frozen == [9]
