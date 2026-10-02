"""AuthContext resolution and the six-step authorization chain — auth.md §5.3, §7.1.

Every protected route depends on `require_auth(...)`. It is the *only* place any of the
six checks happens; no endpoint re-implements a step or skips one (AC5, AC5b).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import cast
from uuid import UUID

from clerk_backend_api.security.types import AuthenticateRequestOptions
from fastapi import Depends, HTTPException, Request

from backend.auth.clerk_client import get_clerk_client
from backend.auth.clock_diagnostics import clock_hint, is_time_related
from backend.auth.key_diagnostics import key_hint
from backend.auth.permissions import OWNER_ROLE, PARTNER_ROLE, has_permission
from backend.config import clerk_clock_skew_ms, clerk_jwt_key, clerk_secret_key
from backend.repositories import app_user_repo, membership_repo, tenant_repo

logger = logging.getLogger(__name__)

# §6.1 onboarding_state values
PENDING_EMAIL_VERIFICATION = "PENDING_EMAIL_VERIFICATION"
PENDING_ONBOARDING = "PENDING_ONBOARDING"
ACTIVE = "ACTIVE"


@dataclass(frozen=True)
class AuthContext:
    app_user_id: UUID
    clerk_user_id: str
    email_verified: bool
    tenant_id: UUID | None
    membership_status: str | None
    role: str | None
    permissions: dict[str, object]
    onboarding_state: str


async def _reconcile_app_user_from_clerk(clerk_user_id: str) -> dict[str, object]:
    """D6/E14: a missed webhook is corrected here, on next login, rather than left stale.
    Defensive attribute access throughout — this SDK's generated models are a discriminated
    union we don't want a hard dependency on the exact shape of; the webhook path
    (`webhooks/clerk.py`) is the primary, well-defined sync mechanism and handles plain JSON.

    Raises `HTTPException(503)` if Clerk's API can't be reached or errors — fail closed,
    never fabricate a local identity from a request we couldn't actually confirm.

    Uses `users.get_async` (not the sync `users.get`) for the same reason `require_auth`
    uses `authenticate_request_async`: the sync SDK call hangs indefinitely when invoked
    from inside an async request-handling context — reproduced directly before this fix,
    on the very first request from a genuinely new Clerk user (the one path that reaches
    this function, since the webhook normally creates the row first).
    """
    try:
        remote = await get_clerk_client().users.get_async(user_id=clerk_user_id)
    except Exception:
        logger.exception("Failed to reconcile app_user %s from Clerk", clerk_user_id)
        raise HTTPException(status_code=503, detail="Identity provider unavailable") from None
    primary_email_id = getattr(remote, "primary_email_address_id", None)
    email = ""
    email_verified = False
    for addr in getattr(remote, "email_addresses", None) or []:
        if getattr(addr, "id", None) == primary_email_id:
            email = getattr(addr, "email_address", "") or ""
            verification = getattr(addr, "verification", None)
            email_verified = getattr(verification, "status", None) == "verified"
            break
    is_google = any(
        getattr(acct, "provider", "") == "oauth_google" for acct in (getattr(remote, "external_accounts", None) or [])
    )
    auth_provider = "GOOGLE" if is_google else "EMAIL_PASSWORD"
    app_user_repo.upsert(
        clerk_user_id=clerk_user_id,
        email=email,
        email_verified=email_verified,
        auth_provider=auth_provider,
        display_name=getattr(remote, "first_name", None),
    )
    reconciled = app_user_repo.get_by_clerk_user_id(clerk_user_id)
    assert reconciled is not None
    return reconciled


async def _reconcile_tenant_from_clerk(clerk_org_id: str) -> dict[str, object] | None:
    """D6/E14, tenant-side: the session's active-org claim can outlive our local `tenant`
    row (a missed `organization.created` webhook, or — in dev — a database reset that
    Clerk's own org store never saw). Without this, such a user hits a permanent 403 on
    every request ("Onboarding incomplete") with no way back in, even though Clerk still
    considers the org valid and onboarding already happened once.

    Returns `None` (never raises) when Clerk also has no record of the org — that's a
    genuinely stale/deleted reference, and the caller falls back to treating this as
    "needs onboarding" rather than a dead end."""
    try:
        organization = await get_clerk_client().organizations.get_async(organization_id=clerk_org_id)
    except Exception:
        logger.warning("Clerk org %s not found while reconciling tenant; treating as stale", clerk_org_id)
        return None
    tenant_repo.create(clerk_org_id=clerk_org_id, business_name=organization.name or "")
    return tenant_repo.get_by_clerk_org_id(clerk_org_id)


async def _reconcile_membership_from_clerk(
    tenant_id: UUID, app_user_id: UUID, clerk_org_id: str, clerk_user_id: str
) -> None:
    """D6/E14: same reconciliation, for the membership row, when the org-membership webhook
    hasn't landed yet but the user's session already carries an active org.

    Unlike `_reconcile_app_user_from_clerk`, a failure here degrades to "no membership
    found" (the caller's existing 403 path) rather than a hard error — the caller already
    has a fully resolved identity and tenant; a stale/unreachable membership lookup is a
    reason to deny this specific request, not to fail the whole chain. Uses the `_async`
    SDK method for the same reason as `_reconcile_app_user_from_clerk`."""
    try:
        cl = get_clerk_client()
        result = await cl.organization_memberships.list_async(organization_id=clerk_org_id, user_id=[clerk_user_id])
    except Exception:
        logger.exception("Failed to reconcile membership for tenant %s / user %s from Clerk", tenant_id, clerk_user_id)
        return
    memberships = getattr(result, "data", None) or []
    for m in memberships:
        org_role = getattr(m, "role", "") or ""
        role = OWNER_ROLE if org_role == "org:admin" else PARTNER_ROLE
        membership_repo.upsert_partner(tenant_id, app_user_id, role=role, status="ACTIVE")
        return


async def resolve_auth_context(
    *, clerk_user_id: str | None, clerk_org_id: str | None, permission: str | None
) -> AuthContext:
    """Steps 2-6 of §7.1, plus the app_user resolution step 1 hands off to. Split out from
    `require_auth()` so it's testable against a real Postgres without needing a live Clerk
    JWT for every test case — `clerk_user_id`/`clerk_org_id` are exactly the two claims step
    1 extracts from a verified token's payload (`sub`, `org_id`).

    Async only because of the two Clerk-API reconciliation calls it may make; the
    repository calls in between remain plain synchronous SQLAlchemy (fast local Postgres
    queries — not worth threading through `run_in_threadpool` for this scope)."""
    if not clerk_user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")

    user_row = app_user_repo.get_by_clerk_user_id(clerk_user_id)
    if user_row is None:
        user_row = await _reconcile_app_user_from_clerk(clerk_user_id)
    app_user_id = UUID(str(user_row["id"]))
    email_verified = bool(user_row["email_verified"])

    if not email_verified:
        # I5/E3: unverified email/password users get no access beyond onboarding-state
        # awareness. Google users are pre-verified (I6) so never land here.
        pending = AuthContext(
            app_user_id=app_user_id,
            clerk_user_id=clerk_user_id,
            email_verified=False,
            tenant_id=None,
            membership_status=None,
            role=None,
            permissions={},
            onboarding_state=PENDING_EMAIL_VERIFICATION,
        )
        if permission is not None:
            # §6.1/I7: every endpoint but session/verification/onboarding/sign-out
            # returns 403 carrying the state, never partial data.
            raise HTTPException(status_code=403, detail=PENDING_EMAIL_VERIFICATION)
        return pending

    if not clerk_org_id:
        # §6.1: authenticated, verified, but no active organization yet.
        pending = AuthContext(
            app_user_id=app_user_id,
            clerk_user_id=clerk_user_id,
            email_verified=True,
            tenant_id=None,
            membership_status=None,
            role=None,
            permissions={},
            onboarding_state=PENDING_ONBOARDING,
        )
        if permission is not None:
            raise HTTPException(status_code=403, detail=PENDING_ONBOARDING)
        return pending

    tenant_row = tenant_repo.get_by_clerk_org_id(clerk_org_id)
    if tenant_row is None:
        tenant_row = await _reconcile_tenant_from_clerk(clerk_org_id)
    if tenant_row is None:
        # Clerk itself has no record of this org either (deleted org, or — in dev — a
        # database reset Clerk never saw): a genuinely stale active-org claim. Treat as
        # "not yet onboarded" rather than a dead-end 403; resubmitting the business-name
        # form creates a fresh org and the frontend activates it, same as a first-time user.
        pending = AuthContext(
            app_user_id=app_user_id,
            clerk_user_id=clerk_user_id,
            email_verified=True,
            tenant_id=None,
            membership_status=None,
            role=None,
            permissions={},
            onboarding_state=PENDING_ONBOARDING,
        )
        if permission is not None:
            raise HTTPException(status_code=403, detail=PENDING_ONBOARDING)
        return pending
    tenant_id = UUID(str(tenant_row["id"]))

    # Step 2 — organization membership must exist.
    membership_row = membership_repo.get_by_tenant_and_user(tenant_id, app_user_id)
    if membership_row is None:
        await _reconcile_membership_from_clerk(tenant_id, app_user_id, clerk_org_id, clerk_user_id)
        membership_row = membership_repo.get_by_tenant_and_user(tenant_id, app_user_id)
    if membership_row is None:
        raise HTTPException(status_code=403, detail="No membership for this organization")

    # Step 3 — active membership status.
    status = str(membership_row["status"])
    if status != "ACTIVE":
        raise HTTPException(status_code=403, detail="Membership not active")

    # Step 4 — Metrion role resolved.
    role = str(membership_row["role"])
    if role not in (OWNER_ROLE, PARTNER_ROLE):
        raise HTTPException(status_code=403, detail="No role resolved")

    permissions = cast(dict[str, object], membership_row["permissions"] or {})

    # Step 5 — required permission present in the grid (OWNER bypasses per §5.2).
    if permission is not None and not has_permission(role=role, permissions=permissions, key=permission):
        raise HTTPException(status_code=403, detail=f"Missing permission: {permission}")

    # Step 6 — tenant ownership of the resource is enforced by each endpoint's own
    # tenant-scoped lookup (every query goes through `tenant_scope(ctx.tenant_id)`);
    # there is no separate generic check to perform here.

    return AuthContext(
        app_user_id=app_user_id,
        clerk_user_id=clerk_user_id,
        email_verified=True,
        tenant_id=tenant_id,
        membership_status=status,
        role=role,
        permissions=permissions,
        onboarding_state=ACTIVE,
    )


def require_auth(*, permission: str | None = None) -> AuthContext:
    """Returns a FastAPI dependency implementing all six §7.1 steps in order. `permission`
    is the required `agent.*`/other grid key for step 5; omit it for routes with no
    permission requirement beyond being an active member (e.g. the session endpoint).

    The declared `-> AuthContext` return type describes what every call site actually
    receives once FastAPI resolves the dependency (`ctx: AuthContext = require_auth()`),
    not this function's own literal return value (`Depends(_dependency)`) — the standard,
    documented mismatch for typing FastAPI dependency-provider functions."""

    async def _dependency(request: Request) -> AuthContext:
        # Step 1 — Clerk authentication. jwt_key makes this networkless (verifies the RS256
        # signature locally against the instance's public key) — without it, the SDK
        # performs a live JWKS fetch per call with no bounded timeout.
        #
        # Uses the _async variant specifically: the sync `authenticate_request()` hangs
        # indefinitely when called from a FastAPI sync dependency (Starlette runs those in
        # a plain worker thread via anyio's threadpool, with no event loop of its own —
        # something inside the SDK's request handling depends on one and deadlocks without
        # it). Calling from a genuinely sync context (a plain script) is instant; only the
        # threadpool case hangs. Confirmed by direct reproduction before this fix.
        state = await get_clerk_client().authenticate_request_async(
            request,
            AuthenticateRequestOptions(
                secret_key=clerk_secret_key(), jwt_key=clerk_jwt_key(), clock_skew_in_ms=clerk_clock_skew_ms()
            ),
        )
        if not state.is_signed_in or state.payload is None:
            # Server-side only — the client still gets the generic 401 below. Clerk's
            # `reason` names why (token expired, signature/jwt_key mismatch, pending session…).
            logger.warning(
                "Clerk rejected request: status=%s reason=%s message=%s",
                getattr(state, "status", None),
                getattr(state, "reason", None),
                getattr(state, "message", None),
            )
            reason = getattr(state, "reason", None)
            problem = key_hint(reason)
            if problem:
                logger.error("Clerk token verification cannot succeed: %s", problem)
            if is_time_related(reason):
                # A valid token rejected on timing alone is almost always a skewed system clock —
                # say so (timing claims only; the token itself is never logged).
                hint = clock_hint(request.headers.get("Authorization"), leeway_ms=clerk_clock_skew_ms())
                if hint:
                    logger.warning("Clerk token timing rejected: %s", hint)
            raise HTTPException(status_code=401, detail="Not authenticated")
        return await resolve_auth_context(
            clerk_user_id=state.payload.get("sub"),
            clerk_org_id=state.payload.get("org_id"),
            permission=permission,
        )

    return Depends(_dependency)  # type: ignore[no-any-return]  # see docstring above
