"""The discovery run state machine - competitor-intelligence-agent.md Sec 6.12.2, tying
together `query_runner.py` (Sec 6.10-6.12 SEARCHING), `identity_resolution.py` (Sec 6.13
DISCOVERING) and `relevance_scoring.py` (Sec 6.14 DISCOVERING) into the run lifecycle:

    QUEUED -> SEARCHING -> DISCOVERING -> WAITING_FOR_REVIEW -> RESEARCHING -> COMPLETE
                                                                    -> FAILED
                                                                    -> PARTIAL

This module owns exactly the state transitions and the tier assignment rules (Sec 6.15) - it
does not reimplement query composition, identity resolution or relevance scoring, all of
which are already built and are only called from here.

Resolved design points, documented rather than silently decided (this project's own rule -
see e.g. relevance_scoring.py's module docstring for the same discipline applied to a
different ambiguity):

1. **Tier vs identity_match.** `ci_candidate`'s own DDL comment (Sec 5.4) is explicit:
   `identity_match ... | null while tier = RAW`. Read literally, a candidate leaves `RAW`
   the moment identity resolution sets `identity_match` - for **all four** outcomes,
   including `NOT_A_MATCH`. Sec 6.13.2's prose ("still visible in the raw tier") is read as
   describing where a `NOT_A_MATCH` candidate is *surfaced in the UI* (alongside the
   unanalyzed/raw section, not in the Recommended flow), not as a literal assertion about
   the persisted `tier` column - the DDL comment is the more precise, binding source. A
   `NOT_A_MATCH` candidate here gets `tier = ANALYZED` (identity-resolved) but never
   `RECOMMENDED` and never enters relevance scoring.
2. **`RESEARCHING` is a transient pass-through state in this checkpoint.** No new automated
   work happens here - evidence upload is the existing, unrelated CI evidence pipeline
   (`direct_path/research_run.py`), invoked later and separately by the seller once they've
   accepted a candidate into a tracked `competitor_url`. A run passes through `RESEARCHING`
   to `COMPLETE`/`PARTIAL` in the same call once nothing is blocking it.
3. **`WAITING_FOR_REVIEW` blocks only on `UNCERTAIN` candidates with no seller decision yet**
   (Sec 6.12.2: "the pipeline waits here only for UNCERTAIN candidates"). `EXACT_MATCH`/
   `LIKELY_VARIANT` candidates are scored and tiered without blocking the run. Once every
   `UNCERTAIN` candidate in a run has a seller decision (`APPROVED`/`REJECTED`),
   `advance_after_review()` moves the run to `RESEARCHING` then `COMPLETE`/`PARTIAL`
   (`PARTIAL` if a budget/provider issue was already recorded during `SEARCHING`).
4. **Recommended selection.** Among candidates that entered relevance scoring
   (`EXACT_MATCH`/`LIKELY_VARIANT`), the top `max_recommended_candidates` by
   `total_score` (ties broken by earliest `created_at`) are tiered `RECOMMENDED`; the rest
   stay `ANALYZED` ("Other analyzed", Sec 6.15).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from competitor_intelligence.capture.allowlist import marketplace_for_host
from competitor_intelligence.discovery.lead_quality import brand_of, is_junk, rank_key
from competitor_intelligence.discovery.budget import DiscoveryBudget
from competitor_intelligence.discovery.identity_resolution import (
    GatingOutcome,
    IdentityMatch,
    IdentityResolution,
    enters_relevance_scoring,
    gate,
    resolve_identity,
)
from competitor_intelligence.discovery.relationship import Relationship, classify_relationship, product_tier_from_tokens
from competitor_intelligence.discovery.query_runner import DiscoveryQueryRunResult, run_discovery_queries
from competitor_intelligence.discovery.relevance_scoring import (
    AxisResult,
    AxisState,
    RelevanceBreakdown,
    RelevanceScoreInputs,
    score_category,
    score_fulfillment,
    score_overlap,
    score_price_proximity,
    score_product_similarity,
    score_relevance,
    score_review_tier,
    score_use_case_similarity,
)
from competitor_intelligence.discovery.search_cache import SearchResultCache
from competitor_intelligence.discovery.search_provider import SearchProvider, SearchResult
from competitor_intelligence.repositories import (
    ci_candidate_relevance_repo,
    ci_candidate_repo,
    ci_discovery_run_repo,
    competitor_url_repo,
)
from competitor_intelligence.seller_product.types import SellerProduct
from competitor_intelligence.types import Marketplace

# --------------------------------------------------------------------------------------
# Sec 6.14: turning a raw SearchResult into RelevanceScoreInputs.
#
# A discovered candidate is a search snippet - Sec 6.10.2's Evidence Acquisition Matrix
# states plainly that price/rating/review-count/category are "lead only, often absent" or
# "not available from search" at this stage. This module never fabricates a value a search
# result cannot actually supply: price_proximity, category, fulfillment and review_tier are
# scored against `None` on the candidate side unless a real structured source provides them
# (there isn't one yet at discovery time), which correctly and honestly yields UNKNOWN per
# Sec 6.14.2 rule 1 - not a bug, the expected consequence of thin discovery-stage data.
# Keyword overlap is the one axis a raw title/snippet can genuinely support.
#
# No LLM classifier for product/use-case similarity is wired in this checkpoint (Sec 6.14.1
# allows an LLM-assisted path, but Sec 6.5's "models classify, code computes" boundary and
# this package's existing convention - see relevance_scoring.py's own docstring, "No LLM
# client is imported or called from this module" - mean this checkpoint does not introduce
# one either). Passing `None` for these tiers is the honest choice: UNKNOWN, never a guess.
# --------------------------------------------------------------------------------------

_STOPWORDS = frozenset(
    {
        "the", "a", "an", "for", "and", "or", "with", "of", "in", "on", "to", "by",
        "is", "are", "your", "you", "this", "that", "from", "at", "&",
    }
)


def _extract_candidate_keywords(candidate: SearchResult) -> frozenset[str]:
    """A plain, undecorated tokenizer over title+snippet - not spec-locked (only the
    set-intersection *method* is, Sec 6.14.1), tunable without touching the scoring rule
    itself, same status as identity_resolution.py's own extraction heuristics."""
    text = f"{candidate.title or ''} {candidate.snippet or ''}".lower()
    tokens = {tok for tok in "".join(c if c.isalnum() else " " for c in text).split() if len(tok) > 2}
    return frozenset(tokens - _STOPWORDS)


