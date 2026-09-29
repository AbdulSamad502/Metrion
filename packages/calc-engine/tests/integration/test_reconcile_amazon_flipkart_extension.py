"""`calc_engine.api.reconcile.reconcile` extended to Amazon/Flipkart — data-foundation.md
§5.1.5, deterministic-engine.md §5.12.2 — against a real Postgres.

Fixtures here are synthetic-but-structurally-real: shaped to match each real adapter's actual
canonical_field output (`amazon.settlement.v2`'s `gross_settlement_amount` always absent,
`component_code=None` on every row; `flipkart.payments.v1`'s real `gross_settlement_amount`
and real settlement-side `component_code`s) — no adapter is actually run here, only the row
shapes those adapters are documented to produce (§5.1.4/§5.1.3), inserted directly via the same
real repositories/raw SQL `test_reconcile_real_meesho_data.py` already uses.

Assertions map directly to this checkpoint's own test list:
  (a) reconciliation_run.join_key_validated: false for AMAZON/FLIPKART, true for MEESHO.
  (b) Every AMAZON/FLIPKART match/exception confidence caps at PROVISIONAL even when the
      underlying rows are VERIFIED.
  (c) Amazon: a settlement row with gross_settlement_amount=None never produces a persisted
      exception; amount_unavailable_count reflects it.
  (d) Amazon produces zero DUPLICATE_SETTLEMENT/VARIANCE_EXCEEDS_TOLERANCE outcomes even when
      seeded with a structure that DOES trigger both for Meesho (same test file, direct
      contrast) — a natural consequence of Amazon's real structural gaps (None amount, zero
      settlement-side line_component rows), never a marketplace-if-branch in reconcile.py.
  (e) Flipkart, with a real seeded gross_settlement_amount, CAN produce ORPHAN_SETTLEMENT and
      DUPLICATE_SETTLEMENT — it is not equally blocked (§5.1.5 point 3).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import text

from calc_engine.api.reconcile import reconcile
from calc_engine.repositories.tenant_context import tenant_scope as engine_tenant_scope
from data_foundation.repositories import ingestion_run_repo, sales_line_repo
from data_foundation.repositories.tenant_context import tenant_scope as df_tenant_scope

pytestmark = [pytest.mark.usefixtures("_clean_engine_tables")]

_PERIOD_START = date(2026, 1, 1)
_PERIOD_END = date(2026, 1, 31)
_AS_OF = date(2026, 1, 20)  # close to order_date, well inside a 90-day lag -> Path B stays quiet
_COMPUTED_AT = datetime(2026, 1, 20, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _clean_extension_tables(migrate_engine):
    tables = (
        "reconciliation_exception",
        "reconciliation_match",
        "reconciliation_run",
        "line_component",
        "sales_line",
        "settlement_line",
        "ingestion_run",
        "report_file",
        "reconciliation_tolerance_config",
    )
    with migrate_engine.begin() as conn:
        for t in tables:
            conn.execute(text(f"DELETE FROM {t}"))
    yield
    with migrate_engine.begin() as conn:
        for t in tables:
            conn.execute(text(f"DELETE FROM {t}"))


def _insert_report_file(tenant_id: uuid.UUID, *, marketplace: str) -> uuid.UUID:
    file_id = uuid.uuid4()
    with df_tenant_scope(tenant_id) as conn:
        conn.execute(
            text(
                """
                INSERT INTO report_file
                    (id, tenant_id, marketplace, report_category, content_sha256, original_filename,
                     byte_size, storage_uri, uploaded_by, uploaded_at)
                VALUES
                    (:id, :tenant_id, :marketplace, 'SETTLEMENT', :sha, 'synthetic.xlsx', 100,
                     's3://bucket/x', :uploaded_by, :uploaded_at)
                """
            ),
            {
                "id": str(file_id),
                "tenant_id": str(tenant_id),
                "marketplace": marketplace,
                "sha": uuid.uuid4().hex + uuid.uuid4().hex,
                "uploaded_by": str(uuid.uuid4()),
                "uploaded_at": datetime.now(timezone.utc),
            },
        )
    return file_id


def _insert_ingestion_run(tenant_id: uuid.UUID, *, marketplace: str) -> uuid.UUID:
    report_file_id = _insert_report_file(tenant_id, marketplace=marketplace)
    return ingestion_run_repo.insert_ingestion_run(
        tenant_id,
        report_file_id=report_file_id,
        adapter_id=f"{marketplace.lower()}.synthetic.v1",
        adapter_version="v1",
        started_at=datetime.now(timezone.utc),
    )


def _insert_sales_line(
    tenant_id: uuid.UUID,
    *,
    ingestion_run_id: uuid.UUID,
    marketplace: str,
    order_ref: str,
    line_ref: str | None = None,
    taxable_amount: int = 10_000,
    order_date: date = date(2026, 1, 10),
    confidence: str = "VERIFIED",
) -> uuid.UUID:
    return sales_line_repo.insert_sales_line(
        tenant_id,
        ingestion_run_id=ingestion_run_id,
        marketplace=marketplace,
        canonical_fields={
            "order_ref": order_ref,
            "line_ref": line_ref,
            "taxable_amount": taxable_amount,
            "order_date": order_date,
        },
        source_row_number=1,
        source_row_json={},
        confidence=confidence,
    )


def _insert_settlement_line(
    tenant_id: uuid.UUID,
    *,
    ingestion_run_id: uuid.UUID,
    marketplace: str,
    order_ref: str | None,
    line_ref: str | None = None,
    gross_settlement_amount: int | None,
    settlement_date_: date,
    confidence: str = "VERIFIED",
) -> uuid.UUID:
    settlement_line_id = uuid.uuid4()
    with df_tenant_scope(tenant_id) as conn:
        conn.execute(
            text(
                """
                INSERT INTO settlement_line
                    (id, tenant_id, ingestion_run_id, marketplace, order_ref, line_ref,
                     settlement_id, gross_settlement_amount, currency, settlement_date,
                     document_type, source_row_number, source_row_json, confidence)
                VALUES
                    (:id, :tenant_id, :ingestion_run_id, :marketplace, :order_ref, :line_ref,
                     NULL, :gross_settlement_amount, 'INR', :settlement_date,
                     'SETTLEMENT', 1, '{}'::jsonb, :confidence)
                """
            ),
            {
                "id": str(settlement_line_id),
                "tenant_id": str(tenant_id),
                "ingestion_run_id": str(ingestion_run_id),
                "marketplace": marketplace,
                "order_ref": order_ref,
                "line_ref": line_ref,
                "gross_settlement_amount": gross_settlement_amount,
                "settlement_date": settlement_date_,
                "confidence": confidence,
            },
        )
    return settlement_line_id


def _insert_settlement_component(
    tenant_id: uuid.UUID, *, settlement_line_id: uuid.UUID, component_code: str, amount_paise: int
) -> None:
    with df_tenant_scope(tenant_id) as conn:
        conn.execute(
            text(
                """
                INSERT INTO line_component
                    (id, tenant_id, sales_line_id, settlement_line_id, component_kind,
                     component_code, source_side, amount, tax_amount, rate_pct, source_column,
                     is_verified, note)
                VALUES
                    (:id, :tenant_id, NULL, :settlement_line_id, 'FEE', :component_code,
                     'SETTLEMENT', :amount, NULL, NULL, 'synthetic', false, NULL)
                """
            ),
            {
                "id": str(uuid.uuid4()),
                "tenant_id": str(tenant_id),
                "settlement_line_id": str(settlement_line_id),
                "component_code": component_code,
                "amount": amount_paise,
            },
        )


def _insert_invoice_component(
    tenant_id: uuid.UUID, *, sales_line_id: uuid.UUID, component_code: str, amount_paise: int
) -> None:
    with df_tenant_scope(tenant_id) as conn:
        conn.execute(
            text(
                """
                INSERT INTO line_component
                    (id, tenant_id, sales_line_id, settlement_line_id, component_kind,
                     component_code, source_side, amount, tax_amount, rate_pct, source_column,
                     is_verified, note)
                VALUES
                    (:id, :tenant_id, :sales_line_id, NULL, 'FEE', :component_code,
                     'INVOICE', :amount, NULL, NULL, 'synthetic', false, NULL)
                """
            ),
            {
                "id": str(uuid.uuid4()),
                "tenant_id": str(tenant_id),
                "sales_line_id": str(sales_line_id),
                "component_code": component_code,
                "amount": amount_paise,
            },
        )


def _insert_tolerance(
    tenant_id: uuid.UUID,
    *,
    marketplace: str,
    component_code: str,
    tolerance_paise: int,
    tolerance_bps: int,
    settlement_lag_days: int = 90,
    grace_period_days: int = 30,
) -> None:
    with engine_tenant_scope(tenant_id) as conn:
        conn.execute(
            text(
                """
                INSERT INTO reconciliation_tolerance_config
                    (id, tenant_id, marketplace, component_code, tolerance_paise, tolerance_bps,
                     settlement_lag_days, grace_period_days, effective_from, version)
                VALUES
                    (:id, NULL, :marketplace, :component_code, :tolerance_paise, :tolerance_bps,
                     :settlement_lag_days, :grace_period_days, '2026-01-01', 1)
                """
            ),
            {
                "id": str(uuid.uuid4()),
                "marketplace": marketplace,
                "component_code": component_code,
                "tolerance_paise": tolerance_paise,
                "tolerance_bps": tolerance_bps,
                "settlement_lag_days": settlement_lag_days,
                "grace_period_days": grace_period_days,
            },
        )


def _run_row(tenant_id: uuid.UUID, run_id: uuid.UUID):
    with engine_tenant_scope(tenant_id) as conn:
        return conn.execute(
            text("SELECT * FROM reconciliation_run WHERE id = :id"), {"id": str(run_id)}
        ).mappings().first()


def _exceptions_for_run(tenant_id: uuid.UUID, run_id: uuid.UUID) -> list[dict]:
    with engine_tenant_scope(tenant_id) as conn:
        return [
            dict(r)
            for r in conn.execute(
                text("SELECT * FROM reconciliation_exception WHERE reconciliation_run_id = :id"),
                {"id": str(run_id)},
            ).mappings().all()
        ]


def _matches_for_run(tenant_id: uuid.UUID, run_id: uuid.UUID) -> list[dict]:
    with engine_tenant_scope(tenant_id) as conn:
        return [
            dict(r)
            for r in conn.execute(
                text("SELECT * FROM reconciliation_match WHERE reconciliation_run_id = :id"),
                {"id": str(run_id)},
            ).mappings().all()
        ]


# --- (a) join_key_validated: false for AMAZON/FLIPKART, true for MEESHO ---------------------


def test_join_key_validated_false_for_amazon_and_flipkart_true_for_meesho(two_tenants):
    tenant_a, _ = two_tenants
    for marketplace, expected in (("MEESHO", True), ("AMAZON", False), ("FLIPKART", False)):
        result = reconcile(
            tenant_a,
            marketplace=marketplace,
            period_start=_PERIOD_START,
            period_end=_PERIOD_END,
            as_of_date=_AS_OF,
            computed_at=_COMPUTED_AT,
        )
        run_row = _run_row(tenant_a, result.reconciliation_run_id)
        assert run_row["join_key_validated"] is expected, marketplace


# --- (b) confidence capped at PROVISIONAL for AMAZON/FLIPKART even when rows are VERIFIED ----


def test_amazon_ambiguous_match_confidence_capped_at_provisional(two_tenants):
    tenant_a, _ = two_tenants
    ingestion_run_id = _insert_ingestion_run(tenant_a, marketplace="AMAZON")

    # Order-grain collision: two real Amazon sales_line rows sharing one order_ref — the
    # expected, structural consequence of order-grain matching (§5.1.5).
    _insert_sales_line(tenant_a, ingestion_run_id=ingestion_run_id, marketplace="AMAZON", order_ref="AMZ-1", confidence="VERIFIED")
    _insert_sales_line(tenant_a, ingestion_run_id=ingestion_run_id, marketplace="AMAZON", order_ref="AMZ-1", confidence="VERIFIED")
    _insert_settlement_line(
        tenant_a,
        ingestion_run_id=ingestion_run_id,
        marketplace="AMAZON",
        order_ref="AMZ-1",
        gross_settlement_amount=9_999,  # a real amount, for this test only — proves the cap
        settlement_date_=date(2026, 1, 15),
        confidence="VERIFIED",
    )

    result = reconcile(
        tenant_a,
        marketplace="AMAZON",
        period_start=_PERIOD_START,
        period_end=_PERIOD_END,
        as_of_date=_AS_OF,
        computed_at=_COMPUTED_AT,
    )

    exceptions = _exceptions_for_run(tenant_a, result.reconciliation_run_id)
    assert len(exceptions) == 1
    assert exceptions[0]["exception_type"] == "AMBIGUOUS_MATCH"
    assert exceptions[0]["confidence"] == "PROVISIONAL"
    assert result.exception_metric_results[0].confidence == "PROVISIONAL"


def test_meesho_ambiguous_match_confidence_stays_verified_contrast(two_tenants):
    """Direct contrast to the AMAZON test above: same VERIFIED inputs, same collision shape,
    but Meesho's join-key confidence is VERIFIED, so the exception is not capped."""
    tenant_a, _ = two_tenants
    ingestion_run_id = _insert_ingestion_run(tenant_a, marketplace="MEESHO")

    _insert_sales_line(tenant_a, ingestion_run_id=ingestion_run_id, marketplace="MEESHO", order_ref="M-1", line_ref="M-1_1", confidence="VERIFIED")
    _insert_sales_line(tenant_a, ingestion_run_id=ingestion_run_id, marketplace="MEESHO", order_ref="M-1", line_ref="M-1_1", confidence="VERIFIED")
    _insert_settlement_line(
        tenant_a,
        ingestion_run_id=ingestion_run_id,
        marketplace="MEESHO",
        order_ref=None,
        line_ref="M-1_1",
        gross_settlement_amount=9_999,
        settlement_date_=date(2026, 1, 15),
        confidence="VERIFIED",
    )

    result = reconcile(
        tenant_a,
        marketplace="MEESHO",
        period_start=_PERIOD_START,
        period_end=_PERIOD_END,
        as_of_date=_AS_OF,
        computed_at=_COMPUTED_AT,
    )

    exceptions = _exceptions_for_run(tenant_a, result.reconciliation_run_id)
    assert len(exceptions) == 1
    assert exceptions[0]["exception_type"] == "AMBIGUOUS_MATCH"
    assert exceptions[0]["confidence"] == "VERIFIED"


