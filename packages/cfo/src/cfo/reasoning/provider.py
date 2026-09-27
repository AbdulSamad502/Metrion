"""`LlmProvider` — the one seam between CFO's Brain 3 narration and a model, mirroring
`competitor_intelligence.evidence.ollama_client.OllamaClient`'s shape (Protocol +
one real, swappable implementation, wired up once at the composition root).

CLAUDE.md: "LLMs explain numbers, they never compute them." This protocol's `complete`
takes and returns plain text only — no numeric type appears anywhere in this interface, so
there is no call shape here that could pass a provider a raw figure to operate on.
"""

from __future__ import annotations

from typing import Protocol


class LlmProvider(Protocol):
    def complete(self, *, model: str, prompt: str) -> str: ...
