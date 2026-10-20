"""Typed contracts for the CEO layer — spec §5, §6.11, §6.13, §6.15.

Nothing here computes anything. `Figure.formatted_value` is a string produced by a deterministic
formatter from an already-stored number (`figure_format`); there is no numeric field on `Figure`, so
there is nothing for a model to operate on (CLAUDE.md hard rule; `LlmProvider.complete` is text in/text out).

`ActionSpec` deliberately has no `WRITE` effect: a write-class action cannot even be *expressed* in the
V1 registry (spec C21). `registry.FORBIDDEN_ACTION_KEYS` additionally names the excluded actions so a
future change that registers one fails loudly.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from backend.auth.permissions import AGENT_CFO, AGENT_CI, AGENT_CMO, AGENT_PI
from backend.ceo.effects import ActionEffects


class AgentCode(str, Enum):
    """The four attachable specialists (spec §6.22). The CEO is always present and is not attachable."""

    CFO = "CFO"
    CI = "CI"
    PI = "PI"
    CMO = "CMO"


# Turn statuses (`investigation_turn_status_check`). The in-flight statuses are written while a turn runs; the
# terminal ones end it. `PLANNED` is vocabulary only until the approval workflow exists: nothing produces it yet.
# `tests/integration/test_ceo_turn_status_vocabulary.py` fails if these constants and the DB constraint drift apart.
IN_FLIGHT_TURN_STATUSES: tuple[str, ...] = ("RECEIVED", "CAP_CHECKED", "CLASSIFIED", "PLAN_VALIDATED", "DISPATCHED", "GATHERED", "COMPOSED")
TERMINAL_TURN_STATUSES: tuple[str, ...] = ("DELIVERED", "CLARIFIED", "DENIED", "FAILED", "PLANNED")
TURN_STATUSES: tuple[str, ...] = (*IN_FLIGHT_TURN_STATUSES, *TERMINAL_TURN_STATUSES)

AGENT_PERMISSION_KEY: Mapping[AgentCode, str] = {
    AgentCode.CFO: AGENT_CFO,
    AgentCode.CI: AGENT_CI,
    AgentCode.PI: AGENT_PI,
    AgentCode.CMO: AGENT_CMO,
}


class Effect(str, Enum):
    READ = "READ"  # reads persisted data only
    COMPUTE_PERSIST = "COMPUTE_PERSIST"  # deterministic computation that persists a derived result (not a seller input, not a marketplace write)
    GENERATE_METERED = "GENERATE_METERED"  # produces a seller-metered artefact
    RECORD_CHOICE = "RECORD_CHOICE"  # persists the seller's own explicit selection inside a specialist workflow (title approval, niche/image-hint confirmation); not a financial input, not a marketplace write, free


class RefKind(str, Enum):
    ENGINE_RESULT = "ENGINE_RESULT"  # metric_result.id — an engine_result_ref
    ESTIMATE = "ESTIMATE"  # product_feasibility_estimate.id (competitor_estimate is deferred) — an estimate_ref; NEVER interchangeable with the above
    AGENT_REPORT_FIELD = "AGENT_REPORT_FIELD"  # a field on a specialist's persisted structured report; `source` names the owning table
    SELLER_PROVIDED = "SELLER_PROVIDED"  # a stored seller-supplied value (manual_adjustment)


class Register(str, Enum):
    """cfo-agent.md §7.4.7's five registers — never a sixth."""

    VERIFIED = "VERIFIED"
    DERIVED = "DERIVED"
    MANUAL = "MANUAL"
    ESTIMATE = "ESTIMATE"
    UNAVAILABLE = "UNAVAILABLE"


class LegStatus(str, Enum):
    """Mirrors `investigation_finding.status`'s CHECK."""

    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    DENIED = "DENIED"  # permission or attachment refusal
    NOT_ENTITLED = "NOT_ENTITLED"  # entitlement refusal (the agent_run row is DENIED either way — spec R6)
    FAILED = "FAILED"
    UNAVAILABLE = "UNAVAILABLE"


