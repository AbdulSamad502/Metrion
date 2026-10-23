"""The CEO action registry — spec §6.11 (C15, C21).

The ONLY way CEO code reaches a specialist or a shared service. An entry is code reviewed with the owning
agent's spec; it is not model-writable and not configurable per tenant. This is also the **only** module in
`backend/ceo` allowed to import specialist handlers (`backend.api.v1.*`) — `tests/unit/test_ceo_architecture.py`
fails the build otherwise (AC22).

Handlers are the SAME functions the direct-execution HTTP routes call (C20: one function, two entry paths), invoked
with the REAL authenticated `AuthContext` — never a synthetic one (R1; the old `ceo_hub_cmo` pattern built a fake
context and is retired). An entry whose handler cannot be called without caller-assembled or not-yet-specified input is
registered with `invoke=None` and an honest `not_wired_reason`: it is absent from every catalog and refuses if forced —
removed, not worked around (§6.11).

**Excluded by decision (C21):** every write-class or free-form action. `Effect` has no WRITE member, and
`FORBIDDEN_ACTION_KEYS` names the excluded actions so registering one fails loudly.
"""

from __future__ import annotations

import inspect
import typing
from collections.abc import Callable, Iterable, Mapping
from datetime import datetime
from functools import lru_cache
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, Field, model_validator

from backend.auth.context import AuthContext
from backend.auth.permissions import (
    CATALOG_VIEW,
    FINANCIALS_ADJUST,
    RESEARCH_MARKET_TRENDS,
    RESEARCH_NICHE_RUN,
    has_permission,
)
from backend.ceo import gst_lookup
from backend.ceo.contract import (
    AGENT_PERMISSION_KEY,
    ActionSpec,
    AgentCode,
    Effect,
    EntitlementPreflight,
    LegContext,
    UnregisteredAction,
)

# Write-class / free-form actions that must never be CEO-callable in V1 (spec C21, §6.11). Registering any of these raises.
FORBIDDEN_ACTION_KEYS: frozenset[str] = frozenset(
    {
        "cfo.enter_expense",
        "cfo.expense_budget_set",
        "cfo.line_status_override",
        "cfo.line_count_override",
        "cfo.seller_goal_set",
        "cfo.gst_lookup_accept",
        "cfo.analyze_gst_lines",  # caller-assembled lines
        "cfo.pnl",  # caller-assembled canonical lines — CEO uses cfo.pnl_for_tenant
        "cfo.ingest",
        "ci.competitor_url_create",
        "ci.competitor_url_update",
        "ci.evidence_upload",
        "ci.digest_subscription_set",
        "ci.seller_product_set",
        "pi.niche_brief_create",
        "pi.niche_brief_update",
        "cmo.image_upload",
    }
)


class RegistryError(ValueError):
    pass