def test_flipkart_orphan_settlement_confidence_capped_at_provisional(two_tenants):
    tenant_a, _ = two_tenants
    ingestion_run_id = _insert_ingestion_run(tenant_a, marketplace="FLIPKART")

    _insert_settlement_line(
        tenant_a,
        ingestion_run_id=ingestion_run_id,
        marketplace="FLIPKART",
        order_ref="FK-ORPHAN",
        gross_settlement_amount=8_000,
        settlement_date_=date(2026, 1, 15),
        confidence="VERIFIED",
    )

    result = reconcile(
        tenant_a,
        marketplace="FLIPKART",
        period_start=_PERIOD_START,
        period_end=_PERIOD_END,
        as_of_date=_AS_OF,
        computed_at=_COMPUTED_AT,
    )

    exceptions = _exceptions_for_run(tenant_a, result.reconciliation_run_id)
    assert len(exceptions) == 1
    assert exceptions[0]["exception_type"] == "ORPHAN_SETTLEMENT"
    assert exceptions[0]["confidence"] == "PROVISIONAL"


# --- (c) Amazon: gross_settlement_amount=None never produces a persisted exception ----------


def test_amazon_orphan_settlement_with_none_amount_never_persisted(two_tenants):
    tenant_a, _ = two_tenants
    ingestion_run_id = _insert_ingestion_run(tenant_a, marketplace="AMAZON")

    _insert_settlement_line(
        tenant_a,
        ingestion_run_id=ingestion_run_id,
        marketplace="AMAZON",
        order_ref="AMZ-ORPHAN",
        gross_settlement_amount=None,  # real Amazon shape — amazon.settlement.v2 never binds this
        settlement_date_=date(2026, 1, 15),
        confidence="VERIFIED",
    )

    result = reconcile(
        tenant_a,
        marketplace="AMAZON",
        period_start=_PERIOD_START,
        period_end=_PERIOD_END,
        as_of_date=_AS_OF,
        computed_at=_COMPUTED_AT,
    )

    assert result.exception_count == 0
    assert result.amount_unavailable_count == 1
    assert _exceptions_for_run(tenant_a, result.reconciliation_run_id) == []