class Denial(str, Enum):
    PERMISSION = "PERMISSION"
    ENTITLEMENT = "ENTITLEMENT"
    NOT_ATTACHED = "NOT_ATTACHED"
    NOT_WIRED = "NOT_WIRED"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"  # approval-required action with no stored approval plan (the workflow does not exist yet): never run


class EntryStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    STALE = "STALE"
    PARTIAL = "PARTIAL"
    UNAVAILABLE = "UNAVAILABLE"
    NOT_ENTITLED = "NOT_ENTITLED"
    NOT_PERMITTED = "NOT_PERMITTED"
    NOT_ATTACHED = "NOT_ATTACHED"


@dataclass(frozen=True, slots=True)
class Ref:
    kind: RefKind
    id: UUID
    source: str | None = None  # REQUIRED for AGENT_REPORT_FIELD (the owning table); None otherwise
    as_of: datetime | None = None

    def __post_init__(self) -> None:
        if self.kind is RefKind.AGENT_REPORT_FIELD and not self.source:
            raise ValueError("an AGENT_REPORT_FIELD ref must name its source table")

    def to_json(self) -> dict[str, str]:
        out = {"kind": self.kind.value, "id": str(self.id)}
        if self.source:
            out["source"] = self.source
        if self.as_of is not None:
            out["as_of"] = self.as_of.isoformat()
        return out

    @staticmethod
    def from_json(raw: Mapping[str, Any]) -> "Ref":
        as_of = raw.get("as_of")
        return Ref(
            kind=RefKind(raw["kind"]),
            id=UUID(str(raw["id"])),
            source=raw.get("source"),
            as_of=datetime.fromisoformat(as_of) if as_of else None,
        )


@dataclass(frozen=True, slots=True)
class Figure:
    """One displayable figure: a pre-formatted STRING plus the provenance it must cite. Every Figure has a ref
    that resolves for the tenant, or it is not a Figure (spec §6.13 hard rule 2) — an absent value is a `Gap`."""

    label: str
    formatted_value: str
    register: Register
    ref: Ref
    as_of: datetime | None = None
    note: str | None = None


@dataclass(frozen=True, slots=True)
class Fact:
    """A textual, non-numeric statement with a basis (seller context, ingestion status). Never used to carry a number
    the seller could mistake for a verified figure — numbers are Figures."""

    label: str
    text: str
    basis: str  # SELLER_PROVIDED | SOURCE_DERIVED
    as_of: datetime | None = None


@dataclass(frozen=True, slots=True)
class Gap:
    code: str
    message: str
    ref_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class Conflict:
    """Two stored values for one quantity that disagree (spec §6.32). Both sides are Figures with refs, so each is verified like any other figure; the block that
    states them is rendered by code (`conflicts.render`), never by the model."""

    kind: str  # C1_METRIC | C2_MANUAL_INPUT
    what: str
    a: Figure
    b: Figure


@dataclass(frozen=True, slots=True)
class BusinessStateEntry:
    key: str
    status: EntryStatus
    as_of: datetime | None = None
    period: str | None = None
    figures: tuple[Figure, ...] = ()
    facts: tuple[Fact, ...] = ()
    gaps: tuple[Gap, ...] = ()
    conflicts: tuple[Conflict, ...] = ()
    preview_hint: str | None = None  # NOT_ENTITLED CFO-class entries point at cfo.preview (spec C17)
    # Content a specialist WROTE for the seller (title, items, note): shown quoted and labelled, never a figure (spec 6.35, R9). Only BS_CMO_CONTENT_LATEST sets it.
    artefacts: tuple[tuple[str, tuple[str, ...], str | None], ...] = ()
    # (registry key, label) actions that could produce a missing result: OFFERED to the seller, never run in this turn (spec 6.13 rule 4, AC26)
    offers: tuple[tuple[str, str], ...] = ()


