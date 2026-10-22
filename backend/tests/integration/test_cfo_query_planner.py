"""The CFO query planner end to end on a real database (cfo-query-planner.md §13): a mocked model proposes plans; everything else is real —
validator, statistics measured from the data, the oracle-verified SQL path, Brain 1's own composition, the cache and tenant isolation.

The central claim: the planner's numbers ARE the dashboard's numbers (same engine results), never a parallel calculation."""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import text

from calc_engine.repositories import read_model_version_repo
from calc_engine.types import RecognitionState
from cfo.planner.cache_store import InMemoryEvidenceCache
from cfo.planner.pipeline import MockPlannerProvider, PlannerAnswer, PlannerRefusal
from cfo.planner.plan import PeriodRef

import backend.services.cfo_actions as cfo_actions
from backend.services.cfo_query import answer_financial_query

SEP = PeriodRef(date(2026, 9, 1), date(2026, 9, 30), date(2026, 10, 1))
OCT = PeriodRef(date(2026, 10, 1), date(2026, 10, 31), date(2026, 11, 1))
FEES = frozenset({"COD_FEE", "COLLECTION_FEE", "COMMISSION", "FIXED_FEE", "MARKETPLACE_FEE_GENERIC", "NON_ORDER_FEE", "PACKAGING_FEE", "PLATFORM_FEE"})


def _file_and_run(tenant: uuid.UUID) -> uuid.UUID:
    from data_foundation.repositories import ingestion_run_repo
    from data_foundation.repositories.tenant_context import tenant_scope

    fid = uuid.uuid4()
    with tenant_scope(tenant) as conn:
        conn.execute(text(
            "INSERT INTO report_file (id, tenant_id, marketplace, report_category, content_sha256, original_filename, byte_size, storage_uri, uploaded_by, uploaded_at)"
            " VALUES (:id, :t, 'MEESHO', 'TAX', :sha, 'synthetic.csv', 100, 'file://x', :u, :at)"),
            {"id": str(fid), "t": str(tenant), "sha": uuid.uuid4().hex + uuid.uuid4().hex, "u": str(uuid.uuid4()), "at": datetime.now(timezone.utc)})
    return ingestion_run_repo.insert_ingestion_run(tenant, report_file_id=fid, adapter_id="meesho.orders.v1", adapter_version="v1", started_at=datetime.now(timezone.utc))


def _line(tenant: uuid.UUID, run: uuid.UUID, *, day: date, sku: str, gross: int, fee: int, marketplace: str = "MEESHO", statuses: bool = True) -> uuid.UUID:
    from calc_engine.repositories.manual_adjustment_repo import insert_adjustment
    from data_foundation.repositories.sales_line_repo import insert_sales_line
    from data_foundation.repositories.tenant_context import tenant_scope

    lid = insert_sales_line(tenant, ingestion_run_id=run, marketplace=marketplace,
                            canonical_fields={"order_ref": f"O-{uuid.uuid4().hex[:8]}", "quantity": 2, "gross_item_amount": gross, "taxable_amount": gross,
                                              "order_date": day, "return_status": "NOT_RETURNED", "sku": sku},
                            source_row_number=1, source_row_json={}, confidence="PROVISIONAL")
    with tenant_scope(tenant) as conn:
        conn.execute(text(
            "INSERT INTO line_component (id, tenant_id, sales_line_id, settlement_line_id, component_kind, component_code, source_side, amount, tax_amount, rate_pct,"
            " source_column, is_verified, note) VALUES (:id, :t, :l, NULL, 'FEE', 'COMMISSION', 'INVOICE', :a, NULL, NULL, 'synthetic', false, NULL)"),
            {"id": str(uuid.uuid4()), "t": str(tenant), "l": str(lid), "a": fee})
    if statuses:
        for field, value in (("cancellation_state_override", "NOT_CANCELLED"), ("rto_status_override", "NOT_RTO")):
            insert_adjustment(tenant, target_type="LINE", target_ref=str(lid), field=field, value=value, created_by=uuid.uuid4(), created_at=datetime.now(timezone.utc))
    return lid


def _cogs(tenant: uuid.UUID, sku: str, paise: int) -> None:
    from calc_engine.repositories.manual_adjustment_repo import insert_adjustment

    insert_adjustment(tenant, target_type="SKU", target_ref=sku, field="cogs_per_unit", value=paise, created_by=uuid.uuid4(), created_at=datetime(2026, 1, 1, tzinfo=timezone.utc))


