"""CFO's direct-execution routes — mirrors `api/v1/ci.py`'s structure. `require_auth(
permission=AGENT_CFO)` on every route; expense-write routes additionally check
`FINANCIALS_ADJUST` in-handler (§8 rule 4 / E19 — the plan's judgment call 3: a second
permission beyond `require_auth`'s single one, done locally rather than by extending
`require_auth` itself).

`POST /cfo/reconcile` (D5, cfo-agent.md §6.2/§6.8 `cfo.reconcile`) is the leak/reconcile route
guardrail 4 (twinkly-mapping-canyon.md CP2) withheld until a real `reconcile()` shipped — it
has now shipped (D4) and is wired end-to-end here.

`POST /cfo/preview` (D7, cfo-agent.md §6.9/§6.8 `cfo.preview`) is the free-tier gated preview —
the ONE route in this file that intentionally does NOT call `_require_cfo_entitlement` (see its
own docstring for why); permission (`agent.cfo`) still applies unchanged.

`POST /cfo/gst-lookup` (G3, cfo-agent.md §6.6 C5/C6/§6.8 `cfo.gst_lookup`, AC17b/T31) is the
first route in this file requiring TWO independent permissions (`agent.cfo` **and**
`service.gst_lookup`) and TWO independent entitlement caps — see `post_gst_lookup`'s own
docstring for the exact mechanism (`require_auth` for the first permission, an in-handler
`has_permission` check for the second, mirroring `put_expense`'s existing second-permission
pattern).

`POST /cfo/gst-lookup/accept` (G4, deterministic-engine.md §7.2.1/§8.4's updated L2 rule) is the
seller-acceptance act G3 deliberately left out of scope — turning a `PROVISIONAL`
`gst_lookup_result` into a real `gst_rate_override` manual_adjustment. THREE permission gates
(`agent.cfo` + `service.gst_lookup`, mirroring `post_gst_lookup`'s pair exactly, PLUS
`financials.adjust`, since this route creates a manual financial input — §7's standing rule,
restated at §7.2.1's own "Permission" paragraph). See `post_accept_gst_lookup`'s own docstring
for why it deliberately does NOT re-run the entitlement caps `post_gst_lookup` enforces.
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime, timezone
from fractions import Fraction
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, UploadFile
from pydantic import BaseModel, Field

from data_foundation.adapters.registry import ADAPTER_REGISTRY
from data_foundation.ingestion.file_reader import read_csv_file
from data_foundation.ingestion.persist import ingest_and_persist
from data_foundation.ingestion.pipeline import AdapterMismatchError
from data_foundation.repositories import report_file_repo

from calc_engine.formulas.cost_components import CostEntry
from calc_engine.types import CanonicalLine, ComponentRow, Confidence, Paise, RecognitionState, Unavailable

from backend.agents.ceo_hub import (
    CFO_ANALYZE_GST_LINES,
    CFO_ANOMALY_CHECK,
    CFO_BATCH_SIZE,
    CFO_ENTER_EXPENSE,
    CFO_FUNDING_READINESS,
    CFO_GST_SUMMARY,
    CFO_LANDED_COST,
    CFO_PERIOD_COMPARISON,
    CFO_PNL,
    CFO_PRICING,
    CFO_RECONCILE,
    CFO_SUPPLIER_RANKING,
)
from backend.auth.context import AuthContext, require_auth
from backend.auth.permissions import AGENT_CFO, FINANCIALS_ADJUST, SERVICE_GST_LOOKUP, has_permission
from backend.config import cfo_narration_model, cfo_report_storage_dir, ollama_host
from backend.entitlement import resolve_cfo_entitlement, resolve_gst_lookup_entitlement
from backend.services.cfo_actions import (
    AcceptGstLookupRequest,
    AnomalyCheckRequest,
    BatchSizeRequest,
    CashReconciliationRequest,
    DeclareLineCountOverrideRequest,
    DeclareLineStatusOverrideRequest,
    EnterExpenseBudgetRequest,
    FinancialHealthRequest,
    FundingReadinessRequest,
    StrategicBriefingRequest,
    GstLineInput,
    GstLineResult,
    GstLookupRequest,
    GstPeriodSummaryRequest,
    LandedCostRequest,
    PeriodComparisonRequest,
    PeriodPnlForTenantRequest,
    PeriodPnlRequest,
    PricingCurveRequest,
    SupplierRankingRequest,
    accept_gst_lookup_result,
    analyze_gst_lines,
    assemble_batch_size_estimate,
    assemble_cash_reconciliation,
    assemble_cfo_preview,
    assemble_financial_health,
    assemble_funding_readiness_reduced,
    assemble_strategic_briefing,
    check_expense_budget,
    compute_landed_cost_for_quote,
    compute_period_pnl,
    compute_period_pnl_for_tenant,
    compute_pricing_curve,
    declare_line_count_override,
    declare_line_status_override,
    enter_expense,
    get_line_status_overrides,
    get_seller_goal,
    list_expenses,
    narrate_anomaly_check,
    narrate_period_comparison,
    rank_suppliers,
    render_gst_period_summary,
    run_anomaly_check,
    run_gst_applicability_lookup,
    run_leak_shield_reconciliation,
    set_expense_budget,
    set_seller_goal,
)
from cfo.reasoning.ollama_provider import OllamaLlmProvider
from cfo.reasoning.signals import PricingCandidateInput, SupplierRankInput
from cfo.repositories.agent_data_request_repo import list_for_tenant

router = APIRouter(prefix="/api/v1/cfo")

# cfo-agent.md §6.16 (ingestion). Direct-path only, no CEO dispatch — same reasoning as
# CFO_PREVIEW below. Read-write (creates a report_file/ingestion_run/sales_line trail, not a
# manual financial adjustment), so `financials.adjust` is NOT required — mirrors `POST /ci/
# evidence`'s own "uploading source data isn't declaring a financial fact" reasoning.
CFO_INGEST = "cfo.ingest"
CFO_SELLER_GOAL = "cfo.seller_goal"


class SellerGoalHttpRequest(BaseModel):
    target_margin_pct: str | None = None
    priority_category: str | None = None
    note: str | None = None


@router.put("/seller-goal")
def put_seller_goal(
    body: SellerGoalHttpRequest, ctx: AuthContext = require_auth(permission=AGENT_CFO)
) -> dict[str, str]:
    """cfo-agent.md §7.5 — seller-declared context only, never a rule any formula branches on."""
    assert ctx.tenant_id is not None
    _require_cfo_entitlement(ctx.tenant_id, direct_action_code=CFO_SELLER_GOAL)
    if ctx.role is None or not has_permission(role=ctx.role, permissions=ctx.permissions, key=FINANCIALS_ADJUST):
        raise HTTPException(status_code=403, detail="financials.adjust permission required")
    manual_adjustment_id = set_seller_goal(
        ctx.tenant_id, target_margin_pct=body.target_margin_pct, priority_category=body.priority_category,
        note=body.note, created_by=ctx.app_user_id,
    )
    return {"manualAdjustmentId": str(manual_adjustment_id)}


@router.get("/seller-goal")
def get_seller_goal_route(ctx: AuthContext = require_auth(permission=AGENT_CFO)) -> dict[str, object]:
    assert ctx.tenant_id is not None
    goal = get_seller_goal(ctx.tenant_id)
    if goal is None:
        return {"targetMarginPct": None, "priorityCategory": None, "note": None}
    return {"targetMarginPct": goal.target_margin_pct, "priorityCategory": goal.priority_category, "note": goal.note}


@router.post("/ingest")
async def post_ingest(
    file: UploadFile,
    marketplace: str,
    adapter_id: str,
    ctx: AuthContext = require_auth(permission=AGENT_CFO),
) -> dict[str, object]:
    """Upload -> parse -> validate -> persist (cfo-agent.md §6.16). CSV only this pass.
    Local-disk storage (`cfo_report_storage_dir`), same functional-only posture as `POST /ci/
    evidence`. Deduped by content hash (§3.1: a byte-identical re-upload is reported, not
    re-ingested) and, within `ingest_and_persist`, by natural key (§6 rule 4)."""
    assert ctx.tenant_id is not None
    _require_cfo_entitlement(ctx.tenant_id, direct_action_code=CFO_INGEST)

    adapter = ADAPTER_REGISTRY.get(adapter_id)
    if adapter is None:
        raise HTTPException(status_code=400, detail=f"unknown adapter_id {adapter_id!r}")

    contents = await file.read()
    content_sha256 = hashlib.sha256(contents).hexdigest()

    existing_id = report_file_repo.find_by_content_hash(ctx.tenant_id, content_sha256)
    if existing_id is not None:
        return {"reportFileId": str(existing_id), "duplicate": True}

    storage_dir = Path(cfo_report_storage_dir())
    storage_dir.mkdir(parents=True, exist_ok=True)
    stored_name = f"{content_sha256}{Path(file.filename or '').suffix or '.csv'}"
    (storage_dir / stored_name).write_bytes(contents)

    uploaded_at = datetime.now(timezone.utc)
    report_file_id = report_file_repo.insert_report_file(
        ctx.tenant_id,
        marketplace=marketplace,
        report_category=adapter.report_category,
        content_sha256=content_sha256,
        original_filename=file.filename or stored_name,
        byte_size=len(contents),
        storage_uri=f"file://{storage_dir / stored_name}",
        uploaded_by=ctx.app_user_id,
        uploaded_at=uploaded_at,
    )

    try:
        sample, raw_file = read_csv_file(contents)
        outcome = ingest_and_persist(
            ctx.tenant_id, report_file_id=report_file_id, adapter_id=adapter_id,
            sample=sample, raw_file=raw_file, started_at=uploaded_at,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except AdapterMismatchError as exc:
        raise HTTPException(
            status_code=400, detail=f"file does not match adapter {adapter_id!r} — missing columns {exc.missing_columns}"
        ) from None

    return {
        "reportFileId": str(report_file_id),
        "duplicate": False,
        "ingestionRunId": str(outcome.ingestion_run_id),
        "rowCountRead": outcome.row_count_read,
        "rowCountAccepted": outcome.row_count_accepted,
        "rowCountRejected": outcome.row_count_rejected,
        "rowCountDuplicate": outcome.row_count_duplicate,
        "persistedSalesLineIds": [str(i) for i in outcome.persisted_sales_line_ids],
    }


# D7 (cfo-agent.md §6.8 `cfo.preview` table row) — the trigger id string, reused verbatim from
# the spec's own table. Defined HERE, not in `agents/ceo_hub.py`'s `CFO_*` constants, because
# the spec's own table marks this trigger's "CEO call" column "No": there is no
# `dispatch_cfo_preview` in `ceo_hub.py` and none is added by this change — direct-path only,
# HTTP route below.
CFO_PREVIEW = "cfo.preview"

# G3 (cfo-agent.md §6.8 `cfo.gst_lookup` table row) — the trigger id string, reused verbatim
# from the spec's own table. Defined HERE, not in `agents/ceo_hub.py`'s `CFO_*` constants, for
# the SAME documented reason as `CFO_PREVIEW` immediately above: §6.8's own table marks this
# trigger's "CEO call" column "No" (identical to `cfo.preview`'s row) — no `dispatch_cfo_gst_
# lookup` exists in `ceo_hub.py`, and none is added here; direct-path only, HTTP route below.
CFO_GST_LOOKUP = "cfo.gst_lookup"

# Expense-budget-write addition (small, additive — see `put_expense`'s own docstring for the
# established write-path pattern this mirrors). Defined here, not in `ceo_hub.py`, for the SAME
# reason as `CFO_PREVIEW`/`CFO_GST_LOOKUP` above: no `dispatch_cfo_*` wiring exists or is added
# for this — direct-path only, HTTP route below. The two new read-only routes (`GET /cfo/
# expenses`, `GET /cfo/expenses/budget-status`) need no trigger id of their own — they never
# call `_require_cfo_entitlement`, mirroring `GET /cfo/data-requests`'s own identical
# "read-only, no entitlement gate" precedent.
CFO_EXPENSE_BUDGET_SET = "cfo.expense_budget_set"

# Line-status-override write addition (deterministic-engine.md §7.2.1's new
# `cancellation_state_override`/`return_status_override`/`rto_status_override` triple — closes
# the CFO end-to-end evaluation's headline finding, see `declare_line_status_override`'s own
# docstring). Same reasoning as `CFO_EXPENSE_BUDGET_SET` immediately above: no `dispatch_cfo_*`
# wiring exists or is added for this — direct-path only, HTTP route below. The read route
# (`GET /cfo/line-status-override`) needs no trigger id of its own — same "read-only, no
# entitlement gate" precedent as `GET /cfo/expenses`.
CFO_LINE_STATUS_OVERRIDE = "cfo.line_status_override"

# Financial Health Band addition (cfo-agent.md §6.15). Defined here, not in `ceo_hub.py`, for
# the SAME reason as `CFO_PREVIEW`/`CFO_GST_LOOKUP`/`CFO_EXPENSE_BUDGET_SET` above: no
# `dispatch_cfo_*` wiring exists or is added for this — direct-path only, HTTP route below.
# Read-only (no manual write), so unlike `put_expense`/`put_line_status_override` this route
# needs no second `financials.adjust` gate — same "computed insight, not a manual input"
# reasoning `post_anomaly_check` already established for its own entitlement-only gate.
CFO_FINANCIAL_HEALTH = "cfo.financial_health"
CFO_CASH_RECONCILIATION = "cfo.cash_reconciliation"

# Strategic Insight layer addition (cfo-agent.md §7.5). Defined here, not in `ceo_hub.py`, for
# the SAME reason as `CFO_FINANCIAL_HEALTH` above: no `dispatch_cfo_*` wiring exists or is added
# for this — direct-path only, HTTP route below. Read-only (gathers already-computed/persisted
# outputs, creates no manual input), so needs no `financials.adjust` gate either.
CFO_STRATEGIC_BRIEFING = "cfo.strategic_briefing"


def _require_cfo_entitlement(tenant_id: UUID, *, direct_action_code: str) -> None:
    """F3 of the entitlement roadmap — the real HTTP-layer enforcement gate
    `resolve_cfo_entitlement` (F2) was computed for but this file never actually called.
    Zero functional regression today: with no `entitlement_cap_config` row seeded anywhere,
    every real call resolves `NO_CAP_CONFIGURED`/`passed=True` (entitlement.md §5.5), so this
    never denies in production until a cap is actually configured.

    **`402 Payment Required` is a judgment call, not yet confirmed by any spec** — `auth.md`'s
    six-step chain never assigns entitlement a status code (it's a separate gate, §7.2), and
    `require_auth` already owns `403` for permission denials. `402` is the semantically closest
    standard code for "not entitled to this paid capability" without colliding with that
    existing meaning. Flagged here explicitly for review; a one-line change if a different code
    is wanted.

    `REDUCED_PAYLOAD` rendering (entitlement.md D1/§6 rule 9) is deliberately NOT implemented
    here. **Note (D7):** `cfo.preview` now exists (`POST /cfo/preview`, `assemble_cfo_preview`)
    as a genuinely reduced-payload surface, but it is reached by a DIFFERENT mechanism than
    this function's `REDUCED_PAYLOAD` branch below — `post_preview` never calls this function
    at all (see its own docstring), so this branch still has no real caller today. Since no
    `capability_entitlement_rule` row is ever seeded in V1, `denial_rendering` is always
    `'ERROR'` for every call site that DOES call this function; the `501` branch below remains
    an honest, labelled placeholder for the day a rule row exists, never a silent fallthrough
    to a fake preview response.
    """
    result = resolve_cfo_entitlement(tenant_id, direct_action_code=direct_action_code)
    if result.passed:
        return
    if result.denial_rendering == "REDUCED_PAYLOAD":
        raise HTTPException(
            status_code=501,
            detail="reduced payload rendering not yet implemented for this action",
        )
    raise HTTPException(
        status_code=402,
        detail={
            "reason": result.reason,
            "meterCode": result.meter_code,
            "evaluationBasis": result.evaluation_basis,
        },
    )


def _gst_line_result_to_dict(result: GstLineResult) -> dict[str, object]:
    return {
        "lineRef": result.line_ref,
        "normalizedExclusivePaise": result.normalized_exclusive_paise,
        "isAvailable": result.is_available,
        "unavailableReason": result.unavailable_reason,
        "ratePlausibilityMatched": result.rate_plausibility_matched,
        "ratePlausibilitySeverity": result.rate_plausibility_severity,
        "disclaimer": result.disclaimer,
    }


class EnterExpenseRequest(BaseModel):
    """The manual expense-entry form — one engine §7.2.1 field at a time (`enter_expense`
    rejects any field outside that registry). `value` is passed through unchanged; its shape
    is whatever §7.2.1 defines for the given `field` (e.g. `{amount_paise, gst_amount_paise?,
    marketplace?}` for an `expense.*` pool)."""

    target_type: str = Field(pattern="^(SKU|ACCOUNT|PERIOD)$")
    target_ref: str = Field(min_length=1)
    field: str = Field(min_length=1)
    value: Any
    reason: str | None = None
    supersedes_id: UUID | None = None


@router.put("/expenses")
def put_expense(
    body: EnterExpenseRequest, ctx: AuthContext = require_auth(permission=AGENT_CFO)
) -> dict[str, str]:
    """Direct-execution path (C20) for manual financial input — shares
    `backend.services.cfo_actions.enter_expense` with `agents.ceo_hub.dispatch_cfo_enter_
    expense`. `financials.adjust` is checked here, in-handler, as the plan's second gate
    (§8 rule 4) — `require_auth(permission=AGENT_CFO)` alone is not sufficient for a write
    that creates/supersedes a manual financial input (cfo-agent.md §8 rule 4)."""
    assert ctx.tenant_id is not None
    _require_cfo_entitlement(ctx.tenant_id, direct_action_code=CFO_ENTER_EXPENSE)
    if ctx.role is None or not has_permission(role=ctx.role, permissions=ctx.permissions, key=FINANCIALS_ADJUST):
        raise HTTPException(status_code=403, detail="financials.adjust permission required")

    try:
        manual_adjustment_id = enter_expense(
            ctx.tenant_id,
            target_type=body.target_type,
            target_ref=body.target_ref,
            field=body.field,
            value=body.value,
            created_by=ctx.app_user_id,
            reason=body.reason,
            supersedes_id=body.supersedes_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None

    return {"manualAdjustmentId": str(manual_adjustment_id)}


def _expense_entry_to_dict(entry: Any) -> dict[str, object]:
    return {
        "manualAdjustmentId": str(entry.manual_adjustment_id),
        "category": entry.category,
        "amountPaise": entry.amount_paise.value,
        "targetType": entry.target_type,
        "targetRef": entry.target_ref,
        "createdAt": entry.created_at.isoformat(),
        "createdBy": str(entry.created_by),
        "reason": entry.reason,
    }


@router.get("/expenses")
def get_expenses(
    period_start: date | None = None,
    period_end: date | None = None,
    category: str | None = None,
    ctx: AuthContext = require_auth(permission=AGENT_CFO),
) -> dict[str, object]:
    """Feature 1: read-only listing of ACTIVE `expense.<category>` manual_adjustment rows
    (`backend.services.cfo_actions.list_expenses`), optionally filtered by category and/or
    period. Viewing an existing manual input is not creating one, so this route — unlike
    `PUT /cfo/expenses` — needs only `agent.cfo`, mirroring `GET /cfo/data-requests`'s own
    identical "read-only surfacing, no `financials.adjust` gate" pattern."""
    assert ctx.tenant_id is not None
    try:
        outcome = list_expenses(
            ctx.tenant_id, period_start=period_start, period_end=period_end, category=category
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None

    return {
        "entries": [_expense_entry_to_dict(e) for e in outcome.entries],
        "totalPaise": outcome.total_paise.value,
    }


class EnterExpenseBudgetHttpRequest(BaseModel):
    """Mirrors `EnterExpenseRequest`'s own shape (deterministic-engine.md §7.2.1's
    `expense.budget` row) — one category ceiling for one period. No `target_type`/`target_ref`
    fields: `set_expense_budget` fixes both (`ACCOUNT`, `str(tenant_id)`) itself, see that
    function's own grain-decision docstring."""

    category: str = Field(min_length=1)
    amount_paise: int
    period_start: date
    period_end: date
    reason: str | None = None
    supersedes_id: UUID | None = None


