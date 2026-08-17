import json

import pytest
from pydantic import BaseModel

from zeitgeist.llm.base import LLMError
from zeitgeist.llm.ollama import OllamaProvider


class Answer(BaseModel):
    value: str


class StubResponse:
    """Ollama replies with the model's text in message.content."""

    def __init__(self, content: str, error: Exception | None = None):
        self._content = content
        self._error = error

    def raise_for_status(self):
        if self._error is not None:
            raise self._error

    def json(self):
        return {"message": {"content": self._content}}


class StubClient:
    """Replays raw response bodies so malformed output is as easy to stage
    as valid output — no subclassing needed per case.
    """

    def __init__(self, responses: list[StubResponse]):
        self._responses = list(responses)
        self.requests = []

    def post(self, url, json=None, timeout=None):
        self.requests.append((url, json, timeout))
        return self._responses.pop(0)


def _ok(payload: dict) -> StubResponse:
    return StubResponse(json.dumps(payload))


def _provider(client) -> OllamaProvider:
    return OllamaProvider(host="http://h", model="qwen-test", client=client)


def test_returns_validated_model():
    assert (
        _provider(StubClient([_ok({"value": "hello"})]))
        .complete("prompt", Answer)
        .value
        == "hello"
    )


def test_sends_the_schema_as_the_format_constraint():
    """Ollama only constrains output when `format` carries the JSON schema
    and streaming is off. Losing either silently returns prose.
    """
    client = StubClient([_ok({"value": "hello"})])
    _provider(client).complete("prompt", Answer, system="be terse")

    url, body, timeout = client.requests[0]
    assert url == "http://h/api/chat"
    assert body["model"] == "qwen-test"
    assert body["format"] == Answer.model_json_schema()
    assert body["stream"] is False
    assert body["messages"] == [
        {"role": "system", "content": "be terse"},
        {"role": "user", "content": "prompt"},
    ]
    assert timeout is not None, "a local model can take minutes; never unbounded"


def test_omits_the_system_message_when_none_is_given():
    client = StubClient([_ok({"value": "hello"})])
    _provider(client).complete("prompt", Answer)
    assert client.requests[0][1]["messages"] == [{"role": "user", "content": "prompt"}]


def test_trailing_slash_on_host_does_not_double_up():
    client = StubClient([_ok({"value": "hello"})])
    OllamaProvider(host="http://h/", model="m", client=client).complete(
        "prompt", Answer
    )
    assert client.requests[0][0] == "http://h/api/chat"


def test_retries_once_with_the_validation_error_appended():
    client = StubClient([_ok({"wrong": 1}), _ok({"value": "recovered"})])
    assert _provider(client).complete("prompt", Answer).value == "recovered"
    assert "value" in client.requests[1][1]["messages"][0]["content"]


def test_malformed_json_is_treated_as_a_validation_failure():
    """Small local models emit prose around their JSON often enough that
    this must be a retry, not a crash.
    """
    client = StubClient([StubResponse("not json at all"), _ok({"value": "ok"})])
    assert _provider(client).complete("prompt", Answer).value == "ok"


def test_gives_up_after_exactly_two_attempts():
    client = StubClient(
        [_ok({"wrong": 1}), _ok({"bad": 2}), _ok({"value": "never reached"})]
    )
    client_provider = _provider(client)
    with pytest.raises(LLMError, match="Answer"):
        client_provider.complete("prompt", Answer)
    assert len(client.requests) == 2


def test_http_errors_are_not_swallowed_as_validation_failures():
    """A stopped Ollama server should surface as a connection problem, not
    be retried once and reported as a schema failure.
    """
    boom = RuntimeError("connection refused")
    client = StubClient([StubResponse("", error=boom)])
    with pytest.raises(RuntimeError, match="connection refused"):
        _provider(client).complete("prompt", Answer)
