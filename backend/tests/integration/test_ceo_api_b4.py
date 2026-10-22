"""B4 backend additions the CEO Hub needs: archive, attach/detach, per-agent availability, explicit date range (spec §6.22, R13, §6.3 rule 3).

Same harness as `test_ceo_api.py`: real app, real auth chain (Clerk faked), real Postgres, scripted models."""

from __future__ import annotations

import os
import uuid

import pytest

from backend.auth.permissions import AGENT_CEO, INVESTIGATION_VIEW, PARTNER_ROLE
from backend.repositories import investigation_repo as repo
from tests.integration.ceo_support import row_counts, seed_platform_cap
from tests.integration.test_ceo_api import STATE, api, clerk, login, start  # noqa: F401
from tests.integration.test_ceo_turn import Grounded, Scripted, decision, health_config, runtime, seed_books  # noqa: F401

pytestmark = pytest.mark.skipif(not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL"), reason="needs a live Postgres")

CFO_ACTION_METERS = (
    "cfo.pnl", "cfo.pricing", "cfo.gst_summary", "cfo.period_comparison", "cfo.landed_cost", "cfo.supplier_ranking", "cfo.funding_readiness",
    "cfo.batch_size", "cfo.reconcile", "cfo.anomaly_check", "cfo.financial_health", "cfo.cash_reconciliation", "cfo.strategic_briefing",
    "cfo.gst_lookup",  # wired in B4 (Route A of the GST lookup)
    "cfo.query",  # CFO 2.0 planner: a CFO action like the rest, so capping every CFO meter must lock the agent
)


def test_archive_hides_without_a_conclusion_and_closes_the_thread(api):
    client, ha, hb, a, _ = api
    inv = start(client, ha)
    assert client.post(f"/api/v1/ceo/investigations/{inv}/archive", headers=hb).status_code == 404  # another tenant
    r = client.post(f"/api/v1/ceo/investigations/{inv}/archive", headers=ha)
    assert r.status_code == 200 and r.json() == {"status": "ARCHIVED"}
    assert [(i["id"], i["status"]) for i in client.get("/api/v1/ceo/investigations", params={"status": "ARCHIVED"}, headers=ha).json()] == [(inv, "ARCHIVED")]
    assert client.get("/api/v1/ceo/investigations", params={"status": "ACTIVE"}, headers=ha).json() == []
    detail = client.get(f"/api/v1/ceo/investigations/{inv}", headers=ha).json()  # still readable as history
    assert detail["investigation"]["status"] == "ARCHIVED" and detail["investigation"]["resolution_note"] is None
    assert client.post(f"/api/v1/ceo/investigations/{inv}/archive", headers=ha).status_code == 409
    assert client.post(f"/api/v1/ceo/investigations/{inv}/turns", json={"message": STATE}, headers=ha).status_code == 409


def test_a_resolved_investigation_can_be_archived_later(api):
    client, ha, *_ = api
    inv = start(client, ha)
    assert client.post(f"/api/v1/ceo/investigations/{inv}/resolve", json={"resolution_note": "done"}, headers=ha).status_code == 200
    assert client.post(f"/api/v1/ceo/investigations/{inv}/archive", headers=ha).status_code == 200


def test_detaching_an_agent_is_future_only_and_leaves_a_system_note(api):
    client, ha, hb, a, _ = api
    seed_books(a)
    inv = start(client, ha)
    first = client.post(f"/api/v1/ceo/investigations/{inv}/turns", json={"message": STATE}, headers=ha).json()
    findings_before = client.get(f"/api/v1/ceo/investigations/{inv}/findings", headers=ha).json()
    assert first["findings"]

    r = client.put(f"/api/v1/ceo/investigations/{inv}/agents/cfo", json={"attached": False}, headers=ha)
    assert r.status_code == 200 and r.json() == {"agent": "CFO", "attached": False}
    detail = client.get(f"/api/v1/ceo/investigations/{inv}", headers=ha).json()
    assert detail["agents"]["CFO"] is False and detail["agents"]["CI"] is True
    notes = [m for m in detail["messages"] if m["kind"] == "SYSTEM_NOTE"]
    assert len(notes) == 1 and "CFO was detached" in notes[0]["content"] and "historical evidence" in notes[0]["content"] and notes[0]["role"] == "SYSTEM"
    assert client.get(f"/api/v1/ceo/investigations/{inv}/findings", headers=ha).json() == findings_before  # nothing erased or invalidated

    again = client.put(f"/api/v1/ceo/investigations/{inv}/agents/CFO", json={"attached": False}, headers=ha)
    assert again.status_code == 200
    assert len([m for m in client.get(f"/api/v1/ceo/investigations/{inv}", headers=ha).json()["messages"] if m["kind"] == "SYSTEM_NOTE"]) == 1  # idempotent

    blocked = client.post(f"/api/v1/ceo/investigations/{inv}/turns", json={"message": STATE}, headers=ha).json()  # BS_PNL_LATEST is CFO-owned: gone from the catalog
    assert blocked["status"] == "CLARIFIED" and blocked["findings"] == []

    back = client.put(f"/api/v1/ceo/investigations/{inv}/agents/CFO", json={"attached": True}, headers=ha)
    assert back.status_code == 200 and client.get(f"/api/v1/ceo/investigations/{inv}", headers=ha).json()["agents"]["CFO"] is True


def test_attachment_endpoint_guards(api, clerk):
    client, ha, hb, a, _ = api
    inv = start(client, ha)
    assert client.put(f"/api/v1/ceo/investigations/{inv}/agents/HACKER", json={"attached": False}, headers=ha).status_code == 404
    assert client.put(f"/api/v1/ceo/investigations/{inv}/agents/CFO", json={"attached": False}, headers=hb).status_code == 404  # another tenant
    assert client.put(f"/api/v1/ceo/investigations/{inv}/agents/CFO", json={}, headers=ha).status_code == 422
    assert client.get(f"/api/v1/ceo/investigations/{inv}", headers=ha).json()["agents"]["CFO"] is True  # B's attempt changed nothing
    no_ceo = login(clerk, a, role=PARTNER_ROLE, permissions={INVESTIGATION_VIEW: True})
    assert client.put(f"/api/v1/ceo/investigations/{inv}/agents/CFO", json={"attached": False}, headers=no_ceo).status_code == 403
    client.post(f"/api/v1/ceo/investigations/{inv}/archive", headers=ha)
    r = client.put(f"/api/v1/ceo/investigations/{inv}/agents/CFO", json={"attached": False}, headers=ha)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "INVESTIGATION_NOT_ACTIVE"


def test_an_agent_the_tenant_is_not_entitled_to_cannot_be_attached_and_shows_locked(api, migrate_engine):
    client, ha, _, a, _ = api
    for meter in CFO_ACTION_METERS:
        seed_platform_cap(migrate_engine, agent_code="CFO", meter_code=meter, cap_value=0)
    avail = client.get("/api/v1/ceo/agents/availability", headers=ha).json()
    assert avail["CFO"] == {"status": "NOT_ENTITLED", "chatActions": 7} and avail["CI"]["status"] == "PRESENT"
    inv = start(client, ha)  # default attachment follows entitlement (§6.22 rule 1): CFO is recorded detached
    assert client.get(f"/api/v1/ceo/investigations/{inv}", headers=ha).json()["agents"]["CFO"] is False
    r = client.put(f"/api/v1/ceo/investigations/{inv}/agents/CFO", json={"attached": True}, headers=ha)
    assert r.status_code == 409 and r.json()["detail"] == {"code": "AGENT_NOT_ENTITLED"}
    assert client.get(f"/api/v1/ceo/investigations/{inv}", headers=ha).json()["agents"]["CFO"] is False  # never silently attached


def test_availability_reflects_the_members_permissions_and_truthful_chat_actions(api, clerk):
    client, ha, _, a, _ = api
    full = client.get("/api/v1/ceo/agents/availability", headers=ha).json()
    assert {k: v["status"] for k, v in full.items()} == {"CFO": "PRESENT", "CI": "PRESENT", "PI": "PRESENT", "CMO": "PRESENT"}
    assert {k: v["chatActions"] for k, v in full.items()} == {"CFO": 7, "CI": 4, "PI": 1, "CMO": 9}  # CFO +GST lookup (Route A) +open financial question (cfo.query), CI price positioning + re-check + review findings + remove a competitor (CI spec 6.21.3; discovery is approval-required, so not counted), PI report only, CMO market-trends preview only: the approval-required ones (D-8) are refused from chat, so they are not counted
    member = login(clerk, a, role=PARTNER_ROLE, permissions={AGENT_CEO: True, INVESTIGATION_VIEW: True})
    assert client.get("/api/v1/ceo/agents/availability", headers=member).json()["CFO"]["status"] == "NOT_PERMITTED"
    assert client.get("/api/v1/ceo/agents/availability", headers={}).status_code == 401


def test_an_explicit_period_is_the_period_the_model_cannot_choose_or_withhold(api, health_config):
    from backend.api.v1 import ceo as ceo_api
    from backend.main import app

    client, ha, _, a, _ = api
    seed_books(a)
    # the model names a DIFFERENT period (October) in one turn and none at all in the other; the seller's picker decides both
    cls = Scripted({
        "Why did profit drop?": decision(route="PLAYBOOK", route_key="PROFIT_DIAGNOSIS", slots={"period": "October"}),
        "And again?": decision(route="PLAYBOOK", route_key="PROFIT_DIAGNOSIS", slots={}),
    })
    rt = runtime(cls, Grounded())
    app.dependency_overrides[ceo_api.get_runtime] = lambda: rt
    inv = start(client, ha)
    body = {"message": "Why did profit drop?", "period_start": "2026-09-01", "period_end": "2026-09-30"}
    r = client.post(f"/api/v1/ceo/investigations/{inv}/turns", json=body, headers=ha)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["status"] == "DELIVERED" and out["route"] == "PLAYBOOK"
    assert "2026-09-01 to 2026-09-30" in out["answer"] and "October" not in out["answer"]  # AC17: the echoed interpretation is the seller's range
    assert "already chose the period 2026-09-01 to 2026-09-30" in cls.prompts[0]
    turn = repo.get_turn(a, uuid.UUID(out["turnId"]))
    assert turn["classifier_result"]["slots"]["period"] == "2026-09-01 to 2026-09-30" and turn["classifier_result"]["effectiveRoute"] == "PLAYBOOK"

    r2 = client.post(f"/api/v1/ceo/investigations/{inv}/turns", json={**body, "message": "And again?"}, headers=ha)
    assert r2.status_code == 200 and r2.json()["status"] == "DELIVERED"  # the model withheld the period; no clarification was needed


def test_an_invalid_explicit_period_is_rejected_before_anything_runs(api):
    client, ha, _, a, _ = api
    inv = start(client, ha)
    before = row_counts(a, "investigation_message", "agent_run")
    for extra in (
        {"period_start": "2026-09-01"}, {"period_end": "2026-09-30"}, {"period_start": "2026-09-30", "period_end": "2026-09-01"},
        {"period_start": "2027-01-01", "period_end": "2027-01-31"}, {"period_start": "not-a-date", "period_end": "2026-09-30"},
    ):
        r = client.post(f"/api/v1/ceo/investigations/{inv}/turns", json={"message": "hello", **extra}, headers=ha)
        assert r.status_code == 422, extra
    assert row_counts(a, "investigation_message", "agent_run") == before


# ------------------------------------------------------------------------------------------------ B4.1: reopen
def test_reopen_restores_a_resolved_investigation_and_keeps_every_record(api):
    client, ha, _, a, _ = api
    seed_books(a)
    inv = start(client, ha)
    client.post(f"/api/v1/ceo/investigations/{inv}/turns", json={"message": STATE}, headers=ha)
    before = client.get(f"/api/v1/ceo/investigations/{inv}", headers=ha).json()
    client.post(f"/api/v1/ceo/investigations/{inv}/resolve", json={"resolution_note": "Fees explained it."}, headers=ha)
    resolved = client.get(f"/api/v1/ceo/investigations/{inv}", headers=ha).json()["investigation"]

    r = client.post(f"/api/v1/ceo/investigations/{inv}/reopen", headers=ha)
    assert r.status_code == 200 and r.json() == {"status": "ACTIVE"}
    after = client.get(f"/api/v1/ceo/investigations/{inv}", headers=ha).json()
    assert after["investigation"]["status"] == "ACTIVE"
    # the seller's conclusion is neither deleted nor rewritten
    for col in ("resolution_note", "resolved_by", "resolved_at"):
        assert after["investigation"][col] == resolved[col] and resolved[col] is not None
    # every earlier message, turn, finding (and its provenance refs) is intact; the only addition is one SYSTEM_NOTE
    assert after["findings"] == before["findings"] and after["turns"] == before["turns"]
    assert [m["id"] for m in after["messages"][:-1]] == [m["id"] for m in before["messages"]]
    note = after["messages"][-1]
    assert (note["role"], note["kind"]) == ("SYSTEM", "SYSTEM_NOTE") and "Fees explained it." in note["content"] and "reopened" in note["content"]
    assert [i["status"] for i in client.get("/api/v1/ceo/investigations", headers=ha).json()] == ["ACTIVE"]

    # it works again: a new turn is accepted, and a later re-resolve writes the NEW conclusion while the old one stays in the thread
    assert client.post(f"/api/v1/ceo/investigations/{inv}/turns", json={"message": STATE}, headers=ha).status_code == 200
    assert client.post(f"/api/v1/ceo/investigations/{inv}/resolve", json={"resolution_note": "Second conclusion."}, headers=ha).status_code == 200
    final = client.get(f"/api/v1/ceo/investigations/{inv}", headers=ha).json()
    assert final["investigation"]["resolution_note"] == "Second conclusion."
    assert any("Fees explained it." in m["content"] for m in final["messages"] if m["kind"] == "SYSTEM_NOTE")  # the first conclusion survives


def test_only_a_resolved_investigation_can_be_reopened(api):
    client, ha, *_ = api
    active = start(client, ha)
    r = client.post(f"/api/v1/ceo/investigations/{active}/reopen", headers=ha)
    assert r.status_code == 409 and r.json()["detail"] == {"code": "NOT_RESOLVED"}

    archived = start(client, ha)
    client.post(f"/api/v1/ceo/investigations/{archived}/archive", headers=ha)
    r = client.post(f"/api/v1/ceo/investigations/{archived}/reopen", headers=ha)
    assert r.status_code == 409 and r.json()["detail"] == {"code": "NOT_RESOLVED"}  # archived is visibility, not resolution
    assert client.get(f"/api/v1/ceo/investigations/{archived}", headers=ha).json()["investigation"]["status"] == "ARCHIVED"

    resolved = start(client, ha)
    client.post(f"/api/v1/ceo/investigations/{resolved}/resolve", json={"resolution_note": "x"}, headers=ha)
    assert client.post(f"/api/v1/ceo/investigations/{resolved}/reopen", headers=ha).status_code == 200
    assert client.post(f"/api/v1/ceo/investigations/{resolved}/reopen", headers=ha).status_code == 409  # now active: nothing to reopen


def test_reopen_enforces_authentication_permission_and_tenant(api, clerk):
    client, ha, hb, a, _ = api
    inv = start(client, ha)
    client.post(f"/api/v1/ceo/investigations/{inv}/resolve", json={"resolution_note": "mine"}, headers=ha)
    assert client.post(f"/api/v1/ceo/investigations/{inv}/reopen", headers={}).status_code == 401
    assert client.post(f"/api/v1/ceo/investigations/{inv}/reopen", headers={"Authorization": "Bearer nope"}).status_code == 401
    no_view = login(clerk, a, role=PARTNER_ROLE, permissions={AGENT_CEO: True})
    assert client.post(f"/api/v1/ceo/investigations/{inv}/reopen", headers=no_view).status_code == 403
    r = client.post(f"/api/v1/ceo/investigations/{inv}/reopen", headers=hb)  # another tenant
    assert r.status_code == 404 and r.json()["detail"] == {"code": "NOT_FOUND"}
    detail = client.get(f"/api/v1/ceo/investigations/{inv}", headers=ha).json()
    assert detail["investigation"]["status"] == "RESOLVED" and detail["investigation"]["resolution_note"] == "mine"  # nothing changed
    assert row_counts(a, "investigation_message") == {"investigation_message": 0}
    assert client.post(f"/api/v1/ceo/investigations/{uuid.uuid4()}/reopen", headers=ha).status_code == 404


def test_the_repository_reopen_is_strict_and_keeps_the_note(two_tenants, app_user):
    from tests.integration.ceo_support import T0

    a, _ = two_tenants
    inv = repo.create_investigation(a, created_by=app_user, attached_agents=("CFO",), now=T0)
    with pytest.raises(repo.InvalidInvestigationTransition):
        repo.reopen_resolved_investigation(a, inv)  # active
    repo.resolve_investigation(a, inv, resolved_by=app_user, resolution_note="done")
    assert repo.reopen_resolved_investigation(a, inv) == "done"
    row = repo.get_investigation(a, inv)
    assert row["status"] == "ACTIVE" and row["resolution_note"] == "done" and row["resolved_by"] == app_user and row["resolved_at"] is not None
    repo.archive_investigation(a, inv)
    with pytest.raises(repo.InvalidInvestigationTransition):
        repo.reopen_resolved_investigation(a, inv)  # archived


def test_availability_never_counts_an_approval_required_action_as_runnable_from_chat(api, clerk):
    """D-8: `chatActions` is what chat can actually run. The six approval-required chat actions are refused until a stored approval plan exists, so they are not counted;
    the count equals the unflagged chat actions per agent. (Agent pages are separate surfaces and are not part of this number.)"""
    from backend.ceo import cmo_delegation
    from backend.ceo.approval_gate import plan_required
    from backend.ceo.plans import ACTIONS, VIRTUAL_ROUTES
    from backend.ceo.registry import get_registry

    client, ha, _, a, _ = api
    reg = get_registry()
    expected: dict[str, int] = {}
    for k in ACTIONS:
        if not plan_required([k]) or k in cmo_delegation.DELEGATED_ACTIONS:  # the five CMO actions go to a plan card
            agent = reg.get(VIRTUAL_ROUTES.get(k, (k,))[0]).agent.value
            expected[agent] = expected.get(agent, 0) + 1
    got = {k: v["chatActions"] for k, v in client.get("/api/v1/ceo/agents/availability", headers=ha).json().items()}
    assert got == {"CFO": expected.get("CFO", 0), "CI": expected.get("CI", 0), "PI": expected.get("PI", 0), "CMO": expected.get("CMO", 0)}
    assert got["PI"] == 1 and got["CMO"] == 9  # pi.discover stays blocked; the eight delegated CMO writing actions + trends end at a plan card
