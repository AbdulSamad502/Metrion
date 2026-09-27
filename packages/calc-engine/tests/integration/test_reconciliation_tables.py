"""reconciliation_run / reconciliation_match / reconciliation_exception (calc-engine-owned,
data-foundation.md §5.7/§5.9) against a real Postgres — migration application, RLS isolation,
the CHECK constraint, FK enforcement, and one realistic row per `exception_type`, mirroring
`test_rls_isolation.py`/`test_settlement_repo.py`'s seed-via-real-SQL patterns.

Task 1a's schema documentation (migration docstring) is what this test proves the schema
actually accommodates — no `reconcile()` logic is exercised here, only DDL/constraints.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from calc_engine.repositories.tenant_context import tenant_scope

_TABLES = ("reconciliation_run", "reconciliation_match", "reconciliation_exception")

pytestmark = [pytest.mark.usefixtures("_clean_reconciliation_tables")]


@pytest.fixture(autouse=True)
def _clean_reconciliation_tables(migrate_engine):
    with migrate_engine.begin() as conn:
        for t in ("reconciliation_exception", "reconciliation_match", "reconciliation_run"):
            conn.execute(text(f"DELETE FROM {t}"))
    yield
    with migrate_engine.begin() as conn:
        for t in ("reconciliation_exception", "reconciliation_match", "reconciliation_run"):
            conn.execute(text(f"DELETE FROM {t}"))


def _insert_run(tenant_id) -> uuid.UUID:
    run_id = uuid.uuid4()
    with tenant_scope(tenant_id) as conn:
        conn.execute(
            text(
                """
                INSERT INTO reconciliation_run
                    (id, tenant_id, marketplace, period_start, period_end, as_of_date,
                     tolerance_config_version, formula_version, status, join_key_validated,
                     started_at)
                VALUES
                    (:id, :tenant_id, 'MEESHO', '2026-09-01', '2026-09-30', '2026-10-05',
                     1, 'reconcile.v1', 'COMPLETE', true, :started_at)
                """
            ),
            {"id": str(run_id), "tenant_id": str(tenant_id), "started_at": datetime.now(timezone.utc)},
        )
    return run_id


def test_migration_applied_tables_and_rls_policies_exist(migrate_engine):
    inspector = inspect(migrate_engine)
    table_names = set(inspector.get_table_names())
    assert set(_TABLES) <= table_names

    with migrate_engine.connect() as conn:
        forced = conn.execute(
            text(
                "SELECT relname FROM pg_class WHERE relforcerowsecurity = true AND relname = ANY(:names)"
            ).bindparams(names=list(_TABLES))
        ).fetchall()
    assert {r[0] for r in forced} == set(_TABLES)

    with migrate_engine.connect() as conn:
        policies = conn.execute(
            text(
                "SELECT tablename FROM pg_policies WHERE policyname = 'tenant_isolation' AND tablename = ANY(:names)"
            ).bindparams(names=list(_TABLES))
        ).fetchall()
    assert {r[0] for r in policies} == set(_TABLES)


def test_rls_isolation_run_row_invisible_to_other_tenant(two_tenants):
    tenant_a, tenant_b = two_tenants
    _insert_run(tenant_a)

    with tenant_scope(tenant_a) as conn:
        rows = conn.execute(text("SELECT id FROM reconciliation_run")).fetchall()
    assert len(rows) == 1

    with tenant_scope(tenant_b) as conn:
        rows = conn.execute(text("SELECT id FROM reconciliation_run")).fetchall()
    assert rows == []


def test_exception_check_constraint_rejects_both_null(two_tenants):
    tenant_a, _ = two_tenants
    run_id = _insert_run(tenant_a)

    with pytest.raises((IntegrityError, DBAPIError)):
        with tenant_scope(tenant_a) as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO reconciliation_exception
                        (id, tenant_id, reconciliation_run_id, exception_type, marketplace,
                         amount_paise, confidence, formula_version, computed_at)
                    VALUES
                        (:id, :tenant_id, :run_id, 'ORPHAN_SETTLEMENT', 'MEESHO',
                         100, 'VERIFIED', 'reconcile.v1', :computed_at)
                    """
                ),
                {
                    "id": str(uuid.uuid4()),
                    "tenant_id": str(tenant_a),
                    "run_id": str(run_id),
                    "computed_at": datetime.now(timezone.utc),
                },
            )


