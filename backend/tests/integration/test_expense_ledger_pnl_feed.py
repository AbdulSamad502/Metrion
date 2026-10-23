"""S4a: the expense-ledger feed into the period P&L, behind a default-OFF flag (expense-tracker.md F6/F7, AC17; engine §5.17).

Flag OFF: nothing is read and every result and response is exactly what it was. Flag ON: the engine feed's ADVERTISING pool becomes the advertising term, the DIRECT pool the
other-attributed term, STORAGE and OVERHEAD are shown beside contribution profit as unallocated lines labelled with the formula version (v1 has no storage term), and the dashboard totals reconcile with
the P&L (the same feed produces both).
"""

from __future__ import annotations

import os
import uuid
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL_APP/DATABASE_URL not set — integration tests need a live Postgres",
)

_START, _END, _AS_OF, _ORDER = date(2026, 9, 1), date(2026, 9, 30), date(2026, 9, 27), date(2026, 9, 10)
_FLAG = "EXPENSE_LEDGER_FEEDS_PNL"
# NRR 40,000 - fees 4,000 - COGS 20,000 = 16,000 with no advertising and no other costs (same fixture as the CFO package's period P&L test).
_BASE_CP = 16_000


@pytest.fixture
def migrate_engine():
    from sqlalchemy import create_engine

    engine = create_engine(os.environ["DATABASE_URL"])
    yield engine
    engine.dispose()


@pytest.fixture(autouse=True)
def _clean_tables(migrate_engine, monkeypatch):
    monkeypatch.delenv(_FLAG, raising=False)
    tables = ("manual_adjustment", "line_component", "sales_line", "ingestion_run", "report_file", "metric_result", "agent_data_request")
    with migrate_engine.begin() as conn:
        for t in tables:
            conn.execute(text(f"DELETE FROM {t}"))
    yield
    with migrate_engine.begin() as conn:
        for t in tables:
            conn.execute(text(f"DELETE FROM {t}"))


def _seed_pnl(tenant_id: uuid.UUID) -> None:
    from calc_engine.repositories.manual_adjustment_repo import insert_adjustment
    from data_foundation.repositories import ingestion_run_repo
    from data_foundation.repositories.sales_line_repo import insert_sales_line
    from data_foundation.repositories.tenant_context import tenant_scope

    file_id = uuid.uuid4()
    with tenant_scope(tenant_id) as conn:
        conn.execute(
            text(
                "INSERT INTO report_file (id, tenant_id, marketplace, report_category, content_sha256, original_filename, byte_size, storage_uri, uploaded_by, uploaded_at) "
                "VALUES (:id, :t, 'MEESHO', 'TAX', :sha, 'synthetic.csv', 100, 'file://x', :by, :at)"
            ),
            {"id": str(file_id), "t": str(tenant_id), "sha": uuid.uuid4().hex + uuid.uuid4().hex, "by": str(uuid.uuid4()), "at": datetime.now(timezone.utc)},
        )
    run = ingestion_run_repo.insert_ingestion_run(
        tenant_id, report_file_id=file_id, adapter_id="meesho.orders.v1", adapter_version="v1", started_at=datetime.now(timezone.utc)
    )
    for _ in range(2):
        line = insert_sales_line(
            tenant_id, ingestion_run_id=run, marketplace="MEESHO",
            canonical_fields={"order_ref": f"ORD-{uuid.uuid4().hex[:8]}", "quantity": 2, "gross_item_amount": 20_000, "taxable_amount": 20_000, "order_date": _ORDER,
                              "return_status": "NOT_RETURNED", "sku": "SKU-001"},
            source_row_number=1, source_row_json={}, confidence="PROVISIONAL",
        )
        with tenant_scope(tenant_id) as conn:
            conn.execute(
                text(
                    "INSERT INTO line_component (id, tenant_id, sales_line_id, settlement_line_id, component_kind, component_code, source_side, amount, tax_amount, rate_pct, "
                    "source_column, is_verified, note) VALUES (:id, :t, :l, NULL, 'FEE', 'COMMISSION', 'INVOICE', 2000, NULL, NULL, 'synthetic', false, NULL)"
                ),
                {"id": str(uuid.uuid4()), "t": str(tenant_id), "l": str(line)},
            )
        for field, value in (("cancellation_state_override", "NOT_CANCELLED"), ("rto_status_override", "NOT_RTO")):
            insert_adjustment(tenant_id, target_type="LINE", target_ref=str(line), field=field, value=value, created_by=uuid.uuid4(), created_at=datetime.now(timezone.utc))
    insert_adjustment(tenant_id, target_type="SKU", target_ref="SKU-001", field="cogs_per_unit", value=5_000, created_by=uuid.uuid4(), created_at=datetime(2026, 1, 1, tzinfo=timezone.utc))


