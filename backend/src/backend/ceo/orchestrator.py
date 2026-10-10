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
import dataclasses
import logging
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any
from uuid import UUID

from backend import config
from backend.auth.context import AuthContext
from backend.auth.permissions import AGENT_CEO, INVESTIGATION_CREATE, INVESTIGATION_VIEW, has_permission
from backend.ceo import business_state, classifier, clarification, data_requests, findings, input_session, intent_router, memory, needs, references
from backend.ceo.capabilities import NOT_ATTACHED, NOT_ENTITLED, NOT_PERMITTED, PRESENT, Capabilities, compute_capabilities
from backend.ceo.composer import WEB_ARTEFACT_TITLE, Composition, compose, template_only
from backend.ceo.contract import AgentCode, BusinessStateEntry, Denial, LegResult, LegStatus, TurnDenied
from backend.ceo.dispatch import CeoTurn, dispatch, open_turn
from backend.ceo.evidence import EvidenceCollector, finding_status_for_entry
from backend.ceo.presentation import present_entry, present_leg, safe
from backend.ceo.plans import ACTIONS, GST_KEY, SLOT_VOCAB, GST_ROUTE_KEYS, PLAYBOOK_LEG_SLOTS, PLAYBOOKS, SLOT_QUESTIONS, Clarification, ResolvedSlots, gst_route_key, resolve_playbook_run, resolve_slots
from backend.ceo.playbook_inputs import InvalidInputs
from backend.ceo.runtime import CeoRuntime, EventLog, EventSink, StageClock, TurnEvent
from backend.ceo.turn_lock import investigation_turn_lock
from backend.entitlement import meter_ceo_turn
from backend.repositories import investigation_repo as repo
from backend.repositories import ceo_need_repo
from backend.services import ceo_briefs, ceo_inputs

logger = logging.getLogger(__name__)

_ACKS: contextvars.ContextVar[list[str]] = contextvars.ContextVar("ceo_memory_acks", default=[])
MAX_MESSAGE_CHARS = 4000  # a request-size bound, not a business threshold
GENERAL_GUIDANCE_TEXT = "This is general advice, not derived from your data."


@dataclass(frozen=True, slots=True)
class UiAction:
    """A quick action the seller chose with a deterministic control (spec section 6.26 L2). It skips the classifier but nothing else: the same closed
    catalog (attached, permitted and entitled), slot validation, per-leg pre-flight, choke point, evidence, gate and persistence apply."""

    route: str  # BUSINESS_STATE | ACTION | PLAYBOOK | SYNTHESIZE
    key: str | None
    slots: Mapping[str, str] = field(default_factory=dict)
    refs: Mapping[str, str] = field(default_factory=dict)  # validated references chosen through a control (spec 6.12): ids, checked against the caller's tenant
    inputs: Mapping[str, Any] | None = None  # a decision playbook's structured form inputs (spec 6.33): validated by code, never produced by a model
    save: Mapping[str, Any] | None = None  # what the seller just confirmed for a data request (spec 6.37): saved FIRST, then this same request runs again
    save_sku: str | None = None
    save_ref: str | None = None
    addons: tuple[str, ...] = ()  # add-on lookups the request also asks for (spec agent-needs 5.3); filtered against the needs catalog before anything runs


@dataclass(frozen=True, slots=True)
class ClarificationReply:
    """The seller answering a decision card: the card's message id and the chosen option key, or None for the free-text "Other" (the message text)."""

    card_id: UUID
    option: str | None


def clarification_module_resume(card: Mapping[str, Any], option: str | None, text: str) -> tuple[str, str | None, dict[str, str], dict[str, str]]:
    return clarification.resume_action(card, option_key=option, other_text=text)


class InvalidAttachments(Exception):
    """An attachment id that is not an attachment of THIS investigation in this tenant (foreign, unknown or from another conversation)."""


class InvalidClarification(Exception):
    """The reply names a card that does not exist in this investigation, is not a decision card, or an option it does not have."""


# the reference kinds a UI action may carry today (each is validated against the caller's own tenant before use)
REF_VOCAB: tuple[str, ...] = ("competitor_url_id",)


UI_ACTION_UNAVAILABLE_TEXT = (
    "That quick action is not available for this investigation. Its agent may be detached, not on your plan, or you may not have access to it."
)


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
    choices: dict[str, Any] | None = None  # the decision card of a clarification (spec 6.32); the card's id is `message_id`


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
GST_WALL_TEXT = (
    "You do not have access to the GST lookup. It needs the GST lookup permission on your account, and I will not answer a GST question from general "
    "knowledge. Please ask your account owner, or check with your accountant."
)
DENIED_TEXT = {
    Denial.PERMISSION: "You do not have access to the CEO for this investigation.",
    Denial.ENTITLEMENT: "Your CEO conversation allowance for this period has been used. It resets with your plan period.",
}
FAILED_TEXT = "Something went wrong on our side and nothing was changed. Please try again."
CONFIG_TEXT = "The CEO's investigation limits have not been configured by the operator yet, so this investigation cannot run."
FORM_TEXT = "This one needs exact prices and costs, which are entered in a form rather than typed into chat. Open the form below and I will run it on what you enter."
BAD_FORM_TEXT = "That form could not be used, so nothing was run: "


def _resume_plain_question(tenant: UUID, investigation_id: UUID, text: str) -> UiAction | None:
    """When the CEO's last message is a plain question for one missing slot (a product, a marketplace, an amount, a period...), a SHORT reply is that slot's value and the
    task that asked resumes with it. A long message or a question is a new request and is routed normally. The slot value is still parsed by code like any other."""
    if len(text) > 80 or len(text.split()) > 8 or text.rstrip().endswith("?"):
        return None
    msgs = repo.list_messages(tenant, investigation_id)
    last = msgs[-1] if msgs else None
    if last is None or last["role"] != "CEO" or last["kind"] != "CLARIFICATION" or last.get("choices") or not last.get("turn_id"):
        return None
    turn = repo.get_turn(tenant, last["turn_id"]) or {}
    result = turn.get("classifier_result") or {}
    pending, slot = result.get("pending"), result.get("pendingSlot")
    if not isinstance(pending, dict) or slot not in SLOT_VOCAB or pending.get("route") not in ("ACTION", "PLAYBOOK") or not pending.get("key"):
        return None
    return UiAction(str(pending["route"]), str(pending["key"]), {**(pending.get("slots") or {}), str(slot): text.strip()}, pending.get("refs") or {})


def _with_request_key(done: Any, anchor: str) -> dict[str, Any]:
    """The collected inputs plus an idempotency key derived from the message that finished them: answering the same card twice reuses the finished result."""
    out = dict(done.inputs)
    if done.playbook in input_session.CMO_SESSIONS:
        out["request_key"] = f"ceo-{anchor}"
    if done.playbook in ("pi.discover", "NEW_PRODUCT_DECISION"):
        out["ceo_ref"] = f"ceo-{anchor}"
    return out


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
    ideas = references.latest_ideas(repo.list_findings(tenant, inv["id"]))  # what the seller was shown earlier ("the list above"), quoted as data so the CEO does not forget it
    ideas_line = ("Product ideas shown earlier in this conversation (from public web sources, not verified): " + "; ".join(f"#{n} {name}" for n, name in enumerate(ideas[:10], start=1))) if ideas else None
    composer_ctx = " | ".join(x for x in (summary, memory.context_line(tenant), ideas_line, ("Earlier the seller asked: " + "; ".join(earlier_questions)) if earlier_questions else None) if x) or None
    return classifier.TurnContext(summary, recent, findings), composer_ctx