def _seller_keywords(seller_product: SellerProduct) -> frozenset[str] | None:
    if not seller_product.keywords:
        return None
    return frozenset(kw.strip().lower() for kw in seller_product.keywords if kw.strip())


def build_relevance_inputs(
    candidate: SearchResult, seller_product: SellerProduct, resolution: IdentityResolution | None = None
) -> RelevanceScoreInputs:
    """Assembles the eight axes for one candidate against the seller's product, per the
    module-level docstring's honesty rules. `features` has no structured candidate-side
    source at discovery time (Sec 6.10.2) and is therefore always UNKNOWN today, the same
    documented degradation `relevance_scoring.py` already applies to `review_tier`."""
    candidate_keywords = _extract_candidate_keywords(candidate)
    seller_keywords = _seller_keywords(seller_product)

    return RelevanceScoreInputs(
        category=score_category(seller_product.category, None),
        product=score_product_similarity(
            product_tier_from_tokens(resolution.basis) if resolution is not None else None,
            "title-token overlap with your product (provisional, from a search lead)" if resolution is not None else None,
        ),
        price_proximity=score_price_proximity(seller_product.price_paise, None),
        features=AxisResult(0, AxisState.UNKNOWN, "structured feature data not available from a search result"),
        keywords=score_overlap(seller_keywords, candidate_keywords or None, axis_label="keyword"),
        use_case=score_use_case_similarity(None),
        fulfillment=score_fulfillment(seller_product.fulfillment_type, None),
        review_tier=score_review_tier(seller_product.review_count, None),
    )


# --------------------------------------------------------------------------------------
# Run orchestration
# --------------------------------------------------------------------------------------


