"""`LlmProvider` — the one seam between this module's L7 extraction step and a model.

**Why this is a local Protocol, not `from cfo.reasoning.provider import LlmProvider`.**
`packages/cfo` already depends on `packages/calc-engine` (its `pyproject.toml`: "`calc-engine`
[...] is a real runtime dependency — CFO's composition logic calls `calc_engine.api.
compute_metric` functions directly"), and nothing in `calc-engine` currently imports anything
from `cfo` — checked directly before writing this module (`grep` over
`packages/calc-engine/src` found zero `from cfo`/`import cfo` occurrences; the only import
direction that exists anywhere in this codebase is `cfo -> calc-engine`). Adding an import the
other way (`calc-engine -> cfo`) would be a new, backwards dependency edge and risks a real
circular import the moment `cfo` imports anything from `calc_engine.gst_lookup` (which G3,
CFO's wiring checkpoint, will need to do). The correct fix per the task's own instruction is
to define an equivalent `LlmProvider` Protocol locally, not force a dependency direction that
doesn't exist anywhere else in this codebase.

The shape is intentionally identical to `cfo.reasoning.provider.LlmProvider`
(`complete(*, model: str, prompt: str) -> str`) — a `Protocol`, so any real implementation
already satisfying that shape (e.g. `cfo`'s own `OllamaClient`-style adapter, wired up at a
future composition root) satisfies this one too, structurally, with no adapter needed.

CLAUDE.md: "LLMs explain numbers, they never compute them." `complete` takes and returns plain
text only — no numeric type appears anywhere in this interface, so there is no call shape here
that could pass a provider a raw figure (or a rate) to operate on. `lookup.py`'s
`_parse_extraction_response` is exactly where a plain-text response gets turned back into a
`GstLookupResult`'s typed fields, deterministically, in this package — never inside the LLM
call itself.
"""

from __future__ import annotations

from typing import Protocol


class LlmProvider(Protocol):
    def complete(self, *, model: str, prompt: str) -> str: ...
