"""The read-only tenant data inventory: runs as the owner under RLS on the scratch database, counts only the given tenant's rows, writes nothing, and leaves no table unclassified."""

from __future__ import annotations

import importlib.util
import os
from datetime import datetime, timezone

import pytest
from sqlalchemy import text

from backend.repositories import agent_run_repo

pytestmark = pytest.mark.usefixtures("two_tenants")
spec = importlib.util.spec_from_file_location("tenant_data_inventory", os.path.join(os.path.dirname(__file__), "..", "..", "scripts", "tenant_data_inventory.py"))
inventory = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inventory)  # type: ignore[union-attr]


def test_it_counts_only_this_tenants_rows_and_changes_nothing(two_tenants, app_user, capsys, migrate_engine):
    a, b = two_tenants
    now = datetime.now(timezone.utc)
    for tenant, n in ((a, 3), (b, 1)):
        for _ in range(n):
            run = agent_run_repo.insert_run(tenant, agent_id="CFO", trigger_type="DIRECT", trigger_ref="x", requested_by=app_user, permission_check="PASS",
                                            entitlement_check="PASS", status="RUNNING", started_at=now)
            agent_run_repo.finish_run(tenant, run, status="COMPLETE", error_reason=None, finished_at=now)
    with migrate_engine.connect() as conn:
        before = conn.execute(text("SELECT count(*) FROM pg_stat_user_tables WHERE n_tup_ins + n_tup_upd + n_tup_del > 0")).scalar_one()
    assert inventory.main(["inventory", str(a)]) == 0
    out = capsys.readouterr().out
    assert "port=5544" in out and "(read-only)" in out
    line = next(line for line in out.splitlines() if line.strip().startswith("agent_run "))
    assert int(line.split()[-1]) == 3  # tenant A's three runs; tenant B's one is not counted
    assert "UNCLASSIFIED" not in out, out  # every tenant table is in a retention category
    with migrate_engine.connect() as conn:
        after = conn.execute(text("SELECT count(*) FROM pg_stat_user_tables WHERE n_tup_ins + n_tup_upd + n_tup_del > 0")).scalar_one()
    assert after == before
