"""Propose and confirm column mappings (cfo-data-intelligence.md §6.4, AC-D3, AC-D4).

`propose` asks a proposer (a local model in production, a fixed fake in tests) for a mapping, validates it
deterministically, and stores it as PROPOSED with a per-field decision: AUTO_ACCEPTED_BY_RULES only where every
rule passed and the header is one a verified adapter already uses, otherwise PENDING for the seller.

`confirm` never trusts what it stored: it applies the seller's edits, **re-validates the final mapping against
the file again**, and refuses (changing nothing) if any error remains, any required field is missing, or a
field that needs the seller's confirmation was not explicitly decided. The model proposes; the validator and the
seller decide.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from dataclasses import replace as _replace
from datetime import date, datetime
from typing import Any
from uuid import UUID

from data_foundation.ingestion.profiling import ProfileInput
from data_foundation.mapping.proposal import FieldProposal, MappingProposal, ProposalParseError
from data_foundation.mapping.validator import MappingLimits, MappingVerdict, validate_mapping
from data_foundation.repositories import column_mapping_repo as repo


@dataclass(frozen=True, slots=True)
class ProposerInput:
    """Everything a proposer may see: names, inferred shapes and a *masked* sample — never full rows."""

    report_kind: str
    marketplace: str | None
    columns: tuple[str, ...]
    masked_sample: tuple[tuple[str, ...], ...]
    profiles: tuple[Any, ...]


MappingProposer = Callable[[ProposerInput], "MappingProposal | str | Mapping[str, Any]"]


class MappingProposalFailed(Exception):
    """The proposer returned something unusable. The caller falls back to asking the seller to map manually."""


class MappingRefused(Exception):
    """Confirmation refused; `reasons` are shown to the seller. Nothing was changed."""

    def __init__(self, reasons: Sequence[str]) -> None:
        self.reasons = tuple(reasons)
        super().__init__("; ".join(reasons))


@dataclass(frozen=True, slots=True)
class ProposeResult:
    mapping_id: UUID
    verdict: MappingVerdict


@dataclass(frozen=True, slots=True)
class FieldOverride:
    """The seller's edit of one proposed field (keyed by column position)."""

    canonical_field: str | None = None
    component_code: str | None = None
    transform: str | None = None
    tax_inclusion: str | None = None
    sign_convention: str | None = None


def _evidence(fv: Any) -> dict[str, Any]:
    return {
        "errors": [{"rule": i.rule, "message": i.message} for i in fv.errors],
        "warnings": [{"rule": i.rule, "message": i.message} for i in fv.warnings],
        "confirm_reasons": list(fv.confirm_reasons),
        "detected_tax_inclusion": fv.detected_tax_inclusion,
        "enum_values": list(fv.enum_values),
        "exact_register_match": fv.exact_register_match,
    }


def _masked_profiles(profiles: Sequence[Any]) -> tuple[Any, ...]:
    """A proposer must never see a raw cell: the only raw values a profile carries are a column's distinct values (kept for
    short status-like columns so the seller can confirm them). Hand over masked copies — a personal-data column keeps none."""
    from data_foundation.mapping.masking import is_pii_column, mask_cell

    out = []
    for p in profiles:
        values = () if is_pii_column(p.name) else tuple(mask_cell(p.name, v) for v in p.enum_values)
        out.append(_replace(p, enum_values=values))
    return tuple(out)


def propose(
    tenant_id: UUID,
    *,
    pinput: ProfileInput,
    report_kind: str,
    marketplace: str | None,
    proposer: MappingProposer,
    proposed_by: str,
    limits: MappingLimits,
    as_of: date,
) -> ProposeResult:
    from data_foundation.mapping.proposal import parse_proposal

    raw = proposer(ProposerInput(report_kind, marketplace, pinput.columns, pinput.masked_sample, _masked_profiles(pinput.profiles)))
    try:
        proposal = raw if isinstance(raw, MappingProposal) else parse_proposal(raw)
    except ProposalParseError as exc:
        raise MappingProposalFailed(str(exc)) from None

    verdict = validate_mapping(proposal, report_kind=report_kind, columns=pinput.columns, rows=pinput.profile_rows,
                               profiles=pinput.profiles, limits=limits, as_of=as_of)
    by_index = {fv.index: fv for fv in verdict.fields}
    rows = [
        repo.FieldRow(
            source_column=f.source_column, source_column_index=f.index, canonical_field=f.canonical_field,
            component_code=f.component_code, transform=f.transform, tax_inclusion=f.tax_inclusion, sign_convention=f.sign_convention,
            decision="AUTO_ACCEPTED_BY_RULES" if by_index[f.index].auto_acceptable else "PENDING", evidence=_evidence(by_index[f.index]),
        )
        for f in proposal.fields
        if f.index in by_index
    ]
    mapping_id = repo.create_proposal(
        tenant_id, fingerprint=pinput.fingerprint, report_kind=report_kind, marketplace=marketplace, sheet_name=pinput.sheet_name,
        header_row=pinput.header_row_index, proposed_by=proposed_by, fields=rows,
        evidence={
            "global_issues": [{"rule": i.rule, "message": i.message} for i in verdict.global_issues],
            "global_warnings": [{"rule": i.rule, "message": i.message} for i in verdict.global_warnings],
            "missing_required": [list(g) for g in verdict.missing_required],
            "unmapped_columns": list(proposal.unmapped_columns),
        },
    )
    return ProposeResult(mapping_id=mapping_id, verdict=verdict)


