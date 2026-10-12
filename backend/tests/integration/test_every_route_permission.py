"""Every `/api/v1` route that needs a permission refuses a signed-in member who holds none: 403, decided before the body is read and before any data is touched.

The companion of `tests/unit/test_every_route_requires_auth.py` (401, no database). One parameterised test over the app's own OpenAPI document with a real membership
row on the scratch Postgres (only Clerk is faked), so a new route is covered the day it is added. A member with a role of PARTNER and an empty permission set is the
least-privileged real member the grid can produce."""

from __future__ import annotations

import os
import re
import uuid

import pytest

from backend.main import app
from tests.integration.test_ci_api import _register_deny_all_partner, client, fake_clerk  # noqa: F401  (fixtures and helpers)

pytestmark = [
    pytest.mark.usefixtures("two_tenants"),
    pytest.mark.skipif(not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL"), reason="needs a live Postgres"),
]

# Reachable without a session at all (see test_every_route_requires_auth.py), or by any signed-in user whatever their permissions, each with its reason.
NO_PERMISSION_NEEDED: dict[str, str] = {
    "GET /api/v1/ping": "liveness probe",
    # operator endpoints: gated by the X-Ops-Token shared secret, not by a member permission (off, 401, unless OPS_TOKEN is set); tested in test_ops_endpoints.py
    "GET /api/v1/ops/live": "operator probe behind OPS_TOKEN, not a member permission",
    "GET /api/v1/ops/ready": "operator probe behind OPS_TOKEN, not a member permission",
    "GET /api/v1/ops/runs": "operator diagnostics behind OPS_TOKEN, not a member permission",
    "GET /api/v1/ceo-hub/agents": "a fixed roster with no tenant data",
    "GET /api/v1/session": "a signed-in user reads their own session, including before they have a workspace",
    "POST /api/v1/onboarding/business": "the step that creates the workspace; needs a session, not a permission",
    # product-intelligence-agent.md section 6.1: niche briefs are a plain tenant write with no agent key (they are the seller's own notes, not an agent run)
    "GET /api/v1/pi/niche-briefs": "niche_brief CRUD is a plain tenant write, no agent key (PI spec 6.1)",
    "POST /api/v1/pi/niche-briefs": "niche_brief CRUD is a plain tenant write, no agent key (PI spec 6.1)",
    "GET /api/v1/pi/niche-briefs/{brief_id}": "niche_brief CRUD is a plain tenant write, no agent key (PI spec 6.1)",
    "PUT /api/v1/pi/niche-briefs/{brief_id}": "niche_brief CRUD is a plain tenant write, no agent key (PI spec 6.1)",
    "POST /api/v1/pi/niche-briefs/{brief_id}/archive": "niche_brief CRUD is a plain tenant write, no agent key (PI spec 6.1)",
    "POST /api/v1/pi/niche-briefs/{brief_id}/mark-draft": "niche_brief CRUD is a plain tenant write, no agent key (PI spec 6.1)",
    "POST /api/v1/pi/niche-briefs/{brief_id}/mark-ready": "niche_brief CRUD is a plain tenant write, no agent key (PI spec 6.1)",
}


def _routes() -> list[tuple[str, str]]:
    out = []
    for path, methods in sorted(app.openapi()["paths"].items()):
        if path.startswith("/api/v1"):
            out.extend((m.upper(), path) for m in sorted(methods) if m in {"get", "post", "put", "patch", "delete"})
    return out


def _fill(path: str) -> str:
    return re.sub(r"\{[^}]+\}", lambda _m: str(uuid.uuid4()), path)


def test_the_exemptions_name_only_routes_that_exist() -> None:
    served = {f"{m} {p}" for m, p in _routes()}
    assert set(NO_PERMISSION_NEEDED) <= served


@pytest.mark.parametrize("method,path", [r for r in _routes() if f"{r[0]} {r[1]}" not in NO_PERMISSION_NEEDED], ids=lambda v: str(v))
def test_a_member_with_no_permissions_is_refused(client, fake_clerk, two_tenants, method, path):
    tenant_a, _ = two_tenants
    headers = _register_deny_all_partner(fake_clerk, tenant_a)
    resp = client.request(method, _fill(path), headers=headers, json={} if method in {"POST", "PUT", "PATCH"} else None)
    assert resp.status_code == 403, f"{method} {path} answered {resp.status_code} to a member who holds no permission"
