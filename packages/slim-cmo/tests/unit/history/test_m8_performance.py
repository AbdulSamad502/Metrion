"""CMO 3.0 M8, pure parts: reading a performance report and the deterministic metrics / grounded insights. No I/O, no model."""

from __future__ import annotations

from datetime import date

import pytest

from slim_cmo.history import metrics as mx
from slim_cmo.history import report_import as ri

TODAY = date(2026, 10, 31)
HEAD = ["Date", "SKU", "Impressions", "Clicks", "Orders", "Units Sold", "Sales"]


def v(rows, head=HEAD, mp="AMAZON"):
    return ri.validate([head, *rows], mp, TODAY)


# ------------------------------------------------------------------------------------------------ the report
def test_a_valid_report_keeps_only_what_it_carries():
    r = v([["2026-10-01", "AQ-1", "1,000", "50", "5", "6", "₹1,234.50"], ["01/10/2026", "AQ-2", "200", "-", "", "N/A", "10"]])
    assert r["ok"] and r["rowCount"] == 2 and r["period"] == (date(2026, 10, 1), date(2026, 10, 1))
    a, b = r["lines"]
    assert (a["impressions"], a["clicks"], a["orders"], a["units"], a["sales"]) == (1000, 50, 5, 6, 123450)
    assert (b["impressions"], b["clicks"], b["orders"], b["units"], b["sales"]) == (200, None, None, None, 1000)  # blank / "-" / N/A are MISSING, never zero


def test_a_report_may_carry_only_some_metrics_and_a_rate_column_is_not_stored():
    r = ri.validate([["day", "seller sku", "clicks", "CTR"], ["2026-10-01", "A", "5", "2.5%"]], "FLIPKART", TODAY)
    assert r["ok"] and r["metrics"] == ["clicks"] and r["lines"][0]["impressions"] is None
    assert any("CTR" in w and "Not stored" in w for w in r["warnings"])


@pytest.mark.parametrize("head,row,fragment", [
    (["Date", "Orders"], ["2026-10-01", "1"], "SKU column"),
    (["Date", "SKU"], ["2026-10-01", "A"], "none of the supported metric columns"),
    (["Date", "SKU", "Page views"], ["2026-10-01", "A", "9"], "none of the supported metric columns"),  # page views are not impressions
    (HEAD, ["31/02/2026", "A", "1", "1", "1", "1", "1"], "not a valid date"),
    (HEAD, ["2026-11-02", "A", "1", "1", "1", "1", "1"], "in the future"),
    (HEAD, ["2026-10-01", "", "1", "1", "1", "1", "1"], "SKU is blank"),
    (HEAD, ["2026-10-01", "A", "10", "20", "1", "1", "1"], "more than impressions"),
    (HEAD, ["2026-10-01", "A", "1.5", "1", "1", "1", "1"], "whole number"),
    (HEAD, ["2026-10-01", "A", "-3", "1", "1", "1", "1"], "whole number"),
    (HEAD, ["2026-10-01", "A", "x", "1", "1", "1", "1"], "not a number"),
    (HEAD, ["2026-10-01", "A", "10", "1", "1", "1", "1.234"], "two decimals"),
])
def test_invalid_reports_are_refused_with_a_plain_reason(head, row, fragment):
    r = v([row], head=head)
    assert not r["ok"] and r["lines"] == [] or not r["ok"]
    assert any(fragment in e["message"] for e in r["errors"]), r["errors"]


def test_a_wrong_marketplace_and_an_unknown_marketplace_are_refused():
    r = ri.validate([[*HEAD, "Marketplace"], ["2026-10-01", "A", "1", "1", "1", "1", "1", "Flipkart"]], "AMAZON", TODAY)
    assert not r["ok"] and "Flipkart" in r["errors"][0]["message"]
    assert not ri.validate([HEAD], "EBAY", TODAY)["ok"]
    assert not ri.validate([], "AMAZON", TODAY)["ok"]


def test_repeated_rows_identical_are_counted_once_and_conflicting_ones_are_refused():
    same = v([["2026-10-01", "A", "10", "1", "1", "1", "1"], ["2026-10-01", "A", "10", "1", "1", "1", "1"]])
    assert same["ok"] and same["rowCount"] == 1 and any("counted once" in w for w in same["warnings"])
    bad = v([["2026-10-01", "A", "10", "1", "1", "1", "1"], ["2026-10-01", "A", "11", "1", "1", "1", "1"]])
    assert not bad["ok"] and "different numbers" in bad["errors"][0]["message"]


