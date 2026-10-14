"""PI action composition — mirrors `ci_actions.py`/`cfo_actions.py`'s role: the shared layer
between `api/v1/pi.py`'s direct-execution routes and (Phase 2's explicitly deferred scope,
per the plan's own boundary) any future CEO-routed call, "so they can never quietly diverge
on how inputs are assembled." **CEO Hub wiring is out of scope for this change entirely** —
nothing here is imported by `agents/ceo_hub.py`, and this module imports nothing from it.

The real source clients (`HttpTavilyClient`/`HttpYoutubeClient`/`HttpPlacesClient`/
`OllamaTextInsightExtractor`/`OllamaEmbeddingClient`) are wired up only here, at the
composition root — `packages/product-intelligence`'s own modules stay composition-agnostic
(Protocol + real implementation, never self-wiring), matching `ci_actions.py`'s
`MockSearchProvider`/`PostgresSearchResultCache` precedent.

`_QUERY_CACHE` is a module-level singleton, not created fresh per call — `sources/cache.py`'s
own docstring is explicit that its whole purpose is a *process-wide* (not per-tenant,
per-request) cache to stop concurrent tenants fanning out 1:1 to Tavily/YouTube's shared
free-tier quota; a fresh `InProcessQueryCache()` per call would defeat that entirely.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from product_intelligence.direct_path.pi_discover import PiRunResult, submit_pi_discover
from product_intelligence.direct_path import pi_case
from product_intelligence.direct_path.pi_report import PiReport, render_report
from product_intelligence.direct_path.pi_supplier_lookup import SupplierLookupResult, lookup_suppliers_for_candidates
from product_intelligence.discovery.discovery_run import DEFAULT_CANDIDATE_CAP
from product_intelligence.discovery.top5_images import HttpImageVerifier, ImageVerifier, resolve_top5_images
from product_intelligence.discovery.product_extraction import OllamaProductExtractionClient, ProductExtractionClient
from product_intelligence.embedding.embed import EmbeddingClient, OllamaEmbeddingClient
from product_intelligence.repositories import niche_brief_repo, pi_research_history_repo
from product_intelligence.review_insight.text_extraction import OllamaTextInsightExtractor, TextInsightExtractor
from product_intelligence.sources.cache import InProcessQueryCache, QueryCache
from product_intelligence.sources.tavily_client import HttpTavilyClient, TavilyClient
from product_intelligence.sources.youtube_client import HttpYoutubeClient, YoutubeClient
from product_intelligence.supplier.google_places_client import HttpPlacesClient, PlacesClient

from backend.config import (
    google_places_api_key,
    ollama_host,
    pi_embedding_model,
    pi_product_extraction_model,
    pi_text_insight_model,
    tavily_api_key,
    youtube_api_key,
)

_QUERY_CACHE: QueryCache = InProcessQueryCache()


def _tavily_client() -> TavilyClient:
    return HttpTavilyClient(api_key=tavily_api_key())


def _youtube_client() -> YoutubeClient:
    return HttpYoutubeClient(api_key=youtube_api_key())


def _places_client() -> PlacesClient:
    return HttpPlacesClient(api_key=google_places_api_key())


def _text_extractor() -> TextInsightExtractor:
    return OllamaTextInsightExtractor(host=ollama_host(), model=pi_text_insight_model())


def _product_extraction_client() -> ProductExtractionClient:
    return OllamaProductExtractionClient(host=ollama_host(), model=pi_product_extraction_model())


def _image_verifier() -> ImageVerifier:
    return HttpImageVerifier()


def _embedding_client() -> EmbeddingClient:
    return OllamaEmbeddingClient(host=ollama_host(), model=pi_embedding_model())


def json_safe(value: Any) -> Any:
    """Recursively converts `UUID`/`datetime`/`date`/`Decimal` (raw `SELECT *` row values from
    `product_intelligence`'s repositories, which never pre-serialize for HTTP) into
    JSON-safe primitives. `jsonb` columns already arrive as parsed `dict`/`list` from
    psycopg — this never touches their contents beyond recursing into them."""
    if isinstance(value, dict):
        return {k: json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


# --- niche_brief CRUD composition -----------------------------------------------------------


def create_niche_brief_draft(
    tenant_id: UUID,
    *,
    created_by: UUID,
    category_text: str | None = None,
    budget_paise: int | None = None,
    target_price_min_paise: int | None = None,
    target_price_max_paise: int | None = None,
    marketplaces: list[str] | None = None,
    constraints: dict[str, Any] | None = None,
) -> UUID:
    return niche_brief_repo.create_draft(
        tenant_id,
        created_by=created_by,
        category_text=category_text,
        budget_paise=budget_paise,
        target_price_min_paise=target_price_min_paise,
        target_price_max_paise=target_price_max_paise,
        marketplaces=marketplaces,
        constraints=constraints,
    )


def get_niche_brief(tenant_id: UUID, brief_id: UUID) -> dict[str, Any] | None:
    brief = niche_brief_repo.get_brief(tenant_id, brief_id)
    return json_safe(brief) if brief is not None else None


def list_niche_briefs(tenant_id: UUID, *, status: str | None = None) -> list[dict[str, Any]]:
    return [json_safe(b) for b in niche_brief_repo.list_briefs(tenant_id, status=status)]


def update_niche_brief_draft(
    tenant_id: UUID,
    brief_id: UUID,
    *,
    category_text: str | None = None,
    budget_paise: int | None = None,
    target_price_min_paise: int | None = None,
    target_price_max_paise: int | None = None,
    marketplaces: list[str] | None = None,
    constraints: dict[str, Any] | None = None,
) -> None:
    niche_brief_repo.update_draft(
        tenant_id,
        brief_id,
        category_text=category_text,
        budget_paise=budget_paise,
        target_price_min_paise=target_price_min_paise,
        target_price_max_paise=target_price_max_paise,
        marketplaces=marketplaces,
        constraints=constraints,
    )


def mark_niche_brief_ready(tenant_id: UUID, brief_id: UUID, *, readied_at: datetime) -> None:
    niche_brief_repo.mark_ready(tenant_id, brief_id, readied_at=readied_at)


def mark_niche_brief_draft(tenant_id: UUID, brief_id: UUID) -> None:
    niche_brief_repo.mark_draft(tenant_id, brief_id)


def archive_niche_brief(tenant_id: UUID, brief_id: UUID) -> None:
    niche_brief_repo.archive(tenant_id, brief_id)


# --- pi.discover / pi.supplier_lookup / pi.report composition ------------------------------


def run_discovery(
    tenant_id: UUID,
    niche_brief_id: UUID,
    depth: str,
    *,
    requested_by: UUID,
    permission_check: str,
    entitlement_check: str,
    candidate_cap: int = DEFAULT_CANDIDATE_CAP,
    parent_run_id: UUID | None = None,
    now: datetime | None = None,
) -> PiRunResult:
    """Composes `niche_brief_repo` validation (inside `submit_pi_discover` itself) with the
    real Tavily/YouTube/cache/text-extraction/embedding clients — the same composition root
    `direct_path/pi_discover.py`'s own fakes-injected unit/integration tests already exercise,
    just with real clients instead of fakes."""
    return submit_pi_discover(
        tenant_id,
        niche_brief_id,
        depth,
        requested_by=requested_by,
        permission_check=permission_check,
        entitlement_check=entitlement_check,
        tavily=_tavily_client(),
        youtube=_youtube_client(),
        cache=_QUERY_CACHE,
        text_extractor=_text_extractor(),
        embedding_client=_embedding_client(),
        product_extraction_client=_product_extraction_client(),
        candidate_cap=candidate_cap,
        parent_run_id=parent_run_id,
        now=now,
    )


def run_supplier_lookup(
    tenant_id: UUID,
    *,
    run_id: UUID,
    candidate_ids: list[UUID],
    now: datetime | None = None,
) -> list[SupplierLookupResult]:
    """Composes `lookup_suppliers_for_candidates` with the real Google Places + Tavily
    clients. `candidate_ids` is trusted as already narrowed to the seller's chosen top-5 —
    same contract `pi_supplier_lookup.py`'s own docstring states; this composition layer adds
    no further selection."""
    return lookup_suppliers_for_candidates(
        tenant_id,
        run_id=run_id,
        candidate_ids=candidate_ids,
        places=_places_client(),
        tavily=_tavily_client(),
        now=now,
    )


def load_report(tenant_id: UUID, run_id: UUID) -> PiReport:
    return render_report(tenant_id, run_id)


def pi_run_result_to_dict(result: PiRunResult) -> dict[str, object]:
    return {
        "runId": str(result.run_id),
        "agentRunId": str(result.agent_run_id),
        "status": result.status,
        "candidateIds": [str(c) for c in result.candidate_ids],
        "shortlistedCandidateIds": [str(c) for c in result.shortlisted_candidate_ids],
        "partialReason": result.partial_reason,
        "failedReason": result.failed_reason,
    }


def supplier_lookup_result_to_dict(result: SupplierLookupResult) -> dict[str, object]:
    return {
        "candidateId": str(result.candidate_id),
        "leadIds": [str(i) for i in result.lead_ids],
        "degradedReason": result.degraded_reason,
    }


def pi_report_to_dict(report: PiReport) -> dict[str, object]:
    return {
        "runId": str(report.run_id),
        "status": report.status,
        "candidates": json_safe(report.candidates),
        "unavailable": json_safe(report.unavailable),
    }


# --- Research cases, history and pinning (docs/specs/ceo-pi-research-flow.md). Reads and flag writes over persisted data only; nothing here fetches or computes a figure. ---
CaseNotAvailable = pi_case.CaseNotAvailable


def list_research_history(tenant_id: UUID) -> list[dict[str, Any]]:
    return json_safe(pi_case.list_history(tenant_id))


def load_research_case(tenant_id: UUID, run_id: UUID) -> dict[str, Any]:
    """Raises `CaseNotAvailable` (looks identical for an unknown, another tenant's, archived or unfinished run)."""
    return json_safe(pi_case.render_case(tenant_id, run_id))


def pin_research(tenant_id: UUID, run_id: UUID, *, pinned: bool) -> None:
    """Idempotent. Unpinning re-applies the tenant's history limit (the oldest unpinned report is archived, never deleted)."""
    now = datetime.now(timezone.utc)
    if not pi_research_history_repo.set_pinned(tenant_id, run_id, pinned=pinned, now=now):
        raise CaseNotAvailable(f"no finished research report {run_id} for this tenant")
    if not pinned:
        pi_research_history_repo.archive_over_limit(tenant_id, limit=pi_research_history_repo.get_history_unpinned_limit(tenant_id), now=now)


def select_research_top5(tenant_id: UUID, run_id: UUID, *, investigation_id: UUID | None = None) -> list[UUID]:
    """Picks the five seller-facing products, then resolves a clear, verified product image for those five only (never a video thumbnail). The image step is
    external (Tavily + the image host) but costs no metered unit and never fails the case: a product without a verified image simply has none."""
    ids = pi_case.select_top5(tenant_id, run_id, investigation_id=investigation_id)
    if ids:
        resolve_top5_images(tenant_id, ids, tavily=_tavily_client(), verifier=_image_verifier())
    return ids


def finalize_research_case(tenant_id: UUID, run_id: UUID) -> dict[str, Any]:
    return pi_case.finalize_case(tenant_id, run_id)


def attach_cfo_figures(tenant_id: UUID, product_name: str, entries: list[dict[str, Any]]) -> UUID | None:
    return pi_case.attach_cfo_figures(tenant_id, product_name, entries)


def top_five_for_report(tenant_id: UUID, run_id: UUID) -> list[dict[str, Any]]:
    """The seller-facing five in rank order, for the saved-report read the CEO numbers its follow-ups by ("#1" is rank 1)."""
    try:
        case = pi_case.render_case(tenant_id, run_id)
    except CaseNotAvailable:
        return []
    return [{"rank": p["rank"], "candidateId": str(p["candidate"]["id"]), "title": p["candidate"]["candidate_title"]} for p in case["products"]]


def research_budget_for_product(tenant_id: UUID, product_name: str) -> int | None:
    return pi_case.research_budget_for_product(tenant_id, product_name)


def suppliers_for_product(tenant_id: UUID, product_name: str) -> list[dict[str, Any]]:
    return pi_case.suppliers_for_product(tenant_id, product_name)
