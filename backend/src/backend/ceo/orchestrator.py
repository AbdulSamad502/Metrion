"""The first real end-to-end CEO turn — spec §6.3–§6.5, §6.12, §6.22, §6.26 (B3).

    seller message
      -> admission (permission + CEO cap, anchor `agent_run`)            [dispatch.open_turn]
      -> ONE classification pass (closed enum + slot text)                [classifier]
      -> deterministic plan validation (catalog, slots, periods)          [plans, periods]
      -> per-leg permission / attachment / entitlement pre-flight         [here + dispatch re-checks every leg]
      -> parallel specialist legs + Business State reads, findings emitted as each completes   [dispatch, business_state]
      -> evidence table (every figure resolved through its ref)           [evidence, provenance]
      -> at most ONE composition call, then the numeral/provenance gate   [composer, composition_gate]
      -> persisted CEO answer, turn, findings, timings

Code owns every decision except "what did the seller mean" (classification) and "how to word the evidence" (composition). The model
never selects a tool outside the closed catalog, never builds a leg, never supplies a date or a number, and never attaches an agent.
A turn that cannot be answered safely ends in a plain explanation or a fixed template — never a guess.
"""

from __future__ import annotations

import contextvars
import logging
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any
from uuid import UUID

from backend.auth.context import AuthContext
from backend.auth.permissions import AGENT_CEO, INVESTIGATION_CREATE, has_permission
from backend.ceo import business_state, classifier
from backend.ceo.capabilities import NOT_ATTACHED, NOT_ENTITLED, NOT_PERMITTED, PRESENT, Capabilities, compute_capabilities
from backend.ceo.composer import Composition, compose, template_only
from backend.ceo.contract import AgentCode, BusinessStateEntry, Denial, LegResult, LegStatus, TurnDenied
from backend.ceo.dispatch import CeoTurn, dispatch, open_turn
from backend.ceo.evidence import EvidenceCollector, finding_status_for_entry
from backend.ceo.plans import ACTIONS, PLAYBOOKS, SLOT_QUESTIONS, Clarification, ResolvedSlots, resolve_slots
from backend.ceo.runtime import CeoRuntime, EventLog, EventSink, StageClock, TurnEvent
from backend.entitlement import meter_ceo_turn
from backend.repositories import investigation_repo as repo

logger = logging.getLogger(__name__)

MAX_MESSAGE_CHARS = 4000  # a request-size bound, not a business threshold
GENERAL_GUIDANCE_TEXT = "This is general advice, not derived from your data."


class InvestigationNotActive(Exception):
    def __init__(self, status: str) -> None:
        super().__init__(status)
        self.status = status


@dataclass(slots=True)
class TurnResult:
    status: str  # DELIVERED | CLARIFIED | DENIED | FAILED
    route: str
    answer: str
    turn_id: UUID | None = None
    route_key: str | None = None
    message_id: UUID | None = None
    composition_mode: str | None = None
    findings: list[dict[str, Any]] = field(default_factory=list)
    timings: dict[str, Any] = field(default_factory=dict)
    events: list[TurnEvent] = field(default_factory=list)
    clarify_for: str | None = None
    notes: list[str] = field(default_factory=list)  # period/marketplace interpretations echoed back to the seller (AC17)


# ------------------------------------------------------------------------------------------------ investigations
def start_investigation(ctx: AuthContext, runtime: CeoRuntime, *, title: str | None = None) -> UUID:
    """A NEW investigation exists only when the seller explicitly starts one (C6). Default attachment (§6.22 rule 1): every agent the
    tenant is entitled to; an agent it is not entitled to is recorded as detached (LOCKED in the UI). Attachment grants nothing."""
    assert ctx.tenant_id is not None and ctx.role is not None
    for key in (AGENT_CEO, INVESTIGATION_CREATE):
        if not has_permission(role=ctx.role, permissions=ctx.permissions, key=key):
            raise PermissionError(key)
    now = runtime.clock()
    caps = compute_capabilities(ctx, runtime.registry, frozenset(a.value for a in AgentCode), now=now)
    attached = [a for a, s in caps.agent_status.items() if s != NOT_ENTITLED]
    detached = [a for a, s in caps.agent_status.items() if s == NOT_ENTITLED]
    return repo.create_investigation(ctx.tenant_id, created_by=ctx.app_user_id, title=title, attached_agents=attached, detached_agents=detached, now=now)