# ------------------------------------------------------------------------------------------------ the turn
def run_turn(
    ctx: AuthContext, runtime: CeoRuntime, investigation_id: UUID, message: str, *, sink: EventSink | None = None,
    period: tuple[date, date] | None = None, ui_action: UiAction | None = None, clarification: ClarificationReply | None = None, attachment_ids: Sequence[UUID] = (),
) -> TurnResult:
    """One turn, serialized per investigation (spec E24): a second turn waits for the running one (bounded by `CEO_TURN_LOCK_WAIT_SECONDS`)
    or is refused with `TurnInProgress`. Everything below, including any summary regeneration, runs under that lock."""
    assert ctx.tenant_id is not None
    if repo.get_investigation(ctx.tenant_id, investigation_id) is None:  # RLS: another tenant's id is a plain not-found, and takes no lock
        raise repo.InvestigationNotFound(str(investigation_id))
    with investigation_turn_lock(investigation_id, config.ceo_turn_lock_wait_seconds()):
        return _run_turn_locked(ctx, runtime, investigation_id, message, sink=sink, period=period, ui_action=ui_action, clarification=clarification, attachment_ids=attachment_ids)


def _run_turn_locked(
    ctx: AuthContext, runtime: CeoRuntime, investigation_id: UUID, message: str, *, sink: EventSink | None = None,
    period: tuple[date, date] | None = None, ui_action: UiAction | None = None, clarification: ClarificationReply | None = None, attachment_ids: Sequence[UUID] = (),
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
    attachments = repo.get_attachments(tenant, investigation_id, list(dict.fromkeys(attachment_ids)))
    if len(attachments) != len(set(attachment_ids)):  # a foreign, unknown or other-conversation id: refused before anything is written
        raise InvalidAttachments("unknown attachment")

    reply_meta: dict[str, Any] | None = None
    input_outcome: Any = None
    if clarification is None and ui_action is None and has_permission(role=ctx.role, permissions=ctx.permissions, key=INVESTIGATION_VIEW):
        ui_action = _resume_plain_question(tenant, investigation_id, text)  # a short answer to the CEO's plain question resumes that task
    if clarification is None and ui_action is None and has_permission(role=ctx.role, permissions=ctx.permissions, key=INVESTIGATION_VIEW):
        # Guided input (spec 6.34): when the CEO's last message is an open input question, whatever the seller types is the ANSWER to it, parsed by code.
        tail = repo.list_messages(tenant, investigation_id)
        last = tail[-1] if tail else None
        if last is not None and last["role"] == "CEO" and last["kind"] == "CLARIFICATION" and (last.get("choices") or {}).get("kind") == "INPUT":
            clarification = ClarificationReply(last["id"], None)
    if clarification is not None and ui_action is None and has_permission(role=ctx.role, permissions=ctx.permissions, key=INVESTIGATION_VIEW):
        # Answering a decision card resumes ITS pending intent with the chosen option (or the typed text) and no model call. Resolved before anything is
        # written, and only for a member who may view the investigation (anyone else is refused by admission below, learning nothing about cards).
        card_msg = repo.get_message(tenant, investigation_id, clarification.card_id)
        if card_msg is None or card_msg["kind"] != "CLARIFICATION" or not card_msg.get("choices"):
            raise InvalidClarification("no such decision card")
        if card_msg["choices"].get("kind") == "INPUT":
            try:
                input_outcome = input_session.advance(card_msg["choices"], option_key=clarification.option, text=text, ctx=input_session.Ctx(tenant, runtime.clock().date(), runtime.max_candidate_prices))
            except ValueError as exc:
                raise InvalidClarification(str(exc)) from None
            if isinstance(input_outcome, input_session.Done) and input_outcome.playbook.startswith("dr.") and input_outcome.resume:
                rs = input_outcome.resume  # spec 6.37: save what the seller confirmed, then ask the very same question again
                ui_action = UiAction(
                    str(rs["route"]), rs.get("key"), dict(rs.get("slots") or {}), dict(rs.get("refs") or {}), rs.get("inputs"),
                    save={**input_outcome.inputs["save"], "request_id": rs.get("request_id")} if input_outcome.inputs.get("save") else None,
                    save_sku=str(input_outcome.inputs.get("sku", "")), save_ref=f"ceo-{clarification.card_id}",
                )
                input_outcome = None
            elif isinstance(input_outcome, input_session.Done):  # every field collected: the same validated inputs as the form, and the playbook / action runs
                ui_action = UiAction(input_session.route_of(input_outcome.playbook), input_outcome.playbook, {}, {}, _with_request_key(input_outcome, str(clarification.card_id)),
                                     addons=input_outcome.addons)
                input_outcome = None
        else:
            try:
                r_route, r_key, r_slots, r_refs = clarification_module_resume(card_msg["choices"], clarification.option, text)
            except ValueError as exc:
                raise InvalidClarification(str(exc)) from None
            ui_action = UiAction(r_route, r_key, r_slots, r_refs)
        reply_meta = {"clarificationId": str(clarification.card_id), "clarificationOption": clarification.option or "other"}

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
    shown = text + (("\n\nAttached: " + ", ".join(f"{a['filename']}" for a in attachments)) if attachments else "")  # written by code; the classifier still sees only the seller's words
    user_msg = repo.append_message(tenant, investigation_id, role="USER", content=shown, created_by=ctx.app_user_id, now=runtime.clock())
    turn.presenter = lambda leg: present_leg(tenant, leg)  # every finding is written with its verified display snapshot (R7 as amended)
    log.emit("TURN_ADMITTED")

    result = TurnResult("FAILED", "CLARIFY", FAILED_TEXT)
    try:
        result = _run_admitted(ctx, runtime, inv, user_msg, text, turn, clock, log, period, ui_action, reply_meta, input_outcome, attachments)
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
    return {k: (str(v) if isinstance(v, UUID) else v) for k, v in f.items() if k in ("id", "source", "action_key", "status", "figure_refs", "report_ref", "gap_reason", "agent_run_id", "presentation", "created_at")}


def _finish(
    ctx: AuthContext, runtime: CeoRuntime, turn: CeoTurn, clock: StageClock, log: EventLog, *, status: str, route: str, route_key: str | None, answer: str,
    kind: str, composition: Composition | None, anchor_status: str, error_reason: str | None = None, clarify_for: str | None = None,
    classifier_flags: Sequence[str] = (), notes: Sequence[str] = (), choices: Mapping[str, Any] | None = None,
) -> TurnResult:
    assert ctx.tenant_id is not None
    tenant = ctx.tenant_id
    assert turn.investigation_id is not None
    pending_acks = _ACKS.get()
    if pending_acks and kind in ("ANSWER", "CLARIFICATION"):  # what was just remembered is said in the same answer, written by code (spec agent-memory 4.3)
        answer = answer + "\n\n" + "\n".join(pending_acks)
        _ACKS.set([])
    msg = repo.append_message(tenant, turn.investigation_id, role="CEO", kind=kind, content=answer, agent_run_id=turn.anchor_run_id, turn_id=turn.turn_id,
                              choices=choices, now=runtime.clock())
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
                      clarify_for=clarify_for, notes=list(notes), choices=dict(choices) if choices else None)


