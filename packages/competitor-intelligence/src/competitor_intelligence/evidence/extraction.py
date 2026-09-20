"""Vision extraction seam — competitor-intelligence-agent.md §5.3 rule 1.

`VisionExtractor` is a `Protocol`, the same seam pattern `capture/parser.py`'s `Parser`
already established: every caller depends on the protocol, never a concrete model, so the
real model can be wired at the composition root without touching orchestration or tests.
`UnimplementedVisionExtractor` is the honest stub — no model has been chosen yet (spec §1a
item 4, echoing the still-unresolved 🔴 Q7 on local-model quality); this raises rather than
fabricating extracted fields.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class ExtractedField:
    """One candidate value a vision model read off a single screenshot. Always
    `source = VISION_EXTRACTED` at this stage (§5.3 rule 1) — that tier is applied by the
    merge step (`evidence/merge.py`), not stored redundantly here."""

    field_name: str
    value: Any


@dataclass(frozen=True, slots=True)
class ExtractionResult:
    fields: tuple[ExtractedField, ...]


@dataclass(frozen=True, slots=True)
class ExtractionFailed:
    reason: str


class VisionExtractor(Protocol):
    def extract(self, image_ref: str) -> ExtractionResult | ExtractionFailed: ...


class UnimplementedVisionExtractor:
    """Deliberately not a real extractor. Wiring one requires a model choice and quality
    validation against real screenshots — genuinely unresolved (spec §1a item 4 / Q7), not
    something to guess at here. Inject a fake `VisionExtractor` for tests.
    """

    def extract(self, image_ref: str) -> ExtractionResult | ExtractionFailed:
        raise NotImplementedError(
            "No vision extraction model wired yet — see UnimplementedVisionExtractor's "
            "docstring (competitor-intelligence-agent.md §1a item 4, Q7). Inject a fake "
            "VisionExtractor for tests; wiring a real one needs a model choice and quality "
            "validation against real screenshots first."
        )
