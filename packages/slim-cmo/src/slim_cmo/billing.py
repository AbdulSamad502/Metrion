"""Billing arithmetic and idempotency rules (spec §8, §8.1.1, §8.3, §8.4, AC8, AC15, AC16, AC17).

Pure functions over integers and enums - no database, no clock, no model. A later phase wires
these to the entitlement chokepoint and the repositories; the RULES live here so they are
testable in isolation and cannot drift between routes.

What is decided here (all from the approved spec, nothing invented):

* **One artefact delivered = one unit.** A five-option title set for one marketplace is one
  artefact; three marketplaces are three. The listing copy pack is one artefact per
  marketplace. Everything else in §8.1.1 is one unit per artefact. Approval, niche-term
  suggestion/confirmation and hint confirmation are zero.
* **Only `COMPLETE` consumes a unit.** `FAILED` never does (§8.3).
* **Idempotency scope** is `(request_key, output_type, marketplace)`. A COMPLETE artefact under
  that key is *reused* - same row, no second row, no second unit. FAILED attempts under the
  key are ignored, so a retry runs again. A different request key is a new artefact (that is
  what "regeneration" is).
* **All-or-nothing pre-check (§8.4).** The whole request's unit count is checked against the
  remaining allowance BEFORE anything runs. Reused artefacts are free and are excluded from the
  count. If the allowance is short the entire request is denied - no partial run to "use up"
  the remainder.
* **A trend report is checked against two independent meters** (CMO and the shared
  `research.market_trends` meter); either denying denies the report, and the answer says which.

Cap values are never read or assumed here: callers pass `cap=None` for "no cap configured"
(which passes - stated honestly, entitlement.md E1) or the configured integer.

Not decided here, deliberately (reported as an open P5 design requirement): the *concurrency*
of check-then-record. This module computes the answer for a given usage snapshot; making the
snapshot trustworthy under simultaneous requests is a serialisation concern for the route
layer (independent verification showed 7 of 8 simultaneous requests passing a cap of 1).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import Enum
from uuid import UUID

from slim_cmo.types import (
    MARKETPLACE_SCOPED_OUTPUT_TYPES,
    GenerationStatus,
    Marketplace,
    OutputType,
)

# --------------------------------------------------------------------------------------------
# the unit table (spec §8.1.1) - pinned verbatim by tests
# --------------------------------------------------------------------------------------------

UNITS_PER_ARTEFACT: dict[OutputType, int] = {t: 1 for t in OutputType}


class Action(str, Enum):
    """Every registered CMO action (spec §8.1). Values are the trigger ids and double as the
    `metered_event.event_kind` for the artefact-producing ones."""

    GENERATE_TITLE_SETS = "cmo.generate_title_sets"
    APPROVE_TITLE = "cmo.approve_title"
    GENERATE_LISTING_COPY = "cmo.generate_listing_copy"
    GENERATE_DESCRIPTION = "cmo.generate_description"
    GENERATE_BULLETS = "cmo.generate_bullets"
    GENERATE_KEYWORDS = "cmo.generate_keywords"
    GENERATE_BACKEND_TERMS = "cmo.generate_backend_terms"
    GENERATE_HASHTAGS = "cmo.generate_hashtags"
    CATALOG_ANSWER = "cmo.catalog_answer"
    SUGGEST_NICHE_TERMS = "cmo.suggest_niche_terms"
    CONFIRM_NICHE_TERMS = "cmo.confirm_niche_terms"
    CONFIRM_IMAGE_HINT = "cmo.confirm_image_hint"
    MARKET_TRENDS = "cmo.market_trends"


ACTION_OUTPUT_TYPE: dict[Action, OutputType | None] = {
    Action.GENERATE_TITLE_SETS: OutputType.TITLE_SET,
    Action.APPROVE_TITLE: None,
    Action.GENERATE_LISTING_COPY: OutputType.LISTING_COPY,
    Action.GENERATE_DESCRIPTION: OutputType.DESCRIPTION,
    Action.GENERATE_BULLETS: OutputType.BULLETS,
    Action.GENERATE_KEYWORDS: OutputType.KEYWORDS,
    Action.GENERATE_BACKEND_TERMS: OutputType.BACKEND_TERMS,
    Action.GENERATE_HASHTAGS: OutputType.HASHTAGS,
    Action.CATALOG_ANSWER: OutputType.CATALOG_ANSWER,
    Action.SUGGEST_NICHE_TERMS: None,
    Action.CONFIRM_NICHE_TERMS: None,
    Action.CONFIRM_IMAGE_HINT: None,
    Action.MARKET_TRENDS: OutputType.TREND_REPORT,
}

ZERO_UNIT_ACTIONS: frozenset[Action] = frozenset(a for a, t in ACTION_OUTPUT_TYPE.items() if t is None)

# metered_event.event_kind per artefact type; the shared trend meter is separate (entitlement.md A3)
EVENT_KIND_BY_OUTPUT_TYPE: dict[OutputType, str] = {
    t: action.value for action, t in ACTION_OUTPUT_TYPE.items() if t is not None
}
SHARED_TRENDS_EVENT_KIND = "research.market_trends"


def units_for_action(action: Action) -> int:
    """Units ONE successful invocation of the action costs per artefact it produces
    (0 for the no-artefact actions)."""
    output_type = ACTION_OUTPUT_TYPE[action]
    return 0 if output_type is None else UNITS_PER_ARTEFACT[output_type]


# --------------------------------------------------------------------------------------------
# request keys (idempotency identity)
# --------------------------------------------------------------------------------------------

# A technical input bound on a client-supplied identifier (so it cannot be abused to bloat the
# unique index or smuggle control characters) - not a business value. 128 printable-ASCII chars.
MAX_REQUEST_KEY_CHARS = 128
_REQUEST_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:\-]*$")


class RequestError(str, Enum):
    EMPTY_REQUEST = "EMPTY_REQUEST"
    BAD_REQUEST_KEY = "BAD_REQUEST_KEY"
    MARKETPLACE_REQUIRED = "MARKETPLACE_REQUIRED"
    MARKETPLACE_NOT_ALLOWED = "MARKETPLACE_NOT_ALLOWED"
    BACKEND_TERMS_AMAZON_ONLY = "BACKEND_TERMS_AMAZON_ONLY"
    DUPLICATE_ARTEFACT = "DUPLICATE_ARTEFACT"


class InvalidRequest(ValueError):
    def __init__(self, code: RequestError, detail: str = "") -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code.value}: {detail}" if detail else code.value)


def normalise_request_key(raw: object) -> str:
    if not isinstance(raw, str):
        raise InvalidRequest(RequestError.BAD_REQUEST_KEY, "must be a string")
    key = raw.strip()
    if not key or len(key) > MAX_REQUEST_KEY_CHARS or not _REQUEST_KEY_RE.match(key):
        raise InvalidRequest(
            RequestError.BAD_REQUEST_KEY,
            f"1-{MAX_REQUEST_KEY_CHARS} characters of letters, digits and . _ : -; starting with a letter or digit",
        )
    return key


# --------------------------------------------------------------------------------------------
# requests, reuse and the all-or-nothing pre-check
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RequestedArtefact:
    output_type: OutputType
    marketplace: Marketplace | None = None

    @property
    def identity(self) -> tuple[OutputType, Marketplace | None]:
        return (self.output_type, self.marketplace)


def validate_request(items: Sequence[RequestedArtefact]) -> None:
    if not items:
        raise InvalidRequest(RequestError.EMPTY_REQUEST)
    seen: set[tuple[OutputType, Marketplace | None]] = set()
    for item in items:
        t, m = item.output_type, item.marketplace
        if t in MARKETPLACE_SCOPED_OUTPUT_TYPES and m is None:
            raise InvalidRequest(RequestError.MARKETPLACE_REQUIRED, t.value)
        if t is OutputType.TREND_REPORT and m is not None:
            raise InvalidRequest(RequestError.MARKETPLACE_NOT_ALLOWED, t.value)
        if t is OutputType.BACKEND_TERMS and m is not Marketplace.AMAZON:
            raise InvalidRequest(RequestError.BACKEND_TERMS_AMAZON_ONLY, str(m))
        if item.identity in seen:
            raise InvalidRequest(RequestError.DUPLICATE_ARTEFACT, f"{t.value}/{m.value if m else '-'}")
        seen.add(item.identity)


@dataclass(frozen=True, slots=True)
class ExistingArtefact:
    id: UUID
    output_type: OutputType
    marketplace: Marketplace | None
    request_key: str
    status: GenerationStatus


@dataclass(frozen=True, slots=True)
class ReusedArtefact:
    item: RequestedArtefact
    existing_id: UUID


@dataclass(frozen=True, slots=True)
class RequestPlan:
    to_generate: tuple[RequestedArtefact, ...]
    reused: tuple[ReusedArtefact, ...]
    units_required: int  # CMO meter
    shared_units_required: int  # shared research.market_trends meter (trend reports only)


def plan_request(
    items: Sequence[RequestedArtefact],
    *,
    request_key: str,
    existing: Iterable[ExistingArtefact],
) -> RequestPlan:
    """Split a validated request into artefacts that must run and artefacts already delivered
    under this exact key. Only a COMPLETE artefact with the SAME key, type and marketplace is
    reusable; a FAILED one is ignored (the retry runs); a COMPLETE one under a different key is
    ignored (that is a regeneration - a new artefact, a new unit)."""
    validate_request(items)
    key = normalise_request_key(request_key)
    delivered: dict[tuple[OutputType, Marketplace | None], UUID] = {}
    for e in existing:
        if e.request_key == key and e.status is GenerationStatus.COMPLETE:
            delivered.setdefault((e.output_type, e.marketplace), e.id)
    to_generate: list[RequestedArtefact] = []
    reused: list[ReusedArtefact] = []
    for item in items:
        found = delivered.get(item.identity)
        if found is not None:
            reused.append(ReusedArtefact(item, found))
        else:
            to_generate.append(item)
    units = sum(UNITS_PER_ARTEFACT[i.output_type] for i in to_generate)
    shared = sum(1 for i in to_generate if i.output_type is OutputType.TREND_REPORT)
    return RequestPlan(tuple(to_generate), tuple(reused), units, shared)


class CapBasis(str, Enum):
    NOTHING_TO_BILL = "NOTHING_TO_BILL"
    NO_CAP_CONFIGURED = "NO_CAP_CONFIGURED"
    WITHIN_CAP = "WITHIN_CAP"
    OVER_CAP = "OVER_CAP"


@dataclass(frozen=True, slots=True)
class PreCheck:
    allowed: bool
    basis: CapBasis
    requested: int
    usage: int
    cap: int | None
    remaining: int | None  # None = uncapped
    shortfall: int  # units missing for the request to fit (0 when allowed)


def _nonneg_int(value: object, name: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{name} must be a non-negative integer, got {value!r}")
    return value


def precheck(requested: int, *, usage: int, cap: int | None) -> PreCheck:
    """All-or-nothing: the request fits iff `usage + requested <= cap`. `cap=None` means no cap
    is configured, which passes - and is reported as such rather than as a limit. A request that
    needs zero units (everything reused) always passes, even over cap."""
    requested = _nonneg_int(requested, "requested")
    usage = _nonneg_int(usage, "usage")
    if cap is not None:
        cap = _nonneg_int(cap, "cap")
    if requested == 0:
        remaining = None if cap is None else max(cap - usage, 0)
        return PreCheck(True, CapBasis.NOTHING_TO_BILL, 0, usage, cap, remaining, 0)
    if cap is None:
        return PreCheck(True, CapBasis.NO_CAP_CONFIGURED, requested, usage, None, None, 0)
    remaining = max(cap - usage, 0)
    if requested <= remaining:
        return PreCheck(True, CapBasis.WITHIN_CAP, requested, usage, cap, remaining, 0)
    return PreCheck(False, CapBasis.OVER_CAP, requested, usage, cap, remaining, requested - remaining)


class Meter(str, Enum):
    CMO = "CMO"
    SHARED_TRENDS = "SHARED_TRENDS"


@dataclass(frozen=True, slots=True)
class RequestPreCheck:
    allowed: bool
    cmo: PreCheck
    shared: PreCheck | None
    denied_by: tuple[Meter, ...]


def precheck_request(
    plan: RequestPlan,
    *,
    cmo_usage: int,
    cmo_cap: int | None,
    shared_usage: int = 0,
    shared_cap: int | None = None,
) -> RequestPreCheck:
    """Evaluate both independent meters for a planned request. The shared meter is evaluated
    only when the plan contains a trend report. Either denial denies the request; both are
    reported (AC17)."""
    cmo = precheck(plan.units_required, usage=cmo_usage, cap=cmo_cap)
    shared = (
        precheck(plan.shared_units_required, usage=shared_usage, cap=shared_cap)
        if plan.shared_units_required > 0
        else None
    )
    denied = tuple(
        m for m, pc in ((Meter.CMO, cmo), (Meter.SHARED_TRENDS, shared)) if pc is not None and not pc.allowed
    )
    return RequestPreCheck(not denied, cmo, shared, denied)


# --------------------------------------------------------------------------------------------
# settlement after the run
# --------------------------------------------------------------------------------------------


class RunStatus(str, Enum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class ArtefactResult:
    item: RequestedArtefact
    status: GenerationStatus


@dataclass(frozen=True, slots=True)
class Settlement:
    units_billed: int
    shared_units_billed: int
    billed: tuple[RequestedArtefact, ...]
    unbilled: tuple[RequestedArtefact, ...]
    run_status: RunStatus


def settle(results: Sequence[ArtefactResult]) -> Settlement:
    """Units after the run: 1 per COMPLETE artefact, 0 per FAILED (§8.3). The run status is the
    `agent_run.status`: COMPLETE (all delivered), PARTIAL (a mix - the delivered ones are billed,
    the rest reported), FAILED (nothing delivered, nothing billed)."""
    if not results:
        raise ValueError("cannot settle an empty run")
    billed = tuple(r.item for r in results if r.status is GenerationStatus.COMPLETE)
    unbilled = tuple(r.item for r in results if r.status is not GenerationStatus.COMPLETE)
    if not unbilled:
        status = RunStatus.COMPLETE
    elif not billed:
        status = RunStatus.FAILED
    else:
        status = RunStatus.PARTIAL
    return Settlement(
        units_billed=sum(UNITS_PER_ARTEFACT[i.output_type] for i in billed),
        shared_units_billed=sum(1 for i in billed if i.output_type is OutputType.TREND_REPORT),
        billed=billed,
        unbilled=unbilled,
        run_status=status,
    )
