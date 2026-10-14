"""The CEO approval workflow: the frozen plan, its hash, and the approval checks (ceo-approval-workflow.md sections 5.3, 6.1, 6.2, 6.6; CD9-CD15 of ceo-cmo-delegation.md).

What this module IS: the CODE that decides what a plan says, hashes it, and decides - in the fixed order of section 6.6, failing closed - whether an approval may proceed.
What it is NOT: it runs nothing and meters nothing (`approval_run.py` runs an approved plan), it asks no model anything, and it computes no money: slot values that are
money are integer paise copied from already-validated slots, and a float anywhere in a plan is refused outright (the canonical form is integers and text only).

Decisions of record applied here:
* C4: the plan is built by CODE from the action registry and already-validated slots; no model writes, approves, declines or alters any part of it.
* C6 / D4 / Q-A9: the lifetime is the CONSTANT `PLAN_TTL_SECONDS = 1800`, stored per plan in `expires_at` (immutable), measured on the server clock (`runtime.clock()`).
  There is deliberately no setting that could be mis-set to a long window or extend an existing plan.
* C7: only the authenticated user who requested the action may approve; no role (not even OWNER) overrides it.
* C8 / 6.2: approval is bound to the exact frozen plan by `plan_hash = sha256(canonical_json({plan_id, tenant_id, investigation_id, requested_by, expires_at, plan}))`;
  the server RECOMPUTES it from the stored row and compares it in constant time with the stored hash and the client's value. The client's value is never a source.
* C3 / CD11: nothing typed in chat, no clarification reply and no classifier output can approve; the only caller of the approval path is the explicit approve endpoint.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from backend import config
from backend.auth.context import AuthContext
from backend.auth.permissions import AGENT_CEO, INVESTIGATION_VIEW, has_permission
from backend.ceo import dispatch as ceo_dispatch
from backend.ceo.approval_gate import gate_leg
from backend.ceo.contract import ActionSpec, InvalidSlots, TurnDenied
from backend.ceo.runtime import CeoRuntime
from backend.entitlement import resolve_ceo_entitlement
from backend.repositories import accounting_cutover_repo, agent_run_repo, investigation_plan_repo as plan_repo, investigation_repo as inv_repo

logger = logging.getLogger(__name__)

PLAN_VERSION = 1
THEN_SLOTS_MARKER = "CODE_FROM_EARLIER_RESULT"  # a follow-up step's slots are not frozen: code resolves them from the earlier result (ceo-pi-research-flow.md Q1a)
PLAN_TTL_SECONDS = 1800  # C6 / Q-A9: a constant, stored in each plan's `expires_at`

PLAN_MESSAGE_LEAD = "I have prepared a plan. Nothing runs until you press Approve on the card below; typing yes does not approve it."
APPROVED_NOTE = "You approved this plan."


def approved_note(plan: Mapping[str, Any]) -> str:
    """The one short line shown after approval: \"You approved: <plan title>\". The full plan stays on its card (Details) and in the stored plan; it is never repeated in the chat."""
    title = " ".join(str(plan.get("title") or "").split())
    return f"You approved: {title}" if title else APPROVED_NOTE

DECLINED_NOTE = "Declined: nothing was run, sent or used up."

# What the seller is told when approval is refused. Fixed text written by code; nothing here can carry a figure.
REFUSAL_TEXT = {
    "NOT_FOUND": "That plan was not found.",
    "NOT_REQUESTER": "Only the person who asked for this can approve or decline it.",
    "PLAN_CHANGED": "This plan changed, or the approval does not match it. Nothing was run. Ask again to get a fresh plan.",
    "PLAN_EXPIRED": "This plan expired (plans last 30 minutes). Nothing was run. Ask again to get a fresh plan.",
    "PLAN_NOT_AWAITING": "This plan is no longer waiting for approval. Nothing was run.",
    "PLAN_STALE": "The information behind this plan changed after it was made, so it was not run. Ask again to get a fresh plan.",
    "INVESTIGATION_NOT_ACTIVE": "This investigation is no longer active, so its plans cannot be approved.",
    "INTEGRATION_UNAVAILABLE": "A service this plan needs is not available right now, so it was not run.",
    "EXECUTION_LIMITS": "The CEO's execution limits are not configured, or this plan exceeds them, so it was not run.",
    "ACCOUNTING_NOT_READY": "The usage accounting rule that keeps a failed run from costing you anything is not in effect yet, so this was not run.",
    "TURN_IN_PROGRESS": "Another request in this conversation is still running. Try again in a moment.",
    "FORBIDDEN": "You do not have access to run this plan.",
    "ENTITLEMENT_DENIED": "Your allowance for this period does not cover running this plan, so it was not run. The plan stays open until it expires.",
}


