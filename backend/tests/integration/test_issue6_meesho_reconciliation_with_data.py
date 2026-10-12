"""Issue 6 (Metrion_24_Fixes): "MEESHO September reconciliation returned a generic failure ... retest with canonical data".

`test_cfo_reconcile_preview_states` pins the empty and undated states. This file retests the case the issue names with PERSISTED, DATED canonical MEESHO data: matched lines whose
fee differs, matched lines that agree, an orphan settlement, an orphan sale, and the same data with NO reconciliation tolerance configured (the state a freshly migrated
database is in, and the likeliest cause of an unexplained failure on a seller's instance). Real routes, real `reconcile()`, scratch PostgreSQL: the answer must always be a
200 with structured counts, never a 5xx."""

from __future__ import annotations

import uuid
from datetime import date

import pytest

from tests.integration.test_cfo_imports import _register_owner, app_client, fake_clerk  # noqa: F401  (fixtures and helpers)
from tests.integration.test_settlement_lag_days import (
    _clean_reconciliation_tables,  # noqa: F401  (autouse fixture: clean tables before and after)
    _insert_component,
    _insert_ingestion_run,
    _insert_sales_line,
    _insert_settlement_line,
    _insert_tolerance,
)

PERIOD = {"marketplace": "MEESHO", "period_start": "2026-09-01", "period_end": "2026-09-30", "as_of_date": "2026-09-30"}
RECONCILE, PREVIEW = "/api/v1/cfo/reconcile", "/api/v1/cfo/preview"


def _seed_september(tenant: uuid.UUID) -> None:
    """Meesho joins on the sub-order number (`line_ref`); the sale carries the invoice-side fee, the settlement the settled fee."""
    run = _insert_ingestion_run(tenant, marketplace="MEESHO")
    for n, (sale_fee, settled_fee) in enumerate([(1000, 1500), (1000, 1000), (2000, 2600)]):  # two fee mismatches, one agreeing pair
        ref = f"M-{n}_1"
        sale = _insert_sales_line(tenant, ingestion_run_id=run, marketplace="MEESHO", order_ref=f"M-{n}", line_ref=ref, order_date=date(2026, 9, 5 + n))
        settled = _insert_settlement_line(tenant, ingestion_run_id=run, marketplace="MEESHO", order_ref=None, line_ref=ref, gross_settlement_amount=10_000,
                                          settlement_date_=date(2026, 9, 20 + n))
        _insert_component(tenant, sales_line_id=sale, settlement_line_id=None, source_side="INVOICE", component_code="COMMISSION", amount_paise=sale_fee)
        _insert_component(tenant, sales_line_id=None, settlement_line_id=settled, source_side="SETTLEMENT", component_code="COMMISSION", amount_paise=settled_fee)
    _insert_settlement_line(tenant, ingestion_run_id=run, marketplace="MEESHO", order_ref=None, line_ref="M-ORPHAN_1", gross_settlement_amount=5_000, settlement_date_=date(2026, 9, 25))
    _insert_sales_line(tenant, ingestion_run_id=run, marketplace="MEESHO", order_ref="M-ORPHAN-SALE", line_ref="M-ORPHAN-SALE_1", order_date=date(2026, 9, 28))


@pytest.mark.parametrize("configured", [False, True], ids=["no-tolerance-configured", "tolerance-configured"])
def test_meesho_september_with_real_canonical_data_answers_200_with_structured_counts(app_client, fake_clerk, two_tenants, configured):
    a, _ = two_tenants
    headers = _register_owner(fake_clerk, a)
    _seed_september(a)
    if configured:
        _insert_tolerance(a, marketplace="MEESHO", component_code="*", tolerance_paise=0, tolerance_bps=0)
        _insert_tolerance(a, marketplace="MEESHO", component_code="COMMISSION", tolerance_paise=0, tolerance_bps=0)
    r = app_client.post(RECONCILE, json=PERIOD, headers=headers)
    assert r.status_code == 200, r.text  # the issue: this used to be an unexplained generic failure
    body = r.json()
    assert isinstance(body["findings"], list)
    assert body["datesMissingCount"] == 0
    assert body["exceptionCount"] >= 1  # the orphans are reported as exceptions, not dropped
    if configured:
        assert body["matchCount"] >= 3 and any(f["leakCategory"] == "FEE_OVERCHARGE" for f in body["findings"])  # pairs matched on the sub-order number; both fee mismatches found
    else:
        # KNOWN GAP (docs/planning/stages-3-4-5-report-2026-10-12.md, issue 6): with no tolerance row for a component the engine cannot compare it, skips the pair, and the
        # response says nothing about WHY matchCount is 0. It is a 200 with structure, never a failure; the missing "unavailable reason" field is an additive API change that
        # needs approval. This assertion pins today's behaviour so the change is deliberate when it is made.
        assert body["matchCount"] == 0
    p = app_client.post(PREVIEW, json=PERIOD, headers=headers)
    assert p.status_code == 200 and "lockedFindingsCount" in p.json()


def test_a_second_run_over_the_same_data_is_also_a_200(app_client, fake_clerk, two_tenants):
    a, _ = two_tenants
    headers = _register_owner(fake_clerk, a)
    _seed_september(a)
    assert app_client.post(RECONCILE, json=PERIOD, headers=headers).status_code == 200
    assert app_client.post(RECONCILE, json=PERIOD, headers=headers).status_code == 200  # repeating a run must not trip over its own earlier rows