MAX_PER_BRAND = 2  # leads of one brand in the shown list


@dataclass(frozen=True, slots=True)
class DiscoveryRunOutcome:
    discovery_run_id: UUID
    status: str
    raw_candidate_count: int
    analyzed_candidate_count: int
    recommended_candidate_ids: tuple[UUID, ...]
    uncertain_candidate_ids: tuple[UUID, ...]
    partial_reason: str | None
    failed_reason: str | None


def _candidate_marketplace(url: str) -> str | None:
    marketplace = marketplace_for_host(url)
    return marketplace.value if marketplace is not None else None


def start_discovery_run(
    tenant_id: UUID,
    *,
    requested_by: UUID,
    seller_product: SellerProduct,
    provider: SearchProvider,
    provider_name: str,
    cache: SearchResultCache,
    budget: DiscoveryBudget,
    discovery_enabled: bool,
) -> DiscoveryRunOutcome:
    """The full QUEUED -> ... -> WAITING_FOR_REVIEW/RESEARCHING/COMPLETE/PARTIAL/FAILED
    pass for one run, in one call. QUEUED itself is implicit (entitlement/permission checks
    already happened at the API layer per Sec 6.4/D12 before this function is ever called -
    same "direct execution path" pattern used by every other CI action)."""
    now = datetime.now(timezone.utc)
    discovery_run_id = ci_discovery_run_repo.create_run(
        tenant_id,
        seller_product_ref=seller_product.product_id,
        requested_by=requested_by,
        status="SEARCHING",
        provider_name=provider_name,
    )

    query_result: DiscoveryQueryRunResult = run_discovery_queries(
        tenant_id=tenant_id,
        discovery_run_id=discovery_run_id,
        seller_product=seller_product,
        provider=provider,
        provider_name=provider_name,
        cache=cache,
        budget=budget,
        discovery_enabled=discovery_enabled,
    )

    if not discovery_enabled:
        ci_discovery_run_repo.update_status(tenant_id, discovery_run_id, status="COMPLETE", finished_at=now)
        return DiscoveryRunOutcome(
            discovery_run_id=discovery_run_id,
            status="COMPLETE",
            raw_candidate_count=0,
            analyzed_candidate_count=0,
            recommended_candidate_ids=(),
            uncertain_candidate_ids=(),
            partial_reason=None,
            failed_reason=None,
        )

    if not query_result.raw_results and query_result.query_errors:
        failed_reason = f"all queries failed: {query_result.query_errors[0].error}"
        ci_discovery_run_repo.update_status(
            tenant_id, discovery_run_id, status="FAILED", failed_reason=failed_reason, finished_at=now
        )
        return DiscoveryRunOutcome(
            discovery_run_id=discovery_run_id,
            status="FAILED",
            raw_candidate_count=0,
            analyzed_candidate_count=0,
            recommended_candidate_ids=(),
            uncertain_candidate_ids=(),
            partial_reason=None,
            failed_reason=failed_reason,
        )

    ci_discovery_run_repo.update_status(tenant_id, discovery_run_id, status="DISCOVERING")

    # -- a candidate the seller already rejected for this product is not re-surfaced (§6.24) --
    rejected = ci_candidate_repo.rejected_urls(tenant_id, seller_product.product_id)
    # plainly-not-a-competitor leads (books, keyword-stuffed titles, titles too short to name a product) are never surfaced (owner decision 2026-10-20)
    raw_results = tuple(r for r in query_result.raw_results if r.url not in rejected and not is_junk(r.title))

    # -- create RAW candidates for every deduplicated raw result --------------------------
    raw_candidate_ids: list[UUID] = []
    for result in raw_results:
        candidate_id = ci_candidate_repo.create_candidate(
            tenant_id,
            discovery_run_id=discovery_run_id,
            candidate_url=result.url,
            origin="DISCOVERED",
            marketplace=_candidate_marketplace(result.url),
            tier="RAW",
        )
        raw_candidate_ids.append(candidate_id)

    # -- identity resolution + relevance scoring on the analyzed subset (Sec 6.12.1 cap) --
    analyzed_ids = raw_candidate_ids[: budget.max_analyzed_candidates]
    uncertain_ids: list[UUID] = []
    scored: list[tuple[UUID, RelevanceBreakdown]] = []
    titles: dict[UUID, str | None] = {}

    for candidate_id, result in zip(analyzed_ids, raw_results[: budget.max_analyzed_candidates]):
        titles[candidate_id] = result.title
        resolution = resolve_identity(result, seller_product)
        ci_candidate_repo.set_identity_resolution(tenant_id, candidate_id, resolution, tier="ANALYZED")

        outcome = gate(resolution.identity_match)
        if outcome is GatingOutcome.BLOCKED_FOR_REVIEW:
            uncertain_ids.append(candidate_id)
            # Identity cannot be confirmed (a product with no recorded brand, or a title with none): the lead is still scored by what is visible so the seller can see which are worth
            # a look. Its identity stays UNCERTAIN, it is never presented as the same product, and it is never a verified observation (owner decision 2026-10-20).
            breakdown, _relationship = _score_and_classify(tenant_id, candidate_id, result, seller_product, resolution)
            product_axis = breakdown.axis_results["product"]
            if product_axis.state is AxisState.KNOWN and product_axis.score >= 1:  # its title matches the seller's product at least in type: eligible to be surfaced, ranked by score
                scored.append((candidate_id, breakdown))
            continue

        assert enters_relevance_scoring(resolution.identity_match)
        breakdown, relationship = _score_and_classify(tenant_id, candidate_id, result, seller_product, resolution)
        if relationship.recommendable:  # C43: UNKNOWN / UNRELATED never fill the Recommended tier
            scored.append((candidate_id, breakdown))

    # -- Recommended tier: top max_recommended_candidates by score (Sec 6.15) -------------
    # recognisable brands first, then any brand, then how well the title matches; at most two leads per brand so the list is a spread of businesses, not one seller's variants
    scored.sort(key=lambda pair: rank_key(titles.get(pair[0]), pair[1].total_score), reverse=True)
    per_brand: dict[str, int] = {}
    picked: list[UUID] = []
    for candidate_id, _ in scored:
        brand = (brand_of(titles.get(candidate_id)) or "").casefold()
        if brand and per_brand.get(brand, 0) >= MAX_PER_BRAND:
            continue
        per_brand[brand] = per_brand.get(brand, 0) + 1
        picked.append(candidate_id)
    recommended_ids = tuple(picked[: budget.max_recommended_candidates])
    for candidate_id in recommended_ids:
        ci_candidate_repo.set_tier(tenant_id, candidate_id, "RECOMMENDED")

    ci_discovery_run_repo.update_candidate_counts(
        tenant_id,
        discovery_run_id,
        raw_candidate_count=len(raw_candidate_ids),
        analyzed_candidate_count=len(analyzed_ids),
    )

    return _resolve_post_discovery_status(
        tenant_id,
        discovery_run_id,
        uncertain_candidate_ids=tuple(uncertain_ids),
        recommended_candidate_ids=recommended_ids,
        raw_candidate_count=len(raw_candidate_ids),
        analyzed_candidate_count=len(analyzed_ids),
        partial_reason=query_result.partial_reason,
        now=now,
    )


