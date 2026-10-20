"""Product/entity identity resolution and gating — competitor-intelligence-agent.md
§6.13.1-§6.13.3, §5.4 (`ci_candidate.identity_match`/`identity_match_basis`).

Pipeline stage (§6.13.1): ``Candidate found -> Product identity resolution -> Match
confidence -> Gating rule (§6.13.2) -> Relevance scoring``. This module owns the first three
steps and the gate; `relevance_scoring.py` (a sibling module) owns the last, and is never
invoked here directly — a caller runs `resolve_identity()`, then `gate()`, then decides
whether to call into `relevance_scoring` at all (§6.13.2's whole point is that `UNCERTAIN`
candidates must not reach scoring before a seller acts).

Extraction of brand/model/pack-size/bundle-status from a candidate's title/snippet is a
best-effort heuristic — the spec fixes the *four match-confidence tiers* and *what attributes
must drive the judgement* (§6.13.1) but deliberately does not lock a specific text-matching
algorithm (contrast with §6.14.3's numeric axis thresholds, which is why real accuracy on
live marketplace snippets is called out as unproven at V14). Treat the extraction heuristics
in this module as tunable; treat the four-tier vocabulary, the gating table and the
caveat-propagation requirement as locked.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from enum import Enum
from typing import Generic, TypeVar

from competitor_intelligence.discovery.search_provider import SearchResult
from competitor_intelligence.seller_product.types import SellerProduct

_STOPWORDS = frozenset(
    {
        "for",
        "with",
        "the",
        "a",
        "an",
        "of",
        "and",
        "by",
        "in",
        "on",
        "to",
        "new",
        "original",
        "genuine",
    }
)

_BUNDLE_KEYWORDS = frozenset({"combo", "bundle", "kit", "set"})

# "pack of 2", "2 pack", "2-pack", "2pcs", "2 pieces", "2 units", "pack of 2"
_PACK_SIZE_PATTERNS = (
    re.compile(r"\bpack\s*of\s*(\d+)\b", re.IGNORECASE),
    re.compile(r"\b(\d+)\s*[- ]?\s*(?:pack|pcs|pieces|units|count)\b", re.IGNORECASE),
)


class IdentityMatch(str, Enum):
    """§6.13.1 — the only four values this axis may ever hold. Never silently assumed to be
    `EXACT_MATCH`; every candidate that has passed through `resolve_identity()` carries one
    of these explicitly."""

    EXACT_MATCH = "EXACT_MATCH"
    LIKELY_VARIANT = "LIKELY_VARIANT"
    UNCERTAIN = "UNCERTAIN"
    NOT_A_MATCH = "NOT_A_MATCH"


@dataclass(frozen=True, slots=True)
class IdentityMatchBasis:
    """`ci_candidate.identity_match_basis` (§5.4) — required whenever `identity_match` is
    set (§6.13.1). Records the four attributes the spec names: brand, model/variant
    (`*_model_tokens`), pack size and bundle status, for both sides of the comparison."""

    candidate_brand: str | None
    seller_brand: str | None
    candidate_model_tokens: frozenset[str]
    seller_model_tokens: frozenset[str]
    candidate_pack_size: int | None
    seller_pack_size: int | None
    candidate_is_bundle: bool
    seller_is_bundle: bool
    notes: str | None = None


@dataclass(frozen=True, slots=True)
class IdentityResolution:
    """The full result of one identity-resolution pass over one candidate.

    `caveat` is populated if and only if `identity_match is LIKELY_VARIANT` — enforced in
    `__post_init__` so a `LIKELY_VARIANT` result can never silently lose its caveat, and an
    `EXACT_MATCH`/`UNCERTAIN`/`NOT_A_MATCH` result can never carry a spurious one.
    """

    identity_match: IdentityMatch
    basis: IdentityMatchBasis
    caveat: str | None = None

    def __post_init__(self) -> None:
        if self.identity_match is IdentityMatch.LIKELY_VARIANT and not self.caveat:
            raise ValueError(
                "a LIKELY_VARIANT identity resolution must carry a visible caveat "
                "(§6.13.2: 'visibly marked everywhere it appears')"
            )
        if self.identity_match is not IdentityMatch.LIKELY_VARIANT and self.caveat:
            raise ValueError(
                "only a LIKELY_VARIANT identity resolution carries a caveat — "
                f"got {self.identity_match} with caveat={self.caveat!r}"
            )


# --------------------------------------------------------------------------------------
# §6.13.2 — the locked gating table
# --------------------------------------------------------------------------------------


class GatingOutcome(str, Enum):
    PROCEEDS = "PROCEEDS"
    """`EXACT_MATCH` — automatically eligible, proceeds to relevance scoring without a stop."""

    PROCEEDS_WITH_CAVEAT = "PROCEEDS_WITH_CAVEAT"
    """`LIKELY_VARIANT` — automatically eligible and proceeds, but visibly marked everywhere
    (§6.13.2). The pipeline never blocks waiting for a seller decision on this tier."""

    BLOCKED_FOR_REVIEW = "BLOCKED_FOR_REVIEW"
    """`UNCERTAIN` — blocked; requires seller approval before relevance scoring runs
    (`WAITING_FOR_REVIEW`, E24)."""

    PROCEEDS_AS_OTHER_PRODUCT = "PROCEEDS_AS_OTHER_PRODUCT"
    """`NOT_A_MATCH` — REVISED by C43 (CP2, owner-approved Q20): "not the same product as
    mine" is exactly what a competitor is, so this no longer stops at the gate. It proceeds to
    relevance scoring and to relationship classification (`relationship.py`); whether it is
    recommended is decided by its relationship class, and `UNRELATED`/`UNKNOWN` ones stay out
    of the Recommended tier (still visible in the other tiers, §6.15)."""


_GATING_TABLE: dict[IdentityMatch, GatingOutcome] = {
    IdentityMatch.EXACT_MATCH: GatingOutcome.PROCEEDS,
    IdentityMatch.LIKELY_VARIANT: GatingOutcome.PROCEEDS_WITH_CAVEAT,
    IdentityMatch.UNCERTAIN: GatingOutcome.BLOCKED_FOR_REVIEW,
    IdentityMatch.NOT_A_MATCH: GatingOutcome.PROCEEDS_AS_OTHER_PRODUCT,
}


def gate(identity_match: IdentityMatch) -> GatingOutcome:
    """§6.13.2's locked gating table, and nothing else — a pure lookup, never re-derived
    ad hoc at a call site."""
    return _GATING_TABLE[identity_match]


def enters_relevance_scoring(identity_match: IdentityMatch) -> bool:
    """`True` for every tier except `UNCERTAIN`, which stays blocked pending seller approval
    (C43). `NOT_A_MATCH` (a different product — i.e. a candidate competitor) now proceeds."""
    outcome = gate(identity_match)
    return outcome in (
        GatingOutcome.PROCEEDS,
        GatingOutcome.PROCEEDS_WITH_CAVEAT,
        GatingOutcome.PROCEEDS_AS_OTHER_PRODUCT,
    )


# --------------------------------------------------------------------------------------
# Caveat propagation (§6.13.2: "travels with the data, not just a UI badge")
# --------------------------------------------------------------------------------------

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class CaveatedValue(Generic[T]):
    """Wraps any comparison-shaped value (a price comparison, a feature-overlap figure, a
    `CIHandoff` field — anything §6.19 calls a "comparison field") derived from a candidate,
    binding its `LIKELY_VARIANT` caveat onto the value itself. A caller that forwards a
    `CaveatedValue` cannot drop the caveat without deliberately unwrapping `.value` and
    discarding the rest of the object — there is no code path that produces one of these
    for a `LIKELY_VARIANT` candidate without a caveat string attached.
    """

    value: T
    identity_match: IdentityMatch
    caveat: str | None

    def __post_init__(self) -> None:
        if self.identity_match is IdentityMatch.LIKELY_VARIANT and not self.caveat:
            raise ValueError("a LIKELY_VARIANT-derived comparison field must carry its caveat")
        if self.identity_match is not IdentityMatch.LIKELY_VARIANT and self.caveat:
            raise ValueError("only a LIKELY_VARIANT-derived comparison field carries a caveat")


def attach_identity_caveat(value: T, resolution: IdentityResolution) -> CaveatedValue[T]:
    """The one supported way to turn a derived value (e.g. a price-difference figure) into
    something safe to render or place in a `CIHandoff` payload — used at every point
    downstream code produces a comparison field from a candidate (§6.13.2, §6.19)."""
    return CaveatedValue(value=value, identity_match=resolution.identity_match, caveat=resolution.caveat)


# --------------------------------------------------------------------------------------
# Extraction heuristics (not spec-locked — see module docstring)
# --------------------------------------------------------------------------------------


def _attr(seller_product: SellerProduct, key: str) -> str | None:
    if not seller_product.attributes:
        return None
    key_lower = key.lower()
    for k, v in seller_product.attributes:
        if k.lower() == key_lower:
            return v
    return None


def _extract_brand(title: str | None) -> str | None:
    if not title:
        return None
    tokens = [t for t in re.findall(r"[A-Za-z0-9]+", title) if t]
    for token in tokens:
        # First capitalised alphabetic token is treated as the brand guess — a coarse but
        # cheap heuristic; a licensed provider or a richer catalogue lookup can replace this
        # without touching the resolution/gating logic above.
        if token[0].isupper() and any(c.isalpha() for c in token):
            return token
    return tokens[0] if tokens else None


def _seller_brand(seller_product: SellerProduct) -> str | None:
    brand = _attr(seller_product, "brand")
    if brand:
        return brand
    if str(getattr(seller_product.field_source.get("title"), "value", seller_product.field_source.get("title"))) == "SELLER_ENTERED":
        return None  # a title the seller typed into their profile does not tell which word is the brand: unknown, never guessed from its first word
    return _extract_brand(seller_product.title)


def _extract_pack_size(text: str) -> int | None:
    for pattern in _PACK_SIZE_PATTERNS:
        match = pattern.search(text)
        if match:
            try:
                return int(match.group(1))
            except ValueError:
                continue
    return None


def _seller_pack_size(seller_product: SellerProduct) -> int | None:
    raw = _attr(seller_product, "pack_size")
    if raw is not None:
        try:
            return int(raw)
        except ValueError:
            return None
    if seller_product.title:
        return _extract_pack_size(seller_product.title)
    return None


def _extract_bundle(text: str) -> bool:
    lowered = text.lower()
    return any(keyword in lowered for keyword in _BUNDLE_KEYWORDS)


def _seller_bundle(seller_product: SellerProduct) -> bool:
    raw = _attr(seller_product, "bundle")
    if raw is not None:
        return raw.strip().lower() in ("true", "yes", "1")
    return _extract_bundle(seller_product.title or "")


def _model_tokens(title: str | None, *, exclude_brand: str | None) -> frozenset[str]:
    if not title:
        return frozenset()
    tokens = {t.lower() for t in re.findall(r"[A-Za-z0-9]+", title)}
    tokens -= _STOPWORDS
    if exclude_brand:
        tokens.discard(exclude_brand.lower())
    tokens = {t for t in tokens if len(t) > 2 or t.isdigit()}
    return frozenset(tokens)


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a and not b:
        return 0.0
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


_EXACT_MATCH_OVERLAP_THRESHOLD = 0.5
_VARIANT_OVERLAP_THRESHOLD = 0.2


def _variant_caveat_text(basis: IdentityMatchBasis) -> str:
    if basis.candidate_pack_size is not None and basis.seller_pack_size is not None and (
        basis.candidate_pack_size != basis.seller_pack_size
    ):
        return (
            f"may be a {basis.candidate_pack_size}-pack, "
            f"not the {basis.seller_pack_size}-pack/unit you sell"
        )
    if basis.candidate_pack_size is not None and basis.seller_pack_size is None:
        return f"may be a {basis.candidate_pack_size}-pack, not the single unit you sell"
    if basis.candidate_is_bundle != basis.seller_is_bundle:
        return "may be a bundle/combo listing rather than the standalone product you sell"
    return "may be a different variant of the same product line"


def resolve_identity(candidate: SearchResult, seller_product: SellerProduct) -> IdentityResolution:
    """§6.13.1: extracts brand/model/pack-size/bundle-status from `candidate` and compares
    against `seller_product`, returning exactly one of the four match-confidence tiers with
    its required basis. Never returns `EXACT_MATCH` by default — insufficient data resolves
    to `UNCERTAIN`, never silently assumed to be exact (AC20)."""

    text = f"{candidate.title or ''} {candidate.snippet or ''}".strip()

    candidate_brand = _extract_brand(candidate.title)
    seller_brand = _seller_brand(seller_product)
    candidate_pack = _extract_pack_size(text)
    seller_pack = _seller_pack_size(seller_product)
    candidate_bundle = _extract_bundle(text)
    seller_bundle = _seller_bundle(seller_product)
    candidate_tokens = _model_tokens(candidate.title, exclude_brand=candidate_brand)
    seller_tokens = _model_tokens(seller_product.title, exclude_brand=seller_brand)

    basis = IdentityMatchBasis(
        candidate_brand=candidate_brand,
        seller_brand=seller_brand,
        candidate_model_tokens=candidate_tokens,
        seller_model_tokens=seller_tokens,
        candidate_pack_size=candidate_pack,
        seller_pack_size=seller_pack,
        candidate_is_bundle=candidate_bundle,
        seller_is_bundle=seller_bundle,
    )

    if not text or candidate_brand is None or seller_brand is None or not seller_tokens:
        basis = replace(basis, notes="insufficient identifying text to resolve a match confidence")
        return IdentityResolution(identity_match=IdentityMatch.UNCERTAIN, basis=basis)

    if candidate_brand.lower() != seller_brand.lower():
        basis = replace(basis, notes="different brand")
        return IdentityResolution(identity_match=IdentityMatch.NOT_A_MATCH, basis=basis)

    overlap = _jaccard(seller_tokens, candidate_tokens)

    if overlap < _VARIANT_OVERLAP_THRESHOLD:
        basis = replace(basis, notes="same brand but product/model could not be confidently matched")
        return IdentityResolution(identity_match=IdentityMatch.UNCERTAIN, basis=basis)

    variant_mismatch = (
        (candidate_pack is not None and seller_pack is not None and candidate_pack != seller_pack)
        or (candidate_pack is not None and seller_pack is None and candidate_pack != 1)
        or (candidate_bundle != seller_bundle)
    )

    if overlap >= _EXACT_MATCH_OVERLAP_THRESHOLD and not variant_mismatch:
        basis = replace(basis, notes="same brand, same model family, no variant signal")
        return IdentityResolution(identity_match=IdentityMatch.EXACT_MATCH, basis=basis)

    caveat = _variant_caveat_text(basis)
    basis = replace(basis, notes=caveat)
    return IdentityResolution(identity_match=IdentityMatch.LIKELY_VARIANT, basis=basis, caveat=caveat)
