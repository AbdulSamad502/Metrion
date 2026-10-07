"""The choke point against a real Postgres and the REAL registry's CFO/PI handlers (spec R1, R2, R5, R6, R13, AC2, AC7, AC11, AC31, Q23).

Real specialist code runs (`cfo.financial_health`, `pi.report`); only the model-bearing and network-bearing actions are not exercised here
(they have their own suites and the manual E2E at B6)."""

from __future__ import annotations

import uuid

import pytest

from backend.auth.permissions import AGENT_CEO, AGENT_CFO, INVESTIGATION_VIEW
from backend.ceo.contract import AgentCode, Denial, LegStatus, TurnDenied
from backend.ceo.dispatch import dispatch, open_turn
from backend.ceo.registry import get_registry
from backend.entitlement import meter_ceo_turn
from backend.repositories import agent_run_repo, investigation_repo as repo
from tests.integration.ceo_support import ALL_AGENTS, T0, ctx_for, later, partner_ctx, row_counts, seed_platform_cap
from tests.unit.ceo_fakes import spec

HEALTH = {"period_start": "2026-09-01", "period_end": "2026-09-30", "as_of_date": "2026-10-01"}


def _open(tenant, user, ctx, *, attached=ALL_AGENTS, detached=()):
    inv = repo.create_investigation(tenant, created_by=user, attached_agents=tuple(attached), detached_agents=tuple(detached), now=T0)
    msg = repo.append_message(tenant, inv, role="USER", content="how is my health?", created_by=user, now=T0)
    turn = open_turn(ctx, investigation_id=inv, now=T0)
    turn.turn_id = repo.create_turn(tenant, inv, user_message_id=msg, agent_run_id=turn.anchor_run_id, route="ACTION", route_key="cfo.financial_health", now=T0)
    return inv, turn


def test_a_real_cfo_leg_is_one_child_row_and_one_finding(two_tenants, app_user):
    a, _ = two_tenants
    ctx = ctx_for(a, user_id=app_user)
    inv, turn = _open(a, app_user, ctx)

    leg = dispatch(turn, "cfo.financial_health", HEALTH, now=T0)

    assert leg.status is LegStatus.COMPLETE and leg.payload is not None and leg.payload["overallBand"] is None  # honest: nothing computed yet -> no band
    [child] = agent_run_repo.list_children(a, turn.anchor_run_id)
    assert (child["agent_id"], child["trigger_ref"], child["trigger_type"], child["status"]) == ("CFO", "cfo.financial_health", "CONVERSATIONAL", "COMPLETE")
    assert child["parent_run_id"] == turn.anchor_run_id and child["investigation_id"] == inv and child["permission_check"] == "PASS"
    assert child["entitlement_check"] == "NO_CAP_CONFIGURED"  # honest: no cap is seeded anywhere
    [finding] = repo.list_findings(a, inv, turn_id=turn.turn_id)
    assert (finding["source"], finding["action_key"], finding["status"], finding["agent_run_id"]) == ("CFO", "cfo.financial_health", "COMPLETE", child["id"])

    turn.close(status=turn.derive_status(), now=later(1))
    anchor = agent_run_repo.get_run(a, turn.anchor_run_id)
    assert (anchor["agent_id"], anchor["trigger_type"], anchor["status"], anchor["parent_run_id"]) == ("CEO", "CONVERSATIONAL", "COMPLETE", None)


def test_the_direct_path_writes_no_ceo_row_and_is_unchanged(two_tenants, app_user):
    """AC2: a direct execution never creates a CEO-attributed agent_run and never runs through the choke point."""
    from backend.api.v1 import cfo as cfo_api

    a, _ = two_tenants
    before = row_counts(a, "agent_run")
    payload = cfo_api.post_financial_health(cfo_api.FinancialHealthHttpRequest(**HEALTH), ctx_for(a, user_id=app_user))
    assert payload["overallBand"] is None
    assert row_counts(a, "agent_run") == before


