"""CFO 2.0 dashboard read routes, real Postgres (docs/specs/cfo-dashboard-implementation.md §3–4, AC-DI2/DI3/DI5/DI6/DI10).

Every figure comes from the same planner pipeline the CEO uses, so the same-truth test compares the dashboard to the CEO's own evidence packet."""

from __future__ import annotations

import uuid
from datetime import date

from calc_engine.repositories import cost_owner_repo
from cfo.planner.pipeline import MockPlannerProvider, PlannerAnswer

from backend.services.cfo_query import answer_financial_query
from tests.integration.test_cfo_ads import ad_lines, book, cp, pool
from tests.integration.test_cfo_expense_ledger import _register_owner, app_client, fake_clerk  # noqa: F401
from tests.integration.test_cfo_query_planner import SEP, plan

Q = {"period_start": "2026-09-01", "period_end": "2026-09-30", "as_of_date": "2026-10-01"}


def _seed(tenant: uuid.UUID) -> uuid.UUID:
    from tests.integration.test_cfo_query_planner import _cogs, _file_and_run, _line

    run = _file_and_run(tenant)
    for d in (3, 4, 5, 6):
        _line(tenant, run, day=date(2026, 9, d), sku="A", gross=50_000, fee=5_000)
    _line(tenant, run, day=date(2026, 9, 7), sku="B", gross=20_000, fee=2_000)
    _cogs(tenant, "A", 4_000)
    _cogs(tenant, "B", 3_000)
    return run


def get(client, headers, path, **params):  # noqa: ANN001, ANN201
    return client.get(f"/api/v1/cfo{path}", params={**Q, **params}, headers=headers)


def test_overview_equals_the_ceo_evidence_packet_for_the_same_period_and_never_shows_zero_for_missing(app_client, fake_clerk, two_tenants):  # noqa: F811
    a, _ = two_tenants
    _seed(a)
    h = _register_owner(fake_clerk, a)
    body = get(app_client, h, "/overview").json()
    assert body["status"] == "ANSWERED" and len(body["kpis"]) == 6 and body["canAdjust"] is True
    from backend.auth.permissions import AGENT_CFO
    from tests.integration.test_cfo_uploads_jobs import partner_with

    assert get(app_client, partner_with(fake_clerk, a, AGENT_CFO), "/overview").json()["canAdjust"] is False  # can read, cannot change
    by = {k["label"]: k for k in body["kpis"]}
    ceo = answer_financial_query(a, requested_by=uuid.uuid4(), question="q", periods=[SEP],
                                 provider=MockPlannerProvider([plan([{"op": "metric", "params": {"metric": "CONTRIBUTION_PROFIT"}}])]))
    assert isinstance(ceo, PlannerAnswer)
    f = ceo.packet.figures[0]
    from backend.ceo.figure_format import format_paise

    assert f.value_paise is not None and by["Contribution Profit"]["valueDisplay"] == format_paise(f.value_paise)  # AC-DI5: one truth (each run mints its own ref; the value is what must match)
    assert by["Contribution Profit"]["engineResultRef"] and by["Contribution Profit"]["formulaVersion"] == f.formula_version
    assert by["Contribution Profit"]["valueDisplay"].startswith("₹") and by["Contribution Profit"]["completeness"] in ("COMPLETE", "PROVISIONAL", "PARTIAL")
    # no expense data and no declaration: operating profit is UNAVAILABLE with a reason, never 0
    op = by["Operating Profit"]
    assert op["valueDisplay"] is None and op["completeness"] == "UNAVAILABLE" and op["unavailableReason"] and body["operatingProfitState"] == "UNAVAILABLE"
    # GST stays unconfirmed: the GST / tax assets figure is unavailable with that reason
    gst = by["GST / tax assets"]
    assert gst["valueDisplay"] is None and "not confirmed" in gst["unavailableReason"]
    assert all(k["register"] in ("VERIFIED", "DERIVED", "MANUAL", "ESTIMATE", "UNAVAILABLE") for k in body["kpis"])


