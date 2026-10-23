"""The expense ledger over HTTP and through the planner, real Postgres (docs/specs/cfo-expense-ledger.md AC-L1…L11).

Routes: permission and entitlement gates, plain-language refusals, suggestion-only classes, holds. Planner: operating profit and the expense breakdown
come from the ledger and Contribution Profit through Brain 1, and a ledger write invalidates a cached answer."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

import pytest
from sqlalchemy import text

from calc_engine.repositories import read_model_version_repo
from cfo.planner.cache_store import InMemoryEvidenceCache
from cfo.planner.pipeline import MockPlannerProvider, PlannerAnswer
from cfo.planner.plan import PeriodRef

from backend.services.cfo_query import answer_financial_query
from tests.integration.test_cfo_query_planner import SEP, _cogs, _file_and_run, _line, plan

_AS_OF = date(2026, 10, 1)


@pytest.fixture
def app_client():
    from fastapi.testclient import TestClient

    from backend.main import app

    return TestClient(app)


@pytest.fixture
def fake_clerk(monkeypatch):
    from dataclasses import dataclass, field
    from typing import Any

    from backend.auth import context as auth_context_module

    @dataclass
    class _FakeAuthState:
        is_signed_in: bool
        payload: dict[str, Any] | None

    @dataclass
    class _FakeClerkClient:
        tokens: dict[str, tuple[str, str | None]] = field(default_factory=dict)

        async def authenticate_request_async(self, request: Any, options: Any) -> _FakeAuthState:
            header = request.headers.get("authorization", "")
            token = header.removeprefix("Bearer ").strip()
            if token in self.tokens:
                clerk_user_id, clerk_org_id = self.tokens[token]
                return _FakeAuthState(is_signed_in=True, payload={"sub": clerk_user_id, "org_id": clerk_org_id})
            return _FakeAuthState(is_signed_in=False, payload=None)

    client = _FakeClerkClient()
    monkeypatch.setattr(auth_context_module, "get_clerk_client", lambda: client)
    return client


def _register_owner(fake_clerk, tenant_id: uuid.UUID) -> dict[str, str]:
    from backend.repositories import app_user_repo, membership_repo

    clerk_user_id = f"user_{uuid.uuid4()}"
    app_user_repo.upsert(
        clerk_user_id=clerk_user_id,
        email=f"{clerk_user_id}@example.com",
        email_verified=True,
        auth_provider="GOOGLE",
        display_name="Test Owner",
    )
    user_row = app_user_repo.get_by_clerk_user_id(clerk_user_id)
    membership_repo.create_owner(tenant_id, user_row["id"])

    token = f"tok_{uuid.uuid4()}"
    fake_clerk.tokens[token] = (clerk_user_id, f"org_{tenant_id}")
    return {"Authorization": f"Bearer {token}"}


def _seed_zero_cap(migrate_engine, *, agent_code: str, meter_code: str) -> None:
    with migrate_engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO entitlement_cap_config
                  (id, tenant_id, agent_code, meter_code, scope, period_unit, cap_value, effective_from, version)
                VALUES
                  (:id, NULL, :agent_code, :meter_code, 'TENANT', 'MONTH', 0, :effective_from, 1)
                """
            ),
            {
                "id": str(uuid.uuid4()),
                "agent_code": agent_code,
                "meter_code": meter_code,
                "effective_from": _AS_OF,
            },
        )


def _register_owner(fake_clerk, tenant_id: uuid.UUID) -> dict[str, str]:
    from backend.repositories import app_user_repo, membership_repo

    clerk_user_id = f"user_{uuid.uuid4()}"
    app_user_repo.upsert(
        clerk_user_id=clerk_user_id,
        email=f"{clerk_user_id}@example.com",
        email_verified=True,
        auth_provider="GOOGLE",
        display_name="Test Owner",
    )
    user_row = app_user_repo.get_by_clerk_user_id(clerk_user_id)
    membership_repo.create_owner(tenant_id, user_row["id"])

    token = f"tok_{uuid.uuid4()}"
    fake_clerk.tokens[token] = (clerk_user_id, f"org_{tenant_id}")
    return {"Authorization": f"Bearer {token}"}


