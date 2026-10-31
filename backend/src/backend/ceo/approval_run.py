"""Approving a stored plan and running exactly what it froze (ceo-approval-workflow.md sections 6.6 last paragraph, 6.7, D3, D5; ceo-cmo-delegation.md CD10, CD11).

The ONLY caller of `approve_plan` is the explicit approve endpoint, bound to the plan id and the plan hash. Nothing typed in chat, no clarification reply, no classifier
output and no replay reaches this module (the classifier has no approve route and no plan-id slot).

Order (all of it fails closed; a refusal runs nothing, meters nothing and creates no turn):
  1. checks 1-10 of section 6.6 (`approval.verify_for_approval`), in order;
  2. check 11: the investigation turn lock (409 TURN_IN_PROGRESS when busy), then the same checks again under the lock, so nothing changed in between;
  3. `open_turn` (the CEO cap and permissions, exactly as a turn does) opens the execution turn's anchor run;
  4. ONE transaction: the approval note, the execution turn (`route_source = APPROVAL`, `plan_id`), the compare-and-set AWAITING_APPROVAL -> APPROVED, the APPROVED event
     (`investigation_plan_repo.approve`). If the compare-and-set loses, everything in it is rolled back and nothing ran;
  5. only after that commit, dispatch begins: EXACTLY the frozen legs with the frozen validated slots, through the same choke point (per-leg permission, attachment and
     entitlement still apply, and the specialist's own quota admission runs again inside the leg). No classifier and no routing model is called; the answer is the
     deterministic template over what the legs returned (no composer call either).

D5: the approved plan is CONSUMED. A failed or interrupted execution is never retried by Metrion; the seller asks again and gets a new plan and a new approval. A repeat of
`approve` on an approved plan returns the SAME execution turn and never starts a second run, so a second meter event for the same operation cannot occur.

NOT built here (separately reviewed work, ceo-approval-remediation-design.md R5): crash reconciliation of an execution turn that dies mid-run (EXECUTION_NOT_STARTED,
OUTCOME_UNKNOWN). Until then a hard crash leaves the same non-terminal rows a normal turn would; that is why chat plan creation stays behind `CEO_APPROVAL_ENABLED`.
"""

from __future__ import annotations

import dataclasses
import logging
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from backend import config
from backend.ceo import approval, cmo_chat, cmo_delegation, expense_chat, import_chat, input_session, orchestrator, pi_research
from backend.ceo.approval import ApprovalRefused
from backend.ceo.billing import unit_decision
from backend.ceo.composer import template_only
from backend.ceo.contract import TERMINAL_TURN_STATUSES, ApprovalGrant, Denial, LegStatus, TurnDenied
from backend.ceo.dispatch import CeoTurn, open_turn
from backend.ceo.evidence import EvidenceCollector
from backend.ceo.plans import GST_ROUTE_KEYS, ResolvedSlots
from backend.ceo.presentation import present_leg
from backend.ceo.runtime import CeoRuntime, EventLog, EventSink, StageClock
from backend.ceo.turn_lock import TurnInProgress, investigation_turn_lock
from backend.auth.context import AuthContext
from backend.repositories import investigation_plan_repo as plan_repo, investigation_repo as repo
from backend.services import ceo_pi_research

logger = logging.getLogger(__name__)

EXECUTING = "RUNNING"  # what a client is told about an execution turn that has not reached a terminal status


@dataclass(slots=True)
class ApproveOutcome:
    replayed: bool  # True: the plan was already approved; this is the SAME execution turn, nothing new was started
    plan: dict[str, Any]
    turn_id: UUID
    turn_status: str  # the execution turn's current status, or RUNNING while it has not finished
    result: orchestrator.TurnResult | None = None  # present only for the call that actually ran the plan


def _turn_status(tenant: UUID, turn_id: UUID) -> str:
    row = repo.get_turn(tenant, turn_id)
    if row is None:
        return EXECUTING
    return str(row["status"]) if row["status"] in ("DELIVERED", "CLARIFIED", "DENIED", "FAILED", "PLANNED") else EXECUTING


def _replayed(tenant: UUID, row: dict[str, Any]) -> ApproveOutcome:
    turn_id = row["execution_turn_id"]
    return ApproveOutcome(True, row, turn_id, _turn_status(tenant, turn_id))


def _refusal_for(denied: TurnDenied) -> ApprovalRefused:
    if denied.kind is Denial.ENTITLEMENT:
        return ApprovalRefused(402, "ENTITLEMENT_DENIED", "ENTITLEMENT")
    return ApprovalRefused(403, "FORBIDDEN", "PERMISSION")


