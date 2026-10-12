"""Historical issue 1 ("imported CFO data is not visible"): the data was never lost. FORCE ROW LEVEL SECURITY applies even to the table owner, so any inspection that does not set
the tenant context (a psql session, a DB tool, an ad-hoc script) sees ZERO rows of a tenant table, as `metrion_migrate` (the owner) and as `metrion_app` alike. Only a session that sets
`app.current_tenant_id` sees the tenant's rows. This pins that behaviour so it is never weakened (a weaker setup would be a cross-tenant leak), and records the explanation."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import text

from backend.repositories import agent_run_repo

pytestmark = pytest.mark.usefixtures("two_tenants")


def test_without_tenant_context_even_the_owner_sees_no_rows_and_with_it_the_rows_are_there(two_tenants, app_user, migrate_engine, app_engine):
    a, b = two_tenants
    now = datetime.now(timezone.utc)
    for tenant in (a, b):
        run = agent_run_repo.insert_run(tenant, agent_id="CFO", trigger_type="DIRECT", trigger_ref="x", requested_by=app_user, permission_check="PASS",
                                        entitlement_check="PASS", status="RUNNING", started_at=now)
        agent_run_repo.finish_run(tenant, run, status="COMPLETE", error_reason=None, finished_at=now)
    for engine in (migrate_engine, app_engine):  # the owner role and the application role
        with engine.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM agent_run")).scalar_one() == 0
    with app_engine.begin() as conn:
        conn.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": str(a)})
        rows = conn.execute(text("SELECT DISTINCT tenant_id FROM agent_run")).scalars().all()
    assert [str(r) for r in rows] == [str(a)]  # with context: exactly this tenant's rows, never the other's