def test_reconciliation_match_fk_to_run_enforced(two_tenants):
    tenant_a, _ = two_tenants
    bogus_run_id = uuid.uuid4()

    with pytest.raises((IntegrityError, DBAPIError)):
        with tenant_scope(tenant_a) as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO reconciliation_match
                        (id, tenant_id, reconciliation_run_id, sales_line_id, settlement_line_id,
                         outcome, variance_paise, confidence, formula_version, computed_at)
                    VALUES
                        (:id, :tenant_id, :run_id, :sales_line_id, :settlement_line_id,
                         'MATCHED_EXACT', 0, 'VERIFIED', 'reconcile.v1', :computed_at)
                    """
                ),
                {
                    "id": str(uuid.uuid4()),
                    "tenant_id": str(tenant_a),
                    "run_id": str(bogus_run_id),
                    "sales_line_id": str(uuid.uuid4()),
                    "settlement_line_id": str(uuid.uuid4()),
                    "computed_at": datetime.now(timezone.utc),
                },
            )


def test_reconciliation_exception_fk_to_run_and_match_enforced(two_tenants):
    tenant_a, _ = two_tenants
    bogus_run_id = uuid.uuid4()

    with pytest.raises((IntegrityError, DBAPIError)):
        with tenant_scope(tenant_a) as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO reconciliation_exception
                        (id, tenant_id, reconciliation_run_id, exception_type,
                         settlement_line_id, marketplace, amount_paise, confidence,
                         formula_version, computed_at)
                    VALUES
                        (:id, :tenant_id, :run_id, 'ORPHAN_SETTLEMENT',
                         :settlement_line_id, 'MEESHO', 100, 'VERIFIED', 'reconcile.v1', :computed_at)
                    """
                ),
                {
                    "id": str(uuid.uuid4()),
                    "tenant_id": str(tenant_a),
                    "run_id": str(bogus_run_id),
                    "settlement_line_id": str(uuid.uuid4()),
                    "computed_at": datetime.now(timezone.utc),
                },
            )

    # valid run, but bogus reconciliation_match_id
    run_id = _insert_run(tenant_a)
    bogus_match_id = uuid.uuid4()
    with pytest.raises((IntegrityError, DBAPIError)):
        with tenant_scope(tenant_a) as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO reconciliation_exception
                        (id, tenant_id, reconciliation_run_id, reconciliation_match_id,
                         exception_type, sales_line_id, settlement_line_id, marketplace,
                         component_code, amount_paise, confidence, formula_version, computed_at)
                    VALUES
                        (:id, :tenant_id, :run_id, :match_id,
                         'VARIANCE_EXCEEDS_TOLERANCE', :sales_line_id, :settlement_line_id, 'MEESHO',
                         'COMMISSION', 500, 'VERIFIED', 'reconcile.v1', :computed_at)
                    """
                ),
                {
                    "id": str(uuid.uuid4()),
                    "tenant_id": str(tenant_a),
                    "run_id": str(run_id),
                    "match_id": str(bogus_match_id),
                    "sales_line_id": str(uuid.uuid4()),
                    "settlement_line_id": str(uuid.uuid4()),
                    "computed_at": datetime.now(timezone.utc),
                },
            )


def test_one_realistic_row_per_exception_type(two_tenants):
    """Task 1a's five exception_type field combinations, each inserted for real."""
    tenant_a, _ = two_tenants
    run_id = _insert_run(tenant_a)
    now = datetime.now(timezone.utc)

    sales_line_id = uuid.uuid4()
    settlement_line_id = uuid.uuid4()
    other_settlement_line_id = uuid.uuid4()
    ambiguous_settlement_line_id = uuid.uuid4()
    unsettled_sales_line_id = uuid.uuid4()
    duplicate_settlement_line_id = uuid.uuid4()
    candidate_ids = [str(uuid.uuid4()), str(uuid.uuid4())]

    with tenant_scope(tenant_a) as conn:
        # VARIANCE_EXCEEDS_TOLERANCE — has a paired reconciliation_match row.
        match_id = uuid.uuid4()
        conn.execute(
            text(
                """
                INSERT INTO reconciliation_match
                    (id, tenant_id, reconciliation_run_id, sales_line_id, settlement_line_id,
                     component_code, outcome, variance_paise, confidence, formula_version, computed_at)
                VALUES
                    (:id, :tenant_id, :run_id, :sales_line_id, :settlement_line_id,
                     'COMMISSION', 'VARIANCE_EXCEEDS_TOLERANCE', 500, 'VERIFIED', 'reconcile.v1', :computed_at)
                """
            ),
            {
                "id": str(match_id),
                "tenant_id": str(tenant_a),
                "run_id": str(run_id),
                "sales_line_id": str(sales_line_id),
                "settlement_line_id": str(settlement_line_id),
                "computed_at": now,
            },
        )
        conn.execute(
            text(
                """
                INSERT INTO reconciliation_exception
                    (id, tenant_id, reconciliation_run_id, reconciliation_match_id, exception_type,
                     sales_line_id, settlement_line_id, marketplace, component_code, amount_paise,
                     confidence, formula_version, computed_at)
                VALUES
                    (:id, :tenant_id, :run_id, :match_id, 'VARIANCE_EXCEEDS_TOLERANCE',
                     :sales_line_id, :settlement_line_id, 'MEESHO', 'COMMISSION', 500,
                     'VERIFIED', 'reconcile.v1', :computed_at)
                """
            ),
            {
                "id": str(uuid.uuid4()),
                "tenant_id": str(tenant_a),
                "run_id": str(run_id),
                "match_id": str(match_id),
                "sales_line_id": str(sales_line_id),
                "settlement_line_id": str(settlement_line_id),
                "computed_at": now,
            },
        )

        # ORPHAN_SETTLEMENT — settlement_line_id only, no match.
        conn.execute(
            text(
                """
                INSERT INTO reconciliation_exception
                    (id, tenant_id, reconciliation_run_id, exception_type, settlement_line_id,
                     marketplace, amount_paise, confidence, formula_version, computed_at)
                VALUES
                    (:id, :tenant_id, :run_id, 'ORPHAN_SETTLEMENT', :settlement_line_id,
                     'MEESHO', 6500, 'VERIFIED', 'reconcile.v1', :computed_at)
                """
            ),
            {
                "id": str(uuid.uuid4()),
                "tenant_id": str(tenant_a),
                "run_id": str(run_id),
                "settlement_line_id": str(other_settlement_line_id),
                "computed_at": now,
            },
        )

        # UNSETTLED_BEYOND_LAG — sales_line_id only, no match.
        conn.execute(
            text(
                """
                INSERT INTO reconciliation_exception
                    (id, tenant_id, reconciliation_run_id, exception_type, sales_line_id,
                     marketplace, amount_paise, confidence, formula_version, computed_at)
                VALUES
                    (:id, :tenant_id, :run_id, 'UNSETTLED_BEYOND_LAG', :sales_line_id,
                     'MEESHO', 12000, 'VERIFIED', 'reconcile.v1', :computed_at)
                """
            ),
            {
                "id": str(uuid.uuid4()),
                "tenant_id": str(tenant_a),
                "run_id": str(run_id),
                "sales_line_id": str(unsettled_sales_line_id),
                "computed_at": now,
            },
        )

        # DUPLICATE_SETTLEMENT — settlement_line_id only, no match.
        conn.execute(
            text(
                """
                INSERT INTO reconciliation_exception
                    (id, tenant_id, reconciliation_run_id, exception_type, settlement_line_id,
                     marketplace, amount_paise, confidence, formula_version, computed_at)
                VALUES
                    (:id, :tenant_id, :run_id, 'DUPLICATE_SETTLEMENT', :settlement_line_id,
                     'MEESHO', 6500, 'VERIFIED', 'reconcile.v1', :computed_at)
                """
            ),
            {
                "id": str(uuid.uuid4()),
                "tenant_id": str(tenant_a),
                "run_id": str(run_id),
                "settlement_line_id": str(duplicate_settlement_line_id),
                "computed_at": now,
            },
        )

        # AMBIGUOUS_MATCH — settlement_line_id set, candidate_sales_line_ids populated.
        conn.execute(
            text(
                """
                INSERT INTO reconciliation_exception
                    (id, tenant_id, reconciliation_run_id, exception_type, settlement_line_id,
                     candidate_sales_line_ids, marketplace, amount_paise, confidence,
                     formula_version, computed_at)
                VALUES
                    (:id, :tenant_id, :run_id, 'AMBIGUOUS_MATCH', :settlement_line_id,
                     CAST(:candidate_ids AS jsonb), 'MEESHO', 6500, 'VERIFIED', 'reconcile.v1', :computed_at)
                """
            ),
            {
                "id": str(uuid.uuid4()),
                "tenant_id": str(tenant_a),
                "run_id": str(run_id),
                "settlement_line_id": str(ambiguous_settlement_line_id),
                "candidate_ids": _json_array(candidate_ids),
                "computed_at": now,
            },
        )

    with tenant_scope(tenant_a) as conn:
        rows = conn.execute(
            text("SELECT exception_type FROM reconciliation_exception ORDER BY exception_type")
        ).fetchall()
    assert sorted(r[0] for r in rows) == sorted(
        [
            "VARIANCE_EXCEEDS_TOLERANCE",
            "ORPHAN_SETTLEMENT",
            "UNSETTLED_BEYOND_LAG",
            "DUPLICATE_SETTLEMENT",
            "AMBIGUOUS_MATCH",
        ]
    )


def _json_array(values: list[str]) -> str:
    import json

    return json.dumps(values)


def test_downgrade_then_upgrade_roundtrips_reconciliation_tables(migrate_engine):
    from pathlib import Path

    package_root = Path(__file__).resolve().parents[2]
    cfg = Config(str(package_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(package_root / "migrations"))

    command.downgrade(cfg, "20260917_0003")
    inspector = inspect(migrate_engine)
    assert not (set(_TABLES) & set(inspector.get_table_names())), "downgrade left reconciliation tables behind"

    command.upgrade(cfg, "head")
    inspector = inspect(migrate_engine)
    assert set(_TABLES) <= set(inspector.get_table_names()), "upgrade did not recreate every reconciliation table"

    with migrate_engine.connect() as conn:
        forced = conn.execute(
            text(
                "SELECT relname FROM pg_class WHERE relforcerowsecurity = true AND relname = ANY(:names)"
            ).bindparams(names=list(_TABLES))
        ).fetchall()
    assert {r[0] for r in forced} == set(_TABLES)
