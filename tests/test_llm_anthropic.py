from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from zeitgeist.llm.anthropic import AnthropicProvider
from zeitgeist.llm.base import LLMError


class Answer(BaseModel):
    value: str


def _tool_response(payload: dict) -> SimpleNamespace:
    block = SimpleNamespace(type="tool_use", name="respond", input=payload)
    return SimpleNamespace(content=[block])


class StubClient:
    """Stands in for anthropic.Anthropic; records kwargs, replays responses."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.requests = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.requests.append(kwargs)
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


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
    client = StubClient([SimpleNamespace(content=[]), SimpleNamespace(content=[])])
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
