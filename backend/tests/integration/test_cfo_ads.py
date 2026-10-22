"""Advertising through the planner and the routes, real Postgres (docs/specs/cfo-phase3-scope.md AC-B2…B7). Golden values are hand-computed.

Book: four Meesho lines (gross 50,000 paise, quantity 2, cost 4,000 per unit, fee 5,000) dated 3–6 Sep 2026 -> Net Realized Revenue 200,000."""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timezone
from fractions import Fraction
from typing import Any

import pytest
from sqlalchemy import text

from calc_engine.repositories import ad_report_repo
from calc_engine.repositories.manual_adjustment_repo import insert_adjustment
from cfo.planner.cache_store import InMemoryEvidenceCache
from cfo.planner.pipeline import MockPlannerProvider, PlannerAnswer
from cfo.planner.plan import PeriodRef

from backend.services.cfo_query import answer_financial_query
from tests.integration.test_cfo_expense_ledger import _register_owner, app_client, fake_clerk, _seed_zero_cap  # noqa: F401
from tests.integration.test_cfo_query_planner import SEP, _cogs, _file_and_run, _line, plan

USER = uuid.uuid4()


def book() -> tuple[uuid.UUID, uuid.UUID]:
    t = uuid.uuid4()
    run = _file_and_run(t)
    for d in (3, 4, 5, 6):
        _line(t, run, day=date(2026, 9, d), sku="A", gross=50_000, fee=5_000)
    _cogs(t, "A", 4_000)
    return t, run


def ad_lines(t: uuid.UUID, run: uuid.UUID, *, marketplace: str = "MEESHO", days: range = range(1, 31), spend: int = 1_000, sales: int | None = 5_000) -> None:
    with ad_conn(t) as conn:
        for d in days:
            conn.execute(text(
                "INSERT INTO ad_report_line (tenant_id, ingestion_run_id, marketplace, campaign_ref, report_date, spend, attributed_sales, source_row_number, source_row_json, confidence) "
                "VALUES (:t, :r, :m, 'C', :d, :s, :a, :n, '{}'::jsonb, 'PROVISIONAL')"),
                {"t": str(t), "r": str(run), "m": marketplace, "d": date(2026, 9, d), "s": spend, "a": sales, "n": d})


def ad_conn(t: uuid.UUID):
    from cfo.repositories.tenant_context import tenant_scope

    return tenant_scope(t)


def pool(t: uuid.UUID, amount: int, marketplace: str | None = "MEESHO") -> None:
    value: dict[str, Any] = {"amount_paise": amount}
    if marketplace:
        value["marketplace"] = marketplace
    insert_adjustment(t, target_type="PERIOD", target_ref="2026-09", field="expense.advertising", value=value, created_by=USER, created_at=datetime.now(timezone.utc))


def ask(t: uuid.UUID, steps: list[dict]) -> Any:
    r = answer_financial_query(t, requested_by=USER, question="q", periods=[SEP], provider=MockPlannerProvider([plan(steps)]), cache=InMemoryEvidenceCache())
    assert isinstance(r, PlannerAnswer), r
    return r.packet


def ads_metrics(t: uuid.UUID, by_marketplace: bool = False) -> Any:
    steps = ([{"op": "group_by", "params": {"dimensions": ["marketplace"]}}] if by_marketplace else []) + [{"op": "metric", "params": {"metric": m}} for m in ("AD_SPEND", "ROAS", "ACOS", "TACOS")]
    return ask(t, steps)


def by_metric(packet: Any, marketplace: str | None = None) -> dict[str, Any]:
    out = {}
    for f in packet.figures:
        keys = dict(f.dimension_keys)
        if keys.get("marketplace") == marketplace:
            out[f.metric_id] = f
    return out


def cp(t: uuid.UUID) -> Any:
    return by_metric(ask(t, [{"op": "metric", "params": {"metric": "CONTRIBUTION_PROFIT"}}]))["CONTRIBUTION_PROFIT"]


# ------------------------------------------------------------------------------------------------ report as the source
def test_report_spend_gives_exact_ratios_with_refs_and_the_status_label() -> None:
    t, run = book()
    ad_lines(t, run)
    m = by_metric(ads_metrics(t))
    assert m["AD_SPEND"].value_paise == 30_000 and "AD_STATUS_KNOWN_SPEND" in m["AD_SPEND"].labels
    assert m["ROAS"].value_fraction == "5/1" and m["ACOS"].value_fraction == "1/5" and m["TACOS"].value_fraction == "3/20"  # 150,000/30,000 · 30,000/150,000 · 30,000/200,000
    assert all(f.engine_result_ref for f in m.values())


