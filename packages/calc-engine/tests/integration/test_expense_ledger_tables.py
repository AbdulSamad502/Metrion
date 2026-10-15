"""Expense ledger tables (kickoff S3a; expense-tracker.md §5.1; EXP-01, EXP-05, Round 6/9) against a real Postgres.

`expense_event` holds the immutable content of one ledger record; `expense_status_event` holds the append-only review-state and payment-status
history. Both are tenant-owned, FORCE RLS, and UPDATE/DELETE are revoked from the application role (grant level, not just application code).
"""

from __future__ import annotations

import uuid
from datetime import date
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from calc_engine.repositories.tenant_context import tenant_scope

_PACKAGE_ROOT = Path(__file__).resolve().parents[2]
_LEDGER = ("expense_event", "expense_status_event")
_USER = uuid.uuid4()

_EVENT_SQL = text(
    """
    INSERT INTO expense_event (id, tenant_id, effective_date, vendor, description, category, cost_class, treatment, amount_paise,
                               channel_scope, sku, origin, source_validated, identifier, source_reference, corrects_expense_id,
                               refund_of_expense_id, recurring, idempotency_key, created_by)
    VALUES (:id, :tenant, :day, :vendor, :description, :category, :cost_class, :treatment, :amount,
            :channel, :sku, :origin, :validated, :identifier, :source, :corrects, :refund, :recurring, :idem, :user)
    """
)
_STATUS_SQL = text(
    """
    INSERT INTO expense_status_event (tenant_id, expense_id, kind, review_state, payment_status, paid_amount_paise, reason, idempotency_key, created_by)
    VALUES (:tenant, :expense, :kind, :review, :payment, :paid, :reason, :idem, :user)
    """
)


def add_event(tenant, *, amount=10_000, eid=None, **kw):
    eid = eid or uuid.uuid4()
    params = dict(
        id=str(eid), tenant=str(tenant), day=date(2026, 9, 10), vendor="Acme", description="rent", category="rent", cost_class="OVERHEAD",
        treatment="incremental", amount=amount, channel=None, sku=None, origin="MANUAL", validated=False, identifier=None, source="manual",
        corrects=None, refund=None, recurring=False, idem=None, user=str(_USER),
    )
    params.update(kw)
    with tenant_scope(tenant) as conn:
        conn.execute(_EVENT_SQL, params)
    return eid


def add_status(tenant, expense, **kw):
    params = dict(tenant=str(tenant), expense=str(expense), kind="REVIEW", review="confirmed", payment=None, paid=None, reason=None, idem=None, user=str(_USER))
    params.update(kw)
    with tenant_scope(tenant) as conn:
        conn.execute(_STATUS_SQL, params)


def test_the_ledger_tables_exist_with_forced_rls(migrate_engine):
    inspector = inspect(migrate_engine)
    assert set(_LEDGER) <= set(inspector.get_table_names())
    with migrate_engine.connect() as conn:
        forced = conn.execute(text("SELECT relname FROM pg_class WHERE relforcerowsecurity = true AND relname = ANY(:n)").bindparams(n=list(_LEDGER))).fetchall()
    assert {r[0] for r in forced} == set(_LEDGER)


def test_a_tenant_sees_only_its_own_rows_and_no_context_sees_none(two_tenants, app_engine):
    a, b = two_tenants
    eid = add_event(a)
    add_status(a, eid)
    with tenant_scope(b) as conn:
        assert conn.execute(text("SELECT count(*) FROM expense_event")).scalar_one() == 0
        assert conn.execute(text("SELECT count(*) FROM expense_status_event")).scalar_one() == 0
    with tenant_scope(a) as conn:
        assert conn.execute(text("SELECT count(*) FROM expense_event")).scalar_one() == 1
    with app_engine.connect() as conn:  # no app.current_tenant_id at all: fail closed
        assert conn.execute(text("SELECT count(*) FROM expense_event")).scalar_one() == 0


def test_a_row_for_another_tenant_cannot_be_written(two_tenants):
    a, b = two_tenants
    with pytest.raises(DBAPIError):
        with tenant_scope(a) as conn:
            conn.execute(_EVENT_SQL, dict(id=str(uuid.uuid4()), tenant=str(b), day=date(2026, 9, 10), vendor=None, description=None, category="rent",
                                         cost_class="OVERHEAD", treatment="incremental", amount=1, channel=None, sku=None, origin="MANUAL", validated=False,
                                         identifier=None, source=None, corrects=None, refund=None, recurring=False, idem=None, user=str(_USER)))


