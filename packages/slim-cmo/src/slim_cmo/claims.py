"""Claim eligibility and grounding (spec C8, C9, §6.2.1, §6.4, §6.5, AC10, AC11, AC12, AC20, AC23).

Two questions, both answered by deterministic code and never by the model:

1. **May this attribute be asserted as a fact in generated copy?** (`assess` / `partition`)
   Only `SELLER_PROVIDED`, cited `SOURCE_DERIVED`, and `IMAGE_OBSERVED` attributes whose
   `trust_state` is `EVAL_PASSED` may. `ESTIMATED` and `UNKNOWN` never may; an unevaluated
   image hint (`UNVERIFIED_HINT`) never may; and an image attribute that names something a
   photograph cannot show (weight, dimensions, price, rating, certification...) never may even
   if it somehow carries a passed gate (defence in depth over the vision parser and the
   database constraint).
2. **Is this generation anchored to the right title?** (`check_grounding`) Description, bullets,
   keywords, the copy pack and backend terms are generated against a title the seller approved
   (or supplied) *for that marketplace*, in *their* tenant, and that title must still satisfy
   the marketplace's current constraint.

On the OUTPUT side it also detects the two ways a model smuggles in an unsupported claim:
a number that appears in no input (`find_unsupported_numbers`) and the value of an
ineligible attribute (`find_ineligible_values_in_text`).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID

from slim_cmo.constraints import FormatConstraint
from slim_cmo.textnorm import dedupe_key, skeleton
from slim_cmo.types import AttributeBasis, GroundingBasis, Marketplace, OutputType, TrustState, GROUNDED_OUTPUT_TYPES
from slim_cmo.validators import check_title


# --------------------------------------------------------------------------------------------
# 1. attribute eligibility
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Citation:
    url: str
    retrieved_at: datetime


@dataclass(frozen=True, slots=True)
class Attribute:
    name: str
    value: str | None
    basis: AttributeBasis | str  # a str is accepted so an unrecognised basis fails closed instead of raising
    trust_state: TrustState | str | None = None
    citation: Citation | None = None


class EligibilityReason(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    ESTIMATED = "ESTIMATED"
    UNKNOWN = "UNKNOWN"
    UNVERIFIED_IMAGE_HINT = "UNVERIFIED_IMAGE_HINT"
    IMAGE_ATTRIBUTE_NOT_OBSERVABLE = "IMAGE_ATTRIBUTE_NOT_OBSERVABLE"
    MISSING_CITATION = "MISSING_CITATION"
    EMPTY_VALUE = "EMPTY_VALUE"
    UNRECOGNISED_BASIS = "UNRECOGNISED_BASIS"


@dataclass(frozen=True, slots=True)
class Eligibility:
    eligible: bool
    reason: EligibilityReason


# Things a product photograph cannot establish (spec §6.2). Matched on whole words of the
# attribute NAME so "net weight" and "item dimensions" are caught but "lightweight" is not.
IMAGE_UNOBSERVABLE_NAME_TOKENS: frozenset[str] = frozenset(
    {
        "weight", "dimension", "dimensions", "height", "width", "length", "depth",
        "price", "mrp", "rating", "ratings", "certification", "certifications", "certified",
    }
)
_WORD = re.compile(r"[^\W_]+", re.UNICODE)


def _name_tokens(name: str) -> set[str]:
    return set(_WORD.findall(skeleton(name)))


def _basis(value: AttributeBasis | str) -> AttributeBasis | None:
    try:
        return value if isinstance(value, AttributeBasis) else AttributeBasis(str(value))
    except ValueError:
        return None


def assess(attr: Attribute) -> Eligibility:
    basis = _basis(attr.basis)
    if basis is None:
        return Eligibility(False, EligibilityReason.UNRECOGNISED_BASIS)
    if basis is AttributeBasis.UNKNOWN:
        return Eligibility(False, EligibilityReason.UNKNOWN)
    if basis is AttributeBasis.ESTIMATED:
        return Eligibility(False, EligibilityReason.ESTIMATED)
    if attr.value is None or not str(attr.value).strip():
        return Eligibility(False, EligibilityReason.EMPTY_VALUE)
    if basis is AttributeBasis.SELLER_PROVIDED:
        return Eligibility(True, EligibilityReason.ELIGIBLE)
    if basis is AttributeBasis.SOURCE_DERIVED:
        cited = attr.citation is not None and bool(attr.citation.url.strip())
        return Eligibility(cited, EligibilityReason.ELIGIBLE if cited else EligibilityReason.MISSING_CITATION)
    # IMAGE_OBSERVED
    if _name_tokens(attr.name) & IMAGE_UNOBSERVABLE_NAME_TOKENS:
        return Eligibility(False, EligibilityReason.IMAGE_ATTRIBUTE_NOT_OBSERVABLE)
    trust = attr.trust_state.value if isinstance(attr.trust_state, TrustState) else attr.trust_state
    if trust != TrustState.EVAL_PASSED.value:
        return Eligibility(False, EligibilityReason.UNVERIFIED_IMAGE_HINT)
    return Eligibility(True, EligibilityReason.ELIGIBLE)


def seller_confirmation(hint: Attribute, confirmed_value: str | None = None) -> Attribute:
    """What `cmo.confirm_image_hint` records (spec §6.2.1): the SELLER'S OWN assertion.

    It returns a NEW attribute with basis `SELLER_PROVIDED` (value = the seller's confirmed or
    corrected text; defaulting to the hint's text when the seller simply agrees). It does not
    touch the hint: the hint object, its stored analysis row and its `UNVERIFIED_HINT` trust state
    are unchanged, because a seller clicking "yes" does not make the vision model reliable.
    The image-derived attribute therefore stays untrusted until an approved evaluation passes;
    only the seller's statement is usable as a claim - and it is attributable to them.

    Costs nothing (no generation happens) and takes no model input."""
    if _basis(hint.basis) is not AttributeBasis.IMAGE_OBSERVED:
        raise ValueError("only an image-derived hint can be confirmed this way")
    value = (confirmed_value if confirmed_value is not None else hint.value) or ""
    if not value.strip():
        raise ValueError("a confirmation needs a non-empty value; to reject a hint, record nothing")
    return Attribute(name=hint.name, value=value.strip(), basis=AttributeBasis.SELLER_PROVIDED, trust_state=None, citation=None)


@dataclass(frozen=True, slots=True)
class Partition:
    eligible: tuple[Attribute, ...]
    ineligible: tuple[tuple[Attribute, EligibilityReason], ...]


def partition(attributes: Iterable[Attribute]) -> Partition:
    eligible: list[Attribute] = []
    ineligible: list[tuple[Attribute, EligibilityReason]] = []
    for attr in attributes:
        verdict = assess(attr)
        if verdict.eligible:
            eligible.append(attr)
        else:
            ineligible.append((attr, verdict.reason))
    return Partition(tuple(eligible), tuple(ineligible))


def allowed_context_text(eligible: Iterable[Attribute], *extra: str | None) -> str:
    """Everything the output is entitled to say, as one string: eligible attribute names/values
    plus any extra grounding text (the approved title, the seller's own product details)."""
    parts: list[str] = []
    for attr in eligible:
        parts += [attr.name, str(attr.value or "")]
    parts += [e for e in extra if e]
    return "\n".join(parts)


# --------------------------------------------------------------------------------------------
# 2. output-side detectors
# --------------------------------------------------------------------------------------------

_NUMBER_RE = re.compile(r"\d{1,3}(?:,\d{2,3})+(?:\.\d+)?|\d+(?:\.\d+)?")


def canonical_number(token: str) -> str:
    """'1,200' -> '1200', '12.50' -> '12.5', '007' -> '7', '12.0' -> '12'. Decimal arithmetic only."""
    d = Decimal(token.replace(",", "")).normalize()
    return format(d, "f")


def extract_numbers(text: str) -> tuple[str, ...]:
    """Every numeric token in `text`, canonicalised, in order of appearance. Digits in any
    script are folded to ASCII first (a number cannot hide behind Devanagari digits), and a
    digit glued to letters ('750ml', 'A4') still counts - alphanumeric model numbers are an
    invention vector, so they are not exempt."""
    return tuple(canonical_number(m.group(0)) for m in _NUMBER_RE.finditer(skeleton(text)))


def find_unsupported_numbers(text: str, allowed_sources: Iterable[str]) -> tuple[str, ...]:
    """Numbers present in `text` that appear in NONE of the allowed sources (eval 1, 'no
    invented numbers'). Returns canonical tokens, sorted and de-duplicated."""
    allowed: set[str] = set()
    for source in allowed_sources:
        allowed.update(extract_numbers(source))
    return tuple(sorted({n for n in extract_numbers(text) if n not in allowed}))


def _contains_phrase(haystack: str, needle: str) -> bool:
    return re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", haystack) is not None


def find_ineligible_values_in_text(
    text: str,
    ineligible: Iterable[tuple[Attribute, EligibilityReason]] | Iterable[Attribute],
    *,
    allowed_context: str = "",
) -> tuple[str, ...]:
    """Names of ineligible attributes whose VALUE the output asserts (AC12: an ESTIMATED weight
    or an unverified image hint must never appear as a fact).

    A value that the eligible context also states is not a leak (the seller said it AND a
    model estimated it). Values shorter than 2 characters are skipped - a one-letter value
    would match inside any sentence; purely numeric values are covered by
    `find_unsupported_numbers`, which is stricter."""
    folded_text = skeleton(text)
    folded_context = skeleton(allowed_context)
    leaked: list[str] = []
    for item in ineligible:
        attr = item[0] if isinstance(item, tuple) else item
        if attr.value is None:
            continue
        value = skeleton(str(attr.value))
        if len(value) < 2 or value.replace(" ", "").isdigit():
            continue
        if _contains_phrase(folded_context, value):
            continue
        if _contains_phrase(folded_text, value):
            leaked.append(attr.name)
    return tuple(sorted(set(leaked)))


@dataclass(frozen=True, slots=True)
class SharedTextFinding:
    a: Marketplace
    b: Marketplace
    kind: str  # 'description' | 'bullet'


def shared_text_findings(
    packs: Mapping[Marketplace, tuple[str, Sequence[str]]],
) -> tuple[SharedTextFinding, ...]:
    """DIAGNOSTIC for AC23/T22: identical description or an identical bullet appearing in two
    marketplaces' packs (after normalisation). Separateness itself is structural - each pack is
    generated in its own call from its own title and constraint - so this reports; whether a
    hit forces regeneration is the generation layer's policy (a short, factual bullet such as a
    stated capacity can legitimately coincide)."""
    findings: list[SharedTextFinding] = []
    items = sorted(packs.items(), key=lambda kv: kv[0].value)
    for i, (ma, (desc_a, bullets_a)) in enumerate(items):
        keys_a = {dedupe_key(b) for b in bullets_a if dedupe_key(b)}
        for mb, (desc_b, bullets_b) in items[i + 1:]:
            if dedupe_key(desc_a) and dedupe_key(desc_a) == dedupe_key(desc_b):
                findings.append(SharedTextFinding(ma, mb, "description"))
            if keys_a & {dedupe_key(b) for b in bullets_b}:
                findings.append(SharedTextFinding(ma, mb, "bullet"))
    return tuple(findings)


# --------------------------------------------------------------------------------------------
# 3. grounding
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ApprovalRef:
    """The persisted seller approval a generation is anchored to (`cmo_title_approval`)."""

    id: UUID
    tenant_id: UUID
    marketplace: Marketplace
    approved_text: str


@dataclass(frozen=True, slots=True)
class Grounding:
    basis: GroundingBasis
    approval: ApprovalRef | None = None
    seller_title: str | None = None


class GroundingError(str, Enum):
    MISSING_GROUNDING = "MISSING_GROUNDING"
    UNEXPECTED_GROUNDING = "UNEXPECTED_GROUNDING"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    APPROVAL_NOT_ALLOWED = "APPROVAL_NOT_ALLOWED"
    TENANT_MISMATCH = "TENANT_MISMATCH"
    MARKETPLACE_MISMATCH = "MARKETPLACE_MISMATCH"
    ANCHOR_TITLE_MISSING = "ANCHOR_TITLE_MISSING"
    ANCHOR_TITLE_INVALID = "ANCHOR_TITLE_INVALID"


@dataclass(frozen=True, slots=True)
class GroundingResult:
    ok: bool
    anchor_text: str | None
    errors: tuple[GroundingError, ...]
    basis: GroundingBasis | None = None
    approval_id: UUID | None = None

    def persisted_columns(self) -> tuple[str | None, UUID | None]:
        """(`grounding_basis`, `grounding_approval_id`) - always consistent with the database
        CHECK that an APPROVED_TITLE basis carries an approval id and nothing else does."""
        if not self.ok:
            raise ValueError("a failed grounding has nothing to persist")
        return (self.basis.value if self.basis else None, self.approval_id)


def check_grounding(
    output_type: OutputType,
    *,
    tenant_id: UUID,
    marketplace: Marketplace,
    grounding: Grounding | None,
    constraint: FormatConstraint,
) -> GroundingResult:
    needs_anchor = output_type in GROUNDED_OUTPUT_TYPES
    if not needs_anchor:
        if grounding is not None:
            return GroundingResult(False, None, (GroundingError.UNEXPECTED_GROUNDING,))
        return GroundingResult(True, None, ())
    if grounding is None:
        return GroundingResult(False, None, (GroundingError.MISSING_GROUNDING,))

    errors: list[GroundingError] = []
    if grounding.basis is GroundingBasis.APPROVED_TITLE:
        approval = grounding.approval
        if approval is None:
            return GroundingResult(False, None, (GroundingError.APPROVAL_REQUIRED,))
        if grounding.seller_title is not None:
            errors.append(GroundingError.UNEXPECTED_GROUNDING)
        if approval.tenant_id != tenant_id:
            errors.append(GroundingError.TENANT_MISMATCH)
        if approval.marketplace is not marketplace:
            errors.append(GroundingError.MARKETPLACE_MISMATCH)  # a Flipkart pack cannot hang on an Amazon approval (AC23)
        anchor = approval.approved_text
    else:  # SELLER_SUPPLIED_TITLE
        if grounding.approval is not None:
            errors.append(GroundingError.APPROVAL_NOT_ALLOWED)
        anchor = grounding.seller_title or ""
        if not anchor.strip():
            errors.append(GroundingError.ANCHOR_TITLE_MISSING)

    if anchor.strip():
        # The anchor must still satisfy THIS marketplace's CURRENT constraint (it may have been
        # tightened since approval); otherwise copy would be grounded on a title the seller can
        # no longer legally use there.
        if not check_title(anchor, constraint, field="anchor_title").valid:
            errors.append(GroundingError.ANCHOR_TITLE_INVALID)

    if errors:
        return GroundingResult(False, None, tuple(dict.fromkeys(errors)))
    return GroundingResult(
        True,
        anchor.strip(),
        (),
        basis=grounding.basis,
        approval_id=grounding.approval.id if grounding.approval else None,
    )