def _run_admitted(
    ctx: AuthContext, runtime: CeoRuntime, inv: dict[str, Any], user_msg: UUID, text: str, turn: CeoTurn, clock: StageClock, log: EventLog,
    period: tuple[date, date] | None = None, ui_action: UiAction | None = None, reply_meta: dict[str, Any] | None = None, input_outcome: Any = None,
    attachments: Sequence[Mapping[str, Any]] = (),
) -> TurnResult:
    tenant = ctx.tenant_id
    assert tenant is not None
    inv_id: UUID = inv["id"]
    now = runtime.clock()
    _ACKS.set([])  # nothing remembered yet this turn (the context variable must not carry over from an earlier turn)
    if input_outcome is not None:  # the next question of a guided input, or its end: no model, no specialist
        return _answer_input(ctx, runtime, inv_id, user_msg, turn, clock, log, input_outcome, reply_meta, now)
    pre_notes: list[str] = []
    if ui_action is not None and ui_action.save:  # the seller confirmed a missing figure: it is saved as their own, and only then does the question run again
        try:
            pre_notes = ceo_inputs.save_new_product_inputs(tenant, created_by=ctx.app_user_id, role=ctx.role, permissions=ctx.permissions, sku=str(ui_action.save_sku), save=ui_action.save, ref=str(ui_action.save_ref))
        except ceo_inputs.CannotSave as exc:
            return _finish(ctx, runtime, turn, clock, log, status="FAILED", route="PLAYBOOK", route_key=None, answer=BAD_FORM_TEXT + str(exc) + ".", kind="ANSWER", composition=None,
                           anchor_status="FAILED", error_reason="could not save")
        except Exception:  # noqa: BLE001
            logger.exception("could not save a confirmed figure")
            return _finish(ctx, runtime, turn, clock, log, status="FAILED", route="PLAYBOOK", route_key=None, answer=BAD_FORM_TEXT + "I could not save that figure, so I did not run it.", kind="ANSWER",
                           composition=None, anchor_status="FAILED", error_reason="could not save")
    with clock.span("capabilities"):  # attached ∩ permitted ∩ entitled: the entitlement lookups are the cost here (a caching candidate, §6.26 L7)
        attached = repo.attached_agents(tenant, inv_id)
        caps = compute_capabilities(ctx, runtime.registry, attached, now=now)
    with clock.span("context"):
        tctx, composer_ctx = _turn_context(tenant, inv, user_msg)
    cat = classifier.build_catalog(caps.allowed_actions, caps.allowed_playbooks, caps.allowed_state)
    _ACKS.set([])
    if ui_action is None:
        try:  # remembering is best-effort: a failure here never costs the seller their answer
            _ACKS.set(memory.remember_from_message(tenant, ctx.app_user_id, user_msg, text))
            direct = memory.answer_profile_question(tenant, text)
        except Exception:  # noqa: BLE001
            logger.exception("memory capture failed")
            direct = None
        if direct is not None:  # "what is my business name?": answered by code from what the seller told us, with no model call
            return _answer_direct(ctx, runtime, inv_id, user_msg, turn, clock, log, direct, now)
        if _ACKS.get() and not text.rstrip().endswith("?") and intent_router.route(text, cat) is None:  # only a statement about their business: acknowledged, nothing to answer
            return _answer_direct(ctx, runtime, inv_id, user_msg, turn, clock, log, "Noted.", now)
    ref_notes: list[str] = []
    routed_text = text  # what the router and classifier see: earlier results referred to by position ("#3") are replaced by their names (spec 6.35)
    if ui_action is None:
        try:
            routed_text, ref_notes = references.expand(repo.list_findings(tenant, inv_id), text)
            _ACKS.set([*_ACKS.get(), *ref_notes])
        except Exception:  # noqa: BLE001
            logger.exception("reference expansion failed")
    preset: dict[str, str] = {}
    if period is not None:
        preset["period"] = f"{period[0].isoformat()} to {period[1].isoformat()}"
        tctx = classifier.TurnContext(
            tctx.summary, tctx.recent, tctx.findings,
            period_note=f"The seller already chose the period {preset['period']} with the date picker; it is supplied, do not ask for it.",
        )

    # ---- one classification pass, or none at all for a seller-chosen quick action (spec section 6.26 L2)
    if ui_action is not None:
        with clock.span("route_resolution"):
            decision = classifier.decision_from_ui_action(ui_action.route, ui_action.key, ui_action.slots, cat, preset)
        classifier_model = "none (UI action)"
        log.emit("CLASSIFIED", route=decision.route, routeKey=decision.key, source="UI_ACTION")
    elif (ruled := intent_router.route(routed_text, cat)) is not None:  # an unmistakable request: the explicit rule decides, instantly (spec 6.35)
        decision = ruled
        classifier_model = "rules"
        log.emit("CLASSIFIED", route=decision.route, routeKey=decision.key, source="RULES")
    else:
        classifier_model = runtime.classifier.name
        with clock.span("classification"):
            try:
                outcome = classifier.classify(runtime.classifier, cat, routed_text, tctx, preset_slots=preset)
                decision = outcome.decision
                clock.note("classificationModelMs", outcome.completion.wall_ms)
                if outcome.completion.ttft_ms is not None:
                    clock.note("classificationTtftMs", outcome.completion.ttft_ms)
            except Exception:  # noqa: BLE001 - a model failure is a safe CLARIFY, never a guess
                logger.exception("classifier failed")
                decision = classifier.Decision(False, None, None, "CLARIFY", None, {}, None, "UNCLEAR_REQUEST", frozenset({"MODEL_ERROR"}))
        if decision.route == "CLARIFY" and decision.clarify_for == "WHICH_AGENT":  # a general question: the CEO answers it, it does not ask "which area?"
            decision = dataclasses.replace(decision, route="ADVISORY", key=None, clarify_for=None, needs_agent=None)
        log.emit("CLASSIFIED", route=decision.route, routeKey=decision.key)

    # ---- deterministic plan validation (slots, periods, closed catalog already enforced by parse_decision)
    route, key, notes = decision.route, decision.key, []
    clarify_slot: str | None = decision.clarify_for
    clarify_text: str | None = None
    resolved: ResolvedSlots | None = None
    required: tuple[str, ...] = ()
    resolves: tuple[str, ...] = ()
    pending: dict[str, Any] | None = None  # the intent a clarification would resume (route, key, what is already understood)
    candidates: tuple[tuple[UUID, str], ...] = ()
    ui_refs: dict[str, UUID] = {}
    if ui_action is not None:
        for name, raw_id in ui_action.refs.items():
            if name in REF_VOCAB:
                try:
                    ui_refs[name] = UUID(str(raw_id))
                except ValueError:
                    pass  # a malformed reference is simply absent: the slot is then asked for, never guessed
    if route == "ACTION" and key is not None and key in ACTIONS:
        required, resolves = ACTIONS[key].required_slots, ACTIONS[key].resolves
    elif route == "PLAYBOOK" and key is not None and key in PLAYBOOKS:
        required = PLAYBOOKS[key].required_slots
    form_playbook = (route == "PLAYBOOK" and key is not None and key in PLAYBOOKS and PLAYBOOKS[key].needs_form) or (route == "ACTION" and key is not None and key in ACTIONS and ACTIONS[key].session)
    invalid_form: str | None = None
    addons: tuple[str, ...] = tuple(ui_action.addons) if ui_action is not None else tuple(decision.addons)  # spec agent-needs 5.3: filtered by the catalog before they run
    if ref_notes and decision.key == "NEW_PRODUCT_DECISION" and "LANDED_COST_FOR_IDEA" not in addons:
        addons = (*addons, "LANDED_COST_FOR_IDEA")  # the seller named a PI idea: carried through the questions so the link is recorded when the flow runs (spec 5.2, S2)
    ask_sku: str | None = None  # the product the question was about, for a missing-figure follow-up (spec 6.37)
    ask_inputs: dict[str, Any] | None = None
    session_card: dict[str, Any] | None = None
    if form_playbook:
        assert key is not None
        run_inputs: Mapping[str, Any] | None = ui_action.inputs if ui_action is not None else None
        if run_inputs is None and not (key == "COMPETITOR_PRICE_IMPACT" and runtime.max_candidate_prices is None):
            # from typed chat or a chip: the CEO asks for what it needs, one question at a time; every answer is parsed by code (spec 6.34).
            # What the seller already said (classifier slot text) is offered to the same parsers first, so nothing already given is asked again.
            started = input_session.start(key, input_session.Ctx(tenant, now.date(), runtime.max_candidate_prices), prefill=decision.slots)
            if isinstance(started, input_session.Done):
                run_inputs = _with_request_key(started, str(user_msg))
            else:
                route, key = "CLARIFY", None
                if isinstance(started, input_session.Ask):
                    clarify_slot, clarify_text, session_card = started.card["slot"], started.text, started.card
                    if addons:
                        session_card["addons"] = list(addons)
                else:
                    clarify_slot, clarify_text = "INPUT", started.text
        if run_inputs is not None:
            ask_inputs = {k: v for k, v in run_inputs.items() if k not in ("save", "ceo_ref", "request_key")}
            ask_sku = str(run_inputs["sku"]) if run_inputs.get("sku") else None
        if route == "CLARIFY":
            pass
        elif run_inputs is None or (key == "COMPETITOR_PRICE_IMPACT" and runtime.max_candidate_prices is None):
            resolved = ResolvedSlots(tenant_id=tenant, today=now.date())  # refused below with CONFIG_MISSING: the bound has no default (Q32)
        elif route == "ACTION" and key == "cmo.market_trends" and not run_inputs.get("plan_digest"):
            # spec 6.40: the exact outbound searches are shown first (a zero-cost preview) and nothing is sent until the seller confirms them
            pv = _trend_preview(ctx, runtime, turn, tenant, now, attached, clock, log, run_inputs)
            if isinstance(pv, str):
                invalid_form = pv
            else:
                route, key, clarify_slot, clarify_text, session_card = "CLARIFY", None, pv.card["slot"], pv.text, pv.card
        elif route == "ACTION" and key == "pi.discover":
            try:  # the seller confirmed these answers: they become their saved research brief, which Product Intelligence then runs from
                brief = ceo_briefs.create_ready_brief(tenant, created_by=ctx.app_user_id, inputs=run_inputs, ref=str(run_inputs.get("ceo_ref")))
            except (ValueError, KeyError) as exc:
                invalid_form = f"the research brief could not be saved ({exc})"
            else:
                resolved = ResolvedSlots(tenant_id=tenant, today=now.date(), direct={"niche_brief_id": str(brief), "depth": run_inputs["depth"]})
                try:  # PI's own private memory of what the seller just confirmed: offered as a choice next time, never filled in silently
                    src = {"message_id": str(user_msg)}
                    for k, v in (("last_category", str(run_inputs["category_text"])), ("last_budget_paise", str(run_inputs["budget_paise"])), ("last_marketplaces", ", ".join(run_inputs["marketplaces"]))):
                        memory.note(tenant, agent="PI", key=k, value=v, basis="CONFIRMED_DECISION", source_ref=src, created_by=ctx.app_user_id)
                except Exception:  # noqa: BLE001
                    logger.exception("could not save PI memory")
                notes = [f"Researching: {run_inputs['category_text']} on " + ", ".join(str(m).title() for m in run_inputs["marketplaces"]) + "."]
        elif route == "ACTION":
            resolved = ResolvedSlots(tenant_id=tenant, today=now.date(), direct=dict(run_inputs))
            notes = list(resolved.echoes())
            input_session.remember_confirmed(tenant, key, run_inputs, source_ref={"message_id": str(user_msg)}, user_id=ctx.app_user_id)  # CMO's private choice, best-effort (agent-memory C6)
        else:
            run_inputs = dict(run_inputs)
            saved_notes: list[str] = []
            save, ref = run_inputs.pop("save", None), str(run_inputs.pop("ceo_ref", ""))
            if key == "NEW_PRODUCT_DECISION" and save:  # the seller confirmed these on the confirm card: saved as their own CFO inputs, then the engine runs (spec 6.36)
                try:
                    saved_notes = ceo_inputs.save_new_product_inputs(tenant, created_by=ctx.app_user_id, role=ctx.role, permissions=ctx.permissions, sku=str(run_inputs.get("sku")), save=save, ref=ref)
                except ceo_inputs.CannotSave as exc:
                    invalid_form, save = str(exc), None
                except Exception:  # noqa: BLE001
                    logger.exception("could not save new-product inputs")
                    invalid_form, save = "I could not save those figures, so I did not run it", None
            try:
                if invalid_form is not None:
                    raise InvalidInputs([])
                r = resolve_playbook_run(key, run_inputs, tenant_id=tenant, today=now.date(), max_candidate_prices=runtime.max_candidate_prices)
            except InvalidInputs as exc:
                invalid_form = invalid_form or "; ".join(exc.problems)
            else:
                if isinstance(r, Clarification):
                    pending = clarification.pending_intent("PLAYBOOK", key, {}, {})
                    candidates = r.candidates
                    route, key, clarify_slot, clarify_text = "CLARIFY", None, r.slot, r.question
                else:
                    resolved = r
                    notes = [*saved_notes, *r.echoes()]
                    input_session.remember_confirmed(tenant, key, run_inputs, source_ref={"message_id": str(user_msg)}, user_id=ctx.app_user_id)  # CFO/CI private choices, best-effort (agent-memory C6)
    elif route in ("ACTION", "PLAYBOOK"):
        r = resolve_slots(decision.slots, required, tenant_id=tenant, today=now.date(), resolves=resolves, refs=ui_refs)
        if isinstance(r, Clarification):
            pending = clarification.pending_intent(decision.route, decision.key, decision.slots, {k: str(v) for k, v in ui_refs.items()})
            candidates = r.candidates
            route, key, clarify_slot, clarify_text = "CLARIFY", None, r.slot, r.question
        else:
            resolved = r
            notes = list(r.echoes())
    if route == "CLARIFY" and pending is None and "MISSING_SLOT" in decision.flags and decision.raw_route in ("ACTION", "PLAYBOOK") and decision.raw_key:
        pending = clarification.pending_intent(decision.raw_route, decision.raw_key, decision.slots, {k: str(v) for k, v in ui_refs.items()})
    if attachments and route == "CLARIFY" and pending is None and clarify_slot in (None, "UNCLEAR_REQUEST"):
        route, clarify_slot, clarify_text = "ADVISORY", None, None  # the seller showed a file and asked about it: the CEO answers qualitatively from what it read
    turn.turn_id = repo.create_turn(
        tenant, inv_id, user_message_id=user_msg, agent_run_id=turn.anchor_run_id, route=route, route_key=key, slots=dict(decision.slots),
        route_source="UI_ACTION" if ui_action is not None else "CLASSIFIER",
        classifier_result={**decision.to_json(), "effectiveRoute": route, "effectiveKey": key, "model": classifier_model, **(reply_meta or {}),
                           **({"inputs": resolved.run.inputs.model_dump(mode="json")} if resolved is not None and resolved.run is not None else {}),
                           **({"attachments": [str(a["id"]) for a in attachments]} if attachments else {}),
                           # what a plain question is waiting for, so the seller's short answer resumes THIS task instead of starting a new one (spec 6.35)
                           **({"pending": pending, "pendingSlot": clarify_slot} if route == "CLARIFY" and pending is not None and clarify_slot in SLOT_VOCAB else {})},
        status="PLAN_VALIDATED", now=now,
    )
    log.emit("PLAN_VALIDATED", route=route, routeKey=key)
    flags = tuple(decision.flags)

    if "GST_UNAVAILABLE" in flags:  # a GST question this member cannot have looked up: the wall stands, and it is never answered from general knowledge (spec C11, G1)
        return _finish(ctx, runtime, turn, clock, log, status="DENIED", route="ADVISORY", route_key=None, answer=GST_WALL_TEXT, kind="ANSWER", composition=None,
                       anchor_status="DENIED", error_reason="no GST route available", classifier_flags=flags)
    if ui_action is not None and route == "CLARIFY" and "OUT_OF_CATALOG" in flags:
        # The chip named something this member cannot use here (detached / not entitled / no permission): say so plainly; nothing was dispatched.
        return _finish(ctx, runtime, turn, clock, log, status="DENIED", route="CLARIFY", route_key=None, answer=UI_ACTION_UNAVAILABLE_TEXT, kind="ANSWER",
                       composition=None, anchor_status="DENIED", error_reason="ui action not available", classifier_flags=flags)
    if invalid_form is not None:
        return _finish(ctx, runtime, turn, clock, log, status="FAILED", route="PLAYBOOK", route_key=decision.key, answer=BAD_FORM_TEXT + invalid_form + ".", kind="ANSWER",
                       composition=None, anchor_status="FAILED", error_reason="invalid form inputs", classifier_flags=flags)
    if route == "CLARIFY":
        if pending is None and "MISSING_SLOT" in decision.flags and decision.raw_route in ("ACTION", "PLAYBOOK") and decision.raw_key:
            pending = clarification.pending_intent(decision.raw_route, decision.raw_key, decision.slots, {k: str(v) for k, v in ui_refs.items()})
        card = session_card
        if card is None and pending is not None and clarify_slot in clarification.CARD_SLOTS:
            card = clarification.build(tenant, slot=clarify_slot, pending=pending, candidates=candidates, now=now)  # real candidates only; None = a plain question
        return _finish(ctx, runtime, turn, clock, log, status="CLARIFIED", route=route, route_key=None, answer=clarify_text or _clarification_text(clarify_slot or "UNCLEAR_REQUEST"),
                       kind="CLARIFICATION", composition=None, anchor_status="COMPLETE", clarify_for=clarify_slot, classifier_flags=flags, choices=card)
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
        notes.append(GENERAL_GUIDANCE_TEXT)  # written by code after the answer, never placed by the model
        _explain_needed_agent(decision.needs_agent, caps, collector, attach)
        if "BS_SELLER_CONTEXT" in caps.allowed_state:
            seller = business_state.read_entry(ctx, "BS_SELLER_CONTEXT", attached=attached, now=now)  # K2: what the seller told us
            collector.add_entry(dataclasses.replace(seller, gaps=()))  # an empty goal is not news in a general answer: only what exists is shown
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
        if route == "PLAYBOOK" and key == "COMPETITOR_PRICE_IMPACT" and runtime.max_candidate_prices is None:
            return _finish(ctx, runtime, turn, clock, log, status="FAILED", route=route, route_key=key, answer=CONFIG_TEXT, kind="ANSWER", composition=None,
                           anchor_status="FAILED", error_reason="CONFIG_MISSING: max candidate prices", classifier_flags=flags)
        leg_keys, required_keys, reads = _plan_legs(route, key)
        if route == "ACTION" and key == GST_KEY:
            # Route A / Route B is a permission-and-attachment result computed HERE, never a model choice (spec C11, G1).
            route_key = gst_route_key(caps.entitled_registry_keys)
            if route_key is None:
                return _finish(ctx, runtime, turn, clock, log, status="DENIED", route=route, route_key=key, answer=GST_WALL_TEXT, kind="ANSWER", composition=None,
                               anchor_status="DENIED", error_reason="no GST route available", classifier_flags=flags)
            leg_keys, required_keys = [route_key], {route_key}
        if leg_keys and (runtime.leg_timeout_seconds is None or runtime.max_legs is None):
            return _finish(ctx, runtime, turn, clock, log, status="FAILED", route=route, route_key=key, answer=CONFIG_TEXT, kind="ANSWER", composition=None,
                           anchor_status="FAILED", error_reason="CONFIG_MISSING", classifier_flags=flags)
        if runtime.max_legs is not None and len(leg_keys) > runtime.max_legs:
            return _finish(ctx, runtime, turn, clock, log, status="FAILED", route=route, route_key=key, answer=CONFIG_TEXT, kind="ANSWER", composition=None,
                           anchor_status="FAILED", error_reason="CONFIG_MISSING: max legs", classifier_flags=flags)
        legs, entries, refused_required = _execute(ctx, runtime, turn, resolved, leg_keys, required_keys, reads, attached, now, clock, log)
        need_gaps: list[str] = []
        if addons and route == "ACTION" and not refused_required:  # spec agent-needs 5: the CEO fetches what the request also asked for from the agent that provides it
            need_legs, need_gaps = _run_needs(ctx, runtime, turn, inv_id, user_msg, key, addons, ask_inputs, legs, caps, attached, now, clock, log)
            legs = [*legs, *need_legs]
        if key == "pi.discover":  # the run's candidates are read back from what it saved (the report), never taken from the run call's own return
            legs = _with_pi_report(runtime, turn, tenant, now, legs, attached, clock, log)
            _record_pi_finding(tenant, ctx.app_user_id, legs)
        for leg in legs:
            collector.add_leg(leg)
            if leg.action_key in GST_ROUTE_KEYS and leg.payload and (leg.payload.get("result") or {}).get("disclaimer"):
                disclaimers.append(("GST_LOOKUP", str(leg.payload["result"]["disclaimer"])))  # the stored text, rendered by code, never retyped by the model
        for entry in entries:
            collector.add_entry(entry)
        for g in need_gaps:
            collector.add_gap(g)
        if route == "PLAYBOOK" and key in _FLOW_NEEDS:  # the PI idea / competitor link (spec 5.2, S2) is recorded, with its outcome, beside the others
            _record_flow_need(tenant, inv_id, user_msg, key, legs, "LANDED_COST_FOR_IDEA" in addons)
        for k in leg_keys:
            if not any(l.action_key == k for l in legs):  # a leg that missed its deadline: named, never silently absent (E36, L9)
                collector.add_gap(f"{_label(k)} is still running; its result will appear in this investigation's findings when it finishes.")
                if k in required_keys:
                    refused_required = True
        if route == "PLAYBOOK" and not leg_keys:
            heading = None
        if key == "pi.discover" and any(t.startswith(WEB_ARTEFACT_TITLE) for t, _, _ in collector.artefacts):
            notes.append("To continue with any of these, say for example “write titles for #2”, “hashtags for #5” or “GST rate for #3”.")
        if route == "ACTION" and ACTIONS[key].session:
            template_only_answer = True  # what the specialist wrote is shown as it is, quoted and labelled, never re-worded by a second model
            heading = ("Here is what Product Intelligence found for your niche." if key == "pi.discover"
                       else "Here is what the market-trend research found." if key == "cmo.market_trends" else "Here is what was written for the details you gave.")
        if route == "PLAYBOOK" and PLAYBOOKS[key].needs_form:
            # Several figures of one metric (one margin per candidate price, one cost per supplier) can only be told apart by their labels, which the fixed
            # layout carries and prose with markers cannot. The answer is therefore the deterministic layout, with no model call (spec 6.33).
            template_only_answer = True
            heading = "Here is what the saved results show for what you entered."
    else:  # defensive: an unknown route is a safe clarification
        return _finish(ctx, runtime, turn, clock, log, status="CLARIFIED", route="CLARIFY", route_key=None, answer=_clarification_text("UNCLEAR_REQUEST"), kind="CLARIFICATION",
                       composition=None, anchor_status="COMPLETE", clarify_for="UNCLEAR_REQUEST", classifier_flags=flags)

    # What the seller attached is UNTRUSTED quoted data: shown to the composer only inside delimited evidence, never as a figure or an instruction (R9, spec 6.34).
    untrusted = [(f"your attached file {a['filename']}", str(a["extracted_text"])[:ATTACHMENT_EVIDENCE_CHARS]) for a in attachments if a.get("extracted_text")]
    notes = [*pre_notes, *notes, *_attachment_notes(attachments)]
    table = collector.table(untrusted=untrusted, disclaimers=disclaimers, attach=attach)
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
    follow_up = _missing_figure_question(ctx, runtime, tenant, now, turn, route, key, decision.slots, ui_refs, ask_sku, ask_inputs)
    if follow_up is not None:  # a CFO leg said what it is missing and the CEO can collect it: the answer ends with that one question (spec 6.37)
        return _finish(ctx, runtime, turn, clock, log, status="DELIVERED", route=route, route_key=key, answer=answer + "\n\n" + follow_up.text, kind="CLARIFICATION", composition=comp,
                       anchor_status=turn.derive_status(), clarify_for=follow_up.card["slot"], classifier_flags=flags, notes=notes, choices=follow_up.card)
    return _finish(ctx, runtime, turn, clock, log, status="DELIVERED", route=route, route_key=key, answer=answer, kind="ANSWER", composition=comp,
                   anchor_status=turn.derive_status(), classifier_flags=flags, notes=notes)