class ActionRegistry:
    def __init__(self, specs: Iterable[ActionSpec]) -> None:
        self._specs: dict[str, ActionSpec] = {}
        for spec in specs:
            if spec.key in FORBIDDEN_ACTION_KEYS:
                raise RegistryError(f"{spec.key!r} is a write-class/free-form action and may not be registered (spec C21)")
            if spec.key in self._specs:
                raise RegistryError(f"duplicate action key {spec.key!r}")
            if spec.agent is None and spec.source != "GST_LOOKUP":
                raise RegistryError(f"{spec.key!r}: only the shared GST service may have no attachable agent")
            if spec.invoke is None and not spec.not_wired_reason:
                raise RegistryError(f"{spec.key!r}: an unwired action must state why (not_wired_reason)")
            for field_name in spec.fixed_params:
                if spec.slot_model is None or field_name not in spec.slot_model.model_fields:
                    raise RegistryError(f"{spec.key!r}: fixed param {field_name!r} is not a field of its slot model")
            self._specs[spec.key] = spec

    def get(self, key: str) -> ActionSpec:
        try:
            return self._specs[key]
        except KeyError:
            raise UnregisteredAction(key) from None

    def __contains__(self, key: object) -> bool:
        return key in self._specs

    def keys(self) -> tuple[str, ...]:
        return tuple(self._specs)

    def specs(self) -> tuple[ActionSpec, ...]:
        return tuple(self._specs.values())

    def required_permissions(self, spec: ActionSpec) -> tuple[str, ...]:
        """`agent.ceo` + the agent's own key + the registry extras — the conversational chain (spec §8 rule 2)."""
        from backend.auth.permissions import AGENT_CEO

        agent_key = (AGENT_PERMISSION_KEY[spec.agent],) if spec.agent is not None else ()
        return (AGENT_CEO, *agent_key, *spec.required_permissions)

    def catalog_for(
        self,
        ctx: AuthContext,
        *,
        attached: frozenset[str],
        check_entitlement: bool = False,
        now: datetime | None = None,
    ) -> tuple[str, ...]:
        """The closed set of action keys the classifier may be shown for THIS member in THIS investigation:
        wired ∩ member-permitted ∩ attached (∩ entitled, when `check_entitlement`). Advisory only — the choke point
        re-checks everything on every dispatch (C8); this exists so the model is not offered what can never run."""
        assert ctx.role is not None and ctx.tenant_id is not None
        out: list[str] = []
        for spec in self._specs.values():
            if not spec.wired:
                continue
            if spec.agent is not None and spec.agent.value not in attached:
                continue
            if not all(has_permission(role=ctx.role, permissions=ctx.permissions, key=k) for k in self.required_permissions(spec)):
                continue
            if check_entitlement and spec.entitlement is not None:
                if not spec.entitlement(ctx.tenant_id, now or datetime.now().astimezone()).passed:
                    continue
            out.append(spec.key)
        return tuple(out)


# ------------------------------------------------------------------------------------------------ builders
def _body_model(fn: Callable[..., Any]) -> type[BaseModel] | None:
    """The single non-ctx parameter's pydantic model — i.e. the SAME request body the direct route validates."""
    hints = typing.get_type_hints(fn)
    params = [p for p in inspect.signature(fn).parameters if p != "ctx"]
    if not params:
        return None
    if len(params) != 1:
        raise RegistryError(f"{fn.__name__}: expected one body parameter, found {params}")
    model = hints.get(params[0])
    if not (isinstance(model, type) and issubclass(model, BaseModel)):
        raise RegistryError(f"{fn.__name__}: parameter {params[0]!r} is not a pydantic model")
    return model


def _route_invoke(fn: Callable[..., Any]) -> Callable[[Any, AuthContext, LegContext], Mapping[str, Any]]:
    takes_body = any(p != "ctx" for p in inspect.signature(fn).parameters)

    def invoke(slots: Any, ctx: AuthContext, leg: LegContext) -> Mapping[str, Any]:  # noqa: ARG001
        result: Mapping[str, Any] = fn(slots, ctx) if takes_body else fn(ctx)
        return result

    return invoke


def _cfo_entitlement(code: str) -> EntitlementPreflight:
    from backend.entitlement import resolve_cfo_entitlement

    return lambda tenant_id, now: resolve_cfo_entitlement(tenant_id, direct_action_code=code, occurred_at=now)


def _ci_entitlement() -> EntitlementPreflight:
    from backend.entitlement import resolve_ci_entitlement

    return lambda tenant_id, now: resolve_ci_entitlement(tenant_id)


def _pi_entitlement(code: str, *, also_niche_run: bool) -> EntitlementPreflight:
    from backend.entitlement import resolve_niche_run_entitlement, resolve_pi_entitlement

    def check(tenant_id: UUID, now: datetime) -> Any:
        first = resolve_pi_entitlement(tenant_id, direct_action_code=code, occurred_at=now)
        if not first.passed or not also_niche_run:
            return first
        return resolve_niche_run_entitlement(tenant_id)

    return check


def _gst_invoke(slots: Any, ctx: AuthContext, leg: LegContext) -> Mapping[str, Any]:
    from backend.api.v1 import cfo as cfo_api

    try:
        return gst_lookup.invoke(
            slots, ctx, leg, result_to_dict=cfo_api._gst_lookup_result_to_dict, no_match_to_dict=cfo_api._gst_lookup_no_match_to_dict,
        )
    except cfo_api.OllamaUnavailable:
        # Same meaning as the direct route's 503 (C20: one function, two entry paths): the model that reads the pages is down. That is a dependency outage,
        # not a result and not a server bug; the choke point turns a 503 into an UNAVAILABLE leg, and nothing was written.
        raise HTTPException(status_code=503, detail="The model that reads GST pages could not be reached, so nothing was looked up.") from None


