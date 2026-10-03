"""Resolve catalog questions against the seller's evidence (spec §6.5, AC12, AC20, T13, E14).

Precedence, per attribute (deterministic, no model):

1. **SELLER_PROVIDED** - the LATEST seller fact for the attribute (the same latest-wins rule as P3:
   `facts.is_later`). A later EMPTY row clears the attribute: the older value is never resurrected.
   Earlier, different seller values are reported as `superseded_values`; a passed-gate image
   observation that disagrees is reported as `conflicting_observation`. Neither overrides the seller.
2. **IMAGE_OBSERVED** - only an attribute that `claims.assess` finds claim-eligible: gate PASSED
   (`EVAL_PASSED`), a literally observable attribute (never weight / dimensions / price ...), with a value.
3. **ESTIMATED** - only a validated estimate (`estimates.validate_estimate`) for an estimable attribute
   (weight and dimensions as a range, category and vertical in plain words). Never claim-eligible.
4. **UNKNOWN** - everything else, with an explicit request for the seller to supply it.

An `UNVERIFIED_HINT` image attribute never becomes an answer: it is surfaced ONLY as a suggestion
("suggested from your photo - please confirm") on an attribute that stays `UNKNOWN` (AC20, §6.2.1).
`SOURCE_DERIVED` is part of the vocabulary but is never produced here: no cited-source store exists
in V1, and an uncited value would not be claim-eligible anyway.

Nothing is invented: no value, id, taxonomy entry, dimension or weight appears unless a seller fact,
a passed-gate observation or a validated estimate put it there.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from slim_cmo.catalog.attributes import SPECS, CatalogAttribute, EstimateKind, normalise_name
from slim_cmo.catalog.estimates import CATEGORY_NOTE, ESTIMATE_LABEL, ValidEstimate
from slim_cmo.claims import Attribute, EligibilityReason, assess
from slim_cmo.generation.facts import FactContext, FactInput, build_fact_context, fact_display_name, is_later
from slim_cmo.textnorm import skeleton
from slim_cmo.types import AttributeBasis, SellerFactType, TrustState

HINT_TEXT = "suggested from your photo - please confirm"
SELLER_INPUT_NOTE = "Not determinable from your confirmed details. Please provide it."
_ANSWERABLE_TYPES = frozenset({SellerFactType.ATTRIBUTE, SellerFactType.BRAND, SellerFactType.CATEGORY})


@dataclass(frozen=True, slots=True)
class Suggestion:
    value: str
    text: str = HINT_TEXT


@dataclass(frozen=True, slots=True)
class AttributeAnswer:
    attribute: CatalogAttribute
    value: str | None
    basis: AttributeBasis
    claim_eligible: bool
    requires_seller_input: bool
    note: str
    source_fact_id: str | None = None
    suggestion: Suggestion | None = None
    estimate: ValidEstimate | None = None
    superseded_values: tuple[str, ...] = ()
    conflicting_observation: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "attribute": self.attribute.value,
            "value": self.value,
            "basis": self.basis.value,
            "claim_eligible": self.claim_eligible,
            "requires_seller_input": self.requires_seller_input,
            "note": self.note,
            "source_fact_id": self.source_fact_id,
            "suggestion": None if self.suggestion is None else {"value": self.suggestion.value, "text": self.suggestion.text},
            "estimate": None if self.estimate is None else self.estimate.to_json(),
            "superseded_values": list(self.superseded_values),
            "conflicting_observation": self.conflicting_observation,
        }


@dataclass(frozen=True, slots=True)
class AnswerSet:
    answers: tuple[AttributeAnswer, ...]
    context: FactContext = field(repr=False)

    def basis_counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for a in self.answers:
            out[a.basis.value] = out.get(a.basis.value, 0) + 1
        return dict(sorted(out.items()))


def _same(a: str | None, b: str | None) -> bool:
    return skeleton(a or "") == skeleton(b or "")


def _unique(requested: Iterable[CatalogAttribute]) -> list[CatalogAttribute]:
    return list(dict.fromkeys(requested))


def _alias_facts(attribute: CatalogAttribute, facts: Sequence[FactInput]) -> list[FactInput]:
    aliases = SPECS[attribute].aliases
    return [f for f in facts if f.fact_type in _ANSWERABLE_TYPES and normalise_name(fact_display_name(f)) in aliases]


def _latest(facts: Sequence[FactInput]) -> FactInput | None:
    best: FactInput | None = None
    for f in facts:
        if best is None or is_later(f, best):
            best = f
    return best


def _image_attrs(ctx: FactContext, attribute: CatalogAttribute) -> tuple[list[Attribute], list[Attribute]]:
    """(passed-gate observations, unverified hints) whose NAME matches this question."""
    spec = SPECS[attribute]
    if not spec.image_observable:
        return [], []
    aliases = spec.aliases
    passed = [a for a in ctx.eligible if a.basis == AttributeBasis.IMAGE_OBSERVED and normalise_name(a.name) in aliases]
    hints = [
        a for a, reason in ctx.ineligible
        if reason is EligibilityReason.UNVERIFIED_IMAGE_HINT and normalise_name(a.name) in aliases and (a.value or "").strip()
    ]
    return passed, hints


def unresolved_estimable(
    requested: Iterable[CatalogAttribute], facts: Sequence[FactInput], image_attrs: Sequence[Attribute] = ()
) -> list[CatalogAttribute]:
    """Questions still `UNKNOWN` after seller facts and passed-gate observations that an estimator
    MAY be asked about (weight, dimensions, category, vertical)."""
    baseline = resolve_answers(requested, facts, image_attrs, {})
    return [a.attribute for a in baseline.answers if a.basis is AttributeBasis.UNKNOWN and SPECS[a.attribute].estimate_kind is not None]


def known_facts(ctx: FactContext) -> dict[str, str]:
    """CLAIM-ELIGIBLE attribute name -> value, the only context an estimator may be shown: no hints,
    no estimates, no price."""
    return {a.name: str(a.value) for a in ctx.eligible}


def resolve_answers(
    requested: Iterable[CatalogAttribute],
    facts: Sequence[FactInput],
    image_attrs: Sequence[Attribute] = (),
    estimates: Mapping[CatalogAttribute, ValidEstimate] | None = None,
) -> AnswerSet:
    """`estimates` must already be validated; an entry for a non-estimable attribute is ignored."""
    ctx = build_fact_context(facts, image_attrs)
    out: list[AttributeAnswer] = []
    for attribute in _unique(requested):
        spec = SPECS[attribute]
        rows = _alias_facts(attribute, facts)
        winner = _latest(rows)
        passed, hints = _image_attrs(ctx, attribute)
        passed_value = passed[0].value if passed else None

        if winner is not None and (winner.value or "").strip():
            value = (winner.value or "").strip()
            older = tuple(dict.fromkeys(
                (f.value or "").strip() for f in rows
                if f is not winner and (f.value or "").strip() and not _same(f.value, value)
            ))
            conflict = passed_value if passed_value and not _same(passed_value, value) else None
            eligible = assess(Attribute(attribute.value.lower(), value, AttributeBasis.SELLER_PROVIDED)).eligible
            note = "Stated by you."
            if older:
                note += " A later statement replaced earlier different value(s)."
            if conflict:
                note += " Your photo analysis observed something different; your statement is used."
            out.append(AttributeAnswer(
                attribute, value, AttributeBasis.SELLER_PROVIDED, eligible, False, note,
                source_fact_id=winner.fact_id, superseded_values=older, conflicting_observation=conflict,
            ))
            continue

        # A seller row exists but its LATEST statement is empty: the seller cleared it. Older values are not resurrected.
        if passed_value:
            eligible = assess(Attribute(attribute.value.lower(), passed_value, AttributeBasis.IMAGE_OBSERVED, TrustState.EVAL_PASSED)).eligible
            out.append(AttributeAnswer(
                attribute, passed_value, AttributeBasis.IMAGE_OBSERVED, eligible, False,
                "Observed in your photo by an evaluated vision provider. Observed text and branding are not an ownership claim.",
            ))
            continue

        suggestion = Suggestion(hints[0].value or "") if hints else None
        estimate = (estimates or {}).get(attribute) if spec.estimate_kind is not None else None
        if estimate is not None and estimate.kind is spec.estimate_kind:
            note = f"{ESTIMATE_LABEL}. Basis: {estimate.basis_note}."
            if spec.estimate_kind is EstimateKind.PATH:
                note += " " + CATEGORY_NOTE
            out.append(AttributeAnswer(
                attribute, estimate.value_text, AttributeBasis.ESTIMATED, False, True, note,
                suggestion=suggestion, estimate=estimate,
            ))
            continue

        note = (f"A {HINT_TEXT}; it is not a confirmed fact. " if suggestion else "") + SELLER_INPUT_NOTE
        out.append(AttributeAnswer(attribute, None, AttributeBasis.UNKNOWN, False, True, note, suggestion=suggestion))
    return AnswerSet(tuple(out), ctx)