def _resolve_post_discovery_status(
    tenant_id: UUID,
    discovery_run_id: UUID,
    *,
    uncertain_candidate_ids: tuple[UUID, ...],
    recommended_candidate_ids: tuple[UUID, ...],
    raw_candidate_count: int,
    analyzed_candidate_count: int,
    partial_reason: str | None,
    now: datetime,
) -> DiscoveryRunOutcome:
    """Sec 6.12.2: WAITING_FOR_REVIEW only while an UNCERTAIN candidate has no seller
    decision yet; otherwise RESEARCHING -> COMPLETE/PARTIAL in the same pass."""
    pending = _pending_uncertain(tenant_id, uncertain_candidate_ids)
    if pending:
        ci_discovery_run_repo.update_status(tenant_id, discovery_run_id, status="WAITING_FOR_REVIEW")
        return DiscoveryRunOutcome(
            discovery_run_id=discovery_run_id,
            status="WAITING_FOR_REVIEW",
            raw_candidate_count=raw_candidate_count,
            analyzed_candidate_count=analyzed_candidate_count,
            recommended_candidate_ids=recommended_candidate_ids,
            uncertain_candidate_ids=tuple(pending),
            partial_reason=partial_reason,
            failed_reason=None,
        )

    ci_discovery_run_repo.update_status(tenant_id, discovery_run_id, status="RESEARCHING")
    final_status = "PARTIAL" if partial_reason else "COMPLETE"
    ci_discovery_run_repo.update_status(
        tenant_id, discovery_run_id, status=final_status, partial_reason=partial_reason, finished_at=now
    )
    return DiscoveryRunOutcome(
        discovery_run_id=discovery_run_id,
        status=final_status,
        raw_candidate_count=raw_candidate_count,
        analyzed_candidate_count=analyzed_candidate_count,
        recommended_candidate_ids=recommended_candidate_ids,
        uncertain_candidate_ids=(),
        partial_reason=partial_reason,
        failed_reason=None,
    )


