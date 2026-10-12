"""The one seam between this package's vision-derivation code and a model — mirrors
`capture/fetcher.py`'s `Fetcher` pattern exactly. `OllamaClient` is a `Protocol`;
`HttpOllamaClient` (the only implementation that can reach a real model) is wired up once,
at the composition root, and nothing under `tests/` ever constructs it.

CLAUDE.md names local Ollama as the stack's LLM/vision provider "always behind a provider
abstraction" — this module is that abstraction for CI's two derivation paths (listing-field
extraction, review-screenshot classification). C15 (local-only derivation) is satisfied
structurally: `HttpOllamaClient` only ever talks to a caller-supplied host, which in every
deployment of this codebase is `localhost` — no hosted provider is reachable through this
seam at all, let alone conditionally.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Protocol

import httpx

from competitor_intelligence.evidence.ollama_errors import describe_ollama_error


class OllamaUnavailable(Exception):
    """The model server could not be reached, timed out, or returned a non-2xx response —
    never a reason to fabricate a result. Callers treat this as "extraction failed," on the
    same terms as an illegible screenshot (E12b) or an outright unusable one (E3)."""


class OllamaClient(Protocol):
    def generate(self, *, model: str, prompt: str, image_bytes: bytes) -> str: ...


@dataclass(frozen=True, slots=True)
class HttpOllamaClient:
    """Calls Ollama's `/api/generate` with `stream=False` — a single JSON response, not an
    event stream, keeping this client a plain request/response call like `HttpxFetcher`."""

    host: str
    timeout_seconds: float = 60.0
    # Ollama unloads an idle model after its own default (5 min) and reloads it on the next call;
    # that cold start was measured at ~140 s for llava on a CPU host. `None` leaves Ollama's
    # default untouched; an operator can pass e.g. "30m" to keep the model resident.
    keep_alive: str | None = None

    def generate(self, *, model: str, prompt: str, image_bytes: bytes) -> str:
        image_b64 = base64.b64encode(image_bytes).decode("ascii")
        payload: dict[str, object] = {"model": model, "prompt": prompt, "images": [image_b64], "stream": False}
        if self.keep_alive is not None:
            payload["keep_alive"] = self.keep_alive
        try:
            response = httpx.post(
                f"{self.host}/api/generate",
                json=payload,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise OllamaUnavailable(f"Ollama request failed: {describe_ollama_error(exc, model)}") from None

        body = response.json()
        text = body.get("response")
        if not isinstance(text, str):
            raise OllamaUnavailable("Ollama response had no 'response' text field")
        return text
