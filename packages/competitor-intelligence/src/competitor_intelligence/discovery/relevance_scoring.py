"""Relevance scoring — the locked 8-axis algorithm, competitor-intelligence-agent.md
§6.14 (§6.14.0 provisional labelling, §6.14.1 per-axis method, §6.14.2 missing-data rule,
§6.14.3 bands, §6.14.4 "why this competitor", §6.14.5 four-separate-attributes rule, §6.14.6
naming). This module implements **exactly** the scheme §6.14.3 locks — score/band cutoffs,
the HIGH-requires-category-and-product-both->=1 gate, and the rule that an `UNKNOWN`/
`CONFLICTED` axis always scores 0 — never an invented variant (§6.14.3: "implementation
builds this exact scheme, not an invented one").

§6.14.1 assigns three of the eight axes (product similarity, use-case similarity, feature
overlap) an *optional* LLM-judgement path for when structured data is insufficient. Per the
model-output boundary this codebase already locks at §6.5 ("models classify, code
computes"), this module never lets an LLM produce a score or a band directly: an LLM
judgement, when used, is reduced by a caller to one of this module's plain similarity-tier
enums (`ProductSimilarityTier`/`UseCaseSimilarityTier`) *before* it reaches `score_*` here,
and deterministic code alone converts a tier into a 0/1/2 score, sums the eight axes and
assigns the band (§6.14.1's own words: "deterministic code sums the axes and assigns the
band"). No LLM client is imported or called from this module.

One documented gap in the locked bands (§6.14.3 fixes `HIGH: total>=11 AND category&product
both >=1`, `MEDIUM: 6-10`, `LOW: <=5`, which leaves `total in [11,16]` with the HIGH gate
failed undefined by the literal ranges): this implementation resolves that gap to `MEDIUM`,
consistent with the rule's stated intent ("cannot reach HIGH on price/keyword overlap alone")
without inventing a new band. Flagged as an open question for the spec owner to confirm
in writing, per this project's rule that undecided points are never silently resolved.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping

# --------------------------------------------------------------------------------------
# §6.14.3 locked thresholds — the only numbers this module is allowed to use for axis/band
# cutoffs. Do not adjust without a corresponding spec change.
# --------------------------------------------------------------------------------------

PRICE_PROXIMITY_STRONG_PCT = 15.0
PRICE_PROXIMITY_PARTIAL_PCT = 40.0
OVERLAP_STRONG_PCT = 60.0
OVERLAP_PARTIAL_PCT = 25.0

HIGH_MIN_TOTAL = 11
MEDIUM_MIN_TOTAL = 6
MAX_AXIS_SCORE = 2

AXIS_ORDER = (
    "category",
    "product",
    "price_proximity",
    "features",
    "keywords",
    "use_case",
    "fulfillment",
    "review_tier",
)
MAX_TOTAL_SCORE = MAX_AXIS_SCORE * len(AXIS_ORDER)  # 16

AXIS_LABELS: Mapping[str, str] = {
    "category": "category",
    "product": "product",
    "price_proximity": "price proximity",
    "features": "features",
    "keywords": "keywords",
    "use_case": "use-case",
    "fulfillment": "fulfillment",
    "review_tier": "review-tier",
}


class AxisState(str, Enum):
    """§6.14.2 — `KNOWN`/`UNKNOWN`/`CONFLICTED`, stored separately from the numeric score
    (`ci_candidate_relevance.axis_states` vs `.axis_scores`) because *"scored 0 because it
    genuinely doesn't match"* and *"scored 0 because we don't know"* are different facts."""

    KNOWN = "KNOWN"
    UNKNOWN = "UNKNOWN"
    CONFLICTED = "CONFLICTED"


