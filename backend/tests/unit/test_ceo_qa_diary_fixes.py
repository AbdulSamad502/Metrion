"""Regressions from the 12 Oct 2026 CEO Hub manual QA diary (metrion_ceo_20_test_cases.pdf).

* Briefings, profit-leak investigations, PI status questions, greetings and "what can you do?" are recognised by code, so they no longer depend on the classifier model
  (tests 01, 03, 06, 07, 13, 14, 15, 18, 19).
* A spreadsheet's identifier / year / rate columns are never summed as money, and an ambiguous or file-name-contradicting reporting period is said so (test 08).
* An attachment can be continued in a later message (test 09).
"""

from __future__ import annotations

from backend.ceo import classifier, conversational, intent_router, question_types
from backend.ceo.capabilities import Capabilities
from backend.ceo.plans import ACTIONS, PLAYBOOKS
from backend.services import attachment_tables as tables
from backend.services import ceo_attachment_analysis as analysis

CAT = classifier.build_catalog(list(ACTIONS), list(PLAYBOOKS), question_types.descriptions())


def _route(text: str):
    d = intent_router.route(text, CAT)
    return None if d is None else (d.route, d.key)


def test_briefing_prompts_route_to_the_briefing_playbook_even_when_they_mention_missing_data():
    assert _route("Give me a concise briefing on my business: what is performing well, what needs attention, and what data is missing.") == ("PLAYBOOK", "BUSINESS_BRIEFING")
    assert _route("Give me a cross-domain business briefing using information currently available across finance, products, competitors, and marketing.") == ("PLAYBOOK", "BUSINESS_BRIEFING")


def test_profit_leak_investigation_reads_the_saved_leaks_and_never_starts_work():
    assert _route("Investigate where my business may be losing profit. Review available financial data, identify confirmed leaks with evidence, and list missing data.") == ("BUSINESS_STATE", "QT_LEAKS")


def test_a_pi_status_question_is_a_state_read_not_a_new_discovery():
    assert _route("What is the current status of my Product Intelligence brief c270eadc-d69b-4968-bc27-fa57f6888c85? Do not run discovery.") == ("BUSINESS_STATE", "QT_PRODUCT_IDEAS")
    assert _route("Research product ideas for Amazon India under 20000") == ("ACTION", "pi.discover")  # a request to do the work is unchanged


def test_a_pnl_summary_request_is_a_profit_read():
    assert _route("Summarize my latest P&L. If no report is available, tell me exactly what is missing and what I should upload.") == ("BUSINESS_STATE", "QT_PROFIT_BY_PERIOD")


def test_greetings_are_answered_by_code_and_a_request_that_starts_with_one_is_not():
    assert conversational.is_greeting("hi") and conversational.is_greeting("Hello there!")
    assert conversational.is_greeting("Hi! Give me a one-sentence welcome and ask what part of my business I want to work on today.")
    assert not conversational.is_greeting("hi, what was my profit in September?")
    assert not conversational.is_greeting("Why did my profit drop?")
    assert conversational.WELCOME_TEXT.count(".") == 0 and conversational.WELCOME_TEXT.endswith("?")  # one sentence, ends with the question


def test_capability_answer_comes_from_the_members_own_catalog_and_names_what_is_not_built():
    q = "What is Metrion, what are its main agents, and what can I currently do from the CEO Hub? Separate available capabilities from features that are not yet implemented."
    assert conversational.is_capability_question(q) and not conversational.is_capability_question("What is my profit this month?")
    caps = Capabilities(frozenset({"CFO"}), ("cfo.reconcile",), (), {}, {"CFO": "PRESENT", "CI": "NOT_ATTACHED", "PI": "NOT_ENTITLED", "CMO": "NOT_PERMITTED"})
    text = conversational.capability_answer(caps)
    assert "chat for: a leak check against your orders; a business briefing" in text  # only the actions this member's catalog holds
    assert "not on your current plan" in text and "not attached to this conversation" in text
    assert "image" in text and "Not available from chat yet" in text
    assert not any(ch.isdigit() for ch in text)  # no figure of any kind


CSV = (
    "Order Id,Invoice Date,Ship To Postal Code,GST Filing Year,Igst Rate,Invoice Amount,Shipping Charges\n"
    "A1,03/04/2026,560001,2025,0.18,1000.50,50\n"
    "A2,04/04/2026,110001,2025,0.18,2000,60\n"
).encode()


def test_identifiers_years_and_rates_are_not_amount_columns():
    wb = tables.read_csv(CSV, "amazon_mtr_sep_2025.csv")
    amount = {c.name for c in wb.sheets[0].columns if c.amount_like}
    assert amount == {"Invoice Amount", "Shipping Charges"}
    text = "\n".join(tables.totals(wb))
    assert "Postal Code" not in text and "Filing Year" not in text and "Igst Rate" not in text


def test_ambiguous_dates_and_a_file_name_that_disagrees_with_them_are_stated():
    out = "\n".join(tables.describe(tables.read_csv(CSV, "amazon_mtr_sep_2025.csv")))
    assert "ambiguous" in out and "2026-04-03 to 2026-04-04" in out
    assert "September 2025" in out and "reporting period is unverified" in out
    agree = "Order Id,Invoice Date,Invoice Amount\nA1,2025-09-03,10\nA2,2025-09-20,20\n".encode()
    assert "unverified" not in "\n".join(tables.describe(tables.read_csv(agree, "mtr_sep_2025.csv")))


def test_a_follow_up_that_points_at_an_earlier_file_is_recognised():
    assert analysis.refers_to_earlier_file("Using the file I attached in my previous message, continue the analysis.")
    assert analysis.refers_to_earlier_file("summarize the file i attached earlier")
    assert not analysis.refers_to_earlier_file("What is my profit?")
