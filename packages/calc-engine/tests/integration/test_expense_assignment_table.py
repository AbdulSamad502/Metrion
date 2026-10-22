"""`expense_assignment` (migration 0015/0016): the basis check accepts the five bases and nothing else, the table stays append-only for the application role, and
assignments never cross tenants."""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from sqlalchemy import text

from calc_engine.formulas.expense_assignment import SkuAssignment
from calc_engine.repositories import expense_ledger_repo as repo
from calc_engine.repositories.expense_ledger_repo import NewRecord
from calc_engine.repositories.tenant_context import tenant_scope

USER = uuid.uuid4()


def record(tenant):
    return repo.insert_record(tenant, NewRecord(effective_date=date(2026, 9, 1), category="advertising", cost_class="ADVERTISING", amount_paise=1_000), review_state="confirmed", created_by=USER).expense_id


@pytest.mark.parametrize("basis,shares", [("EQUAL", (("A", None), ("B", None))), ("EXPLICIT_SHARES", (("A", 4_000), ("B", 6_000))), ("NET_REVENUE", (("A", None),)), ("UNITS", (("A", None), ("B", None))), ("ORDERS", (("A", None),))])
def test_every_supported_basis_is_stored_and_read_back(two_tenants, basis, shares):
    a, _ = two_tenants
    eid = record(a)
    repo.assign_skus(a, eid, SkuAssignment(basis, shares), created_by=USER)
    assert repo.get_assignment(a, eid) == SkuAssignment(basis, shares)


def test_an_unknown_basis_is_refused_by_the_database(two_tenants):
    a, _ = two_tenants
    eid = record(a)
    with pytest.raises(Exception):
        repo.assign_skus(a, eid, SkuAssignment("MAGIC", (("A", None),)), created_by=USER)
    assert repo.get_assignment(a, eid) is None


def test_the_newest_choice_wins_and_the_application_role_cannot_rewrite_history(two_tenants):
    a, _ = two_tenants
    eid = record(a)
    repo.assign_skus(a, eid, SkuAssignment("UNITS", (("A", None), ("B", None))), created_by=USER)
    repo.assign_skus(a, eid, SkuAssignment("EQUAL", (("A", None), ("B", None))), created_by=USER)
    assert repo.get_assignment(a, eid).basis == "EQUAL"
    for sql in ("UPDATE expense_assignment SET basis = 'ORDERS'", "DELETE FROM expense_assignment"):
        with pytest.raises(Exception):
            with tenant_scope(a) as conn:
                conn.execute(text(sql))


def test_tenants_are_isolated(two_tenants):
    a, b = two_tenants
    eid = record(a)
    repo.assign_skus(a, eid, SkuAssignment("ORDERS", (("A", None),)), created_by=USER)
    assert repo.get_assignment(b, eid) is None
    with pytest.raises(Exception):
        repo.assign_skus(b, eid, SkuAssignment("ORDERS", (("A", None),)), created_by=USER)  # the record is not this tenant's