def test_a_cost_conflict_is_labelled_on_the_figure_in_words(app_client, fake_clerk, two_tenants):  # noqa: F811
    a, _ = two_tenants
    run = _seed(a)
    ad_lines(a, run)
    pool(a, 20_000)
    h = _register_owner(fake_clerk, a)
    note = " ".join(k for kpi in get(app_client, h, "/overview").json()["kpis"] for k in kpi["statusNotes"])
    assert "more than one place" in note
    cost_owner_repo.choose_owner(a, "ADVERTISING", "MEESHO", date(2026, 9, 1), date(2026, 9, 30), "REPORT", uuid.uuid4())
    after = " ".join(k for kpi in get(app_client, h, "/overview").json()["kpis"] for k in kpi["statusNotes"])
    assert "more than one place" not in after and cp(a).value_paise is not None


def test_marketplace_and_sku_tables_are_server_sorted_paged_and_carry_status_not_numbers_to_format(app_client, fake_clerk, two_tenants):  # noqa: F811
    a, _ = two_tenants
    _seed(a)
    h = _register_owner(fake_clerk, a)
    m = get(app_client, h, "/profitability/marketplaces").json()
    rows = {r["key"]: r for r in m["items"]}
    assert set(rows) == {"AMAZON", "FLIPKART", "MEESHO"} and set(rows["MEESHO"]["grossSales"]) == {"display", "status"}
    assert rows["MEESHO"]["grossSales"]["display"] is not None
    assert rows["AMAZON"]["grossSales"] == {"display": None, "status": "UNAVAILABLE"}  # no Amazon data: shown as unavailable, never as zero
    s = get(app_client, h, "/profitability/skus", sort="grossSales", dir="desc").json()
    assert [r["key"] for r in s["items"]] == ["A", "B"] and s["total"] == 2 and s["pageCount"] == 1
    asc = get(app_client, h, "/profitability/skus", sort="grossSales", dir="asc").json()
    assert [r["key"] for r in asc["items"]] == ["B", "A"]
    one = get(app_client, h, "/profitability/skus", sort="grossSales", dir="desc", page_size=1, page=2).json()
    assert [r["key"] for r in one["items"]] == ["B"] and one["pageCount"] == 2
    assert [r["key"] for r in get(app_client, h, "/profitability/skus", sku="b").json()["items"]] == ["B"]
    assert [r["key"] for r in get(app_client, h, "/profitability/marketplaces", marketplace="AMAZON").json()["items"]] == ["AMAZON"]


def test_trend_has_a_point_per_month_with_the_servers_display_string(app_client, fake_clerk, two_tenants):  # noqa: F811
    a, _ = two_tenants
    _seed(a)
    h = _register_owner(fake_clerk, a)
    t = get(app_client, h, "/profitability/trend").json()
    assert t["status"] == "ANSWERED" and len(t["points"]) >= 1 and all("display" in p and "status" in p for p in t["points"])


def test_bad_filters_are_refused_before_any_query(app_client, fake_clerk, two_tenants):  # noqa: F811
    a, _ = two_tenants
    h = _register_owner(fake_clerk, a)
    assert get(app_client, h, "/overview", marketplace="EBAY").status_code == 400
    assert get(app_client, h, "/overview", period_start="2026-10-01", period_end="2026-09-01").status_code == 400
    assert get(app_client, h, "/overview", period_start="2024-01-01", period_end="2026-09-30").status_code == 400
    assert app_client.get("/api/v1/cfo/overview", params={"period_start": "nope", "period_end": "2026-09-30"}, headers=h).status_code == 422
    assert get(app_client, h, "/leak/findings", status="BOGUS").status_code == 400


def test_dashboard_routes_need_the_cfo_key_and_see_only_their_own_tenant(app_client, fake_clerk, two_tenants):  # noqa: F811
    from backend.auth.permissions import AGENT_CFO  # noqa: F401
    from tests.integration.test_cfo_uploads_jobs import partner_with

    a, b = two_tenants
    _seed(a)
    nokey = partner_with(fake_clerk, a)  # no grants
    for path in ("/overview", "/profitability/marketplaces", "/profitability/skus", "/profitability/trend", "/cash/expected-receipts", "/cash/payables", "/leak/findings", "/intelligence/alerts"):
        assert get(app_client, nokey, path).status_code == 403, path
    other = _register_owner(fake_clerk, b)
    assert get(app_client, other, "/profitability/skus").json()["items"] == []  # another tenant's SKUs never appear
    assert get(app_client, other, "/leak/findings").json()["items"] == []