def approve_plan(
    ctx: AuthContext, runtime: CeoRuntime, investigation_id: UUID, plan_id: UUID, client_hash: str, *, sink: EventSink | None = None,
) -> ApproveOutcome:
    """See the module docstring. Raises `ApprovalRefused` (HTTP 403/404/409/402) with nothing run; returns the outcome otherwise."""
    assert ctx.tenant_id is not None
    tenant = ctx.tenant_id
    checked = approval.verify_for_approval(ctx, runtime, investigation_id, plan_id, client_hash, now=runtime.clock())
    if isinstance(checked, approval.Replay):
        return _replayed(tenant, checked.row)
    try:  # check 11
        with investigation_turn_lock(investigation_id, config.ceo_turn_lock_wait_seconds()):
            return _approve_locked(ctx, runtime, investigation_id, plan_id, client_hash, sink)
    except TurnInProgress:
        raise approval._refuse(tenant, plan_id, ctx.app_user_id, ApprovalRefused(409, "TURN_IN_PROGRESS", "TURN_LOCK")) from None


def _approve_locked(ctx: AuthContext, runtime: CeoRuntime, investigation_id: UUID, plan_id: UUID, client_hash: str, sink: EventSink | None) -> ApproveOutcome:
    assert ctx.tenant_id is not None
    tenant, user = ctx.tenant_id, ctx.app_user_id
    now = runtime.clock()
    checked = approval.verify_for_approval(ctx, runtime, investigation_id, plan_id, client_hash, now=now)  # again, under the lock: nothing changed since the first pass
    if isinstance(checked, approval.Replay):
        return _replayed(tenant, checked.row)
    plan = checked.row["plan"]
    try:
        turn = open_turn(ctx, investigation_id=investigation_id, trigger_ref="ceo.approved_plan", now=now)
    except TurnDenied as denied:
        raise approval._refuse(tenant, plan_id, user, _refusal_for(denied)) from None
    approved = plan_repo.approve(
        tenant, plan_id=plan_id, investigation_id=investigation_id, user_id=user, anchor_run_id=turn.anchor_run_id, route=str(plan["route"]), route_key=plan.get("route_key"),
        slots={}, note_content=approval.approved_note(plan), now=now,
    )
    if approved is None:  # lost the compare-and-set (declined / expired / superseded / approved by another request): nothing was written but this anchor, which is settled
        turn.close(status="DENIED", error_reason="plan no longer awaiting approval", now=runtime.clock())
        current = plan_repo.get(tenant, investigation_id, plan_id) or checked.row
        if current["status"] == "APPROVED":  # the other request won and approved it: the idempotent answer is its execution turn
            return _replayed(tenant, current)
        raise approval._refuse(tenant, plan_id, user, ApprovalRefused(409, "PLAN_EXPIRED" if current["status"] == "EXPIRED" else "PLAN_NOT_AWAITING", "LOST_RACE", status=current["status"]))
    turn.turn_id, turn.investigation_id = approved.execution_turn_id, investigation_id
    turn.presenter = lambda leg: present_leg(tenant, leg)
    clock = StageClock()
    log = EventLog(clock, sink)
    log.emit("TURN_ADMITTED", approvedPlanId=str(plan_id))
    plan_repo.record_event(tenant, plan_id, event="EXECUTION_STARTED", actor_user_id=user, metadata={"executionTurnId": str(approved.execution_turn_id), "anchorRunId": str(turn.anchor_run_id)}, now=runtime.clock())
    result = orchestrator.TurnResult("FAILED", str(plan["route"]), orchestrator.FAILED_TEXT)
    try:
        result = _run_frozen(ctx, runtime, plan_id, plan, turn, clock, log)
    except Exception:  # noqa: BLE001 - nothing internal reaches the seller; the server log has it. The plan stays consumed (D5): no retry.
        logger.exception("approved plan execution failed (tenant=%s plan=%s)", tenant, plan_id)
        log.emit("TURN_FAILED")
        try:
            result = orchestrator._finish(ctx, runtime, turn, clock, log, status="FAILED", route=str(plan["route"]), route_key=plan.get("route_key"), answer=orchestrator.FAILED_TEXT,
                                          kind="ANSWER", composition=None, anchor_status="FAILED", error_reason="turn failed")
        except Exception:  # noqa: BLE001
            logger.exception("could not record the failed execution turn")
            try:
                turn.close(status="FAILED", error_reason="turn failed", now=runtime.clock())
            except Exception:  # noqa: BLE001
                logger.exception("could not settle the execution turn's run")
            raise
    result.timings, result.events = clock.to_json(), list(log.events)
    try:
        repo.update_turn(tenant, approved.execution_turn_id, status=result.status if result.status in TERMINAL_TURN_STATUSES else "FAILED",
                         stage_timings=result.timings, completed_at=runtime.clock())
        result.findings = [orchestrator._public_finding(f) for f in repo.list_findings(tenant, investigation_id, turn_id=approved.execution_turn_id)]
    except Exception:  # noqa: BLE001
        logger.exception("could not finalise the execution turn")
    ok = (result.status == "DELIVERED" and (result.outcome in ("SUCCEEDED", "PARTIAL") if result.outcome is not None else True)) or (
        plan.get("route_key") == cmo_delegation.IMAGE_ACTION and result.status == "CLARIFIED" and result.choices is not None)  # the photo was read and the seller is being asked to confirm
    try:
        plan_repo.record_event(
            tenant, plan_id, event="EXECUTION_FINISHED" if ok else "EXECUTION_FAILED", actor_user_id=None, reason_code=result.status,
            metadata={"executionTurnId": str(approved.execution_turn_id), "status": result.status, "outcome": result.outcome,
                      "agentRunIds": [str(l.agent_run_id) for l in turn.legs if l.agent_run_id]},
            now=runtime.clock(),
        )
    except Exception:  # noqa: BLE001 - the audit write never costs the seller the result they already have
        logger.exception("could not record the execution result")
    return ApproveOutcome(False, plan_repo.get(tenant, investigation_id, plan_id) or checked.row, approved.execution_turn_id, result.status, result)