def test_contribution_profit_subtracts_report_spend_only_when_the_report_owns_advertising() -> None:
    t, run = book()
    base = cp(t)
    assert base.status != "UNAVAILABLE" and base.value_paise is not None
    ad_lines(t, run)
    with_ads = cp(t)
    assert with_ads.value_paise == base.value_paise - 30_000 and "ADVERTISING_FROM_REPORT" in with_ads.labels  # exact paisa


def test_a_report_that_covers_only_part_of_the_period_is_a_named_gap_not_a_total() -> None:
    t, run = book()
    ad_lines(t, run, days=range(1, 16))
    m = by_metric(ads_metrics(t))
    assert m["AD_SPEND"].status == "UNAVAILABLE" and "does not cover the whole period" in (m["AD_SPEND"].unavailable_reason or "")
    assert len(ads_metrics(t).data_requests) >= 1


def test_no_evidence_at_all_is_unavailable_never_zero() -> None:
    t, _ = book()
    p = ads_metrics(t)
    f = by_metric(p)["AD_SPEND"]
    assert f.status == "UNAVAILABLE" and f.value_paise is None and "ad_source" in (f.unavailable_reason or "")


def test_a_no_advertising_statement_is_a_verified_zero_with_roas_undefined() -> None:
    t, _ = book()
    ad_report_repo.declare_no_ads(t, "MEESHO", date(2026, 9, 1), date(2026, 9, 30), USER)
    m = by_metric(ads_metrics(t))
    assert m["AD_SPEND"].value_paise == 0 and "AD_STATUS_VERIFIED_ZERO" in m["AD_SPEND"].labels
    assert m["TACOS"].value_fraction == "0/1" and m["ROAS"].status == "UNAVAILABLE"


def test_reports_without_attributed_sales_leave_roas_and_acos_unavailable_but_spend_known() -> None:
    t, run = book()
    ad_lines(t, run, sales=None)
    m = by_metric(ads_metrics(t))
    assert m["AD_SPEND"].value_paise == 30_000 and m["ROAS"].status == "UNAVAILABLE" and m["ACOS"].status == "UNAVAILABLE" and m["TACOS"].value_fraction == "3/20"


# ------------------------------------------------------------------------------------------------ two sources (V-DUP-2)
def test_a_report_and_a_hand_entered_cost_for_the_same_dates_are_a_conflict_until_the_seller_chooses() -> None:
    t, run = book()
    ad_lines(t, run)
    pool(t, 20_000)
    p = ads_metrics(t)
    f = by_metric(p)["AD_SPEND"]
    assert f.status == "UNAVAILABLE" and "choose which one is right" in (f.unavailable_reason or "") and len(p.data_requests) >= 1
    legacy_cp = cp(t)  # the legacy pool keeps working as before; the report is NOT added on top
    assert any(lbl.startswith("ADVERTISING_SOURCE_CONFLICT_MEESHO") for lbl in legacy_cp.labels)

    ad_report_repo.choose_owner(t, "MEESHO", date(2026, 9, 1), date(2026, 9, 30), "REPORT", USER)
    m = by_metric(ads_metrics(t))
    assert m["AD_SPEND"].value_paise == 30_000
    chosen_report = cp(t)
    ad_report_repo.choose_owner(t, "MEESHO", date(2026, 9, 1), date(2026, 9, 30), "POOL", USER)  # a later choice supersedes
    m2 = by_metric(ads_metrics(t))
    assert m2["AD_SPEND"].value_paise == 20_000
    chosen_pool = cp(t)
    assert chosen_report.value_paise == chosen_pool.value_paise - 10_000  # 30,000 from the report vs 20,000 from the pool: exactly one of them is counted each time