def _pending_uncertain(tenant_id: UUID, candidate_ids: tuple[UUID, ...]) -> list[UUID]:
    pending: list[UUID] = []
    for candidate_id in candidate_ids:
        candidate = ci_candidate_repo.get_candidate(tenant_id, candidate_id)
        if candidate is not None and candidate["seller_decision"] == "NONE":
            pending.append(candidate_id)
    return pending


def advance_after_review(tenant_id: UUID, discovery_run_id: UUID) -> DiscoveryRunOutcome:
    """Re-checks a `WAITING_FOR_REVIEW` run after a seller decision: if every `UNCERTAIN`
    candidate now has a decision, advances RESEARCHING -> COMPLETE/PARTIAL. A no-op (returns
    the run unchanged) if the run isn't `WAITING_FOR_REVIEW` or candidates are still
    undecided. Called by `accept_candidate`/`reject_candidate` below - a caller never needs
    to invoke this separately in the normal flow."""
    run = ci_discovery_run_repo.get_run(tenant_id, discovery_run_id)
    if run is None:
        raise ValueError(f"discovery run {discovery_run_id} not found")

    if run["status"] != "WAITING_FOR_REVIEW":
        return _outcome_from_row(run)

    all_candidates = ci_candidate_repo.list_candidates_for_run(tenant_id, discovery_run_id)
    uncertain_ids = tuple(
        UUID(str(c["id"])) for c in all_candidates if c["identity_match"] == IdentityMatch.UNCERTAIN.value
    )
    recommended_ids = tuple(UUID(str(c["id"])) for c in all_candidates if c["tier"] == "RECOMMENDED")

    return _resolve_post_discovery_status(
        tenant_id,
        discovery_run_id,
        uncertain_candidate_ids=uncertain_ids,
        recommended_candidate_ids=recommended_ids,
        raw_candidate_count=run["raw_candidate_count"],
        analyzed_candidate_count=run["analyzed_candidate_count"],
        partial_reason=run["partial_reason"],
        now=datetime.now(timezone.utc),
    )


# --------------------------------------------------------------------------------------
# Seller decisions - Sec 6.15 rule 4 ("Accept / Reject / Add manually / Promote to
# analysis"), Sec 6.15 rule 6 (accepting promotes into a tracked competitor_url), Sec 6.13.3
# ("Competitor is not a thing discovery finds. It is a relationship a seller approves.").
# `ci_candidate.seller_decision` is written ONLY through ci_candidate_repo.set_seller_decision
# - never by resolve_identity/gate - so a human decision can never be confused with a
# machine judgement (Sec 5.4's "must stay distinguishable" table).
# --------------------------------------------------------------------------------------


class CandidateNotFound(Exception):
    pass


class CandidateNotAllowlisted(Exception):
    """Raised on accept when the candidate's URL never resolved to an allowlisted
    marketplace host (Sec 6.15 rule 6: "subject to the same C4/D7 allowlist check ... as
    manual intake") - never silently promoted anyway."""