def test_a_detached_agent_is_refused_and_its_earlier_findings_stay_visible(two_tenants, app_user):
    """R13 + resolved Q23, end to end."""
    a, _ = two_tenants
    ctx = ctx_for(a, user_id=app_user)
    inv, turn = _open(a, app_user, ctx)
    first = dispatch(turn, "cfo.financial_health", HEALTH, now=T0)
    assert first.status is LegStatus.COMPLETE
    kept = repo.list_findings(a, inv)

    repo.set_agent_attachment(a, inv, "CFO", attached=False, changed_by=app_user, now=later(1))
    second = dispatch(turn, "cfo.financial_health", HEALTH, now=later(2))

    assert second.status is LegStatus.DENIED and second.denial is Denial.NOT_ATTACHED
    rows = {r["id"]: r for r in agent_run_repo.list_children(a, turn.anchor_run_id)}
    assert rows[second.agent_run_id]["status"] == "DENIED" and "not attached" in rows[second.agent_run_id]["error_reason"]
    findings = repo.list_findings(a, inv)
    assert findings[0] == kept[0]  # the earlier, verified finding is untouched
    assert findings[-1]["status"] == "DENIED" and len(findings) == 2  # the refusal is evidence too


def test_a_member_without_the_agent_key_is_denied_and_logged(two_tenants, app_user):
    a, _ = two_tenants
    inv, turn = _open(a, app_user, ctx_for(a, user_id=app_user))
    turn.ctx = partner_ctx(a, AGENT_CEO, INVESTIGATION_VIEW)  # agent.ceo but not agent.cfo (auth.md T8e)
    leg = dispatch(turn, "cfo.financial_health", HEALTH, now=T0)
    assert leg.status is LegStatus.DENIED and leg.denial is Denial.PERMISSION
    [child] = agent_run_repo.list_children(a, turn.anchor_run_id)
    assert (child["status"], child["permission_check"]) == ("DENIED", f"DENIED:{AGENT_CFO}")
    assert repo.list_findings(a, inv)[0]["status"] == "DENIED"


def test_an_entitlement_refusal_is_denied_not_failed(two_tenants, app_user, migrate_engine):
    a, _ = two_tenants
    seed_platform_cap(migrate_engine, agent_code="CFO", meter_code="cfo.financial_health", cap_value=0)
    inv, turn = _open(a, app_user, ctx_for(a, user_id=app_user))
    leg = dispatch(turn, "cfo.financial_health", HEALTH, now=T0)
    assert leg.status is LegStatus.NOT_ENTITLED and leg.denial is Denial.ENTITLEMENT
    [child] = agent_run_repo.list_children(a, turn.anchor_run_id)
    assert child["status"] == "DENIED" and child["entitlement_check"] == "DENIED:cfo.financial_health"  # R6: never FAILED
    assert repo.list_findings(a, inv)[0]["status"] == "NOT_ENTITLED"


def test_a_specialist_404_becomes_an_unavailable_leg_without_leaking(two_tenants, app_user):
    a, _ = two_tenants
    inv, turn = _open(a, app_user, ctx_for(a, user_id=app_user))
    leg = dispatch(turn, "pi.report", {"run_id": str(uuid.uuid4())}, now=T0)
    assert leg.status is LegStatus.UNAVAILABLE and leg.reason == "unavailable"
    [child] = agent_run_repo.list_children(a, turn.anchor_run_id)
    assert child["status"] == "FAILED" and child["error_reason"] == "404"
    assert repo.list_findings(a, inv)[0]["status"] == "UNAVAILABLE"


def test_an_unwired_action_is_logged_not_executed(two_tenants, app_user):
    a, _ = two_tenants
    inv, turn = _open(a, app_user, ctx_for(a, user_id=app_user))
    leg = dispatch(turn, "ci.research_now", {}, now=T0)
    assert leg.denial is Denial.NOT_WIRED and leg.status is LegStatus.UNAVAILABLE
    [child] = agent_run_repo.list_children(a, turn.anchor_run_id)
    assert child["status"] == "FAILED" and child["error_reason"].startswith("NOT_WIRED")


