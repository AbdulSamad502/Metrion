"""`gst_applicability_lookup` — the G2 composition function. Implements §8.4.1's exact
sequence: iterate known pages in Tier 1 then Tier 2 order, fetch each (skip any fetch that
errors, per `FetchError`), pass fetched text + query to the LLM extraction step (L7), stop at
the first genuine match, return `GstLookupNoMatch` if every attempt fails or yields nothing.

No calculation happens here (§8.4: "A research feature. Structurally isolated from the
calculation engine.") — this function never touches `calc_engine.api.compute_metric` or any
formula, and its result never carries an `engine_result_ref`. L2 (never applies automatically)
is enforced by omission: there is no code path anywhere in this module, or this checkpoint,
that feeds a `GstLookupResult` into a calculation — that wiring (behind explicit seller
acceptance) is G3's concern, not built here.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from calc_engine.gst_lookup.allowlist import TIER_1, is_allowed_gst_host, tier_for_host
from calc_engine.gst_lookup.extraction import build_extraction_prompt, parse_extraction_response
from calc_engine.gst_lookup.fetcher import FetchError, GstFetcher, RawPage
from calc_engine.gst_lookup.known_pages import KNOWN_PAGES, KnownPage
from calc_engine.gst_lookup.llm_provider import LlmProvider
from calc_engine.gst_lookup.types import GstLookupNoMatch, GstLookupQuery, GstLookupResult

_TIER_ORDER = {TIER_1: 0}  # anything else (TIER_2, or unknown) sorts after TIER_1.


def _sorted_known_pages(pages: tuple[KnownPage, ...]) -> list[KnownPage]:
    """Tier 1 before Tier 2 (§8.4.1: "Tier 1 then Tier 2 order"), stable within a tier."""
    return sorted(pages, key=lambda p: _TIER_ORDER.get(tier_for_host(p.url) or "", 1))


def _relevant_pages(query: GstLookupQuery, pages: tuple[KnownPage, ...]) -> list[KnownPage]:
    """§8.4.1: "fetches the relevant known page(s) for the query's category (where a category
    is available in the input) or a general rate-schedule page." No known page here is
    labelled "general" (every one is category-specific, per `known_pages.py`), so: if the
    query names a category, pages whose `category` hint shares a case-insensitive word overlap
    with it are tried first, followed by every other page (a category hint is a relevance
    ranking, never an exclusion — a query with an imprecise category label should still be
    able to match a page via its product title). If the query has no category at all, every
    known page is tried, in tier order, matched against the product title instead."""
    ordered = _sorted_known_pages(pages)
    if not query.category:
        return ordered

    needle_words = {w for w in query.category.lower().split() if len(w) > 2}

    def _relevance(page: KnownPage) -> tuple[int, int]:
        page_words = set(page.category.lower().replace(",", " ").split())
        overlap = len(needle_words & page_words)
        tier_rank = _TIER_ORDER.get(tier_for_host(page.url) or "", 1)
        return (0 if overlap > 0 else 1, tier_rank)

    return sorted(ordered, key=_relevance)


def gst_applicability_lookup(
    query: GstLookupQuery,
    *,
    fetcher: GstFetcher,
    llm: LlmProvider,
    tenant_id: UUID,
    computed_at: datetime,
    model: str,
    known_pages: tuple[KnownPage, ...] = KNOWN_PAGES,
) -> GstLookupResult | GstLookupNoMatch:
    """§8.4.1's fetch-then-extract sequence. `computed_at` is the caller-supplied "now" (kept
    as a parameter, not `datetime.now()` called internally, for determinism in tests and
    consistency with this package's house style of caller-supplied clocks); `retrieved_at` on
    a genuine result is this same value."""
    attempted_urls: list[str] = []

    for page in _relevant_pages(query, known_pages):
        if not is_allowed_gst_host(page.url):
            # Structurally should never happen (known_pages.py only ever cites allowlisted
            # domains) — defence in depth, mirroring the allowlist check running before every
            # fetch in competitor_intelligence.capture.
            continue

        attempted_urls.append(page.url)
        fetched = fetcher.fetch(page.url)
        if isinstance(fetched, FetchError):
            continue  # §8.4.1: a failed fetch produces no result row; try the next page.

        assert isinstance(fetched, RawPage)
        prompt = build_extraction_prompt(query, page_text=fetched.body, source_url=page.url)
        raw_response = llm.complete(model=model, prompt=prompt)
        extracted = parse_extraction_response(raw_response)
        if extracted is None:
            continue  # no genuine match on this page, or a malformed response — same path.

        return GstLookupResult(
            id=uuid4(),
            tenant_id=tenant_id,
            query_text=query.product_title,
            source_url=page.url,
            retrieved_at=computed_at,
            sku=query.sku,
            query_hsn=query.hsn,
            likely_rate_pct=extracted.rate_pct,
            likely_hsn=extracted.hsn,
            likely_category=extracted.category,
            ambiguity_note=extracted.ambiguity_note if extracted.ambiguous else None,
            alternatives=extracted.alternatives,
            source_title=page.source_title,
        )

    return GstLookupNoMatch(query_text=query.product_title, attempted_urls=tuple(attempted_urls))
