"""GET /api/v1/session — resolves the caller's AuthContext (§5.3) without requiring a
specific permission, so the frontend can read `onboarding_state` and route accordingly
(sign-in -> onboarding -> dashboard). This is the one endpoint reachable from every
`PENDING_*` state (§6.1)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.auth.context import AuthContext, require_auth
from backend.services import business_profile

router = APIRouter(prefix="/api/v1")


@router.get("/session")
def get_session(ctx: AuthContext = require_auth()) -> dict[str, object]:
    # profileComplete: has the business-details step been finished (docs/specs/business-profile.md D4). Only meaningful for a member with a tenant.
    complete = business_profile.is_complete(ctx.tenant_id) if ctx.tenant_id and ctx.onboarding_state == "ACTIVE" else False
    return {
        "profileComplete": complete,
        "appUserId": str(ctx.app_user_id),
        "emailVerified": ctx.email_verified,
        "tenantId": str(ctx.tenant_id) if ctx.tenant_id else None,
        "membershipStatus": ctx.membership_status,
        "role": ctx.role,
        "onboardingState": ctx.onboarding_state,
    }
