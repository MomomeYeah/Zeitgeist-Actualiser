"""The single narrow interface every pipeline stage uses to reach a model."""

from dataclasses import dataclass, field
from typing import Protocol, TypeVar

from pydantic import BaseModel

M = TypeVar("M", bound=BaseModel)


class LLMError(Exception):
    """Raised when a provider cannot return a valid structured response."""


class LLMProvider(Protocol):
    """Every stage needs the same thing: a validated structured object.

    Keeping this to one method is what makes the local-versus-cloud
    comparison honest — swapping backends changes one config value and
    nothing else.
    """

    name: str

    def complete(
        self, prompt: str, schema: type[M], *, system: str | None = None
    ) -> M: ...


@dataclass
class LLMCall:
    prompt: str
    system: str | None
    schema: type[BaseModel]


@dataclass
class FakeLLMProvider:
    """Test double returning queued responses and recording prompts.

    A queued ``Exception`` is raised rather than returned, so tests can
    exercise the degradation paths every stage is required to have.
    """

    responses: list[BaseModel | Exception] = field(default_factory=list)
    name: str = "fake"
    calls: list[LLMCall] = field(default_factory=list)

    def complete(self, prompt: str, schema: type[M], *, system: str | None = None) -> M:
        self.calls.append(LLMCall(prompt=prompt, system=system, schema=schema))
        if not self.responses:
            raise AssertionError(
                f"FakeLLMProvider: no queued response for {schema.__name__}"
            )
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        if not isinstance(response, schema):
            raise AssertionError(
                f"FakeLLMProvider: expected {schema.__name__}, "
                f"got {type(response).__name__}"
            )
        return response