def plan(steps: list[dict], periods: list[PeriodRef] = [SEP], intent: str = "METRIC_BY_DIMENSION") -> str:
    return json.dumps({"plan_version": "1", "intent": intent, "limit": 50, "steps": steps,
                       "periods": [{"start": p.start.isoformat(), "end": p.end.isoformat(), "as_of_date": p.as_of_date.isoformat()} for p in periods]})


def ask(tenant: uuid.UUID, provider: MockPlannerProvider, periods: list[PeriodRef] = [SEP], cache=None):  # noqa: B006
    return answer_financial_query(tenant, requested_by=uuid.uuid4(), question="q", periods=periods, provider=provider, cache=cache or InMemoryEvidenceCache())


def seeded_tenant() -> uuid.UUID:
    t = uuid.uuid4()
    run = _file_and_run(t)
    for i, (day, sku, gross, fee) in enumerate([(date(2026, 9, 5), "A", 30_000, 3_000), (date(2026, 9, 12), "A", 20_000, 2_000), (date(2026, 9, 20), "B", 50_000, 5_000)]):
        _line(t, run, day=day, sku=sku, gross=gross, fee=fee)
    _line(t, run, day=date(2026, 9, 25), sku="B", gross=10_000, fee=0, marketplace="AMAZON", statuses=False)  # Amazon: no cancellation/RTO status
    _cogs(t, "A", 4_000)
    _cogs(t, "B", 6_000)
    return t


def _direct_pnl(t: uuid.UUID, period: PeriodRef = SEP):
    out = cfo_actions.compute_period_pnl_for_tenant(t, cfo_actions.PeriodPnlForTenantRequest(
        period_start=period.start, period_end=period.end, as_of_date=period.as_of_date, recognition_state=RecognitionState.RECOGNISED, fee_component_codes=FEES,
        forward_logistics_codes=frozenset({"LOGISTICS_FEE", "SHIPPING_CHARGE"}), reverse_logistics_codes=frozenset({"RETURN_SHIPPING_FEE"}),
        non_refunded_fee_codes=frozenset(), requested_by=uuid.uuid4()))
    assert out.pnl is not None
    return out.pnl


def test_a_mixed_book_shows_the_meesho_result_independently_and_labels_the_total_partial() -> None:
    """The default 95% threshold, applied per marketplace: Meesho qualifies, Amazon (no cancellation/RTO status) does not."""
    t = seeded_tenant()
    direct = _direct_pnl(t)
    r = ask(t, MockPlannerProvider([plan([{"op": "metric", "params": {"metric": "NET_REALIZED_REVENUE"}}, {"op": "metric", "params": {"metric": "CONTRIBUTION_PROFIT"}}])]))
    assert isinstance(r, PlannerAnswer), r
    total = {f.metric_id: f for f in r.packet.figures if not f.dimension_keys}
    assert total["NET_REALIZED_REVENUE"].value_paise == direct.nrr.value_paise == 100_000  # Amazon contributes nothing it cannot support
    assert "PARTIAL_MARKETPLACE_COVERAGE" in total["NET_REALIZED_REVENUE"].labels and "PARTIAL_MARKETPLACE_COVERAGE" in r.packet.labels
    assert total["NET_REALIZED_REVENUE"].engine_result_ref and total["CONTRIBUTION_PROFIT"].engine_result_ref
    amazon = [f for f in r.packet.figures if f.metric_id == "NET_REALIZED_REVENUE" and dict(f.dimension_keys).get("marketplace") == "AMAZON"][0]
    assert amazon.status == "UNAVAILABLE" and "cancellation_state" in (amazon.unavailable_reason or "")


def test_the_packet_reports_coverage_percentages_excluded_amounts_and_reasons() -> None:
    t = seeded_tenant()
    r = ask(t, MockPlannerProvider([plan([{"op": "metric", "params": {"metric": "NET_REALIZED_REVENUE"}}])]))
    assert isinstance(r, PlannerAnswer), r
    by = {c.marketplace: c for c in r.packet.coverage}
    assert by["MEESHO"].included and by["MEESHO"].share_pct == "100.0" and by["MEESHO"].threshold_pct == "95.0"
    a = by["AMAZON"]
    assert not a.included and a.input_id == "cancellation_state" and a.share == "0/1" and a.share_pct == "0.0"
    assert a.excluded_amount_paise == 10_000 and a.excluded_line_count == 1 and a.excluded_basis == "GROSS_SALES_OF_EXCLUDED_MARKETPLACE" and a.excluded_ref
    assert "below the required 19/20" in (a.reason or "")