def _photo_reading_result(
    ctx: AuthContext, runtime: CeoRuntime, plan: dict[str, Any], legs: list[Any], refused_required: bool, turn: CeoTurn, clock: StageClock, log: EventLog,
) -> orchestrator.TurnResult:
    """The photo-reading plan ran (or failed). Success: the labelled observations plus the FIRST confirmation question of the seller's original request (state on that message, so a
    reload keeps it). Failure or nothing readable: said plainly, nothing guessed, nothing used. No CEO conversation unit is consumed by this step (it asks, it does not deliver);
    the writing that follows is its own plan and its own approval. Text and counts are written by code; no model is asked anything."""
    tenant = ctx.tenant_id
    assert tenant is not None and turn.investigation_id is not None
    route, key = str(plan["route"]), str(plan["route_key"])
    leg = next((l for l in legs if l.action_key == key), None)
    payload = dict(leg.payload or {}) if leg is not None and leg.status in (LegStatus.COMPLETE, LegStatus.PARTIAL) else None
    analysis = (payload or {}).get("analysis") or {}
    if refused_required or payload is None or analysis.get("state") == "FAILED":
        code = None if leg is None else ("NOT_AN_IMAGE" if "NOT_AN_IMAGE" in str(leg.reason or "") else None)
        status = "DENIED" if turn.legs and all(l.status in (LegStatus.DENIED, LegStatus.NOT_ENTITLED) for l in turn.legs) else "FAILED"
        text = cmo_delegation.analysis_unusable_text(payload, code) + " The plan you approved is spent; nothing was used up."
        return orchestrator._finish(ctx, runtime, turn, clock, log, status=status, route=route, route_key=key, answer=text, kind="ANSWER", composition=None,
                                    anchor_status=turn.derive_status() if turn.legs else "FAILED", error_reason="photo could not be read")
    followup = plan.get("followup") or {}
    attachment_id = UUID(str(followup["attachment_id"]))
    rows = repo.get_attachments(tenant, turn.investigation_id, [attachment_id])
    filename = str(rows[0]["filename"]) if rows else "your attachment"
    seen, visible = cmo_delegation.observations(payload)
    gate_open = bool((analysis.get("trustGate") or {}).get("open"))
    readable = any(k in seen for k in ("product_type", *input_session.IMAGE_FACT_ATTRS))
    shown = cmo_delegation.observation_text(filename, seen, visible, gate_open=gate_open)
    now = runtime.clock()
    started: Any = None
    if readable:
        hidden = {"_obs": seen, "_attachment": {"id": str(attachment_id), "sha256": str(rows[0].get("sha256")) if rows else None, "analysis_id": analysis.get("analysisId")}}
        started = input_session.start(str(followup["action_key"]), input_session.Ctx(tenant, now.date(), runtime.max_candidate_prices), prefill=followup.get("slots") or {}, hidden=hidden)
    if not isinstance(started, input_session.Ask):
        tail = ("Nothing usable could be read from it, so I have not guessed anything. " if not readable else "Nothing in it needs your confirmation for this request. ") + (
            "Tell me the product details in a message, for example “titles for steel water bottle on Amazon”, and I will ask for what is missing.")
        return orchestrator._finish(ctx, runtime, turn, clock, log, status="CLARIFIED", route=route, route_key=key, answer=shown + "\n\n" + tail, kind="ANSWER", composition=None,
                                    anchor_status=turn.derive_status())
    ask = cmo_delegation.begin(started, action_key=str(followup["action_key"]), now=now)
    return orchestrator._finish(ctx, runtime, turn, clock, log, status="CLARIFIED", route=route, route_key=key, answer=shown + "\n\n" + ask.text, kind="CLARIFICATION", composition=None,
                                anchor_status=turn.derive_status(), clarify_for=str(ask.card["slot"]), choices=ask.card)