def _gst_entitlement(*, through_cfo: bool) -> EntitlementPreflight:
    """Route A meters CFO's own cap AND the shared GST cap (two independent keys); Route B meters the shared GST cap ONLY (G2): no CFO or CMO unit."""
    from backend.entitlement import resolve_cfo_entitlement, resolve_gst_lookup_entitlement

    def check(tenant_id: UUID, now: datetime) -> Any:
        if through_cfo:
            cfo = resolve_cfo_entitlement(tenant_id, direct_action_code="cfo.gst_lookup", occurred_at=now)
            if not cfo.passed:
                return cfo
        return resolve_gst_lookup_entitlement(tenant_id)

    return check


class _PiReportSlots(BaseModel):
    model_config = {"extra": "forbid"}
    run_id: UUID


class _PriceScenarioSlots(BaseModel):
    model_config = {"extra": "forbid"}
    competitor_url_id: UUID
    seller_price_paise: int = Field(gt=0)
    stance: str | None = Field(
        default=None, pattern="^(MATCH_LOWEST|BEAT_LOWEST_BY_PCT|BEAT_LOWEST_BY_PAISE|MATCH_AVERAGE|MATCH_HIGHEST)$"
    )
    stance_param_pct: str | None = None  # decimal string (never a float); the route model parses it
    stance_param_paise: int | None = None


class _DiscoverySlots(BaseModel):
    """One of the seller's products, OR the categories (from their business profile) to search; exactly one."""

    model_config = {"extra": "forbid"}
    product_id: str | None = Field(default=None, min_length=1)
    categories: list[str] | None = Field(default=None, min_length=1, max_length=8)

    @model_validator(mode="after")
    def _one_of(self) -> "_DiscoverySlots":
        if (self.product_id is None) == (self.categories is None):
            raise ValueError("give a product or categories, not both and not neither")
        return self


class _EvidenceIntakeSlots(BaseModel):
    """A screenshot the seller attached to this conversation, BY REFERENCE (never bytes). `competitor_url_id` is which tracked competitor it shows; absent means
    the CEO must ask — nothing is stored and nothing is auto-added (CI spec 6.22.3)."""

    model_config = {"extra": "forbid"}
    attachment_id: UUID
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    competitor_url_id: UUID | None = None
    allow_near_duplicate: bool = False


class _ConfirmAnswer(BaseModel):
    model_config = {"extra": "forbid"}
    info_request_id: UUID
    value: int | str | list[dict[str, Any]]  # a price or delivery charge (paise), a stock status, or the offers the seller accepted as read


class _ConfirmFieldSlots(BaseModel):
    model_config = {"extra": "forbid"}
    answers: list[_ConfirmAnswer] = Field(default_factory=list, max_length=10)
    declined: list[UUID] = Field(default_factory=list, max_length=10)


class _CompetitorAddSlots(BaseModel):
    model_config = {"extra": "forbid"}
    url: str = Field(min_length=1, max_length=2048)
    product_id: str = Field(min_length=1)
    label: str | None = Field(default=None, max_length=120)


class _CompetitorRemoveSlots(BaseModel):
    model_config = {"extra": "forbid"}
    competitor_url_id: UUID
    reason: str | None = Field(default=None, max_length=200)


class _CandidateSlots(BaseModel):
    model_config = {"extra": "forbid"}
    candidate_id: UUID


class _AlertSettingsSlots(BaseModel):
    model_config = {"extra": "forbid"}
    quiet_start: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    quiet_end: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    quiet_tz: str | None = Field(default=None, max_length=64)
    clear_quiet: bool = False
    price_threshold_pct: str | None = Field(default=None, pattern=r"^\d{1,2}(\.\d{1,2})?$")


class _FindingSlots(BaseModel):
    model_config = {"extra": "forbid"}
    finding_id: UUID


class _ReviewIntakeSlots(BaseModel):
    model_config = {"extra": "forbid"}
    attachment_id: UUID
    competitor_url_id: UUID