# --- (d) Amazon: zero DUPLICATE_SETTLEMENT/VARIANCE_EXCEEDS_TOLERANCE, contrasted with Meesho -


def test_amazon_zero_duplicate_and_variance_outcomes_vs_meesho_same_shape(two_tenants):
    tenant_a, _ = two_tenants

    # --- Meesho: real structure (invoice+settlement components, real amount) DOES trigger both.
    meesho_run_id = _insert_ingestion_run(tenant_a, marketplace="MEESHO")
    meesho_sales_id = _insert_sales_line(
        tenant_a, ingestion_run_id=meesho_run_id, marketplace="MEESHO", order_ref="M-2", line_ref="M-2_1"
    )
    _insert_invoice_component(tenant_a, sales_line_id=meesho_sales_id, component_code="COMMISSION", amount_paise=5_000)
    _insert_tolerance(tenant_a, marketplace="MEESHO", component_code="COMMISSION", tolerance_paise=50, tolerance_bps=10)
    _insert_tolerance(tenant_a, marketplace="MEESHO", component_code="*", tolerance_paise=0, tolerance_bps=0)

    first = _insert_settlement_line(
        tenant_a, ingestion_run_id=meesho_run_id, marketplace="MEESHO", order_ref=None, line_ref="M-2_1",
        gross_settlement_amount=6_500, settlement_date_=date(2026, 1, 15),
    )
    _insert_settlement_component(tenant_a, settlement_line_id=first, component_code="COMMISSION", amount_paise=6_500)
    duplicate = _insert_settlement_line(
        tenant_a, ingestion_run_id=meesho_run_id, marketplace="MEESHO", order_ref=None, line_ref="M-2_1",
        gross_settlement_amount=6_500, settlement_date_=date(2026, 1, 15),
    )
    _insert_settlement_component(tenant_a, settlement_line_id=duplicate, component_code="COMMISSION", amount_paise=6_500)

    meesho_result = reconcile(
        tenant_a, marketplace="MEESHO", period_start=_PERIOD_START, period_end=_PERIOD_END,
        as_of_date=_AS_OF, computed_at=_COMPUTED_AT,
    )
    meesho_exceptions = _exceptions_for_run(tenant_a, meesho_result.reconciliation_run_id)
    meesho_types = {e["exception_type"] for e in meesho_exceptions}
    assert "DUPLICATE_SETTLEMENT" in meesho_types
    assert "VARIANCE_EXCEEDS_TOLERANCE" in meesho_types

    # --- Amazon: the SAME shape (same order_ref reused across two settlement rows, same date),
    # but real Amazon structural gaps (None amount, zero settlement-side components) mean
    # neither outcome is reachable — no marketplace-specific skip branch, this falls out of
    # is_duplicate_settlement's None-amount guard and _group_settlement_components being empty.
    amazon_run_id = _insert_ingestion_run(tenant_a, marketplace="AMAZON")
    _insert_sales_line(tenant_a, ingestion_run_id=amazon_run_id, marketplace="AMAZON", order_ref="A-2")
    _insert_tolerance(tenant_a, marketplace="AMAZON", component_code="*", tolerance_paise=0, tolerance_bps=0)
    _insert_settlement_line(
        tenant_a, ingestion_run_id=amazon_run_id, marketplace="AMAZON", order_ref="A-2",
        gross_settlement_amount=None, settlement_date_=date(2026, 1, 15),
    )
    _insert_settlement_line(
        tenant_a, ingestion_run_id=amazon_run_id, marketplace="AMAZON", order_ref="A-2",
        gross_settlement_amount=None, settlement_date_=date(2026, 1, 15),
    )
    # deliberately no settlement-side line_component rows — amazon.settlement.v2's real
    # capture-not-classify shape (§5.1.4).

    amazon_result = reconcile(
        tenant_a, marketplace="AMAZON", period_start=_PERIOD_START, period_end=_PERIOD_END,
        as_of_date=_AS_OF, computed_at=_COMPUTED_AT,
    )
    amazon_exceptions = _exceptions_for_run(tenant_a, amazon_result.reconciliation_run_id)
    amazon_matches = _matches_for_run(tenant_a, amazon_result.reconciliation_run_id)
    amazon_types = {e["exception_type"] for e in amazon_exceptions}
    assert "DUPLICATE_SETTLEMENT" not in amazon_types
    assert amazon_matches == []  # no VARIANCE_EXCEEDS_TOLERANCE (or any outcome) possible
    assert amazon_result.match_count == 0