@router.put("/expenses/budget")
def put_expense_budget(
    body: EnterExpenseBudgetHttpRequest, ctx: AuthContext = require_auth(permission=AGENT_CFO)
) -> dict[str, str]:
    """Feature 2's write half — creates/supersedes one `expense.budget` manual_adjustment via
    `backend.services.cfo_actions.set_expense_budget`. Same second gate `put_expense` already
    enforces (`financials.adjust`, in-handler, §8 rule 4 — a budget ceiling is a manual
    financial input exactly like an expense entry itself)."""
    assert ctx.tenant_id is not None
    _require_cfo_entitlement(ctx.tenant_id, direct_action_code=CFO_EXPENSE_BUDGET_SET)
    if ctx.role is None or not has_permission(role=ctx.role, permissions=ctx.permissions, key=FINANCIALS_ADJUST):
        raise HTTPException(status_code=403, detail="financials.adjust permission required")

    try:
        manual_adjustment_id = set_expense_budget(
            ctx.tenant_id,
            EnterExpenseBudgetRequest(
                category=body.category,
                amount_paise=body.amount_paise,
                period_start=body.period_start,
                period_end=body.period_end,
                created_by=ctx.app_user_id,
                reason=body.reason,
                supersedes_id=body.supersedes_id,
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None

    return {"manualAdjustmentId": str(manual_adjustment_id)}


@router.get("/expenses/budget-status")
def get_expense_budget_status(
    category: str,
    period_start: date,
    period_end: date,
    ctx: AuthContext = require_auth(permission=AGENT_CFO),
) -> dict[str, object]:
    """Feature 2's read half — `backend.services.cfo_actions.check_expense_budget`'s real,
    deterministic `exceeded`/`remaining_paise` fact for one category/period, read-only
    (`agent.cfo` only, same "viewing isn't creating" reasoning as `GET /cfo/expenses` above).
    `noBudgetSet: true` is a real, distinguished outcome — `budgetPaise`/`remainingPaise` are
    `null` ONLY in that case, never a fabricated default ceiling."""
    assert ctx.tenant_id is not None
    try:
        status = check_expense_budget(
            ctx.tenant_id, category=category, period_start=period_start, period_end=period_end
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None

    return {
        "category": status.category,
        "periodStart": status.period_start.isoformat(),
        "periodEnd": status.period_end.isoformat(),
        "spentPaise": status.spent_paise.value,
        "noBudgetSet": status.no_budget_set,
        "budgetPaise": status.budget_paise.value if status.budget_paise is not None else None,
        "remainingPaise": status.remaining_paise.value if status.remaining_paise is not None else None,
        "exceeded": status.exceeded,
        "manualAdjustmentId": (
            str(status.manual_adjustment_id) if status.manual_adjustment_id is not None else None
        ),
    }


class DeclareLineStatusOverrideHttpRequest(BaseModel):
    """One seller declaration of a real order-line outcome (deterministic-engine.md §7.2.1's
    `cancellation_state_override`/`return_status_override`/`rto_status_override`) — mirrors
    `EnterExpenseRequest`'s own shape, restricted to this trio's real enumerated values by
    `declare_line_status_override` itself, not by this model (the same division of validation
    responsibility `EnterExpenseRequest`/`enter_expense` already use)."""

    sales_line_id: UUID
    field: str = Field(min_length=1)
    value: str = Field(min_length=1)
    reason: str | None = None
    supersedes_id: UUID | None = None


@router.put("/line-status-override")
def put_line_status_override(
    body: DeclareLineStatusOverrideHttpRequest, ctx: AuthContext = require_auth(permission=AGENT_CFO)
) -> dict[str, str]:
    """Direct-execution write for a seller's cancellation/return/RTO status declaration, for
    the real order-line case the CFO end-to-end evaluation surfaced: a marketplace upload that
    carries no resolvable status at all for a line. Same second gate `put_expense` already
    established (`financials.adjust`, §8 rule 4) — this creates a manual financial-adjacent
    input exactly like an expense entry does."""
    assert ctx.tenant_id is not None
    _require_cfo_entitlement(ctx.tenant_id, direct_action_code=CFO_LINE_STATUS_OVERRIDE)
    if ctx.role is None or not has_permission(role=ctx.role, permissions=ctx.permissions, key=FINANCIALS_ADJUST):
        raise HTTPException(status_code=403, detail="financials.adjust permission required")

    try:
        manual_adjustment_id = declare_line_status_override(
            ctx.tenant_id,
            DeclareLineStatusOverrideRequest(
                sales_line_id=body.sales_line_id,
                field=body.field,
                value=body.value,
                created_by=ctx.app_user_id,
                reason=body.reason,
                supersedes_id=body.supersedes_id,
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None

    return {"manualAdjustmentId": str(manual_adjustment_id)}


@router.get("/line-status-override")
def get_line_status_override(
    sales_line_id: UUID, ctx: AuthContext = require_auth(permission=AGENT_CFO)
) -> dict[str, object]:
    """Read-only surfacing of one line's current declarations, all five fields at once —
    `agent.cfo` only, same "viewing isn't creating" reasoning as `GET /cfo/expenses`. `None` for
    a field with no ACTIVE row, never a fabricated default."""
    assert ctx.tenant_id is not None
    overrides = get_line_status_overrides(ctx.tenant_id, sales_line_id=sales_line_id)
    return {
        "salesLineId": str(sales_line_id),
        "cancellationStateOverride": overrides.cancellation_state_override,
        "returnStatusOverride": overrides.return_status_override,
        "rtoStatusOverride": overrides.rto_status_override,
        "returnedQtyOverride": overrides.returned_qty_override,
        "rtoQtyOverride": overrides.rto_qty_override,
    }


class DeclareLineCountOverrideHttpRequest(BaseModel):
    """Mirrors `DeclareLineStatusOverrideHttpRequest`'s shape, `value` typed `int` instead of
    `str` — the two count-shaped fields (`returned_qty_override`/`rto_qty_override`) validated
    by `declare_line_count_override` itself, not by this model."""

    sales_line_id: UUID
    field: str = Field(min_length=1)
    value: int
    reason: str | None = None
    supersedes_id: UUID | None = None


@router.put("/line-count-override")
def put_line_count_override(
    body: DeclareLineCountOverrideHttpRequest, ctx: AuthContext = require_auth(permission=AGENT_CFO)
) -> dict[str, str]:
    """Sibling write route to `PUT /cfo/line-status-override`, for the two count-shaped fields
    no real report/adapter supplies today (deterministic-engine.md §7.2.1). Same second gate
    (`financials.adjust`) as every other manual-input write route."""
    assert ctx.tenant_id is not None
    _require_cfo_entitlement(ctx.tenant_id, direct_action_code=CFO_LINE_STATUS_OVERRIDE)
    if ctx.role is None or not has_permission(role=ctx.role, permissions=ctx.permissions, key=FINANCIALS_ADJUST):
        raise HTTPException(status_code=403, detail="financials.adjust permission required")

    try:
        manual_adjustment_id = declare_line_count_override(
            ctx.tenant_id,
            DeclareLineCountOverrideRequest(
                sales_line_id=body.sales_line_id,
                field=body.field,
                value=body.value,
                created_by=ctx.app_user_id,
                reason=body.reason,
                supersedes_id=body.supersedes_id,
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None

    return {"manualAdjustmentId": str(manual_adjustment_id)}


class GstLineRequest(BaseModel):
    """One line for `analyze_gst_lines` — never accepts a period range; this endpoint has no
    concept of a period total (cfo-agent.md §6.6, `gst/summary.py` stays a stub)."""

    line_ref: str = Field(min_length=1)
    listed_paise: int
    basis: str = Field(pattern="^(INCLUSIVE|EXCLUSIVE)$")
    rate_pct: str | None = None  # decimal string, e.g. "18" or "18.00" — parsed to Fraction below


class AnalyzeGstLinesRequest(BaseModel):
    lines: list[GstLineRequest] = Field(min_length=1)
    as_of_date: date


@router.post("/gst/analyze-lines")
def post_analyze_gst_lines(
    body: AnalyzeGstLinesRequest, ctx: AuthContext = require_auth(permission=AGENT_CFO)
) -> dict[str, object]:
    """Line-level GST analysis (§6.6) — `normalize_to_exclusive` + `check_rate_plausibility`
    per line, every result carrying the §6.6 management-grade disclaimer. **Not a period
    summary; returns no total.**"""
    assert ctx.tenant_id is not None
    _require_cfo_entitlement(ctx.tenant_id, direct_action_code=CFO_ANALYZE_GST_LINES)
    parsed_lines = [
        GstLineInput(
            line_ref=line.line_ref,
            listed_paise=line.listed_paise,
            basis=line.basis,  # type: ignore[arg-type]
            rate_pct=Fraction(line.rate_pct) if line.rate_pct is not None else None,
        )
        for line in body.lines
    ]
    results = analyze_gst_lines(ctx.tenant_id, parsed_lines, as_of_date=body.as_of_date)
    return {"lines": [_gst_line_result_to_dict(r) for r in results]}


def _pricing_metric_result_to_dict(result: Any) -> dict[str, object]:
    return {
        "engineResultRef": str(result.id),
        "metricCode": result.metric_code,
        "valuePaise": result.value_paise,
        "isAvailable": result.is_available,
        "confidence": result.confidence,
        "calculationBasis": result.calculation_basis,
        "unavailableReason": result.unavailable_reason,
        "asOfDate": result.as_of_date.isoformat() if result.as_of_date else None,
    }


class PricingCurveHttpRequest(BaseModel):
    """One SKU, a set of candidate prices — never a single "optimal price" request (D4/AC12).
    `cogs_paise`/`return_rto_losses_paise` are `None` when that input is genuinely
    UNAVAILABLE to the caller (E14: refused with a data request, never an assumed cost), not
    a way to spell zero."""

    sku: str = Field(min_length=1)
    candidate_prices_paise: list[int] = Field(min_length=1)
    basis: str = Field(pattern="^(INCLUSIVE|EXCLUSIVE)$")
    gst_rate_pct: str | None = None  # decimal string, e.g. "18"; None = no GST component
    marketplace: str = Field(min_length=1)
    category: str = Field(min_length=1)
    fee_type: str = Field(min_length=1)
    as_of_date: date
    cogs_paise: int | None = None
    cogs_unavailable_reason: str | None = None
    shipping_logistics_paise: int = 0
    advertising_costs_paise: int = 0
    return_rto_losses_paise: int | None = None
    return_rto_losses_unavailable_reason: str | None = None
    other_allocated_costs_paise: int = 0
    ingestion_run_ids: list[str] = Field(default_factory=list)
    adapter_versions: list[str] = Field(default_factory=list)
    active_adjustment_ids: list[str] = Field(default_factory=list)


@router.post("/pricing")
def post_pricing_curve(
    body: PricingCurveHttpRequest, ctx: AuthContext = require_auth(permission=AGENT_CFO)
) -> dict[str, object]:
    """Direct-execution path (`cfo-agent.md` §6.8 `cfo.pricing`) for `backend.services.
    cfo_actions.compute_pricing_curve` — same composition root `agents.ceo_hub.dispatch_cfo_
    pricing` uses (C20). Returns a margin curve (one row per candidate price), never a single
    optimal price (D4/AC12)."""
    assert ctx.tenant_id is not None
    _require_cfo_entitlement(ctx.tenant_id, direct_action_code=CFO_PRICING)

    cogs: Paise | Unavailable = (
        Paise(body.cogs_paise)
        if body.cogs_paise is not None
        else Unavailable(
            reason=body.cogs_unavailable_reason or "cogs_per_unit not supplied",
            missing_inputs=("cogs_per_unit",),
        )
    )
    return_rto_losses: Paise | Unavailable = (
        Paise(body.return_rto_losses_paise)
        if body.return_rto_losses_paise is not None
        else Unavailable(
            reason=body.return_rto_losses_unavailable_reason or "rto_outcome not supplied",
            missing_inputs=("return_rto_losses",),
        )
    )

    request = PricingCurveRequest(
        sku=body.sku,
        candidate_prices=[Paise(p) for p in body.candidate_prices_paise],
        basis=body.basis,  # type: ignore[arg-type]
        gst_rate=Fraction(body.gst_rate_pct) if body.gst_rate_pct is not None else None,
        marketplace=body.marketplace,
        category=body.category,
        fee_type=body.fee_type,
        as_of_date=body.as_of_date,
        cogs=cogs,
        shipping_logistics=Paise(body.shipping_logistics_paise),
        advertising_costs=Paise(body.advertising_costs_paise),
        return_rto_losses=return_rto_losses,
        other_allocated_costs=Paise(body.other_allocated_costs_paise),
        ingestion_run_ids=body.ingestion_run_ids,
        adapter_versions=body.adapter_versions,
        active_adjustment_ids=body.active_adjustment_ids,
        requested_by=ctx.app_user_id,
    )
    outcome = compute_pricing_curve(ctx.tenant_id, request)

    return {
        "curve": [_pricing_metric_result_to_dict(r) for r in outcome.curve],
        "dataRequestId": str(outcome.data_request_id) if outcome.data_request_id is not None else None,
    }


class PeriodPnlLineRequest(BaseModel):
    """One full `CanonicalLine` for `cfo.pnl` (cfo-agent.md §6.8 `cfo.pnl`) — deliberately NOT
    `GstPeriodSummaryLineRequest` (the shape `/gst/period-summary` and `/batch-size` already
    accept over HTTP). That shape is a documented reduction: its own docstring states it never
    carries a line's cancellation/return/RTO status because the GST period summary has no use
    for them. `compute_period_pnl` genuinely needs those fields — `NetRealizedRevenue` consumes
    `cancellation_state`/`return_status`/`refunded_amount` (§5.4/§5.7) and `ReturnRTOLosses`
    consumes `rto_status`/`rto_outcome` (§5.6/§5.7) — reusing the reduced shape here would
    silently null every line's status and misreport a resolvable marketplace (e.g. Meesho) as
    UNAVAILABLE (E9-style), exactly the silent-wrong-default this codebase's hard rule forbids.
    This model is therefore the fuller `CanonicalLine` shape `compute_period_pnl`'s own test
    fixtures (`packages/cfo/tests/unit/test_cfo_actions_pnl.py::_line`) construct — still
    caller-assembled (`PeriodPnlRequest`'s own docstring, judgment call 4: this composition
    does not derive a `CanonicalLine` from raw `sales_line`/`line_component` rows itself), just
    not truncated to the GST-only subset."""

    sales_line_id: UUID
    marketplace: str
    document_type: str
    quantity: int
    invoice_date: date | None = None
    dispatch_date: date | None = None
    order_date: date | None = None
    gross_item_amount_paise: int
    components: list[dict[str, Any]]  # ComponentRow-shaped dicts: component_kind/component_code/source_side/amount_paise
    confidence: str = "VERIFIED"
    cancellation_state: str | None = None
    return_status: str | None = None
    returned_qty: int = 0
    refunded_amount_paise: int | None = None
    rto_status: str | None = None
    rto_qty: int = 0
    rto_outcome: str | None = None
    quarantine_rule_ids: list[str] = Field(default_factory=list)


def _period_pnl_line_to_canonical(line: PeriodPnlLineRequest) -> CanonicalLine:
    components = tuple(
        ComponentRow(
            id=UUID(c["id"]) if "id" in c else UUID(int=0),
            component_kind=c["component_kind"],
            component_code=c["component_code"],
            source_side=c["source_side"],
            amount=Paise(int(c["amount_paise"])),
        )
        for c in line.components
    )
    return CanonicalLine(
        sales_line_id=line.sales_line_id,
        marketplace=line.marketplace,
        document_type=line.document_type,
        quantity=line.quantity,
        invoice_date=line.invoice_date,
        dispatch_date=line.dispatch_date,
        order_date=line.order_date,
        gross_item_amount=Paise(line.gross_item_amount_paise),
        components=components,
        confidence=Confidence(line.confidence),
        cancellation_state=line.cancellation_state,
        return_status=line.return_status,
        returned_qty=line.returned_qty,
        refunded_amount=(Paise(line.refunded_amount_paise) if line.refunded_amount_paise is not None else None),
        rto_status=line.rto_status,
        rto_qty=line.rto_qty,
        rto_outcome=line.rto_outcome,
        quarantine_rule_ids=tuple(line.quarantine_rule_ids),
    )


class CostEntryHttpRequest(BaseModel):
    """One `cogs_per_unit` weighted-average-cost data point (§7.2.1) — `CostEntry`'s own shape."""

    amount_paise: int
    effective_from: date


class PeriodPnlHttpRequest(BaseModel):
    """Everything `PeriodPnlRequest` needs (cfo-agent.md §6.8 `cfo.pnl`) — caller-assembled,
    same convention `/gst/period-summary` and `/batch-size` already established for
    already-resolved `CanonicalLine`/cost-history/component-code inputs over HTTP.
    `compute_period_pnl` is a composition over already-assembled canonical data, not a raw
    ingestion endpoint (`PeriodPnlRequest`'s own docstring, judgment call 4): a client posts the
    lines it has already fetched from its own store, exactly as every other multi-line CFO
    route in this file does — this is not a novel shape for this file, just the first time it
    is paired with `cfo.pnl` specifically."""

    lines: list[PeriodPnlLineRequest] = Field(min_length=1)
    period_start: date
    period_end: date
    as_of_date: date
    recognition_state: str = Field(pattern="^(RECOGNISED|REALIZED|UNAVAILABLE)$")
    sku_by_line: dict[str, str] = Field(default_factory=dict)
    cost_history_by_sku: dict[str, list[CostEntryHttpRequest]] = Field(default_factory=dict)
    fee_component_codes: list[str] = Field(default_factory=list)
    forward_logistics_codes: list[str] = Field(default_factory=list)
    reverse_logistics_codes: list[str] = Field(default_factory=list)
    non_refunded_fee_codes: list[str] = Field(default_factory=list)
    advertising_adjustment_values: list[dict[str, Any]] = Field(default_factory=list)
    other_adjustment_values: list[dict[str, Any]] = Field(default_factory=list)
    ingestion_run_ids: list[str] = Field(default_factory=list)
    adapter_versions: list[str] = Field(default_factory=list)
    active_adjustment_ids: list[str] = Field(default_factory=list)
    duplicate_fee_candidate_codes: list[str] = Field(default_factory=list)


def _period_pnl_metric_result_to_dict(result: Any) -> dict[str, object]:
    """Same shape `_pricing_metric_result_to_dict` returns, extended with `valueFraction` —
    `CONTRIBUTION_MARGIN_PCT` is this file's first Fraction-valued (percentage) `MetricResult`
    (`value_fraction`, populated INSTEAD OF `value_paise`, never alongside it — see
    `calc_engine.api.compute_metric.MetricResult.value_fraction`'s own docstring). Serialized as
    a decimal string, the same convention `likelyRatePct` already uses elsewhere in this file.
    `_pricing_metric_result_to_dict` itself is deliberately left untouched — every other route
    in this file keeps exactly the dict shape it always has."""
    base = _pricing_metric_result_to_dict(result)
    base["valueFraction"] = str(result.value_fraction) if result.value_fraction is not None else None
    return base


@router.post("/pnl")
def post_period_pnl(
    body: PeriodPnlHttpRequest, ctx: AuthContext = require_auth(permission=AGENT_CFO)
) -> dict[str, object]:
    """Direct-execution path (cfo-agent.md §6.8 `cfo.pnl`) for `backend.services.cfo_actions.
    compute_period_pnl` — the same composition root `agents.ceo_hub.dispatch_cfo_pnl` uses
    (C20; `dispatch_cfo_pnl`'s own docstring already refers to "the same composition root
    `api/v1/cfo.py`'s direct-execution route uses", which was true in intent but never actually
    wired until this route). Persists `NET_REALIZED_REVENUE`, `CONTRIBUTION_PROFIT`,
    `CONTRIBUTION_MARGIN_PCT`, `MARKETPLACE_FEES`, `FEE_RATIO_PCT` and `RETURN_RATE_PCT`
    (TENANT_PERIOD grain) and returns all six, plus any `marketplace_fee_flags`
    duplicate-fee-candidate warnings and a `dataRequestId` when COGS or RTO classification came
    back UNAVAILABLE (E2)."""
    assert ctx.tenant_id is not None
    _require_cfo_entitlement(ctx.tenant_id, direct_action_code=CFO_PNL)

    lines = [_period_pnl_line_to_canonical(line) for line in body.lines]
    cost_history_by_sku = {
        sku: [CostEntry(amount_paise=Paise(e.amount_paise), effective_from=e.effective_from) for e in entries]
        for sku, entries in body.cost_history_by_sku.items()
    }

    request = PeriodPnlRequest(
        lines=lines,
        period_start=body.period_start,
        period_end=body.period_end,
        as_of_date=body.as_of_date,
        recognition_state=RecognitionState(body.recognition_state),
        sku_by_line=body.sku_by_line,
        cost_history_by_sku=cost_history_by_sku,
        fee_component_codes=frozenset(body.fee_component_codes),
        forward_logistics_codes=frozenset(body.forward_logistics_codes),
        reverse_logistics_codes=frozenset(body.reverse_logistics_codes),
        non_refunded_fee_codes=frozenset(body.non_refunded_fee_codes),
        advertising_adjustment_values=body.advertising_adjustment_values,
        other_adjustment_values=body.other_adjustment_values,
        ingestion_run_ids=body.ingestion_run_ids,
        adapter_versions=body.adapter_versions,
        active_adjustment_ids=body.active_adjustment_ids,
        requested_by=ctx.app_user_id,
        duplicate_fee_candidate_codes=frozenset(body.duplicate_fee_candidate_codes),
    )
    outcome = compute_period_pnl(ctx.tenant_id, request)

    return {
        "nrr": _period_pnl_metric_result_to_dict(outcome.nrr),
        "contributionProfit": _period_pnl_metric_result_to_dict(outcome.contribution_profit),
        "marginPct": _period_pnl_metric_result_to_dict(outcome.margin_pct),
        "feeRatioPct": _period_pnl_metric_result_to_dict(outcome.fee_ratio_pct),
        "returnRatePct": _period_pnl_metric_result_to_dict(outcome.return_rate_pct),
        "marketplaceFeeFlags": list(outcome.marketplace_fee_flags),
        "dataRequestId": str(outcome.data_request_id) if outcome.data_request_id is not None else None,
    }


class PeriodPnlForTenantHttpRequest(BaseModel):
    """The real, DB-driven counterpart to `PeriodPnlHttpRequest` — no `lines`/`sku_by_line`/
    `cost_history_by_sku`/`ingestion_run_ids`/`active_adjustment_ids` fields at all, since
    `compute_period_pnl_for_tenant` auto-derives every one of them from the real database
    (cfo-agent.md §6.16). The four component-code classification sets remain caller-supplied —
    genuine tenant/business classifications this composition does not guess."""

    period_start: date
    period_end: date
    as_of_date: date
    recognition_state: str = Field(pattern="^(RECOGNISED|REALIZED|UNAVAILABLE)$")
    fee_component_codes: list[str] = Field(default_factory=list)
    forward_logistics_codes: list[str] = Field(default_factory=list)
    reverse_logistics_codes: list[str] = Field(default_factory=list)
    non_refunded_fee_codes: list[str] = Field(default_factory=list)
    advertising_adjustment_values: list[dict[str, Any]] = Field(default_factory=list)
    other_adjustment_values: list[dict[str, Any]] = Field(default_factory=list)
    duplicate_fee_candidate_codes: list[str] = Field(default_factory=list)


def _canonical_assembly_blocked_line_to_dict(blocked: Any) -> dict[str, object]:
    return {
        "salesLineId": str(blocked.sales_line_id),
        "reason": blocked.reason,
        "missingInputs": list(blocked.missing_inputs),
    }


@router.post("/pnl-for-tenant")
def post_period_pnl_for_tenant(
    body: PeriodPnlForTenantHttpRequest, ctx: AuthContext = require_auth(permission=AGENT_CFO)
) -> dict[str, object]:
    """Direct-execution path (cfo-agent.md §6.16, the ingestion-to-canonical composition layer)
    for `backend.services.cfo_actions.compute_period_pnl_for_tenant`. Unlike `POST /cfo/pnl`,
    this route reads real `sales_line`/`line_component`/`manual_adjustment` rows for the period
    and assembles them itself — the caller supplies only the period, the recognition state, and
    the four component-code classification sets. `pnl: null` with real `blockedLines`/
    `dataRequestIds` (never a fabricated result) is the correct, honest outcome when every real
    line for this period was blocked or none exist."""
    assert ctx.tenant_id is not None
    _require_cfo_entitlement(ctx.tenant_id, direct_action_code=CFO_PNL)

    outcome = compute_period_pnl_for_tenant(
        ctx.tenant_id,
        PeriodPnlForTenantRequest(
            period_start=body.period_start,
            period_end=body.period_end,
            as_of_date=body.as_of_date,
            recognition_state=RecognitionState(body.recognition_state),
            fee_component_codes=frozenset(body.fee_component_codes),
            forward_logistics_codes=frozenset(body.forward_logistics_codes),
            reverse_logistics_codes=frozenset(body.reverse_logistics_codes),
            non_refunded_fee_codes=frozenset(body.non_refunded_fee_codes),
            advertising_adjustment_values=body.advertising_adjustment_values,
            other_adjustment_values=body.other_adjustment_values,
            duplicate_fee_candidate_codes=frozenset(body.duplicate_fee_candidate_codes),
            requested_by=ctx.app_user_id,
        ),
    )

    return {
        "pnl": (
            None
            if outcome.pnl is None
            else {
                "nrr": _period_pnl_metric_result_to_dict(outcome.pnl.nrr),
                "contributionProfit": _period_pnl_metric_result_to_dict(outcome.pnl.contribution_profit),
                "marginPct": _period_pnl_metric_result_to_dict(outcome.pnl.margin_pct),
                "feeRatioPct": _period_pnl_metric_result_to_dict(outcome.pnl.fee_ratio_pct),
                "returnRatePct": _period_pnl_metric_result_to_dict(outcome.pnl.return_rate_pct),
                "marketplaceFeeFlags": list(outcome.pnl.marketplace_fee_flags),
                "dataRequestId": (
                    str(outcome.pnl.data_request_id) if outcome.pnl.data_request_id is not None else None
                ),
            }
        ),
        "assembledLineCount": outcome.assembled_line_count,
        "blockedLines": [_canonical_assembly_blocked_line_to_dict(b) for b in outcome.blocked_lines],
        "dataRequestIds": [str(i) for i in outcome.data_request_ids],
    }


class GstPeriodSummaryLineRequest(BaseModel):
    """One canonical line's tax-relevant fields for the PERIOD summary. Deliberately a
    different shape from `GstLineRequest` (which drives the LINE-level `/gst/analyze-lines`
    route) — this route has no concept of a single line's own rate/plausibility, only the tax
    components that feed the period total."""

    sales_line_id: UUID
    marketplace: str
    document_type: str
    quantity: int
    gross_item_amount_paise: int
    components: list[dict[str, Any]]  # ComponentRow-shaped dicts: component_kind/component_code/source_side/amount_paise
    confidence: str = "CONFIRMED"


class GstPeriodSummaryHttpRequest(BaseModel):
    """A period range, never a single line — the inverse of `AnalyzeGstLinesRequest`. This is
    `cfo.gst_summary` (§6.6/§6.8), genuinely distinct from `/gst/analyze-lines`; the two routes
    are never interchangeable and never share a request/response model."""

    lines: list[GstPeriodSummaryLineRequest]
    period_start: date
    period_end: date
    as_of_date: date
    tax_heads: list[str] | None = None
    ingestion_run_ids: list[str] = Field(default_factory=list)
    adapter_versions: list[str] = Field(default_factory=list)
    active_adjustment_ids: list[str] = Field(default_factory=list)


def _gst_period_summary_line_to_canonical(line: GstPeriodSummaryLineRequest) -> Any:
    from calc_engine.types import CanonicalLine, ComponentRow, Confidence

    components = tuple(
        ComponentRow(
            id=UUID(c["id"]) if "id" in c else UUID(int=0),
            component_kind=c["component_kind"],
            component_code=c["component_code"],
            source_side=c["source_side"],
            amount=Paise(int(c["amount_paise"])),
        )
        for c in line.components
    )
    return CanonicalLine(
        sales_line_id=line.sales_line_id,
        marketplace=line.marketplace,
        document_type=line.document_type,
        quantity=line.quantity,
        invoice_date=None,
        dispatch_date=None,
        order_date=None,
        gross_item_amount=Paise(line.gross_item_amount_paise),
        components=components,
        confidence=Confidence(line.confidence),
    )


@router.post("/gst/period-summary")
def post_gst_period_summary(
    body: GstPeriodSummaryHttpRequest, ctx: AuthContext = require_auth(permission=AGENT_CFO)
) -> dict[str, object]:
    """Direct-execution path (cfo-agent.md §6.6/§6.8 `cfo.gst_summary`) for
    `backend.services.cfo_actions.render_gst_period_summary` — the same composition root
    `agents.ceo_hub.dispatch_cfo_gst_summary` uses (C20). Returns the PERIOD total, one row per
    tax head; **not** the LINE-level result `/gst/analyze-lines` returns, and this route never
    calls that one."""
    assert ctx.tenant_id is not None
    _require_cfo_entitlement(ctx.tenant_id, direct_action_code=CFO_GST_SUMMARY)

    lines = [_gst_period_summary_line_to_canonical(line) for line in body.lines]
    request = GstPeriodSummaryRequest(
        lines=lines,
        period_start=body.period_start,
        period_end=body.period_end,
        as_of_date=body.as_of_date,
        ingestion_run_ids=body.ingestion_run_ids,
        adapter_versions=body.adapter_versions,
        active_adjustment_ids=body.active_adjustment_ids,
        requested_by=ctx.app_user_id,
        **({"tax_heads": frozenset(body.tax_heads)} if body.tax_heads is not None else {}),
    )
    outcome = render_gst_period_summary(ctx.tenant_id, request)

    return {
        "results": [_pricing_metric_result_to_dict(r) for r in outcome.results],
        "disclaimer": outcome.disclaimer,
    }


class PeriodComparisonHttpRequest(BaseModel):
    """Two already-persisted `metric_result` ids for the SAME `metric_code` — e.g. this
    period's `CONTRIBUTION_PROFIT` vs. last period's. Never accepts raw figures; the whole
    point of this route (cfo-agent.md §7.4.4's "once built" rule, twinkly-mapping-canyon.md
    CP A3) is to compare two figures the engine has ALREADY computed and persisted."""

    result_a_id: UUID
    result_b_id: UUID
    as_of_date: date
    model: str | None = None


@router.post("/period-comparison")
def post_period_comparison(
    body: PeriodComparisonHttpRequest, ctx: AuthContext = require_auth(permission=AGENT_CFO)
) -> dict[str, object]:
    """Direct-execution path (cfo-agent.md §7.4.4, twinkly-mapping-canyon.md CP A3) for
    `backend.services.cfo_actions.narrate_period_comparison` — the same composition root
    `agents.ceo_hub.dispatch_cfo_period_comparison` uses (C20). This is the first real caller
    of `cfo.reasoning.narrate.narrate_figures` from `backend/`; the `LlmProvider` is wired here
    exactly the way `ollama_provider.py`'s own docstring specifies (local Ollama, `host` from
    `backend.config.ollama_host()`, C15: always local, never a hosted provider) — the same
    provider-instantiation shape `api/v1/ci.py` already uses for CI's vision extractor, applied
    to CFO's text-only narration provider instead."""
    assert ctx.tenant_id is not None
    _require_cfo_entitlement(ctx.tenant_id, direct_action_code=CFO_PERIOD_COMPARISON)

    request = PeriodComparisonRequest(
        result_a_id=body.result_a_id,
        result_b_id=body.result_b_id,
        as_of_date=body.as_of_date,
        requested_by=ctx.app_user_id,
    )
    provider = OllamaLlmProvider(host=ollama_host())
    outcome = narrate_period_comparison(
        ctx.tenant_id, request, provider, model=body.model or cfo_narration_model()
    )

    return {
        "delta": _pricing_metric_result_to_dict(outcome.delta) if outcome.delta is not None else None,
        "narration": outcome.narration,
        "dataRequestId": str(outcome.data_request_id) if outcome.data_request_id is not None else None,
    }


class LandedCostHttpRequest(BaseModel):
    """One SKU, one `supplier.quote` target — never a set of quotes to compare (that is
    supplier ranking, Phase B1, not this primitive). `supplier_quote_target_type`/
    `supplier_quote_target_ref` identify exactly the `(target_type, target_ref)` a seller used
    when recording the quote via `PUT /cfo/expenses` (`EnterExpenseRequest`'s own
    `target_type`/`target_ref` fields) — this route reads back what that write path wrote."""

    sku: str = Field(min_length=1)
    supplier_quote_target_type: str = Field(pattern="^(SKU|ACCOUNT|PERIOD)$")
    supplier_quote_target_ref: str = Field(min_length=1)
    quantity: int = Field(gt=0)
    as_of_date: date | None = None
    active_adjustment_ids: list[str] = Field(default_factory=list)


@router.post("/landed-cost")
def post_landed_cost(
    body: LandedCostHttpRequest, ctx: AuthContext = require_auth(permission=AGENT_CFO)
) -> dict[str, object]:
    """Direct-execution path (cfo-agent.md §6.11 supplier-ranking *primitive*,
    `twinkly-mapping-canyon.md` CP A4) for `backend.services.cfo_actions.
    compute_landed_cost_for_quote` — the same composition root `agents.ceo_hub.
    dispatch_cfo_landed_cost` uses (C20). Returns exactly ONE quote's landed cost; never a
    ranked or compared list (that is Phase B1, not yet built).

    **`POST` with a body, not the roadmap's originally-sketched `GET /cfo/landed-cost`**: this
    request identifies a `(target_type, target_ref)` pair plus a quantity and an optional
    `active_adjustment_ids` list — the same shape `enter_expense`'s `EnterExpenseRequest`
    identifies a manual_adjustment target with, which this codebase always carries as a JSON
    body (`PUT /cfo/expenses`), never as query params. A `GET` with query params could technically
    carry `sku`/`target_type`/`target_ref`/`quantity` as scalars, but `active_adjustment_ids`
    is a list of opaque UUID-or-string tokens whose count is caller-determined and unbounded —
    exactly the shape every other multi-value CFO input in this file (`ingestion_run_ids`,
    `adapter_versions`, `active_adjustment_ids` on `/pricing` and `/gst/period-summary`) is
    already sent as a POST body field, never a repeated query parameter. Matching that existing
    convention over the roadmap's shorthand naming is the correct engineering choice here."""
    assert ctx.tenant_id is not None
    _require_cfo_entitlement(ctx.tenant_id, direct_action_code=CFO_LANDED_COST)

    request = LandedCostRequest(
        sku=body.sku,
        supplier_quote_target_type=body.supplier_quote_target_type,
        supplier_quote_target_ref=body.supplier_quote_target_ref,
        quantity=body.quantity,
        active_adjustment_ids=body.active_adjustment_ids,
        requested_by=ctx.app_user_id,
        as_of_date=body.as_of_date,
    )

    try:
        outcome = compute_landed_cost_for_quote(ctx.tenant_id, request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None

    return {
        "result": _pricing_metric_result_to_dict(outcome.result) if outcome.result is not None else None,
        "dataRequestId": str(outcome.data_request_id) if outcome.data_request_id is not None else None,
    }


class SupplierRankingHttpRequest(BaseModel):
    """One SKU — ranks every ACTIVE `supplier.quote` row for it by landed cost (cfo-agent.md
    §6.11, `twinkly-mapping-canyon.md` Phase B1). No `target_type`/`target_ref` fields here
    (unlike `LandedCostHttpRequest`): `rank_suppliers` fixes `target_type="SKU"` internally,
    per CP A4's own established convention that multiple suppliers quoting the same SKU land
    as multiple ACTIVE rows under one `(target_type="SKU", target_ref=sku)` pair — `sku` alone
    is the lookup key."""

    sku: str = Field(min_length=1)
    quantity: int = Field(gt=0)
    as_of_date: date | None = None
    active_adjustment_ids: list[str] = Field(default_factory=list)


def _ranked_supplier_quote_to_dict(entry: Any) -> dict[str, object]:
    return {
        "result": _pricing_metric_result_to_dict(entry.result),
        "supplierName": entry.supplier_name,
        "reliabilityNote": entry.reliability_note,
        "paymentTerms": entry.payment_terms,
        "leadTimeDays": entry.lead_time_days,
        "moq": entry.moq,
    }


def _quarantined_supplier_quote_to_dict(entry: Any) -> dict[str, object]:
    return {
        "adjustmentId": str(entry.adjustment_id),
        "supplierName": entry.supplier_name,
        "reason": entry.reason,
    }


@router.post("/suppliers/rank")
def post_rank_suppliers(
    body: SupplierRankingHttpRequest, ctx: AuthContext = require_auth(permission=AGENT_CFO)
) -> dict[str, object]:
    """Direct-execution path (cfo-agent.md §6.11 supplier ranking, `twinkly-mapping-canyon.md`
    CP B1) for `backend.services.cfo_actions.rank_suppliers` — the same composition root
    `agents.ceo_hub.dispatch_cfo_supplier_ranking` uses (C20). Ranks every ACTIVE
    `supplier.quote` row for the given SKU ascending by landed cost per unit; `isSingleQuote`
    is `True` when exactly one quote computed (E15: reported as a single quote, not a
    ranking), and `quarantined` discloses any row that failed to parse without aborting the
    ranking of the rest (E8 precedent)."""
    assert ctx.tenant_id is not None
    _require_cfo_entitlement(ctx.tenant_id, direct_action_code=CFO_SUPPLIER_RANKING)

    request = SupplierRankingRequest(
        sku=body.sku,
        quantity=body.quantity,
        active_adjustment_ids=body.active_adjustment_ids,
        requested_by=ctx.app_user_id,
        as_of_date=body.as_of_date,
    )

    try:
        outcome = rank_suppliers(ctx.tenant_id, request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None

    return {
        "ranked": [_ranked_supplier_quote_to_dict(r) for r in outcome.ranked],
        "quarantined": [_quarantined_supplier_quote_to_dict(q) for q in outcome.quarantined],
        "isSingleQuote": outcome.is_single_quote,
        "dataRequestId": str(outcome.data_request_id) if outcome.data_request_id is not None else None,
    }


class FundingReadinessHttpRequest(BaseModel):
    """A period range plus the caller's own explicit statement of which period labels it
    expected a `CONTRIBUTION_PROFIT` result for (cfo-agent.md §6.13, `twinkly-mapping-canyon.md`
    CP B2). `expected_periods` entries must be in the same `"{start}/{end}"` ISO-date-range
    shape `compute_period_pnl` already persists to `metric_result.period` — CFO has no
    periodicity assumption of its own (see `FundingReadinessRequest`'s own docstring); an empty
    list means "no missing-period check requested", not "no periods were expected"."""

    period_start: date
    period_end: date
    as_of_date: date
    expected_periods: list[str] = Field(default_factory=list)


def _funding_readiness_gap_to_dict(gap: Any) -> dict[str, object]:
    return {"kind": gap.kind, "period": gap.period, "reason": gap.reason}


def _deferred_section_to_dict(section: Any) -> dict[str, object]:
    return {"name": section.name, "reason": section.reason, "blockedOn": section.blocked_on}


@router.post("/funding-readiness")
def post_funding_readiness(
    body: FundingReadinessHttpRequest, ctx: AuthContext = require_auth(permission=AGENT_CFO)
) -> dict[str, object]:
    """Direct-execution path (cfo-agent.md §6.8 `cfo.funding_readiness`, `twinkly-mapping-
    canyon.md` CP B2) for `backend.services.cfo_actions.assemble_funding_readiness_reduced` —
    the same composition root `agents.ceo_hub.dispatch_cfo_funding_readiness` uses (C20).

    This is the REDUCED §6.13 slice: Contribution Profit history, period-over-period trend,
    explicit gaps (periods missing, COGS/RTO-classification absent), and — real wherever Leak
    Shield reconciliation has already run for this tenant/period — `cashConversionTiming`
    (`SETTLEMENT_LAG_DAYS`, anomaly-detection.md §6.1/§6.6). **No score, valuation or lending
    judgement anywhere** (AC19) — the response has no "readiness score" or "risk rating" field.
    Margin stability and revenue concentration are still NOT included; `deferredSections` states
    this explicitly on every response, and adds `cash_conversion_timing` back to that list only
    for a period where no `SETTLEMENT_LAG_DAYS` row exists yet — never a fabricated day count."""
    assert ctx.tenant_id is not None
    _require_cfo_entitlement(ctx.tenant_id, direct_action_code=CFO_FUNDING_READINESS)

    request = FundingReadinessRequest(
        period_start=body.period_start,
        period_end=body.period_end,
        as_of_date=body.as_of_date,
        requested_by=ctx.app_user_id,
        expected_periods=body.expected_periods,
    )
    outcome = assemble_funding_readiness_reduced(ctx.tenant_id, request)

    return {
        "contributionProfitHistory": [
            _pricing_metric_result_to_dict(r) for r in outcome.contribution_profit_history
        ],
        "trend": [_pricing_metric_result_to_dict(r) for r in outcome.trend],
        "gaps": [_funding_readiness_gap_to_dict(g) for g in outcome.gaps],
        "deferredSections": [_deferred_section_to_dict(s) for s in outcome.deferred_sections],
        "dataRequestId": str(outcome.data_request_id) if outcome.data_request_id is not None else None,
        "cashConversionTiming": [_pricing_metric_result_to_dict(r) for r in outcome.cash_conversion_timing],
    }


class BatchSizeHttpRequest(BaseModel):
    """One SKU, one chosen `supplier.quote`, one `batch.budget` target, plus already-assembled
    sales history (cfo-agent.md §6.12, `twinkly-mapping-canyon.md` CP B3b). `lines` reuses
    `GstPeriodSummaryLineRequest`'s shape (the same already-assembled-`CanonicalLine` request
    field convention `POST /cfo/gst/period-summary` already established) — an empty `lines`
    list is this route's own way of expressing "no sales history for this SKU", exactly §6.12's
    own "never sold" case, never a request-validation error."""

    sku: str = Field(min_length=1)
    supplier_quote_target_type: str = Field(pattern="^(SKU|ACCOUNT|PERIOD)$")
    supplier_quote_target_ref: str = Field(min_length=1)
    budget_target_type: str = Field(pattern="^(SKU|ACCOUNT)$")
    budget_target_ref: str = Field(min_length=1)
    lines: list[GstPeriodSummaryLineRequest] = Field(default_factory=list)
    period_start: date
    period_end: date
    as_of_date: date
    active_adjustment_ids: list[str] = Field(default_factory=list)


@router.post("/batch-size")
def post_batch_size(
    body: BatchSizeHttpRequest, ctx: AuthContext = require_auth(permission=AGENT_CFO)
) -> dict[str, object]:
    """Direct-execution path (cfo-agent.md §6.12/D9 "batch size", `twinkly-mapping-canyon.md`
    CP B3b) for `backend.services.cfo_actions.assemble_batch_size_estimate` — the same
    composition root `agents.ceo_hub.dispatch_cfo_batch_size` uses (C20).

    Returns a budget-constrained order-quantity ESTIMATE — never a demand forecast, a
    guaranteed sell-through, or a claim about future volume (D9). `velocityStatus` names
    whether the estimate used real observed sales history (`"OBSERVED"`), degraded because the
    SKU has never sold (`"NEVER_SOLD"`), or degraded because velocity came back UNAVAILABLE
    (`"UNAVAILABLE"`) — in the latter two cases the estimate still proceeds (T34) unless the
    quote ALSO names neither `moq` nor `lead_time_days`, per §6.12's precise rule, in which case
    `result` is `None` and `dataRequestId` is set instead.
    `referenceQuantityCaveat(Applies)` discloses the reference-quantity approximation this
    estimate's landed-cost figure rests on (see the composition function's own docstring)."""
    assert ctx.tenant_id is not None
    _require_cfo_entitlement(ctx.tenant_id, direct_action_code=CFO_BATCH_SIZE)

    lines = [_gst_period_summary_line_to_canonical(line) for line in body.lines]
    request = BatchSizeRequest(
        sku=body.sku,
        supplier_quote_target_type=body.supplier_quote_target_type,
        supplier_quote_target_ref=body.supplier_quote_target_ref,
        budget_target_type=body.budget_target_type,
        budget_target_ref=body.budget_target_ref,
        lines=lines,
        period_start=body.period_start,
        period_end=body.period_end,
        as_of_date=body.as_of_date,
        active_adjustment_ids=body.active_adjustment_ids,
        requested_by=ctx.app_user_id,
    )

    try:
        outcome = assemble_batch_size_estimate(ctx.tenant_id, request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None

    return {
        "result": _pricing_metric_result_to_dict(outcome.result) if outcome.result is not None else None,
        "landedCostResult": (
            _pricing_metric_result_to_dict(outcome.landed_cost_result)
            if outcome.landed_cost_result is not None
            else None
        ),
        "velocityStatus": outcome.velocity_status,
        "observedUnitsSold": outcome.observed_units_sold,
        "velocityUnavailableReason": outcome.velocity_unavailable_reason,
        "referenceQuantity": outcome.reference_quantity,
        "referenceQuantityBasis": outcome.reference_quantity_basis,
        "referenceQuantityCaveatApplies": outcome.reference_quantity_caveat_applies,
        "referenceQuantityCaveat": outcome.reference_quantity_caveat,
        "leadTimeDays": outcome.lead_time_days,
        "moq": outcome.moq,
        "dataRequestId": str(outcome.data_request_id) if outcome.data_request_id is not None else None,
    }


class ReconcileHttpRequest(BaseModel):
    """A marketplace and period range for Leak Shield's real reconciliation (D5, cfo-agent.md
    §6.2/§6.8 `cfo.reconcile`). Never accepts raw sales/settlement figures — this route always
    reads the tenant's already-ingested `sales_line`/`settlement_line` rows for the given
    period, exactly as `reconcile()` itself does."""

    marketplace: str = Field(min_length=1)
    period_start: date
    period_end: date
    as_of_date: date


def _leak_shield_outcome_to_dict(outcome: Any) -> dict[str, object]:
    return {
        "reconciliationRunId": str(outcome.reconciliation_run_id),
        "findings": [
            {
                "leakFindingId": str(f["leak_finding_id"]),
                "leakCategory": f["leak_category"],
                "severity": f["severity"],
                "windowStatus": f["window_status"],
                "amountPaise": f["amount_paise"],
                "marketplace": f["marketplace"],
                "engineResultRef": f["engine_result_ref"],
            }
            for f in outcome.findings
        ],
        "matchCount": outcome.match_count,
        "exceptionCount": outcome.exception_count,
        "ambiguousMatchCount": outcome.ambiguous_match_count,
        "datesMissingCount": outcome.dates_missing_count,
    }


@router.post("/reconcile")
def post_reconcile(
    body: ReconcileHttpRequest, ctx: AuthContext = require_auth(permission=AGENT_CFO)
) -> dict[str, object]:
    """Direct-execution path (D5, cfo-agent.md §6.2/§6.8 `cfo.reconcile`) for
    `backend.services.cfo_actions.run_leak_shield_reconciliation` — the same composition root
    `agents.ceo_hub.dispatch_cfo_reconcile` uses (C20). This is the first Leak Shield route
    that produces real, persisted `leak_finding` rows (guardrail 4, now closed) — every
    finding returned here carries a real `engineResultRef` that resolves to a real,
    persisted `metric_result` row (§6.4 rule 5). `AMBIGUOUS_MATCH` exceptions are never
    surfaced here (Decision B, `run_leak_shield_reconciliation`'s own docstring) — only
    counted, via `ambiguousMatchCount`."""
    assert ctx.tenant_id is not None
    _require_cfo_entitlement(ctx.tenant_id, direct_action_code=CFO_RECONCILE)

    outcome = run_leak_shield_reconciliation(
        ctx.tenant_id,
        marketplace=body.marketplace,
        period_start=body.period_start,
        period_end=body.period_end,
        as_of_date=body.as_of_date,
    )

    return _leak_shield_outcome_to_dict(outcome)


class PreviewHttpRequest(BaseModel):
    """A marketplace and period range for the free-tier gated preview (D7, cfo-agent.md
    §6.9/§6.8 `cfo.preview`) — mirrors `ReconcileHttpRequest` exactly, since this route calls
    the same real reconciliation `POST /cfo/reconcile` does; the preview differs only in what
    it reveals, never in what it computes."""

    marketplace: str = Field(min_length=1)
    period_start: date
    period_end: date
    as_of_date: date


def _cfo_preview_outcome_to_dict(outcome: Any) -> dict[str, object]:
    return {
        "headlineTotalPaise": outcome.headline_total_paise,
        "headlineEngineResultRef": outcome.headline_engine_result_ref,
        "affectedSkuCount": outcome.affected_sku_count,
        "affectedSkuCountUnavailable": outcome.affected_sku_count_unavailable,
        "revealedFinding": (
            {
                "leakFindingId": str(outcome.revealed_finding["leak_finding_id"]),
                "leakCategory": outcome.revealed_finding["leak_category"],
                "severity": outcome.revealed_finding["severity"],
                "windowStatus": outcome.revealed_finding["window_status"],
                "amountPaise": outcome.revealed_finding["amount_paise"],
                "marketplace": outcome.revealed_finding["marketplace"],
                "engineResultRef": outcome.revealed_finding["engine_result_ref"],
                "sku": outcome.revealed_finding["sku"],
            }
            if outcome.revealed_finding is not None
            else None
        ),
        "lockedFindingsCount": outcome.locked_findings_count,
    }


@router.post("/preview")
def post_preview(
    body: PreviewHttpRequest, ctx: AuthContext = require_auth(permission=AGENT_CFO)
) -> dict[str, object]:
    """Direct-execution path (D7, cfo-agent.md §6.9/§6.8 `cfo.preview`) for
    `backend.services.cfo_actions.assemble_cfo_preview`.

    **Deliberately does NOT call `_require_cfo_entitlement`.** This is by design, not an
    oversight — do not "fix" this route by adding that check back in. §6.8's own table row for
    `cfo.preview` states the entitlement gate as "Passes permission, then intentionally
    bypasses the entitlement denial", and the prose immediately below that table explains why:
    the CFO capability is still denied for an un-entitled tenant, but the preview is what is
    served **in place of** that denial, not behind it. Calling `_require_cfo_entitlement` here
    would 402 exactly the tenant this route exists to serve, defeating its entire purpose.
    `require_auth(permission=AGENT_CFO)` below is unaffected — permission is never bypassed,
    only entitlement (§6.8: "There is no un-permissioned path. A member without `agent.cfo`
    gets `403`, entitled or not.")."""
    assert ctx.tenant_id is not None

    outcome = assemble_cfo_preview(
        ctx.tenant_id,
        marketplace=body.marketplace,
        period_start=body.period_start,
        period_end=body.period_end,
        as_of_date=body.as_of_date,
    )

    return _cfo_preview_outcome_to_dict(outcome)


class AnomalyCheckHttpRequest(BaseModel):
    """One `target_ref` (SKU/ACCOUNT/MARKETPLACE grain, matching `MetricResult.target_ref`) and
    a lookback window (cfo-agent.md §6.1 rule 4/§6.5/§7, anomaly-detection.md). `MARGIN_PCT` is
    the only series this checkpoint has a real, spec-grounded composition for — this route does
    not accept a `metric` field because there is only one real choice today (§10 P1/P2 name
    `FEE_RATIO_PCT`/`SETTLEMENT_LAG_DAYS`/`RETURN_RATE_PCT` as genuinely out of scope).

    `include_narration` (default `False`, opt-in — see `post_anomaly_check`'s own docstring for
    why this is opt-in rather than always-on) additionally calls `narrate_anomaly_check` and
    returns its prose under `narration`. `model` is only meaningful when `include_narration` is
    `True`; it is ignored otherwise, mirroring `PeriodComparisonHttpRequest.model`'s own
    optional-override shape."""

    target_ref: str = Field(min_length=1)
    period_start: date
    period_end: date
    as_of_date: date
    include_narration: bool = False
    model: str | None = None


def _anomaly_flag_to_dict(flag: Any) -> dict[str, object]:
    return {
        "id": str(flag.id),
        "metric": flag.metric,
        "targetRef": flag.target_ref,
        "period": flag.period.isoformat(),
        "method": flag.method,
        "decoratesEngineResultRef": str(flag.decorates_engine_result_ref),
        "sourceEngineResultRefs": [str(r) for r in flag.source_engine_result_refs],
        "score": str(flag.score),
        "fired": flag.fired,
        "severity": flag.severity,
        "dataConfidence": flag.data_confidence,
        "seriesLength": flag.series_length,
        "minSeriesLengthRequired": flag.min_series_length_required,
        "configVersion": flag.config_version,
        "formulaVersion": flag.formula_version,
        "asOfDate": flag.as_of_date.isoformat(),
        "computedAt": flag.computed_at.isoformat(),
    }


def _anomaly_method_outcome_to_dict(outcome: Any) -> dict[str, object]:
    return {
        "method": outcome.method,
        "flag": _anomaly_flag_to_dict(outcome.flag) if outcome.flag is not None else None,
        "insufficientHistory": (
            {
                "metric": outcome.insufficient_history.metric,
                "method": outcome.insufficient_history.method,
                "targetRef": outcome.insufficient_history.target_ref,
                "seriesLength": outcome.insufficient_history.series_length,
                "minSeriesLengthRequired": outcome.insufficient_history.min_series_length_required,
                "reason": outcome.insufficient_history.reason,
            }
            if outcome.insufficient_history is not None
            else None
        ),
        "zeroVariance": (
            {
                "metric": outcome.zero_variance.metric,
                "method": outcome.zero_variance.method,
                "targetRef": outcome.zero_variance.target_ref,
                "seriesLength": outcome.zero_variance.series_length,
                "reason": outcome.zero_variance.reason,
            }
            if outcome.zero_variance is not None
            else None
        ),
        "configurationGap": (
            {
                "metric": outcome.configuration_gap.metric,
                "method": outcome.configuration_gap.method,
                "targetRef": outcome.configuration_gap.target_ref,
                "reason": outcome.configuration_gap.reason,
            }
            if outcome.configuration_gap is not None
            else None
        ),
    }


@router.post("/anomaly-check")
def post_anomaly_check(
    body: AnomalyCheckHttpRequest, ctx: AuthContext = require_auth(permission=AGENT_CFO)
) -> dict[str, object]:
    """Direct-execution path (E3, cfo-agent.md §6.1 rule 4/§6.5/§7) for
    `backend.services.cfo_actions.run_anomaly_check` — the same composition root
    `agents.ceo_hub.dispatch_cfo_anomaly_check` uses (C20). Runs all three Brain-2 methods
    (Z_SCORE, PERCENTILE_THRESHOLD, PERIOD_OVER_PERIOD_DELTA) against this tenant's persisted
    `CONTRIBUTION_MARGIN_PCT` history for `target_ref` and returns all three outcomes together
    — never just one. Entitlement enforcement is MANDATORY here, unlike `cfo.preview`'s
    documented exemption.

    **Narration is opt-in** (`body.include_narration`, default `False`), NOT always-on like
    `post_period_comparison`'s narration call, which that route makes unconditionally. This is
    a deliberate divergence, not an oversight: `run_anomaly_check` itself is a cheap, pure
    read-plus-statistics composition with no LLM call of its own — this route previously
    returned instantly with zero model cost, and CFO's own model-cost discipline
    (`cfo-agent.md` §7.3.1: "CFO's model cost is flat with respect to seller data volume") means
    that flat cost should stay a deliberate choice a caller opts into, not something every
    structured-data fetch (e.g. a dashboard tile polling this route repeatedly) pays for
    unconditionally. When `include_narration` is `False` (the default), this route's response
    shape is byte-identical to before this checkpoint — no `narration` key is even present."""
    assert ctx.tenant_id is not None
    _require_cfo_entitlement(ctx.tenant_id, direct_action_code=CFO_ANOMALY_CHECK)

    request = AnomalyCheckRequest(
        target_ref=body.target_ref,
        period_start=body.period_start,
        period_end=body.period_end,
        as_of_date=body.as_of_date,
        requested_by=ctx.app_user_id,
    )
    outcome = run_anomaly_check(ctx.tenant_id, request)

    response: dict[str, object] = {
        "targetRef": outcome.target_ref,
        "metric": outcome.metric,
        "seriesLength": outcome.series_length,
        "methods": [_anomaly_method_outcome_to_dict(m) for m in outcome.methods],
    }

    if body.include_narration:
        provider = OllamaLlmProvider(host=ollama_host())
        response["narration"] = narrate_anomaly_check(
            provider, model=body.model or cfo_narration_model(), outcome=outcome
        )

    return response


class FinancialHealthHttpRequest(BaseModel):
    period_start: date
    period_end: date
    as_of_date: date


@router.post("/financial-health")
def post_financial_health(
    body: FinancialHealthHttpRequest, ctx: AuthContext = require_auth(permission=AGENT_CFO)
) -> dict[str, object]:
    """Direct-execution path (cfo-agent.md §6.15, Financial Health Band) for
    `backend.services.cfo_actions.assemble_financial_health`. Classifies this tenant's already-
    persisted `CONTRIBUTION_MARGIN_PCT`/`FEE_RATIO_PCT`/`RETURN_RATE_PCT` for one period into a
    `GOOD`/`WATCH`/`AT_RISK` band per `financial_health_config` — never a new derived figure,
    only a classification of figures `POST /cfo/pnl` already computed and persisted for this
    period. `overallBand: null` with a real `unavailableReason` (never a fabricated `GOOD`) is
    the correct, honest outcome for a period `cfo.pnl` was never run for, or one where every
    metric came back UNAVAILABLE (e.g. deterministic-engine.md §7.2.1's cancellation/RTO-status
    gap)."""
    assert ctx.tenant_id is not None
    _require_cfo_entitlement(ctx.tenant_id, direct_action_code=CFO_FINANCIAL_HEALTH)

    outcome = assemble_financial_health(
        ctx.tenant_id,
        FinancialHealthRequest(
            period_start=body.period_start, period_end=body.period_end, as_of_date=body.as_of_date
        ),
    )

    return {
        "overallBand": outcome.overall_band.value if outcome.overall_band is not None else None,
        "perMetricBands": {metric: band.value for metric, band in outcome.per_metric_bands.items()},
        "engineResultRefs": [str(ref) for ref in outcome.engine_result_refs],
        "unavailableReason": outcome.unavailable_reason,
    }


class CashReconciliationHttpRequest(BaseModel):
    marketplace: str
    period_start: date
    period_end: date
    as_of_date: date


@router.post("/cash-reconciliation")
def post_cash_reconciliation(
    body: CashReconciliationHttpRequest, ctx: AuthContext = require_auth(permission=AGENT_CFO)
) -> dict[str, object]:
    """Direct-execution path (cfo-agent.md §6.10, deterministic-engine.md §5.13.3) for
    `backend.services.cfo_actions.assemble_cash_reconciliation`. `cashReceived` is real, summed
    from persisted `settlement_line` rows; `cashExpected`/`cashVariance` are structurally
    `isAvailable: false` this pass — no adapter anywhere maps an invoice-side marketplace-fee
    component, so a net "expected settlement" figure cannot be honestly computed yet (a real,
    disclosed data-foundation gap, never approximated from a gross, pre-deduction amount).
    `tcsCollected` is real for FLIPKART only; `tdsDeducted` is `isAvailable: false` for every
    marketplace this pass — no adapter maps a TDS component anywhere. `settledWithinLagCount`/
    `unsettledBeyondLagCount` reuse the same settlement-lag classification `cfo.preview`'s
    Leak Shield reconciliation already runs, applied here independently (no prior `reconcile()`
    run is required to call this route)."""
    assert ctx.tenant_id is not None
    _require_cfo_entitlement(ctx.tenant_id, direct_action_code=CFO_CASH_RECONCILIATION)

    outcome = assemble_cash_reconciliation(
        ctx.tenant_id,
        CashReconciliationRequest(
            marketplace=body.marketplace,
            period_start=body.period_start,
            period_end=body.period_end,
            as_of_date=body.as_of_date,
        ),
    )

    return {
        "cashReceived": _pricing_metric_result_to_dict(outcome.cash_received),
        "cashExpected": _pricing_metric_result_to_dict(outcome.cash_expected),
        "cashVariance": _pricing_metric_result_to_dict(outcome.cash_variance),
        "tcsCollected": _pricing_metric_result_to_dict(outcome.tcs_collected),
        "tdsDeducted": _pricing_metric_result_to_dict(outcome.tds_deducted),
        "settledWithinLagCount": outcome.settled_within_lag_count,
        "unsettledBeyondLagCount": outcome.unsettled_beyond_lag_count,
        "datesMissingCount": outcome.dates_missing_count,
    }


class PricingCandidateHttpInput(BaseModel):
    sku: str
    price_paise: int
    margin_pct: str
    engine_result_ref: UUID


class SupplierRankHttpInput(BaseModel):
    sku: str
    supplier_name: str
    landed_cost_paise: int
    engine_result_ref: UUID


class StrategicBriefingHttpRequest(BaseModel):
    """Every opt-in field defaults to "don't run this check" — mirrors `FinancialHealthHttpRequest`'s
    minimal shape, extended only with the opt-in signal sources `assemble_strategic_briefing`
    itself documents as opt-in (see that function's own docstring). `pricing_candidates`/
    `supplier_ranking` are the caller's own already-computed `compute_pricing_curve`/
    `rank_suppliers` output, copied through unchanged (never recomputed here) — same opt-in,
    pass-through contract as `anomaly_target_ref`/`expense_budget_categories`."""

    period_start: date
    period_end: date
    as_of_date: date
    anomaly_target_ref: str | None = None
    expense_budget_categories: list[str] = Field(default_factory=list)
    include_narration: bool = True
    model: str | None = None
    pricing_candidates: list[PricingCandidateHttpInput] = Field(default_factory=list)
    supplier_ranking: list[SupplierRankHttpInput] = Field(default_factory=list)


def _strategic_signal_to_dict(signal: Any) -> dict[str, object]:
    evidence = signal.evidence[0] if signal.evidence else None
    return {
        "category": signal.category,
        "severityRank": signal.severity_rank,
        "severityLabel": signal.severity_label,
        "recommendedActionType": signal.recommended_action_type,
        "headline": signal.headline,
        "evidence": (
            None
            if evidence is None
            else {
                "label": evidence.label,
                "valuePaise": evidence.value_paise,
                "valueFraction": str(evidence.value_fraction) if evidence.value_fraction is not None else None,
                "textValue": evidence.text_value,
                "isAvailable": evidence.is_available,
                "register": evidence.register,
                "engineResultRef": (
                    str(evidence.engine_result_ref) if evidence.engine_result_ref is not None else None
                ),
            }
        ),
    }


@router.post("/strategic-briefing")
def post_strategic_briefing(
    body: StrategicBriefingHttpRequest, ctx: AuthContext = require_auth(permission=AGENT_CFO)
) -> dict[str, object]:
    """Direct-execution path (cfo-agent.md §7.5, Strategic Insight layer) for
    `backend.services.cfo_actions.assemble_strategic_briefing`. Gathers already-computed
    Financial Health bands, persisted Leak Shield findings, open data requests, and (only when
    the caller opts in via `anomalyTargetRef`/`expenseBudgetCategories`/`pricingCandidates`/
    `supplierRanking`) fired anomaly flags, expense-budget overages, and pricing/supplier
    scenario-comparison signals, ranks them deterministically, and — when `includeNarration=true`
    (the default) and at least one signal exists — makes exactly ONE LLM call over the whole
    ranked list. Every `recommendedActionType` is deterministically assigned; the LLM never
    picks or reorders one. `pricingCandidates`/`supplierRanking` are copied through unchanged —
    this route never calls `compute_pricing_curve`/`rank_suppliers` itself, the caller must have
    already run those and pass their output. Read-only: creates no manual input, so needs no
    `financials.adjust` gate."""
    assert ctx.tenant_id is not None
    _require_cfo_entitlement(ctx.tenant_id, direct_action_code=CFO_STRATEGIC_BRIEFING)

    outcome = assemble_strategic_briefing(
        ctx.tenant_id,
        StrategicBriefingRequest(
            period_start=body.period_start,
            period_end=body.period_end,
            as_of_date=body.as_of_date,
            requested_by=ctx.app_user_id,
            anomaly_target_ref=body.anomaly_target_ref,
            expense_budget_categories=tuple(body.expense_budget_categories),
            include_narration=body.include_narration,
            narration_model=body.model,
            pricing_candidates=tuple(
                PricingCandidateInput(
                    sku=c.sku,
                    price_paise=c.price_paise,
                    margin_pct=Fraction(c.margin_pct),
                    engine_result_ref=c.engine_result_ref,
                )
                for c in body.pricing_candidates
            ),
            supplier_ranking=tuple(
                SupplierRankInput(
                    sku=s.sku,
                    supplier_name=s.supplier_name,
                    landed_cost_paise=s.landed_cost_paise,
                    engine_result_ref=s.engine_result_ref,
                )
                for s in body.supplier_ranking
            ),
        ),
    )

    return {
        "signals": [_strategic_signal_to_dict(s) for s in outcome.signals],
        "narrative": outcome.narrative,
        "generatedAt": outcome.generated_at.isoformat(),
        "narrationSafety": (
            None
            if outcome.narration_safety is None
            else {
                "isSafe": outcome.narration_safety.is_safe,
                "fabricatedNumbers": list(outcome.narration_safety.fabricated_numbers),
                "unavailableFiguresStatedAsReal": list(
                    outcome.narration_safety.unavailable_figures_stated_as_real
                ),
            }
        ),
    }


class GstLookupHttpRequest(BaseModel):
    """One product to research — `sku`/`hsn`/`category` optional, exactly `calc_engine.
    gst_lookup.types.GstLookupQuery`'s own shape (`GstLookupRequest` mirrors it verbatim)."""

    product_title: str = Field(min_length=1)
    sku: str | None = None
    hsn: str | None = None
    category: str | None = None


def _gst_lookup_result_to_dict(result: Any) -> dict[str, object]:
    return {
        "id": str(result.id),
        "queryText": result.query_text,
        "sku": result.sku,
        "queryHsn": result.query_hsn,
        "likelyRatePct": str(result.likely_rate_pct) if result.likely_rate_pct is not None else None,
        "likelyHsn": result.likely_hsn,
        "likelyCategory": result.likely_category,
        "ambiguityNote": result.ambiguity_note,
        "alternatives": [
            {
                "ratePct": str(a["rate_pct"]) if a.get("rate_pct") is not None else None,
                "hsn": a.get("hsn"),
                "category": a.get("category"),
            }
            for a in result.alternatives
        ],
        "sourceUrl": result.source_url,
        "sourceTitle": result.source_title,
        "retrievedAt": result.retrieved_at.isoformat(),
        "status": result.status,
        "disclaimer": result.disclaimer,
    }


def _gst_lookup_no_match_to_dict(no_match: Any) -> dict[str, object]:
    return {
        "queryText": no_match.query_text,
        "attemptedUrls": list(no_match.attempted_urls),
        "reason": no_match.reason,
    }


@router.post("/gst-lookup")
def post_gst_lookup(
    body: GstLookupHttpRequest, ctx: AuthContext = require_auth(permission=AGENT_CFO)
) -> dict[str, object]:
    """Direct-execution path (cfo-agent.md §6.6 C5/C6, §6.8 `cfo.gst_lookup`, AC17b/T31) for
    `backend.services.cfo_actions.run_gst_applicability_lookup` — G3's wiring of the
    already-complete G2 lookup (`calc_engine.gst_lookup`) into CFO.

    **The two-gate shape is intentional and NOT the same as every other route in this file**
    (§6.8's own table row: `agent.cfo` **and** `service.gst_lookup`, each with its OWN
    independent entitlement cap — never conflated into one check):

    - **Permission**: `require_auth(permission=AGENT_CFO)` below enforces `agent.cfo` as
      §7.1 step 5, exactly like every other route. `require_auth` takes only one `permission`
      key, so it cannot also express `service.gst_lookup` — this is the first CFO route that
      needs a SECOND, independent permission, checked in-handler via `has_permission` (the
      SAME established pattern `put_expense` already uses for its own second permission,
      `financials.adjust`, per §8 rule 4). T31 (`agent.cfo` present, `service.gst_lookup`
      absent -> `403`) is satisfied by this in-handler check; the symmetric reverse case
      (`service.gst_lookup` present, `agent.cfo` absent -> `403`) is satisfied by `require_auth`
      itself denying before this handler body ever runs, per its own §7.1 step 5 — no code path
      here reaches the `service.gst_lookup` check without `agent.cfo` already having passed.
    - **Entitlement**: TWO independent checks, neither substituting for the other (AC17b).
      `_require_cfo_entitlement` (existing, `agent.cfo`'s own CFO entitlement cap) AND
      `resolve_gst_lookup_entitlement` (new, `service.gst_lookup`'s own OP9 shared-service cap).
      Both must pass.
    """
    assert ctx.tenant_id is not None

    if ctx.role is None or not has_permission(role=ctx.role, permissions=ctx.permissions, key=SERVICE_GST_LOOKUP):
        raise HTTPException(status_code=403, detail="service.gst_lookup permission required")

    _require_cfo_entitlement(ctx.tenant_id, direct_action_code=CFO_GST_LOOKUP)

    gst_lookup_entitlement = resolve_gst_lookup_entitlement(ctx.tenant_id)
    if not gst_lookup_entitlement.passed:
        raise HTTPException(
            status_code=402,
            detail={
                "reason": gst_lookup_entitlement.reason,
                "service": "gst_lookup",
                "gstLookupCount": gst_lookup_entitlement.gst_lookup_count,
            },
        )

    request = GstLookupRequest(
        product_title=body.product_title,
        sku=body.sku,
        hsn=body.hsn,
        category=body.category,
        requested_by=ctx.app_user_id,
    )
    outcome = run_gst_applicability_lookup(ctx.tenant_id, request)

    return {
        "result": _gst_lookup_result_to_dict(outcome.result) if outcome.result is not None else None,
        "noMatch": _gst_lookup_no_match_to_dict(outcome.no_match) if outcome.no_match is not None else None,
        "fromCache": outcome.from_cache,
    }


class AcceptGstLookupHttpRequest(BaseModel):
    """Accepting a specific `gst_lookup_result` for a SKU (deterministic-engine.md §7.2.1
    `gst_rate_override` / §8.4's updated L2 rule). Deliberately carries no `rate_pct`/`hsn`/
    `category` fields at all — `accept_gst_lookup_result` reads those from the real stored
    `gst_lookup_result` row, never from this request body (see that function's own docstring
    on why `AcceptGstLookupRequest` even has those fields internally but never reads them)."""

    gst_lookup_result_id: UUID
    sku: str = Field(min_length=1)
    reason: str | None = None
    effective_from: date | None = None


@router.post("/gst-lookup/accept")
def post_accept_gst_lookup(
    body: AcceptGstLookupHttpRequest, ctx: AuthContext = require_auth(permission=AGENT_CFO)
) -> dict[str, object]:
    """G4 (deterministic-engine.md §7.2.1/§8.4 L2) — the seller-acceptance act
    `run_gst_applicability_lookup`/`post_gst_lookup` (G3) deliberately left out of scope. Turns
    a specific, already-persisted `PROVISIONAL` `gst_lookup_result` into a real, calculation-
    unblocking `gst_rate_override` manual_adjustment.

    **THREE permission gates, not two** — this is the same `agent.cfo` + `service.gst_lookup`
    pair `post_gst_lookup` already enforces (the acceptance is part of the same capability,
    gated identically), PLUS `financials.adjust` (checked in-handler, the SAME established
    pattern `put_expense` uses for its own second gate, and `post_gst_lookup` uses for its own
    `service.gst_lookup` gate) — per §7's standing rule that creating or superseding ANY manual
    financial input requires `financials.adjust`, restated explicitly for `gst_rate_override`
    at §7.2.1's own "Permission" paragraph and `cfo-agent.md` §5 rule 4, with no exception for
    this field. `require_auth(permission=AGENT_CFO)` enforces the first gate; the other two are
    both checked below, in-handler, before `accept_gst_lookup_result` is ever called.

    Deliberately does NOT re-run `_require_cfo_entitlement`/`resolve_gst_lookup_entitlement` —
    those are the ENTITLEMENT caps guarding a fresh `cfo.gst_lookup` RESEARCH call (§8.4.1's
    per-query volume cap); accepting an already-persisted result creates no new lookup and
    consumes no lookup quota, so gating it behind that same usage cap would be a category
    error, not a faithful mirror of `post_gst_lookup`'s gate shape. Only the permission grid
    is mirrored here, per this checkpoint's own explicit instruction — the entitlement gate is
    a deliberate, disclosed scope boundary, not an oversight.

    A rejection (`GstRateOverrideOutcome.manual_adjustment_id is None` — no such
    `gst_lookup_result` row for this tenant, or the row has no `likely_rate_pct`) is surfaced as
    `400`, naming the reason; it is never silently swallowed or treated as success."""
    assert ctx.tenant_id is not None

    if ctx.role is None or not has_permission(role=ctx.role, permissions=ctx.permissions, key=SERVICE_GST_LOOKUP):
        raise HTTPException(status_code=403, detail="service.gst_lookup permission required")
    if ctx.role is None or not has_permission(role=ctx.role, permissions=ctx.permissions, key=FINANCIALS_ADJUST):
        raise HTTPException(status_code=403, detail="financials.adjust permission required")

    request = AcceptGstLookupRequest(
        gst_lookup_result_id=body.gst_lookup_result_id,
        sku=body.sku,
        accepted_by=ctx.app_user_id,
        reason=body.reason,
        effective_from=body.effective_from,
    )
    outcome = accept_gst_lookup_result(ctx.tenant_id, request)
    if outcome.manual_adjustment_id is None:
        raise HTTPException(status_code=400, detail=outcome.rejected_reason)

    return {"manualAdjustmentId": str(outcome.manual_adjustment_id)}


@router.get("/data-requests")
def list_data_requests(ctx: AuthContext = require_auth(permission=AGENT_CFO)) -> list[dict[str, object]]:
    """Lists this tenant's `agent_data_request` rows (OP1: CFO asks rather than assumes) —
    read-only surfacing of what CP1's repository already records; no new write path here."""
    assert ctx.tenant_id is not None
    rows = list_for_tenant(ctx.tenant_id)
    return [
        {
            "id": str(r["id"]),
            "requestedField": r["requested_field"],
            "reason": r["reason"],
            "blockingMetric": r["blocking_metric"],
            "status": r["status"],
            "createdAt": r["created_at"].isoformat(),
        }
        for r in rows
    ]
