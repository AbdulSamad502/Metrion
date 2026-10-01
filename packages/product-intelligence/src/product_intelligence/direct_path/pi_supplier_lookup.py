"""pi.supplier_lookup — separate trigger: seller's chosen top-5 (or fewer) `candidate_ids` ->
Google Places + Tavily supplier leads. PI build plan §2. No ranking, no score (C4 — CFO ranks
suppliers, from seller-supplied quotes only, not this module).

**Cost-bounding split enforced here, per the plan's own instruction** (`google_places_client.py`'s
docstring names this file as the enforcement point): `search_place_ids` (free/uncapped tier)
is called once per candidate to find matches; `enrich_place` (paid Pro-tier phone/website/
address fields) is called only for the single best-matching place per candidate — never for
every match `search_place_ids` returns, and never for anything beyond the candidate set this
function was explicitly called with (the caller already narrowed to the seller's chosen
top-5, this function does not further expand that set).

**Concurrency (bug-fix pass, 2026-09-30):** the per-candidate Places+Tavily lookup loop was
previously sequential; it now runs through a bounded `ThreadPoolExecutor`
(`_MAX_CONCURRENT_CANDIDATE_LOOKUPS` workers). Each candidate's lookup still degrades
independently on failure — a `PlacesUnavailable`/`TavilyUnavailable` in one candidate's
lookup only sets *that* candidate's `degraded_reason`, never touching another candidate's
result or aborting the run, same as before.
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Sequence
from urllib.parse import urlparse
from uuid import UUID

from product_intelligence.repositories import product_candidate_repo, supplier_lead_repo
from product_intelligence.sources.rate_limiter import throttle
from product_intelligence.sources.tavily_client import TavilyClient, TavilySearchResult, TavilyUnavailable
from product_intelligence.supplier.google_places_client import PlacesClient, PlacesUnavailable

_MAX_PLACES_MATCHES_PER_CANDIDATE = 5
_MAX_TAVILY_LEADS_PER_CANDIDATE = 3
# Overfetch beyond the final lead cap so `_filter_and_rank_supplier_results` has enough raw
# results to filter obvious non-suppliers out of and still leave up to
# `_MAX_TAVILY_LEADS_PER_CANDIDATE` genuine leads.
_MAX_TAVILY_RAW_RESULTS_PER_CANDIDATE = 10
_MAX_CONCURRENT_CANDIDATE_LOOKUPS = 5  # bounded deliberately — see module docstring

# Editorial/listicle-shaped title signal — a result whose title reads like an article about
# products, not a supplier's own page, is excluded (module docstring below). Distinct from
# `candidate_synthesis.py`'s `_STOPWORDS` (a tokenization filter, different purpose).
_EDITORIAL_TITLE_PATTERN = re.compile(
    r"\b(\d+\s+best|best\s+\d*|top\s+\d+|buying\s+guide|review|reviews|comparison|vs\.?)\b",
    re.IGNORECASE,
)

# Supplier-signal words — a result whose title/content contains these reads like an actual
# manufacturer/wholesaler/distributor page, not editorial content or a retail storefront.
_SUPPLIER_SIGNAL_WORDS = (
    "manufacturer", "manufacturers", "wholesale", "wholesaler", "supplier", "suppliers",
    "exporter", "exporters", "factory", "distributor", "distributors", "oem",
)

# Well-known major consumer retail/brand storefront domains — a seller looking for a wholesale
# contact almost never wants these. Not remotely exhaustive; see module docstring's honesty
# note on this filter's limits.
_RETAIL_STOREFRONT_DOMAINS = frozenset(
    {
        "amazon.in", "amazon.com", "flipkart.com", "meesho.com", "myntra.com", "ajio.com",
        "nykaa.com", "snapdeal.com", "tatacliq.com", "reliancedigital.in", "croma.com",
        "walmart.com", "ebay.com", "aliexpress.com", "alibaba.com",
    }
)

# Social/content platforms — never a supplier contact under any circumstance, regardless of
# what the post/page is about. Found as a real live-data bug (quality pass, 2026-10-01): an
# Instagram post and a Facebook post about a product both passed the pre-existing filter and
# were persisted as "supplier leads" with no contact info at all, since a social post is never
# a business's own site to begin with.
_SOCIAL_MEDIA_DOMAINS = frozenset(
    {
        "instagram.com", "facebook.com", "twitter.com", "x.com", "pinterest.com",
        "tiktok.com", "youtube.com", "youtu.be", "reddit.com", "threads.net", "linkedin.com",
    }
)

# Official/retail-storefront framing in a title — "buy X online", "official store" etc. read
# as a brand's own consumer-facing retail page, not a B2B wholesale contact.
_RETAIL_STOREFRONT_TITLE_PATTERN = re.compile(
    r"\b(buy\s+.+\s+online|official\s+store|shop\s+now|online\s+store)\b", re.IGNORECASE
)


def _domain(url: str) -> str:
    try:
        netloc = urlparse(url).netloc.lower()
    except ValueError:
        return url
    return netloc[4:] if netloc.startswith("www.") else netloc


def _collapsed(text: str) -> str:
    """Lowercased, alphanumeric-only — used only to compare a candidate's own brand/product
    identity against a result's domain (e.g. "New Balance" -> "newbalance" matches the domain
    "newbalance.com"'s registrable-label form). Same conservative spirit as
    `candidate_synthesis.py`'s own `_collapsed_key` for near-identical-spelling matching."""
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _is_candidates_own_brand_domain(result: TavilySearchResult, candidate_title: str) -> bool:
    """A result whose domain IS the candidate's own brand (e.g. "newbalance.com" for a "New
    Balance 1080v15" candidate) is the brand's own site, not a third-party wholesale supplier
    — a seller researching where to SOURCE a product from a manufacturer/distributor almost
    never wants the original brand's own consumer storefront. Compares the domain's own first
    label against a PREFIX of the candidate title's collapsed form, not just its first word —
    multi-word brand names ("New Balance" -> "newbalance.com") need more than one word to
    match. A domain label under 3 characters is never checked (too short to be a meaningful
    brand match); only `netloc` is compared, never `content`, so a domain that merely
    *mentions* the brand elsewhere in its path is never excluded by this check alone."""
    domain = _domain(result.url)
    domain_label = domain.split(".")[0] if domain else ""
    if len(domain_label) < 3:
        return False
    # Bug-hunt pass (2026-10-01): `domain_label` was compared raw (hyphens/digits intact)
    # against `collapsed_title` (fully alphanumeric-collapsed) — for any domain whose first
    # label contains a hyphen (e.g. "new-balance-store.com"), `collapsed_title.startswith(...)`
    # could never match even when the brand genuinely is that domain, silently under-excluding
    # a brand's own storefront. Both sides must go through the same collapsing.
    collapsed_domain_label = _collapsed(domain_label)
    collapsed_title = _collapsed(candidate_title)
    return bool(collapsed_title) and bool(collapsed_domain_label) and collapsed_title.startswith(collapsed_domain_label)