def _expense(tenant_id, *, cost_class, category, amount, review="confirmed", treatment="incremental", day=date(2026, 9, 12), refund_of=None, **kw):
    from calc_engine.repositories import expense_tracker_repo as ledger
    from calc_engine.repositories.expense_tracker_repo import NewRecord

    return ledger.insert_record(
        tenant_id, NewRecord(effective_date=day, category=category, cost_class=cost_class, amount_paise=amount, treatment=treatment, refund_of_expense_id=refund_of, **kw),
        review_state=review, created_by=uuid.uuid4(),
    ).expense_id


def _pnl(tenant_id, **kw):
    import backend.services.cfo_actions as cfo
    from calc_engine.types import RecognitionState

    return cfo.compute_period_pnl_for_tenant(
        tenant_id,
        cfo.PeriodPnlForTenantRequest(
            period_start=_START, period_end=_END, as_of_date=_AS_OF, recognition_state=RecognitionState.RECOGNISED, fee_component_codes=frozenset({"COMMISSION"}),
            forward_logistics_codes=frozenset(), reverse_logistics_codes=frozenset(), non_refunded_fee_codes=frozenset(), requested_by=uuid.uuid4(), **kw,
        ),
    )


def _ledger_rows(tenant_id):
    _expense(tenant_id, cost_class="ADVERTISING", category="advertising", amount=7_000)
    _expense(tenant_id, cost_class="STORAGE", category="storage", amount=3_000)
    _expense(tenant_id, cost_class="OVERHEAD", category="software", amount=5_000)
    _expense(tenant_id, cost_class="DIRECT", category="packaging", amount=2_000)


def test_flag_off_changes_nothing_and_reads_no_ledger(monkeypatch) -> None:
    tenant = uuid.uuid4()
    _seed_pnl(tenant)
    baseline = _pnl(tenant)
    _ledger_rows(tenant)
    import backend.services.expense_ledger_pnl as feed_module

    def boom(*a, **k):
        raise AssertionError("the ledger must not be read while the flag is off")

    monkeypatch.setattr(feed_module, "build", boom)
    off = _pnl(tenant)
    assert off.ledger_feed is None
    assert off.pnl.contribution_profit.value_paise == baseline.pnl.contribution_profit.value_paise == _BASE_CP
    assert off.pnl.advertising_entered is False and off.pnl.advertising_costs_paise is None
    assert off.assembled_line_count == baseline.assembled_line_count


def test_flag_off_values_are_false_for_every_spelling_except_true(monkeypatch) -> None:
    from backend import config

    for raw in ("", "false", "0", "no", "off", "TRUE ", "yes"):
        monkeypatch.setenv(_FLAG, raw)
        assert config.expense_ledger_feeds_pnl() is (raw.strip().lower() == "true")
    monkeypatch.delenv(_FLAG)
    assert config.expense_ledger_feeds_pnl() is False


def test_flag_on_feeds_advertising_and_storage_and_shows_overhead_beside_contribution_profit(monkeypatch) -> None:
    tenant = uuid.uuid4()
    _seed_pnl(tenant)
    _ledger_rows(tenant)
    monkeypatch.setenv(_FLAG, "true")
    out = _pnl(tenant)
    assert out.pnl.contribution_profit.value_paise == _BASE_CP - 7_000 - 2_000  # advertising and direct costs reduce it, by exactly their pools
    assert out.pnl.advertising_entered is True and out.pnl.advertising_costs_paise == 7_000
    feed = out.ledger_feed
    assert feed is not None
    assert feed.formula_version == "CONTRIBUTION_PROFIT.v1"
    unallocated = {u.cost_class: u for u in feed.unallocated}
    assert unallocated["OVERHEAD"].paise == 5_000 and unallocated["STORAGE"].paise == 3_000  # shown beside contribution profit, NOT inside it
    assert unallocated["OVERHEAD"].engine_result_ref and unallocated["STORAGE"].engine_result_ref


