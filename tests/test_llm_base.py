import pytest
from pydantic import BaseModel

from zeitgeist.llm.base import FakeLLMProvider, LLMError


class Answer(BaseModel):
    value: str


class Other(BaseModel):
    number: int


def test_returns_queued_responses_in_order():
    provider = FakeLLMProvider([Answer(value="first"), Answer(value="second")])
    assert provider.complete("p1", Answer).value == "first"
    assert provider.complete("p2", Answer).value == "second"


def test_records_each_call():
    provider = FakeLLMProvider([Answer(value="x")])
    provider.complete("the prompt", Answer, system="the system")
    assert len(provider.calls) == 1
    assert provider.calls[0].prompt == "the prompt"
    assert provider.calls[0].system == "the system"
    assert provider.calls[0].schema is Answer


def test_raises_when_queue_is_empty():
    provider = FakeLLMProvider()
    with pytest.raises(AssertionError, match="no queued response"):
        provider.complete("p", Answer)


def test_raises_when_queued_response_has_wrong_schema():
    provider = FakeLLMProvider([Other(number=1)])
    with pytest.raises(AssertionError, match="expected Answer"):
        provider.complete("p", Answer)


def test_queued_exception_is_raised():
    provider = FakeLLMProvider([LLMError("model exploded")])
    with pytest.raises(LLMError, match="model exploded"):
        provider.complete("p", Answer)


def test_call_recorded_when_queue_is_empty():
    """Catches append moved below guard; later tasks read calls for failures."""
    provider = FakeLLMProvider()
    with pytest.raises(AssertionError):
        provider.complete("failed prompt", Answer)
    assert len(provider.calls) == 1
    assert provider.calls[0].prompt == "failed prompt"


def test_call_recorded_when_exception_is_raised():
    """Catches append moved below guard; later tasks read calls for failures."""
    provider = FakeLLMProvider([LLMError("boom")])
    with pytest.raises(LLMError):
        provider.complete("another failed prompt", Answer)
    assert len(provider.calls) == 1
    assert provider.calls[0].prompt == "another failed prompt"
