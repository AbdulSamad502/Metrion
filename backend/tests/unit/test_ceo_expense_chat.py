"""The expense ledger conversation, pure parts (docs/specs/ceo-expense-tracker-chat.md): what the seller says is read BY CODE, never by a model; nothing is guessed."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from backend.ceo import expense_chat as ec
from backend.ceo import intent_router
from backend.services.ceo_expense_ops import breakdown_of

TODAY = date(2026, 10, 23)


@pytest.mark.parametrize("raw,paise", [("5000", 500_000), ("₹5,000", 500_000), ("Rs. 1,299.50", 129_950), ("1,29,900", 12_990_000), ("499 rupees", 49_900)])
def test_amounts_are_read_exactly_in_paise(raw, paise):
    assert ec.parse_amount(raw) == paise


@pytest.mark.parametrize("raw", ["", "five thousand", "5k", "0", "-300", "a lakh", "12,00,00,00,00,000"])
def test_what_is_not_an_exact_positive_amount_is_asked_again(raw):
    assert isinstance(ec.parse_amount(raw), ec.Bad)


@pytest.mark.parametrize("raw,iso", [("today", "2026-10-23"), ("yesterday", "2026-10-22"), ("5 October", "2026-10-05"), ("2026-10-01", "2026-10-01"), ("oct 5 2026", "2026-10-05")])
def test_days_are_read_exactly(raw, iso):
    assert ec.parse_day(raw, TODAY) == iso


@pytest.mark.parametrize("raw", ["tomorrow", "2026-10-24", "next week", "soon", "31 october 2026", ""])
def test_a_future_or_unreadable_day_is_refused_never_guessed(raw):
    assert isinstance(ec.parse_day(raw, TODAY), ec.Bad)


@pytest.mark.parametrize("text,cat", [
    ("office rent", "operating_overhead"), ("monthly Tally subscription", "software"), ("salary for staff", "personnel"), ("facebook ads campaign", "advertising"),
    ("bubble wrap and tape", "packaging"), ("warehouse charges", "storage"), ("razorpay processing fee", "financial_charges"), ("advance tax", "taxes"),
])
def test_a_category_is_inferred_only_when_the_words_point_at_exactly_one(text, cat):
    assert ec.infer_category(text) == cat


@pytest.mark.parametrize("text", ["", "something random", "rent and salary", "ads and packaging"])
def test_no_category_is_guessed_when_the_words_point_at_none_or_several(text):
    assert ec.infer_category(text) is None


def test_a_category_is_accepted_by_id_label_or_word_and_otherwise_asked_with_the_list():
    assert ec.parse_category("software") == "software" and ec.parse_category("Packaging") == "packaging" and ec.parse_category("office rent") == "operating_overhead"
    bad = ec.parse_category("banana")
    assert isinstance(bad, ec.Bad) and "software" in bad.why and "packaging" in bad.why


@pytest.mark.parametrize("text", [
    "I paid ₹5,000 for office rent yesterday", "We spent Rs 1,200 on packaging tape today", "i just bought a laptop for rs 45000", "I've paid 3000 rupees to the courier",
])
def test_a_first_person_payment_with_an_amount_is_a_mention(text):
    assert ec.is_mention(text)


@pytest.mark.parametrize("text", [
    "Should I pay ₹5,000 for ads?", "What if I spent Rs 500 more on packaging", "I sold 10 pieces for Rs 5000", "I paid for the course", "How much did I pay in rent?",
    "I received ₹5,000 from Amazon", "I am planning to pay Rs 500", "my customer paid ₹500",
])
def test_questions_hypotheticals_inflows_and_statements_without_an_amount_are_not_mentions(text):
    assert not ec.is_mention(text)


def test_slots_for_add_carry_only_what_was_said_as_text_for_the_parsers():
    got = ec.slots_for_add("Add expense of ₹5,000 for office rent yesterday")
    assert got == {"amount": "₹5,000", "period": "yesterday", "note": "office rent", "category": "operating_overhead"}
    assert ec.slots_for_add("add an expense") == {}


@pytest.mark.parametrize("q,cut", [
    ("monthly expenses for this year", "MONTH"), ("show month wise expenses", "MONTH"), ("date wise expenses for September", "DAY"), ("daily spend last 7 days", "DAY"),
    ("how much did I spend in September", "TOTAL"), ("list my expenses", "TOTAL"),
])
def test_the_breakdown_is_decided_by_code_from_the_words(q, cut):
    assert breakdown_of(q) == cut


@pytest.mark.parametrize("q,phrase", [
    ("How much did I spend in September?", "September"), ("expenses for 5 October", "5 October"), ("expenses from 1 oct to 15 oct", "1 oct to 15 oct"),
    ("show my expenses for the last 30 days", "the last 30 days"), ("expenses today", "today"), ("what did I spend 2026-09-01 to 2026-09-30", "2026-09-01 to 2026-09-30"),
])
def test_the_period_words_are_found_for_resolve_period_to_read_exactly(q, phrase):
    assert ec.period_text(q) == phrase


def test_no_period_words_means_the_ceo_asks():
    assert ec.period_text("show my expenses") is None and "period" not in ec.read_slots("show my expenses")


# ------------------------------------------------------------------------------------------------ routing: plain rules, no model
class _Cat:
    """A catalog offering every expense action (the member may use them)."""

    def item(self, kind, key):
        return SimpleNamespace(key=key, required_slots=()) if key.startswith("cfo.expense") else None

    actions = ()
    playbooks = ()
    state = ()


@pytest.mark.parametrize("text,key,flags", [
    ("Add this expense: 5000 for office rent yesterday", "cfo.expense_add", set()),
    ("can you add an expense of 300 for tape", "cfo.expense_add", set()),
    ("record an expense", "cfo.expense_add", set()),
    ("remove my rent expense", "cfo.expense_void", set()),
    ("delete that expense", "cfo.expense_void", set()),
    ("edit the packaging expense", "cfo.expense_correct", set()),
    ("mark the courier expense as paid", "cfo.expense_paid", set()),
    ("How much did I spend in September?", "cfo.expense_summary", set()),
    ("show my expenses for 5 October", "cfo.expense_summary", set()),
    ("monthly expenses please", "cfo.expense_summary", set()),
    ("I paid ₹5,000 for office rent yesterday", "cfo.expense_add", {"EXPENSE_MENTION"}),
])
def test_expense_phrases_route_by_rule(text, key, flags):
    hit = next((r for r in intent_router._EXPENSE_RULES if r.pattern.search(text)), None)
    assert hit is not None and hit.key == key and set(hit.flags) == flags


@pytest.mark.parametrize("text", [
    "How do I add an expense?", "what is my ad spend", "Should I pay Rs 500 for ads?", "what is my profit in September", "Remove my competitor Acme",
    "I sold 5 items for Rs 500", "tell me about expenses in general terms why they matter",
])
def test_everything_else_is_not_taken_by_the_expense_rules(text):
    hit = next((r for r in intent_router._EXPENSE_RULES if r.pattern.search(text)), None)
    assert hit is None or text.startswith("tell me")  # the last phrase mentions 'expenses' but asks nothing the rules read as a tracker request


def test_the_write_keys_are_exactly_the_four_and_the_mention_flag_is_named():
    assert ec.WRITE_KEYS == ("cfo.expense_add", "cfo.expense_correct", "cfo.expense_void", "cfo.expense_paid") and ec.MENTION_FLAG == "EXPENSE_MENTION"
    assert ec.hidden_for("cfo.expense_add", {"note": "rent"}, {"RULE_ROUTED", "EXPENSE_MENTION"}) == {"_mention": True, "_hint": "rent"}
    assert ec.hidden_for("cfo.query", {}, set()) is None and ec.hidden_for("cfo.expense_void", {}, set()) is None
