"""`OllamaLlmProvider` — the dev `LlmProvider` implementation, calling local Ollama's
`/api/generate`. Mirrors `competitor_intelligence.evidence.ollama_client.HttpOllamaClient`
almost exactly (same request shape, same fail-loud-never-fabricate contract on error) —
text-only here (`narrate.py` never hands this provider an image), so there is no
`image_bytes`/`images` field at all, unlike CI's vision client.

CLAUDE.md / C15 (mirrored from CI's own client docstring): always a local address, never a
hosted provider — `host` is caller-supplied, defaulting to Ollama's standard local port.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import httpx

# Strips a "thinking" model's <think>...</think> reasoning block (e.g. qwen3:8b emits one
# before every answer) — CFO end-to-end evaluation, 2026-09-27: this codebase's narration
# contract (narrate.py's own docstring) is that `narrate_figures` "returns the provider's
# prose response unchanged", but an unstripped <think> block is internal reasoning, not the
# prose answer itself; leaving it in would surface a wall of chain-of-thought to a seller.
# `re.DOTALL` so the block is matched across newlines; an unclosed <think> (a truncated
# response) is left as-is rather than guessed at.
_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>\s*", re.DOTALL)


class OllamaUnavailable(Exception):
    """The model server could not be reached, timed out, or returned a non-2xx response —
    never a reason to fabricate narration. Callers surface this as narration-unavailable,
    the same "fail loud, don't invent" treatment CI's own Ollama client uses."""


@dataclass(frozen=True, slots=True)
class OllamaLlmProvider:
    host: str = "http://localhost:11434"
    timeout_seconds: float = 60.0

    def complete(self, *, model: str, prompt: str) -> str:
        try:
            response = httpx.post(
                f"{self.host}/api/generate",
                json={"model": model, "prompt": prompt, "stream": False},
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise OllamaUnavailable(f"Ollama request failed: {exc}") from exc

        body = response.json()
        text = body.get("response")
        if not isinstance(text, str):
            raise OllamaUnavailable("Ollama response had no 'response' text field")
        return _THINK_BLOCK_RE.sub("", text).strip()
