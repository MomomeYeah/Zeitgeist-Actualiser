"""Anthropic backend. Uses tool use, the most reliable structured-output path."""

from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from zeitgeist.llm.base import LLMError

M = TypeVar("M", bound=BaseModel)

TOOL_NAME = "respond"
MAX_TOKENS = 4096


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, api_key: str, model: str, client: Any = None) -> None:
        if client is None:
            from anthropic import Anthropic

            client = Anthropic(api_key=api_key)
        self._client = client
        # Public: the factory wires these from Settings, and tests assert it.
        self.model = model

    def complete(self, prompt: str, schema: type[M], *, system: str | None = None) -> M:
        tool = {
            "name": TOOL_NAME,
            "description": schema.__doc__ or f"Return a {schema.__name__}.",
            "input_schema": schema.model_json_schema(),
        }
        attempt_prompt = prompt
        last_error: str | None = None

        for _ in range(2):
            kwargs: dict[str, Any] = {
                "model": self.model,
                "max_tokens": MAX_TOKENS,
                "tools": [tool],
                "tool_choice": {"type": "tool", "name": TOOL_NAME},
                "messages": [{"role": "user", "content": attempt_prompt}],
            }
            if system is not None:
                kwargs["system"] = system

            response = self._client.messages.create(**kwargs)
            payload = _extract_tool_input(response)

            if payload is None:
                last_error = "no tool_use block in response"
            else:
                try:
                    return schema.model_validate(payload)
                except ValidationError as exc:
                    last_error = str(exc)

            attempt_prompt = (
                f"{prompt}\n\nYour previous response failed validation:\n"
                f"{last_error}\n\nReturn a corrected response."
            )

        raise LLMError(
            f"Anthropic did not return a valid {schema.__name__}: {last_error}"
        )


def _extract_tool_input(response: Any) -> dict | None:
    for block in getattr(response, "content", []):
        if getattr(block, "type", None) == "tool_use":
            return block.input
    return None