def test_flag_on_without_any_ledger_row_keeps_advertising_not_entered(monkeypatch) -> None:
    tenant = uuid.uuid4()
    _seed_pnl(tenant)
    monkeypatch.setenv(_FLAG, "true")
    out = _pnl(tenant)
    assert out.pnl.contribution_profit.value_paise == _BASE_CP
    assert out.pnl.advertising_entered is False and out.pnl.advertising_costs_paise is None
    assert all(u.paise is None and u.engine_result_ref is None for u in out.ledger_feed.unallocated)  # not entered, never zero


def test_only_confirmed_incremental_rows_count_and_a_refund_reduces_the_pool(monkeypatch) -> None:
    tenant = uuid.uuid4()
    _seed_pnl(tenant)
    ad = _expense(tenant, cost_class="ADVERTISING", category="advertising", amount=7_000)
    _expense(tenant, cost_class="ADVERTISING", category="advertising", amount=900, review="pending_review")  # queued, not counted
    _expense(tenant, cost_class="ADVERTISING", category="advertising", amount=800, review="draft")  # not counted
    _expense(tenant, cost_class="ADVERTISING", category="advertising", amount=700, treatment="already_in_settlement")  # already deducted by the marketplace
    _expense(tenant, cost_class="ADVERTISING", category="advertising", amount=600, treatment="informational")
    _expense(tenant, cost_class="ADVERTISING", category="advertising", amount=500, day=date(2026, 10, 2))  # outside the period
    _expense(tenant, cost_class="ADVERTISING", category="advertising", amount=-1_000, refund_of=ad)  # a refund in its own period reduces the pool (sign mapping)
    voided = _expense(tenant, cost_class="ADVERTISING", category="advertising", amount=400)
    from calc_engine.repositories import expense_tracker_repo as ledger

    ledger.append_review(tenant, voided, review_state="voided", reason="duplicate", created_by=uuid.uuid4())
    monkeypatch.setenv(_FLAG, "true")
    out = _pnl(tenant)
    assert out.pnl.advertising_costs_paise == 6_000  # 7,000 - 1,000
    assert out.pnl.contribution_profit.value_paise == _BASE_CP - 6_000


def test_an_advertising_entry_in_the_request_wins_so_nothing_is_counted_twice(monkeypatch) -> None:
    tenant = uuid.uuid4()
    _seed_pnl(tenant)
    _expense(tenant, cost_class="ADVERTISING", category="advertising", amount=7_000)
    monkeypatch.setenv(_FLAG, "true")
    out = _pnl(tenant, advertising_adjustment_values=[{"amount_paise": 2_500}])
    assert out.pnl.advertising_costs_paise == 2_500
    assert out.pnl.contribution_profit.value_paise == _BASE_CP - 2_500
    assert "ADVERTISING" in out.ledger_feed.skipped  # stated, not silent


def test_the_pnl_and_the_dashboard_total_reconcile(monkeypatch) -> None:
    from calc_engine.formulas.ledger_feed import ledger_feed
    from calc_engine.repositories import expense_tracker_repo as ledger

    tenant = uuid.uuid4()
    _seed_pnl(tenant)
    _ledger_rows(tenant)
    monkeypatch.setenv(_FLAG, "true")
    out = _pnl(tenant)
    fed = ledger_feed(ledger.feed_events(tenant, period_start=_START, period_end=_END), period_start=_START, period_end=_END, channel_scope=None, catalog={})
    pools = fed.pools
    total = fed.expense_total.value
    in_pnl = (out.pnl.advertising_costs_paise or 0) + 2_000  # advertising + direct costs
    unallocated = sum(u.paise for u in out.ledger_feed.unallocated if u.paise is not None)
    assert in_pnl + unallocated == total == sum(pools[c].total.value for c in ("ADVERTISING", "DIRECT", "STORAGE", "OVERHEAD"))
    assert out.ledger_feed.watermark == fed.watermark


def test_the_route_adds_the_ledger_block_only_when_the_flag_is_on(monkeypatch) -> None:
    import backend.api.v1.cfo as cfo_api

    tenant = uuid.uuid4()
    _seed_pnl(tenant)
    _ledger_rows(tenant)
    off = _pnl(tenant)
    assert cfo_api._ledger_block(off) == {}  # the response gains no key at all while the flag is off
    monkeypatch.setenv(_FLAG, "true")
    on = _pnl(tenant)
    block = cfo_api._ledger_block(on)["expenseLedger"]
    assert block["formulaVersion"] == "CONTRIBUTION_PROFIT.v1"
    assert {u["costClass"] for u in block["unallocated"]} == {"STORAGE", "OVERHEAD"}
    assert block["watermark"] == on.ledger_feed.watermark