def test_a_specialist_that_writes_its_own_row_is_linked_to_the_turn_without_a_duplicate(two_tenants, app_user):
    """The inheritance mechanism against the real repository (PI/CMO write rows through `agent_run_repo`)."""
    from backend.ceo.registry import ActionRegistry

    def own_row(slots, ctx, leg):
        assert leg.leg_run_id is None
        agent_run_repo.insert_run(ctx.tenant_id, agent_id="PI", trigger_type="DIRECT", trigger_ref="pi.fake", requested_by=ctx.app_user_id,
                                  permission_check="PASS", entitlement_check="PASS", status="COMPLETE", started_at=T0)
        return {"agentRunId": str(uuid.uuid4())}

    a, _ = two_tenants
    inv, turn = _open(a, app_user, ctx_for(a, user_id=app_user))
    reg = ActionRegistry([spec("pi.fake", agent=AgentCode.PI, source="PI", invoke=own_row, writes_own_run=True, slot_model=None)])
    leg = dispatch(turn, "pi.fake", None, registry=reg, now=T0)
    children = agent_run_repo.list_children(a, turn.anchor_run_id)
    assert leg.status is LegStatus.COMPLETE and len(children) == 1 and children[0]["agent_id"] == "PI" and children[0]["trigger_type"] == "DIRECT"
    assert agent_run_repo.CURRENT_PARENT_RUN_ID.get() is None


# ------------------------------------------------------------------------------------------- the CEO's own cap (D5, E7)
def test_ceo_cap_denies_the_turn_before_any_specialist_is_considered(two_tenants, app_user, migrate_engine):
    a, _ = two_tenants
    seed_platform_cap(migrate_engine, agent_code="CEO", meter_code="ceo.chat_turn", cap_value=1)
    ctx = ctx_for(a, user_id=app_user)

    first = open_turn(ctx, now=T0)
    assert meter_ceo_turn(a, member_id=app_user, turn_id=uuid.uuid4(), agent_run_id=first.anchor_run_id, occurred_at=T0) is not None

    with pytest.raises(TurnDenied) as exc:
        open_turn(ctx, now=later(1))
    assert exc.value.kind is Denial.ENTITLEMENT
    denied = agent_run_repo.get_run(a, exc.value.anchor_run_id)
    assert (denied["status"], denied["entitlement_check"], denied["agent_id"]) == ("DENIED", "DENIED:ceo.chat_turn", "CEO")
    assert agent_run_repo.list_children(a, exc.value.anchor_run_id) == []  # no sub-agent was even considered (E7)


def test_a_system_turn_is_not_blocked_by_and_does_not_consume_the_seller_cap(two_tenants, app_user, migrate_engine):
    a, _ = two_tenants
    seed_platform_cap(migrate_engine, agent_code="CEO", meter_code="ceo.chat_turn", cap_value=0)
    ctx = ctx_for(a, user_id=app_user)
    with pytest.raises(TurnDenied):
        open_turn(ctx, now=T0)  # a seller turn is blocked ...
    system = open_turn(ctx, trigger_type="SYSTEM", now=T0)  # ... a system run is not (CP1-D5)
    assert agent_run_repo.get_run(a, system.anchor_run_id)["trigger_type"] == "SYSTEM"
    assert row_counts(a, "metered_event") == {"metered_event": 0}


def test_turn_metering_is_idempotent_per_turn(two_tenants, app_user):
    a, _ = two_tenants
    turn_id = uuid.uuid4()
    ids = {meter_ceo_turn(a, member_id=app_user, turn_id=turn_id, occurred_at=T0) for _ in range(3)}
    assert len(ids) == 1 and None not in ids
    assert row_counts(a, "metered_event") == {"metered_event": 1}  # one delivered turn is exactly one unit (D5)



def test_ceo_entitlement_with_no_cap_is_honest(two_tenants):
    from backend.entitlement import resolve_ceo_entitlement

    a, _ = two_tenants
    result = resolve_ceo_entitlement(a, occurred_at=T0)
    assert result.passed and result.evaluation_basis == "NO_CAP_CONFIGURED" and result.cap_value is None and result.meter_code == "ceo.chat_turn"