def _seed_zero_cap(migrate_engine, *, agent_code: str, meter_code: str) -> None:
    with migrate_engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO entitlement_cap_config
                  (id, tenant_id, agent_code, meter_code, scope, period_unit, cap_value, effective_from, version)
                VALUES
                  (:id, NULL, :agent_code, :meter_code, 'TENANT', 'MONTH', 0, :effective_from, 1)
                """
            ),
            {
                "id": str(uuid.uuid4()),
                "agent_code": agent_code,
                "meter_code": meter_code,
                "effective_from": _AS_OF,
            },
        )




def body(*entries: dict) -> dict:
    return {"entries": list(entries)}


def e(amount: int, category: str, day: int = 5, **kw: Any) -> dict:
    return {"entry_date": f"2026-09-{day:02d}", "amount_paise": amount, "category": category, **kw}


def test_add_list_suggest_confirm_and_see_operating_profit_move(app_client, fake_clerk, two_tenants):
    tenant_a, _ = two_tenants
    headers = _register_owner(fake_clerk, tenant_a)
    r = app_client.post("/api/v1/cfo/ledger/entries", json=body(e(1_200_00, "Office Rent", vendor="Landlord")), headers=headers)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["inserted"] == 1 and out["suggestionsRecorded"] == 1 and out["heldOverlap"] == 0
    listed = app_client.get("/api/v1/cfo/ledger/entries", params={"period_start": "2026-09-01", "period_end": "2026-09-30"}, headers=headers).json()["entries"]
    assert len(listed) == 1 and listed[0]["confirmedClass"] is None and listed[0]["suggestedClass"] == "OVERHEAD" and "rent" in listed[0]["suggestionReason"]
    c = app_client.post("/api/v1/cfo/ledger/classes", json={"class": "OVERHEAD", "category": "Office Rent"}, headers=headers)
    assert c.status_code == 200, c.text
    again = app_client.get("/api/v1/cfo/ledger/entries", headers=headers).json()["entries"][0]
    assert again["confirmedClass"] == "OVERHEAD"


def test_duplicates_and_overlap_are_reported_back_and_can_be_released(app_client, fake_clerk, two_tenants):
    tenant_a, _ = two_tenants
    headers = _register_owner(fake_clerk, tenant_a)
    r = app_client.post("/api/v1/cfo/ledger/entries", json=body(e(100_00, "Software", vendor="V", description="a"), e(100_00, "Software", vendor="V", description="a"),
                                                                 e(100_00, "Software", vendor="V", description="b"), e(50_00, "Marketplace commission")), headers=headers).json()
    assert (r["inserted"], r["skippedExactDuplicates"], r["heldPossibleDuplicates"], r["heldOverlap"]) == (3, 1, 1, 1)
    rel = app_client.post(f"/api/v1/cfo/ledger/entries/{r['heldIds'][0]}/release", headers=headers)
    assert rel.status_code == 200, rel.text
    assert app_client.post(f"/api/v1/cfo/ledger/entries/{rel.json()['entryId']}/release", headers=headers).status_code == 400  # no longer on hold


def test_allocated_cost_must_name_its_cost_pool_and_then_confirms(app_client, fake_clerk, two_tenants):
    tenant_a, _ = two_tenants
    headers = _register_owner(fake_clerk, tenant_a)
    app_client.post("/api/v1/cfo/ledger/entries", json=body(e(100_00, "Packaging")), headers=headers)
    r = app_client.post("/api/v1/cfo/ledger/classes", json={"class": "ALLOCATED_COST", "category": "Packaging"}, headers=headers)
    assert r.status_code == 400 and "must say which cost" in r.json()["detail"]
    ok = app_client.post("/api/v1/cfo/ledger/classes", json={"class": "ALLOCATED_COST", "category": "Packaging", "allocated_component": "packaging"}, headers=headers)
    assert ok.status_code == 200
    assert app_client.post("/api/v1/cfo/ledger/classes", json={"class": "NOT_A_CLASS", "category": "Packaging"}, headers=headers).status_code == 400
    assert app_client.post("/api/v1/cfo/ledger/classes", json={"class": "OVERHEAD"}, headers=headers).status_code == 400  # neither an entry nor a category


def test_bad_entries_get_plain_400s_and_unknown_fields_422(app_client, fake_clerk, two_tenants):
    tenant_a, _ = two_tenants
    headers = _register_owner(fake_clerk, tenant_a)
    assert app_client.post("/api/v1/cfo/ledger/entries", json=body(e(0, "Rent")), headers=headers).status_code == 400
    assert app_client.post("/api/v1/cfo/ledger/entries", json=body(e(10, "Rent", marketplace="EBAY")), headers=headers).status_code == 400
    assert app_client.post("/api/v1/cfo/ledger/entries", json={"entries": [e(10, "Rent")], "tenant_id": str(uuid.uuid4())}, headers=headers).status_code == 422
    assert app_client.post("/api/v1/cfo/ledger/entries", json=body({**e(10, "Rent"), "identity": "x"}), headers=headers).status_code == 422
    assert app_client.post("/api/v1/cfo/ledger/entries", json={"entries": []}, headers=headers).status_code == 422


def test_correct_and_void_keep_the_history_and_a_no_overhead_declaration_is_checked(app_client, fake_clerk, two_tenants):
    tenant_a, _ = two_tenants
    headers = _register_owner(fake_clerk, tenant_a)
    first = app_client.post("/api/v1/cfo/ledger/entries", json=body(e(100_00, "Rent")), headers=headers).json()["entryIds"][0]
    fixed = app_client.post(f"/api/v1/cfo/ledger/entries/{first}/correct", json=e(110_00, "Rent"), headers=headers)
    assert fixed.status_code == 200, fixed.text
    assert app_client.post(f"/api/v1/cfo/ledger/entries/{first}/correct", json=e(120_00, "Rent"), headers=headers).status_code == 400  # already corrected
    app_client.post("/api/v1/cfo/ledger/classes", json={"class": "OVERHEAD", "category": "Rent"}, headers=headers)
    d = app_client.post("/api/v1/cfo/ledger/declarations/no-overhead", json={"period_start": "2026-09-01", "period_end": "2026-09-30"}, headers=headers)
    assert d.status_code == 400 and "contradict" in d.json()["detail"]
    voided = app_client.post(f"/api/v1/cfo/ledger/entries/{fixed.json()['entryId']}/void", json={"reason": "entered by mistake"}, headers=headers)
    assert voided.status_code == 200
    ok = app_client.post("/api/v1/cfo/ledger/declarations/no-overhead", json={"period_start": "2026-09-01", "period_end": "2026-09-30"}, headers=headers)
    assert ok.status_code == 200, ok.text


def test_a_member_without_financials_adjust_cannot_write_but_can_read(app_client, fake_clerk, two_tenants):
    from backend.auth.permissions import AGENT_CFO
    from tests.integration.test_cfo_pnl import _register_partner_with_permissions

    tenant_a, _ = two_tenants
    owner = _register_owner(fake_clerk, tenant_a)
    app_client.post("/api/v1/cfo/ledger/entries", json=body(e(100_00, "Rent")), headers=owner)
    h = _register_partner_with_permissions(fake_clerk, tenant_a, permissions={AGENT_CFO: True})
    assert app_client.get("/api/v1/cfo/ledger/entries", headers=h).status_code == 200
    for method, url, payload in (("post", "/api/v1/cfo/ledger/entries", body(e(1_00, "Rent"))), ("post", "/api/v1/cfo/ledger/classes", {"class": "OVERHEAD", "category": "Rent"}),
                                 ("post", "/api/v1/cfo/ledger/declarations/no-overhead", {"period_start": "2026-09-01", "period_end": "2026-09-30"})):
        assert getattr(app_client, method)(url, json=payload, headers=h).status_code == 403, url


def test_capped_entitlement_denies_402_on_the_ledger(app_client, fake_clerk, two_tenants, migrate_engine):
    tenant_a, _ = two_tenants
    _seed_zero_cap(migrate_engine, agent_code="CFO", meter_code="cfo.expense_ledger")
    headers = _register_owner(fake_clerk, tenant_a)
    assert app_client.post("/api/v1/cfo/ledger/entries", json=body(e(1_00, "Rent")), headers=headers).status_code == 402
    assert app_client.get("/api/v1/cfo/ledger/entries", headers=headers).status_code == 402


def test_one_tenant_never_sees_anothers_ledger(app_client, fake_clerk, two_tenants):
    tenant_a, tenant_b = two_tenants
    ha, hb = _register_owner(fake_clerk, tenant_a), _register_owner(fake_clerk, tenant_b)
    r = app_client.post("/api/v1/cfo/ledger/entries", json=body(e(100_00, "Rent")), headers=ha).json()
    assert app_client.get("/api/v1/cfo/ledger/entries", headers=hb).json()["entries"] == []
    assert app_client.post(f"/api/v1/cfo/ledger/entries/{r['entryIds'][0]}/void", json={"reason": "entered by mistake"}, headers=hb).status_code == 400


# ---------------------------------------------------------------------------------------------------- the planner reads the ledger
def ask(tenant: uuid.UUID, plan_json: str, cache=None):
    return answer_financial_query(tenant, requested_by=uuid.uuid4(), question="q", periods=[SEP], provider=MockPlannerProvider([plan_json]), cache=cache or InMemoryEvidenceCache())


def full_book() -> uuid.UUID:
    """Meesho only, every line carries its status and a cost price, so Contribution Profit is available at the default 95% threshold."""
    t = uuid.uuid4()
    run = _file_and_run(t)
    for i in range(4):
        _line(t, run, day=date(2026, 9, 3 + i), sku="A", gross=50_000, fee=5_000)
    _cogs(t, "A", 4_000)
    return t


def test_operating_profit_is_unavailable_until_there_is_an_expense_entry_or_a_declaration_then_moves_with_confirmed_overhead(monkeypatch):
    from calc_engine.expense_ledger import NewEntry
    from calc_engine.formulas.expense_accounting import ExpenseClass
    from calc_engine.repositories import expense_ledger_repo as repo

    t = full_book()
    op = plan([{"op": "metric", "params": {"metric": "OPERATING_PROFIT"}}])
    r0 = ask(t, op)
    assert isinstance(r0, PlannerAnswer), r0
    assert r0.packet.figures[0].status == "UNAVAILABLE" and len(r0.packet.data_requests) == 1  # no expense data, no declaration
    cp = ask(t, plan([{"op": "metric", "params": {"metric": "CONTRIBUTION_PROFIT"}}]))
    assert isinstance(cp, PlannerAnswer)
    cp_value = cp.packet.figures[0].value_paise
    assert cp_value is not None

    repo.add_entries(t, [NewEntry(entry_date=date(2026, 9, 10), amount_paise=300_00, category="Rent", vendor="L")], uuid.uuid4())
    r1 = ask(t, op)
    assert isinstance(r1, PlannerAnswer)
    f1 = r1.packet.figures[0]
    assert f1.status == "PROVISIONAL" and f1.value_paise == cp_value and f1.exclusions == (("UNCLASSIFIED_EXPENSE", 1),)  # unconfirmed: not subtracted, exposed
    assert "BASED_ON_1_EXPENSE_ENTRIES" in f1.labels

    repo.confirm_class(t, klass=ExpenseClass.OVERHEAD, confirmed_by=uuid.uuid4(), category="Rent")
    r2 = ask(t, op)
    assert isinstance(r2, PlannerAnswer)
    f2 = r2.packet.figures[0]
    assert f2.status == "DERIVED" and f2.value_paise == cp_value - 300_00 and f2.engine_result_ref and f2.exclusions == ()


def test_the_breakdown_comes_from_the_ledger_and_a_ledger_write_invalidates_the_cached_answer():
    from calc_engine.expense_ledger import NewEntry
    from calc_engine.formulas.expense_accounting import ExpenseClass
    from calc_engine.repositories import expense_ledger_repo as repo

    t = uuid.uuid4()
    uid = uuid.uuid4()
    repo.add_entries(t, [NewEntry(entry_date=date(2026, 9, 2), amount_paise=900_00, category="Rent", vendor="L"),
                         NewEntry(entry_date=date(2026, 9, 3), amount_paise=-100_00, category="Rent", vendor="L", description="refund"),
                         NewEntry(entry_date=date(2026, 9, 4), amount_paise=700_00, category="Stock purchase", vendor="S")], uid)
    repo.confirm_class(t, klass=ExpenseClass.OVERHEAD, confirmed_by=uid, category="Rent")
    repo.confirm_class(t, klass=ExpenseClass.INVENTORY_PURCHASE, confirmed_by=uid, category="Stock purchase")
    cache = InMemoryEvidenceCache()
    p = plan([{"op": "aggregate", "params": {"metric": "EXPENSE_BY_CATEGORY"}}], intent="EXPENSE_BREAKDOWN")
    a = ask(t, p, cache)
    assert isinstance(a, PlannerAnswer), a
    rows = {(dict(f.dimension_keys)["expense_category"], dict(f.dimension_keys)["expense_class"]): f.value_paise for f in a.packet.figures if f.dimension_keys}
    assert rows == {("Rent", "OVERHEAD"): 800_00, ("Stock purchase", "INVENTORY_PURCHASE"): 700_00}  # the refund reduced Rent
    assert [f.value_paise for f in a.packet.figures if not f.dimension_keys] == [1_500_00] and all(f.engine_result_ref for f in a.packet.figures)
    again = ask(t, p, cache)
    assert isinstance(again, PlannerAnswer) and again.packet.cached
    repo.add_entries(t, [NewEntry(entry_date=date(2026, 9, 9), amount_paise=50_00, category="Rent", vendor="L", description="extra")], uid)
    fresh = ask(t, p, cache)
    assert isinstance(fresh, PlannerAnswer) and not fresh.packet.cached
    assert [f.value_paise for f in fresh.packet.figures if not f.dimension_keys] == [1_550_00]  # the new 50.00 Rent entry is in the answer: the stale total was unreachable


def test_the_owner_drawing_view_shows_drawings_and_nothing_else():
    from calc_engine.expense_ledger import NewEntry
    from calc_engine.formulas.expense_accounting import ExpenseClass
    from calc_engine.repositories import expense_ledger_repo as repo

    t = uuid.uuid4()
    uid = uuid.uuid4()
    repo.add_entries(t, [NewEntry(entry_date=date(2026, 9, 2), amount_paise=900_00, category="Rent", vendor="L"),
                         NewEntry(entry_date=date(2026, 9, 3), amount_paise=250_00, category="Owner draw", vendor="Self")], uid)
    repo.confirm_class(t, klass=ExpenseClass.OVERHEAD, confirmed_by=uid, category="Rent")
    repo.confirm_class(t, klass=ExpenseClass.OWNER_DRAWING, confirmed_by=uid, category="Owner draw")
    r = ask(t, plan([{"op": "filter", "params": {"dimension": "expense_class", "op": "eq", "value": "OWNER_DRAWING"}},
                     {"op": "aggregate", "params": {"metric": "EXPENSE_BY_CATEGORY"}}], intent="EXPENSE_BREAKDOWN"))
    assert isinstance(r, PlannerAnswer), r
    assert [(dict(f.dimension_keys)["expense_category"], f.value_paise) for f in r.packet.figures] == [("Owner draw", 250_00)]


def test_planner_ledger_answers_are_tenant_isolated():
    from calc_engine.expense_ledger import NewEntry
    from calc_engine.repositories import expense_ledger_repo as repo

    a, b = uuid.uuid4(), uuid.uuid4()
    repo.add_entries(a, [NewEntry(entry_date=date(2026, 9, 2), amount_paise=900_00, category="Rent", vendor="L")], uuid.uuid4())
    r = ask(b, plan([{"op": "aggregate", "params": {"metric": "EXPENSE_BY_CATEGORY"}}], intent="EXPENSE_BREAKDOWN"))
    assert isinstance(r, PlannerAnswer) and r.packet.figures[0].status == "UNAVAILABLE"


def test_removal_needs_a_reason_and_payment_states_are_validated_and_shown(app_client, fake_clerk, two_tenants):
    tenant_a, tenant_b = two_tenants
    ha, hb = _register_owner(fake_clerk, tenant_a), _register_owner(fake_clerk, tenant_b)
    eid = app_client.post("/api/v1/cfo/ledger/entries", json=body(e(500_00, "Rent")), headers=ha).json()["entryIds"][0]
    pay = f"/api/v1/cfo/ledger/entries/{eid}/payment"
    assert app_client.post(f"/api/v1/cfo/ledger/entries/{eid}/void", headers=ha).status_code == 422  # no body: no reason
    assert app_client.post(f"/api/v1/cfo/ledger/entries/{eid}/void", json={"reason": "ok"}, headers=ha).status_code == 422  # too short to be a reason
    assert app_client.post(pay, json={"status": "PARTIALLY_PAID"}, headers=ha).status_code == 400  # a partial payment names the amount
    assert app_client.post(pay, json={"status": "PARTIALLY_PAID", "paid_amount_paise": 500_00}, headers=ha).status_code == 400  # not the whole amount
    assert app_client.post(pay, json={"status": "PAID", "paid_amount_paise": 5}, headers=ha).status_code == 400
    assert app_client.post(pay, json={"status": "UNKNOWN"}, headers=ha).status_code == 422
    assert app_client.post(pay, json={"status": "PARTIALLY_PAID", "paid_amount_paise": 200_00}, headers=hb).status_code == 400  # another tenant's entry does not exist for them
    ok = app_client.post(pay, json={"status": "PARTIALLY_PAID", "paid_amount_paise": 200_00}, headers=ha)
    assert ok.status_code == 200 and ok.json()["changed"] is True
    assert app_client.post(pay, json={"status": "PARTIALLY_PAID", "paid_amount_paise": 200_00}, headers=ha).json()["changed"] is False
    row = app_client.get("/api/v1/cfo/ledger/entries", headers=ha).json()["entries"][0]
    assert row["paymentStatus"] == "PARTIALLY_PAID" and row["paidAmountPaise"] == 200_00
    assert app_client.post(f"/api/v1/cfo/ledger/entries/{eid}/void", json={"reason": "Entered by mistake"}, headers=ha).status_code == 200
    assert app_client.get("/api/v1/cfo/ledger/entries", headers=ha).json()["entries"] == []
