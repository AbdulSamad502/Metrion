"""CMO 3.0 M8 through the real CEO chat: the seller asks how their listings perform, which is weakest, what happened after a version went live, what data is missing, and states their SKU and go-live date.
Free: no model, no unit, no credit. A statement made in chat is only shown back on a card; nothing is saved until the card's Save button (the same route as the performance page) is used. Persisted state is asserted."""

from __future__ import annotations

import io
import os

import pytest
from slim_cmo.history import metrics as mx
from tests.integration.test_ceo_cmo_delegation import chat, messages, new_investigation, say  # noqa: F401
from tests.integration.test_cmo_api import _erase_cmo_rows, ctx_engine, env, fake_clerk  # noqa: F401
from tests.integration.test_cmo_b8_performance import REPORT_SKU, SKU, days_ago, put_golive
from tests.integration.test_cmo_m6_integration import ListingProvider, ru_env
from tests.integration.test_cmo_m8_performance import importing, report, span
from tests.integration.test_ceo_cmo_m7_history_chat import edit, footprint, versions

pytestmark = pytest.mark.skipif(not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL"), reason="needs a live Postgres")


def ask(c, inv, text):
    say(c, inv, text)
    last = [m for m in messages(c, inv) if m["role"] == "CEO"][-1]
    return last["content"], last.get("choices"), last["kind"]


def card(choices, view):
    assert choices and choices["kind"] == "LISTING_PERFORMANCE" and choices["view"] == view, choices
    assert choices["aiCredits"] == 0
    return choices


def seed(c, window=7):
    e = c.env
    v1, v2 = versions(c, 2)
    e.post("performance/window", {"days": window})
    importing(e, report(span(45, 5)), name="all.csv")
    return v1, v2


def link(c):
    assert c.env.post("performance/sku-link", {"sku": SKU, "marketplace": "AMAZON", "report_sku": REPORT_SKU}).status_code == 200


def test_with_no_report_imported_the_answer_says_so_and_invents_nothing(chat):
    versions(chat, 2)
    inv = new_investigation(chat)
    before = footprint(chat)
    text, choices, kind = ask(chat, inv, "How are my listings performing?")
    card(choices, "NO_DATA")
    assert kind == "ANSWER" and "have not imported a performance report" in text and "Nothing is estimated" in text
    assert footprint(chat) == before and chat.env.n("cmo_perf_line") == 0


def test_overview_reports_stored_numbers_only_and_compares_with_the_previous_period(chat):
    seed(chat)
    e = chat.env
    importing(e, report(span(4, 0), imp=200, clk=10, orders=3), name="recent.csv")
    inv = new_investigation(chat)
    before = footprint(chat)
    text, choices, _ = ask(chat, inv, "Show my sales and conversion trends")
    c = card(choices, "OVERVIEW")
    assert c["dashboard"]["current"]["metrics"]["orders"]["state"] in ("AVAILABLE", "NOT_ASSESSED")
    assert "from your imported reports" in text and "caused" not in text.replace(mx.NEVER_CAUSE, "").casefold() and "improved" not in text.casefold()
    assert footprint(chat) == before


def test_which_listing_has_the_lowest_ctr_ranks_only_linked_listings_and_names_what_is_not_assessed(chat):
    seed(chat)
    inv = new_investigation(chat)
    text, choices, _ = ask(chat, inv, "Which listing has the lowest CTR?")
    assert card(choices, "RANK")["ranking"]["ranked"] == [] and "cannot rank" in text and "SKU link" in text
    link(chat)
    text, choices, _ = ask(chat, inv, "Which listing has the lowest CTR?")
    c = card(choices, "RANK")
    assert c["ranking"]["ranked"][0]["text"] == "10.00%" and "not a benchmark" in text
    text, choices, _ = ask(chat, inv, "Which listing should I improve first?")
    assert "look at it first" in text and "nothing is guaranteed" in text and card(choices, "RANK")["action"]["route"] == "M3"


def test_connecting_a_sku_is_proposed_in_chat_and_saved_only_by_the_save_button(chat):
    seed(chat)
    inv = new_investigation(chat)
    before = footprint(chat)
    text, choices, _ = ask(chat, inv, f"Connect SKU {REPORT_SKU} to my AquaNest bottle")
    c = card(choices, "CONFIRM_LINK")
    assert c["proposal"] == {"sku": SKU, "marketplace": "AMAZON", "reportSku": REPORT_SKU} and "Press Save" in text
    ask(chat, inv, "yes")  # typing yes never saves
    assert chat.env.n("cmo_listing_sku_link") == 0 and footprint(chat) == before
    p = c["proposal"]  # what the card's Save button posts
    assert chat.env.post("performance/sku-link", {"sku": p["sku"], "marketplace": p["marketplace"], "report_sku": p["reportSku"]}).status_code == 200
    text, choices, _ = ask(chat, inv, "Connect SKU ALT-9 to my AquaNest bottle")
    assert "Which SKU" in text and card(choices, "CLARIFY")["options"][0]["reportSku"] == REPORT_SKU  # an unknown SKU is never accepted; the seller chooses from their own reports
    assert chat.env.n("cmo_listing_sku_link") == 1


def test_a_golive_statement_asks_for_a_missing_date_and_refuses_an_impossible_one(chat):
    v1, v2 = seed(chat)
    inv = new_investigation(chat)
    text, choices, _ = ask(chat, inv, "Version 2 went live")
    assert "what date" in text.casefold() and card(choices, "CLARIFY")["ask"]["version"] == 2
    text, choices, _ = ask(chat, inv, "today")
    c = card(choices, "CONFIRM_GOLIVE")
    assert c["proposal"]["generationId"] == v2 and c["proposal"]["number"] == 2 and chat.env.n("cmo_listing_golive") == 0  # a version is never assumed live; nothing saved yet
    text, choices, _ = ask(chat, inv, "Version 1 went live on 3 October 2020")
    assert "cannot have gone live" in text and chat.env.n("cmo_listing_golive") == 0
    text, choices, _ = ask(chat, inv, "Version 1 went live tomorrow")
    assert chat.env.n("cmo_listing_golive") == 0 and "tomorrow" not in str(choices.get("proposal", ""))


def test_what_changed_after_i_updated_my_title_guides_the_seller_through_what_is_missing(chat):
    v1, v2 = seed(chat)
    inv = new_investigation(chat)
    text, choices, _ = ask(chat, inv, "What changed after I updated my title?")
    assert card(choices, "VERSIONS")["analysis"]["versions"][0]["state"] == "NOT_ASSESSED" and "I need:" in text and "SKU" in text
    link(chat)
    put_golive(chat.env, v1, days_ago(30))
    put_golive(chat.env, v2, days_ago(14))
    text, choices, _ = ask(chat, inv, "What changed after I updated my listing?")
    assert "went live on" in text and "Impressions" in text and "does not show that the listing change caused it" in text
    assert "caused by" not in text.casefold() and card(choices, "VERSIONS")["analysis"]["versions"][1]["state"] == "OBSERVED_COMPARABLE"


def test_what_performance_data_is_missing_lists_every_open_item(chat):
    versions(chat, 2)
    inv = new_investigation(chat)
    text, choices, _ = ask(chat, inv, "What performance data is missing?")
    c = card(choices, "MISSING")
    assert "performance report imported" in text and any("which SKU" in m for m in c["missing"]) and any("go-live date for version" in m for m in c["missing"])
    assert any("comparison period length" in m for m in c["missing"])


def test_setting_the_comparison_length_is_proposed_and_bounded(chat):
    versions(chat, 2)
    inv = new_investigation(chat)
    text, choices, _ = ask(chat, inv, "Compare over 14 days")
    assert card(choices, "CONFIRM_WINDOW")["proposal"] == {"days": 14} and chat.env.n("cmo_perf_setting") == 0
    text, choices, _ = ask(chat, inv, "Use a 120 days comparison period")
    assert "7 to 90" in text and choices["view"] == "REFUSED"


def test_older_chat_flows_and_unrelated_questions_are_not_intercepted(chat):
    versions(chat, 2)
    inv = new_investigation(chat)
    _, choices, _ = ask(chat, inv, "Show my listing history.")
    assert choices["kind"] == "LISTING_HISTORY" and choices["view"] == "HISTORY"
    _, choices, _ = ask(chat, inv, "Compare version 1 and version 2")
    assert choices["kind"] == "LISTING_HISTORY" and choices["view"] == "COMPARE"
    _, choices, _ = ask(chat, inv, "What is the weather like?")
    assert not choices or choices.get("kind") != "LISTING_PERFORMANCE"


def test_another_tenants_chat_sees_none_of_this(chat):
    seed(chat)
    other, headers = chat.env.other_tenant()
    inv = chat.client.post("/api/v1/ceo/investigations", json={"title": "x"}, headers=headers).json()["investigationId"]
    chat.client.post(f"/api/v1/ceo/investigations/{inv}/turns", json={"message": "How are my listings performing?"}, headers=headers)
    from backend.repositories import investigation_repo as repo
    import uuid

    last = [m for m in repo.list_messages(other, uuid.UUID(inv)) if m["role"] == "CEO"]
    assert not last or "(from your imported reports)" not in last[-1]["content"]  # none of the first tenant's figures


# ---------------------------------------------------------------- M8-12: the one-click hand-off reaches the existing workflow
def test_every_handoff_sentence_reaches_its_existing_workflow_free_and_changes_nothing(chat):
    from slim_cmo.history import metrics as mx

    v1, v2 = seed(chat)
    link(chat)
    e = chat.env
    importing(e, report(span(4, 0), imp=300, clk=10, orders=1), name="recent.csv")  # more impressions, lower CTR and fewer orders than before
    d = e.client().get("/api/v1/cmo/performance/dashboard", params={"sku": SKU, "marketplace": "AMAZON"}, headers=e.headers).json()
    actions = {i["action"]["kind"]: i["action"] for i in d["insights"] if i["action"]}
    assert actions and all(a["draft"] and a["product"] and a["marketplace"] == "AMAZON" for a in actions.values())
    product = next(iter(actions.values()))["product"]
    inv = new_investigation(chat)
    before = footprint(chat)
    expect = {"TITLE": ("LISTING_HISTORY", "RECOMMEND"), "KEYWORDS": ("LISTING_HISTORY", "RECOMMEND"), "CONTENT": ("READINESS", None), "REVISE": ("LISTING_HISTORY", "VERSION")}
    for kind, (card_kind, view) in expect.items():
        draft = mx.HANDOFF[kind].format(product=product, marketplace="Amazon")
        text, choices, status = ask(chat, inv, draft)
        assert choices and choices["kind"] == card_kind and (view is None or choices["view"] == view), (kind, draft, choices)
    assert footprint(chat) == before  # free: nothing generated, billed, approved or changed
    for kind, a in actions.items():  # the hand-off sentence the page offers is the one tested above
        assert a["draft"] == mx.HANDOFF[kind].format(product=product, marketplace="Amazon")


def test_without_a_known_product_the_dashboard_offers_no_handoff(chat):
    seed(chat)
    importing(chat.env, report(span(4, 0), imp=300, clk=10, orders=1), name="recent.csv")
    d = chat.env.client().get("/api/v1/cmo/performance/dashboard", headers=chat.env.headers).json()
    assert all(i["action"] is None or i["action"]["draft"] is None for i in d["insights"])


def test_typing_yes_after_any_proposal_saves_nothing_and_a_changed_statement_needs_replace(chat):
    v1, v2 = seed(chat)
    link(chat)
    e = chat.env
    inv = new_investigation(chat)
    window_before = e.n("cmo_perf_setting")  # the seed saved 7 days through the route
    ask(chat, inv, "Version 2 went live today")
    ask(chat, inv, "yes")
    ask(chat, inv, "confirm")
    ask(chat, inv, "Compare over 14 days")
    ask(chat, inv, "yes")
    assert e.n("cmo_listing_golive") == 0 and e.n("cmo_perf_setting") == window_before and e.n("cmo_listing_sku_link") == 1  # only the link made through the route above
    other = e.client().post("/api/v1/cmo/performance/golive", json={"generation_id": v2, "went_live_on": days_ago(0).isoformat()}, headers=e.headers)
    assert other.status_code == 200
    ask(chat, inv, "Version 2 went live yesterday")  # created today, so yesterday is refused before any card
    text, choices, _ = ask(chat, inv, "Version 2 went live today")
    assert choices["view"] == "CONFIRM_GOLIVE" and choices["replaces"] is None  # the same date again is a repeat, not a change
    changed = e.client().post("/api/v1/cmo/performance/sku-link", json={"sku": SKU, "marketplace": "AMAZON", "report_sku": "OTHER-SKU"}, headers=e.headers)
    assert changed.status_code in (409, 422) and (changed.status_code == 422 or changed.json()["detail"]["code"] == "LINK_EXISTS")
