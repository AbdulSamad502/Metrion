"""The §7.1 six-step authorization chain, exercised via
`auth.context.resolve_auth_context()` — the part of `require_auth()` that doesn't need a
live Clerk JWT (step 1's token verification is Clerk's own concern; this tests everything
`require_auth()` does with the two claims step 1 hands it). Maps to `auth.md` §11's test
scenarios T3, T7, T8, T8c, T8d, T15, T16 and the onboarding-state rules in §6.1.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from backend.auth.context import ACTIVE, PENDING_EMAIL_VERIFICATION, PENDING_ONBOARDING, resolve_auth_context
from backend.auth.permissions import DASHBOARD_VIEW, FINANCIALS_ADJUST
from backend.repositories import app_user_repo, membership_repo, tenant_repo


def _verified_google_user() -> str:
    clerk_user_id = f"user_{uuid.uuid4()}"
    app_user_repo.upsert(
        clerk_user_id=clerk_user_id,
        email=f"{clerk_user_id}@example.com",
        email_verified=True,
        auth_provider="GOOGLE",
        display_name="Test User",
    )
    return clerk_user_id


async def test_no_clerk_user_id_is_401():
    with pytest.raises(HTTPException) as exc:
        await resolve_auth_context(clerk_user_id=None, clerk_org_id=None, permission=None)
    assert exc.value.status_code == 401


async def test_unverified_email_password_user_blocked_from_protected_route(two_tenants):
    """T3: unverified users are denied everything beyond onboarding-state awareness."""
    clerk_user_id = f"user_{uuid.uuid4()}"
    app_user_repo.upsert(
        clerk_user_id=clerk_user_id,
        email=f"{clerk_user_id}@example.com",
        email_verified=False,
        auth_provider="EMAIL_PASSWORD",
        display_name=None,
    )
    with pytest.raises(HTTPException) as exc:
        await resolve_auth_context(clerk_user_id=clerk_user_id, clerk_org_id=None, permission=DASHBOARD_VIEW)
    assert exc.value.status_code == 403
    assert exc.value.detail == PENDING_EMAIL_VERIFICATION

    # The session-style call (no permission) still succeeds and reports the state.
    ctx = await resolve_auth_context(clerk_user_id=clerk_user_id, clerk_org_id=None, permission=None)
    assert ctx.onboarding_state == PENDING_EMAIL_VERIFICATION
    assert ctx.tenant_id is None


async def test_verified_user_with_no_org_is_pending_onboarding():
    clerk_user_id = _verified_google_user()
    with pytest.raises(HTTPException) as exc:
        await resolve_auth_context(clerk_user_id=clerk_user_id, clerk_org_id=None, permission=DASHBOARD_VIEW)
    assert exc.value.status_code == 403
    assert exc.value.detail == PENDING_ONBOARDING

    ctx = await resolve_auth_context(clerk_user_id=clerk_user_id, clerk_org_id=None, permission=None)
    assert ctx.onboarding_state == PENDING_ONBOARDING


async def test_org_with_no_membership_row_is_denied(two_tenants):
    """Step 2: an org exists (tenant resolvable) but this user has no membership in it."""
    tenant_a, _ = two_tenants
    clerk_user_id = _verified_google_user()
    tenant_row = tenant_repo.get_by_clerk_org_id(f"org_{tenant_a}")
    assert tenant_row is not None

    with pytest.raises(HTTPException) as exc:
        await resolve_auth_context(clerk_user_id=clerk_user_id, clerk_org_id=f"org_{tenant_a}", permission=None)
    assert exc.value.status_code == 403


async def test_owner_passes_any_permission_without_explicit_grant(two_tenants):
    """§5.2: OWNER holds every permission implicitly — deny-all grid, still passes."""
    tenant_a, _ = two_tenants
    clerk_user_id = _verified_google_user()
    user_row = app_user_repo.get_by_clerk_user_id(clerk_user_id)
    membership_repo.create_owner(tenant_a, user_row["id"])

    ctx = await resolve_auth_context(clerk_user_id=clerk_user_id, clerk_org_id=f"org_{tenant_a}", permission=FINANCIALS_ADJUST)
    assert ctx.role == "OWNER"
    assert ctx.onboarding_state == ACTIVE
    assert ctx.tenant_id == tenant_a


async def test_partner_deny_all_is_403_on_protected_route(two_tenants):
    """T7: a partner with deny-all permissions is refused at step 5."""
    tenant_a, _ = two_tenants
    clerk_user_id = _verified_google_user()
    user_row = app_user_repo.get_by_clerk_user_id(clerk_user_id)
    membership_repo.upsert_partner(tenant_a, user_row["id"], role="PARTNER", status="ACTIVE")

    with pytest.raises(HTTPException) as exc:
        await resolve_auth_context(clerk_user_id=clerk_user_id, clerk_org_id=f"org_{tenant_a}", permission=DASHBOARD_VIEW)
    assert exc.value.status_code == 403


async def test_partner_granted_permission_passes_that_check_only(two_tenants):
    """T8/T8d: granting one key opens exactly that key, nothing else."""
    tenant_a, _ = two_tenants
    clerk_user_id = _verified_google_user()
    user_row = app_user_repo.get_by_clerk_user_id(clerk_user_id)
    membership_repo.upsert_partner(tenant_a, user_row["id"], role="PARTNER", status="ACTIVE")
    membership_repo.set_permissions(tenant_a, user_row["id"], {DASHBOARD_VIEW: True})

    ctx = await resolve_auth_context(clerk_user_id=clerk_user_id, clerk_org_id=f"org_{tenant_a}", permission=DASHBOARD_VIEW)
    assert ctx.role == "PARTNER"

    with pytest.raises(HTTPException) as exc:
        await resolve_auth_context(clerk_user_id=clerk_user_id, clerk_org_id=f"org_{tenant_a}", permission=FINANCIALS_ADJUST)
    assert exc.value.status_code == 403


async def test_removed_membership_is_denied_at_status_check(two_tenants):
    """T15: a removed member's token is still cryptographically valid, but membership
    status fails step 3."""
    tenant_a, _ = two_tenants
    clerk_user_id = _verified_google_user()
    user_row = app_user_repo.get_by_clerk_user_id(clerk_user_id)
    membership_repo.upsert_partner(tenant_a, user_row["id"], role="PARTNER", status="REMOVED")

    with pytest.raises(HTTPException) as exc:
        await resolve_auth_context(clerk_user_id=clerk_user_id, clerk_org_id=f"org_{tenant_a}", permission=None)
    assert exc.value.status_code == 403


async def test_permission_revoked_takes_effect_immediately(two_tenants):
    """T16/AC6: permissions are read per request, never cached — revoking mid-session
    denies the very next call with no token change."""
    tenant_a, _ = two_tenants
    clerk_user_id = _verified_google_user()
    user_row = app_user_repo.get_by_clerk_user_id(clerk_user_id)
    membership_repo.upsert_partner(tenant_a, user_row["id"], role="PARTNER", status="ACTIVE")
    membership_repo.set_permissions(tenant_a, user_row["id"], {DASHBOARD_VIEW: True})

    await resolve_auth_context(clerk_user_id=clerk_user_id, clerk_org_id=f"org_{tenant_a}", permission=DASHBOARD_VIEW)

    membership_repo.set_permissions(tenant_a, user_row["id"], {})
    with pytest.raises(HTTPException) as exc:
        await resolve_auth_context(clerk_user_id=clerk_user_id, clerk_org_id=f"org_{tenant_a}", permission=DASHBOARD_VIEW)
    assert exc.value.status_code == 403


async def test_cross_tenant_membership_does_not_leak(two_tenants):
    """A user who is OWNER of tenant A has no membership in tenant B."""
    tenant_a, tenant_b = two_tenants
    clerk_user_id = _verified_google_user()
    user_row = app_user_repo.get_by_clerk_user_id(clerk_user_id)
    membership_repo.create_owner(tenant_a, user_row["id"])

    with pytest.raises(HTTPException) as exc:
        await resolve_auth_context(clerk_user_id=clerk_user_id, clerk_org_id=f"org_{tenant_b}", permission=None)
    assert exc.value.status_code == 403