# ------------------------------------------------------------------------------------------------ pieces
PI_FINDING_TEXT = "Product Intelligence found product ideas for the niche you asked about. They come from public web sources and are not verified."


def _record_pi_finding(tenant: UUID, user_id: UUID | None, legs: Sequence[LegResult]) -> None:
    """Product Intelligence's result is noted in the shared findings (spec agent-needs 6.4) so the other agents and the CEO know a research run produced ideas. The text is
    fixed and carries no number or idea name; the source is the stored research run. Best-effort: it never costs the seller their answer."""
    try:
        run = next((l for l in legs if l.action_key == "pi.discover" and l.status in (LegStatus.COMPLETE, LegStatus.PARTIAL) and (l.payload or {}).get("runId")), None)
        report = next((l for l in legs if l.action_key == "pi.report" and l.payload), None)
        if run is None or report is None or not (report.payload or {}).get("candidates"):
            return
        findings.record(tenant, agent="PI", kind="PRODUCT_IDEA", text=PI_FINDING_TEXT, source_ref={"kind": "pi_research_run", "id": str((run.payload or {})["runId"])}, created_by=user_id)
    except Exception:  # noqa: BLE001
        logger.exception("could not record a PI finding")


NEEDS_NOT_CONFIGURED_TEXT = "The CEO's limit for follow-up lookups is not configured, so the extra lookup was not run. Your main request was."
_NEED_STATUS = {LegStatus.COMPLETE: "FULFILLED", LegStatus.PARTIAL: "FULFILLED", LegStatus.DENIED: "DENIED", LegStatus.NOT_ENTITLED: "NOT_ENTITLED", LegStatus.FAILED: "FAILED", LegStatus.UNAVAILABLE: "UNAVAILABLE"}


