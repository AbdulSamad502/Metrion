"""CMO 3.0 M10 (market opportunities and marketplace news) over the real HTTP API and the real CEO chat on a real Postgres: the saved market-trend reports are read back with their sources, dates and freshness,
filtered by product and marketplace, an empty or missing report is said plainly, one seller never sees another's, and nothing is written, generated or billed. Synthetic reports and products only; no model, no search."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from backend.auth.permissions import PARTNER_ROLE
from backend.repositories import investigation_repo as repo
from tests.integration.test_ceo_cmo_delegation import chat, messages, new_investigation, say  # noqa: F401
from tests.integration.test_cmo_api import _erase_cmo_rows, _login, ctx_engine, env, fake_clerk  # noqa: F401

pytestmark = pytest.mark.skipif(not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL"), reason="needs a live Postgres")

BASE = "/api/v1/cmo/market-intelligence"
SKU, PRODUCT = "aqua", "AquaNest steel bottle"


def ago(days: int) -> str:
    return (datetime.now(UTC) - timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()


def finding(fid, theme, summary="Reported by the saved sources.", kind=None, sources=(), corroboration="SINGLE_SOURCE"):
    f = {"finding_id": fid, "theme": theme, "summary": summary, "independent_source_count": len(sources), "corroboration": corroboration,
         "sources": [{"url": u, "title": t, "published_at": p, "retrieved_at": ago(1), "source_class": c} for (u, t, p, c) in sources]}
    if kind:
        f["news_kind"] = kind
    return f


def save_report(env, sections, age_days=2, tenant=None):
    """One saved market-trend report (its generation row first), generated `age_days` ago."""
    t, gen = tenant or env.tenant, uuid.uuid4()
    with env.cengine.begin() as conn:
        conn.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": str(t)})
        conn.execute(text("INSERT INTO cmo_generation (id, tenant_id, output_type, input_mode, output_structured, status, request_key, generated_by) "
                          "VALUES (:g, :t, 'TREND_REPORT', 'INDEPENDENT', '{}'::jsonb, 'COMPLETE', :k, :u)"), {"g": str(gen), "t": str(t), "k": f"m10-{gen}", "u": str(env.user_id)})
        conn.execute(text("INSERT INTO cmo_trend_report (tenant_id, generation_id, sections_requested, sections, evidence, outbound_queries, config_snapshot, market_signal_run_ref, generated_at) "
                          "VALUES (:t, :g, ARRAY['MARKET_NEWS'], CAST(:s AS jsonb), '{\"sources\": []}'::jsonb, '[]'::jsonb, '{}'::jsonb, :r, :at)"),
                     {"t": str(t), "g": str(gen), "s": json.dumps(sections), "r": str(uuid.uuid4()), "at": datetime.now(UTC) - timedelta(days=age_days)})
    return gen


def save_product(env, tenant=None, sku=SKU, name=PRODUCT):
    t = tenant or env.tenant
    with env.cengine.begin() as conn:
        conn.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": str(t)})
        conn.execute(text("INSERT INTO seller_fact (tenant_id, sku, attribute_name, fact_type, fact_value, provided_by) VALUES (:t, :s, 'product_name', 'ATTRIBUTE', :n, :u)"),
                     {"t": str(t), "s": sku, "n": name, "u": str(env.user_id)})


POLICY = finding("f1", "Amazon India updates return policy for steel bottles", kind="POLICY", sources=[("https://sell.amazon.in/returns", "Return policy", ago(6), "OFFICIAL_MARKETPLACE")])
FEE = finding("f2", "Flipkart fee change for garden hoses", kind="FEE", sources=[("https://seller.flipkart.com/fees", "Fee notice", ago(40), "OFFICIAL_MARKETPLACE")])
UNDATED = finding("f3", "Meesho seller programme update", kind="SELLER_PROGRAM", sources=[("https://supplier.meesho.com/programme", "Programme", None, "OFFICIAL_MARKETPLACE")])
GENERAL = finding("f4", "Festive season shopping begins", kind="SEASONAL", sources=[("https://news.example/festive", "Festive news", ago(3), "THIRD_PARTY")])
GIFTING = finding("g1", "Insulated steel bottle gifting", corroboration="MODERATE", sources=[("https://news.example/gift-a", "Gifting A", ago(5), "THIRD_PARTY"), ("https://blog.example/gift-b", "Gifting B", ago(9), "THIRD_PARTY")])
NEWS_ALL = {"MARKET_NEWS": {"state": "OK", "reason": None, "findings": [POLICY, FEE, UNDATED, GENERAL]}, "ADJACENT": {"state": "OK", "reason": None, "findings": [GIFTING]}}


def get(env, path="", headers=None, **params):
    return env.client().get(BASE + path, params=params, headers=env.headers if headers is None else headers)


def sig(env, tenant=None):
    rows = env.q("SELECT id::text, sections::text, generated_at::text FROM cmo_trend_report ORDER BY id", tenant)
    return hashlib.sha256(repr(rows).encode()).hexdigest(), len(rows)


def footprint(env):
    return {**{t: env.n(t) for t in ("cmo_trend_report", "cmo_generation", "seller_fact", "cmo_quota_reservation")}, "cmo_metered": env.n("metered_event", "agent_code = 'CMO'")}


# ------------------------------------------------------------------------------------------------ missing reports and empty results
def test_with_no_saved_report_every_route_says_so_and_invents_nothing(env):
    for path in ("", "/news", "/opportunities"):
        r = get(env, path)
        assert r.status_code == 200, r.text
        b = r.json()
        assert b["state"] == "NO_REPORT" and b["reportCount"] == 0 and b["latestReportAt"] is None and b["aiCredits"] == 0
        assert b.get("news", []) == [] and b.get("opportunities", []) == [] and b["message"]


def test_a_report_with_no_findings_gives_empty_lists_not_made_up_items(env):
    save_report(env, {"MARKET_NEWS": {"state": "NO_FINDINGS", "reason": "Nothing found.", "findings": []}})
    b = get(env).json()
    assert b["news"] == [] and b["opportunities"] == [] and b["reportCount"] == 1 and b["aiCredits"] == 0


# ------------------------------------------------------------------------------------------------ retrieval: sources, dates, freshness
def test_saved_news_comes_back_with_source_link_date_freshness_and_never_demand(env):
    save_product(env)
    save_report(env, NEWS_ALL)
    b = get(env).json()
    assert b["state"] == "OK" and b["reportCount"] == 1 and b["aiCredits"] == 0 and b["today"] == datetime.now(UTC).date().isoformat()
    by = {n["headline"]: n for n in b["news"]}
    pol = by[POLICY["theme"]]
    assert pol["sources"][0]["url"] == "https://sell.amazon.in/returns" and pol["sources"][0]["title"] == "Return policy" and pol["publishedAt"] == ago(6)[:10]
    assert pol["freshness"] == "FRESH" and pol["ageDays"] == 6 and pol["officialSource"] is True and pol["marketplaces"] == ["AMAZON"] and pol["newsKind"] == "POLICY"
    assert by[FEE["theme"]]["freshness"] == "RECENT" and by[FEE["theme"]]["ageDays"] == 40
    und = by[UNDATED["theme"]]
    assert und["freshness"] == "DATE_UNKNOWN" and und["publishedAt"] is None and und["ageDays"] is None  # an undated item is never called fresh and never given a guessed date
    opp = b["opportunities"][0]
    assert opp["title"] == GIFTING["theme"] and opp["demand"]["state"] == "UNAVAILABLE" and opp["observed"]["independentSources"] == 2
    assert {s["url"] for s in opp["observed"]["sources"]} == {"https://news.example/gift-a", "https://blog.example/gift-b"}
    assert "not measured" in opp["possible"]["label"] and opp["rank"] == 1


def test_an_old_report_is_flagged_stale_and_its_old_items_are_not_called_fresh(env):
    old = finding("o1", "Amazon India updates return policy", kind="POLICY", sources=[("https://sell.amazon.in/old", "Old", ago(120), "OFFICIAL_MARKETPLACE")])
    save_report(env, {"MARKET_NEWS": {"state": "OK", "reason": None, "findings": [old]}}, age_days=90)
    b = get(env).json()
    assert b["state"] == "STALE_REPORTS" and "90 days" in b["message"]
    assert b["news"][0]["freshness"] == "STALE" and b["news"][0]["isStale"] is True


def test_the_same_finding_in_two_reports_is_shown_once_with_the_count_of_reports(env):
    save_report(env, {"MARKET_NEWS": {"state": "OK", "reason": None, "findings": [POLICY]}}, age_days=20)
    save_report(env, {"MARKET_NEWS": {"state": "OK", "reason": None, "findings": [{**POLICY, "finding_id": "again"}]}}, age_days=2)
    news = get(env, "/news").json()["news"]
    assert len(news) == 1 and news[0]["seenInReports"] == 2 and news[0]["reportDate"] == ago(2)[:10]


# ------------------------------------------------------------------------------------------------ product and marketplace filters
def test_marketplace_filter_keeps_only_news_naming_it_and_counts_what_names_none(env):
    save_report(env, NEWS_ALL)
    amazon = get(env, "/news", marketplace="AMAZON").json()
    assert [n["headline"] for n in amazon["news"]] == [POLICY["theme"]] and amazon["filters"] == {"sku": None, "marketplace": "AMAZON"}
    assert amazon["newsWithoutMarketplace"] == 1  # the festive item names no marketplace: counted, not guessed into one
    assert [n["headline"] for n in get(env, "/news", marketplace="FLIPKART").json()["news"]] == [FEE["theme"]]
    assert [n["headline"] for n in get(env, "/news", marketplace="MEESHO").json()["news"]] == [UNDATED["theme"]]


def test_product_filter_keeps_news_and_opportunities_that_relate_to_that_product(env):
    save_product(env)
    save_product(env, sku="hose", name="Garden hose pipe")
    save_report(env, NEWS_ALL)
    b = get(env, sku=SKU).json()
    heads = [n["headline"] for n in b["news"]]
    assert POLICY["theme"] in heads and FEE["theme"] not in heads  # hoses are not the steel bottle
    pol = next(n for n in b["news"] if n["headline"] == POLICY["theme"])
    assert pol["relevance"]["level"] in ("HIGH", "MEDIUM") and any(a["sku"] == SKU for a in pol["relevance"]["affects"])
    assert [o["title"] for o in b["opportunities"]] == [GIFTING["theme"]] and b["opportunities"][0]["rank"] == 1
    hose = get(env, "/opportunities", sku="hose").json()
    assert hose["opportunities"] == []  # the steel-bottle lead does not relate to the hose: an empty result, not a filler


def test_marketplace_and_product_together_and_bad_values_are_refused(env):
    save_product(env)
    save_report(env, NEWS_ALL)
    both = get(env, "/news", sku=SKU, marketplace="AMAZON").json()
    assert POLICY["theme"] in [n["headline"] for n in both["news"]] and FEE["theme"] not in [n["headline"] for n in both["news"]]
    assert get(env, marketplace="EBAY").status_code == 422
    nope = get(env, sku="not-mine")
    assert nope.status_code == 404 and nope.json()["detail"]["code"] == "UNKNOWN_PRODUCT"


# ------------------------------------------------------------------------------------------------ tenant isolation, permissions, persistence
def test_another_seller_never_sees_these_reports_or_products(env):
    save_product(env)
    save_report(env, NEWS_ALL)
    other, other_headers = env.other_tenant()
    b = get(env, headers=other_headers).json()
    assert b["state"] == "NO_REPORT" and b["news"] == [] and b["opportunities"] == [] and b["products"] == []
    assert get(env, sku=SKU, headers=other_headers).status_code == 404
    assert env.n("cmo_trend_report", tenant=other) == 0 and env.n("cmo_trend_report") == 1
    private = finding("p1", "Meesho private-label seller note", sources=[("https://other.example/p", "Theirs", ago(2), "THIRD_PARTY")])
    save_report(env, {"MARKET_NEWS": {"state": "OK", "reason": None, "findings": [private]}}, tenant=other)
    mine = get(env).json()
    assert private["theme"] not in [n["headline"] for n in mine["news"]] and mine["reportCount"] == 1
    theirs = get(env, headers=other_headers).json()
    assert [n["headline"] for n in theirs["news"]] == [private["theme"]] and theirs["reportCount"] == 1


def test_sign_in_and_the_cmo_permission_are_required(env):
    assert get(env, headers={}).status_code == 401
    no_cmo, _ = _login(env.fake_clerk, env.tenant, role=PARTNER_ROLE, permissions={})
    assert get(env, headers=no_cmo).status_code == 403
    cmo_only, _ = _login(env.fake_clerk, env.tenant, role=PARTNER_ROLE, permissions={"agent.cmo": True})
    assert get(env, headers=cmo_only).status_code == 200  # read-only: the CMO permission alone is enough


def test_reading_changes_nothing_and_repeats_identically(env):
    save_product(env)
    save_report(env, NEWS_ALL)
    before, fp = sig(env), footprint(env)
    first = get(env).json()
    for path in ("", "/news", "/opportunities"):
        assert get(env, path, marketplace="AMAZON").status_code == 200
    assert get(env).json() == first  # deterministic
    assert sig(env) == before and footprint(env) == fp  # the saved reports are untouched; nothing generated, metered or reserved
    assert env.client().post(BASE, json={}, headers=env.headers).status_code == 405  # there is no write route


def test_the_application_role_cannot_alter_a_saved_report_and_security_is_forced(env):
    assert env.q("SELECT has_table_privilege('metrion_app', 'cmo_trend_report', 'UPDATE'), has_table_privilege('metrion_app', 'cmo_trend_report', 'DELETE')")[0] == (False, False)
    assert env.q("SELECT relforcerowsecurity FROM pg_class WHERE relname = 'cmo_trend_report'")[0][0] is True


# ------------------------------------------------------------------------------------------------ CEO chat
def ask(c, inv, t, headers=None, tenant=None):
    say(c, inv, t, headers=headers)
    msgs = repo.list_messages(tenant or c.env.tenant, uuid.UUID(inv))
    last = [m for m in msgs if m["role"] == "CEO"][-1]
    return last["content"], last.get("choices"), last["kind"]


def market_card(choices, view):
    assert choices and choices["kind"] == "MARKET_INTELLIGENCE" and choices["view"] == view, choices
    assert choices["aiCredits"] == 0 and choices["page"] == "/dashboard/cmo/market"
    return choices


def test_chat_with_no_saved_report_says_so_and_invents_nothing(chat):
    inv, before = new_investigation(chat), footprint(chat.env)
    text_, choices, kind = ask(chat, inv, "Show latest marketplace news")
    c = market_card(choices, "NO_REPORT")
    assert kind == "ANSWER" and "no saved market-trend report" in text_ and c["news"] == [] and c["opportunities"] == []
    assert footprint(chat.env) == before and chat.env.provider.calls == 0


def test_chat_news_shows_stored_items_with_source_date_and_freshness_and_costs_nothing(chat):
    e = chat.env
    save_product(e)
    save_report(e, NEWS_ALL)
    inv, before, snap = new_investigation(chat), footprint(e), sig(e)
    text_, choices, _ = ask(chat, inv, "Show latest marketplace news")
    c = market_card(choices, "NEWS")
    heads = [n["headline"] for n in c["news"]]
    assert POLICY["theme"] in heads and c["reportCount"] == 1
    pol = next(n for n in c["news"] if n["headline"] == POLICY["theme"])
    assert pol["sources"][0]["url"] == "https://sell.amazon.in/returns" and pol["freshness"] == "FRESH" and pol["publishedAt"] == ago(6)[:10]
    assert POLICY["theme"] in text_ and "fresh" in text_.lower()
    assert footprint(e) == before and sig(e) == snap and e.provider.calls == 0


def test_chat_changed_on_a_marketplace_filters_to_it(chat):
    e = chat.env
    save_report(e, NEWS_ALL)
    inv = new_investigation(chat)
    _, choices, _ = ask(chat, inv, "What has changed on Amazon?")
    c = market_card(choices, "CHANGED")
    assert [n["headline"] for n in c["news"]] == [POLICY["theme"]] and c["filter"] == {"marketplace": "AMAZON"}
    text_, choices, _ = ask(chat, inv, "What has changed on Meesho?")
    assert [n["headline"] for n in market_card(choices, "CHANGED")["news"]] == [UNDATED["theme"]] and "date unknown" in text_


def test_chat_asks_one_marketplace_question_when_two_are_named_then_answers_it(chat):
    e = chat.env
    save_report(e, NEWS_ALL)
    inv = new_investigation(chat)
    q, choices, _ = ask(chat, inv, "What has changed on Amazon and Flipkart?")
    c = market_card(choices, "CLARIFY")
    assert q == "Which marketplace do you mean?" and [o["marketplace"] for o in c["options"]] == ["AMAZON", "FLIPKART", "MEESHO"] and "news" not in c
    _, choices, _ = ask(chat, inv, "Flipkart")
    assert [n["headline"] for n in market_card(choices, "CHANGED")["news"]] == [FEE["theme"]]
    assert e.provider.calls == 0


def test_chat_opportunities_focus_affects_and_action_use_the_stored_items(chat):
    e = chat.env
    save_product(e)
    save_report(e, NEWS_ALL)
    inv, before = new_investigation(chat), footprint(e)
    text_, choices, _ = ask(chat, inv, "Find opportunities for my products")
    c = market_card(choices, "OPPORTUNITIES")
    assert [o["title"] for o in c["opportunities"]] == [GIFTING["theme"]] and "leads to check, not predictions" in text_
    text_, choices, _ = ask(chat, inv, "Which opportunities should I focus on?")
    assert market_card(choices, "FOCUS")["opportunities"][0]["title"] == GIFTING["theme"] and "Demand is UNAVAILABLE" in text_
    _, choices, _ = ask(chat, inv, "Show latest marketplace news")
    market_card(choices, "NEWS")
    text_, choices, _ = ask(chat, inv, "How does this news affect my products?")
    c = market_card(choices, "AFFECTS")
    assert c["focusId"] and len(c["news"]) == 1 and c["news"][0]["id"] == c["focusId"]
    text_, choices, _ = ask(chat, inv, "What should I do about this update?")
    assert market_card(choices, "ACTION")["focusId"] == c["focusId"] and "changes nothing on a marketplace" in text_
    assert footprint(e) == before and e.provider.calls == 0


def test_chat_with_nothing_relevant_says_so(chat):
    e = chat.env
    save_report(e, {"MARKET_NEWS": {"state": "OK", "reason": None, "findings": []}})
    inv = new_investigation(chat)
    text_, choices, _ = ask(chat, inv, "Find opportunities for my products")
    assert market_card(choices, "OPPORTUNITIES")["opportunities"] == [] and "no opportunity" in text_
    text_, choices, _ = ask(chat, inv, "Show latest marketplace news")
    assert market_card(choices, "NEWS")["news"] == [] and "no marketplace news" in text_


def test_chat_never_shows_another_sellers_reports(chat):
    e = chat.env
    save_report(e, NEWS_ALL)
    other, other_headers = e.other_tenant()
    inv = new_investigation(chat, headers=other_headers)
    _, choices, _ = ask(chat, inv, "Show latest marketplace news", headers=other_headers, tenant=other)
    assert market_card(choices, "NO_REPORT")["news"] == []
    assert e.n("cmo_trend_report", tenant=other) == 0


def test_the_existing_market_research_phrases_are_not_taken_over(chat):
    inv = new_investigation(chat)
    say(chat, inv, "latest news in ecommerce")
    last = [m for m in messages(chat, inv) if m["role"] == "CEO"][-1]
    assert not (isinstance(last.get("choices"), dict) and last["choices"].get("kind") == "MARKET_INTELLIGENCE")