def _single_marketplace_tenant(n_lines: int, n_with_status: int) -> uuid.UUID:
    t = uuid.uuid4()
    run = _file_and_run(t)
    for i in range(n_lines):
        _line(t, run, day=date(2026, 9, 1 + (i % 28)), sku="A", gross=10_000, fee=0, statuses=i < n_with_status)
    return t


def test_exactly_95_percent_coverage_qualifies_and_the_missing_line_is_disclosed() -> None:
    t = _single_marketplace_tenant(20, 19)  # 19/20 = 95.0%
    r = ask(t, MockPlannerProvider([plan([{"op": "metric", "params": {"metric": "NET_REALIZED_REVENUE"}}])]))
    assert isinstance(r, PlannerAnswer), r
    f = r.packet.figures[0]
    assert f.status != "UNAVAILABLE" and f.value_paise == 19 * 10_000 and f.exclusions == (("REVENUE_STATUS_UNRESOLVED", 1),)
    c = r.packet.coverage[0]
    assert c.included and c.share == "19/20" and c.share_pct == "95.0"
    assert "PARTIAL_MARKETPLACE_COVERAGE" not in f.labels  # every marketplace in scope qualified; the one excluded line is disclosed, not hidden


def test_one_line_below_95_percent_withholds_the_marketplace_with_its_gross_sales_shown() -> None:
    t = _single_marketplace_tenant(20, 18)  # 18/20 = 90.0%
    r = ask(t, MockPlannerProvider([plan([{"op": "metric", "params": {"metric": "NET_REALIZED_REVENUE"}}])]))
    assert isinstance(r, PlannerAnswer), r
    f = r.packet.figures[0]
    assert f.status == "UNAVAILABLE" and f.value_paise is None and "90.0% against 95.0%" in (f.unavailable_reason or "")
    c = r.packet.coverage[0]
    assert not c.included and c.share_pct == "90.0" and c.excluded_amount_paise == 200_000 and c.excluded_line_count == 20
    assert len(r.packet.data_requests) == 1


def test_grouped_by_marketplace_gives_each_marketplace_its_own_answer() -> None:
    t = seeded_tenant()
    r = ask(t, MockPlannerProvider([plan([{"op": "group_by", "params": {"dimensions": ["marketplace"]}}, {"op": "metric", "params": {"metric": "NET_REALIZED_REVENUE"}}])]))
    assert isinstance(r, PlannerAnswer), r
    rows = {dict(f.dimension_keys)["marketplace"]: f for f in r.packet.figures if f.dimension_keys}
    assert rows["MEESHO"].value_paise == 100_000 and rows["AMAZON"].status == "UNAVAILABLE"


def test_a_tenant_with_no_data_is_unavailable_never_zero() -> None:
    r = ask(uuid.uuid4(), MockPlannerProvider([plan([{"op": "metric", "params": {"metric": "NET_REALIZED_REVENUE"}}])]))
    assert isinstance(r, PlannerAnswer), r
    f = r.packet.figures[0]
    assert f.status == "UNAVAILABLE" and f.value_paise is None
    assert [(c.marketplace, c.included, c.share) for c in r.packet.coverage] == [("ALL", False, "0/1")]  # nothing in scope: said so, with the reason


def test_the_planners_numbers_are_the_dashboards_numbers_when_every_marketplace_qualifies() -> None:
    t = _single_marketplace_tenant(20, 20)
    _cogs(t, "A", 4_000)
    direct = _direct_pnl(t)
    r = ask(t, MockPlannerProvider([plan([{"op": "metric", "params": {"metric": "NET_REALIZED_REVENUE"}}, {"op": "metric", "params": {"metric": "CONTRIBUTION_PROFIT"}}])]))
    assert isinstance(r, PlannerAnswer), r
    by = {f.metric_id: f for f in r.packet.figures}
    assert by["NET_REALIZED_REVENUE"].value_paise == direct.nrr.value_paise and by["CONTRIBUTION_PROFIT"].value_paise == direct.contribution_profit.value_paise


def test_gross_sales_by_marketplace_uses_the_sql_path_and_includes_amazon() -> None:
    t = seeded_tenant()
    r = ask(t, MockPlannerProvider([plan([{"op": "group_by", "params": {"dimensions": ["marketplace"]}}, {"op": "metric", "params": {"metric": "GROSS_SALES"}}])]))
    assert isinstance(r, PlannerAnswer), r
    vals = {dict(f.dimension_keys).get("marketplace", "ALL"): f.value_paise for f in r.packet.figures}
    assert vals == {"MEESHO": 100_000, "AMAZON": 10_000, "ALL": 110_000}  # gross sales exists where net revenue cannot be measured
    assert all(f.engine_result_ref for f in r.packet.figures)


