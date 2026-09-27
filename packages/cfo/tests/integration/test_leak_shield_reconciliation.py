"""`backend.services.cfo_actions.run_leak_shield_reconciliation` — D5, real Postgres.

Two cases:

1. **The empty path, for real.** A fresh tenant with no `sales_line`/`settlement_line` rows at
   all produces a real `reconciliation_run` with `exception_count=0` and zero `leak_finding`
   rows — this proves the whole pipeline (real `reconcile()`, real persistence, real
   `exceptions_for_run` read, real `classify_and_rank_leaks` call with an empty input) works
   end-to-end for real, not a bug (mirroring D4's own confirmed-real-Meesho-data observation
   that today's real data produces zero exceptions — a fresh/empty tenant is the same honest
   empty case, exercised directly rather than re-seeding D4's adapter fixtures here).

2. **A real `leak_finding` from a seeded exception.** `calc_engine.api.reconcile.reconcile`
   itself is monkeypatched (bypassed, per this task's own explicit allowance — real data
   produces no exceptions to exercise the finding-creation path with) to return a
   `ReconcileResult` pointing at a `reconciliation_run`/`reconciliation_exception` pair seeded
   directly via `calc_engine.repositories.reconciliation_repo`'s own real insert functions —
   everything downstream of that (persisting the exception's `MetricResult`, persisting the
   aggregate, reading the exception back via `reconciliation_repo.exceptions_for_run`,
   `classify_and_rank_leaks`, `leak_finding_repo.insert`) is real, hitting the real database.
   Asserts the resulting `leak_finding` row is real: `leak_category='FEE_OVERCHARGE'`, a real
   `engine_result_ref` UUID that resolves to a real, persisted `metric_result` row, and
   `status='NEW'`.
"""

from __future__ import annotations

import os
import uuid
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import create_engine, text

pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL_APP/DATABASE_URL not set — integration tests need a live Postgres",
)

_AS_OF = date(2026, 9, 25)
_PERIOD_START = date(2026, 9, 1)
_PERIOD_END = date(2026, 9, 30)


@pytest.fixture
def migrate_engine():
    engine = create_engine(os.environ["DATABASE_URL"])
    yield engine
    engine.dispose()


@pytest.fixture(autouse=True)
def _clean_reconciliation_tables(migrate_engine):
    """`reconciliation_exception`/`reconciliation_match`/`reconciliation_run` are owned by
    calc-engine's migration, not cfo's own `_clean_cfo_tables` fixture — cleaned here as the
    table owner, mirroring that fixture's own before/after convention, since this file is the
    first cfo test to write to them."""
    tables = (
        "reconciliation_exception",
        "reconciliation_match",
        "reconciliation_run",
        "leak_finding",
        "metric_result",
    )
    with migrate_engine.begin() as conn:
        for t in tables:
            conn.execute(text(f"DELETE FROM {t}"))
    yield
    with migrate_engine.begin() as conn:
        for t in tables:
            conn.execute(text(f"DELETE FROM {t}"))


def test_empty_tenant_produces_real_run_zero_exceptions_zero_findings() -> None:
    import backend.services.cfo_actions as cfo_actions_module

    tenant_id = uuid.uuid4()

    outcome = cfo_actions_module.run_leak_shield_reconciliation(
        tenant_id,
        marketplace="MEESHO",
        period_start=_PERIOD_START,
        period_end=_PERIOD_END,
        as_of_date=_AS_OF,
    )

    assert outcome.reconciliation_run_id is not None
    assert outcome.match_count == 0
    assert outcome.exception_count == 0
    assert outcome.ambiguous_match_count == 0
    assert outcome.findings == []

    from cfo.repositories.leak_finding_repo import list_for_tenant

    assert list_for_tenant(tenant_id) == []