class PlanNotBuildable(Exception):
    """The turn cannot honestly be turned into a plan; nothing is created and the seller is told `text`."""

    def __init__(self, code: str, text: str) -> None:
        super().__init__(code)
        self.code, self.text = code, text


class ApprovalRefused(Exception):
    """A check of section 6.6 failed. `status_code`/`code` are the HTTP answer; `reason_code` is what the APPROVAL_REFUSED event records."""

    def __init__(self, status_code: int, code: str, reason_code: str, message: str | None = None, **extra: Any) -> None:
        super().__init__(code)
        self.status_code, self.code, self.reason_code = status_code, code, reason_code
        self.message = message or REFUSAL_TEXT.get(code, code)
        self.extra = extra


# ------------------------------------------------------------------------------------------------ canonical form and hash (6.2, C8)
def _norm(value: Any) -> Any:
    """The canonical value: text, integers, booleans, null, lists and string-keyed objects only. UUIDs lowercase, timestamps UTC ISO-8601 with microseconds. A float
    (money must be integer paise) or any other type is a hard error, never rounded or stringified."""
    if value is None or isinstance(value, (bool, str, int)):
        return value
    if isinstance(value, Enum):
        return _norm(value.value)
    if isinstance(value, UUID):
        return str(value).lower()
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise TypeError("a naive timestamp cannot appear in a plan")
        return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for k, v in value.items():
            if not isinstance(k, str):
                raise TypeError("plan keys must be text")
            out[k] = _norm(v)
        return out
    if isinstance(value, (list, tuple)):
        return [_norm(v) for v in value]
    raise TypeError(f"{type(value).__name__} cannot appear in a plan")


