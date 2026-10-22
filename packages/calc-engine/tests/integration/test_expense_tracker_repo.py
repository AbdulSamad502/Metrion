"""`expense_tracker_repo` against a real Postgres (kickoff S3b): append-only writes, current state from the latest status events, linked corrections and
refunds, idempotent replay, filters and tenant isolation. No arithmetic: the repository stores and reads; totals come from the engine feed."""

from __future__ import annotations

import uuid
from datetime import date

import pytest

from calc_engine.repositories import expense_tracker_repo as repo
from calc_engine.repositories.expense_tracker_repo import NewRecord

USER = uuid.uuid4()


def rec(**kw) -> NewRecord:
    base = dict(effective_date=date(2026, 9, 10), vendor="Acme", description="rent", category="operating_overhead", cost_class="OVERHEAD",
                treatment="incremental", amount_paise=10_000)
    base.update(kw)
    return NewRecord(**base)


def add(tenant, record=None, *, review="confirmed", **kw):
    return repo.insert_record(tenant, record or rec(), review_state=review, created_by=USER, **kw)


def test_insert_creates_the_record_with_its_two_initial_statuses(two_tenants):
    a, _ = two_tenants
    r = add(a)
    assert r.replayed is False
    row = repo.get_record(a, r.expense_id)
    assert row["amount_paise"] == 10_000 and row["review_state"] == "confirmed" and row["payment_status"] == "unknown"
    assert [h["kind"] for h in row["history"]] == ["REVIEW", "PAYMENT"]


def test_the_same_idempotency_key_replays_and_creates_nothing(two_tenants):
    a, _ = two_tenants
    first = add(a, idempotency_key="k-1")
    second = add(a, idempotency_key="k-1")
    assert second.replayed is True and second.expense_id == first.expense_id
    assert len(repo.list_records(a)[0]) == 1


def test_status_changes_append_events_and_the_latest_wins(two_tenants):
    a, _ = two_tenants
    r = add(a, review="pending_review")
    repo.append_review(a, r.expense_id, review_state="confirmed", reason=None, created_by=USER)
    repo.append_payment(a, r.expense_id, payment_status="partially_paid", paid_amount_paise=2_500, created_by=USER)
    repo.append_payment(a, r.expense_id, payment_status="paid", paid_amount_paise=10_000, created_by=USER)
    row = repo.get_record(a, r.expense_id)
    assert (row["review_state"], row["payment_status"], row["paid_amount_paise"]) == ("confirmed", "paid", 10_000)
    assert len(row["history"]) == 5  # nothing was updated in place


def test_a_status_event_replays_by_its_key(two_tenants):
    a, _ = two_tenants
    r = add(a)
    assert repo.append_payment(a, r.expense_id, payment_status="paid", paid_amount_paise=1, created_by=USER, idempotency_key="p1") is False
    assert repo.append_payment(a, r.expense_id, payment_status="paid", paid_amount_paise=1, created_by=USER, idempotency_key="p1") is True
    assert len(repo.get_record(a, r.expense_id)["history"]) == 3


def test_void_is_a_status_event_and_the_record_stays(two_tenants):
    a, _ = two_tenants
    r = add(a)
    repo.append_review(a, r.expense_id, review_state="voided", reason="entered twice", created_by=USER)
    row = repo.get_record(a, r.expense_id)
    assert row["review_state"] == "voided" and row["review_reason"] == "entered twice"
    rows, total = repo.list_records(a)
    assert total == 0 and rows == []                                # hidden by default
    rows, total = repo.list_records(a, include_voided=True)
    assert total == 1


def test_a_correction_is_a_new_linked_record_and_voids_the_original(two_tenants):
    a, _ = two_tenants
    original = add(a)
    fixed = repo.insert_record(
        a, rec(amount_paise=12_000, corrects_expense_id=original.expense_id), review_state="confirmed", created_by=USER,
        void_original=(original.expense_id, f"corrected"),
    )
    assert repo.get_record(a, original.expense_id)["review_state"] == "voided"
    new = repo.get_record(a, fixed.expense_id)
    assert new["corrects_expense_id"] == original.expense_id and new["amount_paise"] == 12_000
    rows, total = repo.list_records(a)
    assert [r["id"] for r in rows] == [fixed.expense_id] and total == 1


def test_a_refund_is_a_negative_linked_record(two_tenants):
    a, _ = two_tenants
    original = add(a)
    refund = add(a, rec(amount_paise=-4_000, refund_of_expense_id=original.expense_id, effective_date=date(2026, 10, 3)))
    row = repo.get_record(a, refund.expense_id)
    assert row["refund_of_expense_id"] == original.expense_id and row["amount_paise"] == -4_000


def test_filters_and_paging(two_tenants):
    a, _ = two_tenants
    add(a, rec(effective_date=date(2026, 9, 1), category="software", amount_paise=100))
    add(a, rec(effective_date=date(2026, 9, 15), category="advertising", cost_class="ADVERTISING", amount_paise=200), review="pending_review")
    add(a, rec(effective_date=date(2026, 10, 2), category="software", amount_paise=300))
    rows, total = repo.list_records(a, date_from=date(2026, 9, 1), date_to=date(2026, 9, 30))
    assert total == 2
    assert repo.list_records(a, category="software")[1] == 2
    assert repo.list_records(a, cost_class="ADVERTISING")[1] == 1
    assert repo.list_records(a, review_state="pending_review")[1] == 1
    page, total = repo.list_records(a, limit=2, offset=0)
    assert len(page) == 2 and total == 3
    assert [r["effective_date"] for r in page] == [date(2026, 10, 2), date(2026, 9, 15)]  # newest first


def test_tenants_are_isolated(two_tenants):
    a, b = two_tenants
    r = add(a)
    assert repo.get_record(b, r.expense_id) is None
    assert repo.list_records(b)[1] == 0
    with pytest.raises(LookupError):
        repo.append_review(b, r.expense_id, review_state="confirmed", reason=None, created_by=USER)