class RelevanceBand(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


@dataclass(frozen=True, slots=True)
class AxisResult:
    """One axis's score, state and (optionally) plain-language rationale for the "why this
    competitor" panel (§6.14.4). `__post_init__` makes §6.14.2 rule 1/3 ("an UNKNOWN or
    CONFLICTED axis scores 0, never guessed higher") a structural invariant of the type
    itself, not a convention a caller has to remember: constructing an `AxisResult` with a
    non-`KNOWN` state and a nonzero score raises immediately."""

    score: int
    state: AxisState
    rationale: str | None = None

    def __post_init__(self) -> None:
        if self.score not in (0, 1, 2):
            raise ValueError(f"axis score must be 0, 1 or 2 — got {self.score}")
        if self.state is not AxisState.KNOWN and self.score != 0:
            raise ValueError(
                f"an axis in state {self.state} must score 0 (§6.14.2 rule 1/3) — got score={self.score}"
            )


@dataclass(frozen=True, slots=True)
class RelevanceBreakdown:
    """`ci_candidate_relevance` in memory. Structurally cannot be rendered as a bare band —
    `axis_results` is a required field carrying all eight axes, and every render helper below
    walks it; there is no constructor path that produces a `RelevanceBreakdown` without its
    full per-axis breakdown attached (§6.14.3 step 3, §6.14.4).
    """

    axis_results: Mapping[str, AxisResult]
    total_score: int
    band: RelevanceBand
    is_provisional: bool
    """§6.14.0 — `True` until the candidate has an evidence source. Set explicitly by the
    caller (never inferred inside this module) so the provisional/confirmed decision stays
    owned by whichever layer knows the candidate's `evidence_status`."""

    def __post_init__(self) -> None:
        missing = [axis for axis in AXIS_ORDER if axis not in self.axis_results]
        if missing:
            raise ValueError(f"RelevanceBreakdown missing required axes: {missing}")

    @property
    def band_label(self) -> str:
        """e.g. `"HIGH (12/16)"` — never rendered without the total (§6.14.3)."""
        return f"{self.band.value} ({self.total_score}/{MAX_TOTAL_SCORE})"

    @property
    def breakdown_line(self) -> str:
        """The §6.14.3 step-3 example format, e.g.
        `"HIGH (13/16): category=2, product=2, price proximity=2, features=1, ..."`,
        with `UNKNOWN`/`CONFLICTED` axes rendered honestly rather than omitted (§6.14.4:
        "An implementation that hides UNKNOWN axes from this panel violates §6.18")."""
        parts: list[str] = []
        for axis in AXIS_ORDER:
            result = self.axis_results[axis]
            label = AXIS_LABELS[axis]
            if result.state is AxisState.UNKNOWN:
                parts.append(f"{label}=UNKNOWN(0)")
            elif result.state is AxisState.CONFLICTED:
                parts.append(f"{label}=CONFLICTED(0)")
            else:
                parts.append(f"{label}={result.score}")
        return f"{self.band_label}: " + ", ".join(parts)

    def labelled_line(self) -> str:
        """§6.14.0's provisional-vs-confirmed rendering rule, e.g.
        `"Discovery relevance (provisional): HIGH (12/16): category=2, ..."` before evidence
        exists, `"Relevance: HIGH (12/16): ..."` after."""
        prefix = "Discovery relevance (provisional)" if self.is_provisional else "Relevance"
        return f"{prefix}: {self.breakdown_line}"


@dataclass(frozen=True, slots=True)
class RelevanceScoreInputs:
    """The eight already-scored axes, assembled by a caller (from deterministic comparisons
    and/or a reduced LLM judgement — see module docstring) before calling `score_relevance`.
    Keeping axis computation and band assignment as separate steps makes each independently
    testable against the spec's own worked examples."""

    category: AxisResult
    product: AxisResult
    price_proximity: AxisResult
    features: AxisResult
    keywords: AxisResult
    use_case: AxisResult
    fulfillment: AxisResult
    review_tier: AxisResult

    def as_mapping(self) -> dict[str, AxisResult]:
        return {
            "category": self.category,
            "product": self.product,
            "price_proximity": self.price_proximity,
            "features": self.features,
            "keywords": self.keywords,
            "use_case": self.use_case,
            "fulfillment": self.fulfillment,
            "review_tier": self.review_tier,
        }


def compute_band(axis_results: Mapping[str, AxisResult]) -> tuple[int, RelevanceBand]:
    """§6.14.3 step 2, exactly: sum the eight axes (max 16), then band. `HIGH` additionally
    requires category and product to have both scored >=1 — a candidate cannot reach `HIGH`
    on price/keyword overlap alone. See the module docstring for the one genuine gap in the
    literal ranges and how it's resolved here."""
    missing = [axis for axis in AXIS_ORDER if axis not in axis_results]
    if missing:
        raise ValueError(f"compute_band missing required axes: {missing}")

    total = sum(axis_results[axis].score for axis in AXIS_ORDER)
    category_ok = axis_results["category"].score >= 1
    product_ok = axis_results["product"].score >= 1

    if total <= 5:
        return total, RelevanceBand.LOW
    if total >= HIGH_MIN_TOTAL and category_ok and product_ok:
        return total, RelevanceBand.HIGH
    return total, RelevanceBand.MEDIUM


def score_relevance(inputs: RelevanceScoreInputs, *, is_provisional: bool) -> RelevanceBreakdown:
    """Assembles the eight pre-scored axes into a `RelevanceBreakdown` — the only place band
    assignment happens, so every caller gets the identical §6.14.3 rule."""
    axis_results = inputs.as_mapping()
    total, band = compute_band(axis_results)
    return RelevanceBreakdown(
        axis_results=axis_results, total_score=total, band=band, is_provisional=is_provisional
    )


# --------------------------------------------------------------------------------------
# §6.14.1 per-axis calculation — deterministic axes
# --------------------------------------------------------------------------------------


def _category_root(category: str) -> str:
    separator = ">" if ">" in category else ("/" if "/" in category else None)
    if separator is None:
        return category.strip().lower()
    return category.split(separator)[0].strip().lower()


def score_category(seller_category: str | None, candidate_category: str | None) -> AxisResult:
    """Deterministic — category taxonomy match (§6.14.1). `UNKNOWN` when either side is
    unobserved (§6.14.2 rule 1), never inferred."""
    if not seller_category or not candidate_category:
        return AxisResult(0, AxisState.UNKNOWN, "category not available for one or both sides")
    seller_norm = seller_category.strip().lower()
    candidate_norm = candidate_category.strip().lower()
    if seller_norm == candidate_norm:
        return AxisResult(2, AxisState.KNOWN, "exact category match")
    if _category_root(seller_norm) == _category_root(candidate_norm):
        return AxisResult(1, AxisState.KNOWN, "parent-category match only")
    return AxisResult(0, AxisState.KNOWN, "different category")


def score_price_proximity(seller_price_paise: int | None, candidate_price_paise: int | None) -> AxisResult:
    """Deterministic — % difference from the **seller's own price** (§6.14.6: this is
    "price proximity", never "price band"). §6.14.2 rule 3: a `None` seller price makes the
    comparison itself `UNKNOWN` — the system never invents a seller baseline to score
    against, even when the candidate's price is known."""
    if seller_price_paise is None:
        return AxisResult(0, AxisState.UNKNOWN, "seller's own price is unknown — no baseline to compare against")
    if candidate_price_paise is None:
        return AxisResult(0, AxisState.UNKNOWN, "candidate price was not observed")
    if seller_price_paise <= 0:
        return AxisResult(0, AxisState.UNKNOWN, "seller's own price is not a usable baseline")

    pct_diff = abs(candidate_price_paise - seller_price_paise) / seller_price_paise * 100
    if pct_diff <= PRICE_PROXIMITY_STRONG_PCT:
        return AxisResult(2, AxisState.KNOWN, f"within {pct_diff:.1f}% of seller's price")
    if pct_diff <= PRICE_PROXIMITY_PARTIAL_PCT:
        return AxisResult(1, AxisState.KNOWN, f"within {pct_diff:.1f}% of seller's price")
    return AxisResult(0, AxisState.KNOWN, f"{pct_diff:.1f}% away from seller's price")


def _overlap_pct(seller: frozenset[str] | None, candidate: frozenset[str] | None) -> float | None:
    if not seller or not candidate:
        return None
    union = seller | candidate
    if not union:
        return None
    return len(seller & candidate) / len(union) * 100


def score_overlap(
    seller_set: frozenset[str] | None, candidate_set: frozenset[str] | None, *, axis_label: str
) -> AxisResult:
    """Deterministic set-intersection overlap, used for both `features` and `keywords`
    (§6.14.1, §6.14.3). A missing set on either side is `UNKNOWN`; two known-but-disjoint
    sets legitimately score 0 in `KNOWN` state — the two zeroes are different facts and
    render differently (§6.14.2)."""
    pct = _overlap_pct(seller_set, candidate_set)
    if pct is None:
        return AxisResult(0, AxisState.UNKNOWN, f"{axis_label} not available for one or both sides")
    if pct >= OVERLAP_STRONG_PCT:
        return AxisResult(2, AxisState.KNOWN, f"{pct:.0f}% {axis_label} overlap")
    if pct >= OVERLAP_PARTIAL_PCT:
        return AxisResult(1, AxisState.KNOWN, f"{pct:.0f}% {axis_label} overlap")
    return AxisResult(0, AxisState.KNOWN, f"{pct:.0f}% {axis_label} overlap")


def score_fulfillment(seller_fulfillment: str | None, candidate_fulfillment: str | None) -> AxisResult:
    """Deterministic where the source exposes it explicitly; otherwise `UNKNOWN` — **never
    inferred** (§6.14.1). §6.14.2 rule 3 applies here too: a `None` seller value makes the
    comparison `UNKNOWN`, not a guessed match."""
    if not seller_fulfillment or not candidate_fulfillment:
        return AxisResult(0, AxisState.UNKNOWN, "fulfillment type not available from current evidence")
    if seller_fulfillment.strip().lower() == candidate_fulfillment.strip().lower():
        return AxisResult(2, AxisState.KNOWN, "matches seller's fulfillment type")
    return AxisResult(0, AxisState.KNOWN, "different fulfillment type")


# Review-volume tier bucket boundaries: not numerically locked by the spec (§6.14.1 only
# fixes "bucketed ... otherwise UNKNOWN" and the match/adjacent/else scoring rule, §6.14.3).
# Flagged as an open question for the spec owner; tunable without touching the scoring rule.
_REVIEW_TIER_UPPER_BOUNDS = (100, 1000, 10_000, 100_000)


def _review_tier_index(count: int) -> int:
    for index, upper_bound in enumerate(_REVIEW_TIER_UPPER_BOUNDS):
        if count < upper_bound:
            return index
    return len(_REVIEW_TIER_UPPER_BOUNDS)


def score_review_tier(seller_review_count: int | None, candidate_review_count: int | None) -> AxisResult:
    """Deterministic — bucketed from extracted review count when available; otherwise
    `UNKNOWN` (§6.14.1). `SellerProduct.review_count` is always `None` today (§5.5.2 is
    explicitly out of the manual profile form's scope), so in practice this axis is
    `UNKNOWN` until CI has its own way to observe a seller's review count — an honest
    degradation, not a bug."""
    if seller_review_count is None or candidate_review_count is None:
        return AxisResult(0, AxisState.UNKNOWN, "review volume not available for one or both sides")
    seller_tier = _review_tier_index(seller_review_count)
    candidate_tier = _review_tier_index(candidate_review_count)
    diff = abs(seller_tier - candidate_tier)
    if diff == 0:
        return AxisResult(2, AxisState.KNOWN, "matches seller's review-volume tier")
    if diff == 1:
        return AxisResult(1, AxisState.KNOWN, "adjacent review-volume tier")
    return AxisResult(0, AxisState.KNOWN, "different review-volume tier")


# --------------------------------------------------------------------------------------
# §6.14.1 per-axis calculation — the three LLM-touched axes. This module never calls an LLM
# itself; it only converts an already-judged, cited tier into a score (§6.5's "models
# classify, code computes" boundary, restated by §6.14.1's own last paragraph).
# --------------------------------------------------------------------------------------


class ProductSimilarityTier(str, Enum):
    SAME_LINE = "SAME_LINE"
    SAME_TYPE_DIFFERENT_LINE = "SAME_TYPE_DIFFERENT_LINE"
    DIFFERENT = "DIFFERENT"


def score_product_similarity(tier: ProductSimilarityTier | None, rationale: str | None = None) -> AxisResult:
    """`tier` is `None` when neither deterministic attribute comparison nor an LLM judgement
    could establish a value — `UNKNOWN` (§6.14.2 rule 1), never guessed."""
    if tier is None:
        return AxisResult(0, AxisState.UNKNOWN, rationale or "product similarity could not be established")
    if tier is ProductSimilarityTier.SAME_LINE:
        return AxisResult(2, AxisState.KNOWN, rationale or "same product line/model family")
    if tier is ProductSimilarityTier.SAME_TYPE_DIFFERENT_LINE:
        return AxisResult(1, AxisState.KNOWN, rationale or "same product type, different line")
    return AxisResult(0, AxisState.KNOWN, rationale or "different product")


class UseCaseSimilarityTier(str, Enum):
    SAME = "SAME"
    ADJACENT = "ADJACENT"
    DIFFERENT = "DIFFERENT"


def score_use_case_similarity(tier: UseCaseSimilarityTier | None, rationale: str | None = None) -> AxisResult:
    """LLM-derived from product description and customer-intent query terms (§6.14.1);
    `tier` is the deterministic reduction of that judgement a caller supplies, always with
    cited reasoning. `None` (no judgement available) is `UNKNOWN`."""
    if tier is None:
        return AxisResult(0, AxisState.UNKNOWN, rationale or "use-case similarity could not be established")
    if tier is UseCaseSimilarityTier.SAME:
        return AxisResult(2, AxisState.KNOWN, rationale or "same customer use case")
    if tier is UseCaseSimilarityTier.ADJACENT:
        return AxisResult(1, AxisState.KNOWN, rationale or "adjacent customer use case")
    return AxisResult(0, AxisState.KNOWN, rationale or "different customer use case")