# ------------------------------------------------------------------------------------------------ fixed texts (no model)
_QUESTIONS = {
    "WHICH_AGENT": "Which area should I look at: your profit and payments, your competitors, product research, or your listings?",
    "UNCLEAR_REQUEST": "I'm not sure what you'd like me to do. You can ask about your profit, leaks, payments or the health of your business.",
    "sku": "Which product (SKU) do you mean?", "product": "Which product do you mean?", "quantity": "How many units?", "amount": "What amount?",
    "competitor": "Which competitor do you mean?", "niche": "Which niche do you mean?", "option": "Which option do you mean?",
    "compare_period": "Which period should I compare it with?",
}
OUT_OF_SCOPE_TEXT = (
    "I can't do that from here. I only recommend: I can't change anything on a marketplace, record or remove entries, or upload files. "
    "Some specialist capabilities (such as pricing curves, landed cost, listing writing and market trends) also can't be run from chat yet; "
    "please use that agent's own page for them."
)
DENIED_TEXT = {
    Denial.PERMISSION: "You do not have access to the CEO for this investigation.",
    Denial.ENTITLEMENT: "Your CEO conversation allowance for this period has been used. It resets with your plan period.",
}
FAILED_TEXT = "Something went wrong on our side and nothing was changed. Please try again."
CONFIG_TEXT = "The CEO's investigation limits have not been configured by the operator yet, so this investigation cannot run."


def _clarification_text(slot: str) -> str:
    return SLOT_QUESTIONS.get(slot) or _QUESTIONS.get(slot) or _QUESTIONS["UNCLEAR_REQUEST"]  # period / marketplace wording lives with the resolvers


# ------------------------------------------------------------------------------------------------ context
def _turn_context(tenant: UUID, inv: dict[str, Any], current_msg: UUID) -> tuple[classifier.TurnContext, str | None]:
    msgs = [m for m in repo.list_messages(tenant, inv["id"], after_message_id=inv.get("summary_covers_through")) if m["id"] != current_msg]
    recent = tuple((str(m["role"]), str(m["content"])[:400]) for m in msgs[-classifier.MAX_RECENT_MESSAGES:] if m["kind"] != "SYSTEM_NOTE")
    findings = tuple(
        f"{f['action_key']} {f['status']} as of {f['created_at'].date().isoformat()}" for f in repo.list_findings(tenant, inv["id"])[-12:]
    )
    earlier_questions = [str(m["content"])[:200] for m in msgs if m["role"] == "USER"][-3:]  # questions only: CEO answers carry figures
    summary = inv.get("summary")
    composer_ctx = " | ".join(x for x in (summary, ("Earlier the seller asked: " + "; ".join(earlier_questions)) if earlier_questions else None) if x) or None
    return classifier.TurnContext(summary, recent, findings), composer_ctx