def _run_needs(
    ctx: AuthContext, runtime: CeoRuntime, turn: CeoTurn, inv_id: UUID, user_msg: UUID, key: str, addons: Sequence[str], inputs: Mapping[str, Any] | None,
    primary: Sequence[LegResult], caps: Capabilities, attached: frozenset[str], now: datetime, clock: StageClock, log: EventLog,
) -> tuple[list[LegResult], list[str]]:
    """Fulfils the add-ons of the request through the one choke point (spec agent-needs 5). The provider is chosen by code, the slot is the seller's own text, every
    check is the provider's own, and a refusal is a named gap: never a guessed or model-known value. The add-on never runs when the main request did not complete."""
    tenant = ctx.tenant_id
    assert tenant is not None
    legs: list[LegResult] = []
    gaps: list[str] = []
    wanted = needs.valid_addons(key, addons)
    if not wanted:
        return legs, gaps

    def record(nk: str, n: int, status: str, leg: LegResult | None = None, provider: str | None = None) -> None:
        try:
            ceo_need_repo.record(tenant, investigation_id=inv_id, turn_message_id=user_msg, need_key=nk, requester_agent=needs.NEEDS[nk].requester, mode=needs.NEEDS[nk].mode,
                                 provider_key=provider, idempotency_key=f"ceo-need-{user_msg}-{nk}-{n}", status=status, provider_run_id=leg.agent_run_id if leg else None)
        except Exception:  # noqa: BLE001 - the record is bookkeeping: it never costs the seller their answer
            logger.exception("could not record a need")

    limit = config.ceo_needs_max_per_turn()
    if limit is None:
        for n, nk in enumerate(wanted, start=1):
            record(nk, n, "CONFIG_MISSING")
        return legs, [NEEDS_NOT_CONFIGURED_TEXT]
    if not all(l.status in (LegStatus.COMPLETE, LegStatus.PARTIAL) for l in primary):
        for n, nk in enumerate(wanted, start=1):
            record(nk, n, "DROPPED")
        return legs, ["The extra lookup was not run because your main request did not complete."]
    for n, nk in enumerate(wanted, start=1):
        spec = needs.NEEDS[nk]
        if n > limit:
            record(nk, n, "DROPPED")
            gaps.append("An extra lookup was dropped: more were asked for than the CEO's limit allows in one turn.")
            continue
        log.emit("NEED_RAISED", need=nk, requester=spec.requester)
        text_in = needs.product_text(inputs)
        if text_in is None:
            record(nk, n, "UNAVAILABLE")
            gaps.append("I could not look up the GST rate: there is no product text to look up, or it is too long to pass on whole.")
            continue
        provider = gst_route_key(caps.entitled_registry_keys)
        if provider is None:
            record(nk, n, "DENIED")
            gaps.append(GST_WALL_TEXT)
            continue
        if not _preflight(ctx, runtime, provider, attached, now):
            record(nk, n, "DENIED", provider=provider)
            gaps.append("I could not get the GST rate: that lookup is not available to you here (the agent may be turned off for this conversation, or not part of your plan).")
            continue
        leg = _run_leg(turn, runtime, ResolvedSlots(tenant_id=tenant, today=now.date(), product_text=text_in), provider, attached, clock, log)
        legs.append(leg)
        status = _NEED_STATUS.get(leg.status, "FAILED")
        record(nk, n, status, leg, provider)
        log.emit("NEED_FULFILLED" if status == "FULFILLED" else "NEED_DROPPED", need=nk, status=status)
        if status != "FULFILLED":
            gaps.append("I could not get the GST rate this time" + (f": {leg.reason}." if leg.reason else "."))
    return legs, gaps


