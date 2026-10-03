"""`LlmProvider` - the one seam between CMO generation (Brain 3) and a model.

Mirrors `cfo.reasoning.provider.LlmProvider`: text in, text out, and NO numeric parameter anywhere
in the interface, so there is no call shape that could hand a provider a figure to operate on
(CLAUDE.md hard rule). Each package owns its own copy (no cross-agent imports, spec C6/AC4).

The model name and any transport timeout are supplied by the composition root, not by
`cmo_platform_config` (P3 decision 11).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol


class LlmProvider(Protocol):
    def complete(self, *, model: str, prompt: str) -> str: ...


class LlmUnavailable(Exception):
    """The model could not be reached / timed out / answered with an error. Never a reason to
    fabricate output: the attempt is counted and, if retries run out, the artefact FAILS."""


class ScriptedLlmProvider:
    """Deterministic provider for tests and offline evals: replays a fixed script and records every
    prompt it was given. An entry may be a string (the reply) or an Exception (raised)."""

    def __init__(self, replies: Iterable[str | Exception]) -> None:
        self._replies: list[str | Exception] = list(replies)
        self.prompts: list[str] = []
        self.models: list[str] = []

    def complete(self, *, model: str, prompt: str) -> str:
        self.prompts.append(prompt)
        self.models.append(model)
        if not self._replies:
            raise LlmUnavailable("scripted provider has no more replies")
        reply = self._replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    @property
    def calls(self) -> int:
        return len(self.prompts)
