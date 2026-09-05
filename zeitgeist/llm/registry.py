"""Which models each provider offers.

Not a method on `LLMProvider`: that Protocol's docstring says keeping it to
one method is what makes the local-versus-cloud comparison honest, and model
discovery is a configuration concern rather than a per-call one.
"""

import logging
from typing import Any

from zeitgeist.config import Settings

log = logging.getLogger(__name__)

# Static because Anthropic publishes no list endpoint this app can practically
# use, and the set changes rarely. Ollama's is queried instead, because what
# is installed locally is exactly what changes often.
ANTHROPIC_MODELS: tuple[str, ...] = (
    "claude-opus-5",
    "claude-sonnet-5",
    "claude-haiku-4-5-20251001",
)

TIMEOUT_SECONDS = 2.0


def ollama_models(
    host: str, client: Any = None, timeout: float = TIMEOUT_SECONDS
) -> list[str]:
    """What Ollama has pulled locally, or nothing if it cannot be asked.

    Never raises. The settings screen has to render when Ollama is not
    running, and a 500 there would make the screen unreachable because a
    local daemon happened to be stopped.

    The timeout is short on purpose: this is called to draw a dropdown, and
    a stopped daemon should cost a moment, not the request's whole budget.
    """
    if client is None:
        import httpx

        client = httpx.Client()
    try:
        response = client.get(f"{host.rstrip('/')}/api/tags", timeout=timeout)
        payload = response.json()
        return [entry["name"] for entry in payload["models"]]
    except Exception as exc:  # noqa: BLE001 - an empty dropdown, never a 500
        log.debug("Could not list Ollama models at %s: %s", host, exc)
        return []


def available_models(settings: Settings, client: Any = None) -> dict[str, list[str]]:
    """Both providers' models, so the New run screen can swap its list when
    the provider changes without a second request."""
    return {
        "anthropic": list(ANTHROPIC_MODELS),
        "ollama": ollama_models(settings.ollama_host, client=client),
    }
