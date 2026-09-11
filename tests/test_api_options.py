import json

import pytest

from tests.api_factory import api_settings, seeded_client


@pytest.fixture(autouse=True)
def _no_real_ollama(monkeypatch):
    """`read_options` calls `available_models`, which builds its own
    `httpx.Client` and gets `/api/tags`. Left alone, every test in this
    module reaches whatever Ollama the developer happens to be running:
    `conftest` strips `OLLAMA_HOST`, so the host falls back to the real
    default and the result depends on who runs the suite — exactly the
    hermeticity the autouse fixture exists to guarantee.

    `test_llm_registry.py` injects a fake client for this reason; this module
    has no seam to inject through, so the host is pointed at a port nothing
    listens on instead. `ollama_models` swallows the refusal and reports an
    empty list, which is the CI shape.
    """
    monkeypatch.setenv("OLLAMA_HOST", "http://127.0.0.1:9")


def test_a_stopped_ollama_leaves_the_dropdown_empty_rather_than_500ing(tmp_path):
    """The settings screen has to render when Ollama is not running. The
    registry's own test proves `ollama_models` swallows the error; this
    proves the endpoint above it does not reintroduce one."""
    client = seeded_client(tmp_path)

    response = client.get("/api/config/options")

    assert response.status_code == 200
    assert response.json()["models"]["ollama"] == []


def test_the_api_key_is_reported_as_a_boolean_and_never_returned(tmp_path, monkeypatch):
    """The spec is explicit: the key itself is never returned. The New run
    screen needs to know whether the Anthropic provider is usable, and a
    boolean is the whole of what that needs.
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-secret-value")
    client = seeded_client(tmp_path)

    response = client.get("/api/config/options")

    assert response.json()["anthropic_key_present"] is True
    assert "sk-ant-secret-value" not in response.text


def test_the_key_is_absent_when_it_is_unset(tmp_path):
    """The inverse, and the one that decides whether the screen offers the
    Anthropic provider at all. A field hardcoded True would offer a provider
    that fails on its first call."""
    client = seeded_client(tmp_path)

    assert client.get("/api/config/options").json()["anthropic_key_present"] is False


def test_platforms_report_which_are_actually_usable(tmp_path):
    """Lemmy and Wikipedia are dormant: their code and tests remain but no
    live stage consumes a flat item list, and `Settings` rejects them. A
    screen offering them would let the user configure a run that cannot
    start.
    """
    client = seeded_client(tmp_path)

    platforms = {
        p["name"]: p["enabled"]
        for p in client.get("/api/config/options").json()["platforms"]
    }

    assert platforms["bluesky"] is True
    assert platforms["lemmy"] is False


def test_templates_report_the_slots_their_manifests_declare(tmp_path):
    """The manual generation panel in phase 4 draws one caption input per
    slot. Reporting ids alone — or the key with an empty list, which
    `"slots" in template` cannot tell apart, because `TemplateOption` declares
    the field and so FastAPI always emits it — would leave that panel unable
    to render a form for a template it had not hardcoded.

    The expectation is read out of the manifests on disk rather than written
    here as `["rejected", "preferred"]`. Those names are a manifest author's
    to change, so a literal would fire on a deliberate edit while catching no
    bug. It reads `templates_dir` — the same directory the endpoint loads
    from, so the two cannot drift — but parses it here directly rather than
    through `load_templates`, which is part of what is under test.
    """
    library = api_settings(tmp_path).templates_dir
    manifests = {
        path.stem: [slot["name"] for slot in json.loads(path.read_text())["slots"]]
        for path in library.glob("*.json")
    }
    client = seeded_client(tmp_path)

    templates = {
        template["id"]: template["slots"]
        for template in client.get("/api/config/options").json()["templates"]
    }

    assert manifests, "no shipped manifests found; the assertion is vacuous"
    assert templates == manifests


def test_the_env_defaults_report_the_configured_value(tmp_path, monkeypatch):
    """The New run screen pre-fills its cards from these. A field reported
    with the wrong value is worse than a blank one: the user sees a number
    that is not what the next run would actually use.

    The value is set here and read back, rather than asserting a key is
    present — presence is guaranteed by the comprehension over
    `RUN_OVERRIDE_KEYS` and would pass for a dict of hardcoded zeros.
    """
    monkeypatch.setenv("TOPIC_COUNT", "9")
    client = seeded_client(tmp_path)

    defaults = client.get("/api/config/options").json()["defaults"]

    assert defaults["topic_count"] == "9"
    assert "anthropic_api_key" not in defaults


def test_the_defaults_follow_a_value_the_settings_screen_saved(tmp_path):
    """Found by running a real run, not by a fixture: after the settings
    screen lowered `bluesky_trend_limit` to 4, the New run screen still read
    "of 25 trends analysed" — and the run it started really did analyse 4.

    `read_options` read `app.state.settings`, frozen once at startup, where
    `init_settings` outranks the settings table. The same bug
    `test_a_get_after_a_put_reports_the_new_value` pins for
    `GET /api/settings`, one endpoint over. Both requests share one
    `TestClient`, and so the one frozen object that served the stale value.
    """
    client = seeded_client(tmp_path)

    client.put("/api/settings", json={"values": {"bluesky_trend_limit": "4"}})
    defaults = client.get("/api/config/options").json()["defaults"]

    assert defaults["bluesky_trend_limit"] == "4"