# --- (e) Flipkart is not equally blocked — real gross_settlement_amount CAN produce outcomes -


def test_flipkart_can_produce_orphan_and_duplicate_with_real_amount(two_tenants):
    tenant_a, _ = two_tenants
    ingestion_run_id = _insert_ingestion_run(tenant_a, marketplace="FLIPKART")

    # ORPHAN_SETTLEMENT: no matching sales_line at all.
    _insert_settlement_line(
        tenant_a, ingestion_run_id=ingestion_run_id, marketplace="FLIPKART", order_ref="FK-ORPHAN-2",
        gross_settlement_amount=4_200, settlement_date_=date(2026, 1, 15),
    )

    # DUPLICATE_SETTLEMENT: a real sales_line with two settlement rows sharing order_ref, real
    # equal amount, same date.
    _insert_sales_line(tenant_a, ingestion_run_id=ingestion_run_id, marketplace="FLIPKART", order_ref="FK-DUP")
    _insert_settlement_line(
        tenant_a, ingestion_run_id=ingestion_run_id, marketplace="FLIPKART", order_ref="FK-DUP",
        gross_settlement_amount=7_500, settlement_date_=date(2026, 1, 16),
    )
    _insert_settlement_line(
        tenant_a, ingestion_run_id=ingestion_run_id, marketplace="FLIPKART", order_ref="FK-DUP",
        gross_settlement_amount=7_500, settlement_date_=date(2026, 1, 16),
    )

    result = reconcile(
        tenant_a, marketplace="FLIPKART", period_start=_PERIOD_START, period_end=_PERIOD_END,
        as_of_date=_AS_OF, computed_at=_COMPUTED_AT,
    )

    exceptions = _exceptions_for_run(tenant_a, result.reconciliation_run_id)
    types = {e["exception_type"] for e in exceptions}
    assert "ORPHAN_SETTLEMENT" in types
    assert "DUPLICATE_SETTLEMENT" in types
    # Real amount, real output — still capped at PROVISIONAL (unvalidated join key).
    assert all(e["confidence"] == "PROVISIONAL" for e in exceptions)