# ---------------------------------------------------------------------------------- dispatch contracts
@dataclass(frozen=True, slots=True)
class LegContext:
    """What an action's `invoke` may know about the turn it runs in — identifiers only."""

    tenant_id: UUID
    requested_by: UUID
    investigation_id: UUID | None
    turn_run_id: UUID  # the CEO anchor `agent_run` (the leg's parent)
    leg_run_id: UUID | None  # the choke point's own child row, or None when the specialist writes its own
    now: datetime
    business_profile: str | None = None  # the seller's self-declared profile, one short quoted line built by code (business-profile.md D6): context only, never a figure
    business_profile_brief: Mapping[str, Any] | None = None  # the same profile as a short structured record (fixed keys, words only) for the specialist being called


Invoke = Callable[[Any, Any, LegContext], Mapping[str, Any]]  # (validated slots, AuthContext, LegContext) -> structured payload
EntitlementPreflight = Callable[[UUID, datetime], Any]  # -> backend.entitlement.EntitlementResult


@dataclass(frozen=True, slots=True)
class ActionSpec:
    key: str
    source: str  # CFO | PI | CI | CMO | GST_LOOKUP  (the `agent_run.agent_id` / finding source)
    agent: AgentCode | None  # the attachable agent; None for the shared GST service
    effect: Effect
    description: str
    required_permissions: tuple[str, ...] = ()  # IN ADDITION to agent.ceo + the agent's own key
    slot_model: type[BaseModel] | None = None
    invoke: Invoke | None = None  # None => registered but NOT WIRED: unreachable from the catalog, refuses if forced
    entitlement: EntitlementPreflight | None = None  # None => the handler enforces its own entitlement/admission
    fixed_params: Mapping[str, Any] = field(default_factory=dict)  # pinned by the registry (e.g. include_narration=False)
    writes_own_run: bool = False  # the specialist writes its own agent_run (CMO, PI, CI research); the choke point then writes none
    extract_refs: Callable[[Mapping[str, Any]], list[Ref]] | None = None  # None => provenance.default_extract_refs
    denial_surface: bool = False  # cfo.preview: the entitlement-denial surface (spec C17)
    not_wired_reason: str | None = None
    effects: ActionEffects | None = None  # what the action really does outside computation (ceo/effects.py); attached to EVERY action of the default registry

    @property
    def wired(self) -> bool:
        return self.invoke is not None


@dataclass(frozen=True, slots=True)
class LegResult:
    action_key: str
    status: LegStatus
    agent_run_id: UUID | None = None  # the child row the choke point wrote (None when the specialist wrote its own)
    finding_id: UUID | None = None
    payload: Mapping[str, Any] | None = None  # the specialist's structured report, in memory only (R7: refs are what we persist)
    figure_refs: tuple[Ref, ...] = ()
    reason: str | None = None
    denial: Denial | None = None


@dataclass(frozen=True, slots=True)
class ApprovalGrant:
    """Proof, carried by the execution of an APPROVED plan and by nothing else, that the legs named here may run although the registry says they need approval.

    Only `ceo/approval_run.py` constructs one, after the approve transaction committed (status APPROVED, execution turn created); `dispatch()` honours it only for the
    same tenant and only for the action keys frozen in that plan. It authorizes nothing else: permission, attachment and entitlement are still checked per leg."""

    plan_id: UUID
    tenant_id: UUID
    action_keys: frozenset[str]


class UnregisteredAction(KeyError):
    """The key is not in the registry. Raised, never executed — a classifier or UI value outside the closed catalog."""


class InvalidSlots(ValueError):
    """The slots do not match the action's declared model (unknown field, wrong type). Raised before any run row is written."""


class TurnDenied(Exception):
    """The turn itself was refused before any specialist was considered (no `agent.ceo`, or the CEO cap is exhausted)."""

    def __init__(self, reason: str, anchor_run_id: UUID, *, kind: Denial) -> None:
        super().__init__(reason)
        self.reason, self.anchor_run_id, self.kind = reason, anchor_run_id, kind


ZERO_REFS: Sequence[Ref] = ()
