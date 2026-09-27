"""Integration fixtures — require a real Postgres reachable at DATABASE_URL_APP /
DATABASE_URL with backend's migrations already applied (see migrations/README.md). Skipped
automatically when those env vars aren't set. Mirrors
`packages/calc-engine/tests/integration/conftest.py`.
"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import create_engine, text

from backend.tenant_context import tenant_scope

_APP_URL = os.environ.get("DATABASE_URL_APP")
_MIGRATE_URL = os.environ.get("DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not _APP_URL or not _MIGRATE_URL,
    reason="DATABASE_URL_APP/DATABASE_URL not set — integration tests need a live Postgres",
)


@pytest.fixture
def app_engine():
    engine = create_engine(_APP_URL)
    yield engine
    engine.dispose()


@pytest.fixture
def migrate_engine():
    engine = create_engine(_MIGRATE_URL)
    yield engine
    engine.dispose()


@pytest.fixture
def two_tenants(migrate_engine, _clean_backend_tables):
    """Two fake tenant rows, inserted as the table owner (metrion_migrate) so membership's
    FK to tenant(id) is satisfiable — the RLS tests below then connect as metrion_app to
    verify isolation against those two ids. No teardown here: `_clean_backend_tables`
    (declared as a dependency, in addition to its own autouse=True) deletes every backend
    table, including `tenant`, in FK-safe order after every test — doing it there rather
    than here avoids a "delete parent before child" ordering race between sibling fixtures'
    own teardowns."""
    tenant_a, tenant_b = uuid.uuid4(), uuid.uuid4()
    with migrate_engine.begin() as conn:
        for tid in (tenant_a, tenant_b):
            conn.execute(
                text(
                    "INSERT INTO tenant (id, clerk_org_id, business_name, status, created_at) "
                    "VALUES (:id, :clerk_org_id, 'Test Tenant', 'ACTIVE', now())"
                ),
                {"id": str(tid), "clerk_org_id": f"org_{tid}"},
            )
    yield tenant_a, tenant_b


@pytest.fixture
def app_user(migrate_engine, _clean_backend_tables):
    """A single app_user row, usable as membership.app_user_id / bound_by regardless of
    which tenant is under test. No teardown here — see `two_tenants`."""
    user_id = uuid.uuid4()
    with migrate_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO app_user (id, clerk_user_id, email, auth_provider, created_at) "
                "VALUES (:id, :clerk_user_id, :email, 'EMAIL_PASSWORD', now())"
            ),
            {"id": str(user_id), "clerk_user_id": f"user_{user_id}", "email": f"{user_id}@example.com"},
        )
    yield user_id


_CHILD_TABLES = (
    "auth_audit",
    "whatsapp_pending_action",
    "whatsapp_message",
    "whatsapp_alert_subscription",
    "investigation_message",
    # entitlement.md §5 tenant-owned tables — deleted before agent_run (metered_event's
    # nullable FK to agent_run(id)) and before tenant/app_user themselves.
    "member_entitlement_allocation",
    "metered_event",
    "tenant_cart_item",
    "tenant_plan",
    "agent_run",
    "investigation",
    "whatsapp_binding",
    "membership",
)

# entitlement.md §5/§7 platform-config tables (nullable tenant_id, no RLS-loop cleanup
# possible the way _CHILD_TABLES is — a NULL tenant_id row has no tenant to scope through).
# Deleted directly as the table owner (metrion_migrate), mirroring
# packages/calc-engine/tests/integration/conftest.py's own `_clean_engine_tables` pattern for
# reconciliation_tolerance_config/severity_config.
_PLATFORM_CONFIG_TABLES = (
    "entitlement_cap_config",
    "metered_event_meter_map",
    "capability_entitlement_rule",
    "plan",
)


def _clean(migrate_engine) -> None:
    """Deletes every backend table's rows, in FK-safe order. `FORCE ROW LEVEL SECURITY`
    (auth.md D3) applies even to `metrion_migrate` as table owner, so an unscoped
    `DELETE FROM <child_table>` run on the owner connection with no tenant context set would
    silently delete zero rows (the policy predicate is NULL for every row) — this is
    deliberately NOT how this cleanup works. Instead: read the tenant ids that exist (`tenant`
    itself carries no RLS policy, so this SELECT is unscoped-safe), then delete each child
    table's rows *through* `tenant_scope()` per tenant id, so the same RLS policy that
    protects real requests does the filtering here too. Only once every child row is gone are
    `tenant`/`app_user` deletable without a FK violation."""
    with migrate_engine.begin() as conn:
        tenant_ids = [row[0] for row in conn.execute(text("SELECT id FROM tenant")).fetchall()]

    for tenant_id in tenant_ids:
        with tenant_scope(tenant_id) as conn:
            for t in _CHILD_TABLES:
                conn.execute(text(f"DELETE FROM {t}"))

    with migrate_engine.begin() as conn:
        conn.execute(text("DELETE FROM tenant"))
        conn.execute(text("DELETE FROM app_user"))
        # Platform-config tables (nullable tenant_id) — an unscoped delete as table owner
        # only reaches tenant_id IS NULL rows (the RLS predicate's other branch needs
        # app.current_tenant_id set); that's exactly the row shape every test here seeds
        # (platform-default rows via migrate_engine, mirroring fee_reference's precedent),
        # so this is sufficient cleanup, not a gap.
        for t in _PLATFORM_CONFIG_TABLES:
            conn.execute(text(f"DELETE FROM {t}"))


@pytest.fixture(autouse=True)
def _clean_backend_tables(migrate_engine):
    """Each test starts and ends with empty backend tables — see `_clean()` above for why
    this can't be a plain unscoped DELETE."""
    _clean(migrate_engine)
    yield
    _clean(migrate_engine)
