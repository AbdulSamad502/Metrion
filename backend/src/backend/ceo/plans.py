"""The fixed, code-reviewed execution plans B3 can run: single actions and playbooks (spec §6.4, §6.11, §6.12).

Everything the classifier may select lives here and nowhere else. A plan names registry keys and the deterministic function that
builds each leg's slots from already-validated values; the model can fill declared slot TEXT but cannot add, drop, reorder or
parameterise a leg (§6.12 rule 1). Legs are independent: no leg consumes another's output in the same turn (AC4).

B3 supports the actions/playbooks whose slots can be built from seller text alone. The rest of the registry (pricing, landed cost,
supplier ranking, competitor scenarios, PI discovery, CMO writers/trends, ...) needs inputs a chat message cannot supply safely
(quote refs, competitor ids, run ids, candidate prices) and stays reachable only through its direct surface until its own slot
resolution is specified; the classifier prompt says so, and such requests are declined plainly (never mis-routed).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date
from uuid import UUID

from backend.ceo.periods import PeriodUnresolvable, ResolvedPeriod, resolve_period

MARKETPLACES = ("AMAZON", "FLIPKART", "MEESHO")
SLOT_VOCAB: tuple[str, ...] = (
    "period", "compare_period", "marketplace", "sku", "product", "quantity", "amount", "competitor", "niche", "option",
)


@dataclass(frozen=True, slots=True)
class Clarification:
    slot: str  # a SLOT_VOCAB name, or UNCLEAR_REQUEST / WHICH_AGENT
    question: str


@dataclass(frozen=True, slots=True)
class ResolvedSlots:
    tenant_id: UUID
    today: date
    period: ResolvedPeriod | None = None
    marketplace: str | None = None

    def echoes(self) -> tuple[str, ...]:
        out = []
        if self.period is not None:
            out.append(self.period.echo)
        if self.marketplace is not None:
            out.append(f"Marketplace: {self.marketplace.title()}.")
        return tuple(out)


def normalise_marketplace(raw: str | None) -> str | None:
    text = (raw or "").strip().upper()
    return next((m for m in MARKETPLACES if m in text), None)


SLOT_QUESTIONS: Mapping[str, str] = {
    "period": "Which period do you mean? For example a month name (September), 'last month', or a date range like 2026-09-01 to 2026-09-30.",
    "marketplace": "Which marketplace: Amazon, Flipkart or Meesho?",
}


def resolve_slots(raw: Mapping[str, str], required: tuple[str, ...], *, tenant_id: UUID, today: date) -> ResolvedSlots | Clarification:
    """Validates classifier slot TEXT. A missing or unrecognisable required slot is a `Clarification` — nothing is defaulted (E22)."""
    period: ResolvedPeriod | None = None
    marketplace: str | None = None
    if "period" in required:
        try:
            period = resolve_period(raw.get("period"), today=today)
        except PeriodUnresolvable:
            return Clarification("period", SLOT_QUESTIONS["period"])
    if "marketplace" in required:
        marketplace = normalise_marketplace(raw.get("marketplace"))
        if marketplace is None:
            return Clarification("marketplace", SLOT_QUESTIONS["marketplace"])
    return ResolvedSlots(tenant_id=tenant_id, today=today, period=period, marketplace=marketplace)


# ------------------------------------------------------------------------------------------------ slot builders
def _dates(s: ResolvedSlots) -> dict[str, str]:
    assert s.period is not None
    return {"period_start": s.period.start.isoformat(), "period_end": s.period.end.isoformat(), "as_of_date": s.period.as_of.isoformat()}


def _period_only(s: ResolvedSlots) -> dict[str, object]:
    return dict(_dates(s))


def _period_marketplace(s: ResolvedSlots) -> dict[str, object]:
    assert s.marketplace is not None
    return {**_dates(s), "marketplace": s.marketplace}


def _anomaly(s: ResolvedSlots) -> dict[str, object]:
    # Tenant-level series: the engine persists TENANT_PERIOD metrics with target_ref = the tenant id (derived from the real
    # AuthContext, never from the request). Narration stays off — the CEO composes (§6.4).
    return {**_dates(s), "target_ref": str(s.tenant_id), "include_narration": False}


@dataclass(frozen=True, slots=True)
class ActionPlan:
    key: str  # a registry key
    description: str  # plain language, shown to the classifier
    required_slots: tuple[str, ...]
    build_slots: Callable[[ResolvedSlots], dict[str, object]]


ACTIONS: Mapping[str, ActionPlan] = {
    p.key: p
    for p in (
        ActionPlan("cfo.financial_health", "Financial health bands (good / watch / at-risk) for a period", ("period",), _period_only),
        ActionPlan("cfo.anomaly_check", "Check a period for statistically unusual changes in results", ("period",), _anomaly),
        ActionPlan("cfo.strategic_briefing", "CFO strategic briefing for a period: health, leaks and open data requests ranked", ("period",), _period_only),
        ActionPlan("cfo.reconcile", "Reconcile marketplace settlements against orders to find leaks, for a marketplace and period", ("marketplace", "period"), _period_marketplace),
        ActionPlan("cfo.cash_reconciliation", "Cash reconciliation: is the marketplace paying what it owes, for a marketplace and period", ("marketplace", "period"), _period_marketplace),
    )
}


@dataclass(frozen=True, slots=True)
class LegPlan:
    key: str
    required: bool


@dataclass(frozen=True, slots=True)
class Playbook:
    id: str
    description: str
    required_slots: tuple[str, ...]
    legs: tuple[LegPlan, ...]
    state_reads: tuple[str, ...] = ()
    extra: Mapping[str, str] = field(default_factory=dict)


PLAYBOOKS: Mapping[str, Playbook] = {
    p.id: p
    for p in (
        Playbook(
            "PROFIT_DIAGNOSIS", "Why did my profit or margin drop? Health bands, anomaly check and CFO briefing for a period", ("period",),
            (LegPlan("cfo.financial_health", True), LegPlan("cfo.anomaly_check", False), LegPlan("cfo.strategic_briefing", False)),
            ("BS_PNL_LATEST", "BS_LEAK_OPEN", "BS_DATA_GAPS"),
        ),
        Playbook(
            "CASH_AND_LEAK_CHECK", "Am I being paid what I am owed? Cash reconciliation plus a leak check, for a marketplace and period",
            ("marketplace", "period"), (LegPlan("cfo.cash_reconciliation", True), LegPlan("cfo.reconcile", True)), ("BS_LEAK_OPEN",),
        ),
        Playbook(
            "BUSINESS_BRIEFING", "Give me an overview briefing of the whole business from saved results", (), (),
            ("BS_PNL_LATEST", "BS_LEAK_OPEN", "BS_DATA_GAPS", "BS_HEALTH_BANDS", "BS_SELLER_CONTEXT", "BS_INGEST_STATUS"),
        ),
    )
}

# Spec §6.12 starter playbooks that B3 does NOT run, and why (kept visible so nothing is silently absent).
UNSUPPORTED_PLAYBOOKS: Mapping[str, str] = {
    "COMPETITOR_PRICE_IMPACT": "needs a stored competitor id and the seller's current price as typed slots; no deterministic resolver exists yet",
    "NEW_PRODUCT_DECISION": "needs supplier-quote and budget target refs; no deterministic resolver exists yet",
}