class AnalysisBudgetExceeded(Exception):
    """Raised by `promote_to_analysis` when the run has already reached
    `max_analyzed_candidates` - a manual promotion "consumes budget on the same terms as any
    other analyzed candidate" (Sec 6.15 rule 4), it does not bypass the cap."""


@dataclass(frozen=True, slots=True)
class AcceptCandidateResult:
    competitor_url_id: UUID
    run_outcome: DiscoveryRunOutcome


def accept_candidate(tenant_id: UUID, candidate_id: UUID, *, decided_by: UUID) -> AcceptCandidateResult:
    """Sec 6.15 rule 6: promotes an accepted candidate into a tracked `competitor_url`,
    subject to the identical C4/D7 allowlist check `competitor_url_repo.create_url` already
    enforces for manual intake - no separate/looser check is introduced here. The new
    `competitor_url` starts `evidence_status = AWAITING_EVIDENCE` (the column's own default),
    exactly the same "Approved - awaiting evidence" state Sec 6.10.3 requires until the
    seller uploads real evidence through the existing, unrelated evidence pipeline.

    `linked_sku` is set from the discovery run's own `seller_product_ref` (competitor-
    intelligence-agent.md Sec 5.4: "the SellerProduct.product_id this run is for") - this is
    what Checkpoint 6's price-band/comparison features scope a "tracked competitor" to a
    specific seller product by. A competitor_url added through the older, still-supported
    manual-URL path (no discovery run behind it) has no such linkage and is a known,
    documented gap for a future pass, not something this checkpoint silently fabricates."""
    candidate = ci_candidate_repo.get_candidate(tenant_id, candidate_id)
    if candidate is None:
        raise CandidateNotFound(str(candidate_id))
    if candidate["marketplace"] is None:
        raise CandidateNotAllowlisted(
            f"candidate {candidate_id}'s URL is not on the trusted-domain allowlist (C4/D7)"
        )

    run = ci_discovery_run_repo.get_run(tenant_id, UUID(str(candidate["discovery_run_id"])))
    linked_sku = run["seller_product_ref"] if run is not None else None

    competitor_url_id = competitor_url_repo.create_url(  # raises WatchlistFull when every slot is taken: the lead then stays undecided
        tenant_id,
        marketplace=Marketplace(candidate["marketplace"]),
        url=candidate["candidate_url"],
        added_by=decided_by,
        linked_sku=linked_sku,
    )
    ci_candidate_repo.set_seller_decision(tenant_id, candidate_id, decision="APPROVED", decided_by=decided_by)
    ci_candidate_repo.set_competitor_url_id(tenant_id, candidate_id, competitor_url_id)

    run_outcome = advance_after_review(tenant_id, UUID(str(candidate["discovery_run_id"])))
    return AcceptCandidateResult(competitor_url_id=competitor_url_id, run_outcome=run_outcome)


def reject_candidate(tenant_id: UUID, candidate_id: UUID, *, decided_by: UUID) -> DiscoveryRunOutcome:
    """The mirror of `accept_candidate` - never promotes anything, just records the human
    decision and lets a blocked run advance if this was the last pending `UNCERTAIN`
    candidate."""
    candidate = ci_candidate_repo.get_candidate(tenant_id, candidate_id)
    if candidate is None:
        raise CandidateNotFound(str(candidate_id))

    ci_candidate_repo.set_seller_decision(tenant_id, candidate_id, decision="REJECTED", decided_by=decided_by)
    return advance_after_review(tenant_id, UUID(str(candidate["discovery_run_id"])))