def _looks_like_supplier(result: TavilySearchResult, *, candidate_title: str) -> bool:
    """Heuristic relevance filter for a Tavily "supplier" search result, applied before it is
    ever persisted as a `supplier_lead` — a real bug found in a live run: unfiltered results
    included a major brand's official retail store, a "10 BEST ..." review/listicle article,
    and a foreign (non-Indian) supplier alongside genuine Indian manufacturer/wholesaler
    leads. **Extended (quality pass, 2026-10-01)** after a second live run surfaced two more
    non-supplier shapes slipping through: social-media posts (Instagram/Facebook, which carry
    no contact info at all) and the candidate's own brand selling direct-to-consumer on its
    own domain (also not a wholesale source).

    **This is a heuristic filter, not a guarantee** — same "heuristic, not formal proof"
    honesty this codebase's `narration_safety.py` already models elsewhere. It has no
    exhaustive domain blocklist (impossible to maintain) and no ground-truth "is this
    actually a supplier" signal; it only rejects the shapes of result most likely to be
    noise (editorial/listicle content, known major retail storefronts, social-media posts,
    the candidate's own brand domain, "buy X online"/"official store" framing) and prefers
    results carrying an explicit supplier-signal word. A genuine supplier lead with an
    unusual title can still be filtered out incorrectly, and a well-disguised non-supplier
    can still pass — this narrows the noise, it does not eliminate it.
    """
    title = result.title or ""

    if _EDITORIAL_TITLE_PATTERN.search(title):
        return False

    domain = _domain(result.url)
    if domain in _RETAIL_STOREFRONT_DOMAINS or domain in _SOCIAL_MEDIA_DOMAINS:
        return False
    if _RETAIL_STOREFRONT_TITLE_PATTERN.search(title):
        return False
    if _is_candidates_own_brand_domain(result, candidate_title):
        return False

    return True


def _has_supplier_signal(result: TavilySearchResult) -> bool:
    combined = f"{result.title or ''} {result.content or ''}".lower()
    return any(word in combined for word in _SUPPLIER_SIGNAL_WORDS)