_FLOW_NEEDS = {"NEW_PRODUCT_DECISION": "LANDED_COST_FOR_IDEA", "COMPETITOR_PRICE_IMPACT": "MARGIN_AT_PRICE"}


def _record_flow_need(tenant: UUID, inv_id: UUID, user_msg: UUID, key: str, legs: Sequence[LegResult], from_idea: bool) -> None:
    """A decision playbook that answers a link between two agents is recorded as a need (who asked whom, and how it ended). The "idea" link is recorded only when the
    seller's words named an idea from PI's list ("is #3 worth stocking?"); a competitor margin is always CI's observation with the CFO's margin. Bookkeeping only."""
    nk = _FLOW_NEEDS[key]
    if nk == "LANDED_COST_FOR_IDEA" and not from_idea:
        return
    try:
        ok = bool(legs) and all(l.status in (LegStatus.COMPLETE, LegStatus.PARTIAL) for l in legs)
        spec = needs.NEEDS[nk]
        ceo_need_repo.record(tenant, investigation_id=inv_id, turn_message_id=user_msg, need_key=nk, requester_agent=spec.requester, mode=spec.mode, provider_key=spec.provider_key,
                             idempotency_key=f"ceo-need-{user_msg}-{nk}-1", status="FULFILLED" if ok else "FAILED")
    except Exception:  # noqa: BLE001
        logger.exception("could not record a flow need")