# --- (f) Flipkart CAN produce a genuine SingleMatch/VARIANCE outcome, same as Meesho, when the
# invoice side and settlement side share a component_code — regression test for the
# cfo-e2e-evaluation-mtr-mock-2026-09-27.md §9 item 6 asymmetry (Flipkart match_count=0 where
# Meesho's identical bypass-insert technique produced 40/40). Mirrors
# test_amazon_zero_duplicate_and_variance_outcomes_vs_meesho_same_shape's Meesho half exactly,
# substituting Flipkart's order_ref-only join key for Meesho's line_ref — this proves
# reconcile()'s Path A/Decision-A intersection logic (reconcile.py lines 434-513) is not itself
# marketplace-gated: a real shared component_code on both sides DOES produce a match and, when
# the amounts differ beyond tolerance, a VARIANCE_EXCEEDS_TOLERANCE exception, for Flipkart
# exactly as it does for Meesho. If this test passes, the eval's flagged asymmetry was a property
# of that one-off eval script's own component-code setup for Flipkart, not a defect in reconcile().
def test_flipkart_successful_match_with_shared_component_codes(two_tenants):
    tenant_a, _ = two_tenants
    ingestion_run_id = _insert_ingestion_run(tenant_a, marketplace="FLIPKART")

    sales_id = _insert_sales_line(
        tenant_a, ingestion_run_id=ingestion_run_id, marketplace="FLIPKART", order_ref="FK-MATCH-1"
    )
    _insert_invoice_component(tenant_a, sales_line_id=sales_id, component_code="COMMISSION", amount_paise=5_000)
    _insert_tolerance(tenant_a, marketplace="FLIPKART", component_code="COMMISSION", tolerance_paise=50, tolerance_bps=10)
    _insert_tolerance(tenant_a, marketplace="FLIPKART", component_code="*", tolerance_paise=0, tolerance_bps=0)

    settlement_id = _insert_settlement_line(
        tenant_a, ingestion_run_id=ingestion_run_id, marketplace="FLIPKART", order_ref="FK-MATCH-1",
        gross_settlement_amount=6_500, settlement_date_=date(2026, 1, 15),
    )
    _insert_settlement_component(tenant_a, settlement_line_id=settlement_id, component_code="COMMISSION", amount_paise=6_500)

    result = reconcile(
        tenant_a, marketplace="FLIPKART", period_start=_PERIOD_START, period_end=_PERIOD_END,
        as_of_date=_AS_OF, computed_at=_COMPUTED_AT,
    )

    matches = _matches_for_run(tenant_a, result.reconciliation_run_id)
    exceptions = _exceptions_for_run(tenant_a, result.reconciliation_run_id)
    exception_types = {e["exception_type"] for e in exceptions}

    assert result.match_count == 1
    assert len(matches) == 1
    assert matches[0]["component_code"] == "COMMISSION"
    assert matches[0]["confidence"] == "PROVISIONAL"  # order_ref join key caps it, even matched
    assert "VARIANCE_EXCEEDS_TOLERANCE" in exception_types
    assert result.exception_count == 1
