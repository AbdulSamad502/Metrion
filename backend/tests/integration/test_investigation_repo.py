"""Investigation lifecycle, turns, findings, attachment and the `agent_run` repo changes (spec §6.14, §6.22, resolved Q23, AC42)."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest

from backend.repositories import agent_run_repo, investigation_repo as repo
from tests.integration.ceo_support import ALL_AGENTS, T0, later


def _inv(tenant, user, **kw):
    return repo.create_investigation(tenant, created_by=user, attached_agents=kw.pop("attached", ("CFO", "CI")), now=T0, **kw)


def _run(tenant, user, inv=None, **kw):
    return agent_run_repo.insert_run(
        tenant, agent_id=kw.pop("agent_id", "CEO"), trigger_type=kw.pop("trigger_type", "CONVERSATIONAL"), trigger_ref=kw.pop("trigger_ref", "ceo.chat_turn"),
        requested_by=user, permission_check="PASS", entitlement_check="PASS", status=kw.pop("status", "RUNNING"), started_at=T0, investigation_id=inv, **kw,
    )


# ------------------------------------------------------------------------------------------- lifecycle
def test_create_defaults_and_attached_agents(two_tenants, app_user):
    a, _ = two_tenants
    inv = repo.create_investigation(a, created_by=app_user, title="Profit drop", attached_agents=("CFO", "PI"), detached_agents=("CMO",), now=T0)
    row = repo.get_investigation(a, inv)
    assert row["status"] == "ACTIVE" and row["origin"] == "USER_CHAT" and row["title"] == "Profit drop" and row["resolved_at"] is None
    assert repo.attached_agents(a, inv) == frozenset({"CFO", "PI"})
    assert repo.agent_states(a, inv) == {"CFO": True, "PI": True, "CMO": False}


def test_an_agent_with_no_row_is_not_attached(two_tenants, app_user):
    a, _ = two_tenants
    inv = _inv(a, app_user, attached=("CFO",))
    assert "CI" not in repo.attached_agents(a, inv)  # fail closed


@pytest.mark.parametrize("attached, detached", [(("CEO",), ()), (("NOPE",), ()), (("CFO",), ("CFO",))])
def test_invalid_agent_sets_are_rejected(two_tenants, app_user, attached, detached):
    a, _ = two_tenants
    with pytest.raises(ValueError):
        repo.create_investigation(a, created_by=app_user, attached_agents=attached, detached_agents=detached)


def test_invalid_origin_is_rejected(two_tenants, app_user):
    a, _ = two_tenants
    with pytest.raises(ValueError):
        repo.create_investigation(a, created_by=app_user, origin="TELEPATHY")


def test_resolve_needs_a_real_note_and_an_active_investigation(two_tenants, app_user):
    a, _ = two_tenants
    inv = _inv(a, app_user)
    for note in ("", "   ", None):
        with pytest.raises(ValueError):
            repo.resolve_investigation(a, inv, resolved_by=app_user, resolution_note=note)  # type: ignore[arg-type]
    assert repo.get_investigation(a, inv)["status"] == "ACTIVE"  # CEO cannot resolve by itself: nothing changed
    repo.resolve_investigation(a, inv, resolved_by=app_user, resolution_note="  Repriced SKU X; margin back on goal.  ", now=later(1))
    row = repo.get_investigation(a, inv)
    assert row["status"] == "RESOLVED" and row["resolution_note"] == "Repriced SKU X; margin back on goal." and row["resolved_by"] == app_user
    with pytest.raises(repo.InvalidInvestigationTransition):
        repo.resolve_investigation(a, inv, resolved_by=app_user, resolution_note="again")


def test_reopen_clears_the_conclusion_and_data_is_retained(two_tenants, app_user):
    a, _ = two_tenants
    inv = _inv(a, app_user)
    repo.append_message(a, inv, role="USER", content="hello", created_by=app_user, now=T0)
    repo.resolve_investigation(a, inv, resolved_by=app_user, resolution_note="done")
    repo.reopen_investigation(a, inv)
    row = repo.get_investigation(a, inv)
    assert row["status"] == "ACTIVE" and row["resolution_note"] is None and row["resolved_at"] is None and row["resolved_by"] is None
    assert len(repo.list_messages(a, inv)) == 1  # nothing was lost
    with pytest.raises(repo.InvalidInvestigationTransition):
        repo.reopen_investigation(a, inv)


def test_archive_hides_without_a_conclusion_and_can_be_reopened(two_tenants, app_user):
    a, _ = two_tenants
    inv = _inv(a, app_user)
    repo.archive_investigation(a, inv)
    assert repo.get_investigation(a, inv)["status"] == "ARCHIVED"
    assert [r["id"] for r in repo.list_investigations(a, status="ARCHIVED")] == [inv] and repo.list_investigations(a, status="ACTIVE") == []
    with pytest.raises(repo.InvalidInvestigationTransition):
        repo.archive_investigation(a, inv)
    repo.reopen_investigation(a, inv)
    assert repo.get_investigation(a, inv)["status"] == "ACTIVE"


def test_list_is_most_recent_first_and_filterable(two_tenants, app_user):
    a, _ = two_tenants
    first, second = _inv(a, app_user), _inv(a, app_user)
    repo.append_message(a, first, role="USER", content="newer activity", created_by=app_user, now=later(5))
    assert [r["id"] for r in repo.list_investigations(a)][:2] == [first, second]


# ------------------------------------------------------------------------------------------- messages
def test_messages_are_ordered_and_the_summary_window_returns_only_later_ones(two_tenants, app_user):
    a, _ = two_tenants
    inv = _inv(a, app_user)
    ids = [repo.append_message(a, inv, role="USER" if i % 2 == 0 else "CEO", content=f"m{i}", created_by=app_user if i % 2 == 0 else None, now=later(i)) for i in range(5)]
    assert [m["content"] for m in repo.list_messages(a, inv)] == ["m0", "m1", "m2", "m3", "m4"]
    assert [m["content"] for m in repo.list_messages(a, inv, after_message_id=ids[2])] == ["m3", "m4"]  # AC9: summary + messages since covers_through
    assert repo.get_investigation(a, inv)["last_message_at"] == later(4)


def test_invalid_message_role_or_kind_is_rejected(two_tenants, app_user):
    a, _ = two_tenants
    inv = _inv(a, app_user)
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        repo.append_message(a, inv, role="ROBOT", content="x")
    with pytest.raises(IntegrityError):
        repo.append_message(a, inv, role="CEO", content="x", kind="GOSSIP")


# ------------------------------------------------------------------------------------------- turns & findings
def test_turn_lifecycle_and_message_back_pointer(two_tenants, app_user):
    a, _ = two_tenants
    inv = _inv(a, app_user)
    user_msg = repo.append_message(a, inv, role="USER", content="why?", created_by=app_user, now=T0)
    anchor = _run(a, app_user, inv)
    turn = repo.create_turn(a, inv, user_message_id=user_msg, agent_run_id=anchor, route="PLAYBOOK", route_key="PROFIT_DIAGNOSIS",
                            route_source="UI_ACTION", slots={"period": "2026-09"}, classifier_result=None, now=T0)
    row = repo.get_turn(a, turn)
    assert (row["route"], row["route_key"], row["route_source"], row["status"]) == ("PLAYBOOK", "PROFIT_DIAGNOSIS", "UI_ACTION", "RECEIVED")
    assert row["slots"] == {"period": "2026-09"}
    assert [m for m in repo.list_messages(a, inv) if m["id"] == user_msg][0]["turn_id"] == turn

    ceo_msg = repo.append_message(a, inv, role="CEO", kind="ANSWER", content="answer", agent_run_id=anchor, turn_id=turn, now=later(1))
    repo.update_turn(a, turn, status="DELIVERED", ceo_message_id=ceo_msg, composition_mode="TEMPLATE_FALLBACK",
                     safety_result={"gate": "FAILED"}, stage_timings={"classify_ms": None}, completed_at=later(1))
    done = repo.get_turn(a, turn)
    assert done["status"] == "DELIVERED" and done["ceo_message_id"] == ceo_msg and done["composition_mode"] == "TEMPLATE_FALLBACK"
    assert done["safety_result"] == {"gate": "FAILED"} and done["completed_at"] == later(1)
    repo.update_turn(a, turn, status="DELIVERED")  # a bare status update must not erase earlier fields
    assert repo.get_turn(a, turn)["composition_mode"] == "TEMPLATE_FALLBACK"
    assert [t["id"] for t in repo.list_turns(a, inv)] == [turn]


def test_one_anchor_run_cannot_back_two_turns(two_tenants, app_user):
    a, _ = two_tenants
    inv = _inv(a, app_user)
    anchor = _run(a, app_user, inv)
    m1 = repo.append_message(a, inv, role="USER", content="1", created_by=app_user)
    m2 = repo.append_message(a, inv, role="USER", content="2", created_by=app_user)
    repo.create_turn(a, inv, user_message_id=m1, agent_run_id=anchor, route="ACTION")
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        repo.create_turn(a, inv, user_message_id=m2, agent_run_id=anchor, route="ACTION")


def test_findings_hold_refs_and_pointers_only(two_tenants, app_user):
    a, _ = two_tenants
    inv = _inv(a, app_user)
    turn = _turn(a, app_user, inv)
    ref = {"kind": "ENGINE_RESULT", "id": str(uuid.uuid4())}
    fid = repo.insert_finding(a, inv, turn_id=turn, source="CFO", action_key="cfo.pricing", status="PARTIAL", figure_refs=[ref],
                              report_ref={"generationId": str(uuid.uuid4())}, gap_reason="COGS missing", now=T0)
    [row] = repo.list_findings(a, inv)
    assert row["id"] == fid and row["figure_refs"] == [ref] and row["status"] == "PARTIAL" and row["gap_reason"] == "COGS missing"
    # No numeric value column exists. `presentation` (B5) is the display snapshot of values resolved through their refs; it is None when the caller
    # presents nothing, and is covered in test_ceo_presentation.py.
    assert set(row) == {"id", "turn_id", "agent_run_id", "source", "action_key", "status", "figure_refs", "report_ref", "gap_reason", "presentation", "created_at"}
    assert row["presentation"] is None


def _turn(tenant, user, inv):
    msg = repo.append_message(tenant, inv, role="USER", content="q", created_by=user, now=T0)
    return repo.create_turn(tenant, inv, user_message_id=msg, agent_run_id=_run(tenant, user, inv), route="ACTION", now=T0)


def test_findings_can_be_listed_per_turn(two_tenants, app_user):
    a, _ = two_tenants
    inv = _inv(a, app_user)
    t1, t2 = _turn(a, app_user, inv), _turn(a, app_user, inv)
    repo.insert_finding(a, inv, turn_id=t1, source="CFO", action_key="k1", status="COMPLETE", now=T0)
    repo.insert_finding(a, inv, turn_id=t2, source="CI", action_key="k2", status="COMPLETE", now=later(1))
    assert [f["action_key"] for f in repo.list_findings(a, inv, turn_id=t2)] == ["k2"]
    assert [f["action_key"] for f in repo.list_findings(a, inv)] == ["k1", "k2"]


# ------------------------------------------------------------------------------------------- Q23
def test_detaching_an_agent_never_erases_or_hides_its_earlier_findings(two_tenants, app_user):
    """Resolved Q23: previously completed and verified findings from a detached agent remain visible as historical evidence, with
    their original refs; detaching only stops NEW invocation."""
    a, _ = two_tenants
    inv = _inv(a, app_user, attached=("CFO", "CI"))
    turn = _turn(a, app_user, inv)
    ref = {"kind": "ENGINE_RESULT", "id": str(uuid.uuid4()), "as_of": T0.isoformat()}
    fid = repo.insert_finding(a, inv, turn_id=turn, source="CFO", action_key="cfo.financial_health", status="COMPLETE", figure_refs=[ref],
                              report_ref={"agentRunId": str(uuid.uuid4())}, now=T0)
    before = repo.list_findings(a, inv)

    repo.set_agent_attachment(a, inv, "CFO", attached=False, changed_by=app_user, now=later(2))
    assert "CFO" not in repo.attached_agents(a, inv) and repo.agent_states(a, inv)["CFO"] is False
    assert repo.list_findings(a, inv) == before  # identical: nothing erased, hidden, or invalidated
    assert repo.list_findings(a, inv)[0]["id"] == fid and repo.list_findings(a, inv)[0]["figure_refs"] == [ref]

    repo.set_agent_attachment(a, inv, "CFO", attached=True, changed_by=app_user, now=later(3))  # and re-attaching changes nothing either
    assert repo.list_findings(a, inv) == before


def test_attachment_changes_are_recorded_with_who_and_when(two_tenants, app_user):
    a, _ = two_tenants
    inv = _inv(a, app_user, attached=("CFO",))
    other = uuid.uuid4()
    repo.set_agent_attachment(a, inv, "CFO", attached=False, changed_by=other, now=later(7))
    from sqlalchemy import text
    from backend.tenant_context import tenant_scope

    with tenant_scope(a) as conn:
        row = conn.execute(text("SELECT attached, changed_by, changed_at FROM investigation_agent WHERE investigation_id = :i AND agent_code = 'CFO'"), {"i": str(inv)}).one()
    assert row == (False, other, later(7))


def test_unknown_agent_cannot_be_attached(two_tenants, app_user):
    a, _ = two_tenants
    inv = _inv(a, app_user)
    with pytest.raises(ValueError):
        repo.set_agent_attachment(a, inv, "CEO", attached=True, changed_by=app_user)


# ------------------------------------------------------------------------------------------- agent_run_repo (gap 2, R5)
def test_agent_run_stores_investigation_id_and_output_refs(two_tenants, app_user):
    a, _ = two_tenants
    inv = _inv(a, app_user)
    refs = [{"kind": "ENGINE_RESULT", "id": str(uuid.uuid4())}]
    run = _run(a, app_user, inv, output_refs=refs)
    row = agent_run_repo.get_run(a, run)
    assert row["investigation_id"] == inv and row["output_refs"] == refs and row["trigger_type"] == "CONVERSATIONAL"


def test_finish_run_sets_output_refs_and_a_plain_status_update_keeps_them(two_tenants, app_user):
    a, _ = two_tenants
    run = _run(a, app_user)
    refs = [{"kind": "ESTIMATE", "id": str(uuid.uuid4())}]
    agent_run_repo.finish_run(a, run, status="PARTIAL", error_reason=None, finished_at=later(1), output_refs=refs)
    assert agent_run_repo.get_run(a, run)["output_refs"] == refs
    agent_run_repo.finish_run(a, run, status="COMPLETE", error_reason=None, finished_at=later(2))  # no output_refs argument
    row = agent_run_repo.get_run(a, run)
    assert row["status"] == "COMPLETE" and row["output_refs"] == refs and row["finished_at"] == later(2)


def test_rows_written_inside_a_parent_scope_become_children(two_tenants, app_user):
    a, _ = two_tenants
    anchor = _run(a, app_user, inherit_parent=False)
    with agent_run_repo.parent_run_scope(anchor):
        child = _run(a, app_user, agent_id="PI", trigger_type="DIRECT", trigger_ref="pi.discover")
        opted_out = _run(a, app_user, inherit_parent=False)
        explicit = _run(a, app_user, parent_run_id=child)
    outside = _run(a, app_user, agent_id="CFO", trigger_type="DIRECT", trigger_ref="cfo.pnl")
    assert agent_run_repo.get_run(a, child)["parent_run_id"] == anchor
    assert agent_run_repo.get_run(a, opted_out)["parent_run_id"] is None
    assert agent_run_repo.get_run(a, explicit)["parent_run_id"] == child  # an explicit parent always wins
    assert agent_run_repo.get_run(a, outside)["parent_run_id"] is None  # AC2: direct rows outside a CEO scope have no parent
    assert [r["id"] for r in agent_run_repo.list_children(a, anchor)] == [child]
    assert agent_run_repo.CURRENT_PARENT_RUN_ID.get() is None  # the scope never leaks


def test_the_parent_scope_is_per_thread_of_execution(two_tenants, app_user):
    """A scope set in one thread must not bleed into a concurrent leg (the parallel playbook legs of B4 each run in their own context)."""
    import contextvars
    from concurrent.futures import ThreadPoolExecutor

    a, _ = two_tenants
    anchor_one, anchor_two = _run(a, app_user, inherit_parent=False), _run(a, app_user, inherit_parent=False)

    def leg(anchor):
        with agent_run_repo.parent_run_scope(anchor):
            return _run(a, app_user, agent_id="CFO", trigger_ref=f"cfo.leg.{anchor}")

    with ThreadPoolExecutor(max_workers=2) as pool:
        f1 = pool.submit(contextvars.copy_context().run, leg, anchor_one)
        f2 = pool.submit(contextvars.copy_context().run, leg, anchor_two)
        c1, c2 = f1.result(), f2.result()
    assert agent_run_repo.get_run(a, c1)["parent_run_id"] == anchor_one and agent_run_repo.get_run(a, c2)["parent_run_id"] == anchor_two