# ------------------------------------------------------------------------------------------------ the turn
def run_turn(
    ctx: AuthContext, runtime: CeoRuntime, investigation_id: UUID, message: str, *, sink: EventSink | None = None,
    period: tuple[date, date] | None = None,
) -> TurnResult:
    """`period` is an explicit (start, end) the seller chose with the date-range control. When given it is the period for this turn: it
    is passed to the classifier as a preset slot (the model neither chooses nor withholds it) and resolved by the same deterministic code."""
    assert ctx.tenant_id is not None and ctx.role is not None
    tenant = ctx.tenant_id
    text = message.strip()
    if not text or len(text) > MAX_MESSAGE_CHARS:
        raise ValueError("message must be 1-%d characters" % MAX_MESSAGE_CHARS)
    inv = repo.get_investigation(tenant, investigation_id)  # RLS: another tenant's id is indistinguishable from a missing one
    if inv is None:
        raise repo.InvestigationNotFound(str(investigation_id))
    if inv["status"] != "ACTIVE":
        raise InvestigationNotActive(str(inv["status"]))

    clock = StageClock()
    log = EventLog(clock, sink)
    now = runtime.clock()
    log.emit("TURN_RECEIVED")
    with clock.span("admission"):
        try:
            turn = open_turn(ctx, investigation_id=investigation_id, now=now)  # permission + CEO cap, BEFORE anything is written to the investigation
        except TurnDenied as denied:
            answer = DENIED_TEXT.get(denied.kind, DENIED_TEXT[Denial.PERMISSION])
            msg_id: UUID | None = None
            if denied.kind is Denial.ENTITLEMENT:  # the member may view this investigation: keep their question and the explanation in it
                repo.append_message(tenant, investigation_id, role="USER", content=text, created_by=ctx.app_user_id, now=now)
                msg_id = repo.append_message(tenant, investigation_id, role="CEO", kind="ANSWER", content=answer, agent_run_id=denied.anchor_run_id, now=runtime.clock())
            log.emit("TURN_DENIED", reason=denied.kind.value)  # a member without the permission leaves only the DENIED audit row (R12)
            return TurnResult("DENIED", "ADVISORY", answer, message_id=msg_id, timings=clock.to_json(), events=list(log.events))
    user_msg = repo.append_message(tenant, investigation_id, role="USER", content=text, created_by=ctx.app_user_id, now=runtime.clock())
    log.emit("TURN_ADMITTED")

    result = TurnResult("FAILED", "CLARIFY", FAILED_TEXT)
    try:
        result = _run_admitted(ctx, runtime, inv, user_msg, text, turn, clock, log, period)
    except Exception:  # noqa: BLE001 — R12: nothing internal reaches the seller; the server log has it
        logger.exception("CEO turn failed (tenant=%s investigation=%s)", tenant, investigation_id)
        log.emit("TURN_FAILED")
        result = _finish(ctx, runtime, turn, clock, log, status="FAILED", route=result.route, route_key=None, answer=FAILED_TEXT, kind="ANSWER", composition=None,
                         anchor_status="FAILED", error_reason="turn failed")
    result.timings = clock.to_json()
    result.events = list(log.events)
    if result.turn_id is not None:
        try:
            repo.update_turn(tenant, result.turn_id, status=result.status if result.status in ("DELIVERED", "CLARIFIED", "DENIED", "FAILED") else "FAILED",
                             stage_timings=result.timings, completed_at=runtime.clock())
            result.findings = [_public_finding(f) for f in repo.list_findings(tenant, investigation_id, turn_id=result.turn_id)]
        except Exception:  # noqa: BLE001
            logger.exception("could not finalise turn timings")
    return result


def _public_finding(f: dict[str, Any]) -> dict[str, Any]:
    return {k: (str(v) if isinstance(v, UUID) else v) for k, v in f.items() if k in ("id", "source", "action_key", "status", "figure_refs", "report_ref", "gap_reason", "agent_run_id", "created_at")}


def _finish(
    ctx: AuthContext, runtime: CeoRuntime, turn: CeoTurn, clock: StageClock, log: EventLog, *, status: str, route: str, route_key: str | None, answer: str,
    kind: str, composition: Composition | None, anchor_status: str, error_reason: str | None = None, clarify_for: str | None = None,
    classifier_flags: Sequence[str] = (), notes: Sequence[str] = (),
) -> TurnResult:
    assert ctx.tenant_id is not None
    tenant = ctx.tenant_id
    assert turn.investigation_id is not None
    msg = repo.append_message(tenant, turn.investigation_id, role="CEO", kind=kind, content=answer, agent_run_id=turn.anchor_run_id, turn_id=turn.turn_id, now=runtime.clock())
    safety = dict(composition.safety) if composition else {}
    if classifier_flags:
        safety["classifierFlags"] = sorted(classifier_flags)
    if turn.turn_id is not None:
        repo.update_turn(
            tenant, turn.turn_id, status=status, ceo_message_id=msg, composition_mode=composition.mode if composition else None,
            safety_result=safety or None, stage_timings=clock.to_json(), completed_at=runtime.clock(),
        )
    turn.close(status=anchor_status, error_reason=error_reason, now=runtime.clock())
    if status == "DELIVERED" and turn.turn_id is not None:
        meter_ceo_turn(tenant, member_id=ctx.app_user_id, turn_id=turn.turn_id, agent_run_id=turn.anchor_run_id)  # best-effort (D4)
    log.emit("ANSWER_READY", status=status, mode=composition.mode if composition else None)
    return TurnResult(status, route, answer, turn_id=turn.turn_id, route_key=route_key, message_id=msg, composition_mode=composition.mode if composition else None,
                      clarify_for=clarify_for, notes=list(notes))