def test_a_pool_alone_is_a_source_and_an_account_level_pool_cannot_be_split_by_marketplace() -> None:
    t, _ = book()
    pool(t, 20_000, marketplace="MEESHO")
    # a hand-entered cost without a covering statement is a pool covering its period: known spend, no sales -> ROAS unavailable
    m = by_metric(ads_metrics(t))
    assert m["AD_SPEND"].value_paise == 20_000 and m["ROAS"].status == "UNAVAILABLE"
    u, _ = book()
    pool(u, 20_000, marketplace=None)
    f = by_metric(ads_metrics(u))["AD_SPEND"]
    assert f.status == "UNAVAILABLE" and "whole account" in (f.unavailable_reason or "")


def test_a_declaration_that_contradicts_report_lines_is_refused() -> None:
    t, run = book()
    ad_lines(t, run)
    with pytest.raises(ad_report_repo.AdRuleError, match="contradict"):
        ad_report_repo.declare_no_ads(t, "MEESHO", date(2026, 9, 1), date(2026, 9, 30), USER)


def test_advertising_cannot_be_narrowed_to_a_sku_and_other_marketplaces_do_not_leak_in() -> None:
    t, run = book()
    ad_lines(t, run)
    ad_lines(t, run, marketplace="AMAZON", spend=7_000)
    narrowed = ask(t, [{"op": "filter", "params": {"dimension": "sku", "op": "eq", "value": "A"}}, {"op": "metric", "params": {"metric": "AD_SPEND"}}])
    assert narrowed.figures[0].status == "UNAVAILABLE" and "SKU" in (narrowed.figures[0].unavailable_reason or "")
    one = ask(t, [{"op": "filter", "params": {"dimension": "marketplace", "op": "eq", "value": "MEESHO"}}, {"op": "metric", "params": {"metric": "AD_SPEND"}}])
    assert one.figures[0].value_paise == 30_000


def test_by_marketplace_view_names_each_marketplace_and_the_total_excludes_the_unknown_one() -> None:
    t, run = book()
    ad_lines(t, run)
    # Amazon sales exist but no advertising evidence: it must be named as excluded, never summed as zero
    from tests.integration.test_cfo_query_planner import _line as line
    line(t, run, day=date(2026, 9, 7), sku="A", gross=10_000, fee=0, marketplace="AMAZON", statuses=False)
    p = ads_metrics(t, by_marketplace=True)
    total = by_metric(p)["AD_SPEND"]
    assert total.value_paise == 30_000 and "PARTIAL_MARKETPLACE_COVERAGE" in total.labels  # Amazon has sales but no advertising evidence: excluded by the per-marketplace coverage rule, named, never summed as zero
    assert by_metric(p, "MEESHO")["AD_SPEND"].value_paise == 30_000 and by_metric(p, "AMAZON")["AD_SPEND"].status == "UNAVAILABLE"


def test_ads_are_tenant_isolated() -> None:
    a, run = book()
    ad_lines(a, run)
    b, _ = book()
    assert by_metric(ads_metrics(b))["AD_SPEND"].status == "UNAVAILABLE"
    assert ad_report_repo.spend_in_period(b, "MEESHO", date(2026, 9, 1), date(2026, 9, 30)) is None


# ------------------------------------------------------------------------------------------------ routes
def test_routes_declare_no_ads_and_record_an_owner_choice_with_gates(app_client, fake_clerk, two_tenants, migrate_engine):
    tenant_a, _ = two_tenants
    h = _register_owner(fake_clerk, tenant_a)
    body = {"marketplace": "meesho", "period_start": "2026-09-01", "period_end": "2026-09-30"}
    assert app_client.post("/api/v1/cfo/ads/declarations/no-ads", json=body, headers=h).status_code == 200
    assert app_client.post("/api/v1/cfo/ads/owner", json={**body, "owner": "report"}, headers=h).status_code == 200
    assert app_client.post("/api/v1/cfo/ads/owner", json={**body, "owner": "WHOEVER"}, headers=h).status_code == 400
    assert app_client.post("/api/v1/cfo/ads/declarations/no-ads", json={**body, "marketplace": "EBAY"}, headers=h).status_code == 400
    assert app_client.post("/api/v1/cfo/ads/declarations/no-ads", json={**body, "extra": 1}, headers=h).status_code == 422
    from tests.integration.test_cfo_pnl import _register_partner_with_permissions
    from backend.auth.permissions import AGENT_CFO

    partner = _register_partner_with_permissions(fake_clerk, tenant_a, permissions={AGENT_CFO: True})
    assert app_client.post("/api/v1/cfo/ads/owner", json={**body, "owner": "REPORT"}, headers=partner).status_code == 403
