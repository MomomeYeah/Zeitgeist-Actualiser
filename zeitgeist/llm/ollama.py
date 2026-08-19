"""Local backend via Ollama's JSON-schema constrained output."""

import json
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from zeitgeist.llm.base import ContextLimitError, LLMError

M = TypeVar("M", bound=BaseModel)

TIMEOUT_SECONDS = 300.0

# Ollama loads a model at OLLAMA_CONTEXT_LENGTH (4096 by default) no
# matter how much context the model itself supports, so the window is
# stated per call rather than inherited from whatever the server was
# started with.
DEFAULT_NUM_CTX = 8192

# num_predict is a cap on the reply, but the reply shares the window
# with the prompt. A stage asking for a big reply needs room for both,
# and this is the slice left for the prompt.
PROMPT_RESERVE_TOKENS = 4096


class OllamaProvider:
    name = "ollama"

    def __init__(
        self,
        host: str,
        model: str,
        client: Any = None,
        *,
        think: bool | None = False,
        num_ctx: int = DEFAULT_NUM_CTX,
    ) -> None:
        if client is None:
            import httpx

            client = httpx.Client()
        self._client = client
        # Public: the factory wires these from Settings, and tests assert it.
        self.host = host.rstrip("/")
        self.model = model
        # Thinking is off because these stages want a filled-in schema, not
        # reasoning: a thinking model spends the window on reasoning tokens
        # and is cut off mid-thought, returning empty content. None omits
        # the key for a backend that rejects it outright.
        self._think = think
        self._num_ctx = num_ctx

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
            if self._think is not None:
                body["think"] = self._think

            # Ollama spells the output cap num_predict. Left unset the
            # reply is bounded only by the window.
            options: dict[str, Any] = {"num_ctx": self._num_ctx}
            if max_tokens is not None:
                options["num_predict"] = max_tokens
                options["num_ctx"] = max(
                    self._num_ctx, max_tokens + PROMPT_RESERVE_TOKENS
                )
            body["options"] = options

            try:
                response = self._client.post(
                    f"{self.host}/api/chat",
                    json=body,
                    timeout=TIMEOUT_SECONDS,
                )
                response.raise_for_status()
                payload = response.json()
                content = payload["message"]["content"]
            except Exception as exc:
                last_error = str(exc)
            else:
                # A reply that ran out of room arrives as 200 OK with
                # content empty or half-written, which json.loads reports
                # as a parse error at char 0 as though the model had
                # emitted prose. Only done_reason tells the two apart,
                # and the retry sends a longer prompt, so it truncates
                # in exactly the same place.
                if payload.get("done_reason") == "length":
                    raise ContextLimitError(_truncation_message(schema, options))

                try:
                    return schema.model_validate(json.loads(content))
                except (json.JSONDecodeError, ValidationError) as exc:
                    last_error = str(exc)

            attempt_prompt = (
                f"{prompt}\n\nYour previous response failed validation:\n"
                f"{last_error}\n\nReturn a corrected response."
            )

        raise LLMError(f"Ollama did not return a valid {schema.__name__}: {last_error}")


def _truncation_message(schema: type[BaseModel], options: dict[str, Any]) -> str:
    budget = options.get("num_predict")
    asked_for = "" if budget is None else f" with num_predict={budget}"
    return (
        f"Ollama truncated its {schema.__name__} response: the reply did "
        f"not fit num_ctx={options['num_ctx']}{asked_for}. Give it a larger "
        "window or a smaller request rather than retrying."
    )
