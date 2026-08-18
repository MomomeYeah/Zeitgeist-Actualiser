from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from zeitgeist.llm.anthropic import MAX_TOKENS, AnthropicProvider
from zeitgeist.llm.base import LLMError


class Answer(BaseModel):
    value: str


def _tool_response(payload: dict, stop_reason: str = "tool_use") -> SimpleNamespace:
    block = SimpleNamespace(type="tool_use", name="respond", input=payload)
    return SimpleNamespace(content=[block], stop_reason=stop_reason)


def _truncated_response() -> SimpleNamespace:
    """What the API actually returns when the reply outgrows max_tokens: the
    tool_use block survives but its accumulated JSON is unparseable, so the
    input arrives empty. Only stop_reason distinguishes it from a model that
    genuinely answered with an empty object.
    """
    return _tool_response({}, stop_reason="max_tokens")


class _StubStream:
    def __init__(self, response):
        self._response = response

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def get_final_message(self):
        return self._response


class StubClient:
    """Stands in for anthropic.Anthropic; records kwargs, replays responses."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.requests = []
        self.messages = SimpleNamespace(stream=self._stream)

    def _stream(self, **kwargs):
        self.requests.append(kwargs)
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return _StubStream(response)


def _provider(client) -> AnthropicProvider:
    return AnthropicProvider(api_key="k", model="claude-test", client=client)


def test_returns_validated_model():
    provider = _provider(StubClient([_tool_response({"value": "hello"})]))
    assert provider.complete("prompt", Answer).value == "hello"


def test_sends_the_schema_as_the_tool_contract():
    """The request payload is our contract with the API. A wrong tool name,
    a missing tool_choice, or a schema that is not the one asked for all
    produce unstructured replies at runtime and nothing else catches them.
    """
    client = StubClient([_tool_response({"value": "hello"})])
    _provider(client).complete("prompt", Answer, system="be terse")

    request = client.requests[0]
    assert request["model"] == "claude-test"
    assert request["system"] == "be terse"
    assert request["messages"] == [{"role": "user", "content": "prompt"}]
    assert request["tool_choice"] == {"type": "tool", "name": "respond"}
    assert request["tools"][0]["name"] == "respond"
    assert request["tools"][0]["input_schema"] == Answer.model_json_schema()


def test_system_key_is_absent_when_no_system_prompt_is_given():
    """Sending system=None is an API error, so the key must be omitted
    entirely rather than passed as null.
    """
    client = StubClient([_tool_response({"value": "hello"})])
    _provider(client).complete("prompt", Answer)
    assert "system" not in client.requests[0]


def test_retries_once_with_the_validation_error_appended():
    client = StubClient(
        [_tool_response({"wrong": 1}), _tool_response({"value": "recovered"})]
    )
    assert _provider(client).complete("prompt", Answer).value == "recovered"

    retry_prompt = client.requests[1]["messages"][0]["content"]
    assert "prompt" in retry_prompt
    assert "value" in retry_prompt, "the retry must tell the model what was wrong"


def test_gives_up_after_exactly_two_attempts():
    """Bounds the retry: an unbounded loop against a model that always
    returns garbage would spend money until the process is killed.
    """
    client = StubClient(
        [
            _tool_response({"wrong": 1}),
            _tool_response({"bad": 2}),
            _tool_response({"value": "never reached"}),
        ]
    )
    provider = _provider(client)
    with pytest.raises(LLMError, match="Answer"):
        provider.complete("prompt", Answer)
    assert len(client.requests) == 2


def test_raises_when_no_tool_use_block_returned():
    """A text-only reply must not be mistaken for a valid empty result."""
    empty = SimpleNamespace(content=[], stop_reason="end_turn")
    client = StubClient([empty, empty])
    with pytest.raises(LLMError):
        _provider(client).complete("prompt", Answer)


def test_transport_failure_is_retried_and_can_recover():
    """A connection drop on the first attempt must not escape raw — it gets
    the same one retry a validation failure gets.
    """
    boom = RuntimeError("connection refused")
    client = StubClient([boom, _tool_response({"value": "recovered"})])
    assert _provider(client).complete("prompt", Answer).value == "recovered"


def test_transport_failure_on_both_attempts_raises_llm_error():
    """Exhausting the retry budget on transport errors must surface as
    LLMError, not the raw exception, matching the validation-failure path.
    """
    boom = RuntimeError("connection refused")
    client = StubClient([boom, boom])
    with pytest.raises(LLMError, match="Answer"):
        _provider(client).complete("prompt", Answer)
    assert len(client.requests) == 2


def test_truncated_response_raises_a_truncation_error_without_retrying():
    """A reply cut off at max_tokens loses its tool JSON and arrives as an
    empty input, which pydantic reports as a missing required field. Retrying
    re-sends the same oversized request and truncates identically, so the
    budget must be named and the second attempt skipped.
    """
    client = StubClient([_truncated_response(), _tool_response({"value": "unused"})])
    with pytest.raises(LLMError, match="max_tokens"):
        _provider(client).complete("prompt", Answer)
    assert len(client.requests) == 1, "retrying a truncated reply only burns money"


def test_sends_the_default_token_budget():
    client = StubClient([_tool_response({"value": "hello"})])
    _provider(client).complete("prompt", Answer)
    assert client.requests[0]["max_tokens"] == MAX_TOKENS


def test_caller_can_raise_the_token_budget_for_a_larger_schema():
    """Response size is a property of the schema, not the provider: a stage
    whose output grows with its input needs a budget the default cannot cover.
    """
    client = StubClient([_tool_response({"value": "hello"})])
    _provider(client).complete("prompt", Answer, max_tokens=32768)
    assert client.requests[0]["max_tokens"] == 32768
