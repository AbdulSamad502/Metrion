"""Regression tests for tools/testkit/tenant_cleanup.py — the tenant-scoped test cleanup.

The bug: tenant-owned tables are FORCE ROW LEVEL SECURITY, which applies to the table owner, so
the old `DELETE FROM <table>` fixtures (run as `metrion_migrate` with no tenant context) matched
nothing and silently deleted ZERO rows — test data accumulated in the shared dev database. These
tests pin: (1) that behaviour is real, (2) the scoped purge actually removes a tenant's rows,
(3) it cannot touch another tenant, (4) the autouse fixture really cleans up after each test.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import text

from data_foundation.repositories import ingestion_run_repo, report_file_repo, sales_line_repo
from testkit.tenant_cleanup import TenantTracker, count_rows_for_tenants, purge_tenants

# A FIXED tenant id: lets test #N+1 verify that test #N's data really was removed by the
# autouse cleanup fixture (random uuids could never be checked from a later test).
_FIXED_TENANT = uuid.UUID("cccccccc-0000-4000-8000-00000000c1ea")

_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _seed(tenant: uuid.UUID, lines: int = 3) -> None:
    file_id = report_file_repo.insert_report_file(
        tenant, marketplace="MEESHO", report_category="TAX", content_sha256=uuid.uuid4().hex * 2,
        original_filename="f.csv", byte_size=1, storage_uri="file://x", uploaded_by=uuid.uuid4(), uploaded_at=_NOW,
    )
    run_id = ingestion_run_repo.insert_ingestion_run(
        tenant, report_file_id=file_id, adapter_id="t", adapter_version="v1", started_at=_NOW
    )
    for i in range(lines):
        sales_line_repo.insert_sales_line(
            tenant, ingestion_run_id=run_id, marketplace="MEESHO", canonical_fields={"order_ref": f"O{i}"},
            source_row_number=i, source_row_json={}, confidence="VERIFIED",
        )


def test_unscoped_delete_as_table_owner_removes_nothing_under_force_rls(migrate_engine) -> None:
    tenant = uuid.uuid4()
    _seed(tenant)
    with migrate_engine.begin() as conn:
        deleted = [conn.execute(text(f"DELETE FROM {t}")).rowcount for t in ("sales_line", "ingestion_run", "report_file")]
    assert deleted == [0, 0, 0]  # the old cleanup pattern: silent no-op
    assert count_rows_for_tenants(migrate_engine, [tenant])["sales_line"] == 3  # data still there


def test_scoped_purge_removes_the_tenants_rows_children_before_parents(migrate_engine) -> None:
    tenant = uuid.uuid4()
    _seed(tenant)
    assert count_rows_for_tenants(migrate_engine, [tenant])  # seeded

    deleted = purge_tenants(migrate_engine, [tenant])

    assert deleted["sales_line"] == 3 and deleted["ingestion_run"] == 1 and deleted["report_file"] == 1
    assert count_rows_for_tenants(migrate_engine, [tenant]) == {}  # nothing left, no FK violation


def test_purging_one_tenant_never_touches_another_tenants_rows(migrate_engine) -> None:
    mine, someone_elses = uuid.uuid4(), uuid.uuid4()
    _seed(mine, lines=2)
    _seed(someone_elses, lines=5)

    purge_tenants(migrate_engine, [mine])

    assert count_rows_for_tenants(migrate_engine, [mine]) == {}
    assert count_rows_for_tenants(migrate_engine, [someone_elses])["sales_line"] == 5  # untouched
    # (the autouse fixture purges `someone_elses` too, since the code under test touched it)


def test_tracker_records_exactly_the_tenants_touched_through_tenant_scope(migrate_engine) -> None:
    tracker = TenantTracker()
    tracker.install()
    try:
        a, b, never_touched = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        _seed(a, lines=1)
        _seed(b, lines=1)
        assert {a, b} <= tracker.tenants
        assert never_touched not in tracker.tenants  # an untouched tenant can never be purged
    finally:
        tracker.uninstall()


def test_aa_seed_a_fixed_tenant_so_the_next_test_can_prove_it_was_cleaned_up(migrate_engine) -> None:
    _seed(_FIXED_TENANT, lines=4)
    assert count_rows_for_tenants(migrate_engine, [_FIXED_TENANT])["sales_line"] == 4


def test_zz_the_previous_tests_data_was_actually_removed_by_the_autouse_cleanup(migrate_engine) -> None:
    # test_aa_* left 4 sales_lines + a run + a file under _FIXED_TENANT; the autouse fixture's
    # teardown must have removed them. Before this change they would still be here.
    assert count_rows_for_tenants(migrate_engine, [_FIXED_TENANT]) == {}


def test_purge_with_no_tenants_is_a_noop(migrate_engine) -> None:
    assert purge_tenants(migrate_engine, []) == {}
