"""Model-agnostic completion layer shared by the CEO (production) and its evaluation harness (spec §6.18: "runs against any LlmProvider/model").

Moved here from `backend.ceo_eval.model` in B3 so production code never imports the harness; `ceo_eval.model` re-exports it unchanged.

The product's `LlmProvider` is deliberately `complete(model, prompt) -> str`, text in / text out. A harness needs more —
per-call timings, an optional output schema, token counts — so it uses its own small `EvalModel` interface and offers:

* `OllamaEvalModel` — local Ollama `/api/generate` (streaming, so time-to-first-token is measured), constrained JSON via
  `format`, `think` control, warm-keeping, deterministic sampling. Local addresses only (CLAUDE.md: never a hosted provider).
* `ProviderAdapter` — wraps ANY product `LlmProvider` (so a model reachable only through the production abstraction can be
  evaluated; only wall time is available there, and a schema cannot be enforced).
* `ScriptedModel` — a deterministic fake for the harness's own tests (an oracle or a hostile model).

Swapping the model changes one constructor argument; nothing else in the harness names a model.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

STATIC_END = "=== END OF STATIC INSTRUCTIONS ==="  # both prompt builders put their cacheable instructions before this line
_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>\s*", re.DOTALL)


@dataclass(frozen=True, slots=True)
class Completion:
    text: str
    wall_ms: int
    ttft_ms: int | None = None  # wall time to the first non-empty answer chunk (None when the backend cannot tell)
    load_ms: int | None = None  # model load time reported by the server (a cold start shows here)
    prompt_tokens: int | None = None  # total prompt tokens (a cached prefix still counts; see prompt_eval_ms for the cache effect)
    prompt_eval_ms: int | None = None
    output_tokens: int | None = None
    eval_ms: int | None = None
    error: str | None = None
    raw_meta: Mapping[str, Any] = field(default_factory=dict)


class EvalModel(Protocol):
    name: str

    def complete(self, prompt: str, *, schema: Mapping[str, Any] | None = None, max_output_tokens: int | None = None) -> Completion: ...


def _ms(ns: int | None) -> int | None:
    return None if ns is None else ns // 1_000_000


class OllamaUnavailable(RuntimeError):
    pass


@dataclass(slots=True)
class OllamaEvalModel:
    name: str
    host: str = "http://localhost:11434"
    think: bool | None = False  # False: thinking off (the latency-relevant default). None: leave to the model's default.
    num_ctx: int = 4096
    keep_alive: str = "30m"
    temperature: float = 0.0
    seed: int = 0
    timeout_seconds: float = 900.0
    chat: bool = True  # /api/chat with the static instructions as the system turn (the shape a product would use); False = raw /api/generate

    def __post_init__(self) -> None:
        if not re.match(r"^https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$", self.host):
            raise ValueError("the evaluation harness only talks to a LOCAL model server (CLAUDE.md: no hosted provider)")

    def _payload(self, prompt: str, schema: Mapping[str, Any] | None, max_output_tokens: int | None, *, with_think: bool) -> dict[str, Any]:
        options: dict[str, Any] = {"temperature": self.temperature, "seed": self.seed, "num_ctx": self.num_ctx}
        if max_output_tokens is not None:
            options["num_predict"] = max_output_tokens
        body: dict[str, Any] = {"model": self.name, "stream": True, "keep_alive": self.keep_alive, "options": options}
        if self.chat:
            head, sep, tail = prompt.partition(STATIC_END)
            body["messages"] = [{"role": "system", "content": head.strip()}, {"role": "user", "content": (tail if sep else prompt).strip()}] if sep else [{"role": "user", "content": prompt}]
        else:
            body["prompt"] = prompt
        if with_think and self.think is not None:
            body["think"] = self.think
        if schema is not None:
            body["format"] = dict(schema)
        return body

    def complete(self, prompt: str, *, schema: Mapping[str, Any] | None = None, max_output_tokens: int | None = None) -> Completion:
        started = time.perf_counter()
        try:
            return self._run(prompt, schema, max_output_tokens, started, with_think=True)
        except OllamaUnavailable as exc:
            if "think" in str(exc).lower():  # a model without the thinking switch: retry without it
                return self._run(prompt, schema, max_output_tokens, time.perf_counter(), with_think=False)
            return Completion("", int((time.perf_counter() - started) * 1000), error=str(exc))

    def _run(self, prompt: str, schema: Mapping[str, Any] | None, max_output_tokens: int | None, started: float, *, with_think: bool) -> Completion:
        parts: list[str] = []
        ttft: int | None = None
        final: dict[str, Any] = {}
        try:
            with httpx.stream(
                "POST", f"{self.host}/api/chat" if self.chat else f"{self.host}/api/generate", json=self._payload(prompt, schema, max_output_tokens, with_think=with_think),
                timeout=self.timeout_seconds,
            ) as resp:
                if resp.status_code >= 400:
                    resp.read()
                    raise OllamaUnavailable(f"HTTP {resp.status_code}: {resp.text[:200]}")
                for line in resp.iter_lines():
                    if not line:
                        continue
                    chunk = json.loads(line)
                    piece = (chunk.get("message") or {}).get("content") or "" if self.chat else chunk.get("response") or ""
                    if piece and ttft is None:
                        ttft = int((time.perf_counter() - started) * 1000)
                    parts.append(piece)
                    if chunk.get("done"):
                        final = chunk
        except httpx.HTTPError as exc:
            raise OllamaUnavailable(f"Ollama request failed: {exc}") from exc
        text = _THINK_BLOCK_RE.sub("", "".join(parts)).strip()
        return Completion(
            text=text, wall_ms=int((time.perf_counter() - started) * 1000), ttft_ms=ttft, load_ms=_ms(final.get("load_duration")),
            prompt_tokens=final.get("prompt_eval_count"), prompt_eval_ms=_ms(final.get("prompt_eval_duration")),
            output_tokens=final.get("eval_count"), eval_ms=_ms(final.get("eval_duration")),
        )

    def unload(self) -> None:
        """Frees the model (so a comparison across models is not run with several resident at once)."""
        try:
            httpx.post(f"{self.host}/api/generate", json={"model": self.name, "keep_alive": 0}, timeout=60.0)
        except httpx.HTTPError:
            pass


class _ProviderLike(Protocol):
    def complete(self, *, model: str, prompt: str) -> str: ...


@dataclass(slots=True)
class ProviderAdapter:
    """Evaluates any product `LlmProvider` (`complete(model, prompt) -> str`). No schema can be enforced and only wall time
    is known — which is itself the honest measurement of what the production abstraction offers."""

    provider: _ProviderLike
    name: str

    def complete(self, prompt: str, *, schema: Mapping[str, Any] | None = None, max_output_tokens: int | None = None) -> Completion:
        started = time.perf_counter()
        try:
            text = self.provider.complete(model=self.name, prompt=prompt)
        except Exception as exc:  # a provider failure is a measured outcome, never a crash of the run
            return Completion("", int((time.perf_counter() - started) * 1000), error=f"{type(exc).__name__}: {exc}")
        return Completion(_THINK_BLOCK_RE.sub("", text).strip(), int((time.perf_counter() - started) * 1000))


@dataclass(slots=True)
class ScriptedModel:
    """Deterministic fake: `script(prompt, schema)` returns the text. Used by the harness's own tests."""

    script: Callable[[str, Mapping[str, Any] | None], str]
    name: str = "scripted"

    def complete(self, prompt: str, *, schema: Mapping[str, Any] | None = None, max_output_tokens: int | None = None) -> Completion:
        return Completion(self.script(prompt, schema), 0, ttft_ms=0)


# Production name for the same interface (the CEO uses it for classification and composition).
LlmModel = EvalModel
