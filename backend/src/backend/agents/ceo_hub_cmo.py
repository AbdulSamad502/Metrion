"""CEO hub dispatch functions for Slim CMO and the GST routes (P8; spec `ceo-agent-orchestration.md` §6.9, C4, C10, C11, AC18-20).

Decision D1 (build plan): the real CEO conversational layer (classifier + composer) does not exist - `ceo_hub.py` is a dummy hub of
fixed `dispatch_*` functions. These follow that pattern: ONE call = ONE registered action (C4, star topology), a CEO `agent_run` row for
the turn, and the underlying action's own `agent_run` linked to it through `parent_run_id`. Nothing here chooses an action: the caller
(today a test or the workspace, later the real CEO) names it, and the dispatch function enforces the permissions ITSELF - a CEO that
mis-routes cannot widen access (CEO C8; GST G1). Every CMO action is recommend-only: nothing here, or in any function it calls,
writes to a marketplace.

CMO actions run through the very same handler code as the direct HTTP routes (`api/v1/cmo.py`), so authentication-independent
rules (tenant from context only, quota admission, metering, idempotency, trust gates) cannot drift between the two paths. This
module never imports CFO, PI or CI code for a CMO action (CMO never calls them) and never reads CI data itself: the optional CI themes are
brokered by the CEO orchestrator (`services/cmo_ci_inputs.py`) and arrive as plain request fields, so this dummy hub stays CI-free.

SECURITY NOTE: these functions take `tenant_id`, `role` and `permissions` as ARGUMENTS and build the auth context themselves. Their only
callers today are tests; the future CEO caller MUST pass values taken from the authenticated session, never from a request or a model.

CEO's own turn unit (D5) is not modelled by the dummy hub: the CEO row records `entitlement_check = NOT_EVALUATED` rather than a
fake PASS.

GST (C4/C11): CMO never touches GST. `dispatch_gst_lookup` selects the route from the member's permissions, never from a model:
Route A (`agent.ceo` + `agent.cfo` + `service.gst_lookup`) is CFO's `cfo.gst_lookup`; Route B (`agent.ceo` + `service.gst_lookup`,
no `agent.cfo`) is CEO's call to the shared GST Applicability Lookup. Both run the SAME tier-3 provisional lookup and return its stored
result unchanged; neither ever applies it to a calculation (G4: acceptance stays CFO's `agent.cfo` + `financials.adjust` flow).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import UUID

from fastapi import HTTPException

from backend.auth.context import AuthContext
from backend.auth.permissions import (
    AGENT_CEO, AGENT_CFO, AGENT_CMO, CATALOG_VIEW, RESEARCH_MARKET_TRENDS, SERVICE_GST_LOOKUP, has_permission,
)
from backend.entitlement import cfo_entitlement_check_value, resolve_cfo_entitlement, resolve_gst_lookup_entitlement
from backend.repositories import agent_run_repo
from backend.repositories.agent_run_repo import settles_open_runs
from backend.services import cmo_actions

logger = logging.getLogger(__name__)

NOT_EVALUATED = "NOT_EVALUATED"

# Each CMO action: (handler name in api/v1/cmo.py, the permissions required IN ADDITION to agent.ceo + agent.cmo).
CMO_DISPATCH_ACTIONS: Mapping[str, tuple[str, tuple[str, ...]]] = {
    "cmo.generate_title_sets": ("post_title_sets", ()),
    "cmo.approve_title": ("post_title_approval", ()),
    "cmo.keyword_intelligence": ("post_keyword_intelligence", ()),
    "cmo.analyze_titles": ("post_title_analysis", ()),
    "cmo.generate_listing_copy": ("post_listing_copy", ()),
    "cmo.generate_description": ("post_description", ()),
    "cmo.generate_bullets": ("post_bullets", ()),
    "cmo.generate_keywords": ("post_keywords", ()),
    "cmo.generate_backend_terms": ("post_backend_terms", ()),
    "cmo.generate_hashtags": ("post_hashtags", ()),
    "cmo.catalog_answer": ("post_catalog_answers", ()),
    "cmo.confirm_image_hint": ("post_confirm_image_hint", ()),
    "cmo.suggest_niche_terms": ("post_suggest_niche_terms", (CATALOG_VIEW,)),
    "cmo.confirm_niche_terms": ("post_confirm_niche_terms", ()),
    "cmo.market_trends": ("post_market_trends", (RESEARCH_MARKET_TRENDS,)),
}


class CeoPermissionDenied(Exception):
    def __init__(self, missing: tuple[str, ...], ceo_agent_run_id: UUID) -> None:
        super().__init__(f"missing permission(s): {', '.join(missing)}")
        self.missing, self.ceo_agent_run_id = missing, ceo_agent_run_id


class CeoDispatchError(Exception):
    """The dispatched action refused or failed with an HTTP-shaped outcome (402 quota, 409 plan changed, 422, 503, ...)."""

    def __init__(self, status_code: int, detail: Any, ceo_agent_run_id: UUID) -> None:
        super().__init__(f"{status_code}: {detail}")
        self.status_code, self.detail, self.ceo_agent_run_id = status_code, detail, ceo_agent_run_id


@dataclass(frozen=True, slots=True)
class CeoHubCmoResult:
    ceo_agent_run_id: UUID
    payload: dict[str, Any]


def _now(now: datetime | None) -> datetime:
    return now or datetime.now(timezone.utc)


def _open_ceo_run(tenant_id: UUID, requested_by: UUID, trigger: str, permission_check: str, now: datetime) -> UUID:
    return agent_run_repo.insert_run(
        tenant_id, agent_id="CEO", trigger_type="DIRECT", trigger_ref=f"ceo_hub.{trigger}", requested_by=requested_by,
        permission_check=permission_check, entitlement_check=NOT_EVALUATED, status="RUNNING", started_at=now,
    )


def _missing(role: str, permissions: Mapping[str, object], keys: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(k for k in keys if not has_permission(role=role, permissions=dict(permissions), key=k))


@settles_open_runs
def dispatch_cmo(
    tenant_id: UUID,
    *,
    requested_by: UUID,
    role: str,
    permissions: Mapping[str, object],
    action: str,
    body: Any,
    now: datetime | None = None,
) -> CeoHubCmoResult:
    """Dispatch ONE registered CMO action. `body` is the action's own validated request model (the same Pydantic model the direct
    path takes - declared fields only, so a tenant id, meter, cap or raw report cannot be smuggled in). Unknown actions are refused."""
    from backend.api.v1 import cmo as cmo_api  # late import: the HTTP module imports the services, never the reverse

    if action not in CMO_DISPATCH_ACTIONS:
        raise ValueError(f"{action!r} is not a registered CMO action")
    handler_name, extra = CMO_DISPATCH_ACTIONS[action]
    handler: Callable[..., dict[str, Any]] = getattr(cmo_api, handler_name)
    at = _now(now)
    missing = _missing(role, permissions, (AGENT_CEO, AGENT_CMO, *extra))
    if missing:  # enforced HERE, not by a classifier: a mis-routed turn is a denied turn
        run = _open_ceo_run(tenant_id, requested_by, action, "DENIED", at)
        agent_run_repo.finish_run(tenant_id, run, status="DENIED", error_reason=f"missing: {', '.join(missing)}", finished_at=at)
        raise CeoPermissionDenied(missing, run)

    run = _open_ceo_run(tenant_id, requested_by, action, "PASS", at)
    ctx = AuthContext(
        app_user_id=requested_by, clerk_user_id="ceo-hub", email_verified=True, tenant_id=tenant_id, membership_status="ACTIVE",
        role=role, permissions=dict(permissions), onboarding_state="COMPLETE",
    )
    token = cmo_actions.PARENT_RUN_ID.set(run)  # the action's own agent_run rows become this CEO turn's children
    try:
        payload = handler(body, ctx) if body is not None else handler(ctx)
    except HTTPException as exc:
        agent_run_repo.finish_run(tenant_id, run, status="FAILED", error_reason=f"{exc.status_code}", finished_at=_now(None))
        raise CeoDispatchError(exc.status_code, exc.detail, run) from None
    except Exception:
        agent_run_repo.finish_run(tenant_id, run, status="FAILED", error_reason="dispatch failed", finished_at=_now(None))
        raise
    finally:
        cmo_actions.PARENT_RUN_ID.reset(token)
    agent_run_repo.finish_run(tenant_id, run, status="COMPLETE", error_reason=None, finished_at=_now(None))
    return CeoHubCmoResult(run, payload)


@settles_open_runs
def dispatch_cmo_market_trends_preview(
    tenant_id: UUID, *, requested_by: UUID, role: str, permissions: Mapping[str, object], body: Any, now: datetime | None = None
) -> CeoHubCmoResult:
    """The step that precedes `cmo.market_trends`: the exact outbound queries and their digest (zero units, nothing sent). CEO shows
    these to the seller before the first send; the run itself then needs the digest back (409 PLAN_CHANGED otherwise)."""
    from backend.api.v1 import cmo as cmo_api

    at = _now(now)
    keys = (AGENT_CEO, AGENT_CMO, RESEARCH_MARKET_TRENDS)
    missing = _missing(role, permissions, keys)
    if missing:
        run = _open_ceo_run(tenant_id, requested_by, "cmo.market_trends.preview", "DENIED", at)
        agent_run_repo.finish_run(tenant_id, run, status="DENIED", error_reason=f"missing: {', '.join(missing)}", finished_at=at)
        raise CeoPermissionDenied(missing, run)
    run = _open_ceo_run(tenant_id, requested_by, "cmo.market_trends.preview", "PASS", at)
    ctx = AuthContext(requested_by, "ceo-hub", True, tenant_id, "ACTIVE", role, dict(permissions), "COMPLETE")
    try:
        payload = cmo_api.post_market_trends_preview(body, ctx)
    except HTTPException as exc:
        agent_run_repo.finish_run(tenant_id, run, status="FAILED", error_reason=f"{exc.status_code}", finished_at=_now(None))
        raise CeoDispatchError(exc.status_code, exc.detail, run) from None
    agent_run_repo.finish_run(tenant_id, run, status="COMPLETE", error_reason=None, finished_at=_now(None))
    return CeoHubCmoResult(run, payload)


# ------------------------------------------------------------------------------------------------------------- GST (C4/C11)
class GstBasis(str, Enum):
    SELLER_PROVIDED = "SELLER_PROVIDED"
    ESTIMATED = "ESTIMATED"
    UNVERIFIED_HINT = "UNVERIFIED_HINT"


class GstRoute(str, Enum):
    A_CFO = "A_CFO"
    B_SHARED = "B_SHARED"


@dataclass(frozen=True, slots=True)
class GstQuestion:
    """What CEO supplies to the lookup, each text with its basis (read from the stored CMO records by the caller - never from an
    LLM). An `UNVERIFIED_HINT` category (an image-derived attribute whose vision gate has not passed) is NEVER passed on (G6)."""

    product_title: str
    product_basis: GstBasis
    category: str | None = None
    category_basis: GstBasis | None = None
    sku: str | None = None
    hsn: str | None = None


class GstEntitlementDenied(Exception):
    def __init__(self, service: str, reason: str | None, ceo_agent_run_id: UUID) -> None:
        super().__init__(f"{service} entitlement denied: {reason}")
        self.service, self.reason, self.ceo_agent_run_id = service, reason, ceo_agent_run_id


class GstInputRefused(ValueError):
    """The question carries no usable product text (e.g. its only basis is an unverified image hint)."""


@dataclass(frozen=True, slots=True)
class CeoHubGstResult:
    route: GstRoute
    ceo_agent_run_id: UUID
    lookup_agent_run_id: UUID
    result: dict[str, Any] | None
    no_match: dict[str, Any] | None
    from_cache: bool
    uncertainty_notes: tuple[str, ...]


def select_gst_route(role: str, permissions: Mapping[str, object]) -> GstRoute | None:
    """By permissions only. None = the wall (no `service.gst_lookup`, or no `agent.ceo`)."""
    if _missing(role, permissions, (AGENT_CEO, SERVICE_GST_LOOKUP)):
        return None
    return GstRoute.A_CFO if has_permission(role=role, permissions=dict(permissions), key=AGENT_CFO) else GstRoute.B_SHARED


@settles_open_runs
def dispatch_gst_lookup(
    tenant_id: UUID,
    *,
    requested_by: UUID,
    role: str,
    permissions: Mapping[str, object],
    question: GstQuestion,
    now: datetime | None = None,
    lookup: Callable[..., Any] | None = None,
) -> CeoHubGstResult:
    """One GST turn. `lookup` is injectable for tests; production uses `run_gst_applicability_lookup` (cache, then cited fetch + model
    extraction, persisted `PROVISIONAL`). The rate in the result is copied from the stored `gst_lookup_result` - never generated."""
    from backend.api.v1.cfo import _gst_lookup_no_match_to_dict, _gst_lookup_result_to_dict
    from backend.services.cfo_actions import GstLookupRequest, run_gst_applicability_lookup

    at = _now(now)
    route = select_gst_route(role, permissions)
    if route is None:  # T19 / E17: the wall; no lookup, no model-knowledge answer
        missing = _missing(role, permissions, (AGENT_CEO, SERVICE_GST_LOOKUP))
        run = _open_ceo_run(tenant_id, requested_by, "gst_lookup", "DENIED", at)
        agent_run_repo.finish_run(tenant_id, run, status="DENIED", error_reason=f"missing: {', '.join(missing)}", finished_at=at)
        raise CeoPermissionDenied(missing, run)

    ceo_run = _open_ceo_run(tenant_id, requested_by, "gst_lookup", "PASS", at)

    def fail(status: str, reason: str) -> None:
        agent_run_repo.finish_run(tenant_id, ceo_run, status=status, error_reason=reason, finished_at=_now(None))

    # G6 - input integrity: basis labels decide what may be passed on
    notes: list[str] = []
    if question.product_basis is GstBasis.UNVERIFIED_HINT or not question.product_title.strip():
        fail("FAILED", "no usable product text")
        raise GstInputRefused("a product title with a SELLER_PROVIDED or ESTIMATED basis is required")
    category = question.category
    if category is not None and question.category_basis in (None, GstBasis.UNVERIFIED_HINT):
        category = None  # an unverified image hint (or a category with no stated basis) is never passed as a category
        notes.append("The category was not used: it is only an unverified image hint or has no stated basis.")
    elif category is not None and question.category_basis is GstBasis.ESTIMATED:
        notes.append("The category is an estimate, so the rate below may not apply to the exact product.")
    if question.product_basis is GstBasis.ESTIMATED:
        notes.append("The product description is an estimate.")

    # entitlement: Route A = CFO's cap AND the shared GST cap (two independent keys); Route B = the shared GST cap ONLY (G2:
    # no CFO or CMO unit is ever consumed on Route B).
    if route is GstRoute.A_CFO:
        cfo_ent = resolve_cfo_entitlement(tenant_id, direct_action_code="cfo.gst_lookup", occurred_at=at)
        if not cfo_ent.passed:
            fail("FAILED", cfo_ent.reason or "CFO entitlement denied")
            raise GstEntitlementDenied("cfo", cfo_ent.reason, ceo_run)
    gst_ent = resolve_gst_lookup_entitlement(tenant_id)
    if not gst_ent.passed:
        fail("FAILED", gst_ent.reason or "GST lookup entitlement denied")
        raise GstEntitlementDenied("gst_lookup", gst_ent.reason, ceo_run)

    # G7 - audit: the lookup is its own run, a CHILD of the CEO turn; its trigger names the shared service
    child_agent = "CFO" if route is GstRoute.A_CFO else "CEO"
    child_ref = "cfo.gst_lookup" if route is GstRoute.A_CFO else "service.gst_lookup"
    child = agent_run_repo.insert_run(
        tenant_id, agent_id=child_agent, trigger_type="DIRECT", trigger_ref=child_ref, requested_by=requested_by, permission_check="PASS",
        entitlement_check=cfo_entitlement_check_value(cfo_ent) if route is GstRoute.A_CFO else "PASS", status="RUNNING", started_at=at,
        parent_run_id=ceo_run,
    )
    try:
        request = GstLookupRequest(product_title=question.product_title, sku=question.sku, hsn=question.hsn, category=category, requested_by=requested_by)
        outcome = (lookup or run_gst_applicability_lookup)(tenant_id, request)
    except Exception:
        agent_run_repo.finish_run(tenant_id, child, status="FAILED", error_reason="lookup failed", finished_at=_now(None))
        fail("FAILED", "lookup failed")
        raise
    result = _gst_lookup_result_to_dict(outcome.result) if outcome.result is not None else None
    if result is not None and result["status"] == "SELLER_VERIFIED" and route is GstRoute.B_SHARED:
        agent_run_repo.finish_run(tenant_id, child, status="FAILED", error_reason="unexpected verified status", finished_at=_now(None))
        fail("FAILED", "unexpected verified status")
        raise RuntimeError("Route B can never present a verified result")  # defensive: G3 - a fresh shared lookup is PROVISIONAL
    agent_run_repo.finish_run(tenant_id, child, status="COMPLETE", error_reason=None, finished_at=_now(None))
    agent_run_repo.finish_run(tenant_id, ceo_run, status="COMPLETE", error_reason=None, finished_at=_now(None))
    return CeoHubGstResult(
        route=route, ceo_agent_run_id=ceo_run, lookup_agent_run_id=child, result=result,
        no_match=_gst_lookup_no_match_to_dict(outcome.no_match) if outcome.no_match is not None else None,
        from_cache=bool(outcome.from_cache), uncertainty_notes=tuple(notes),
    )