def test_a_late_upload_invalidates_the_cache_and_a_repeat_hits_it() -> None:
    t = seeded_tenant()
    cache = InMemoryEvidenceCache()
    p = plan([{"op": "metric", "params": {"metric": "GROSS_SALES"}}])
    a = ask(t, MockPlannerProvider([p]), cache=cache)
    b = ask(t, MockPlannerProvider([p]), cache=cache)
    assert isinstance(a, PlannerAnswer) and isinstance(b, PlannerAnswer) and not a.packet.cached and b.packet.cached
    assert b.packet.content_json() == a.packet.content_json()
    run = _file_and_run(t)
    _line(t, run, day=date(2026, 9, 28), sku="A", gross=7_000, fee=0)
    read_model_version_repo.bump(t)  # what an ingest / adjustment does in its own transaction
    c = ask(t, MockPlannerProvider([p]), cache=cache)
    assert isinstance(c, PlannerAnswer) and not c.packet.cached
    total = c.packet.figures[-1].value_paise
    assert total == 117_000  # the new line is in the answer; the stale one was unreachable


def test_missing_cost_prices_make_profit_unavailable_with_one_request_never_zero() -> None:
    t = uuid.uuid4()
    run = _file_and_run(t)
    _line(t, run, day=date(2026, 9, 5), sku="NOCOST", gross=30_000, fee=3_000)
    r = ask(t, MockPlannerProvider([plan([{"op": "metric", "params": {"metric": "CONTRIBUTION_PROFIT"}}])]))
    assert isinstance(r, PlannerAnswer), r
    f = r.packet.figures[0]
    assert f.status == "UNAVAILABLE" and f.value_paise is None and len(r.packet.data_requests) == 1


def test_a_profit_bridge_across_two_months_reconciles_on_real_data() -> None:
    t = uuid.uuid4()
    run = _file_and_run(t)
    _cogs(t, "A", 4_000)
    _line(t, run, day=date(2026, 9, 5), sku="A", gross=40_000, fee=4_000)
    _line(t, run, day=date(2026, 9, 6), sku="A", gross=40_000, fee=4_000)
    _line(t, run, day=date(2026, 10, 5), sku="A", gross=30_000, fee=6_000)
    r = ask(t, MockPlannerProvider([plan([{"op": "metric", "params": {"metric": "PROFIT_BRIDGE"}}, {"op": "compare", "params": {"kind": "period_over_period", "metric": "PROFIT_BRIDGE"}}],
                                         periods=[SEP, OCT], intent="PROFIT_BRIDGE")]), periods=[SEP, OCT])
    assert isinstance(r, PlannerAnswer), r
    b = r.packet.bridge
    assert b is not None and b.reconciles and b.other_paise == 0
    assert sum(d.delta_paise for d in b.drivers) == b.delta_paise


def test_tenants_are_isolated_in_stats_results_and_cache() -> None:
    a, b = seeded_tenant(), uuid.uuid4()
    cache = InMemoryEvidenceCache()
    p = plan([{"op": "metric", "params": {"metric": "GROSS_SALES"}}])
    ra = ask(a, MockPlannerProvider([p]), cache=cache)
    rb = ask(b, MockPlannerProvider([p]), cache=cache)
    assert isinstance(ra, PlannerAnswer) and ra.packet.figures[0].value_paise == 110_000
    assert isinstance(rb, PlannerAnswer) and not rb.packet.cached and rb.packet.figures[0].status == "UNAVAILABLE"  # nothing leaks across


def test_a_sku_filter_for_another_tenants_sku_is_an_empty_scope() -> None:
    a = seeded_tenant()
    b = uuid.uuid4()
    run = _file_and_run(b)
    _line(b, run, day=date(2026, 9, 5), sku="THEIRS", gross=99_000, fee=0)
    p = plan([{"op": "filter", "params": {"dimension": "sku", "op": "eq", "value": "THEIRS"}}, {"op": "metric", "params": {"metric": "GROSS_SALES"}}])
    r = ask(a, MockPlannerProvider([p]))
    assert isinstance(r, PlannerAnswer) and r.packet.figures[0].status == "UNAVAILABLE"


def test_the_planner_is_off_without_a_configured_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CFO_PLANNER_MODEL", raising=False)
    r = answer_financial_query(uuid.uuid4(), requested_by=uuid.uuid4(), question="q", periods=[SEP])
    assert isinstance(r, PlannerRefusal) and r.code == "PLANNER_OFF"
