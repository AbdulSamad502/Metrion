"""GET /api/v1/ping — the Step 3 exit-check endpoint. Requires `dashboard.view` purely to
prove the full six-step chain (§7.1) works end-to-end against a real permission key; it is
not a real feature and carries no business logic of its own."""

from __future__ import annotations

from fastapi import APIRouter

from backend.auth.context import AuthContext, require_auth
from backend.auth.permissions import DASHBOARD_VIEW

router = APIRouter(prefix="/api/v1")


@router.get("/ping")
def ping(ctx: AuthContext = require_auth(permission=DASHBOARD_VIEW)) -> dict[str, str]:
    return {"tenantId": str(ctx.tenant_id), "role": ctx.role or ""}