def _filter_and_rank_supplier_results(
    results: list[TavilySearchResult], *, max_results: int, candidate_title: str
) -> list[TavilySearchResult]:
    """Applies `_looks_like_supplier` to exclude obvious non-suppliers, then boosts results
    carrying an explicit supplier-signal word ("manufacturer", "wholesale", etc.) to the
    front — a stable sort, so relative order among equally-scored results is preserved."""
    plausible = [r for r in results if _looks_like_supplier(r, candidate_title=candidate_title)]
    ranked = sorted(plausible, key=lambda r: not _has_supplier_signal(r))
    return ranked[:max_results]


@dataclass(frozen=True, slots=True)
class SupplierLookupResult:
    candidate_id: UUID
    lead_ids: tuple[UUID, ...]
    degraded_reason: str | None


def _supplier_query(candidate_title: str) -> str:
    return f"{candidate_title} manufacturer supplier wholesale india"


def lookup_suppliers_for_candidates(
    tenant_id: UUID,
    *,
    run_id: UUID,
    candidate_ids: Sequence[UUID],
    places: PlacesClient,
    tavily: TavilyClient,
    now: datetime | None = None,
) -> list[SupplierLookupResult]:
    """Only ever called with a seller-approved top-5-or-fewer set — this function trusts its
    `candidate_ids` argument as already narrowed (module docstring); it performs no ranking
    or further selection of *which* candidates to look up, only *which supplier lead* best
    matches each one already-chosen candidate."""
    now = now or datetime.now(timezone.utc)

    def _lookup_for_one_candidate(candidate_id: UUID) -> SupplierLookupResult:
        candidate = product_candidate_repo.get_candidate(tenant_id, candidate_id)
        if candidate is None:
            return SupplierLookupResult(candidate_id=candidate_id, lead_ids=(), degraded_reason="candidate not found")

        query = _supplier_query(str(candidate.get("candidate_title", "")))
        lead_ids: list[UUID] = []
        degraded_reason: str | None = None

        try:
            with throttle("google_places"):
                place_matches = places.search_place_ids(query, max_results=_MAX_PLACES_MATCHES_PER_CANDIDATE)
        except PlacesUnavailable as exc:
            place_matches = []
            degraded_reason = f"Google Places unavailable: {exc}"

        if place_matches:
            best_match = place_matches[0]
            try:
                with throttle("google_places"):
                    details = places.enrich_place(best_match.place_id)
            except PlacesUnavailable as exc:
                details = None
                degraded_reason = "; ".join(p for p in (degraded_reason, f"Places enrichment unavailable: {exc}") if p)

            contact = None
            if details is not None:
                contact = {"phone": details.phone, "website": details.website, "moq": None}

            lead_id = supplier_lead_repo.insert_lead(
                tenant_id,
                run_id=run_id,
                candidate_id=candidate_id,
                supplier_name=(details.display_name if details else best_match.display_name),
                source="GOOGLE_PLACES",
                contact=contact,
                locality=details.formatted_address if details else None,
                distance_km=None,
                category_match=None,
                source_url=None,
                fetched_at=now,
            )
            lead_ids.append(lead_id)

        try:
            with throttle("tavily"):
                raw_web_results = tavily.search(
                    query, include_images=False, max_results=_MAX_TAVILY_RAW_RESULTS_PER_CANDIDATE
                )
        except TavilyUnavailable as exc:
            raw_web_results = []
            degraded_reason = "; ".join(p for p in (degraded_reason, f"Tavily supplier search unavailable: {exc}") if p)

        web_results = _filter_and_rank_supplier_results(
            raw_web_results,
            max_results=_MAX_TAVILY_LEADS_PER_CANDIDATE,
            candidate_title=str(candidate.get("candidate_title", "")),
        )

        for result in web_results:
            lead_id = supplier_lead_repo.insert_lead(
                tenant_id,
                run_id=run_id,
                candidate_id=candidate_id,
                supplier_name=result.title,
                source="TAVILY",
                contact=None,
                locality=None,
                distance_km=None,
                category_match=None,
                source_url=result.url,
                fetched_at=now,
            )
            lead_ids.append(lead_id)

        if not lead_ids and degraded_reason is None:
            degraded_reason = "no supplier lead found from Google Places or Tavily for this candidate"

        return SupplierLookupResult(candidate_id=candidate_id, lead_ids=tuple(lead_ids), degraded_reason=degraded_reason)

    if not candidate_ids:
        return []

    with ThreadPoolExecutor(max_workers=min(_MAX_CONCURRENT_CANDIDATE_LOOKUPS, len(candidate_ids))) as executor:
        # `map` preserves input order in its return order (submission still happens
        # concurrently up front) — each candidate's Places+Tavily lookup degrades
        # independently via its own try/except inside `_lookup_for_one_candidate`, never
        # taking down another candidate's lookup or the whole run.
        return list(executor.map(_lookup_for_one_candidate, candidate_ids))