def _run_admitted(
    ctx: AuthContext, runtime: CeoRuntime, inv: dict[str, Any], user_msg: UUID, text: str, turn: CeoTurn, clock: StageClock, log: EventLog,
    period: tuple[date, date] | None = None,
) -> TurnResult:
    tenant = ctx.tenant_id
    assert tenant is not None
    inv_id: UUID = inv["id"]
    now = runtime.clock()
    with clock.span("capabilities"):  # attached ∩ permitted ∩ entitled: the entitlement lookups are the cost here (a caching candidate, §6.26 L7)
        attached = repo.attached_agents(tenant, inv_id)
        caps = compute_capabilities(ctx, runtime.registry, attached, now=now)
    with clock.span("context"):
        tctx, composer_ctx = _turn_context(tenant, inv, user_msg)
    cat = classifier.build_catalog(caps.allowed_actions, caps.allowed_playbooks, caps.allowed_state)
    preset: dict[str, str] = {}
    if period is not None:
        preset["period"] = f"{period[0].isoformat()} to {period[1].isoformat()}"
        tctx = classifier.TurnContext(
            tctx.summary, tctx.recent, tctx.findings,
            period_note=f"The seller already chose the period {preset['period']} with the date picker; it is supplied, do not ask for it.",
        )

    # ---- one classification pass
    with clock.span("classification"):
        try:
            outcome = classifier.classify(runtime.classifier, cat, text, tctx, preset_slots=preset)
            decision = outcome.decision
            clock.note("classificationModelMs", outcome.completion.wall_ms)
            if outcome.completion.ttft_ms is not None:
                clock.note("classificationTtftMs", outcome.completion.ttft_ms)
        except Exception:  # noqa: BLE001 — a model failure is a safe CLARIFY, never a guess
            logger.exception("classifier failed")
            decision = classifier.Decision(False, None, None, "CLARIFY", None, {}, None, "UNCLEAR_REQUEST", frozenset({"MODEL_ERROR"}))
    log.emit("CLASSIFIED", route=decision.route, routeKey=decision.key)

    # ---- deterministic plan validation (slots, periods, closed catalog already enforced by parse_decision)
    route, key, notes = decision.route, decision.key, []
    clarify_slot: str | None = decision.clarify_for
    resolved: ResolvedSlots | None = None
    required: tuple[str, ...] = ()
    if route == "ACTION" and key in ACTIONS:
        required = ACTIONS[key].required_slots
    elif route == "PLAYBOOK" and key in PLAYBOOKS:
        required = PLAYBOOKS[key].required_slots
    if route in ("ACTION", "PLAYBOOK"):
        r = resolve_slots(decision.slots, required, tenant_id=tenant, today=now.date())
        if isinstance(r, Clarification):
            route, key, clarify_slot = "CLARIFY", None, r.slot
        else:
            resolved = r
            notes = list(r.echoes())
    turn.turn_id = repo.create_turn(
        tenant, inv_id, user_message_id=user_msg, agent_run_id=turn.anchor_run_id, route=route, route_key=key, slots=dict(decision.slots),
        classifier_result={**decision.to_json(), "effectiveRoute": route, "effectiveKey": key, "model": runtime.classifier.name}, status="PLAN_VALIDATED", now=now,
    )
    log.emit("PLAN_VALIDATED", route=route, routeKey=key)
    flags = tuple(decision.flags)

    if route == "CLARIFY":
        return _finish(ctx, runtime, turn, clock, log, status="CLARIFIED", route=route, route_key=None, answer=_clarification_text(clarify_slot or "UNCLEAR_REQUEST"),
                       kind="CLARIFICATION", composition=None, anchor_status="COMPLETE", clarify_for=clarify_slot, classifier_flags=flags)
    if route == "OUT_OF_SCOPE":
        return _finish(ctx, runtime, turn, clock, log, status="DELIVERED", route=route, route_key=None, answer=OUT_OF_SCOPE_TEXT, kind="ANSWER", composition=None,
                       anchor_status="COMPLETE", classifier_flags=flags)

    collector = EvidenceCollector(tenant)
    disclaimers: list[tuple[str, str]] = []
    attach: list[str] = []
    template_only_answer = False
    refused_required = False
    heading: str | None = None

    if route == "BUSINESS_STATE":
        assert key is not None
        with clock.span("state_read"):
            entry = _read_state(ctx, turn, key, attached, runtime, log)
        collector.add_entry(entry)
        template_only_answer = True  # a pure read is rendered from the template: no model call (§6.26 L3)
        heading = "Here is what your saved, verified results show."
    elif route == "ADVISORY":
        disclaimers.append(("GENERAL_GUIDANCE", GENERAL_GUIDANCE_TEXT))
        _explain_needed_agent(decision.needs_agent, caps, collector, attach)
        if "BS_SELLER_CONTEXT" in caps.allowed_state:
            collector.add_entry(business_state.read_entry(ctx, "BS_SELLER_CONTEXT", attached=attached, now=now))  # K2: what the seller told us
    elif route == "SYNTHESIZE":
        findings = repo.list_findings(tenant, inv_id)
        if not findings:
            return _finish(ctx, runtime, turn, clock, log, status="DELIVERED", route=route, route_key=None, answer="There are no findings in this investigation to summarise yet.",
                           kind="ANSWER", composition=None, anchor_status="COMPLETE", classifier_flags=flags)
        for f in findings:
            collector.add_finding_row(f)
        for agent, is_attached in repo.agent_states(tenant, inv_id).items():
            if not is_attached and any(f["source"] == agent for f in findings):
                collector.add_fact(f"{agent} findings", f"{agent} is detached from this investigation; its earlier verified findings remain here as historical evidence.", "SOURCE_DERIVED")
    elif route in ("ACTION", "PLAYBOOK"):
        assert resolved is not None and key is not None
        leg_keys, required_keys, reads = _plan_legs(route, key)
        if leg_keys and (runtime.leg_timeout_seconds is None or runtime.max_legs is None):
            return _finish(ctx, runtime, turn, clock, log, status="FAILED", route=route, route_key=key, answer=CONFIG_TEXT, kind="ANSWER", composition=None,
                           anchor_status="FAILED", error_reason="CONFIG_MISSING", classifier_flags=flags)
        if runtime.max_legs is not None and len(leg_keys) > runtime.max_legs:
            return _finish(ctx, runtime, turn, clock, log, status="FAILED", route=route, route_key=key, answer=CONFIG_TEXT, kind="ANSWER", composition=None,
                           anchor_status="FAILED", error_reason="CONFIG_MISSING: max legs", classifier_flags=flags)
        legs, entries, refused_required = _execute(ctx, runtime, turn, resolved, leg_keys, required_keys, reads, attached, now, clock, log)
        for leg in legs:
            collector.add_leg(leg)
        for entry in entries:
            collector.add_entry(entry)
        for k in leg_keys:
            if not any(l.action_key == k for l in legs):  # a leg that missed its deadline: named, never silently absent (E36, L9)
                collector.add_gap(f"{_label(k)} is still running; its result will appear in this investigation's findings when it finishes.")
                if k in required_keys:
                    refused_required = True
        if route == "PLAYBOOK" and not leg_keys:
            heading = None
    else:  # defensive: an unknown route is a safe clarification
        return _finish(ctx, runtime, turn, clock, log, status="CLARIFIED", route="CLARIFY", route_key=None, answer=_clarification_text("UNCLEAR_REQUEST"), kind="CLARIFICATION",
                       composition=None, anchor_status="COMPLETE", clarify_for="UNCLEAR_REQUEST", classifier_flags=flags)

    table = collector.table(disclaimers=disclaimers, attach=attach)
    if refused_required:
        # §6.12 rule 3 / E23: a required leg is missing, so no model synthesis is attempted — the seller gets what IS verified plus the named gaps.
        comp = template_only(table, heading="I could not complete this investigation. Here is what is available:")
        status = "DENIED" if all(l.status in (LegStatus.DENIED, LegStatus.NOT_ENTITLED) for l in turn.legs) and turn.legs else "FAILED"
        return _finish(ctx, runtime, turn, clock, log, status=status, route=route, route_key=key, answer=comp.text, kind="ANSWER", composition=comp,
                       anchor_status=turn.derive_status() if turn.legs else "FAILED", error_reason="a required leg did not complete", classifier_flags=flags, notes=notes)
    if template_only_answer:
        comp = template_only(table, heading=heading)
    else:
        log.emit("SYNTHESIS_STARTED")
        with clock.span("synthesis"):
            comp = compose(runtime.composer, text, route, table, summary=composer_ctx)
        if comp.completion is not None:
            clock.note("synthesisModelMs", comp.completion.wall_ms)  # the model-only part of the synthesis span (the rest is the gate and rendering)
    answer = comp.text + ("\n\n" + "\n".join(notes) if notes else "")
    return _finish(ctx, runtime, turn, clock, log, status="DELIVERED", route=route, route_key=key, answer=answer, kind="ANSWER", composition=comp,
                   anchor_status=turn.derive_status(), classifier_flags=flags, notes=notes)