def canonical_json(value: Any) -> str:
    return json.dumps(_norm(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_hash(*, plan_id: UUID, tenant_id: UUID, investigation_id: UUID, requested_by: UUID, expires_at: datetime, plan: Mapping[str, Any]) -> str:
    body = {"plan_id": plan_id, "tenant_id": tenant_id, "investigation_id": investigation_id, "requested_by": requested_by, "expires_at": expires_at, "plan": plan}
    return hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()


def hash_of_row(row: Mapping[str, Any]) -> str:
    """The hash recomputed from a STORED plan row (never from client input)."""
    return compute_hash(plan_id=row["id"], tenant_id=row["tenant_id"], investigation_id=row["investigation_id"], requested_by=row["requested_by"],
                        expires_at=row["expires_at"], plan=row["plan"])


def hashes_match(*candidates: str, recomputed: str) -> bool:
    """Constant-time comparison of the recomputed hash with EVERY candidate (the stored value, the client's value)."""
    ok = True
    for c in candidates:
        ok &= isinstance(c, str) and hmac.compare_digest(c.encode("utf-8"), recomputed.encode("utf-8"))
    return ok


# ------------------------------------------------------------------------------------------------ integrations
# Which configured service a plan's destination label needs. A label this table does not know is UNAVAILABLE (fail closed); public GST pages need no key.
_INTEGRATION_KEYS = {
    "Tavily": config.tavily_api_key, "YouTube Data API": config.youtube_api_key, "Google Places": config.google_places_api_key,
    "Metrion vision model": config.cmo_vision_endpoint_verified,  # raises (= UNAVAILABLE) unless the endpoint is attested operator-controlled, checked now
}
_NO_KEY_NEEDED = frozenset({"Public GST reference pages"})


def integration_status(label: str) -> str:
    if label in _NO_KEY_NEEDED:
        return "AVAILABLE"
    getter = _INTEGRATION_KEYS.get(label)
    try:
        return "AVAILABLE" if getter is not None and bool(getter()) else "UNAVAILABLE"
    except Exception:  # noqa: BLE001 - a configuration read that fails is "not available", never a crash or a guess
        return "UNAVAILABLE"


# ------------------------------------------------------------------------------------------------ data basis (6.6 step 9)
def niche_brief_basis(tenant_id: UUID, brief_id: UUID) -> dict[str, Any] | None:
    """The saved niche brief a PI run reads, as {kind, id, as_of, fingerprint}, or None if it no longer resolves for this tenant."""
    from backend.services import ceo_reads

    row = ceo_reads.niche_brief(tenant_id, brief_id)
    if row is None:
        return None
    stable = {k: row.get(k) for k in ("status", "category_text", "budget_paise", "target_price_min_paise", "target_price_max_paise", "marketplaces")}
    return {"kind": "NICHE_BRIEF", "id": str(brief_id), "as_of": str(row.get("readied_at") or row.get("created_at") or ""),
            "fingerprint": hashlib.sha256(canonical_json(stable).encode("utf-8")).hexdigest()}


def attachment_basis(tenant_id: UUID, attachment_id: UUID, investigation_id: UUID | None = None) -> dict[str, Any] | None:
    """The attached file a photo-reading plan is built on, as {kind, id, as_of, fingerprint = sha256}, or None if it no longer resolves for this tenant (and conversation)."""
    row = inv_repo.get_attachment_meta(tenant_id, attachment_id)
    if row is None or (investigation_id is not None and row["investigation_id"] != investigation_id):
        return None
    return {"kind": "ATTACHMENT", "id": str(attachment_id), "as_of": str(row["created_at"]), "fingerprint": str(row["sha256"])}


_BASIS_RESOLVERS = {
    "NICHE_BRIEF": lambda tenant, ref: niche_brief_basis(tenant, UUID(str(ref))),
    "ATTACHMENT": lambda tenant, ref: attachment_basis(tenant, UUID(str(ref))),
}


def resolve_basis(tenant_id: UUID, kind: str, ref: str) -> dict[str, Any] | None:
    resolver = _BASIS_RESOLVERS.get(kind)
    if resolver is None:
        return None  # an unknown kind cannot be re-validated: it is stale, never trusted
    try:
        return resolver(tenant_id, ref)
    except Exception:  # noqa: BLE001
        logger.exception("could not re-resolve a plan's data basis")
        return None


def data_basis_for(tenant_id: UUID, slots_by_key: Mapping[str, Mapping[str, Any]], investigation_id: UUID | None = None) -> list[dict[str, Any]]:
    """The records a plan was built on, found by code from the frozen slots: the saved research brief of a PI run, or the attached photo a CMO reading is built on."""
    out: list[dict[str, Any]] = []
    for key, slots in slots_by_key.items():
        if key == "cmo.analyze_attachment" and slots.get("attachment_id"):
            basis = attachment_basis(tenant_id, UUID(str(slots["attachment_id"])), investigation_id)
            if basis is None or (slots.get("sha256") and basis["fingerprint"] != slots["sha256"]):
                raise PlanNotBuildable("PLAN_STALE", "The attached photo could not be found in this conversation, so no plan was made. Nothing ran.")
            out.append(basis)
        brief = slots.get("niche_brief_id")
        if key == "pi.discover" and brief:
            basis = niche_brief_basis(tenant_id, UUID(str(brief)))
            if basis is None:
                raise PlanNotBuildable("PLAN_STALE", "The saved research brief for this plan could not be found, so no plan was made. Nothing ran.")
            out.append(basis)
    return out


# ------------------------------------------------------------------------------------------------ plan text (code only)
_EGRESS_TEXT = {"SELLER_NICHE_TEXT": "the niche you described", "CONFIRMED_NICHE_TERMS": "your confirmed niche terms"}
_MODEL_TEXT = {
    "SELLER_CATALOG_TEXT": "the product details you gave go to the language model, which is operated by Metrion",
    "PUBLIC_SEARCH_RESULT_TEXT": "public search results are read by the language model, which is operated by Metrion",
    "PRODUCT_TITLE": "the product title goes to the language model, which is operated by Metrion",
    "FIGURES_AND_LABELS": "figures and labels go to the language model, which is operated by Metrion",
    "PRODUCT_IMAGE": "your attached photo, with its location and camera data removed, goes to the vision model, which is operated by Metrion",
}


def _label(key: str) -> str:
    from backend.ceo.evidence import LEG_LABELS

    return LEG_LABELS.get(key, key)


def _show(value: Any) -> str:
    if isinstance(value, list) and value and all(isinstance(v, Mapping) and "name" in v and "value" in v for v in value):
        text = "; ".join(f"{v['name']}: {v['value']}" for v in value)  # a seller's confirmed product facts, readable on the card
    else:
        text = ", ".join(str(v) for v in value) if isinstance(value, list) else str(value)
    return text if len(text) <= 120 else text[:117] + "..."


def _summary(legs: Sequence[Mapping[str, Any]], assumptions: Sequence[str], details: Sequence[str] = ()) -> str:
    lines = ["Plan: " + "; ".join(f"run {_label(l['action_key'])}" for l in legs) + "."]
    lines.extend(details)
    for l in legs:
        shown = [f"{k} = {_show(v)}" for k, v in l["slots"].items() if k not in ("request_key", "ceo_ref") and v not in (None, "", [], {})]
        if shown:
            lines.append(f"{_label(l['action_key'])}, with: " + "; ".join(shown) + ".")
        if l["meters"]:
            lines.append("It uses: " + ", ".join(f"{m['units']} x {m['meter_code']}" for m in l["meters"]) + " from your plan allowance.")
        if l["egress"]:
            lines.append("It sends " + ", ".join(_EGRESS_TEXT.get(e, e) for e in l["egress"]) + " to " + ", ".join(l["destinations"]) + ".")
        for m in l["model_egress"]:
            if m in _MODEL_TEXT:
                lines.append(f"Language model: {_MODEL_TEXT[m]}.")
    lines.extend(assumptions)
    return "\n".join(lines)


def _generic_title(legs: Sequence[Mapping[str, Any]]) -> str:
    return "; ".join(_label(l["action_key"]) for l in legs)[:160]


def _generic_compact(legs: Sequence[Mapping[str, Any]], title: str) -> list[str]:
    """Short lines for a plan that has no purpose-written ones: what runs, what it uses, and how long it is valid."""
    lines = [f"Run: {title}."]
    uses = [f"{m['units']} x {m['meter_code']}" for l in legs for m in l["meters"]]
    if uses:
        lines.append("Uses: " + ", ".join(uses) + " from your plan allowance, only for results that complete.")
    lines.append(f"Valid for {PLAN_TTL_SECONDS // 60} minutes.")
    return lines


# ------------------------------------------------------------------------------------------------ building a plan (6.1)
@dataclass(frozen=True, slots=True)
class BuiltPlan:
    plan_id: UUID
    plan: dict[str, Any]
    plan_hash: str
    created_at: datetime
    expires_at: datetime


def build_plan(
    ctx: AuthContext, runtime: CeoRuntime, *, investigation_id: UUID, route: str, route_key: str | None, legs: Sequence[tuple[str, Mapping[str, Any]]],
    data_basis: Sequence[Mapping[str, Any]] = (), prior_attempt: Mapping[str, Any] | None = None, now: datetime,
    details: Sequence[str] = (), units: Mapping[str, int] | None = None, followup: Mapping[str, Any] | None = None,
    title: str | None = None, compact: Sequence[str] = (), then: Sequence[str] = (),
) -> BuiltPlan:
    """Freezes what a turn WOULD run. Raises `PlanNotBuildable` (nothing is created) when the plan cannot be built honestly: an unclassified action, slots the action
    refuses, a float, an integration that is not available, or the execution limits not configured (D9, fail closed)."""
    assert ctx.tenant_id is not None
    if runtime.leg_timeout_seconds is None or runtime.max_legs is None:
        raise PlanNotBuildable("CONFIG_MISSING", "The CEO's investigation limits have not been configured by the operator yet, so no plan can be made and nothing was run.")
    if len(legs) > runtime.max_legs:
        raise PlanNotBuildable("TOO_MANY_LEGS", "That request needs more steps than the CEO's limit allows, so no plan was made and nothing was run.")
    plan_id = uuid4()
    frozen_legs: list[dict[str, Any]] = []
    integrations: dict[str, dict[str, Any]] = {}
    for key, slots in legs:
        spec = runtime.registry.get(key)
        if spec.effects is None:
            raise PlanNotBuildable("UNCLASSIFIED_ACTION", "That action is not classified for approval, so no plan was made and nothing was run.")
        try:
            frozen_slots = _norm(dict(slots))
        except TypeError:
            raise PlanNotBuildable("BAD_SLOTS", "The details for that request could not be frozen exactly, so no plan was made and nothing was run.") from None
        if "request_key" in frozen_slots:  # N6: a plan-derived idempotency key, so one approved plan can bill an operation at most once
            frozen_slots["request_key"] = f"ceo-plan-{plan_id}"
        try:
            ceo_dispatch._validate_slots(spec, frozen_slots)
        except InvalidSlots:
            raise PlanNotBuildable("BAD_SLOTS", "Those details are not valid for that action, so no plan was made and nothing was run.") from None
        fx = spec.effects
        gate = gate_leg(key)
        frozen_legs.append({
            "action_key": key, "agent": spec.agent.value if spec.agent else None, "source": spec.source, "effect": spec.effect.value, "requires_approval": gate.requires_approval,
            "external": fx.external.value, "egress": list(fx.egress), "slots": frozen_slots, "refs": {}, "meters": [{"meter_code": m, "units": int((units or {}).get(key, 1))} for m in fx.meters],
            "destinations": list(fx.destinations), "model_egress": list(fx.model_egress),
        })
        for label in fx.destinations:
            required = fx.external.value == "SELLER_DATA_OUT" or fx.force_approval  # a forced-approval action's destination (the vision model) must be reachable, or no plan is made
            prior = integrations.get(label)
            integrations[label] = {"code": label, "status": integration_status(label), "required": required or bool(prior and prior["required"])}
    frozen_then: list[dict[str, Any]] = []
    for key in then:  # follow-up steps of the same approval (ceo-pi-research-flow.md Q1a): listed up front, run by code with slots resolved from the earlier result
        spec = runtime.registry.get(key)
        if spec.effects is None:
            raise PlanNotBuildable("UNCLASSIFIED_ACTION", "That action is not classified for approval, so no plan was made and nothing was run.")
        fx = spec.effects
        frozen_then.append({
            "action_key": key, "agent": spec.agent.value if spec.agent else None, "source": spec.source, "effect": spec.effect.value, "requires_approval": gate_leg(key).requires_approval,
            "external": fx.external.value, "egress": list(fx.egress), "slots": {"resolved_by": THEN_SLOTS_MARKER}, "refs": {}, "meters": [{"meter_code": m, "units": 1} for m in fx.meters],
            "destinations": list(fx.destinations), "model_egress": list(fx.model_egress),
        })
        for label in fx.destinations:  # not required: a missing provider key degrades that lookup (named in the result) rather than blocking the research
            prior = integrations.get(label)
            integrations[label] = {"code": label, "status": integration_status(label), "required": bool(prior and prior["required"])}
    down = [i["code"] for i in integrations.values() if i["required"] and i["status"] != "AVAILABLE"]
    if down:
        raise PlanNotBuildable("INTEGRATION_UNAVAILABLE", "This needs " + ", ".join(down) + ", which is not set up on this server (the operator has to configure it) or is not available right now, so no plan was made, nothing was searched or sent, and nothing was used up.")
    assumptions = [
        "Nothing has run yet. It runs only after you press Approve on this card.",
        f"This plan is valid for {PLAN_TTL_SECONDS // 60} minutes from now.",
        "Usage is counted only for results that complete; a failed or refused step uses nothing.",
    ]
    if any(l["egress"] for l in frozen_legs):
        assumptions.append("Only the data listed above leaves Metrion, and only to the services listed.")
    if any(l["action_key"] == "pi.discover" for l in frozen_legs):
        assumptions.append("After the research run finishes, the saved report is read back to show you the ideas; that read starts no new research.")
    if frozen_then:
        assumptions.append("Then, as part of this same approval and without asking again: " + "; ".join(f"run {_label(t['action_key'])} (uses " + ", ".join(f"{m['units']} x {m['meter_code']}" for m in t["meters"]) + (f"; sends public product names to {', '.join(t['destinations'])}" if t["destinations"] else "") + ")" for t in frozen_then) + ". Which products it covers is decided by code from the research result.")
    plan: dict[str, Any] = {
        "plan_version": PLAN_VERSION, "route": route, "route_key": route_key, "legs": frozen_legs, "then": frozen_then, "integrations": list(integrations.values()), "assumptions": assumptions,
        "data_basis": [dict(b) for b in data_basis], "details": [str(d) for d in details], "limits": {"max_legs": runtime.max_legs, "leg_timeout_seconds": runtime.leg_timeout_seconds},
        "prior_attempt": dict(prior_attempt) if prior_attempt else None,
    }
    if followup:  # the seller's original request, frozen with the photo-reading plan: after it runs, the CEO asks the seller to confirm the facts and then plans THAT request
        plan["followup"] = dict(followup)
    if prior_attempt:
        assumptions.append("Warning: an earlier attempt at this may already have been sent and may have been charged. Metrion never repeats it automatically.")
    plan["summary_text"] = _summary(frozen_legs, assumptions, details)
    # The chat presentation: a short title and 3-5 short lines. The full text above (details, assumptions, frozen slots) is unchanged and is still what the hash covers; the card shows it behind "Details".
    plan["title"] = title or _generic_title(frozen_legs)
    plan["compact_lines"] = [str(c) for c in compact] or _generic_compact([*frozen_legs, *frozen_then], plan["title"])
    plan = _norm(plan)
    created = now.astimezone(timezone.utc)
    expires = created + timedelta(seconds=PLAN_TTL_SECONDS)
    h = compute_hash(plan_id=plan_id, tenant_id=ctx.tenant_id, investigation_id=investigation_id, requested_by=ctx.app_user_id, expires_at=expires, plan=plan)
    return BuiltPlan(plan_id, plan, h, created, expires)


def prior_attempt_for(tenant_id: UUID, investigation_id: UUID, leg_keys: Sequence[str]) -> dict[str, Any] | None:
    """The newest earlier plan of THIS investigation, with the same legs, whose execution ended with an uncertain external outcome (OUTCOME_UNKNOWN), or None."""
    for row in reversed(plan_repo.list_for_investigation(tenant_id, investigation_id)):
        if [l["action_key"] for l in row["plan"].get("legs", [])] != list(leg_keys):
            continue
        if any(e["event"] == "OUTCOME_UNKNOWN" for e in plan_repo.events(tenant_id, row["id"])):
            return {"plan_id": str(row["id"]), "outcome": "UNKNOWN"}
    return None


def create_plan(
    ctx: AuthContext, runtime: CeoRuntime, *, investigation_id: UUID, planned_turn_id: UUID, anchor_run_id: UUID, route: str, route_key: str | None,
    legs: Sequence[tuple[str, Mapping[str, Any]]], now: datetime, details: Sequence[str] = (), units: Mapping[str, int] | None = None,
    followup: Mapping[str, Any] | None = None, title: str | None = None, compact: Sequence[str] = (), then: Sequence[str] = (),
) -> tuple[BuiltPlan, UUID]:
    """Build and store the plan for a turn that would run an approval-required action (6.1): one plan row, its CREATED event, the PLAN message, and any older open plan
    of the investigation SUPERSEDED, in one transaction. Returns the plan and the PLAN message id. Raises `PlanNotBuildable` with nothing written."""
    assert ctx.tenant_id is not None
    if accounting_cutover_repo.effective_at(accounting_cutover_repo.CEO_UNIT_RULE_2) is None:  # fail closed: without it an approved run that FAILS would still cost a conversation unit
        raise PlanNotBuildable("ACCOUNTING_NOT_READY", "The usage accounting rule that keeps a failed run from costing you anything is not in effect yet, so no plan was made and nothing was run.")
    basis = data_basis_for(ctx.tenant_id, {k: s for k, s in legs}, investigation_id)
    built = build_plan(ctx, runtime, investigation_id=investigation_id, route=route, route_key=route_key, legs=legs, data_basis=basis, now=now,
                       prior_attempt=prior_attempt_for(ctx.tenant_id, investigation_id, [k for k, _ in legs]), details=details, units=units, followup=followup, title=title, compact=compact, then=then)
    message_id = plan_repo.create(
        ctx.tenant_id, plan_id=built.plan_id, investigation_id=investigation_id, planned_turn_id=planned_turn_id, anchor_run_id=anchor_run_id, requested_by=ctx.app_user_id,
        plan=built.plan, plan_hash=built.plan_hash, created_at=built.created_at, expires_at=built.expires_at,
        message_text=PLAN_MESSAGE_LEAD,
    )
    return built, message_id


# ------------------------------------------------------------------------------------------------ the approval checks (6.6)
@dataclass(frozen=True, slots=True)
class Verified:
    """Checks 1-10 passed: the stored plan row and what was resolved for it."""

    row: dict[str, Any]
    specs: tuple[ActionSpec, ...]


@dataclass(frozen=True, slots=True)
class Replay:
    """The plan was already approved: the idempotent answer is the execution turn it created."""

    row: dict[str, Any]


def _refuse(tenant_id: UUID, plan_id: UUID | None, user_id: UUID, refusal: ApprovalRefused) -> ApprovalRefused:
    """Every refusal of an existing plan leaves one APPROVAL_REFUSED event naming the check that failed (AC-A6); nothing else changes."""
    if plan_id is not None:
        try:
            _record_refusal(tenant_id, plan_id, user_id, refusal.reason_code)
        except Exception:  # noqa: BLE001 - the audit write must not hide the refusal itself
            logger.exception("could not record an approval refusal")
    return refusal


def _record_refusal(tenant_id: UUID, plan_id: UUID, user_id: UUID, reason_code: str) -> None:
    plan_repo.record_event(tenant_id, plan_id, event="APPROVAL_REFUSED", actor_user_id=user_id, reason_code=reason_code)


def verify_for_approval(ctx: AuthContext, runtime: CeoRuntime, investigation_id: UUID, plan_id: UUID, client_hash: str, *, now: datetime) -> Verified | Replay:
    """Section 6.6 checks 1-10, in order, failing closed. The first failure wins; nothing runs, nothing is metered, no turn is created. Raises `ApprovalRefused`.
    (Check 11, the investigation turn lock, and the approval transaction belong to `approval_run`.)"""
    assert ctx.tenant_id is not None and ctx.role is not None
    tenant, user = ctx.tenant_id, ctx.app_user_id
    # 1. tenant context present (guaranteed by require_auth, asserted above); the investigation is visible under RLS and ACTIVE
    inv = inv_repo.get_investigation(tenant, investigation_id)
    if inv is None:
        raise ApprovalRefused(404, "NOT_FOUND", "INVESTIGATION_NOT_FOUND")
    row = plan_repo.get(tenant, investigation_id, plan_id)
    if inv["status"] != "ACTIVE":  # (a refusal is audited on the plan only when the plan is visible)
        raise _refuse(tenant, plan_id if row is not None else None, user, ApprovalRefused(409, "INVESTIGATION_NOT_ACTIVE", "INVESTIGATION_NOT_ACTIVE", status=inv["status"]))
    # 2. the plan is visible under RLS AND belongs to this investigation: a foreign id looks exactly like a missing one
    if row is None:
        raise ApprovalRefused(404, "NOT_FOUND", "PLAN_NOT_FOUND")
    # 3. only the requester (C7); roles, including OWNER, grant no override
    if row["requested_by"] != user:
        raise _refuse(tenant, plan_id, user, ApprovalRefused(403, "NOT_REQUESTER", "NOT_REQUESTER"))
    # 4. the hash: recomputed from the stored row, equal to the stored hash AND to the client's value
    try:
        recomputed = hash_of_row(row)
    except TypeError:
        recomputed = ""
    if not recomputed or not hashes_match(row["plan_hash"], client_hash, recomputed=recomputed):
        raise _refuse(tenant, plan_id, user, ApprovalRefused(409, "PLAN_CHANGED", "HASH_MISMATCH"))
    # 5. status and expiry. An already approved plan is the idempotent replay (6.7); every other non-open state is a 409.
    if row["status"] == "APPROVED":
        return Replay(row)
    if row["status"] == "AWAITING_APPROVAL" and now >= row["expires_at"]:
        plan_repo.expire_if_due(tenant, plan_id, now=now)  # C6: persisted EXPIRED with its SYSTEM event
        raise _refuse(tenant, plan_id, user, ApprovalRefused(409, "PLAN_EXPIRED", "EXPIRED", status="EXPIRED"))
    if row["status"] != "AWAITING_APPROVAL":
        code = "PLAN_EXPIRED" if row["status"] == "EXPIRED" else "PLAN_NOT_AWAITING"
        raise _refuse(tenant, plan_id, user, ApprovalRefused(409, code, "NOT_AWAITING", status=row["status"]))
    plan = row["plan"]
    leg_keys = [l["action_key"] for l in plan.get("legs", [])]
    leg_keys += [l["action_key"] for l in plan.get("then", [])]  # the follow-up steps are authorized, attached, entitled and counted exactly like the legs
    try:
        specs = tuple(runtime.registry.get(k) for k in leg_keys)
    except Exception:  # noqa: BLE001 - an action no longer in the closed catalog cannot run
        raise _refuse(tenant, plan_id, user, ApprovalRefused(409, "PLAN_STALE", "UNKNOWN_ACTION")) from None
    # 6. authorization re-evaluated NOW: agent.ceo, investigation.view and every leg's required permissions
    if not all(has_permission(role=ctx.role, permissions=ctx.permissions, key=k) for k in (AGENT_CEO, INVESTIGATION_VIEW)):
        _denied_anchor(ctx, investigation_id, now, "agent.ceo/investigation.view")
        raise _refuse(tenant, plan_id, user, ApprovalRefused(403, "FORBIDDEN", "PERMISSION"))
    for spec in specs:
        missing = [k for k in runtime.registry.required_permissions(spec) if not has_permission(role=ctx.role, permissions=ctx.permissions, key=k)]
        if missing:
            _denied_anchor(ctx, investigation_id, now, missing[0])
            raise _refuse(tenant, plan_id, user, ApprovalRefused(403, "FORBIDDEN", "PERMISSION"))
    # 7. each leg's agent is still attached to the investigation
    attached = inv_repo.attached_agents(tenant, investigation_id)
    for spec in specs:
        if spec.agent is not None and spec.agent.value not in attached:
            raise _refuse(tenant, plan_id, user, ApprovalRefused(409, "PLAN_STALE", "NOT_ATTACHED", message="An agent this plan needs is no longer attached to this investigation, so it was not run."))
    # 8. entitlements re-resolved now: every leg's own preflight, then the CEO cap (the same resolver `open_turn` uses)
    for spec in specs:
        if spec.entitlement is not None and not spec.entitlement(tenant, now).passed:
            raise _refuse(tenant, plan_id, user, ApprovalRefused(402, "ENTITLEMENT_DENIED", "ENTITLEMENT"))
    if not resolve_ceo_entitlement(tenant, occurred_at=now).passed:
        try:
            stray = ceo_dispatch.open_turn(ctx, investigation_id=investigation_id, trigger_ref="ceo.approved_plan", now=now)  # writes the DENIED anchor run, as a turn does
            stray.close(status="DENIED", error_reason="cap changed during the check", now=now)  # (cannot normally happen: never leave a RUNNING anchor behind)
        except TurnDenied:
            pass
        raise _refuse(tenant, plan_id, user, ApprovalRefused(402, "ENTITLEMENT_DENIED", "ENTITLEMENT"))
    # 9. data re-validated: the frozen slots pass the same validators, and every data_basis record still resolves unchanged
    for spec, leg in zip(specs, plan["legs"]):
        try:
            ceo_dispatch._validate_slots(spec, leg["slots"])
        except InvalidSlots:
            raise _refuse(tenant, plan_id, user, ApprovalRefused(409, "PLAN_STALE", "SLOTS_INVALID")) from None
    for basis in plan.get("data_basis", []):
        now_basis = resolve_basis(tenant, str(basis.get("kind")), str(basis.get("id")))
        if now_basis is None or now_basis["fingerprint"] != basis.get("fingerprint") or now_basis["as_of"] != basis.get("as_of"):
            raise _refuse(tenant, plan_id, user, ApprovalRefused(409, "PLAN_STALE", "DATA_CHANGED"))
    # 10. execution limits, accounting and integrations
    if accounting_cutover_repo.effective_at(accounting_cutover_repo.CEO_UNIT_RULE_2) is None:
        raise _refuse(tenant, plan_id, user, ApprovalRefused(409, "ACCOUNTING_NOT_READY", "ACCOUNTING_NOT_READY"))
    if runtime.max_legs is None or runtime.leg_timeout_seconds is None or len(leg_keys) > runtime.max_legs:
        raise _refuse(tenant, plan_id, user, ApprovalRefused(409, "EXECUTION_LIMITS", "LIMITS"))
    for integ in plan.get("integrations", []):
        if integ.get("required") and integration_status(str(integ.get("code"))) != "AVAILABLE":
            raise _refuse(tenant, plan_id, user, ApprovalRefused(409, "INTEGRATION_UNAVAILABLE", "INTEGRATION_UNAVAILABLE", integration=integ.get("code")))
    return Verified(row, specs)


def _denied_anchor(ctx: AuthContext, investigation_id: UUID, at: datetime, missing: str) -> None:
    """The DENIED `agent_run` a refused approval leaves (spec 6.6-6), like a refused turn."""
    assert ctx.tenant_id is not None
    try:
        agent_run_repo.insert_run(
            ctx.tenant_id, agent_id="CEO", trigger_type="CONVERSATIONAL", trigger_ref="ceo.approved_plan", requested_by=ctx.app_user_id, permission_check=f"DENIED:{missing}",
            entitlement_check="NOT_EVALUATED", status="DENIED", started_at=at, finished_at=at, error_reason=f"missing: {missing}", investigation_id=investigation_id, inherit_parent=False,
        )
    except Exception:  # noqa: BLE001
        logger.exception("could not record the denied approval")


# ------------------------------------------------------------------------------------------------ reads (lazy expiry) and decline
def read_plan(tenant_id: UUID, investigation_id: UUID, plan_id: UUID, *, now: datetime) -> dict[str, Any] | None:
    """The plan as the seller sees it, with the expiry persisted lazily (an AWAITING_APPROVAL plan past `expires_at` becomes EXPIRED with its SYSTEM event first)."""
    row = plan_repo.get(tenant_id, investigation_id, plan_id)
    if row is not None and row["status"] == "AWAITING_APPROVAL" and now >= row["expires_at"]:
        plan_repo.expire_if_due(tenant_id, plan_id, now=now)
        row = plan_repo.get(tenant_id, investigation_id, plan_id)
    return row


def read_plans(tenant_id: UUID, investigation_id: UUID, *, now: datetime) -> list[dict[str, Any]]:
    for row in plan_repo.list_for_investigation(tenant_id, investigation_id):
        if row["status"] == "AWAITING_APPROVAL" and now >= row["expires_at"]:
            plan_repo.expire_if_due(tenant_id, row["id"], now=now)
    return plan_repo.list_for_investigation(tenant_id, investigation_id)


def decline_plan(ctx: AuthContext, runtime: CeoRuntime, investigation_id: UUID, plan_id: UUID, reason: str | None, *, now: datetime) -> dict[str, Any]:
    """AWAITING_APPROVAL -> DECLINED by the requester. No model call, no CEO unit. Raises `ApprovalRefused`; returns the plan row."""
    assert ctx.tenant_id is not None
    tenant, user = ctx.tenant_id, ctx.app_user_id
    inv = inv_repo.get_investigation(tenant, investigation_id)
    row = read_plan(tenant, investigation_id, plan_id, now=now) if inv is not None else None
    if row is None:
        raise ApprovalRefused(404, "NOT_FOUND", "PLAN_NOT_FOUND")
    if row["requested_by"] != user:
        raise _refuse(tenant, plan_id, user, ApprovalRefused(403, "NOT_REQUESTER", "NOT_REQUESTER"))
    if row["status"] != "AWAITING_APPROVAL":
        raise _refuse(tenant, plan_id, user, ApprovalRefused(409, "PLAN_EXPIRED" if row["status"] == "EXPIRED" else "PLAN_NOT_AWAITING", "NOT_AWAITING", status=row["status"]))
    if not plan_repo.decline(tenant, plan_id=plan_id, investigation_id=investigation_id, user_id=user, reason=reason, note_content=DECLINED_NOTE, now=now):
        current = plan_repo.get(tenant, investigation_id, plan_id) or row  # lost the race: the winner's status is reported
        raise ApprovalRefused(409, "PLAN_NOT_AWAITING", "LOST_RACE", status=current["status"])
    return plan_repo.get(tenant, investigation_id, plan_id) or row