def test_cash_payables_leaks_and_alerts_return_their_shapes_without_inventing_data(app_client, fake_clerk, two_tenants):  # noqa: F811
    a, _ = two_tenants
    _seed(a)
    h = _register_owner(fake_clerk, a)
    c = get(app_client, h, "/cash/expected-receipts").json()
    assert c["status"] == "ANSWERED" and "not your bank balance" in c["note"]
    assert all(f["completeness"] in ("ESTIMATED", "UNAVAILABLE", "PROVISIONAL", "PARTIAL") for f in c["figures"])  # a forecast is never drawn as a confirmed actual
    assert get(app_client, h, "/cash/payables").json()["items"] == []
    leaks = get(app_client, h, "/leak/findings").json()
    assert leaks["items"] == [] and "never files a claim" in leaks["note"]
    assert get(app_client, h, "/intelligence/alerts").json()["items"] == []


def test_the_profit_bridge_needs_a_comparison_period_and_explains_a_missing_one(app_client, fake_clerk, two_tenants):  # noqa: F811
    a, _ = two_tenants
    _seed(a)
    h = _register_owner(fake_clerk, a)
    r = app_client.get("/api/v1/cfo/profitability/bridge", params={**Q, "compare_start": "2026-10-01", "compare_end": "2026-10-31"}, headers=h)
    assert r.status_code == 200 and r.json()["status"] in ("ANSWERED", "REFUSED")
    bad = app_client.get("/api/v1/cfo/profitability/bridge", params={**Q, "compare_start": "2026-10-31", "compare_end": "2026-10-01"}, headers=h)
    assert bad.status_code == 400


def test_payables_can_be_entered_in_rupees_converted_once_on_the_server_and_shown_as_a_display_string(app_client, fake_clerk, two_tenants):  # noqa: F811
    a, _ = two_tenants
    h = _register_owner(fake_clerk, a)
    ok = app_client.post("/api/v1/cfo/payables", json={"amount_rupees": "12500.50", "due_date": "2026-10-30", "supplier_ref": "S1"}, headers=h)
    assert ok.status_code == 200, ok.text
    listed = app_client.get("/api/v1/cfo/payables", headers=h).json()["payables"]
    assert listed[0]["amountPaise"] == 1_250_050
    dash = app_client.get("/api/v1/cfo/cash/payables", headers=h).json()["items"]
    assert dash[0]["amount"]["display"] == "\u20b912,500.50" and dash[0]["supplierRef"] == "S1"
    for bad in ({"amount_rupees": "12,500"}, {"amount_rupees": "1.234"}, {"amount_rupees": "-5"}, {"amount_rupees": "1e3"}, {"amount_rupees": "5", "amount_paise": 500}, {}):
        assert app_client.post("/api/v1/cfo/payables", json=bad, headers=h).status_code == 400, bad
    assert app_client.post("/api/v1/cfo/payables", json={"amount_paise": 5000}, headers=h).status_code == 200  # the paise form still works


def test_ledger_entries_carry_display_strings_for_the_dashboard(app_client, fake_clerk, two_tenants):  # noqa: F811
    a, _ = two_tenants
    h = _register_owner(fake_clerk, a)
    app_client.post("/api/v1/cfo/ledger/entries", json={"entries": [{"entry_date": "2026-09-05", "amount_paise": 118_000, "category": "Software", "gst_amount_paise": 18_000}]}, headers=h)
    e = app_client.get("/api/v1/cfo/ledger/entries", headers=h).json()["entries"][0]
    assert e["amountDisplay"] == "\u20b91,180.00" and e["gstAmountDisplay"] == "\u20b9180.00" and e["gstTreatment"] is None and e["gstTreatmentUnconfirmed"] is True


def test_sku_csv_export_is_the_same_query_server_side_and_neutralises_formula_cells(app_client, fake_clerk, two_tenants):  # noqa: F811
    from backend.services.cfo_dashboard import csv_text

    a, _ = two_tenants
    _seed(a)
    h = _register_owner(fake_clerk, a)
    r = get(app_client, h, "/profitability/skus", export="csv", sort="grossSales", dir="desc")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv") and "attachment" in r.headers["content-disposition"]
    lines = r.text.strip().split("\r\n")
    assert lines[0] == '"SKU","Gross Sales","Net Realized Revenue","Contribution Profit"' and lines[1].startswith('"A"') and lines[2].startswith('"B"')
    assert get(app_client, h, "/profitability/skus", export="xlsx").status_code == 400
    assert csv_text(["x"], [["=1+1"], ["+cmd"], ["-5"], ["@SUM(A1)"], [None], ['a"b']]) == '"x"\r\n"\'=1+1"\r\n"\'+cmd"\r\n"\'-5"\r\n"\'@SUM(A1)"\r\n"Unavailable"\r\n"a""b"\r\n'