def _run_frozen(ctx: AuthContext, runtime: CeoRuntime, plan_id: UUID, plan: dict[str, Any], turn: CeoTurn, clock: StageClock, log: EventLog) -> orchestrator.TurnResult:
    """Runs EXACTLY the frozen legs. No classification, no routing, no composer call: the answer is the deterministic template over what the legs returned."""
    tenant = ctx.tenant_id
    assert tenant is not None and turn.investigation_id is not None
    route, key = str(plan["route"]), plan.get("route_key")
    leg_keys = [str(l["action_key"]) for l in plan["legs"]]
    frozen = {str(l["action_key"]): l["slots"] for l in plan["legs"]}
    then_keys = [str(l["action_key"]) for l in plan.get("then", [])]  # follow-up steps listed on the card and covered by this one approval
    grant = ApprovalGrant(plan_id, tenant, frozenset([*leg_keys, *then_keys]))
    required = set(leg_keys)  # every leg of the approved plan is what the seller approved: any of them failing is a failed execution
    now = runtime.clock()
    attached = repo.attached_agents(tenant, turn.investigation_id)
    log.emit("PLAN_VALIDATED", route=route, routeKey=key)
    wait_runtime = runtime
    if then_keys and "pi.discover" in leg_keys:  # a real research run takes minutes: it gets its own, longer wait (config.ceo_pi_research_timeout_seconds), never shorter than the ordinary one
        longer = config.ceo_pi_research_timeout_seconds()
        if longer is not None and runtime.leg_timeout_seconds is not None and longer > runtime.leg_timeout_seconds:
            wait_runtime = dataclasses.replace(runtime, leg_timeout_seconds=longer)
    with cmo_chat.title_step_scope(plan):  # N-16a: a title step of a complete-listing request carries the server-side marker (copied into each leg thread)
        legs, entries, refused_required = orchestrator._execute(ctx, wait_runtime, turn, ResolvedSlots(tenant_id=tenant, today=now.date()), leg_keys, required, (), attached, now, clock, log, frozen, grant)
    if key == cmo_delegation.IMAGE_ACTION:  # the photo reading: its result is NOT a deliverable but the start of the confirmation questions
        return _photo_reading_result(ctx, runtime, plan, legs, refused_required, turn, clock, log)
    chain_gaps: list[str] = []
    chain_run: UUID | None = None
    if "pi.discover" in leg_keys and then_keys:  # CEO-driven research: top five, supplier lookup for those five, the final case, then the saved report is read back
        legs, chain_gaps, chain_run = pi_research.run_followups(ctx, runtime, turn, now, legs, attached, clock, log, grant, then_keys)
    elif "pi.discover" in leg_keys:  # the run's candidates are read back from what it saved (a read; it starts no new research)
        legs = orchestrator._with_pi_report(runtime, turn, tenant, now, legs, attached, clock, log)
        orchestrator._record_pi_finding(tenant, ctx.app_user_id, legs)
    collector = EvidenceCollector(tenant)
    disclaimers: list[tuple[str, str]] = []
    for leg in legs:
        if chain_run is not None and leg.action_key == "pi.report":
            continue  # the other discovered candidates are internal: only the five final products are described (by `pi_research.summary_text`)
        collector.add_leg(leg)
        if leg.action_key in GST_ROUTE_KEYS and leg.payload and (leg.payload.get("result") or {}).get("disclaimer"):
            disclaimers.append(("GST_LOOKUP", str(leg.payload["result"]["disclaimer"])))
    for entry in entries:
        collector.add_entry(entry)
    for k in leg_keys:
        if not any(l.action_key == k for l in legs):  # a leg that missed its deadline: named, never silently absent
            collector.add_gap(f"{orchestrator._label(k)} is still running; its result will appear in this investigation's findings when it finishes.")
            refused_required = True
    table = collector.table(untrusted=[], disclaimers=disclaimers, attach=[])
    if cmo_delegation.nothing_delivered(legs):  # the CMO ran but wrote nothing usable (every artefact failed): a failed execution that says so, never "here is what was produced"
        refused_required = True
    late = [k for k in leg_keys if not any(l.action_key == k for l in legs)]
    if refused_required and late and len(late) == len(leg_keys) and key in cmo_delegation.DELEGATED_ACTIONS:  # nothing failed: the agent is just slower than the CEO waits
        comp = template_only(table, heading="This is taking longer than usual.")
        return orchestrator._finish(ctx, runtime, turn, clock, log, status="FAILED", route=route, route_key=key, kind="ANSWER", composition=comp, anchor_status="FAILED",
                                    error_reason="the agent is still running",
                                    answer=comp.text + "\n\nNothing failed and nothing has been charged yet. I will post the result here in this conversation when it finishes, and it will also appear on your Slim CMO dashboard. Please do not ask again: that would start a second run.")
    if refused_required:
        comp = template_only(table, heading="I could not complete this plan. Here is what is available:")
        status = "DENIED" if all(l.status in (LegStatus.DENIED, LegStatus.NOT_ENTITLED) for l in turn.legs) and turn.legs else "FAILED"
        failed_text = comp.text + (
            "\n\nA result that did not complete is not charged to your plan. The plan you approved is spent; ask again for a new plan." if key in cmo_delegation.DELEGATED_ACTIONS else "")
        return orchestrator._finish(ctx, runtime, turn, clock, log, status=status, route=route, route_key=key, answer=failed_text, kind="ANSWER", composition=comp,
                                    anchor_status=turn.derive_status() if turn.legs else "FAILED", error_reason="a required leg did not complete")
    delegated = key in cmo_delegation.DELEGATED_ACTIONS
    heading = (expense_chat.heading_for(str(key)) if key in expense_chat.WRITE_KEYS
               else import_chat.heading() if key == import_chat.IMPORT_KEY
               else "Here is what Product Intelligence found for your niche." if key == "pi.discover"
               else "I could not complete this plan. Here is what is available:" if delegated and cmo_delegation.any_leg_failed(legs)
               else cmo_delegation.heading_for(key) if delegated else "Here is what was produced for the plan you approved.")
    comp = template_only(table, heading=heading)
    answer = comp.text + ("\n\n" + cmo_delegation.result_footer(legs) if delegated else "")
    pick_card: dict[str, Any] | None = None
    if key == "ci.discover_competitors":
        try:
            from backend.ceo import ci_conversation  # noqa: PLC0415

            answer += "\n\n" + ci_conversation.discovery_followup(tenant)
            pick_card = ci_conversation.candidate_card(tenant)
        except Exception:  # noqa: BLE001 - the list is a convenience: the search result above stands without it
            logger.exception("could not list the discovery leads")
    if key in ("cmo.generate_full_listing", "cmo.rewrite_listing_section"):  # CMO 3.0 M6: the complete listing (or the new version after a rewrite) rides on this answer as a LISTING card
        leg = next((l for l in legs if l.action_key == key and l.payload), None)
        card = (leg.payload or {}).get("card") if leg is not None else None
        if isinstance(card, dict) and card.get("kind") == "LISTING":
            pick_card = {**card, "investigationId": str(turn.investigation_id)}
            answer += "\n\n" + ("The card below shows the new version: only the section you named changed, and the earlier version is still saved. Nothing is published, and approving it for use only records your decision in Metrion."
                                  if key == "cmo.rewrite_listing_section" else
                                  "The card below shows the listing, where each researched keyword is used, the audit and what it could not check. Nothing is published, and approving it for use only records your decision in Metrion.")
    if chain_run is not None:
        case = ceo_pi_research.load_case(tenant, chain_run)
        if case is not None:  # the seller reads the five-product summary, written by code from the saved case; the "View Detailed Research" link comes from the pi.report finding
            answer = pi_research.summary_text(case, chain_gaps)
    return orchestrator._finish(ctx, runtime, turn, clock, log, status="DELIVERED", route=route, route_key=key, answer=answer, kind="ANSWER", composition=comp,
                                anchor_status=turn.derive_status(), choices=pick_card,
                                billing=unit_decision(status="DELIVERED", route=route, planned_leg_keys=leg_keys, required_keys=required, legs=turn.legs))
