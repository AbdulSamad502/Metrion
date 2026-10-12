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
from tests.integration.db_guard import refusal


@pytest.fixture(scope="session", autouse=True)
def _refuse_the_development_database():
    """Stop the whole session, before any test touches a row, when the configured database is the development one (port 5432). See `db_guard.py`."""
    message = refusal()
    if message:
        pytest.exit(message, returncode=2)


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
    (declared as a dependency, in addition to its own autouse=True) clears platform config;
    the inserted tenant rows themselves are removed, by id, by `_purge_tenants_created_by_test`."""
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


# entitlement.md §5/§7 platform-config tables (nullable tenant_id, no RLS-loop cleanup
# possible — a NULL tenant_id row has no tenant to scope through).
# Deleted directly as the table owner (metrion_migrate), mirroring
# packages/calc-engine/tests/integration/conftest.py's own `_clean_engine_tables` pattern for
# reconciliation_tolerance_config/severity_config.
_PLATFORM_CONFIG_TABLES = (
    "entitlement_cap_config",
    "metered_event_meter_map",
    "capability_entitlement_rule",
    "plan",
)


def _clean_platform_config(migrate_engine) -> None:
    """Clears the platform-default rows (NULL tenant_id) the tests seed into the entitlement
    config tables — the only rows an unscoped DELETE can reach under FORCE ROW LEVEL SECURITY,
    and exactly the row shape every test here seeds.

    This used to ALSO wipe every tenant's child rows and then run `DELETE FROM tenant` /
    `DELETE FROM app_user` unscoped, which deleted every real tenant and user in the shared dev
    database each time the suite ran. Tenant-owned data a test creates is now removed by
    `_purge_tenants_created_by_test` (below): it tracks the tenant/app_user ids the test
    actually used and deletes only those, through each tenant's own RLS context."""
    with migrate_engine.begin() as conn:
        for t in _PLATFORM_CONFIG_TABLES:
            conn.execute(text(f"DELETE FROM {t}"))


@pytest.fixture(autouse=True)
def _clean_backend_tables(migrate_engine):
    """Platform-config rows start and end empty; see `_clean_platform_config`. (Also a declared
    dependency of `two_tenants`/`app_user`, which insert tenant/user rows that the tenant-scoped
    purge below removes.)"""
    _clean_platform_config(migrate_engine)
    yield
    _clean_platform_config(migrate_engine)


# --- Tenant-scoped cleanup of everything a test created --------------------------------------
# The `DELETE FROM <table>` fixtures in this suite never removed tenant-owned rows: every such
# table is FORCE ROW LEVEL SECURITY, which applies to the table owner too, so a DELETE with no
# tenant context matches nothing and silently deletes zero rows. This fixture instead purges the
# tenants the code under test actually touched, through RLS, one tenant at a time — see
# tools/testkit/tenant_cleanup.py for the mechanism and why it cannot touch another tenant.
import pathlib  # noqa: E402
import sys  # noqa: E402

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "tools"))
from testkit.tenant_cleanup import TRACKER as _tenant_tracker  # noqa: E402

_tenant_tracker.install()


@pytest.fixture(autouse=True)
def _purge_tenants_created_by_test(migrate_engine):
    _tenant_tracker.reset()
    yield
    _tenant_tracker.purge(migrate_engine)


@pytest.fixture
def approval_gate_bypassed(monkeypatch):
    """TEST-ONLY and explicit (never autouse): switches off the orchestrator's D-8 refusal for ONE test that exercises the guided-input / execution flow of an
    approval-required chat action, the part a future stored-approval plan will reuse. In production chat these actions are refused until a stored approval plan exists
    (tests/integration/test_ceo_approval_blocked_chat.py proves that with the real guard). This patches an attribute of the module in the test process only: there is no
    setting, environment variable or request that can do the same. The `dispatch()` backstop is NOT bypassed here (these tests use effect-less stub specs, which it ignores)."""
    from backend.ceo import orchestrator

    monkeypatch.setattr(orchestrator, "plan_required", lambda keys: False)