def test_access_route_reports_whether_the_member_may_change_things(app_client, fake_clerk, two_tenants):  # noqa: F811
    from backend.auth.permissions import AGENT_CFO
    from tests.integration.test_cfo_uploads_jobs import partner_with

    a, _ = two_tenants
    assert app_client.get("/api/v1/cfo/access", headers=_register_owner(fake_clerk, a)).json() == {"canAdjust": True}
    assert app_client.get("/api/v1/cfo/access", headers=partner_with(fake_clerk, a, AGENT_CFO)).json() == {"canAdjust": False}
    assert app_client.get("/api/v1/cfo/access", headers=partner_with(fake_clerk, a)).status_code == 403


def test_health_band_classifies_figures_for_exactly_this_period_and_names_why_when_it_cannot(app_client, fake_clerk, two_tenants):  # noqa: F811
    a, b = two_tenants
    _seed(a)
    h = _register_owner(fake_clerk, a)
    r = get(app_client, h, "/overview/health").json()
    assert r["status"] == "ANSWERED"
    assert (r["overallBand"] in ("Good", "Watch", "At risk") and r["perMetric"]) or r["unavailableReason"]  # a band, or the reason there is none - never a made-up GOOD
    assert {f["label"] for f in r["figures"]} <= {"Contribution margin", "Marketplace fees against revenue", "Return rate"}
    empty = get(app_client, _register_owner(fake_clerk, b), "/overview/health").json()
    assert empty["overallBand"] is None and empty["unavailableReason"]


def test_expense_summary_lists_categories_and_the_owner_account_is_separate_and_gated(app_client, fake_clerk, two_tenants):  # noqa: F811
    from backend.auth.permissions import AGENT_CFO
    from tests.integration.test_cfo_uploads_jobs import partner_with

    a, _ = two_tenants
    _seed(a)
    h = _register_owner(fake_clerk, a)
    app_client.post("/api/v1/cfo/ledger/entries", json={"entries": [{"entry_date": "2026-09-05", "amount_paise": 50_000, "category": "Software"}, {"entry_date": "2026-09-06", "amount_paise": 90_000, "category": "Owner Draw"}]}, headers=h)
    app_client.post("/api/v1/cfo/ledger/classes", json={"class": "OVERHEAD", "category": "Software"}, headers=h)
    app_client.post("/api/v1/cfo/ledger/classes", json={"class": "OWNER_DRAWING", "category": "Owner Draw"}, headers=h)
    biz = get(app_client, h, "/expenses/summary").json()
    cats = {i["category"]: i["amount"]["display"] for i in biz["items"]}
    assert cats.get("Software") == "\u20b9500.00" and "Owner Draw" not in cats  # drawings are not a business expense
    own = get(app_client, h, "/expenses/owner-account").json()
    assert {i["category"]: i["amount"]["display"] for i in own["items"]} == {"Owner Draw": "\u20b9900.00"} and "no profit figure" in own["note"]
    reader = partner_with(fake_clerk, a, AGENT_CFO)
    assert get(app_client, reader, "/expenses/summary").status_code == 200
    assert get(app_client, reader, "/expenses/owner-account").status_code == 403  # AC-DI10


def test_cost_breakdown_and_goal_show_figures_with_their_own_provenance(app_client, fake_clerk, two_tenants):  # noqa: F811
    a, _ = two_tenants
    _seed(a)
    h = _register_owner(fake_clerk, a)
    cb = get(app_client, h, "/profitability/cost-breakdown").json()
    labels = [f["label"] for f in cb["figures"]]
    assert labels[0] == "Net Realized Revenue" and labels[-1] == "Contribution Profit"
    assert all(f["engineResultRef"] or f["completeness"] == "UNAVAILABLE" for f in cb["figures"])
    app_client.put("/api/v1/cfo/seller-goal", json={"target_margin_pct": "25", "priority_category": None, "note": None}, headers=h)
    g = get(app_client, h, "/intelligence/goal").json()
    assert g["goal"]["targetMarginPct"] == "25" and g["current"]["label"] == "Contribution margin now"
