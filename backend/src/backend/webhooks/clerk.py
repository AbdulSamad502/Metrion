"""Clerk -> Metrion sync webhook — auth.md D6, §6.5, AC16.

Signature verified before any processing (Svix, Clerk's documented mechanism). Handlers are
idempotent upserts keyed on `clerk_user_id`/`clerk_org_id`, tolerant of out-of-order or
duplicate delivery (A3). This is one half of D6's two-path sync; the other half is the
login-time reconciliation in `auth/context.py` for anything a missed webhook left stale.

Deliberately out of scope here, per the spec's own open/provisional status: full E21
("Clerk user deleted upstream") and E22 ("sole OWNER deleted") handling — both are flagged
provisional/undefined in `auth.md` (Q3, E21) rather than fully specified, so this module
logs and no-ops on `user.deleted`/`organization.deleted` rather than guessing a behavior.
"""

from __future__ import annotations

import json
import logging
from typing import cast
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from svix.webhooks import Webhook, WebhookVerificationError

from backend.auth.permissions import OWNER_ROLE, PARTNER_ROLE
from backend.config import clerk_webhook_secret
from backend.repositories import app_user_repo, membership_repo, tenant_repo

logger = logging.getLogger(__name__)
router = APIRouter()

# Every handler below parses Clerk's webhook JSON, which arrives as untyped `object` at
# every nesting level — these two helpers are the only place raw dict/list casts happen,
# so a malformed payload fails loudly with a KeyError/TypeError inside a try'd handler
# dispatch rather than mypy silently treating `object` as "anything goes" throughout.
def _dict_field(data: dict[str, object], key: str) -> dict[str, object]:
    value = data.get(key)
    return cast(dict[str, object], value) if isinstance(value, dict) else {}


def _list_field(data: dict[str, object], key: str) -> list[dict[str, object]]:
    value = data.get(key)
    return cast(list[dict[str, object]], value) if isinstance(value, list) else []


def _primary_email(data: dict[str, object]) -> tuple[str, bool]:
    primary_id = data.get("primary_email_address_id")
    for addr in _list_field(data, "email_addresses"):
        if addr.get("id") == primary_id:
            verification = _dict_field(addr, "verification")
            return str(addr.get("email_address") or ""), verification.get("status") == "verified"
    return "", False


def _auth_provider(data: dict[str, object]) -> str:
    for acct in _list_field(data, "external_accounts"):
        if acct.get("provider") == "oauth_google":
            return "GOOGLE"
    return "EMAIL_PASSWORD"


def _handle_user_upsert(data: dict[str, object]) -> None:
    clerk_user_id = str(data["id"])
    email, email_verified = _primary_email(data)
    first_name = data.get("first_name")
    app_user_repo.upsert(
        clerk_user_id=clerk_user_id,
        email=email,
        email_verified=email_verified,
        auth_provider=_auth_provider(data),
        display_name=first_name if isinstance(first_name, str) else None,
    )


def _handle_organization_created(data: dict[str, object]) -> None:
    clerk_org_id = str(data["id"])
    if tenant_repo.get_by_clerk_org_id(clerk_org_id) is None:
        # Normal path: our own onboarding endpoint already inserted this row directly and
        # this event is a redundant confirmation. Only inserts when genuinely missing —
        # never overwrites `business_name`, which is user-authoritative (O1), not
        # webhook-authoritative.
        tenant_repo.create(clerk_org_id=clerk_org_id, business_name=str(data.get("name") or ""))


def _handle_membership_upsert(data: dict[str, object]) -> None:
    org = _dict_field(data, "organization")
    public_user_data = _dict_field(data, "public_user_data")
    clerk_org_id = org.get("id")
    clerk_user_id = public_user_data.get("user_id")
    if not clerk_org_id or not clerk_user_id:
        return
    tenant_row = tenant_repo.get_by_clerk_org_id(str(clerk_org_id))
    user_row = app_user_repo.get_by_clerk_user_id(str(clerk_user_id))
    if tenant_row is None or user_row is None:
        # Out-of-order delivery (A3) — the login-time reconciliation path in
        # `auth/context.py` will pick this up once both sides exist.
        return
    org_role = str(data.get("role") or "")
    role = OWNER_ROLE if org_role == "org:admin" else PARTNER_ROLE
    membership_repo.upsert_partner(UUID(str(tenant_row["id"])), UUID(str(user_row["id"])), role=role, status="ACTIVE")


def _handle_membership_deleted(data: dict[str, object]) -> None:
    org = _dict_field(data, "organization")
    public_user_data = _dict_field(data, "public_user_data")
    tenant_row = tenant_repo.get_by_clerk_org_id(str(org.get("id") or ""))
    user_row = app_user_repo.get_by_clerk_user_id(str(public_user_data.get("user_id") or ""))
    if tenant_row is None or user_row is None:
        return
    membership_repo.upsert_partner(
        UUID(str(tenant_row["id"])), UUID(str(user_row["id"])), role=PARTNER_ROLE, status="REMOVED"
    )


_HANDLERS = {
    "user.created": _handle_user_upsert,
    "user.updated": _handle_user_upsert,
    "organization.created": _handle_organization_created,
    "organizationMembership.created": _handle_membership_upsert,
    "organizationMembership.updated": _handle_membership_upsert,
    "organizationMembership.deleted": _handle_membership_deleted,
}


@router.post("/webhooks/clerk")
async def clerk_webhook(request: Request) -> dict[str, bool]:
    body = await request.body()
    try:
        Webhook(clerk_webhook_secret()).verify(body, dict(request.headers))
    except WebhookVerificationError:
        raise HTTPException(status_code=400, detail="Invalid webhook signature")

    event = json.loads(body)
    event_type = event.get("type")
    handler = _HANDLERS.get(event_type)
    if handler is not None:
        handler(event.get("data") or {})
    else:
        logger.info("Unhandled Clerk webhook event type: %s", event_type)
    return {"ok": True}