# ------------------------------------------------------------------------------------------------ pieces
def _label(action_key: str) -> str:
    from backend.ceo.evidence import LEG_LABELS

    return LEG_LABELS.get(action_key, action_key)


def _plan_legs(route: str, key: str) -> tuple[list[str], set[str], tuple[str, ...]]:
    if route == "ACTION":
        return [key], {key}, ()
    pb = PLAYBOOKS[key]
    return [leg.key for leg in pb.legs], {leg.key for leg in pb.legs if leg.required}, pb.state_reads


def _explain_needed_agent(needs: str | None, caps: Capabilities, collector: EvidenceCollector, attach: list[str]) -> None:
    """Spec §6.22 rule 4: when the question needs an agent that is not available, say why — never silently attach, never claim its data."""
    if needs is None:
        return
    status = caps.agent_status.get(needs, PRESENT)
    if status == NOT_ATTACHED:
        attach.append(needs)
    elif status == NOT_PERMITTED:
        collector.add_gap(f"You do not have access to {needs}, which this question needs.")
    elif status == NOT_ENTITLED:
        collector.add_gap(f"{needs} is not available on your current plan, which this question needs.")
        if needs == "CFO":
            collector.offers.append(("cfo.preview", "See the free CFO preview"))
    else:
        collector.add_gap(f"{needs} cannot answer this from chat yet; please use its own page.")


