"""A mapping proposal and its strict parse from (mocked or real) model output (cfo-data-intelligence.md §6.4).

The model returns JSON; `parse_proposal` accepts nothing it does not recognise. An unparseable or
over-reaching proposal is a failure the caller turns into "ask the seller to map manually" — never a
guess, never a partial acceptance.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

_FIELD_KEYS = {"source_column", "index", "canonical_field", "component_code", "transform", "tax_inclusion", "sign_convention", "confidence_note"}
_TOP_KEYS = {"fields", "unmapped_columns"}


class ProposalParseError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class FieldProposal:
    source_column: str
    index: int  # column position — disambiguates duplicate headers
    canonical_field: str
    component_code: str | None
    transform: str
    tax_inclusion: str | None
    sign_convention: str | None
    confidence_note: str | None = None


@dataclass(frozen=True, slots=True)
class MappingProposal:
    fields: tuple[FieldProposal, ...]
    unmapped_columns: tuple[str, ...]


def parse_proposal(raw: Any) -> MappingProposal:
    """Strictly parse model output (a JSON string or an already-decoded object)."""
    if isinstance(raw, (str, bytes)):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ProposalParseError(f"proposal is not valid JSON: {exc}") from None
    if not isinstance(raw, Mapping):
        raise ProposalParseError("proposal must be a JSON object")
    extra = set(raw) - _TOP_KEYS
    if extra:
        raise ProposalParseError(f"unknown proposal fields: {sorted(map(str, extra))}")
    fields_raw = raw.get("fields")
    if not isinstance(fields_raw, list):
        raise ProposalParseError("proposal.fields must be a list")
    fields: list[FieldProposal] = []
    for i, f in enumerate(fields_raw):
        if not isinstance(f, Mapping):
            raise ProposalParseError(f"fields[{i}] must be an object")
        bad = set(f) - _FIELD_KEYS
        if bad:
            raise ProposalParseError(f"fields[{i}] has unknown keys {sorted(map(str, bad))}")
        for req in ("source_column", "index", "canonical_field", "transform"):
            if req not in f:
                raise ProposalParseError(f"fields[{i}] is missing '{req}'")
        idx = f["index"]
        if isinstance(idx, bool) or not isinstance(idx, int) or idx < 0:
            raise ProposalParseError(f"fields[{i}].index must be a non-negative integer")
        for k in ("source_column", "canonical_field", "transform"):
            if not isinstance(f[k], str) or not f[k]:
                raise ProposalParseError(f"fields[{i}].{k} must be a non-empty string")
        for k in ("component_code", "tax_inclusion", "sign_convention", "confidence_note"):
            if f.get(k) is not None and not isinstance(f[k], str):
                raise ProposalParseError(f"fields[{i}].{k} must be a string or null")
        fields.append(FieldProposal(
            source_column=f["source_column"], index=idx, canonical_field=f["canonical_field"],
            component_code=f.get("component_code"), transform=f["transform"],
            tax_inclusion=f.get("tax_inclusion"), sign_convention=f.get("sign_convention"),
            confidence_note=f.get("confidence_note"),
        ))
    um = raw.get("unmapped_columns", [])
    if not isinstance(um, list) or not all(isinstance(x, str) for x in um):
        raise ProposalParseError("proposal.unmapped_columns must be a list of strings")
    return MappingProposal(fields=tuple(fields), unmapped_columns=tuple(um))
