"""Estimates (`ESTIMATED` basis, spec §6.5) - the `Estimator` seam and its deterministic validator.

P4 wires NO estimator: with none supplied, every unresolved estimable attribute is `UNKNOWN` with a
seller-input requirement. The seam exists so a later, evaluated model can propose estimates; whatever
it proposes is untrusted and passes `validate_estimate`, which keeps the spec's promises in code:

* only WEIGHT and DIMENSIONS may be estimated, and only as an integer RANGE with a known unit - a
  point value (low == high) is refused ("never a point value", E14);
* only CATEGORY and VERTICAL may be estimated as plain words - no digits, so no category id,
  browse-node id or taxonomy code can be asserted (Q5);
* every estimate states its basis in plain words (no digits, no forbidden content);
* nothing else (colour, material, size, brand) is ever estimated;
* integers only - there are no floats anywhere.

An estimate is NEVER claim-eligible: it is labelled, shown with "confirm before listing", and kept out
of generated copy by `claims.assess`.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from slim_cmo.catalog.attributes import SPECS, CatalogAttribute, EstimateKind
from slim_cmo.forbidden import scan_forbidden
from slim_cmo.textnorm import clean_generated_text, collapse_whitespace
from slim_cmo.types import Marketplace

WEIGHT_UNITS = frozenset({"mg", "g", "kg"})
LENGTH_UNITS = frozenset({"mm", "cm", "m", "in"})
_UNITS: dict[CatalogAttribute, frozenset[str]] = {
    CatalogAttribute.WEIGHT: WEIGHT_UNITS,
    CatalogAttribute.DIMENSIONS: LENGTH_UNITS,
}
# Technical bounds on free text from an untrusted proposer (implementation limits, not business rules).
_MAX_NOTE_CHARS = 200
_MAX_PATH_CHARS = 120
_PATH_PUNCT = " >/&'-"

ESTIMATE_LABEL = "Estimate - confirm before listing"
CATEGORY_NOTE = "Confirm in the marketplace's own category tool; no category or browse-node id is asserted."


@dataclass(frozen=True, slots=True)
class Estimate:
    """What an estimator proposes. All fields are untrusted until validated."""

    low: int | None = None
    high: int | None = None
    unit: str | None = None
    text: str | None = None
    basis_note: str = ""


class Estimator(Protocol):
    def estimate(
        self,
        *,
        marketplace: Marketplace | None,
        attributes: Sequence[CatalogAttribute],
        known_facts: Mapping[str, str],
    ) -> Mapping[CatalogAttribute, Estimate]:
        """`known_facts` holds CLAIM-ELIGIBLE attribute name -> value only (no hints, no estimates, no price)."""
        ...


@dataclass(frozen=True, slots=True)
class ValidEstimate:
    attribute: CatalogAttribute
    kind: EstimateKind
    value_text: str
    low: int | None
    high: int | None
    unit: str | None
    basis_note: str

    def to_json(self) -> dict[str, object]:
        out: dict[str, object] = {"kind": self.kind.value, "label": ESTIMATE_LABEL, "basis_note": self.basis_note}
        if self.kind is EstimateKind.RANGE:
            out.update({"low": self.low, "high": self.high, "unit": self.unit})
        else:
            out.update({"text": self.value_text, "note": CATEGORY_NOTE})
        return out


@dataclass(frozen=True, slots=True)
class RejectedEstimate:
    attribute: CatalogAttribute
    reason: str  # a fixed rule id, never the proposed text


def _is_int(v: object) -> bool:
    return type(v) is int


def _clean_words(raw: object, limit: int) -> str | None:
    if not isinstance(raw, str):
        return None
    text = collapse_whitespace(clean_generated_text(raw))
    if not text or len(text) > limit or any(ch.isdigit() for ch in text) or scan_forbidden(text):
        return None
    return text


def _is_plain_path(text: str) -> bool:
    """Words and separators only: starts with a letter; letters, combining marks and ` >/&'-` after.
    Digits (and therefore any id or code) cannot appear."""
    return text[0].isalpha() and all(ch.isalpha() or unicodedata.category(ch)[0] == "M" or ch in _PATH_PUNCT for ch in text)


def validate_estimate(attribute: CatalogAttribute, est: object) -> ValidEstimate | RejectedEstimate:
    spec = SPECS[attribute]
    if spec.estimate_kind is None:
        return RejectedEstimate(attribute, "NOT_ESTIMABLE")
    if not isinstance(est, Estimate):
        return RejectedEstimate(attribute, "BAD_SHAPE")
    note = _clean_words(est.basis_note, _MAX_NOTE_CHARS)
    if note is None:
        return RejectedEstimate(attribute, "BASIS_NOTE_REQUIRED_AND_WORDS_ONLY")
    if spec.estimate_kind is EstimateKind.RANGE:
        if est.text is not None:
            return RejectedEstimate(attribute, "RANGE_ONLY")
        if not (_is_int(est.low) and _is_int(est.high)) or est.low is None or est.high is None:
            return RejectedEstimate(attribute, "INTEGER_RANGE_REQUIRED")
        if est.low < 0 or est.low > est.high:
            return RejectedEstimate(attribute, "INVALID_RANGE")
        if est.low == est.high:
            return RejectedEstimate(attribute, "POINT_VALUE_NOT_ALLOWED")
        if est.unit not in _UNITS[attribute]:
            return RejectedEstimate(attribute, "UNIT_NOT_ALLOWED")
        return ValidEstimate(attribute, EstimateKind.RANGE, f"{est.low}-{est.high} {est.unit}", est.low, est.high, est.unit, note)
    if est.low is not None or est.high is not None or est.unit is not None:
        return RejectedEstimate(attribute, "TEXT_ONLY")
    text = _clean_words(est.text, _MAX_PATH_CHARS)
    if text is None or not _is_plain_path(text):
        return RejectedEstimate(attribute, "PLAIN_WORDS_REQUIRED_NO_IDS")
    return ValidEstimate(attribute, EstimateKind.PATH, text, None, None, None, note)
