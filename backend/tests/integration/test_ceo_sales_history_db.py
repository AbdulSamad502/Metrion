"""Spec §6.33 with REAL ingested sales rows: the sales history a new-product run reads is assembled from sales_line / line_component / manual_adjustment rows,
filtered to the SKU, keeps return status (a returned unit is not sold), and names the lines it could not use."""

from __future__ import annotations

import dataclasses
import os
import uuid
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import text

from backend.ceo import orchestrator
from backend.services import ceo_reads, cfo_actions
from tests.integration.ceo_support import ctx_for
from tests.integration.test_ceo_turn import Grounded, Scripted, runtime, start

pytestmark = [pytest.mark.usefixtures("two_tenants"), pytest.mark.skipif(not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL"), reason="needs a live Postgres")]

START, END = date(2026, 7, 1), date(2026, 9, 30)
UI = orchestrator.UiAction


def _run(tenant):
    from data_foundation.repositories import ingestion_run_repo

    from data_foundation.repositories.tenant_context import tenant_scope

    file_id = uuid.uuid4()
    with tenant_scope(tenant) as conn:
        conn.execute(text("INSERT INTO report_file (id, tenant_id, marketplace, report_category, content_sha256, original_filename, byte_size, storage_uri, uploaded_by, uploaded_at) "
                          "VALUES (:id, :t, 'MEESHO', 'TAX', :sha, 's.csv', 1, 'file://x', :by, :at)"),
                     {"id": str(file_id), "t": str(tenant), "sha": uuid.uuid4().hex * 2, "by": str(uuid.uuid4()), "at": datetime.now(timezone.utc)})
    return ingestion_run_repo.insert_ingestion_run(tenant, report_file_id=file_id, adapter_id="meesho.orders.v1", adapter_version="v1", started_at=datetime.now(timezone.utc))


def _line(tenant, run, sku, qty, amount, status):
    from data_foundation.repositories.sales_line_repo import insert_sales_line

    return insert_sales_line(
        tenant, ingestion_run_id=run, marketplace="MEESHO",
        canonical_fields={"order_ref": f"O-{uuid.uuid4().hex[:8]}", "quantity": qty, "gross_item_amount": amount, "taxable_amount": amount, "order_date": date(2026, 8, 10),
                          "return_status": status, "sku": sku},
        source_row_number=1, source_row_json={}, confidence="PROVISIONAL",
    )


@pytest.fixture
def cleanup(migrate_engine):
    yield
    with migrate_engine.begin() as conn:
        for t in ("manual_adjustment", "line_component", "sales_line", "ingestion_run", "report_file"):
            conn.execute(text(f"UPDATE {t} SET supersedes_id = NULL") if t == "manual_adjustment" else text("SELECT 1"))
            conn.execute(text(f"DELETE FROM {t}"))


def test_the_history_is_this_skus_lines_with_return_status_kept_and_unusable_lines_named(two_tenants, app_user, cleanup):
    a, b = two_tenants
    run = _run(a)
    _line(a, run, "SKU-1", 5, 50000, "NOT_RETURNED")
    returned = _line(a, run, "SKU-1", 3, 30000, None)  # status comes from the seller's overrides
    for field, value in (("return_status_override", "RETURNED"), ("returned_qty_override", 2)):
        from calc_engine.repositories.manual_adjustment_repo import insert_adjustment

        insert_adjustment(a, target_type="LINE", target_ref=str(returned), field=field, value=value, created_by=app_user, created_at=datetime.now(timezone.utc))
    _line(a, run, "SKU-1", 1, 10000, "RETURNED")  # confirmed return, no unit count anywhere: cannot be honestly assembled
    _line(a, run, "SKU-2", 9, 90000, "NOT_RETURNED")  # another SKU: never part of this history
    other_run = _run(b)
    _line(b, other_run, "SKU-1", 100, 1000000, "NOT_RETURNED")  # another tenant's SKU-1: never visible

    h = ceo_reads.sales_history(a, "SKU-1", period_start=START, period_end=END)
    assert len(h.lines) == 2 and sum(l["quantity"] for l in h.lines) == 8  # 5 + 3 ordered (the engine, not this code, subtracts the 2 returned)
    assert {l["return_status"] for l in h.lines} == {"NOT_RETURNED", "RETURNED"} and sorted(l["returned_qty"] for l in h.lines) == [0, 2]  # status kept
    assert h.blocked_count == 1 and "no real unit count" in h.blocked_reasons[0]


def test_the_new_product_answer_names_the_unusable_line_and_runs_on_the_real_engine(two_tenants, app_user, cleanup):
    a, _ = two_tenants
    run = _run(a)
    _line(a, run, "SKU-1", 5, 50000, "NOT_RETURNED")
    _line(a, run, "SKU-1", 1, 10000, "RETURNED")  # unusable: named, not dropped silently
    cfo_actions.enter_expense(a, target_type="SKU", target_ref="SKU-1", field="supplier.quote", created_by=app_user,
                              value={"supplier_name": "Acme", "unit_cost_paise": 10000, "moq": 50, "lead_time_days": 21})
    cfo_actions.enter_expense(a, target_type="ACCOUNT", target_ref=str(a), field="batch.budget", created_by=app_user, value={"amount_paise": 2_000_000})
    ctx = ctx_for(a, user_id=app_user)
    rt = dataclasses.replace(runtime(Scripted({}), Grounded()), max_candidate_prices=5)
    inv = start(ctx, rt)
    res = orchestrator.run_turn(ctx, rt, inv, "Should I stock SKU-1?", ui_action=UI("PLAYBOOK", "NEW_PRODUCT_DECISION", inputs={"sku": "SKU-1", "quantity": 100, "period_start": "2026-07-01", "period_end": "2026-09-30"}))
    assert res.status == "DELIVERED"
    assert any("Sales history: 1 line" in n for n in res.notes) and any("1 sales line could not be used" in n for n in res.notes)
    assert "Most units your budget allows: 200 units" in res.answer  # floor(2,000,000 / 10,000): the history does not change a budget-and-MOQ ceiling


def test_a_marketplaces_own_status_words_are_not_read_as_the_engines_status(two_tenants, app_user, cleanup):
    """Found running the owner's mock MTR reports: a file's "Returned" / "Not Returned" / "Delivered" text was taken as an OBSERVED canonical status, so a returned order was read as
    not returned and Net Realized Revenue silently equalled Gross Sales. Only the engine's own values count as observed; other words are unresolved, so the seller's declaration fills
    the gap (and a confirmed return still needs its unit count)."""
    from calc_engine.repositories.manual_adjustment_repo import insert_adjustment

    a, _ = two_tenants
    run = _run(a)
    returned_word = _line(a, run, "SKU-1", 2, 20000, "Returned")
    kept_word = _line(a, run, "SKU-1", 1, 10000, "Not Returned")
    undeclared = _line(a, run, "SKU-1", 1, 10000, "Delivered")
    for lid, field, value in ((returned_word, "return_status_override", "RETURNED"), (kept_word, "return_status_override", "NOT_RETURNED")):
        insert_adjustment(a, target_type="LINE", target_ref=str(lid), field=field, value=value, created_by=app_user, created_at=datetime.now(timezone.utc))
    out = cfo_actions.assemble_canonical_lines_for_period(a, period_start=START, period_end=END)
    by_id = {l.sales_line_id: l for l in out.lines}
    assert by_id[kept_word].return_status == "NOT_RETURNED"  # the seller's declaration was used, not the file's wording
    assert by_id[undeclared].return_status is None  # "Delivered" is not a canonical status: unresolved, never guessed
    blocked = {b.sales_line_id: b for b in out.blocked}
    assert returned_word in blocked and "returned_qty_override" in blocked[returned_word].missing_inputs  # a declared return still needs its unit count
