"""The entitlement chokepoint — auth.md §7.2's second gate ("has this tenant purchased/is
entitled to use this agent, and is there room left?"), kept distinct from `agent.*`
permission (`auth/permissions.py`), exactly as §7.2 requires.

**CI (`resolve_ci_entitlement`) stays a TEMPORARY, always-pass scaffold.** No CI entitlement
spec exists yet (`auth.md` line 5: "entitlement spec (not yet written)"), and every numeric
limit anyone has mentioned for CI — 25 URLs / 100 runs per month
(`competitor-intelligence-agent.md` §12 Q3) — is explicitly flagged **provisional and
unlocked**. Implementing any of those numbers as a real deny threshold would be inventing a
business rule this codebase has not actually decided. What this module DOES do, instead of
leaving `entitlement_check` a bare hardcoded string: compute the tenant's REAL current CI
usage (from already-persisted data, not a stub number) and route every call through one named
function.

**CFO (`resolve_cfo_entitlement`) is REAL, F2 of the entitlement roadmap** — rewritten against
`docs/specs/entitlement.md` (§5 data model, §5.5 `EntitlementResult` contract, §6 core rules)
now that that spec exists and is approved. It is no longer a hardcoded always-`passed=True`
scaffold: it resolves a real `meter_code` (`metered_event_meter_map`, falling back to the
`direct_action_code` itself per E5), computes a real tenant-timezone `period_key` (A1/rule 8),
resolves a real `entitlement_cap_config` row (tenant override beats platform default, latest
`effective_from` wins — rule 2), and only *then* evaluates pass/deny by comparison. **Nothing
about the outcome changes today** — no row in any of these tables is seeded by this rewrite's
own migration (`backend/migrations/versions/20260925_0004_entitlement_tables.py`), so every
real call still resolves `cap_value=None`/`evaluation_basis=NO_CAP_CONFIGURED`/`passed=True`,
exactly as documented at entitlement.md §5.5: "F2's rewrite changes nothing about outcome
until the first non-null cap_value is seeded... it only changes the mechanism."

**Explicitly NOT implemented here (out of scope for F2, see entitlement.md's critical
constraint / E6):** `tenant_cart_item` (`NO_ACTIVE_CART_ITEM`) enforcement. No tenant —
existing or new — has a `tenant_cart_item` row today (`tenant_repo.create()` writes none, and
onboarding is not touched by this change), so enforcing that check now would deny CFO for
every tenant. `entitlement_repo.active_cart_item()` exists and is tested in isolation, but is
not called from `resolve_cfo_entitlement` yet — a missing cart item is treated the same as an
unset cap: not yet enforced, not a denial.

**PI (`resolve_pi_entitlement`) reuses `resolve_cfo_entitlement`'s real F2 mechanism
directly** (PI build plan §3) — `resolve_cfo_entitlement` was already generic (its
`agent_code` parameter defaults to `"CFO"` but is never hardcoded inside the function body),
so `resolve_pi_entitlement` is a thin, same-shape wrapper passing `agent_code="PI"` and a
PI-scoped `direct_action_code` (e.g. `"pi.discover"`, `"pi.supplier_lookup"`) through
unchanged. Exactly like CFO, nothing about the outcome changes until a real
`entitlement_cap_config` row is seeded for `agent_code="PI"` — every call today resolves
`NO_CAP_CONFIGURED`/`passed=True`.

**CMO (`resolve_cmo_entitlement`) and its shared trend meter (`resolve_market_trends_entitlement`)
reuse the same real F2 mechanism** (`docs/specs/slim-cmo-agent.md` §8, `entitlement.md` A3) —
deliberately NOT the always-pass scaffold `resolve_gst_lookup_entitlement` /
`resolve_niche_run_entitlement` use. Nothing about the outcome changes until a cap row is seeded
(`NO_CAP_CONFIGURED`/`passed=True`, stated honestly), but once one is, it binds. That is only
meaningful because CMO is also the first agent to WRITE `metered_event` rows after delivery:
`record_metered_event` below. (Before it, only tests wrote them, so no cap could ever have
bound.)

**`research.niche_run` (`resolve_niche_run_entitlement`) is PI's addition and stays a
TEMPORARY, always-pass scaffold, for the identical reason `resolve_gst_lookup_entitlement`
does.** `product-intelligence-agent.md`/the PI build plan require this shared-service action
(consuming Tavily/YouTube's own account-wide free-tier quota) to be metered against its
**own** cap, independently of `resolve_pi_entitlement`'s `agent.pi` cap — but no entitlement
spec has ever assigned `research.niche_run` a real numeric limit. What this function DOES do,
instead of a bare hardcoded `passed=True`: compute the tenant's REAL current
`pi_research_run` usage (`product_intelligence.repositories.pi_research_run_repo.
count_runs_for_tenant`, live-queried, not a stub) — the identical "real usage, no fabricated
cap" precedent `resolve_gst_lookup_entitlement`'s `gst_lookup_count` already established.

**`service.gst_lookup` (`resolve_gst_lookup_entitlement`) is G3's addition and stays a
TEMPORARY, always-pass scaffold, for the identical reason `resolve_ci_entitlement` does.**
`cfo-agent.md` §6.8's `cfo.gst_lookup` row and AC17b/T31 require this shared-service action to
be metered against its **own** OP9 cap, independently of `resolve_cfo_entitlement`'s `agent.cfo`
cap — but no entitlement spec has ever assigned OP9 a real numeric limit (identical status to
CI's 25-URLs/100-runs figures: mentioned in prose, never confirmed as a real product decision).
Implementing a hardcoded deny threshold here would be inventing a business rule nobody has
actually decided, exactly the mistake `resolve_ci_entitlement`'s own docstring already warns
against. What this function DOES do, instead of a bare hardcoded `passed=True`: compute the
tenant's REAL current `gst_lookup_result` usage (`calc_engine.repositories.gst_lookup_repo.
count_for_tenant`, live-queried, not a stub) — mirroring `active_competitor_urls`'s own "real,
live-queried usage" precedent exactly — so a future cap can be compared against actual numbers
from day one rather than needing its own telemetry added later.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import text

from calc_engine.repositories import gst_lookup_repo
from competitor_intelligence.repositories import competitor_url_repo

from backend.db import engine
from backend.repositories import entitlement_repo

logger = logging.getLogger(__name__)

_GET_TENANT_TIMEZONE_SQL = "SELECT timezone FROM tenant WHERE id = :tenant_id"

# entitlement.md A1: tenant.timezone defaults to Asia/Kolkata (auth.md §5.1) — used here as
# the fallback when a tenant row can't be found or carries no timezone, never as a silent
# substitute for a real lookup.
_DEFAULT_TENANT_TIMEZONE = "Asia/Kolkata"


@dataclass(frozen=True, slots=True)
class CiEntitlementResult:
    passed: bool
    reason: str | None
    active_competitor_urls: int


def resolve_ci_entitlement(tenant_id: UUID) -> CiEntitlementResult:
    """Always passes today — see module docstring for why a deny path isn't implemented
    yet. `active_competitor_urls` is real, live-queried usage, so a future cap can be
    compared against actual numbers from day one rather than needing its own telemetry
    added later."""
    active = competitor_url_repo.count_active(tenant_id)
    return CiEntitlementResult(passed=True, reason=None, active_competitor_urls=active)


def entitlement_check_value(result: CiEntitlementResult) -> str:
    """Maps to `agent_run.entitlement_check`'s existing `PASS | DENIED` column contract
    (`backend/migrations/versions/20260917_0002_orchestration_tables.py`)."""
    return "PASS" if result.passed else "DENIED"


@dataclass(frozen=True, slots=True)
class GstLookupEntitlementResult:
    """`resolve_gst_lookup_entitlement`'s own result shape — deliberately mirrors
    `CiEntitlementResult`'s `passed: bool` + real usage-count shape (not `EntitlementResult`'s
    heavier §5.5 contract, which resolves a real `meter_code`/`period_key`/`entitlement_cap_
    config` row via `entitlement_repo` — no such resolution exists for `service.gst_lookup`
    today, and inventing one would be exactly the "fabricated cap" this scaffold's docstring
    warns against). `gst_lookup_count` is real, live-queried usage, not a stub number."""

    passed: bool
    reason: str | None
    gst_lookup_count: int


def resolve_gst_lookup_entitlement(tenant_id: UUID) -> GstLookupEntitlementResult:
    """Always passes today — see this module's docstring for why `service.gst_lookup`'s OP9
    shared-service cap has no real numeric limit to enforce yet, and why that is a deliberate,
    documented scaffold rather than an oversight. `gst_lookup_count` is real, live-queried
    usage (`calc_engine.repositories.gst_lookup_repo.count_for_tenant`), so a future cap can be
    compared against actual numbers from day one rather than needing its own telemetry added
    later — the identical reasoning `resolve_ci_entitlement`'s `active_competitor_urls` already
    established for CI."""
    count = gst_lookup_repo.count_for_tenant(tenant_id)
    return GstLookupEntitlementResult(passed=True, reason=None, gst_lookup_count=count)


def gst_lookup_entitlement_check_value(result: GstLookupEntitlementResult) -> str:
    """Maps to `agent_run.entitlement_check`'s existing `PASS | DENIED` column contract, same
    as `entitlement_check_value`/`cfo_entitlement_check_value` above."""
    return "PASS" if result.passed else "DENIED"


@dataclass(frozen=True, slots=True)
class EntitlementResult:
    """docs/specs/entitlement.md §5.5's exact result contract — the shape
    `resolve_cfo_entitlement` (and any future `resolve_pi_entitlement`/
    `resolve_cmo_entitlement`) is rewritten against at F2."""

    passed: bool
    reason: str | None
    meter_code: str
    usage_count: int
    cap_value: int | None
    evaluation_basis: str  # NO_CAP_CONFIGURED | UNDER_CAP | OVER_CAP
    denial_rendering: str  # ERROR | REDUCED_PAYLOAD
    reduced_payload_action_code: str | None
    period_key: str


def _tenant_timezone(tenant_id: UUID) -> str:
    """`tenant` carries no `tenant_id` column and gets no RLS policy (it IS the identity
    root — same reasoning as `tenant_repo.py`), so this goes through the plain engine, never
    `tenant_scope()`. Falls back to the documented platform default (A1) if the tenant row is
    somehow missing or its `timezone` column is empty — never raises, since a missing
    timezone must not block the entitlement chokepoint itself."""
    with engine().connect() as conn:
        row = conn.execute(text(_GET_TENANT_TIMEZONE_SQL), {"tenant_id": str(tenant_id)}).first()
    if row is not None and row[0]:
        return str(row[0])
    return _DEFAULT_TENANT_TIMEZONE


def _period_key(occurred_at: datetime, *, tz_name: str, period_unit: str) -> str:
    """Tenant-timezone calendar bucket (A1/rule 8). `period_key` is computed once, at
    evaluation/write time, never lazily re-derived later (rule 8's "never silently
    reinterprets historical events"). `period_unit` here is a documented, conservative
    design choice for F2's own use, since no capability_entitlement_rule/entitlement_cap_
    config row is seeded to supply a real one today: MONTH is the default bucket
    (`YYYY-MM`) used for the result's own `period_key` and for usage aggregation unless a
    resolved cap names DAY (`YYYY-MM-DD`) or RUN_LIFETIME (a constant, non-resetting
    bucket) instead. Uses the standard-library `zoneinfo` — no bespoke timezone-conversion
    logic is written here, only the bucket-formatting choice above it."""
    try:
        local = occurred_at.astimezone(ZoneInfo(tz_name))
    except Exception:
        local = occurred_at.astimezone(ZoneInfo(_DEFAULT_TENANT_TIMEZONE))

    if period_unit == "DAY":
        return local.strftime("%Y-%m-%d")
    if period_unit == "RUN_LIFETIME":
        return "LIFETIME"
    return local.strftime("%Y-%m")


def resolve_cfo_entitlement(
    tenant_id: UUID,
    *,
    direct_action_code: str,
    agent_code: str = "CFO",
    occurred_at: datetime | None = None,
    as_of_date: date | None = None,
) -> EntitlementResult:
    """The real, F2 rewrite of the CFO entitlement chokepoint — see module docstring for the
    full "what changed, what didn't" explanation. `direct_action_code` is the trigger id the
    calling dispatch function actually performed (e.g. `"cfo.pricing"`, `"cfo.reconcile"` —
    `agents/ceo_hub.py`'s own `CFO_*` constants, reused verbatim by every call site); it is
    never chosen or guessed by this function.

    Resolution order (entitlement.md §6):
    1. `meter_code` — `metered_event_meter_map`, tenant override beats platform default,
       falling back to `direct_action_code` itself if no row exists at all (E5, "never
       dropped").
    2. `period_key` — tenant-timezone calendar bucket (A1/rule 8), defaulted to a MONTH
       bucket unless a resolved cap names a different `period_unit` (see `_period_key`).
    3. `entitlement_cap_config` — tenant override beats platform default. No row today
       (nothing seeded) means `cap_value=None`, `evaluation_basis=NO_CAP_CONFIGURED`,
       `passed=True` — E1/§5.5's exact, honest, real state. A resolved row with a non-null
       `cap_value` is compared against a real, live-aggregated `usage_count`
       (`entitlement_repo.usage_count_for_period`) — `UNDER_CAP`/pass or `OVER_CAP`/deny.
    4. `capability_entitlement_rule` — resolves `denial_rendering`/
       `reduced_payload_action_code`. No row (or an unrecognised `denial_rendering` value)
       means the column's own default, `"ERROR"` (rule 9).

    Deliberately does NOT resolve/enforce `tenant_cart_item` (E6's `NO_ACTIVE_CART_ITEM`) —
    see module docstring for why.
    """
    now = occurred_at or datetime.now(timezone.utc)
    resolved_as_of_date = as_of_date or now.date()

    meter_map_row = entitlement_repo.resolve_meter_map(
        tenant_id, event_kind=direct_action_code, as_of_date=resolved_as_of_date
    )
    meter_code = str(meter_map_row["meter_code"]) if meter_map_row is not None else direct_action_code

    tz_name = _tenant_timezone(tenant_id)
    period_key = _period_key(now, tz_name=tz_name, period_unit="MONTH")

    cap_row = entitlement_repo.resolve_cap_config(
        tenant_id,
        agent_code=agent_code,
        meter_code=meter_code,
        scope="TENANT",
        as_of_date=resolved_as_of_date,
    )

    cap_value: int | None = None
    usage_count = 0
    evaluation_basis = "NO_CAP_CONFIGURED"
    passed = True
    reason: str | None = None

    if cap_row is not None and cap_row.get("cap_value") is not None:
        cap_value = int(cap_row["cap_value"])
        period_unit = str(cap_row.get("period_unit") or "MONTH")
        if period_unit != "MONTH":
            period_key = _period_key(now, tz_name=tz_name, period_unit=period_unit)

        usage_count = entitlement_repo.usage_count_for_period(
            tenant_id, agent_code=agent_code, meter_code=meter_code, period_key=period_key
        )

        if usage_count >= cap_value:
            evaluation_basis = "OVER_CAP"
            passed = False
            reason = "OVER_CAP"
        else:
            evaluation_basis = "UNDER_CAP"
            passed = True

    rule_row = entitlement_repo.resolve_capability_rule(
        tenant_id, agent_code=agent_code, direct_action_code=direct_action_code, as_of_date=resolved_as_of_date
    )
    denial_rendering = str(rule_row["denial_rendering"]) if rule_row is not None else "ERROR"
    if denial_rendering not in ("ERROR", "REDUCED_PAYLOAD"):
        denial_rendering = "ERROR"
    reduced_payload_action_code = (
        str(rule_row["reduced_payload_action_code"])
        if rule_row is not None and rule_row.get("reduced_payload_action_code") is not None
        else None
    )
    if denial_rendering != "REDUCED_PAYLOAD":
        reduced_payload_action_code = None

    return EntitlementResult(
        passed=passed,
        reason=reason,
        meter_code=meter_code,
        usage_count=usage_count,
        cap_value=cap_value,
        evaluation_basis=evaluation_basis,
        denial_rendering=denial_rendering,
        reduced_payload_action_code=reduced_payload_action_code,
        period_key=period_key,
    )


def cfo_entitlement_check_value(result: EntitlementResult) -> str:
    """Maps to `agent_run.entitlement_check`'s existing `PASS | DENIED` column contract."""
    return "PASS" if result.passed else "DENIED"


def resolve_pi_entitlement(
    tenant_id: UUID,
    *,
    direct_action_code: str,
    agent_code: str = "PI",
    occurred_at: datetime | None = None,
    as_of_date: date | None = None,
) -> EntitlementResult:
    """PI's F2 entitlement chokepoint — see module docstring for why this is a thin wrapper
    over `resolve_cfo_entitlement`'s already-generic implementation, not a reimplementation."""
    return resolve_cfo_entitlement(
        tenant_id,
        direct_action_code=direct_action_code,
        agent_code=agent_code,
        occurred_at=occurred_at,
        as_of_date=as_of_date,
    )


# --- Slim CMO (docs/specs/slim-cmo-agent.md §8, entitlement.md A3) -------------------------

# The shared Market Signal Retrieval service meters under agent_code SHARED with its own
# meter_code — independently of CMO's own cap (OP9; entitlement.md rule 7, A3).
MARKET_TRENDS_AGENT_CODE = "SHARED"
MARKET_TRENDS_EVENT_KIND = "research.market_trends"


def resolve_cmo_entitlement(
    tenant_id: UUID,
    *,
    direct_action_code: str,
    agent_code: str = "CMO",
    occurred_at: datetime | None = None,
    as_of_date: date | None = None,
) -> EntitlementResult:
    """CMO's entitlement chokepoint: a thin wrapper over `resolve_cfo_entitlement`'s already
    generic mechanism (PI precedent). `direct_action_code` is the CMO trigger id actually
    being performed (`cmo.generate_title_sets`, `cmo.generate_listing_copy`, ...). The
    multi-artefact up-front pre-check (spec §8.4) is built on this in P5; it is not part of
    this resolver."""
    return resolve_cfo_entitlement(
        tenant_id,
        direct_action_code=direct_action_code,
        agent_code=agent_code,
        occurred_at=occurred_at,
        as_of_date=as_of_date,
    )


def resolve_market_trends_entitlement(
    tenant_id: UUID,
    *,
    occurred_at: datetime | None = None,
    as_of_date: date | None = None,
) -> EntitlementResult:
    """The shared `research.market_trends` meter — second of the two independent meters a
    trend report is checked against (spec §6.8.9). Real F2 resolution under `agent_code =
    "SHARED"`, so seeding a cap for it later needs no code change."""
    return resolve_cfo_entitlement(
        tenant_id,
        direct_action_code=MARKET_TRENDS_EVENT_KIND,
        agent_code=MARKET_TRENDS_AGENT_CODE,
        occurred_at=occurred_at,
        as_of_date=as_of_date,
    )


# --- CEO (ceo-agent-orchestration.md D5, §8 rule 3, E7) --------------------------------------
CEO_AGENT_CODE = "CEO"
CEO_TURN_EVENT_KIND = "ceo.chat_turn"


def resolve_ceo_entitlement(
    tenant_id: UUID,
    *,
    occurred_at: datetime | None = None,
    as_of_date: date | None = None,
) -> EntitlementResult:
    """The CEO's own cap check — one conversational turn is one unit (D5), checked BEFORE classification
    runs at all (§8 rule 3, E7). A thin wrapper over the same real F2 mechanism CFO/PI/CMO use, so seeding
    a `CEO` / `ceo.chat_turn` cap needs no code change. Nothing is seeded: until a cap row exists every call
    resolves `NO_CAP_CONFIGURED`/`passed=True`, stated honestly (the 30/month figure is provisional config,
    never a hardcoded threshold here). System/proactive runs never call this: they consume no seller
    conversation unit (CP1-D5)."""
    return resolve_cfo_entitlement(
        tenant_id,
        direct_action_code=CEO_TURN_EVENT_KIND,
        agent_code=CEO_AGENT_CODE,
        occurred_at=occurred_at,
        as_of_date=as_of_date,
    )


def ceo_turn_metering_key(turn_id: UUID) -> str:
    """`metered_event.idempotency_key` is unique per tenant across ALL agents, so the CEO's keys are namespaced."""
    return f"ceo:turn:{turn_id}"


def meter_ceo_turn(
    tenant_id: UUID,
    *,
    member_id: UUID,
    turn_id: UUID,
    agent_run_id: UUID | None = None,
    occurred_at: datetime | None = None,
) -> UUID | None:
    """Records the one unit a delivered seller turn consumes (D5), idempotently per turn. Best-effort like every
    metering write (D4): a failure never blocks the answer the seller already received."""
    return record_metered_event(
        tenant_id,
        agent_code=CEO_AGENT_CODE,
        event_kind=CEO_TURN_EVENT_KIND,
        idempotency_key=ceo_turn_metering_key(turn_id),
        member_id=member_id,
        quantity=1,
        agent_run_id=agent_run_id,
        source_ref=turn_id,
        occurred_at=occurred_at,
    )


def cmo_metering_key(generation_id: UUID) -> str:
    """`metered_event.idempotency_key` is unique per tenant across ALL agents, so CMO's keys are
    namespaced. One delivered artefact (`cmo_generation.id`) is exactly one unit; re-recording
    the same artefact is a no-op (entitlement.md rule 4)."""
    return f"cmo:{generation_id}"


def record_metered_event(
    tenant_id: UUID,
    *,
    agent_code: str,
    event_kind: str,
    idempotency_key: str,
    member_id: UUID | None = None,
    quantity: int = 1,
    agent_run_id: UUID | None = None,
    source_ref: UUID | None = None,
    occurred_at: datetime | None = None,
    as_of_date: date | None = None,
) -> UUID | None:
    """Record one unit of usage AFTER an action reached a terminal state (entitlement.md rule 3).

    Best-effort by design (D4, rule 5): a failure here is logged and swallowed — it must never
    block or roll back a result the seller already received. Returns the stored event id (the
    ORIGINAL id on an idempotent retry), or `None` if the write failed and needs out-of-band
    reconciliation. The entitlement CHECK (read path, before the action) is the opposite: it
    fails closed. Callers decide which terminal states consume a unit (D5) — CMO records only
    `COMPLETE` artefacts — and never call this for a failed one.

    `meter_code` is never chosen by the caller (rule 6): it is resolved through
    `metered_event_meter_map` here, falling back to `event_kind` itself (E5). `period_key` uses
    the same unit the live cap check uses (the resolved cap's `period_unit`, else MONTH), so
    recorded usage and the entitlement check always count the same bucket.
    """
    try:
        now = occurred_at or datetime.now(timezone.utc)
        resolved_as_of = as_of_date or now.date()

        meter_row = entitlement_repo.resolve_meter_map(tenant_id, event_kind=event_kind, as_of_date=resolved_as_of)
        meter_code = str(meter_row["meter_code"]) if meter_row is not None else event_kind

        cap_row = entitlement_repo.resolve_cap_config(
            tenant_id, agent_code=agent_code, meter_code=meter_code, scope="TENANT", as_of_date=resolved_as_of
        )
        period_unit = str(cap_row.get("period_unit") or "MONTH") if cap_row is not None else "MONTH"
        period_key = _period_key(now, tz_name=_tenant_timezone(tenant_id), period_unit=period_unit)

        return entitlement_repo.insert_metered_event(
            tenant_id,
            member_id=member_id,
            agent_code=agent_code,
            event_kind=event_kind,
            meter_code=meter_code,
            quantity=quantity,
            agent_run_id=agent_run_id,
            source_ref=source_ref,
            idempotency_key=idempotency_key,
            occurred_at=now,
            period_key=period_key,
        )
    except Exception:  # noqa: BLE001 - metering must degrade gracefully, never block delivery (D4)
        logger.exception(
            "metered_event write failed; needs reconciliation (tenant=%s agent=%s kind=%s key=%s)",
            tenant_id, agent_code, event_kind, idempotency_key,
        )
        return None


@dataclass(frozen=True, slots=True)
class NicheRunEntitlementResult:
    """`resolve_niche_run_entitlement`'s own result shape — mirrors `GstLookupEntitlementResult`
    exactly (see module docstring): a `passed: bool` + real usage-count shape, not
    `EntitlementResult`'s heavier §5.5 contract, since no `research.niche_run` cap resolution
    exists today."""

    passed: bool
    reason: str | None
    niche_run_count: int  # UNCHANGED MEANING: every run ever STARTED (rows), kept for its existing consumers. It is NOT usage and NOT used for enforcement.
    # Q-R3 / R3: usage and enforcement count SUCCESSFUL runs only (recorded `research.niche_run` events); operational counts are kept separately.
    niche_runs_successful: int = 0  # all-time runs whose stored decision says they were billable
    usage_count: int = 0  # recorded research.niche_run events in the current period (what a cap is compared against)
    cap_value: int | None = None
    meter_code: str = "research.niche_run"
    period_key: str = ""
    evaluation_basis: str = "NO_CAP_CONFIGURED"


NICHE_RUN_AGENT_CODE = "SHARED"
NICHE_RUN_EVENT_KIND = "research.niche_run"


def resolve_niche_run_entitlement(tenant_id: UUID) -> NicheRunEntitlementResult:
    """The shared `research.niche_run` meter, resolved through the same real F2 mechanism as `research.market_trends` (agent `SHARED`), so a cap can
    be seeded without a code change. With no cap row (today) it passes, stated honestly as `NO_CAP_CONFIGURED`. **Only SUCCESSFUL runs count toward usage**
    (events written by `services/pi_usage`); the started/failed/interrupted operational counts are separate and never feed enforcement.
    A cap must not be seeded before PI's quota reservation (R6) is proven: until then it is not safely enforceable (see `services/pi_usage`)."""
    from product_intelligence.repositories import pi_research_run_repo

    base = resolve_cfo_entitlement(tenant_id, direct_action_code=NICHE_RUN_EVENT_KIND, agent_code=NICHE_RUN_AGENT_CODE)
    counts = pi_research_run_repo.operational_counts(tenant_id)
    return NicheRunEntitlementResult(
        passed=base.passed, reason=base.reason, niche_run_count=counts["started"], niche_runs_successful=counts["successful"],
        usage_count=entitlement_repo.usage_count_for_period(tenant_id, agent_code=NICHE_RUN_AGENT_CODE, meter_code=base.meter_code, period_key=base.period_key),
        cap_value=base.cap_value, meter_code=base.meter_code, period_key=base.period_key,
        evaluation_basis=base.evaluation_basis,
    )


def niche_run_entitlement_check_value(result: NicheRunEntitlementResult) -> str:
    """Maps to `agent_run.entitlement_check`'s existing `PASS | DENIED` column contract, same
    as `entitlement_check_value`/`gst_lookup_entitlement_check_value` above."""
    return "PASS" if result.passed else "DENIED"


class EntitlementDenied(Exception):
    """F3 of the entitlement roadmap — the real enforcement signal `resolve_cfo_entitlement`'s
    result (F2) was computed for but nothing previously acted on. Raised by `agents.ceo_hub`'s
    `dispatch_cfo_*` functions when `result.passed` is `False`, carrying the full
    `EntitlementResult` so the caller (a FastAPI route, or `api/v1/cfo.py` directly) can render
    the correct denial without re-deriving it. Deliberately a plain Python exception, not an
    `HTTPException` — this module is a service-layer chokepoint, not a FastAPI route, and must
    not import FastAPI. The route layer is responsible for converting this into the actual HTTP
    response (see `api/v1/cfo.py`)."""

    def __init__(self, result: EntitlementResult) -> None:
        self.result = result
        super().__init__(result.reason or "entitlement denied")