_TREND_LABELS = {"NICHE": "your niche", "MARKET_NEWS": "marketplace news", "REPORTED_TACTICS": "tactics sellers report", "NEW_PRODUCTS_BUZZ": "new product buzz", "ADJACENT": "related niches"}
MAX_QUERIES_SHOWN = 12


def _trend_preview(
    ctx: AuthContext, runtime: CeoRuntime, turn: CeoTurn, tenant: UUID, now: datetime, attached: frozenset[str], clock: StageClock, log: EventLog, run_inputs: Mapping[str, Any],
) -> input_session.Ask | str:
    """Runs the zero-cost preview through the one choke point and turns it into a confirm card written by code. A string is the plain reason it could not be prepared."""
    key = "cmo.market_trends_preview"
    if not _preflight(ctx, runtime, key, attached, now):
        return "market research is not available to you here"
    leg = _run_leg(turn, runtime, ResolvedSlots(tenant_id=tenant, today=now.date(), direct={"marketplaces": list(run_inputs.get("marketplaces") or [])}), key, attached, clock, log)
    p = leg.payload or {}
    if leg.status not in (LegStatus.COMPLETE, LegStatus.PARTIAL) or not p.get("digest"):
        return "the search plan could not be prepared"
    queries = p.get("queries") or []
    lines = [f"{n}. {_TREND_LABELS.get(str(q.get('section')), str(q.get('section')).lower())}: \u201c{q.get('query')}\u201d" for n, q in enumerate(queries[:MAX_QUERIES_SHOWN], start=1)]
    more = f" (and {len(queries) - MAX_QUERIES_SHOWN} more)" if len(queries) > MAX_QUERIES_SHOWN else ""
    off = [f"{_TREND_LABELS.get(str(s).upper(), str(s).lower())} ({r})" for s, r in (p.get("unavailableSections") or {}).items() if r and r != "NOT_REQUESTED"]
    text = (
        ("I will send exactly these searches to the web search providers" + more + ". Only your confirmed niche terms and marketplace names are sent:\n" + "\n".join(lines) if lines else
         "No searches can be sent yet.")
        + ("\nNot covered: " + "; ".join(off) + "." if off else "")
        + "\nThis uses one market-research run from your plan. Shall I go ahead?"
    )
    if not lines:
        return "there is nothing to research yet: confirm your niche terms on the CMO page first"
    resume = {"route": "ACTION", "key": "cmo.market_trends", "slots": {}, "refs": {},
              "inputs": {**{k: v for k, v in run_inputs.items()}, "plan_digest": str(p["digest"])}}
    return input_session.start_confirm("dr.trend_run", input_session.Ctx(tenant, now.date(), runtime.max_candidate_prices), text, resume)