def _read_state(ctx: AuthContext, turn: CeoTurn, key: str, attached: frozenset[str], runtime: CeoRuntime, log: EventLog) -> BusinessStateEntry:
    """One Business State read (persisted results only; nothing is computed) and its finding."""
    entry = business_state.read_entry(ctx, key, attached=attached, now=runtime.clock())
    assert ctx.tenant_id is not None and turn.investigation_id is not None and turn.turn_id is not None
    repo.insert_finding(
        ctx.tenant_id, turn.investigation_id, turn_id=turn.turn_id, source="BUSINESS_STATE", action_key=key, status=finding_status_for_entry(entry.status),
        figure_refs=[f.ref.to_json() for f in entry.figures], gap_reason="; ".join(g.message for g in entry.gaps) or None, now=runtime.clock(),
    )
    log.emit("STATE_READ", entry=key, status=entry.status.value)
    return entry


def _preflight(ctx: AuthContext, runtime: CeoRuntime, key: str, attached: frozenset[str], now: datetime) -> bool:
    """Would this leg be admitted? Mirrors dispatch's order (permission -> attachment -> entitlement) WITHOUT writing anything; dispatch itself
    re-checks and remains the authority. Used so a refused required leg stops the fan-out before any sibling does work (E23)."""
    spec = runtime.registry.get(key)
    assert ctx.role is not None and ctx.tenant_id is not None
    if not all(has_permission(role=ctx.role, permissions=ctx.permissions, key=k) for k in runtime.registry.required_permissions(spec)):
        return False
    if spec.agent is not None and spec.agent.value not in attached:
        return False
    if spec.entitlement is not None and not spec.entitlement(ctx.tenant_id, now).passed:
        return False
    return True


