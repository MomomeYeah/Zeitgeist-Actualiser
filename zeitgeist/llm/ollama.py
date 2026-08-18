"""Local backend via Ollama's JSON-schema constrained output."""

import json
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from zeitgeist.llm.base import LLMError

M = TypeVar("M", bound=BaseModel)

TIMEOUT_SECONDS = 300.0


class OllamaProvider:
    name = "ollama"

    def __init__(self, host: str, model: str, client: Any = None) -> None:
        if client is None:
            import httpx

            client = httpx.Client()
        self._client = client
        # Public: the factory wires these from Settings, and tests assert it.
        self.host = host.rstrip("/")
        self.model = model

    def complete(
        self,
        prompt: str,
        schema: type[M],
        *,
        system: str | None = None,
        max_tokens: int | None = None,
    ) -> M:
        attempt_prompt = prompt
        last_error: str | None = None

        for _ in range(2):
            messages: list[dict[str, str]] = []
            if system is not None:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": attempt_prompt})

            body: dict[str, Any] = {
                "model": self.model,
                "messages": messages,
                "format": schema.model_json_schema(),
                "stream": False,
            }
            if max_tokens is not None:
                # Ollama spells the output cap num_predict. Left
                # unset it uses the model's own default rather than
                # an arbitrary one of ours.
                body["options"] = {"num_predict": max_tokens}

            try:
                response = self._client.post(
                    f"{self.host}/api/chat",
                    json=body,
                    timeout=TIMEOUT_SECONDS,
                )
                response.raise_for_status()
                content = response.json()["message"]["content"]
            except Exception as exc:
                last_error = str(exc)
            else:
                try:
                    return schema.model_validate(json.loads(content))
                except (json.JSONDecodeError, ValidationError) as exc:
                    last_error = str(exc)

            attempt_prompt = (
                f"{prompt}\n\nYour previous response failed validation:\n"
                f"{last_error}\n\nReturn a corrected response."
            )

        raise LLMError(f"Ollama did not return a valid {schema.__name__}: {last_error}")
