from typing import Any

import httpx

from zeitgeist.config import Settings
from zeitgeist.llm.registry import available_models, ollama_models


class _FakeClient:
    """Stands in for `httpx.Client`. The suite is hermetic: no test here may
    reach a real Ollama, and a test that did would pass or fail according to
    whether the developer happened to have one running."""

    def __init__(self, payload: Any = None, error: Exception | None = None) -> None:
        self._payload = payload
        self._error = error
        self.urls: list[str] = []

    def get(self, url: str, timeout: float | None = None) -> Any:
        self.urls.append(url)
        if self._error is not None:
            raise self._error
        return httpx.Response(200, json=self._payload)


def test_ollama_models_are_read_from_what_is_installed():
    """The point of querying rather than hardcoding: a model the user pulled
    must appear without a code change. A static list would leave the dropdown
    permanently wrong for anyone running local models."""
    client = _FakeClient({"models": [{"name": "qwen3.5"}, {"name": "llama3"}]})

    assert ollama_models("http://localhost:11434", client=client) == [
        "qwen3.5",
        "llama3",
    ]


def test_ollama_being_down_yields_no_models_rather_than_an_error():
    """The settings screen must render when Ollama is not running. Letting
    the connection error escape would make the whole screen unreachable
    because a local daemon happened to be stopped."""
    client = _FakeClient(error=httpx.ConnectError("refused"))

    assert ollama_models("http://localhost:11434", client=client) == []


def test_a_malformed_ollama_reply_yields_no_models():
    """`/api/tags` is an external contract this project does not own. A reply
    without the shape we expect must degrade to an empty dropdown, not a
    KeyError that 500s the settings screen."""
    client = _FakeClient({"unexpected": True})

    assert ollama_models("http://localhost:11434", client=client) == []


def test_ollama_models_closes_the_client_it_owns_when_none_is_injected(monkeypatch):
    """Without an injected client, `ollama_models` used to build a bare
    `httpx.Client()` and never close it: every `GET /api/config/options`
    with no client injected — the real production path — leaked a
    connection pool until GC happened to collect it.

    Standing in for `httpx.Client` with a tracking double, since the suite
    must stay hermetic and cannot reach a real Ollama, proves the owned
    client is closed via its context manager. The injectable-client seam
    the tests above rely on is untouched: `_FakeClient` has no
    `__enter__`/`__exit__` at all, and would raise `AttributeError` the
    moment this path tried to use it as one.
    """
    created: list[Any] = []

    class _TrackingClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            self.closed = False
            created.append(self)

        def __enter__(self) -> _TrackingClient:
            return self

        def __exit__(self, *exc_info: object) -> None:
            self.closed = True

        def get(self, url: str, timeout: float | None = None) -> Any:
            return httpx.Response(200, json={"models": []})

    monkeypatch.setattr(httpx, "Client", _TrackingClient)

    result = ollama_models("http://localhost:11434")

    assert result == []
    assert len(created) == 1
    assert created[0].closed is True


def test_available_models_reports_both_providers(tmp_path):
    """The New run screen swaps the model list when the provider changes, so
    it needs both at once. Returning only the configured provider's models
    would make that swap require a second request the screen does not make.
    """
    client = _FakeClient({"models": [{"name": "qwen3.5"}]})
    settings = Settings(_env_file=None, db_path=tmp_path / "z.db")

    models = available_models(settings, client=client)

    # Presence rather than equality against `ANTHROPIC_MODELS`: comparing the
    # function's output to the constant it is built from is true whatever
    # either one says, and pinning the exact list would fire the next time
    # Anthropic ships a model.
    assert set(models) == {"anthropic", "ollama"}
    assert models["anthropic"]
    assert models["ollama"] == ["qwen3.5"]
