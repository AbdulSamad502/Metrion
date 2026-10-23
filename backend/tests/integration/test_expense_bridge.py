"""Expense Tracker -> CFO ledger bridge (docs/specs/cfo-expense-ledger.md 14.4): explicit, idempotent, never double counts, never silent. Real Postgres."""

from __future__ import annotations

import uuid
from datetime import date

from calc_engine.repositories import expense_ledger_repo as ledger_repo
from calc_engine.repositories import expense_tracker_repo as tracker
from calc_engine.repositories.expense_tracker_repo import NewRecord

from backend.services import expense_bridge
from tests.integration.test_cmo_api import _erase_cmo_rows, ctx_engine, env, fake_clerk  # noqa: F401


def seed(tenant, day, category, paise, *, vendor=None, treatment="incremental", review_state="confirmed"):
    kw = {"treatment": treatment} if treatment != "incremental" else {}
    res = tracker.insert_record(tenant, NewRecord(effective_date=day, category=category, cost_class="OVERHEAD", amount_paise=paise, vendor=vendor, **kw), review_state=review_state,
                                created_by=uuid.uuid4(), idempotency_key=None)
    return res.expense_id


def test_nothing_reaches_the_ledger_until_the_seller_syncs_and_a_second_sync_adds_nothing(env):  # noqa: F811
    t, who = env.tenant, uuid.uuid4()
    a = seed(t, date(2026, 9, 5), "software", 120_000, vendor="Zoho")
    seed(t, date(2026, 9, 6), "packaging", 80_000)
    before = expense_bridge.preview(t)
    assert before["toBring"] == 2 and before["alreadyInLedger"] == 0
    assert ledger_repo.list_entries(t, None, None) == []  # a preview adds nothing

    first = expense_bridge.sync(t, who)
    assert first["brought"] == 2 and first["alreadyInLedger"] == 0
    rows = ledger_repo.list_entries(t, None, None)
    assert sorted(r["amount_paise"] for r in rows) == [80_000, 120_000] and f"tracker:{a}" in {r["payment_ref"] for r in rows}

    again = expense_bridge.sync(t, who)
    assert again["brought"] == 0 and again["alreadyInLedger"] == 2
    assert len(ledger_repo.list_entries(t, None, None)) == 2  # no double counting


def test_a_bridged_entry_voided_in_the_ledger_is_not_added_back(env):  # noqa: F811
    t, who = env.tenant, uuid.uuid4()
    seed(t, date(2026, 9, 5), "software", 120_000)
    expense_bridge.sync(t, who)
    entry = ledger_repo.list_entries(t, None, None)[0]["id"]
    ledger_repo.void_entry(t, entry, who, "entered by mistake")
    assert expense_bridge.sync(t, who)["brought"] == 0


def test_drafts_and_non_costs_are_not_bridged_and_say_why(env):  # noqa: F811
    t = env.tenant
    seed(t, date(2026, 9, 2), "other", 50_000, treatment="informational")
    seed(t, date(2026, 9, 3), "other", 60_000, review_state="draft")
    out = expense_bridge.preview(t)
    reasons = " ".join(s["reason"] for s in out["notBridged"])
    assert "informational" in reasons and "draft" in reasons and out["toBring"] == 0


def test_another_tenants_tracker_entries_are_never_bridged(env):  # noqa: F811
    other, _ = env.other_tenant()
    seed(other, date(2026, 9, 5), "software", 120_000)
    assert expense_bridge.preview(env.tenant)["toBring"] == 0
    assert expense_bridge.sync(env.tenant, uuid.uuid4())["brought"] == 0


def test_the_trackers_payment_statement_travels_with_the_entry_and_unknown_stays_not_stated(env):  # noqa: F811
    t, who = env.tenant, uuid.uuid4()
    a = seed(t, date(2026, 9, 5), "software", 120_000)
    b = seed(t, date(2026, 9, 6), "packaging", 80_000)
    tracker.append_payment(t, a, payment_status="partially_paid", paid_amount_paise=50_000, created_by=who)
    expense_bridge.sync(t, who)
    rows = {r["payment_ref"]: r for r in ledger_repo.list_entries(t, None, None)}
    assert rows[f"tracker:{b}"]["payment_status"] is None  # never stated: not assumed unpaid or paid
    assert (rows[f"tracker:{a}"]["payment_status"], rows[f"tracker:{a}"]["paid_amount_paise"]) == ("PARTIALLY_PAID", 50_000)
