"""Multi-screenshot merge semantics — competitor-intelligence-agent.md §5.3.

The hard rule this module exists to enforce: **disagreement across screenshots in one research
session is never silently resolved.** If two screenshots report different values for the same
field, the merge does not pick one — it surfaces `UNAVAILABLE` with every candidate recorded,
and only a seller's manual entry (`SELLER_ENTERED`) resolves it. This is the same
"never fabricate" architectural rule that governs data-foundation confidence, discount-bearer
UNKNOWN handling, and fee-reference gaps elsewhere in this codebase — not a suggestion.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Mapping, Sequence
from uuid import UUID

from competitor_intelligence.evidence.extraction import ExtractionResult
from competitor_intelligence.types import CaptureStatus, Confidence

# §6.1 rule 4 / §5.3: the fields change detection and alerting actually depend on. A snapshot
# can be COMPLETE even if, say, rating extraction failed — only these two gate capture_status.
REQUIRED_FIELDS: tuple[str, ...] = ("listed_price_paise", "availability")


@dataclass(frozen=True, slots=True)
class MergedField:
    """§5 `competitor_snapshot_field` — one row per field per snapshot. `source`/`evidence_id`
    are `None` exactly when `conflict` is `True` (§5.3 rule 3): a conflicted field traces to
    no single screenshot, by construction."""

    field_name: str
    value: Any
    source: Confidence | None
    confidence: Confidence
    evidence_id: UUID | None
    conflict: bool = False
    conflict_values: tuple[Any, ...] | None = None


def merge_extractions(per_evidence: Sequence[tuple[UUID, ExtractionResult]]) -> tuple[MergedField, ...]:
    """§5.3 rules 1-3. `per_evidence` is (evidence_id, its ExtractionResult) for every
    screenshot in a research session that reached `EXTRACTED` — a screenshot that reached
    `EXTRACTION_FAILED` contributes no candidates at all, which is exactly what "extraction
    found nothing" looks like from this function's point of view.
    """
    candidates: dict[str, list[tuple[UUID, Any]]] = defaultdict(list)
    for evidence_id, result in per_evidence:
        for field in result.fields:
            candidates[field.field_name].append((evidence_id, field.value))

    merged: list[MergedField] = []
    for field_name, entries in candidates.items():
        values = [v for _, v in entries]
        if all(v == values[0] for v in values):
            evidence_id, value = entries[0]
            merged.append(
                MergedField(
                    field_name=field_name,
                    value=value,
                    source=Confidence.VISION_EXTRACTED,
                    confidence=Confidence.VISION_EXTRACTED,
                    evidence_id=evidence_id,
                    conflict=False,
                )
            )
        else:
            # Rule 3 — hard rule: never pick one. Every candidate is preserved for the seller.
            merged.append(
                MergedField(
                    field_name=field_name,
                    value=None,
                    source=None,
                    confidence=Confidence.UNAVAILABLE,
                    evidence_id=None,
                    conflict=True,
                    conflict_values=tuple(values),
                )
            )
    return tuple(merged)


def apply_manual_entries(
    merged: Sequence[MergedField], manual: Mapping[str, Any]
) -> tuple[MergedField, ...]:
    """§5.3 rule 4 — a SELLER_ENTERED value always supersedes a VISION_EXTRACTED one for the
    same field, and is how a rule-3 conflict actually gets resolved in practice (the seller
    looks at `conflict_values` and types the correct one in)."""
    by_name = {f.field_name: f for f in merged}
    for field_name, value in manual.items():
        by_name[field_name] = MergedField(
            field_name=field_name,
            value=value,
            source=Confidence.SELLER_ENTERED,
            confidence=Confidence.SELLER_ENTERED,
            evidence_id=None,
            conflict=False,
            conflict_values=None,
        )
    return tuple(by_name.values())


def compute_capture_status(fields: Sequence[MergedField]) -> CaptureStatus:
    """§5.3 rule 5's table, stated as code: COMPLETE when both REQUIRED_FIELDS are resolved
    and unconflicted; PENDING_MANUAL_ENTRY when neither is; PARTIAL otherwise."""
    by_name = {f.field_name: f for f in fields}
    resolved_required = [
        name
        for name in REQUIRED_FIELDS
        if (f := by_name.get(name)) is not None and f.value is not None and not f.conflict
    ]
    if len(resolved_required) == len(REQUIRED_FIELDS):
        return CaptureStatus.COMPLETE
    if not resolved_required:
        return CaptureStatus.PENDING_MANUAL_ENTRY
    return CaptureStatus.PARTIAL


# Judgment call, not spec-prescribed: the spec calls `competitor_snapshot.confidence` a
# "snapshot-level rollup" without specifying the exact rule. This treats UNAVAILABLE as
# weakest and a seller's own manual confirmation as the strongest signal CI can carry
# internally — only the REQUIRED_FIELDS participate, so a snapshot can still roll up to a
# strong confidence even if an optional field (e.g. rating) failed extraction entirely.
_SNAPSHOT_CONFIDENCE_RANK: dict[Confidence, int] = {
    Confidence.UNAVAILABLE: 0,
    Confidence.VISION_EXTRACTED: 1,
    Confidence.DERIVED: 2,
    Confidence.SELLER_ENTERED: 3,
}


def combine_snapshot_confidence(fields: Sequence[MergedField]) -> Confidence:
    by_name = {f.field_name: f for f in fields}
    required = [by_name[name] for name in REQUIRED_FIELDS if name in by_name]
    if not required:
        return Confidence.UNAVAILABLE
    return min(required, key=lambda f: _SNAPSHOT_CONFIDENCE_RANK[f.confidence]).confidence