@pytest.mark.parametrize("table,statement", [
    ("expense_event", "UPDATE expense_event SET vendor = 'x'"),
    ("expense_event", "DELETE FROM expense_event"),
    ("expense_status_event", "UPDATE expense_status_event SET reason = 'x'"),
    ("expense_status_event", "DELETE FROM expense_status_event"),
])
def test_update_and_delete_are_denied_at_the_grant_level(two_tenants, table, statement):
    a, _ = two_tenants
    eid = add_event(a)
    add_status(a, eid)
    with pytest.raises(DBAPIError) as err:
        with tenant_scope(a) as conn:
            conn.execute(text(statement))
    assert "permission denied" in str(err.value).lower()


@pytest.mark.parametrize("field,value", [
    ("treatment", "replaces_input"),       # dropped by EXP-01
    ("cost_class", "COGS"),                # COGS stays cogs_per_unit, never an expense amount
    ("origin", "BANK"),
])
def test_enumerations_are_closed(two_tenants, field, value):
    a, _ = two_tenants
    with pytest.raises(IntegrityError):
        add_event(a, **{field: value})


def test_the_status_event_shape_is_enforced(two_tenants):
    a, _ = two_tenants
    eid = add_event(a)
    for bad in (
        dict(kind="REVIEW", review="approved"),                        # not a review state
        dict(kind="PAYMENT", review=None, payment="settled"),          # not a payment status
        dict(kind="REVIEW", review="confirmed", payment="paid"),       # both set
        dict(kind="PAYMENT", review="confirmed", payment="paid"),      # wrong column for the kind
        dict(kind="REVIEW", review="voided", reason=None),             # a void needs a reason
    ):
        with pytest.raises(IntegrityError):
            add_status(a, eid, **bad)
    add_status(a, eid, kind="REVIEW", review="voided", reason="duplicate entry")
    add_status(a, eid, kind="PAYMENT", review=None, payment="partially_paid", paid=2_500)


def test_a_refund_is_negative_and_linked_and_amounts_are_signed(two_tenants):
    a, _ = two_tenants
    original = add_event(a, amount=10_000)
    add_event(a, amount=-4_000, refund=str(original))      # a refund / credit note: negative, linked
    with pytest.raises(IntegrityError):
        add_event(a, amount=4_000, refund=str(original))   # a "refund" that is positive is refused
    with pytest.raises(IntegrityError):
        add_event(a, amount=-1, refund=str(original), corrects=str(original))  # one record cannot be both


def test_links_cannot_cross_tenants(two_tenants):
    a, b = two_tenants
    original = add_event(a)
    with pytest.raises(IntegrityError):
        add_event(b, amount=-1, refund=str(original))       # tenant B cannot link to tenant A's record
    with pytest.raises(IntegrityError):
        add_event(a, corrects=str(uuid.uuid4()))            # nor to a record that does not exist


def test_an_idempotency_key_is_unique_per_tenant(two_tenants):
    a, b = two_tenants
    add_event(a, idem="k1")
    with pytest.raises(IntegrityError):
        add_event(a, idem="k1")
    add_event(b, idem="k1")  # the same key in another tenant is a different record
    add_event(a)             # no key: unlimited


def _cfg() -> Config:
    cfg = Config(str(_PACKAGE_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_PACKAGE_ROOT / "migrations"))
    return cfg


def test_zz_downgrade_then_upgrade_round_trips_the_ledger_tables(migrate_engine):
    cfg = _cfg()
    command.downgrade(cfg, "20260929_0012")
    assert not (set(_LEDGER) & set(inspect(migrate_engine).get_table_names())), "downgrade left ledger tables behind"
    command.upgrade(cfg, "head")
    assert set(_LEDGER) <= set(inspect(migrate_engine).get_table_names())
    with migrate_engine.connect() as conn:
        forced = conn.execute(text("SELECT relname FROM pg_class WHERE relforcerowsecurity = true AND relname = ANY(:n)").bindparams(n=list(_LEDGER))).fetchall()
        for t in _LEDGER:
            assert not conn.execute(text("SELECT has_table_privilege('metrion_app', CAST(:t AS regclass), 'UPDATE')"), {"t": t}).scalar_one()
            assert not conn.execute(text("SELECT has_table_privilege('metrion_app', CAST(:t AS regclass), 'DELETE')"), {"t": t}).scalar_one()
    assert {r[0] for r in forced} == set(_LEDGER)