def test_a_row_with_no_values_is_skipped_and_never_saved_as_zero():
    r = v([["2026-10-01", "A", "-", "", "N/A", "", "-"], ["2026-10-02", "A", "5", "", "", "", ""]])
    assert r["ok"] and r["rowCount"] == 1 and any("Row 2" in w for w in r["warnings"])


def test_orders_above_clicks_is_a_warning_not_a_hidden_fix():
    r = v([["2026-10-01", "A", "100", "3", "5", "5", "10"]])
    assert r["ok"] and any("more than clicks" in w for w in r["warnings"]) and r["lines"][0]["orders"] == 5


# ------------------------------------------------------------------------------------------------ the maths
def test_rates_and_money_are_integers_with_half_up_rounding():
    assert mx.rate_bp(1, 3) == 3333 and mx.rate_bp(2, 3) == 6667 and mx.rate_bp(0, 5) == 0
    assert mx.rate_bp(1, 0) is None and mx.rate_bp(None, 5) is None
    assert mx.fmt_rate(235) == "2.35%" and mx.fmt_rate(5) == "0.05%"
    assert mx.fmt_money(123450) == "₹1,234.50" and mx.fmt_money(12345678) == "₹1,23,456.78" and mx.fmt_money(5) == "₹0.05"


def day(d, rows=1, **kw):
    out = {"date": date(2026, 10, d), "rows": rows}
    for m in mx.COUNTS:
        out[m] = kw.get(m, 0)
        out[f"n_{m}"] = kw.get(f"n_{m}", rows if m in kw else 0)
    return out


def covered(a, b, mp="AMAZON"):
    return {mp: {date(2026, 10, d) for d in range(a, b + 1)}}


def test_a_period_is_summed_only_when_every_row_carries_the_metric_and_every_day_is_covered():
    daily = [day(1, impressions=100, clicks=10, orders=2), day(2, impressions=300, clicks=30, orders=4)]
    s = mx.summarise(daily, date(2026, 10, 1), date(2026, 10, 2), covered(1, 2))
    m = s["metrics"]
    assert (m["impressions"]["value"], m["clicks"]["value"], m["orders"]["value"]) == (400, 40, 6)
    assert m["ctr"]["value"] == 1000 and m["cvr"]["value"] == 1500  # 10.00% and 15.00%
    assert m["units"]["state"] == mx.UNAVAILABLE and m["sales"]["state"] == mx.UNAVAILABLE  # never carried -> unavailable, not zero
    assert s["complete"] and s["coveredDays"] == 2


def test_an_uncovered_day_or_a_blank_cell_makes_a_total_not_assessed():
    daily = [day(1, impressions=100, clicks=10), day(3, impressions=100, clicks=10)]
    gap = mx.summarise(daily, date(2026, 10, 1), date(2026, 10, 3), covered(1, 1) | {"AMAZON": {date(2026, 10, 1), date(2026, 10, 3)}})
    assert gap["metrics"]["impressions"]["state"] == mx.NOT_ASSESSED and "1 of 3 days" in gap["metrics"]["impressions"]["reason"] and not gap["complete"]
    part = [day(1, impressions=100), {**day(2, impressions=50), "n_impressions": 0}]
    s = mx.summarise(part, date(2026, 10, 1), date(2026, 10, 2), covered(1, 2))
    assert s["metrics"]["impressions"]["state"] == mx.NOT_ASSESSED and "1 of 2 report rows" in s["metrics"]["impressions"]["reason"]
    assert mx.summarise([], date(2026, 10, 1), date(2026, 10, 2), {})["metrics"]["orders"]["state"] == mx.UNAVAILABLE


def test_a_rate_with_a_zero_denominator_is_not_calculable_not_zero():
    s = mx.summarise([day(1, impressions=0, clicks=0)], date(2026, 10, 1), date(2026, 10, 1), covered(1, 1))
    assert s["metrics"]["ctr"]["value"] is None and s["metrics"]["ctr"]["state"] == mx.NOT_ASSESSED


def test_previous_period_is_the_equal_length_period_before():
    assert mx.previous_period(date(2026, 10, 8), date(2026, 10, 14)) == (date(2026, 10, 1), date(2026, 10, 7))