def promote_to_analysis(
    tenant_id: UUID,
    candidate_id: UUID,
    *,
    seller_product: SellerProduct,
    candidate_result: SearchResult,
    budget: DiscoveryBudget,
) -> RelevanceBreakdown | None:
    """Sec 6.15 rule 4: pulls one of the "Unanalyzed search results" (a `RAW` candidate that
    never entered analysis because the run's `max_analyzed_candidates` cap was already hit)
    into identity resolution + relevance scoring by explicit seller action. `candidate_result`
    is the same title/url/snippet shape used at discovery time - the caller re-supplies it
    (this module holds no long-lived cache of raw provider output beyond `ci_search_result`,
    which the caller may read via `ci_search_result_repo` to reconstruct it). Returns `None`
    if identity resolution rejects or blocks it (mirrors the automatic pipeline's own
    behaviour for a `NOT_A_MATCH`/`UNCERTAIN` result - a promotion does not bypass gating)."""
    candidate = ci_candidate_repo.get_candidate(tenant_id, candidate_id)
    if candidate is None:
        raise CandidateNotFound(str(candidate_id))

    run = ci_discovery_run_repo.get_run(tenant_id, UUID(str(candidate["discovery_run_id"])))
    if run is None:
        raise ValueError(f"discovery run for candidate {candidate_id} not found")
    if int(run["analyzed_candidate_count"] or 0) >= budget.max_analyzed_candidates:
        raise AnalysisBudgetExceeded(
            f"run {run['id']} has already reached max_analyzed_candidates={budget.max_analyzed_candidates}"
        )

    ci_candidate_repo.set_origin(tenant_id, candidate_id, "PROMOTED_BY_SELLER")

    resolution = resolve_identity(candidate_result, seller_product)
    ci_candidate_repo.set_identity_resolution(tenant_id, candidate_id, resolution, tier="ANALYZED")
    ci_discovery_run_repo.update_candidate_counts(
        tenant_id,
        UUID(str(candidate["discovery_run_id"])),
        raw_candidate_count=int(run["raw_candidate_count"] or 0),
        analyzed_candidate_count=int(run["analyzed_candidate_count"] or 0) + 1,
    )

    if not enters_relevance_scoring(resolution.identity_match):
        if resolution.identity_match is IdentityMatch.UNCERTAIN:
            # A manually-promoted candidate can also block the run for review, same as an
            # automatically-discovered one (Sec 6.13.2 draws no distinction by origin).
            advance_after_review(tenant_id, UUID(str(candidate["discovery_run_id"])))
        return None

    breakdown, _relationship = _score_and_classify(tenant_id, candidate_id, candidate_result, seller_product, resolution)
    return breakdown


def _score_and_classify(
    tenant_id: UUID,
    candidate_id: UUID,
    result: SearchResult,
    seller_product: SellerProduct,
    resolution: IdentityResolution,
) -> tuple[RelevanceBreakdown, Relationship]:
    """Relevance (§6.14) then relationship (§6.27.1, C43) for a candidate that has cleared the
    identity gate; both are persisted. Relationship is derived from the scored axes and the
    identity result — it never feeds back into the score."""
    inputs = build_relevance_inputs(result, seller_product, resolution)
    breakdown = score_relevance(inputs, is_provisional=True)
    ci_candidate_relevance_repo.insert_relevance(tenant_id, candidate_id=candidate_id, breakdown=breakdown)
    axes = breakdown.axis_results
    relationship = classify_relationship(
        resolution.identity_match, category=axes["category"], product=axes["product"], use_case=axes["use_case"]
    )
    ci_candidate_repo.set_relationship(
        tenant_id,
        candidate_id,
        relationship_class=relationship.relationship_class.value,
        basis=relationship.basis,
        is_provisional=relationship.is_provisional,
    )
    return breakdown, relationship


def _outcome_from_row(run: dict[str, object]) -> DiscoveryRunOutcome:
    return DiscoveryRunOutcome(
        discovery_run_id=UUID(str(run["id"])),
        status=str(run["status"]),
        raw_candidate_count=int(run["raw_candidate_count"] or 0),  # type: ignore[arg-type]
        analyzed_candidate_count=int(run["analyzed_candidate_count"] or 0),  # type: ignore[arg-type]
        recommended_candidate_ids=(),
        uncertain_candidate_ids=(),
        partial_reason=run["partial_reason"] if isinstance(run["partial_reason"], (str, type(None))) else None,
        failed_reason=run["failed_reason"] if isinstance(run["failed_reason"], (str, type(None))) else None,
    )
