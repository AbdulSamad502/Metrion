"""`OllamaLlmProvider` - the dev `LlmProvider`, calling a local Ollama `/api/generate`.

Same request shape and fail-loud-never-fabricate contract as `cfo.reasoning.ollama_provider`
(copied, not imported: no cross-agent imports, spec C6/AC4). Text only - no image field exists.

`host` and `timeout_seconds` are REQUIRED and come from the composition root (P3 decision 11):
there is no default model, host or timeout here, and no `cmo_platform_config` key for them. The
timeout is whole seconds (the package has no floats).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import httpx

from slim_cmo.generation.provider import LlmUnavailable

# A "thinking" model's <think>...</think> block is internal reasoning, not the answer; an
# unclosed block (a truncated reply) is left as-is rather than guessed at.
_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>\s*", re.DOTALL)


@dataclass(frozen=True, slots=True)
class OllamaLlmProvider:
    host: str
    timeout_seconds: int
    transport: httpx.BaseTransport | None = None  # tests inject a mock transport

    def __post_init__(self) -> None:
        if not self.host.strip():
            raise ValueError("host is required")
        if type(self.timeout_seconds) is not int or self.timeout_seconds < 1:
            raise ValueError("timeout_seconds must be a positive integer")

    def complete(self, *, model: str, prompt: str) -> str:
        try:
            with httpx.Client(transport=self.transport, timeout=self.timeout_seconds) as client:
                response = client.post(
                    f"{self.host.rstrip('/')}/api/generate",
                    json={"model": model, "prompt": prompt, "stream": False},
                )
                response.raise_for_status()
                body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise LlmUnavailable(f"Ollama request failed: {type(exc).__name__}") from exc
        text = body.get("response") if isinstance(body, dict) else None
        if not isinstance(text, str):
            raise LlmUnavailable("Ollama response had no 'response' text field")
        return _THINK_BLOCK_RE.sub("", text).strip()