class _ProductSlots(BaseModel):
    """`product_id` absent means every product that has tracked competitors."""

    model_config = {"extra": "forbid"}
    product_id: str | None = Field(default=None, min_length=1)


def build_default_registry() -> ActionRegistry:
    """Builds the V1 registry. Imports of the HTTP modules are deliberately local: they import the services, never
    the reverse, and importing them here (not at module load) keeps `backend.ceo` importable in isolation."""
    from backend.api.v1 import cfo as cfo_api
    from backend.api.v1 import ci as ci_api
    from backend.api.v1 import cmo as cmo_api
    from backend.api.v1 import pi as pi_api

    specs: list[ActionSpec] = []

    # ---- CFO (agent.ceo + agent.cfo; CFO entitlement per direct_action_code; the route re-checks its own gate) ----
    # (registry key, route function, entitlement code, effect, fixed params)
    cfo_rows: list[tuple[str, str, str, Effect, Mapping[str, Any]]] = [
        ("cfo.pnl_for_tenant", "post_period_pnl_for_tenant", "cfo.pnl", Effect.COMPUTE_PERSIST, {}),
        ("cfo.pricing", "post_pricing_curve", "cfo.pricing", Effect.COMPUTE_PERSIST, {}),
        ("cfo.gst_summary", "post_gst_period_summary", "cfo.gst_summary", Effect.COMPUTE_PERSIST, {}),
        ("cfo.period_comparison", "post_period_comparison", "cfo.period_comparison", Effect.COMPUTE_PERSIST, {}),
        ("cfo.landed_cost", "post_landed_cost", "cfo.landed_cost", Effect.COMPUTE_PERSIST, {}),
        ("cfo.supplier_ranking", "post_rank_suppliers", "cfo.supplier_ranking", Effect.COMPUTE_PERSIST, {}),
        ("cfo.funding_readiness", "post_funding_readiness", "cfo.funding_readiness", Effect.COMPUTE_PERSIST, {}),
        ("cfo.batch_size", "post_batch_size", "cfo.batch_size", Effect.COMPUTE_PERSIST, {}),
        ("cfo.reconcile", "post_reconcile", "cfo.reconcile", Effect.COMPUTE_PERSIST, {}),  # persists leak_finding rows: a derived result, not a seller input
        ("cfo.anomaly_check", "post_anomaly_check", "cfo.anomaly_check", Effect.COMPUTE_PERSIST, {}),
        ("cfo.financial_health", "post_financial_health", "cfo.financial_health", Effect.READ, {}),
        ("cfo.cash_reconciliation", "post_cash_reconciliation", "cfo.cash_reconciliation", Effect.COMPUTE_PERSIST, {}),
        # The CEO composes; CFO must not narrate a second time (§6.4) — the registry pins it.
        ("cfo.strategic_briefing", "post_strategic_briefing", "cfo.strategic_briefing", Effect.READ, {"include_narration": False}),
        # CFO 2.0 planner: a question + CEO-resolved periods in, an evidence packet out (cfo-query-planner.md). The CEO narrates; this never does.
        ("cfo.query", "post_financial_query", "cfo.query", Effect.READ, {}),
    ]
    for key, fn_name, code, effect, fixed in cfo_rows:
        fn = getattr(cfo_api, fn_name)
        specs.append(
            ActionSpec(
                key=key, source="CFO", agent=AgentCode.CFO, effect=effect, description=f"CFO {key.split('.', 1)[1]}",
                slot_model=_body_model(fn), invoke=_route_invoke(fn), entitlement=_cfo_entitlement(code), fixed_params=fixed,
            )
        )
    # The Expense Tracker through the CEO (ceo-expense-tracker-chat.md). One READ, and the four chat-prepared writes (owner decision 2026-10-23, amending C21 for exactly these keys):
    # each write is approval-gated (a plan card the seller approves), needs `financials.adjust`, and runs the tracker's own route function with the real context.
    from backend.ceo.expense_chat import summary_refs as expense_summary_refs
    from backend.services import ceo_expense_ops as expense_ops

    expense_rows: list[tuple[str, Any, str, Effect, tuple[str, ...]]] = [
        ("cfo.expense_summary", expense_ops.summary, "cfo.expense_ledger.read", Effect.READ, ()),
        ("cfo.expense_add", expense_ops.add, "cfo.expense_ledger.write", Effect.RECORD_ENTRY, (FINANCIALS_ADJUST,)),
        ("cfo.expense_correct", expense_ops.correct, "cfo.expense_ledger.write", Effect.RECORD_ENTRY, (FINANCIALS_ADJUST,)),
        ("cfo.expense_void", expense_ops.void, "cfo.expense_ledger.write", Effect.RECORD_ENTRY, (FINANCIALS_ADJUST,)),
        ("cfo.expense_paid", expense_ops.paid, "cfo.expense_ledger.write", Effect.RECORD_ENTRY, (FINANCIALS_ADJUST,)),
    ]
    for key, fn, code, effect, extra_perms in expense_rows:
        specs.append(
            ActionSpec(
                key=key, source="CFO", agent=AgentCode.CFO, effect=effect, description=f"CFO {key.split('.', 1)[1]}", required_permissions=extra_perms,
                slot_model=_body_model(fn), invoke=_route_invoke(fn), entitlement=_cfo_entitlement(code),
                extract_refs=expense_summary_refs if key == "cfo.expense_summary" else None,
            )
        )
    # The gated preview is the entitlement-DENIAL surface for CFO-class results (spec C17): it still requires agent.cfo,
    # and it intentionally has no entitlement preflight (CFO §6.8/§6.9).
    preview = cfo_api.post_preview
    specs.append(
        ActionSpec(
            key="cfo.preview", source="CFO", agent=AgentCode.CFO, effect=Effect.READ, description="CFO free-tier gated preview",
            slot_model=_body_model(preview), invoke=_route_invoke(preview), entitlement=None, denial_surface=True,
        )
    )
    # GST: Route A/B selection, the G1–G7 safety conditions and basis-label plumbing land with the playbook/orchestration
    # checkpoint (B4); until then these are registered but NOT callable. They already have tests (test_ceo_hub_cmo G1–G7).
    gst_rows: list[tuple[str, str, AgentCode | None, tuple[str, ...]]] = [
        ("cfo.gst_lookup", "CFO", AgentCode.CFO, ("service.gst_lookup",)),
        ("service.gst_lookup", "GST_LOOKUP", None, ("service.gst_lookup",)),
    ]
    for key, source, agent, extra in gst_rows:
        specs.append(
            ActionSpec(
                key=key, source=source, agent=agent, effect=Effect.COMPUTE_PERSIST,
                description="GST applicability lookup (Route A via CFO / Route B shared)", required_permissions=extra,
                slot_model=gst_lookup.GstSlots, invoke=_gst_invoke, entitlement=_gst_entitlement(through_cfo=agent is not None),
            )
        )

    # ---- PI ----
    discover, supplier, report = pi_api.post_discover, pi_api.post_supplier_lookup, pi_api.get_report
    specs += [
        ActionSpec(
            key="pi.discover", source="PI", agent=AgentCode.PI, effect=Effect.GENERATE_METERED,
            description="PI niche discovery run (needs an existing READY niche brief)",
            required_permissions=(RESEARCH_NICHE_RUN,), slot_model=_body_model(discover), invoke=_route_invoke(discover),
            entitlement=_pi_entitlement("pi.discover", also_niche_run=True), writes_own_run=True,
        ),
        ActionSpec(
            key="pi.supplier_lookup", source="PI", agent=AgentCode.PI, effect=Effect.GENERATE_METERED,
            description="PI supplier lookup for chosen candidates", slot_model=_body_model(supplier),
            invoke=_route_invoke(supplier), entitlement=_pi_entitlement("pi.supplier_lookup", also_niche_run=False),
            writes_own_run=True,
        ),
        ActionSpec(
            key="pi.report", source="PI", agent=AgentCode.PI, effect=Effect.READ,
            description="Re-render a completed PI run from persisted data (no new fetch)", slot_model=_PiReportSlots,
            invoke=lambda s, ctx, leg: report(s.run_id, ctx),
        ),
    ]

    # ---- CI ----
    from backend.api.v1.ci import PriceScenarioRequest, StartDiscoveryRunRequest

    def _price_scenario(slots: _PriceScenarioSlots, ctx: AuthContext, leg: LegContext) -> Mapping[str, Any]:  # noqa: ARG001
        from decimal import Decimal

        body = PriceScenarioRequest(
            seller_price_paise=slots.seller_price_paise, stance=slots.stance,
            stance_param_pct=Decimal(slots.stance_param_pct) if slots.stance_param_pct is not None else None,
            stance_param_paise=slots.stance_param_paise,
        )
        return ci_api.compute_price_scenario(slots.competitor_url_id, body, ctx)

    specs += [
        ActionSpec(
            key="ci.request_price_scenario", source="CI", agent=AgentCode.CI, effect=Effect.COMPUTE_PERSIST,
            description="CI price positioning + repricing scenario (engine-computed)", slot_model=_PriceScenarioSlots,
            invoke=_price_scenario, entitlement=_ci_entitlement(),
        ),
        ActionSpec(
            key="ci.discover_competitors", source="CI", agent=AgentCode.CI, effect=Effect.COMPUTE_PERSIST,
            description="CI competitor discovery pipeline", slot_model=_DiscoverySlots,
            invoke=lambda s, ctx, leg: (ci_api.post_category_discovery(s.categories, ctx) if s.categories else ci_api.post_discovery_run(StartDiscoveryRunRequest(product_id=s.product_id), ctx)),
            entitlement=_ci_entitlement(),
        ),
        ActionSpec(
            key="ci.research_now", source="CI", agent=AgentCode.CI, effect=Effect.COMPUTE_PERSIST,
            description="CI research session over uploaded evidence",
            not_wired_reason="needs a chat-attachment/evidence-upload surface (spec Q8, unresolved); image_refs cannot be supplied from chat yet",
        ),
    ]

    # ---- CMO: the 14 actions (13 of §6.9 + the pre-send trend preview). Each handler runs its own quota admission and
    #      writes its own agent_run, which inherits the CEO turn as its parent through agent_run_repo.parent_run_scope. ----
    cmo_rows: tuple[tuple[str, str, Effect, tuple[str, ...]], ...] = (
        ("cmo.generate_title_sets", "post_title_sets", Effect.GENERATE_METERED, ()),
        ("cmo.approve_title", "post_title_approval", Effect.RECORD_CHOICE, ()),
        ("cmo.generate_listing_copy", "post_listing_copy", Effect.GENERATE_METERED, ()),
        ("cmo.generate_description", "post_description", Effect.GENERATE_METERED, ()),
        ("cmo.generate_bullets", "post_bullets", Effect.GENERATE_METERED, ()),
        ("cmo.generate_keywords", "post_keywords", Effect.GENERATE_METERED, ()),
        ("cmo.generate_backend_terms", "post_backend_terms", Effect.GENERATE_METERED, ()),
        ("cmo.generate_hashtags", "post_hashtags", Effect.GENERATE_METERED, ()),
        ("cmo.catalog_answer", "post_catalog_answers", Effect.GENERATE_METERED, ()),
        ("cmo.confirm_image_hint", "post_confirm_image_hint", Effect.RECORD_CHOICE, ()),
        ("cmo.suggest_niche_terms", "post_suggest_niche_terms", Effect.READ, (CATALOG_VIEW,)),
        ("cmo.confirm_niche_terms", "post_confirm_niche_terms", Effect.RECORD_CHOICE, ()),
        ("cmo.market_trends_preview", "post_market_trends_preview", Effect.READ, (RESEARCH_MARKET_TRENDS,)),
        ("cmo.market_trends", "post_market_trends", Effect.GENERATE_METERED, (RESEARCH_MARKET_TRENDS,)),
    )
    for key, fn_name, effect, extra in cmo_rows:
        fn = getattr(cmo_api, fn_name)
        specs.append(
            ActionSpec(
                key=key, source="CMO", agent=AgentCode.CMO, effect=effect, description=f"CMO {key.split('.', 1)[1]}",
                required_permissions=extra, slot_model=_body_model(fn), invoke=_route_invoke(fn), entitlement=None,
                writes_own_run=True,
            )
        )
    # The CEO -> CMO photo hand-off by reference (ceo-cmo-delegation.md DD2). `cmo.image_upload` (raw bytes, a write) stays forbidden; this action's only slots are an attachment id and
    # the hash the CEO saw, and it always needs its own 0-unit plan card (effects.force_approval).
    analyze_slots = cmo_api.AnalyzeAttachmentBody

    def _analyze_attachment(slots: Any, ctx: AuthContext, leg: LegContext) -> Mapping[str, Any]:
        assert leg.investigation_id is not None  # a hand-off only exists inside a conversation: the reference is validated against it
        return cmo_api.analyze_attachment_for_ceo(slots, ctx, leg.investigation_id)

    specs.append(
        ActionSpec(
            key="cmo.analyze_attachment", source="CMO", agent=AgentCode.CMO, effect=Effect.COMPUTE_PERSIST, description="CMO reads an attached product photo (by reference)",
            slot_model=analyze_slots, invoke=_analyze_attachment, entitlement=None, writes_own_run=True,
        )
    )
    # ---- CI conversational surface (CI spec 6.21.3, C32). Fixed actions; the seller reaches them only through the CEO. ----
    def _ci(key: str, description: str, slot_model: type[BaseModel], invoke: Any, *, effect: Effect = Effect.COMPUTE_PERSIST, writes_own_run: bool = False) -> ActionSpec:
        return ActionSpec(key=key, source="CI", agent=AgentCode.CI, effect=effect, description=description, slot_model=slot_model, invoke=invoke,
                          entitlement=_ci_entitlement(), writes_own_run=writes_own_run)

    specs += [
        _ci("ci.evidence_intake", "CI reads a competitor screenshot the seller attached (by reference)", _EvidenceIntakeSlots, ci_api.evidence_intake_for_ceo, writes_own_run=True),
        _ci("ci.confirm_field", "CI records the seller's answers to its confirmation questions", _ConfirmFieldSlots, ci_api.confirm_field_for_ceo),
        _ci("ci.competitor_add", "Track a competitor the seller named by marketplace link", _CompetitorAddSlots, ci_api.competitor_add_for_ceo),
        _ci("ci.competitor_remove", "Stop tracking a competitor (history is kept)", _CompetitorRemoveSlots, ci_api.competitor_remove_for_ceo),
        _ci("ci.competitor_approve", "Approve a discovered competitor candidate", _CandidateSlots, ci_api.competitor_approve_for_ceo),
        _ci("ci.competitor_reject", "Reject a discovered competitor candidate", _CandidateSlots, ci_api.competitor_reject_for_ceo),
        _ci("ci.monitor_competitors", "Re-evaluate the stored evidence for a product's tracked competitors", _ProductSlots, ci_api.monitor_competitors_for_ceo, effect=Effect.READ),
        _ci("ci.alert_settings_set", "Save the seller's own competitor alert preferences (quiet hours, price-change threshold)", _AlertSettingsSlots, ci_api.alert_settings_set_for_ceo),
        _ci("ci.explain_finding", "Re-read one stored CI finding and the evidence it cites", _FindingSlots, ci_api.explain_finding_for_ceo, effect=Effect.READ),
        _ci("ci.review_intake", "CI reads a competitor reviews screenshot the seller attached (by reference)", _ReviewIntakeSlots, ci_api.review_intake_for_ceo, writes_own_run=True),
        _ci("ci.review_findings", "What saved competitor review evidence says (themes with sample sizes)", _ProductSlots, ci_api.review_findings_for_ceo, effect=Effect.READ),
    ]
    return ActionRegistry(_with_effects(specs))


def _with_effects(specs: list[ActionSpec]) -> list[ActionSpec]:
    """Attaches the reviewed `ACTION_EFFECTS` entry to every action and refuses a registry in which a registered key has no entry or an entry has no
    action: a new action cannot be registered without being classified (approval prerequisite R1)."""
    from dataclasses import replace

    from backend.ceo.effects import ACTION_EFFECTS

    keys = {s.key for s in specs}
    missing, orphan = sorted(keys - set(ACTION_EFFECTS)), sorted(set(ACTION_EFFECTS) - keys)
    if missing or orphan:
        raise RegistryError(f"ACTION_EFFECTS does not match the registry: unclassified={missing} orphaned={orphan}")
    return [replace(s, effects=ACTION_EFFECTS[s.key]) for s in specs]


@lru_cache(maxsize=1)
def get_registry() -> ActionRegistry:
    return build_default_registry()
