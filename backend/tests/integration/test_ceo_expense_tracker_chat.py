"""The expense conversation through the CEO against the CFO ledger, real Postgres + the real registry and approval flow (docs/specs/ceo-expense-tracker-chat.md AC-X1..X12, re-pointed 2026-10-23).

The seller talks only to the CEO: reads come back with planner results (a stored engine result per figure) and per-entry references; every write is a stored plan card that saves NOTHING
until the Approve call (a typed yes is only text). Classification here is by plain rules, so no model is consulted. The ledger is the authoritative expense source: nothing in this file
touches the Expense Tracker's tables."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from calc_engine.expense_ledger import NewEntry
from calc_engine.repositories import expense_ledger_repo as ledger

from backend.auth.permissions import PARTNER_ROLE
from backend.repositories import investigation_plan_repo as plan_repo
from backend.services import expense_bridge
from tests.integration.test_ceo_cmo_delegation import approve, chat, messages, new_investigation, say  # noqa: F401
from tests.integration.test_cmo_api import _erase_cmo_rows, _login, ctx_engine, env, fake_clerk  # noqa: F401

USER = uuid.uuid4()


def seed(tenant: uuid.UUID, day: date, category: str, paise: int, *, vendor: str | None = None) -> uuid.UUID:
    """An entry in the ledger, the way the chat would have written it (the category is the closed-list label)."""
    res = ledger.add_entries(tenant, [NewEntry(entry_date=day, amount_paise=paise, category=expense_bridge.category_name(category), vendor=vendor)], USER)
    assert res.inserted_ids, "the seed entry was not stored"
    return res.inserted_ids[0]


def events(c) -> int:
    """How many rows the ledger holds (every write adds exactly one row; nothing is ever updated or deleted)."""
    return c.env.n("expense_entry")


def yesterday() -> date:
    return datetime.now(timezone.utc).date() - timedelta(days=1)


def plan_of(r) -> dict:
    assert r["status"] == "PLANNED", r
    return r["plan"]


# ================================================================================================ add
def test_add_an_expense_ask_card_nothing_saved_typed_yes_saves_nothing_approve_saves_exactly_once(chat):
    c = chat
    inv = new_investigation(c)
    r = say(c, inv, "Add an expense of ₹5,000 for office rent yesterday")
    assert r["status"] == "CLARIFIED" and "paid to" in r["answer"].lower(), r  # amount, day, category and note were said; only the optional vendor is asked
    planned = say(c, inv, "skip")
    plan = plan_of(planned)
    leg = plan["plan"]["legs"][0]
    assert leg["action_key"] == "cfo.expense_add" and plan["status"] == "AWAITING_APPROVAL"
    assert leg["slots"]["amount_paise"] == 500_000 and leg["slots"]["category"] == "operating_overhead" and leg["slots"]["effective_date"] == yesterday().isoformat()
    assert leg["slots"]["description"] == "office rent" and leg["slots"]["request_key"] == f"ceo-plan-{plan['id']}"
    compact = plan["plan"]["compact_lines"]
    assert compact[0] == "Add an expense to your expense ledger:" and "Amount: ₹5,000.00" in compact and "Saved only when you press Approve." in compact
    assert events(c) == 0  # the card is only a promise
    for typed in ("yes", "go ahead", "approve it"):
        say(c, inv, typed)
    assert events(c) == 0 and plan_repo.get(c.env.tenant, uuid.UUID(inv), uuid.UUID(plan["id"]))["status"] == "AWAITING_APPROVAL"

    r = approve(c, inv, plan)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "DELIVERED" and body["plan"]["status"] == "APPROVED" and events(c) == 1
    assert "saved to your expense ledger" in body["answer"] and "₹5,000.00" in body["answer"]
    assert "no confirmed class" in body["answer"]  # an honest note: it is recorded, but it does not change Operating Profit until the seller confirms its class
    row = ledger.list_entries(c.env.tenant, None, None)[0]
    assert (row["amount_paise"], row["category"], row["entry_date"], row["source"]) == (500_000, "Operating overhead", yesterday(), "MANUAL") and row["confirmed_class"] is None
    again = approve(c, inv, plan)  # a double click
    assert again.status_code == 200 and events(c) == 1


def test_the_same_expense_added_twice_is_held_as_a_possible_duplicate_not_counted_twice(chat):
    c = chat
    seed(c.env.tenant, yesterday(), "operating_overhead", 500_000)
    inv = new_investigation(c)
    say(c, inv, "Add an expense of ₹5,000 for office rent yesterday")
    plan = plan_of(say(c, inv, "skip"))
    body = approve(c, inv, plan).json()
    assert "possible duplicate" in body["answer"] and events(c) == 2
    held = [r for r in ledger.list_entries(c.env.tenant, None, None) if r["hold"] != "NONE"]
    assert len(held) == 1  # stored, but on hold: it is in no total until the seller reviews it


def test_a_declined_card_saves_nothing_and_an_unknown_category_is_asked_never_guessed(chat):
    c = chat
    inv = new_investigation(c)
    r = say(c, inv, "add an expense")
    assert r["status"] == "CLARIFIED" and "how much" in r["answer"].lower()
    assert say(c, inv, "five thousand")["status"] == "CLARIFIED"  # not an exact amount: asked again, with the reason
    assert "could not read" in say(c, inv, "12ab")["answer"].lower()
    say(c, inv, "1,200")
    assert "day" in say(c, inv, "next week")["answer"].lower()  # a day that cannot be read is refused, not defaulted
    say(c, inv, "today")
    cat = say(c, inv, "banana")
    assert cat["status"] == "CLARIFIED" and "could not tell which category" in cat["answer"]
    say(c, inv, "software")
    say(c, inv, "skip")  # vendor
    plan = plan_of(say(c, inv, "skip"))  # note
    assert plan["plan"]["legs"][0]["slots"]["category"] == "software" and plan["plan"]["legs"][0]["slots"]["amount_paise"] == 120_000
    declined = c.client.post(f"/api/v1/ceo/investigations/{inv}/plans/{plan['id']}/decline", json={}, headers=c.env.headers)
    assert declined.status_code == 200 and events(c) == 0
    assert approve(c, inv, plan).status_code in (404, 409, 410, 422)  # a declined card can never be approved
    assert events(c) == 0


def test_cancel_stops_the_questions_and_saves_nothing(chat):
    c = chat
    inv = new_investigation(c)
    say(c, inv, "add an expense")
    r = say(c, inv, "never mind")
    assert "Nothing was run and nothing was saved" in r["answer"] and events(c) == 0


# ================================================================================================ read: totals come from the engine, entries cite their record
def test_how_much_did_i_spend_in_a_month_uses_the_planners_engine_total_and_cites_each_entry(chat):
    c = chat
    t = c.env.tenant
    seed(t, date(2026, 9, 5), "operating_overhead", 500_000, vendor="Landlord")
    seed(t, date(2026, 9, 20), "software", 120_000)
    seed(t, date(2026, 10, 2), "advertising", 999_900)
    inv = new_investigation(c)
    r = say(c, inv, "How much did I spend in September 2026?")
    assert r["status"] == "DELIVERED", r
    a = r["answer"]
    assert "₹6,200.00" in a  # the engine's total for September: 5,000.00 + 1,200.00
    assert "₹9,999.00" not in a  # October's entry is outside the period
    assert "₹5,000.00" in a and "₹1,200.00" in a  # each entry is shown through a reference to its own entry
    assert c.env.n("metric_result", "metric_code = 'EXPENSE_BY_CATEGORY'") >= 1  # the total is a stored engine result with a reference, not text


def test_month_wise_and_date_wise_cut_the_range_by_code(chat):
    c = chat
    t = c.env.tenant
    seed(t, date(2026, 9, 5), "operating_overhead", 500_000)
    seed(t, date(2026, 10, 2), "software", 120_000)
    seed(t, date(2026, 10, 9), "software", 30_000)
    inv = new_investigation(c)
    monthly = say(c, inv, "month wise expenses from 1 september 2026 to 31 october 2026")["answer"]
    assert "₹5,000.00" in monthly and "₹1,500.00" in monthly  # one engine total per month: September, then October (1,200.00 + 300.00)
    daily = say(c, inv, "date wise expenses from 1 october 2026 to 31 october 2026")["answer"]
    assert "₹1,200.00" in daily and "₹300.00" in daily and "₹1,500.00" not in daily  # one engine total per day that has entries; the two October days are NOT merged into one monthly figure


def test_an_empty_period_is_said_to_be_empty_never_zero(chat):
    c = chat
    inv = new_investigation(c)
    r = say(c, inv, "how much did I spend in March 2026?")
    assert r["status"] == "DELIVERED" and "no expenses recorded" in r["answer"] and "₹0" not in r["answer"]


def test_a_question_without_a_period_asks_for_it_and_reads_nothing(chat):
    c = chat
    inv = new_investigation(c)
    r = say(c, inv, "show my expenses")
    assert r["status"] == "CLARIFIED" and "Which period" in r["answer"]


def test_one_sellers_entries_never_appear_for_another(chat):
    c = chat
    other_id, other_headers = c.env.other_tenant()
    seed(other_id, date(2026, 9, 5), "operating_overhead", 777_700, vendor="Secret Landlord")
    seed(c.env.tenant, date(2026, 9, 6), "software", 100_000)
    inv = new_investigation(c)
    a = say(c, inv, "How much did I spend in September 2026?")["answer"]
    assert "₹7,777.00" not in a and "Secret Landlord" not in a and "₹1,000.00" in a


# ================================================================================================ remove, change, mark paid: the seller picks one of THEIR entries
def test_remove_an_expense_needs_a_reason_kept_with_the_removal_and_it_leaves_the_totals(chat):
    c = chat
    t = c.env.tenant
    rent = seed(t, date(2026, 9, 5), "operating_overhead", 500_000, vendor="Landlord")
    seed(t, date(2026, 9, 20), "software", 120_000)
    inv = new_investigation(c)
    r = say(c, inv, "remove my software expense")
    assert r["status"] == "CLARIFIED" and "why are you removing it" in r["answer"].lower(), r  # one entry matches 'software': picked without asking which
    assert say(c, inv, "ok")["status"] == "CLARIFIED"  # a reason of a word or two is not a reason: asked again
    plan = plan_of(say(c, inv, "Entered by mistake"))
    leg = plan["plan"]["legs"][0]
    assert leg["action_key"] == "cfo.expense_void" and leg["slots"]["reason"] == "Entered by mistake" and leg["slots"]["expense_id"] != str(rent)
    assert "Remove this expense:" in plan["plan"]["compact_lines"][0] and "₹1,200.00" in plan["plan"]["compact_lines"][0]
    assert c.env.n("expense_entry", "is_void") == 0  # nothing yet
    body = approve(c, inv, plan).json()
    assert body["status"] == "DELIVERED" and "removed from your totals" in body["answer"]
    assert c.env.n("expense_entry", "is_void AND void_reason = 'Entered by mistake'") == 1  # the reason is kept with the removal (audit); the original row is still in the history
    assert events(c) == 3
    after = say(c, inv, "How much did I spend in September 2026?")["answer"]
    assert "₹5,000.00" in after and "₹1,200.00" not in after  # the removed entry is out of the answer


def test_two_matching_entries_are_offered_to_pick_never_chosen_for_the_seller(chat):
    c = chat
    t = c.env.tenant
    seed(t, date(2026, 9, 5), "operating_overhead", 500_000)
    seed(t, date(2026, 10, 5), "operating_overhead", 510_000)
    inv = new_investigation(c)
    r = say(c, inv, "delete an expense")
    assert r["status"] == "CLARIFIED" and "Which expense" in r["answer"]
    labels = [o["label"] for o in r["choices"]["options"] if o["kind"] in ("RECOMMENDED", "ALTERNATIVE")]
    assert len(labels) == 2 and any("₹5,000.00" in l for l in labels) and any("₹5,100.00" in l for l in labels)


def test_with_no_expenses_there_is_nothing_to_change_and_it_says_so(chat):
    c = chat
    inv = new_investigation(c)
    r = say(c, inv, "remove an expense")
    assert "no expenses in your expense ledger yet" in r["answer"] and events(c) == 0


def test_change_an_expense_keeps_the_original_in_the_history_and_replaces_it(chat):
    c = chat
    t = c.env.tenant
    seed(t, date(2026, 9, 5), "software", 120_000, vendor="Zoho")
    inv = new_investigation(c)
    r = say(c, inv, "change my software expense")
    assert r["status"] == "CLARIFIED"
    r = say(c, inv, "1500")  # the correct amount
    for _ in range(4):  # day, category, vendor: 'same' keeps the stored value
        if r["status"] == "PLANNED":
            break
        r = say(c, inv, "same")
    plan = plan_of(r)
    s = plan["plan"]["legs"][0]["slots"]
    assert plan["plan"]["legs"][0]["action_key"] == "cfo.expense_correct" and s["amount_paise"] == 150_000 and s["category"] == "software" and s["effective_date"] == "2026-09-05" and s["vendor"] == "Zoho"
    approve(c, inv, plan)
    assert events(c) == 2 and len(ledger.list_entries(t, None, None)) == 1  # the new entry replaces the original, which stays in the history
    assert "₹1,500.00" in say(c, inv, "How much did I spend in September 2026?")["answer"]


@pytest.mark.parametrize("answer,status,paid", [("paid", "PAID", None), ("unpaid", "UNPAID", None)])
def test_mark_an_expense_paid_or_unpaid_changes_only_its_payment_state(chat, answer, status, paid):
    c = chat
    seed(c.env.tenant, date(2026, 9, 5), "operating_overhead", 500_000)
    inv = new_investigation(c)
    r = say(c, inv, "mark my rent expense as paid")
    assert r["status"] == "CLARIFIED" and "paid, unpaid or partially paid" in r["answer"]
    plan = plan_of(say(c, inv, answer))
    assert plan["plan"]["legs"][0]["action_key"] == "cfo.expense_paid" and plan["plan"]["legs"][0]["slots"]["status"] == {"paid": "paid", "unpaid": "unpaid"}[answer]
    body = approve(c, inv, plan).json()
    assert "payment status was updated" in body["answer"] and c.env.n("expense_payment_event", f"payment_status = '{status}'") == 1
    assert events(c) == 1  # no new entry


def test_a_partly_paid_expense_names_how_much_was_paid_and_it_must_be_less_than_the_whole(chat):
    c = chat
    seed(c.env.tenant, date(2026, 9, 5), "operating_overhead", 500_000)
    inv = new_investigation(c)
    say(c, inv, "mark my rent expense as paid")
    r = say(c, inv, "partially paid")
    assert r["status"] == "CLARIFIED" and "how much" in r["answer"].lower()
    plan = plan_of(say(c, inv, "2,000"))
    assert plan["plan"]["legs"][0]["slots"]["status"] == "partially_paid" and plan["plan"]["legs"][0]["slots"]["paid_amount_paise"] == 200_000
    body = approve(c, inv, plan).json()
    assert c.env.n("expense_payment_event", "payment_status = 'PARTIALLY_PAID' AND paid_amount_paise = 200000") == 1 and "payment status was updated" in body["answer"]


def test_a_partial_payment_of_the_whole_amount_or_more_is_refused_and_nothing_is_saved(chat):
    c = chat
    seed(c.env.tenant, date(2026, 9, 5), "operating_overhead", 500_000)
    inv = new_investigation(c)
    say(c, inv, "mark my rent expense as paid")
    say(c, inv, "partially paid")
    plan = plan_of(say(c, inv, "5,000"))  # equal to the whole expense: the ledger will not accept it as "partly"
    body = approve(c, inv, plan).json()
    assert "did not save" in body["answer"] and c.env.n("expense_payment_event") == 0


# ================================================================================================ the seller only MENTIONS an expense
def test_a_mention_is_answered_with_a_question_and_saves_nothing_on_no(chat):
    c = chat
    inv = new_investigation(c)
    r = say(c, inv, "I paid ₹5,000 for office rent yesterday")
    assert r["status"] == "CLARIFIED" and "Is this an expense of yours" in r["answer"] and "nothing is saved until you press Approve" in r["answer"], r
    assert "₹5,000.00" in r["answer"] and events(c) == 0
    stop = say(c, inv, "no thanks")
    assert "Nothing was run and nothing was saved" in stop["answer"] and events(c) == 0
    assert c.env.n("investigation_plan") == 0


def test_a_mention_then_yes_collects_the_rest_and_ends_in_a_card_never_a_save(chat):
    c = chat
    inv = new_investigation(c)
    say(c, inv, "I paid Rs 800 for packaging tape today")
    r = say(c, inv, "yes")
    assert r["status"] == "CLARIFIED"  # the vendor is the only thing not already said
    plan = plan_of(say(c, inv, "skip"))
    s = plan["plan"]["legs"][0]["slots"]
    assert (s["amount_paise"], s["category"]) == (80_000, "packaging") and events(c) == 0
    approve(c, inv, plan)
    assert events(c) == 1


@pytest.mark.parametrize("text", ["Should I pay Rs 5000 for ads?", "I sold 10 items for Rs 5000", "How much did I pay in rent last month?", "I paid for the course"])
def test_questions_hypotheticals_and_sales_never_trigger_the_mention_question(chat, text):
    c = chat
    inv = new_investigation(c)
    r = say(c, inv, text)
    assert "Is this an expense of yours" not in r["answer"] and events(c) == 0


# ================================================================================================ who may do what
def test_a_member_without_financials_adjust_cannot_start_a_write_and_nothing_is_prepared(chat):
    c = chat
    reader, _ = _login(c.env.fake_clerk, c.env.tenant, role=PARTNER_ROLE, permissions={"agent.ceo": True, "agent.cfo": True, "investigation.view": True, "investigation.create": True})
    inv = new_investigation(c, headers=reader)
    r = say(c, inv, "add an expense of 500 for tape", headers=reader)
    assert r.get("plan") is None and "How much" not in r["answer"]
    assert events(c) == 0 and c.env.n("investigation_plan") == 0


def test_a_forged_expense_id_from_another_tenant_is_refused_when_picking(chat):
    from backend.ceo import expense_chat as ec

    other_id, _ = chat.env.other_tenant()
    foreign = seed(other_id, date(2026, 9, 5), "software", 100_000)
    got = ec.parse_pick(str(foreign), chat.env.tenant)
    assert isinstance(got, ec.Bad)  # another tenant's id is indistinguishable from an unknown one


def test_the_chat_never_accepts_a_record_id_typed_into_the_message(chat):
    c = chat
    inv = new_investigation(c)
    mine = seed(c.env.tenant, date(2026, 9, 5), "software", 100_000)
    r = say(c, inv, f"remove expense {uuid.uuid4()}")
    assert r["status"] == "CLARIFIED"  # a random id picks nothing: the seller is shown their own entries
    assert any(str(mine) == o["value"] for o in r["choices"]["options"] if o.get("value"))