def _final_proposal(stored: Mapping[str, Any], overrides: Mapping[int, FieldOverride]) -> MappingProposal:
    fields: list[FieldProposal] = []
    for f in stored["fields"]:
        ov = overrides.get(int(f["source_column_index"]))
        fields.append(FieldProposal(
            source_column=f["source_column"], index=int(f["source_column_index"]),
            canonical_field=(ov.canonical_field if ov and ov.canonical_field else f["canonical_field"]),
            component_code=(ov.component_code if ov and ov.canonical_field else (ov.component_code if ov and ov.component_code else f["component_code"])),
            transform=(ov.transform if ov and ov.transform else f["transform"]),
            tax_inclusion=(ov.tax_inclusion if ov and ov.tax_inclusion else f["tax_inclusion"]),
            sign_convention=(ov.sign_convention if ov and ov.sign_convention else f["sign_convention"]),
        ))
    return MappingProposal(fields=tuple(fields), unmapped_columns=tuple((stored.get("evidence") or {}).get("unmapped_columns", ())))


def confirm(
    tenant_id: UUID,
    mapping_id: UUID,
    *,
    confirmed_by: UUID,
    decisions: Mapping[int, str],
    overrides: Mapping[int, FieldOverride],
    pinput: ProfileInput,
    limits: MappingLimits,
    as_of: date,
    now: datetime,
) -> MappingVerdict:
    stored = repo.get_mapping(tenant_id, mapping_id)
    if stored is None:
        raise MappingRefused(["this mapping does not exist"])
    if stored["status"] != "PROPOSED":
        raise MappingRefused([f"this mapping is {stored['status'].lower()} and can no longer be confirmed"])
    if stored["fingerprint"] != pinput.fingerprint:
        raise MappingRefused(["the file's columns changed since this mapping was proposed; upload it again"])

    final = _final_proposal(stored, overrides)
    verdict = validate_mapping(final, report_kind=stored["report_kind"], columns=pinput.columns, rows=pinput.profile_rows,
                               profiles=pinput.profiles, limits=limits, as_of=as_of)

    reasons: list[str] = []
    reasons += [f"{i.rule}: {i.message}" for i in verdict.global_issues]
    for fv in verdict.fields:
        reasons += [f"column {fv.source_column!r}: {e.rule}: {e.message}" for e in fv.errors]
    reasons += [f"a required field is missing; map one of {list(g)}" for g in verdict.missing_required]
    # Every field that needs the seller must be *explicitly* decided — silence is not confirmation.
    for fv in verdict.fields:
        if fv.needs_confirmation and decisions.get(fv.index) not in ("SELLER_CONFIRMED", "SELLER_OVERRIDDEN"):
            reasons.append(f"column {fv.source_column!r} needs your confirmation: {'; '.join(fv.confirm_reasons)}")
    # A gross/total amount must have a definite GST treatment before it can be trusted.
    for f in final.fields:
        if f.canonical_field in ("gross_item_amount", "total_invoice_amount") and f.tax_inclusion not in ("INCLUSIVE", "EXCLUSIVE"):
            reasons.append(f"column {f.source_column!r}: say whether the amount includes GST")
    if reasons:
        raise MappingRefused(reasons)

    # Persist the seller's edits, then confirm.
    final_decisions = dict(decisions)
    for idx, ov in overrides.items():
        if any((ov.canonical_field, ov.component_code, ov.transform, ov.tax_inclusion, ov.sign_convention)):
            f = next(x for x in final.fields if x.index == idx)
            repo.update_field(tenant_id, mapping_id, idx, canonical_field=f.canonical_field, component_code=f.component_code,
                              transform=f.transform, tax_inclusion=f.tax_inclusion, sign_convention=f.sign_convention)
            final_decisions[idx] = "SELLER_OVERRIDDEN"
    repo.confirm(tenant_id, mapping_id, confirmed_by=confirmed_by, field_decisions=final_decisions, now=now)
    return verdict
