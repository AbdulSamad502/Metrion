"""`POST /api/v1/cfo/pnl-scenario` against a real Postgres (calculator.md §14, N-AC3 / N-AC5): permission, entitlement, tenant isolation and "writes nothing but one audit row".

Only Clerk is faked, exactly as in `test_ci_api.py`; the auth chain, tenant context, RLS and repositories are real. Run on the scratch database only
(`backend/scripts/scratch_db.sh up`); the suite's guard refuses the development database."""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from sqlalchemy import text

from backend.tenant_context import tenant_scope
from tests.integration.test_ci_api import _register_deny_all_partner, _register_owner, client, fake_clerk  # noqa: F401  (fixtures and helpers)

pytestmark = pytest.mark.usefixtures("_clean_backend_tables")

URL = "/api/v1/cfo/pnl-scenario"


def _a1() -> dict:
    s = lambda v: {"state": "set", "value": v}  # noqa: E731
    fee = lambda v: {"amount": {"state": "set", "value": {"kind": "single", "amount": v}}}  # noqa: E731
    return {
        "marketplace": "amazon", "mode": "detailed", "selling_price": s("118000"), "gst_rate_bps": s("1800"), "product_cost": s("35400"),
        "packaging_cost": s("2360"), "fees": {"referral": fee("1000"), "closing": fee("2000"), "shipping": fee("5000")},
        "monthly_orders": s("100"), "rto_bps": s("0"), "return_bps": s("0"), "ad_spend": {"state": "na"}, "targets": [{"kind": "breakeven"}],
    }


def _count(tenant_id: uuid.UUID, table: str, where: str = "true") -> int:
    with tenant_scope(tenant_id) as conn:
        return conn.execute(text(f"SELECT count(*) FROM {table} WHERE {where}")).scalar_one()  # noqa: S608 - fixed table names from this file


def _runs(tenant_id: uuid.UUID) -> list[dict]:
    with tenant_scope(tenant_id) as conn:
        rows = conn.execute(text("SELECT agent_id, trigger_type, trigger_ref, status, permission_check, entitlement_check FROM agent_run")).mappings().all()
    return [dict(r) for r in rows]


def test_an_authorised_member_gets_a_labelled_estimate_and_exactly_one_audit_row(client, fake_clerk, two_tenants):
    a, _ = two_tenants
    headers = _register_owner(fake_clerk, a)
    resp = client.post(URL, json=_a1(), headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["perKept"]["contribution"] == "49200" and body["monthly"]["contribution"] == "4920000"  # the reference calculator's fixture A1, to the paisa
    assert (body["kind"], body["verification"], body["persisted"], body["status"]) == ("hypothetical_estimate", "unverified_estimate", False, "estimate")
    assert "engineResultRef" not in resp.text
    assert body["breakdown"]["profitShareBps"] == "4920" and body["breakdown"]["segments"][-1]["endBps"] == "10000"  # where each rupee goes, from the engine
    runs = _runs(a)
    assert runs == [{"agent_id": "CFO", "trigger_type": "DIRECT", "trigger_ref": "cfo.pnl_scenario", "status": "COMPLETE", "permission_check": "PASS", "entitlement_check": "PASS"}]
    assert body["estimateRef"].startswith("pnl-scenario:")
    with tenant_scope(a) as conn:
        run_id = str(conn.execute(text("SELECT id FROM agent_run")).scalar_one())
    assert body["estimateRef"] == f"pnl-scenario:{run_id}"


def test_it_writes_no_metric_result_and_no_data_request_even_when_inputs_are_missing(client, fake_clerk, two_tenants):
    a, _ = two_tenants
    headers = _register_owner(fake_clerk, a)
    before = (_count(a, "metric_result"), _count(a, "agent_data_request"))
    full = client.post(URL, json=_a1(), headers=headers)
    thin = client.post(URL, json={"marketplace": "flipkart"}, headers=headers)  # nothing entered: incomplete, which must not raise a data request
    assert full.status_code == 200 and thin.status_code == 200 and thin.json()["status"] == "incomplete"
    assert (_count(a, "metric_result"), _count(a, "agent_data_request")) == before == (0, 0)
    assert sorted(r["status"] for r in _runs(a)) == ["COMPLETE", "PARTIAL"]


def test_a_member_without_the_cfo_permission_is_refused_and_nothing_is_written(client, fake_clerk, two_tenants):
    a, _ = two_tenants
    headers = _register_deny_all_partner(fake_clerk, a)
    resp = client.post(URL, json=_a1(), headers=headers)
    assert resp.status_code == 403
    assert _runs(a) == []


def test_no_session_is_a_401(client, two_tenants):
    assert client.post(URL, json=_a1()).status_code == 401


def test_an_entitlement_denial_is_a_402_with_no_audit_row_and_no_computation(client, fake_clerk, two_tenants, migrate_engine):
    a, _ = two_tenants
    headers = _register_owner(fake_clerk, a)
    with migrate_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO entitlement_cap_config (id, tenant_id, agent_code, meter_code, scope, period_unit, cap_value, effective_from, version) "
                "VALUES (:id, NULL, 'CFO', 'cfo.pnl_scenario', 'TENANT', 'MONTH', 0, :d, 1)"
            ),
            {"id": str(uuid.uuid4()), "d": date(2026, 1, 1)},
        )
    resp = client.post(URL, json=_a1(), headers=headers)
    assert resp.status_code == 402, resp.text
    assert _runs(a) == [] and _count(a, "metric_result") == 0


def test_the_caller_cannot_name_a_tenant_or_send_unknown_fields(client, fake_clerk, two_tenants):
    a, b = two_tenants
    headers = _register_owner(fake_clerk, a)
    for extra in ({"tenant_id": str(b)}, {"tenantId": str(b)}, {"surprise": 1}):
        resp = client.post(URL, json=_a1() | extra, headers=headers)
        assert resp.status_code == 422, (extra, resp.text)
    assert _runs(a) == [] and _runs(b) == []


def test_a_float_money_value_is_refused_with_a_422(client, fake_clerk, two_tenants):
    a, _ = two_tenants
    headers = _register_owner(fake_clerk, a)
    body = _a1() | {"selling_price": {"state": "set", "value": 1180.5}}
    assert client.post(URL, json=body, headers=headers).status_code == 422
    assert _runs(a) == []


def test_tenants_are_isolated_each_call_is_recorded_only_under_its_own_tenant(client, fake_clerk, two_tenants):
    a, b = two_tenants
    ha, hb = _register_owner(fake_clerk, a), _register_owner(fake_clerk, b)
    ra = client.post(URL, json=_a1(), headers=ha)
    assert ra.status_code == 200
    assert (len(_runs(a)), len(_runs(b))) == (1, 0)
    rb = client.post(URL, json=_a1(), headers=hb)
    rb2 = client.post(URL, json=_a1(), headers=hb)
    assert rb.status_code == rb2.status_code == 200
    assert (len(_runs(a)), len(_runs(b))) == (1, 2)
    # tenant B's scope cannot see tenant A's run, and A's estimate reference is not one of B's runs
    a_run = ra.json()["estimateRef"].split(":", 1)[1]
    assert _count(b, "agent_run", f"id = '{a_run}'") == 0
    # a member of tenant A presenting tenant A's token never reaches B: the answer carries no figures from B's tenant
    assert ra.json()["estimateRef"] != rb.json()["estimateRef"]
