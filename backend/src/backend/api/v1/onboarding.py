"""POST /api/v1/onboarding/business — the O1 blocking business-name step, §6.2.

Creates the Clerk Organization, then the Metrion `tenant`, then the `membership` row as
OWNER/ACTIVE, in that order — the atomic rollback-or-quarantine sequence from §6.2. Only
reachable from `PENDING_ONBOARDING` (no permission required, but `require_auth()` without a
`permission` still runs steps 1 and the email-verification gate — see `auth/context.py`).
"""

from __future__ import annotations

import logging

from clerk_backend_api.models import CreateOrganizationRequestBody
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.auth.clerk_client import get_clerk_client
from backend.auth.context import PENDING_ONBOARDING, AuthContext, require_auth
from backend.repositories import auth_audit_repo, membership_repo, tenant_repo

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1")


class BusinessOnboardingRequest(BaseModel):
    # O1: mandatory. O2: this field is never pre-filled from the Google display name —
    # that adoption would have to happen client-side, and the frontend never does it either.
    business_name: str = Field(min_length=1, max_length=200)


@router.post("/onboarding/business")
def complete_business_onboarding(
    body: BusinessOnboardingRequest,
    ctx: AuthContext = require_auth(),
) -> dict[str, str]:
    if ctx.onboarding_state != PENDING_ONBOARDING:
        # Already has an active org (or isn't verified yet) — this step doesn't apply.
        raise HTTPException(status_code=409, detail=f"Not eligible for onboarding: {ctx.onboarding_state}")

    cl = get_clerk_client()
    organization = cl.organizations.create(
        request=CreateOrganizationRequestBody(name=body.business_name, created_by=ctx.clerk_user_id)
    )
    clerk_org_id = organization.id

    # §6.2 atomic rollback: tenant AND membership both have to land, or neither does. The
    # frontend only learns the new org exists (and calls setActive() on it) once this
    # returns 200 — until then the caller's session still has no org_id, so a failed
    # request here is invisible to `resolve_auth_context` and a retry would silently
    # create a SECOND org+tenant on top of an orphaned first one, not just replay the
    # same request. Never leave a tenant with no membership, or a Clerk org with no
    # tenant, for a retry to pile onto (E5).
    tenant_id = None
    try:
        tenant_id = tenant_repo.create(clerk_org_id=clerk_org_id, business_name=body.business_name)
        membership_repo.create_owner(tenant_id, ctx.app_user_id)
    except Exception:
        if tenant_id is not None:
            try:
                tenant_repo.delete(tenant_id)
            except Exception:
                logger.exception("Failed to roll back orphaned tenant %s", tenant_id)
        try:
            cl.organizations.delete(organization_id=clerk_org_id)
        except Exception:
            logger.exception("Failed to roll back orphaned Clerk organization %s — quarantined", clerk_org_id)
        raise HTTPException(status_code=500, detail="Onboarding failed") from None

    try:
        auth_audit_repo.record(
            tenant_id,
            actor_user_id=ctx.app_user_id,
            event="TENANT_CREATED",
            subject=str(tenant_id),
            metadata={"business_name": body.business_name},
        )
    except Exception:
        # The audit trail is supplementary, not the source of truth (tenant + membership
        # already committed above) — losing this entry is a log-and-move-on situation,
        # never a reason to 500 a request whose real work already succeeded and would
        # otherwise get silently duplicated by the retry this failure would provoke.
        logger.exception("Failed to record TENANT_CREATED audit event for tenant %s", tenant_id)

    return {"tenantId": str(tenant_id), "clerkOrgId": clerk_org_id}
