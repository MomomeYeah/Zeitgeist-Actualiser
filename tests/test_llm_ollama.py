import json
from collections.abc import Sequence
from typing import Any

import pytest
from pydantic import BaseModel

from zeitgeist.llm.base import ContextLimitError, LLMError
from zeitgeist.llm.ollama import (
    DEFAULT_NUM_CTX,
    PROMPT_RESERVE_TOKENS,
    OllamaProvider,
)


class Answer(BaseModel):
    value: str


class StubResponse:
    """Ollama replies with the model's text in message.content."""

    def __init__(
        self,
        content: str,
        error: Exception | None = None,
        done_reason: str = "stop",
    ):
        self._content = content
        self._error = error
        self._done_reason = done_reason

    def raise_for_status(self):
        if self._error is not None:
            raise self._error

    def json(self):
        return {
            "message": {"content": self._content},
            "done_reason": self._done_reason,
        }


class StubClient:
    """Replays raw response bodies so malformed output is as easy to stage
    as valid output — no subclassing needed per case.
    """

    # Sequence[Any], not list[StubResponse]: tests stage malformed bodies
    # with purpose-built local classes, and list is invariant.
    def __init__(self, responses: Sequence[Any]):
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


def test_transport_failure_is_retried_and_can_recover():
    """A connection drop on the first attempt must not escape raw — it gets
    the same one retry a validation failure gets.
    """
    boom = RuntimeError("connection refused")
    client = StubClient([StubResponse("", error=boom), _ok({"value": "recovered"})])
    assert _provider(client).complete("prompt", Answer).value == "recovered"


def test_transport_failure_on_both_attempts_raises_llm_error():
    """Exhausting the retry budget on a stopped Ollama server must surface
    as LLMError, not the raw connection exception.
    """
    boom = RuntimeError("connection refused")
    client = StubClient([StubResponse("", error=boom), StubResponse("", error=boom)])
    with pytest.raises(LLMError, match="Answer"):
        _provider(client).complete("prompt", Answer)
    assert len(client.requests) == 2


def test_error_shaped_response_is_retried_not_a_raw_keyerror():
    """A malformed body (e.g. an error payload with no message.content) must
    be treated like any other retryable failure, not crash with KeyError.
    """

    class ErrorShapedResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"error": "model not found"}

    client = StubClient([ErrorShapedResponse(), _ok({"value": "recovered"})])
    assert _provider(client).complete("prompt", Answer).value == "recovered"


def test_thinking_is_disabled_by_default():
    """A thinking model spends its whole context window on reasoning tokens
    and gets cut off before emitting any JSON, returning empty content.
    """
    client = StubClient([_ok({"value": "hello"})])
    _provider(client).complete("prompt", Answer)
    assert client.requests[0][1]["think"] is False


def test_thinking_key_is_omitted_when_set_to_none():
    """Escape hatch for a backend that rejects `think` outright."""
    client = StubClient([_ok({"value": "hello"})])
    OllamaProvider(host="http://h", model="m", client=client, think=None).complete(
        "prompt", Answer
    )
    assert "think" not in client.requests[0][1]


def test_sets_an_explicit_context_window():
    """Ollama defaults to 4096 regardless of what the model supports, so the
    window has to be stated rather than inherited from the server.
    """
    client = StubClient([_ok({"value": "hello"})])
    _provider(client).complete("prompt", Answer)
    assert client.requests[0][1]["options"]["num_ctx"] == DEFAULT_NUM_CTX


def test_context_window_grows_to_hold_the_reply_budget():
    """num_predict cannot exceed the context window: a 32k reply budget in a
    4096-token window silently truncates instead of erroring.
    """
    client = StubClient([_ok({"value": "hello"})])
    _provider(client).complete("prompt", Answer, max_tokens=32768)

    options = client.requests[0][1]["options"]
    assert options["num_predict"] == 32768
    assert options["num_ctx"] == 32768 + PROMPT_RESERVE_TOKENS


def test_empty_content_is_retried_rather_than_crashing():
    """The observed failure: a truncated reply arrives as 200 OK with
    message.content set to the empty string.
    """
    client = StubClient([StubResponse(""), _ok({"value": "recovered"})])
    assert _provider(client).complete("prompt", Answer).value == "recovered"


def test_truncated_reply_raises_a_context_limit_error_without_retrying():
    """done_reason="length" means the reply outgrew the space for it. The
    retry appends the failure to the prompt, making it longer, so it
    truncates identically, and each attempt costs minutes on a local model.
    """
    client = StubClient([StubResponse("", done_reason="length"), _ok({"value": "x"})])
    with pytest.raises(ContextLimitError):
        _provider(client).complete("prompt", Answer)
    assert len(client.requests) == 1, "retrying a truncated reply cannot help"


def test_context_limit_error_names_the_window_and_the_schema():
    """The bare JSONDecodeError this replaces said only "line 1 column 1
    (char 0)", which reads like malformed output, not a cut-off reply.
    """
    client = StubClient([StubResponse("", done_reason="length")])
    with pytest.raises(ContextLimitError) as excinfo:
        _provider(client).complete("prompt", Answer)

    message = str(excinfo.value)
    assert "Answer" in message
    assert str(DEFAULT_NUM_CTX) in message


def test_context_limit_error_reports_the_reply_budget_when_one_was_set():
    client = StubClient([StubResponse("", done_reason="length")])
    with pytest.raises(ContextLimitError) as excinfo:
        _provider(client).complete("prompt", Answer, max_tokens=32768)
    assert "32768" in str(excinfo.value)


def test_a_context_limit_error_is_still_an_llm_error():
    """Stages degrade on LLMError; truncation must not escape that handling."""
    assert issubclass(ContextLimitError, LLMError)