def period(a, b, **kw):
    n = b - a + 1
    daily = [day(d, impressions=kw["impressions"] // n, clicks=kw["clicks"] // n, orders=kw["orders"] // n) for d in range(a, b + 1)]
    return mx.summarise(daily, date(2026, 10, a), date(2026, 10, b), covered(a, b))


def test_compare_gives_absolute_and_relative_differences_where_calculable():
    prev, cur = period(1, 5, impressions=1000, clicks=100, orders=10), period(6, 10, impressions=2000, clicks=100, orders=5)
    c = mx.compare(prev, cur)
    assert c["impressions"]["difference"] == 1000 and c["impressions"]["relativeBp"] == 10000 and c["impressions"]["direction"] == "UP"
    assert c["orders"]["difference"] == -5 and c["orders"]["relativeBp"] == -5000
    assert c["ctr"]["previous"] == 1000 and c["ctr"]["current"] == 500 and c["ctr"]["difference"] == -500 and c["ctr"]["relativeBp"] is None
    assert c["units"]["state"] == mx.NOT_ASSESSED
    zero = mx.compare(period(1, 5, impressions=0, clicks=0, orders=0), cur)
    assert zero["impressions"]["relativeBp"] is None


def test_wording_is_observational_and_never_causal():
    prev, cur = period(1, 5, impressions=1000, clicks=100, orders=10), period(6, 10, impressions=2000, clicks=100, orders=5)
    c = mx.compare(prev, cur)
    s = mx.sentence("orders", c["orders"], "after this version went live")
    assert s == "Orders was lower after this version went live (10 → 5)."
    for ins in mx.insights(c, prev, cur):
        blob = " ".join(str(x) for x in ins.values()).casefold()
        assert "caused" not in blob.replace("not show that anything you changed caused", "") and "because of your" not in blob and "guarantee" not in blob
        assert mx.NEVER_CAUSE in ins["limits"]


def test_insights_name_what_happened_with_evidence_a_next_step_and_limits():
    prev, cur = period(1, 5, impressions=1000, clicks=100, orders=10), period(6, 10, impressions=2000, clicks=100, orders=10)
    kinds = {i["kind"]: i for i in mx.insights(mx.compare(prev, cur), prev, cur, ["limit one"])}
    i = kinds["IMPRESSIONS_UP_CTR_DOWN"]
    assert i["measured"] and i["evidence"] and i["whyItMatters"] and i["nextStep"] and "limit one" in i["limits"]
    assert i["action"]["route"] == "M3" and {e["metric"] for e in i["evidence"]} == {"impressions", "clicks", "ctr"}
    assert all(e["previous"] and e["current"] and e["currentPeriod"] for e in i["evidence"])


def test_insufficient_data_produces_one_honest_item_and_no_invented_trend():
    empty = mx.summarise([], date(2026, 10, 1), date(2026, 10, 5), {})
    out = mx.insights(mx.compare(empty, empty), empty, empty)
    assert [i["kind"] for i in out] == ["INSUFFICIENT_DATA"] and out[0]["evidence"] == [] and not out[0]["measured"]


def test_sales_up_with_stable_units_is_flagged_for_price_or_mix_not_listing_performance():
    daily = lambda s: [{**day(d, units=10), "sales": s, "n_sales": 1} for d in (1,)]  # noqa: E731
    prev = mx.summarise(daily(100000), date(2026, 10, 1), date(2026, 10, 1), covered(1, 1))
    cur = mx.summarise([{**day(2, units=10), "sales": 150000, "n_sales": 1}], date(2026, 10, 2), date(2026, 10, 2), covered(2, 2))
    out = {i["kind"]: i for i in mx.insights(mx.compare(prev, cur), prev, cur)}
    assert "SALES_UP_UNITS_STABLE" in out and "price" in out["SALES_UP_UNITS_STABLE"]["nextStep"].casefold()


def test_the_change_wording_is_words_and_a_mark_and_matches_the_page():
    ok = mx.AVAILABLE
    assert mx.describe_change("orders", {"state": ok, "difference": 5, "relativeBp": 5000}) == "▲ Up 5 (+50.00%) from the previous period"
    assert mx.describe_change("ctr", {"state": ok, "difference": -500, "relativeBp": None}) == "▼ Down 5.00 points from the previous period"
    assert mx.describe_change("sales", {"state": ok, "difference": 12345, "relativeBp": 250}) == "▲ Up ₹123.45 (+2.50%) from the previous period"
    assert mx.describe_change("orders", {"state": ok, "difference": 0, "relativeBp": 0}).startswith("● Same")
    assert mx.describe_change("units", {"state": mx.NOT_ASSESSED, "reason": "x"}) == "Not assessed"