def _execute(
    ctx: AuthContext, runtime: CeoRuntime, turn: CeoTurn, resolved: ResolvedSlots, leg_keys: list[str], required_keys: set[str], reads: tuple[str, ...],
    attached: frozenset[str], now: datetime, clock: StageClock, log: EventLog,
) -> tuple[list[LegResult], list[BusinessStateEntry], bool]:
    """Runs the fixed legs and state reads. Returns (finished legs, state entries, a-required-leg-was-refused)."""
    admitted = [k for k in leg_keys if _preflight(ctx, runtime, k, attached, now)]
    refused = [k for k in leg_keys if k not in admitted]
    refused_required = any(k in required_keys for k in refused)
    legs: list[LegResult] = []
    with clock.span("dispatch"):
        for k in refused:  # logged with the same fidelity as a completed leg (AC11): dispatch refuses and writes the DENIED row + finding
            legs.append(dispatch(turn, k, _slots_for(k, resolved), registry=runtime.registry, attached=attached, now=now))
        if refused_required:
            return legs, [], True
        tasks: list[tuple[str, str, Callable[[], Any]]] = [("leg", k, lambda k=k: _run_leg(turn, runtime, resolved, k, attached, clock, log)) for k in admitted]  # type: ignore[misc]
        tasks += [("read", e, lambda e=e: _read_state(ctx, turn, e, attached, runtime, log)) for e in reads]  # type: ignore[misc]
        results: list[Any] = []
        if len(tasks) == 1:
            kind, name, fn = tasks[0]
            try:
                results = [fn()]
            except Exception:  # noqa: BLE001
                logger.exception("CEO %s %s raised", kind, name)
                results = [LegResult(name, LegStatus.FAILED, reason="the action failed") if kind == "leg" else None]
        elif tasks:
            pool = ThreadPoolExecutor(max_workers=len(tasks), thread_name_prefix="ceo-leg")
            futures = [pool.submit(contextvars.copy_context().run, fn) for _, _, fn in tasks]  # copy: each thread inherits the parent-run scope
            done, _not_done = wait(futures, timeout=runtime.leg_timeout_seconds)
            pool.shutdown(wait=False)  # a late leg finishes on its own and writes its own finding; the answer does not wait (L9)
            for (kind, name, _), fut in zip(tasks, futures):
                if fut in done and fut.exception() is None:
                    results.append(fut.result())
                elif fut in done:  # raised: a failed leg is named, not "still running"
                    logger.error("CEO %s %s raised", kind, name, exc_info=fut.exception())
                    results.append(LegResult(name, LegStatus.FAILED, reason="the action failed") if kind == "leg" else None)
        for r in results:
            if isinstance(r, LegResult):
                legs.append(r)
        entries = [r for r in results if isinstance(r, BusinessStateEntry)]
    return legs, entries, refused_required


def _slots_for(key: str, resolved: ResolvedSlots) -> dict[str, object]:
    return ACTIONS[key].build_slots(resolved)


def _run_leg(turn: CeoTurn, runtime: CeoRuntime, resolved: ResolvedSlots, key: str, attached: frozenset[str], clock: StageClock, log: EventLog) -> LegResult:
    clock.leg_started(key)
    log.emit("LEG_STARTED", action=key)
    try:
        leg = dispatch(turn, key, _slots_for(key, resolved), registry=runtime.registry, attached=attached, now=runtime.clock())
    except Exception:
        clock.leg_finished(key, "FAILED")
        log.emit("LEG_FINISHED", action=key, status="FAILED")
        raise
    clock.leg_finished(key, leg.status.value)
    log.emit("LEG_FINISHED", action=key, status=leg.status.value, findingId=str(leg.finding_id) if leg.finding_id else None,
             agentRunId=str(leg.agent_run_id) if leg.agent_run_id else None, figureRefs=len(leg.figure_refs))
    return leg