def _missing_figure_question(
    ctx: AuthContext, runtime: CeoRuntime, tenant: UUID, now: datetime, turn: CeoTurn, route: str, key: str | None, slots: Mapping[str, str], refs: Mapping[str, Any],
    sku: str | None, inputs: Mapping[str, Any] | None,
) -> input_session.Ask | None:
    try:
        if route not in ("ACTION", "PLAYBOOK") or key is None:
            return None
        found = data_requests.collectable(tenant, turn.legs, sku)
        if found is None:
            return None
        session, row = found
        resume = {"route": route, "key": key, "slots": dict(slots), "refs": {k: str(v) for k, v in refs.items()}, "inputs": dict(inputs) if inputs else None, "request_id": str(row["id"])}
        return input_session.start_data_request(session, sku or "", input_session.Ctx(tenant, now.date(), runtime.max_candidate_prices), resume)
    except Exception:  # noqa: BLE001 - the follow-up is a convenience: the answer stands without it
        logger.exception("could not build the missing-figure question")
        return None


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
    # PRESENT: the model's guess that a specialist is needed is not a reason to refuse a general answer; nothing is claimed from it


def _read_state(ctx: AuthContext, turn: CeoTurn, key: str, attached: frozenset[str], runtime: CeoRuntime, log: EventLog) -> BusinessStateEntry:
    """One Business State read (persisted results only; nothing is computed) and its finding."""
    entry = business_state.read_entry(ctx, key, attached=attached, now=runtime.clock())
    assert ctx.tenant_id is not None and turn.investigation_id is not None and turn.turn_id is not None
    repo.insert_finding(
        ctx.tenant_id, turn.investigation_id, turn_id=turn.turn_id, source="BUSINESS_STATE", action_key=key, status=finding_status_for_entry(entry.status),
        figure_refs=[f.ref.to_json() for f in entry.figures] + [f.ref.to_json() for c in entry.conflicts for f in (c.a, c.b)], gap_reason="; ".join(g.message for g in entry.gaps) or None,
        presentation=safe(present_entry, ctx.tenant_id, entry), now=runtime.clock(),
    )
    log.emit("STATE_READ", entry=key, status=entry.status.value)
    return entry


ATTACHMENT_EVIDENCE_CHARS = 4000  # how much of a file's text the composer may see (a prompt-size bound, not a business threshold)
ATTACHMENT_EXCERPT_CHARS = 500  # how much the seller is shown verbatim, written by code and labelled as the file's own words


def _attachment_notes(attachments: Sequence[Mapping[str, Any]]) -> list[str]:
    """Plain lines appended to the answer: what was attached, whether it could be read, and a short verbatim excerpt of what the file says. The excerpt is the FILE'S
    text, quoted and labelled as such: it is never a figure with a register and never a verified value."""
    out: list[str] = []
    for a in attachments:
        out.append(f"Attached: {a['filename']} ({a['detected_type']}).")
        if a.get("extraction_note"):
            out.append(str(a["extraction_note"]))
        text = " ".join(str(a.get("extracted_text") or "").split())
        if text:
            cut = text[:ATTACHMENT_EXCERPT_CHARS] + ("…" if len(text) > ATTACHMENT_EXCERPT_CHARS else "")
            out.append(f"Your file says (quoted from {a['filename']}, not checked by Metrion): “{cut}”")
    return out


def _answer_direct(
    ctx: AuthContext, runtime: CeoRuntime, inv_id: UUID, user_msg: UUID, turn: CeoTurn, clock: StageClock, log: EventLog, text: str, now: datetime,
) -> TurnResult:
    """An answer written by code from memory: no classifier, no composer, nothing run."""
    tenant = ctx.tenant_id
    assert tenant is not None
    turn.turn_id = repo.create_turn(
        tenant, inv_id, user_message_id=user_msg, agent_run_id=turn.anchor_run_id, route="ADVISORY", route_key=None, slots={}, route_source="CLASSIFIER",
        classifier_result={"directMemoryAnswer": True, "model": "rules"}, status="PLAN_VALIDATED", now=now,
    )
    log.emit("PLAN_VALIDATED", route="ADVISORY", routeKey=None)
    return _finish(ctx, runtime, turn, clock, log, status="DELIVERED", route="ADVISORY", route_key=None, answer=text, kind="ANSWER", composition=None, anchor_status="COMPLETE")


def _answer_input(
    ctx: AuthContext, runtime: CeoRuntime, inv_id: UUID, user_msg: UUID, turn: CeoTurn, clock: StageClock, log: EventLog, outcome: Any, reply_meta: dict[str, Any] | None, now: datetime,
) -> TurnResult:
    """The CEO's reply to one answer of a guided input: the next question (or the same one again, with why), or the end. Nothing is run and no model is called."""
    tenant = ctx.tenant_id
    assert tenant is not None
    turn.turn_id = repo.create_turn(
        tenant, inv_id, user_message_id=user_msg, agent_run_id=turn.anchor_run_id, route="CLARIFY", route_key=None, slots={}, route_source="UI_ACTION",
        classifier_result={"inputSession": True, **(reply_meta or {})}, status="PLAN_VALIDATED", now=now,
    )
    log.emit("PLAN_VALIDATED", route="CLARIFY", routeKey=None)
    if isinstance(outcome, input_session.Ask):
        return _finish(ctx, runtime, turn, clock, log, status="CLARIFIED", route="CLARIFY", route_key=None, answer=outcome.text, kind="CLARIFICATION", composition=None,
                       anchor_status="COMPLETE", clarify_for=outcome.card["slot"], choices=outcome.card)
    text = "Okay, I have stopped. Nothing was run and nothing was saved." if isinstance(outcome, input_session.Cancelled) else outcome.text
    return _finish(ctx, runtime, turn, clock, log, status="DELIVERED", route="CLARIFY", route_key=None, answer=text, kind="ANSWER", composition=None, anchor_status="COMPLETE")


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


def _with_pi_report(
    runtime: CeoRuntime, turn: CeoTurn, tenant: UUID, now: datetime, legs: list[LegResult], attached: frozenset[str], clock: StageClock, log: EventLog,
) -> list[LegResult]:
    run = next((l for l in legs if l.action_key == "pi.discover" and l.status in (LegStatus.COMPLETE, LegStatus.PARTIAL) and (l.payload or {}).get("runId")), None)
    if run is None:
        return legs
    try:
        run_id = UUID(str((run.payload or {})["runId"]))
    except ValueError:
        return legs
    report = _run_leg(turn, runtime, ResolvedSlots(tenant_id=tenant, today=now.date(), pi_run_id=run_id), "pi.report", attached, clock, log)
    return [*legs, report]


def _slots_for(key: str, resolved: ResolvedSlots) -> dict[str, object]:
    if resolved.run is not None:
        builder = PLAYBOOK_LEG_SLOTS.get((resolved.run.playbook, key))
        if builder is not None:
            return builder(resolved)
    if key in GST_ROUTE_KEYS:  # one plan for both routes: the slots are the same, only who runs them differs
        return ACTIONS[GST_KEY].build_slots(resolved)
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