def test_seeded_variance_exception_produces_a_real_persisted_leak_finding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from calc_engine.api.compute_metric import MetricResult
    from calc_engine.api.reconcile import ReconcileResult
    from calc_engine.repositories import reconciliation_repo
    from calc_engine.types import RecognitionState

    import backend.services.cfo_actions as cfo_actions_module

    tenant_id = uuid.uuid4()
    computed_at = datetime(2026, 9, 25, tzinfo=timezone.utc)

    run_id = reconciliation_repo.insert_reconciliation_run(
        tenant_id,
        marketplace="MEESHO",
        period_start=_PERIOD_START,
        period_end=_PERIOD_END,
        as_of_date=_AS_OF,
        tolerance_config_version=1,
        formula_version="reconcile.v1",
        status="COMPLETE",
        join_key_validated=True,
        started_at=computed_at,
        finished_at=computed_at,
        settlement_line_count=1,
        sales_line_count=1,
        match_count=1,
        exception_count=1,
    )

    # A real component_code that maps to FEE in COMPONENT_KIND_BY_CODE, positive amount_paise
    # (settlement > invoice) — must classify as FEE_OVERCHARGE.
    exception_id = reconciliation_repo.insert_reconciliation_exception(
        tenant_id,
        reconciliation_run_id=run_id,
        exception_type="VARIANCE_EXCEEDS_TOLERANCE",
        sales_line_id=uuid.uuid4(),
        settlement_line_id=uuid.uuid4(),
        component_code="COMMISSION",
        marketplace="MEESHO",
        amount_paise=750,
        confidence="DERIVED",
        formula_version="reconcile.v1",
        computed_at=computed_at,
    )

    exception_metric_result = MetricResult(
        id=uuid.uuid4(),
        metric_code="LEAK_EXCEPTION_AMOUNT",
        value_paise=750,
        recognition_state=RecognitionState.RECOGNISED,
        confidence="DERIVED",
        calculation_basis="LeakExceptionAmount(VARIANCE_EXCEEDS_TOLERANCE) — seeded fixture",
        formula_version="reconcile.v1",
        canonical_data_version="non-canonical",
        as_of_date=_AS_OF,
        input_refs=(exception_id,),
        exclusions=(),
        computed_at=computed_at,
        is_available=True,
    )
    aggregate_metric_result = MetricResult(
        id=uuid.uuid4(),
        metric_code="LEAK_TOTAL",
        value_paise=750,
        recognition_state=RecognitionState.RECOGNISED,
        confidence="DERIVED",
        calculation_basis="LeakAggregate — seeded fixture",
        formula_version="reconcile.v1",
        canonical_data_version="non-canonical",
        as_of_date=_AS_OF,
        input_refs=(exception_metric_result.id,),
        exclusions=(),
        computed_at=computed_at,
        is_available=True,
    )

    seeded_result = ReconcileResult(
        reconciliation_run_id=run_id,
        match_count=1,
        exception_count=1,
        dates_missing_count=0,
        amount_unavailable_count=0,
        exception_metric_results=(exception_metric_result,),
        aggregate_metric_result=aggregate_metric_result,
    )
    monkeypatch.setattr(cfo_actions_module, "reconcile", lambda *a, **k: seeded_result)

    outcome = cfo_actions_module.run_leak_shield_reconciliation(
        tenant_id,
        marketplace="MEESHO",
        period_start=_PERIOD_START,
        period_end=_PERIOD_END,
        as_of_date=_AS_OF,
    )

    assert outcome.reconciliation_run_id == run_id
    assert outcome.ambiguous_match_count == 0
    assert len(outcome.findings) == 1

    finding = outcome.findings[0]
    assert finding["leak_category"] == "FEE_OVERCHARGE"

    from cfo.repositories.leak_finding_repo import list_for_tenant

    rows = list_for_tenant(tenant_id)
    assert len(rows) == 1
    real_row = rows[0]
    assert real_row["leak_category"] == "FEE_OVERCHARGE"
    assert real_row["status"] == "NEW"
    assert str(real_row["reconciliation_exception_id"]) == str(exception_id)

    real_engine_result_ref = real_row["engine_result_ref"]
    assert str(real_engine_result_ref) == str(exception_metric_result.id)

    from calc_engine.repositories import metric_result_repo

    resolved = metric_result_repo.get(tenant_id, real_engine_result_ref)
    assert resolved is not None
    assert resolved["metric_code"] == "LEAK_EXCEPTION_AMOUNT"
    assert resolved["value_paise"] == 750
