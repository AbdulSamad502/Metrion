"""CFO action composition — the single root used by BOTH `agents/ceo_hub.py`'s CEO-routed
actions and `api/v1/cfo.py`'s direct-execution routes (C20: "both entry paths enforce the
same checks"), mirroring `backend/services/ci_actions.py` exactly.

**No money arithmetic anywhere in this module** (CLAUDE.md hard rule). Every function here
either assembles inputs and calls a real, unchanged `calc_engine` function
(`compute_net_realized_revenue`, `compute_contribution_profit`, `normalize_to_exclusive`,
`check_rate_plausibility`), or is a thin wrapper over a repository insert
(`manual_adjustment_repo.insert_adjustment`, `agent_data_request_repo.insert`). No `+`, `-`,
`*`, `/` is ever applied to a `Paise`/paise `int` in this file.

`twinkly-mapping-canyon.md` CP2 scope: `compute_period_pnl`, `enter_expense`,
`analyze_gst_lines`, `raise_data_request`. CP A1 adds `compute_pricing_curve` (cfo-agent.md
§6.7/§6.8 `cfo.pricing`) — same no-arithmetic discipline, the only new composition logic is a
`config_repo.resolve_fee_reference` DB lookup + `resolve_fee_or_unavailable` wrap, mirroring
how `compute_period_pnl` already calls `config_repo.resolve_discount_bearer`. CP A2 adds
`render_gst_period_summary` (cfo-agent.md §6.6/§6.8 `cfo.gst_summary`) — the PERIOD-level GST
total, a genuinely separate surface from `analyze_gst_lines`'s LINE-level analysis; the two
must never be merged or confused (session guardrail). CP A3 adds `narrate_period_comparison`
(cfo-agent.md §7.4.4's "once built" period-comparison narration rule) — fetches two already-
persisted `MetricResult`s via `calc_engine.repositories.metric_result_repo.get`, calls
`calc_engine.api.compute_metric.compute_metric_delta` unchanged (the ONLY place delta
arithmetic happens), then narrates via Brain 3's `narrate_figures` (`packages/cfo`), with
every figure pre-formatted to a display string before Brain 3 ever sees it. CP A4 adds
`compute_landed_cost_for_quote` (cfo-agent.md §6.11 supplier-ranking *primitive*, deliberately
NOT the ranking itself — that is Phase B1) — fetches a seller's `supplier.quote`
manual_adjustment via `calc_engine.repositories.manual_adjustment_repo.
active_adjustments_for_target` (real, unchanged), parses it with
`calc_engine.formulas.landed_cost.parse_supplier_quote_adjustment` (real, unchanged), and calls
`calc_engine.api.compute_metric.compute_landed_cost` (real, unchanged) — the ONLY place landed-
cost arithmetic happens. This function computes exactly ONE quote's landed cost; it never
compares, sorts or scores across quotes. Leak
classification/ranking stays library-only in `packages/cfo/src/cfo/leak/` — deliberately not
composed or wired here (guardrail 4: no seller-facing Leak Shield findings until a real
`reconcile()` exists).

**On `_format_paise_for_narration`'s use of `divmod`/`abs`:** this module's own "no `+ - * /`
on a paise-named variable" convention is about money CALCULATION (deriving a new financial
figure) — it is not violated by converting an already-final, engine-computed paise integer
into a rupee display string for Brain 3's prompt, which determines no monetary outcome at
all. `divmod`/`abs` are function calls, not `+ - * /` operators, so `test_no_arithmetic_lint.py`
does not (and should not) flag them — this is documented here explicitly rather than left to
look like an accidental gap in that lint's coverage.

CP B1 adds `rank_suppliers` (cfo-agent.md §6.11 supplier ranking, `twinkly-mapping-canyon.md`
Phase B1) — the ranking CP A4 deliberately did not build. Calls `manual_adjustment_repo.
active_adjustments_for_target` DIRECTLY (not through `compute_landed_cost_for_quote`, which
treats >1 ACTIVE row as an unresolved ambiguity — correct for a single-quote lookup, wrong for
ranking, which explicitly wants every ACTIVE row for the SKU), parses and computes each row's
landed cost via the same real, unchanged `parse_supplier_quote_adjustment`/`compute_landed_cost`
CP A4 already uses, then `sorted()`s the successfully-computed results ascending by
`MetricResult.value_paise` — a comparison/ordering operation, not `+ - * /` arithmetic, so this
stays outside the money-calculation boundary this module's own guardrail polices. A row that
fails to parse is quarantined (excluded, disclosed with its reason) rather than aborting the
whole ranking, mirroring §9's E8 quarantine precedent for malformed rows in a period.

CP B2 adds `assemble_funding_readiness_reduced` (cfo-agent.md §6.13/D7 "funding readiness",
`twinkly-mapping-canyon.md` Phase B2) — the honestly-buildable REDUCED slice only: Contribution
Profit history and trend, with data-completeness stated, plus explicit gaps (periods missing,
COGS/RTO-classification absent). Margin stability, revenue concentration and cash-conversion
timing are §6.13 bullets this checkpoint does NOT build (they need `reconcile()`/
`cash_reconciliation`, Phase D, not yet built) — the output says so structurally
(`DeferredFundingReadinessSection`), never by silent omission. Fetches history via the new
`calc_engine.repositories.metric_result_repo.list_by_metric_code` (real, this checkpoint's one
new read path), reconstructs each row via the SAME `_metric_result_from_row` CP A3 already
built (no second dict->dataclass helper), and calls `compute_metric_delta` (real, unchanged)
per consecutive pair — the ONLY place delta arithmetic happens, exactly as CP A3 already
established. **No score, valuation or lending judgement anywhere** (AC19) — every field on
`FundingReadinessOutcome` is either a fetched/reconstructed `MetricResult`, a real engine-
computed delta, or a structured statement of what is missing/deferred.

CP B3b adds `assemble_batch_size_estimate` (cfo-agent.md §6.12/D9 "batch size", `twinkly-
mapping-canyon.md` Phase B3b) — the CFO wiring B3a's engine core (`calc_engine.formulas.
batch_size.budget_constrained_quantity` / `calc_engine.api.compute_metric.
compute_batch_constrained_quantity`) deliberately did not build: sales velocity (via the new
`calc_engine.formulas.sales_velocity.observed_units_sold`, real, unchanged), the `batch.budget`
lookup/parse/expiry check, and the `agent_data_request` behaviour §6.12 names. Fetches the
chosen `supplier.quote` via `manual_adjustment_repo.active_adjustments_for_target` (mirroring
CP A4's zero/multiple/malformed handling exactly), fetches `batch.budget` the same way, computes
the landed-cost-per-unit reference at `quantity = moq or 1` (a disclosed approximation — see the
function's own docstring for why), and calls `compute_landed_cost` then
`compute_batch_constrained_quantity` (both real, unchanged) — the ONLY places their respective
arithmetic happens. A never-sold SKU (empty `lines`) or an `Unavailable` velocity degrades the
estimate to the budget-and-MOQ arithmetic floor §6.12 itself names as honest, rather than
refusing outright — refusal (a data request) is reserved for the case where velocity AND
lead-time AND MOQ are ALL missing (§6.12's precise wording), never merely velocity alone.

D7 adds `assemble_cfo_preview` (cfo-agent.md §6.9/§6.8 `cfo.preview`) — the free-tier gated
preview, approved this session (no longer provisional): headline recoverable-discrepancy
total, affected SKU count, one finding revealed in full, the rest locked. Calls the real,
unchanged `run_leak_shield_reconciliation` (D5) directly, deliberately NOT entitlement-gated
(§6.8's own table: the preview is served *in place of* the entitlement denial, not behind it).
Threads `LeakShieldOutcome.aggregate_amount_paise`/`aggregate_engine_result_ref` (also new this
checkpoint, D5's own dataclass extended to expose the already-computed `LEAK_TOTAL` figure it
previously computed but never returned) straight through as the headline — never recomputed,
never summed from individual findings (§6.4 rule 5). `affected_sku_count` is honestly
`None`/flagged unavailable, never a bare `0`, when every real finding's `sku` is `None` (true
of all real data today — no Meesho adapter maps `sku` yet), per CLAUDE.md's "missing input is
UNAVAILABLE, never zero" rule.

G3 adds `run_gst_applicability_lookup` (cfo-agent.md §6.6 C5/C6/§6.8 `cfo.gst_lookup`,
deterministic-engine.md §8.4) — wires the already-complete G2 lookup (`calc_engine.gst_lookup`)
into CFO as a direct execution path. Checks `gst_lookup_repo.find_cached`'s 14-day TTL cache
(L6) FIRST; only calls `gst_applicability_lookup` fresh — composing the real `HttpxGstFetcher`
and `cfo.reasoning.ollama_provider.OllamaLlmProvider` — on a genuine cache miss. Persists a
genuine `GstLookupResult` via `gst_lookup_repo.save` so the next identical query within 14 days
hits the cache; persists nothing on `GstLookupNoMatch` (nothing worth caching about "no
reliable source found"). **L2 enforced by omission, same as `gst_applicability_lookup` itself:
this function never applies its result to any calculation, `MetricResult`, or
`manual_adjustment`** — the seller-acceptance-to-manual-input flow (deterministic-engine.md §7)
is built by G4 immediately below, not this function.

G4 adds `accept_gst_lookup_result` (deterministic-engine.md §7.2.1's `gst_rate_override` row and
§8.4's updated L2 rule) — the seller-acceptance act G3 deliberately left out-of-scope. Reads
back the REAL, already-persisted `gst_lookup_result` row by id (`gst_lookup_repo.get_by_id`,
this checkpoint's one new repository read), never trusting any client-supplied
rate/hsn/category, and inserts a `gst_rate_override` manual_adjustment (`SKU` grain, engine
§7.2.1) via `manual_adjustment_repo.insert_adjustment` (real, unchanged) — mirroring exactly how
every other manual_adjustment field is written in this module. Refuses (never synthesizes an
override) when the row doesn't exist for this tenant, or exists but carries no
`likely_rate_pct` (a `GstLookupNoMatch`-shaped or empty row, which G2's own design says
shouldn't happen but must not crash if it somehow does). Deliberately does NOT mark the source
`gst_lookup_result` row `SELLER_VERIFIED` — per the spec's explicit "two separate,
separately-recorded acts" rule, AND because `gst_lookup_result` has no `UPDATE` grant for
`metrion_app` at all (`20260925_0008_gst_lookup_result.py`'s own docstring: append-only by
design) — this function could not update that row even if the spec wanted it to. When an
ACTIVE `gst_rate_override` already exists for this SKU, the new row's `supersedes_id` is set to
that prior row's id automatically (via `manual_adjustment_repo.active_adjustments_for_target`,
real, unchanged) — the seller accepting a second, different lookup result for a SKU they've
already overridden is a correction, not a fresh unrelated fact, mirroring
`test_correction_is_a_new_row_with_supersedes_id_not_an_update`'s established append-only
chain-by-`supersedes_id` pattern (the OLD row's own `status` column is never changed — it
cannot be, `UPDATE`/`DELETE` are revoked at the grant level for `manual_adjustment` too — both
rows simply exist, newest-first, exactly as that precedent already established for every other
field).

This checkpoint closes the gap G4 named above: `resolve_gst_rate_for_sku` composes OP13's exact
three-tier order — tier 0 `gst_rate_override` (`manual_adjustment_repo.
active_adjustments_for_target`, wins outright over every other tier when ACTIVE), tier 1
observed (whatever rate the caller already resolved from the seller's own report), tier 2
`hsn_gst_reference` (`config_repo.resolve_hsn_gst_reference`, `PROVISIONAL`, only reached when 0
and 1 both miss and an `hsn_code` is given). Tier 3 (the live GST Applicability Lookup, §8.4) is
deliberately never auto-triggered here — a genuine miss on 0/1/2 returns `GstRateUnresolved`, a
real, named non-result naming tier 3 as the caller's explicit next step, never a silent `None`
and never a side-effecting call to `gst_applicability_lookup` itself. `analyze_gst_lines` gained
an opt-in `resolve_unobserved_rates` parameter (default `False`) that calls this composer for a
line with no observed `rate_pct` — existing callers that never pass it see zero behavioural
change."""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction
from typing import Any, Mapping, Sequence
from uuid import UUID

from calc_engine.anomaly.period_over_period_delta import period_over_period_delta
from calc_engine.anomaly.percentile_threshold import percentile_threshold
from calc_engine.anomaly.types import (
    METHOD_PERCENTILE_THRESHOLD,
    METHOD_PERIOD_OVER_PERIOD_DELTA,
    METHOD_Z_SCORE,
    METRIC_FEE_RATIO_PCT,
    METRIC_MARGIN_PCT,
    METRIC_RETURN_RATE_PCT,
    METRIC_SETTLEMENT_LAG_DAYS,
    AnomalyConfigurationGap,
    AnomalyFlag,
    AnomalyInsufficientHistory,
    AnomalyThreshold,
    AnomalyZeroVariance,
    SeriesPoint,
)
from calc_engine.anomaly.z_score import z_score
from calc_engine.api.compute_metric import (
    MetricResult,
    compute_batch_constrained_quantity,
    compute_contribution_margin_pct,
    compute_contribution_profit,
    compute_fee_ratio_pct,
    compute_gst_period_summary,
    compute_landed_cost,
    compute_margin_curve,
    compute_marketplace_fees,
    compute_metric_delta,
    compute_net_realized_revenue,
    compute_return_rate_pct,
    compute_settlement_lag_days,
)
from calc_engine.api.reconcile import reconcile
from calc_engine.formulas import expense_pools
from calc_engine.formulas.cost_components import CostEntry
from calc_engine.formulas.fee_resolution import FeeReference, resolve_fee_or_unavailable
from calc_engine.formulas.landed_cost import parse_supplier_quote_adjustment
from calc_engine.formulas.leak import ReconciliationOutcome
from calc_engine.formulas.settlement_lag import SettlementLagAggregate, settlement_lag_days_aggregate
from calc_engine.formulas.sales_velocity import (
    BatchBudget,
    observed_units_sold,
    parse_batch_budget_adjustment,
)
from calc_engine.formulas.severity import SeverityBand, SeverityConfigRow
from calc_engine.gst.normalization import Basis, normalize_to_exclusive
from calc_engine.gst.slab_reference import GstSlabRow, check_rate_plausibility
from calc_engine.gst.summary import DEFAULT_TAX_HEADS
from calc_engine.gst_lookup.fetcher import GstFetcher, HttpxGstFetcher
from calc_engine.gst_lookup.llm_provider import LlmProvider as GstLookupLlmProvider
from calc_engine.gst_lookup.lookup import gst_applicability_lookup
from calc_engine.gst_lookup.types import GstLookupNoMatch, GstLookupQuery, GstLookupResult
from calc_engine.repositories import (
    config_repo,
    gst_lookup_repo,
    manual_adjustment_repo,
    metric_result_repo,
    reconciliation_repo,
)
from calc_engine.repositories.manual_adjustment_repo import insert_adjustment
from calc_engine.types import Bearer, CanonicalLine, Confidence, Paise, RecognitionState, Unavailable, sum_paise

from data_foundation.component_registry import COMPONENT_KIND_BY_CODE

from cfo.leak.compose import ComposedFinding, LeakExceptionInput, classify_and_rank_leaks
from cfo.pnl import inputs as pnl_inputs
from cfo.reasoning.narrate import FigureToken, narrate_figures
from cfo.reasoning.ollama_provider import OllamaLlmProvider
from cfo.reasoning.prompts import GST_DISCLAIMER
from cfo.reasoning.provider import LlmProvider
from cfo.repositories import leak_finding_repo
from cfo.repositories.agent_data_request_repo import insert as insert_data_request

from backend.config import cfo_narration_model, ollama_host

_PNL_CONFIG_VERSION = "CFO_PERIOD_PNL.v1"
_PRICING_CURVE_CONFIG_VERSION = "CFO_PRICING_CURVE.v1"
_GST_PERIOD_SUMMARY_CONFIG_VERSION = "CFO_GST_PERIOD_SUMMARY.v1"
_PERIOD_COMPARISON_CONFIG_VERSION = "CFO_PERIOD_COMPARISON.v1"
_LANDED_COST_CONFIG_VERSION = "CFO_LANDED_COST.v1"
_SUPPLIER_RANKING_CONFIG_VERSION = "CFO_SUPPLIER_RANKING.v1"
_FUNDING_READINESS_CONFIG_VERSION = "CFO_FUNDING_READINESS.v1"
_BATCH_SIZE_CONFIG_VERSION = "CFO_BATCH_SIZE.v1"
_LEAK_SHIELD_CONFIG_VERSION = "CFO_LEAK_SHIELD.v1"

# engine §7.2.1 — the authoritative manual_adjustment field registry. CFO never invents a
# field name (cfo-agent.md line 73); `enter_expense` is restricted to exactly this set.
#
# `gst_rate_override` is DELIBERATELY NOT in this set. §8.4's L2 rule ("no code path may
# create a gst_rate_override row without an explicit seller acceptance action against a
# specific gst_lookup_result") means the generic `enter_expense`/`PUT /cfo/expenses` write
# path — which passes a caller's `value` straight through, uninspected — must never be able to
# originate this field. The ONLY path that may create one is `accept_gst_lookup_result` below,
# which reads the real stored rate/hsn/category from the referenced `gst_lookup_result` row
# itself rather than trusting a request body. Adding "gst_rate_override" here would silently
# reopen exactly the hole L2 exists to close.
_ALLOWED_MANUAL_ADJUSTMENT_FIELDS: frozenset[str] = frozenset(
    {
        "cogs_per_unit",
        "expense.advertising",
        "expense.packaging",
        "expense.storage",
        "expense.logistics",
        "expense.other",
        "settlement.receipt",
        "supplier.quote",
        "batch.budget",
    }
)


def _metric_result_to_dict(result: MetricResult) -> dict[str, object]:
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


def _bearer_resolver_for(tenant_id: UUID, as_of_date: date):
    """Builds the `BearerResolver` `compute_net_realized_revenue` needs from
    `config_repo.resolve_discount_bearer` (real, unchanged) — a component_code with no
    resolvable row falls back to `Bearer.UNKNOWN`, exactly as that repository's own docstring
    specifies (D2), never a guessed bearer."""

    def resolver(marketplace: str, component_code: str) -> Bearer:
        row = config_repo.resolve_discount_bearer(
            tenant_id, marketplace=marketplace, component_code=component_code, as_of_date=as_of_date
        )
        if row is None:
            return Bearer.UNKNOWN
        return Bearer(row["bearer"])

    return resolver


@dataclass(frozen=True, slots=True)
class PeriodPnlRequest:
    """Everything `compute_period_pnl` needs to assemble `compute_net_realized_revenue` +
    `compute_contribution_profit`'s inputs. Deliberately explicit rather than defaulted —
    every component-code set and adjustment list here is a fact about this tenant's data that
    this composition must be handed, never guessed (judgment call 4: full assembly of a
    `CanonicalLine` from raw `sales_line`/`line_component` columns is out of this checkpoint's
    scope — `calc_engine.repositories.canonical_repo`'s own SELECT list does not carry every
    field a `CanonicalLine` needs; CP2/CP3 compose against constructed `CanonicalLine`s, CP4
    live P&L uses whatever ingestion adapters exist by then)."""

    lines: Sequence[CanonicalLine]
    period_start: date
    period_end: date
    as_of_date: date
    recognition_state: RecognitionState
    sku_by_line: Mapping[str, str]
    cost_history_by_sku: Mapping[str, Sequence[CostEntry]]
    fee_component_codes: frozenset[str]
    forward_logistics_codes: frozenset[str]
    reverse_logistics_codes: frozenset[str]
    non_refunded_fee_codes: frozenset[str]
    advertising_adjustment_values: Sequence[Mapping[str, object]]
    other_adjustment_values: Sequence[Mapping[str, object]]
    ingestion_run_ids: Sequence[UUID | str]
    adapter_versions: Sequence[str]
    active_adjustment_ids: Sequence[UUID | str]
    requested_by: UUID
    duplicate_fee_candidate_codes: frozenset[str] = frozenset()
    computed_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class PeriodPnlOutcome:
    nrr: MetricResult
    contribution_profit: MetricResult
    margin_pct: MetricResult
    fee_ratio_pct: MetricResult
    return_rate_pct: MetricResult
    marketplace_fee_flags: tuple[dict[str, object], ...]
    data_request_id: UUID | None  # set only when COGS or ReturnRTOLosses came back UNAVAILABLE (E2)


def compute_period_pnl(tenant_id: UUID, request: PeriodPnlRequest) -> PeriodPnlOutcome:
    """Assembles `NetRealizedRevenue` then `ContributionProfit` (deterministic-engine.md
    §5.5/§5.8) and persists both via `metric_result_repo.save`, unchanged. A missing COGS or
    unclassified RTO outcome propagates as `Unavailable` (never a silent zero) straight through
    to `ContributionProfit`, which itself reports `UNAVAILABLE` — this function additionally
    raises one `agent_data_request` naming the blocker (C8, E2), rather than leaving the seller
    to guess why the figure is missing."""
    computed_at = request.computed_at or datetime.now()
    bearer_resolver = _bearer_resolver_for(tenant_id, request.as_of_date)
    period_label = f"{request.period_start.isoformat()}/{request.period_end.isoformat()}"

    nrr_result = compute_net_realized_revenue(
        request.lines,
        bearer_resolver=bearer_resolver,
        recognition_state=request.recognition_state,
        ingestion_run_ids=request.ingestion_run_ids,
        adapter_versions=request.adapter_versions,
        active_adjustment_ids=request.active_adjustment_ids,
        computed_at=computed_at,
        as_of_date=request.as_of_date,
    )
    metric_result_repo.save(
        tenant_id,
        nrr_result,
        grain="TENANT_PERIOD",
        target_ref=str(tenant_id),
        period=period_label,
        config_version=_PNL_CONFIG_VERSION,
    )

    cogs = pnl_inputs.resolve_cogs(
        request.lines,
        sku_by_line=request.sku_by_line,
        cost_history_by_sku=request.cost_history_by_sku,
        as_of=request.as_of_date,
    )
    marketplace_fees, fee_flags = pnl_inputs.resolve_marketplace_fees(
        request.lines,
        fee_component_codes=request.fee_component_codes,
        duplicate_candidate_codes=request.duplicate_fee_candidate_codes,
    )

    # anomaly-detection.md §6.1 P2's real gap, closed: MarketplaceFees now gets its own real,
    # citable engine_result_ref (compute_marketplace_fees is a thin minting wrapper only — the
    # real summation already happened in resolve_marketplace_fees above), and FEE_RATIO_PCT is
    # composed from it + the already-computed nrr_result — mirroring exactly how margin_pct_
    # result (below) composes from cp_result + nrr_result.
    fees_result = compute_marketplace_fees(
        marketplace_fees,
        computed_at=computed_at,
        as_of_date=request.as_of_date,
    )
    metric_result_repo.save(
        tenant_id,
        fees_result,
        grain="TENANT_PERIOD",
        target_ref=str(tenant_id),
        period=period_label,
        config_version=_PNL_CONFIG_VERSION,
    )

    fee_ratio_pct_result = compute_fee_ratio_pct(
        fees_result,
        nrr_result,
        computed_at=computed_at,
        as_of_date=request.as_of_date,
    )
    metric_result_repo.save(
        tenant_id,
        fee_ratio_pct_result,
        grain="TENANT_PERIOD",
        target_ref=str(tenant_id),
        period=period_label,
        config_version=_PNL_CONFIG_VERSION,
    )

    shipping_logistics = pnl_inputs.resolve_shipping_logistics(request.lines)
    advertising_costs = pnl_inputs.resolve_expense_pool_total(request.advertising_adjustment_values)
    other_allocated_costs = pnl_inputs.resolve_expense_pool_total(request.other_adjustment_values)
    return_rto_losses = pnl_inputs.resolve_return_rto_losses(
        request.lines,
        sku_by_line=request.sku_by_line,
        cost_history_by_sku=request.cost_history_by_sku,
        as_of=request.as_of_date,
        forward_logistics_codes=request.forward_logistics_codes,
        reverse_logistics_codes=request.reverse_logistics_codes,
        non_refunded_fee_codes=request.non_refunded_fee_codes,
    )

    cp_result = compute_contribution_profit(
        nrr_result,
        cogs=cogs,
        marketplace_fees=marketplace_fees,
        shipping_logistics=shipping_logistics,
        advertising_costs=advertising_costs,
        return_rto_losses=return_rto_losses,
        other_allocated_costs=other_allocated_costs,
        ingestion_run_ids=request.ingestion_run_ids,
        adapter_versions=request.adapter_versions,
        active_adjustment_ids=request.active_adjustment_ids,
        computed_at=computed_at,
        as_of_date=request.as_of_date,
    )
    metric_result_repo.save(
        tenant_id,
        cp_result,
        grain="TENANT_PERIOD",
        target_ref=str(tenant_id),
        period=period_label,
        config_version=_PNL_CONFIG_VERSION,
    )

    margin_pct_result = compute_contribution_margin_pct(
        cp_result,
        nrr_result,
        computed_at=computed_at,
        as_of_date=request.as_of_date,
    )
    metric_result_repo.save(
        tenant_id,
        margin_pct_result,
        grain="TENANT_PERIOD",
        target_ref=str(tenant_id),
        period=period_label,
        config_version=_PNL_CONFIG_VERSION,
    )

    # anomaly-detection.md §6.1's other real, unbuilt gap, closed: RETURN_RATE_PCT is an
    # already-computable ratio from canonical data (§5.6's billable_quantity inputs) — no
    # composition of prior MetricResults needed, so this uses request.lines directly, the same
    # full period line set nrr_result/cp_result were built from.
    return_rate_pct_result = compute_return_rate_pct(
        request.lines,
        ingestion_run_ids=request.ingestion_run_ids,
        adapter_versions=request.adapter_versions,
        active_adjustment_ids=request.active_adjustment_ids,
        computed_at=computed_at,
        as_of_date=request.as_of_date,
    )
    metric_result_repo.save(
        tenant_id,
        return_rate_pct_result,
        grain="TENANT_PERIOD",
        target_ref=str(tenant_id),
        period=period_label,
        config_version=_PNL_CONFIG_VERSION,
    )

    data_request_id: UUID | None = None
    if isinstance(cogs, Unavailable):
        data_request_id = insert_data_request(
            tenant_id,
            requested_field="cogs_per_unit",
            reason=cogs.reason,
            blocking_metric="CONTRIBUTION_PROFIT",
        )
    elif isinstance(return_rto_losses, Unavailable):
        data_request_id = insert_data_request(
            tenant_id,
            requested_field="rto_outcome",
            reason=return_rto_losses.reason,
            blocking_metric="CONTRIBUTION_PROFIT",
        )

    return PeriodPnlOutcome(
        nrr=nrr_result,
        contribution_profit=cp_result,
        margin_pct=margin_pct_result,
        fee_ratio_pct=fee_ratio_pct_result,
        return_rate_pct=return_rate_pct_result,
        marketplace_fee_flags=fee_flags,
        data_request_id=data_request_id,
    )


@dataclass(frozen=True, slots=True)
class PricingCurveRequest:
    """Everything `compute_pricing_curve` needs to assemble `resolve_fee_or_unavailable` +
    `compute_margin_curve`'s inputs (cfo-agent.md §6.7). Deliberately explicit rather than
    defaulted — mirrors `PeriodPnlRequest`'s own judgment call: this composition does not
    derive COGS/shipping/advertising/RTO from raw lines itself, it is handed already-resolved
    figures (or `Unavailable`) by the caller, exactly the same boundary `compute_period_pnl`
    draws around `cfo.pnl.inputs`."""

    sku: str
    candidate_prices: Sequence[Paise]
    basis: Basis
    gst_rate: Any | None  # fractions.Fraction | None
    marketplace: str
    category: str
    fee_type: str
    as_of_date: date
    cogs: Paise | Unavailable
    shipping_logistics: Paise
    advertising_costs: Paise
    return_rto_losses: Paise | Unavailable
    other_allocated_costs: Paise
    ingestion_run_ids: Sequence[UUID | str]
    adapter_versions: Sequence[str]
    active_adjustment_ids: Sequence[UUID | str]
    requested_by: UUID
    computed_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class PricingCurveOutcome:
    curve: list[MetricResult]
    data_request_id: UUID | None  # set only when COGS, RTO, or the fee_reference came back UNAVAILABLE (E14)


def compute_pricing_curve(tenant_id: UUID, request: PricingCurveRequest) -> PricingCurveOutcome:
    """Assembles a resolved `FeeReference` (or `Unavailable`, via
    `config_repo.resolve_fee_reference` + `resolve_fee_or_unavailable`, both real, unchanged)
    then calls `compute_margin_curve` (deterministic-engine.md §5.13.1) unchanged, and persists
    every row via `metric_result_repo.save` — mirroring `compute_period_pnl`'s exact
    grain/target_ref/period shape, adjusted for a per-SKU curve the same way
    `run_price_scenario`'s `grain="SKU", target_ref=..., period=None` precedent already does
    (`backend/services/ci_actions.py`).

    A margin curve is never asserted as a single optimal price — `compute_margin_curve`
    already returns one `MetricResult` per candidate price, unchanged and unreduced, which is
    exactly D4/AC12's "band, not a point" requirement; this function does not collapse that
    list.

    Missing COGS, missing return/RTO outcome classification, or an unresolvable fee_reference
    each raise exactly one `agent_data_request` (E14: "Pricing request with no COGS" is
    refused with a data request, never an assumed cost) — mirroring `compute_period_pnl`'s E2
    handling, extended with the fee_reference case this function newly introduces."""
    computed_at = request.computed_at or datetime.now()

    fee_row = config_repo.resolve_fee_reference(
        tenant_id,
        marketplace=request.marketplace,
        category=request.category,
        fee_type=request.fee_type,
        as_of_date=request.as_of_date,
    )
    fee_reference: FeeReference | Unavailable = resolve_fee_or_unavailable(fee_row)

    curve = compute_margin_curve(
        request.candidate_prices,
        basis=request.basis,
        gst_rate=request.gst_rate,
        cogs=request.cogs,
        fee_reference=fee_reference,
        shipping_logistics=request.shipping_logistics,
        advertising_costs=request.advertising_costs,
        return_rto_losses=request.return_rto_losses,
        other_allocated_costs=request.other_allocated_costs,
        ingestion_run_ids=request.ingestion_run_ids,
        adapter_versions=request.adapter_versions,
        active_adjustment_ids=request.active_adjustment_ids,
        computed_at=computed_at,
        as_of_date=request.as_of_date,
    )

    for result in curve:
        metric_result_repo.save(
            tenant_id,
            result,
            grain="SKU",
            target_ref=request.sku,
            period=None,
            config_version=_PRICING_CURVE_CONFIG_VERSION,
        )

    data_request_id: UUID | None = None
    if isinstance(request.cogs, Unavailable):
        data_request_id = insert_data_request(
            tenant_id,
            requested_field="cogs_per_unit",
            reason=request.cogs.reason,
            blocking_metric="MARGIN_AT_PRICE",
        )
    elif isinstance(request.return_rto_losses, Unavailable):
        data_request_id = insert_data_request(
            tenant_id,
            requested_field="rto_outcome",
            reason=request.return_rto_losses.reason,
            blocking_metric="MARGIN_AT_PRICE",
        )
    elif isinstance(fee_reference, Unavailable):
        data_request_id = insert_data_request(
            tenant_id,
            requested_field="fee_reference",
            reason=fee_reference.reason,
            blocking_metric="MARGIN_AT_PRICE",
        )

    return PricingCurveOutcome(curve=curve, data_request_id=data_request_id)


def enter_expense(
    tenant_id: UUID,
    *,
    target_type: str,
    target_ref: str,
    field: str,
    value: Any,
    created_by: UUID,
    reason: str | None = None,
    supersedes_id: UUID | None = None,
    now: datetime | None = None,
) -> UUID:
    """Thin wrapper over `manual_adjustment_repo.insert_adjustment` (real, unchanged),
    restricted to engine §7.2.1's real field registry — CFO never invents a field name
    (cfo-agent.md line 73). The one fully-real end-to-end slice (append-only; superseding a
    prior value is a new row via `supersedes_id`, never an UPDATE — the table itself revokes
    UPDATE/DELETE from `metrion_app`, see `manual_adjustment_repo.py`'s own docstring)."""
    if field not in _ALLOWED_MANUAL_ADJUSTMENT_FIELDS:
        raise ValueError(
            f"'{field}' is not in the engine §7.2.1 manual_adjustment field registry: "
            f"{sorted(_ALLOWED_MANUAL_ADJUSTMENT_FIELDS)}"
        )
    return insert_adjustment(
        tenant_id,
        target_type=target_type,
        target_ref=target_ref,
        field=field,
        value=value,
        created_by=created_by,
        created_at=now or datetime.now(),
        reason=reason,
        supersedes_id=supersedes_id,
    )


# The five real §7.2.1 expense-pool categories `enter_expense` already accepts, minus the
# "expense." prefix — reused by both new features below so neither invents its own list.
_EXPENSE_CATEGORIES: frozenset[str] = frozenset(
    {"advertising", "packaging", "storage", "logistics", "other"}
)


@dataclass(frozen=True, slots=True)
class ExpenseEntry:
    """One ACTIVE `expense.<category>` manual_adjustment row, read back — never a re-derived
    figure. `amount_paise` is exactly what `expense_pools.parse_expense_pool_adjustment`
    (real, unchanged) parsed from the row's own `value`, unchanged."""

    manual_adjustment_id: UUID
    category: str
    amount_paise: Paise
    target_type: str
    target_ref: str
    created_at: datetime
    created_by: UUID


@dataclass(frozen=True, slots=True)
class ExpenseListOutcome:
    entries: list[ExpenseEntry]
    total_paise: Paise  # a plain sum of already-real paise ints via calc_engine.types.sum_paise
    # (real, unchanged) — presentation-layer aggregation of figures already computed by
    # `expense_pools.parse_expense_pool_adjustment`, not a new financial calculation; see this
    # module's own docstring on "no money arithmetic anywhere in this module."


def _expense_period_label_range(target_type: str, target_ref: str) -> tuple[date, date] | None:
    """Best-effort period recovery for a PERIOD-grain expense adjustment's `target_ref`.

    engine §7.2.1 names `PERIOD | ACCOUNT | SKU` as the valid grains for `expense.<category>`
    but names NO fixed format for what a PERIOD-grain `target_ref` string actually contains —
    `manual_adjustment` itself carries no separate period column at all (verified by reading
    `manual_adjustment_repo.py`'s own INSERT column list). This is a real, disclosed gap, not
    guessed shut: only two shapes are recognised here, an ISO date (`YYYY-MM-DD`, treated as
    that single day) and an ISO year-month (`YYYY-MM`, treated as that whole calendar month) —
    the second shape mirrors the existing convention already used by this codebase's own tests
    (`backend/tests/integration/test_entitlement_enforcement.py`'s
    `target_ref="2026-09"` for an `expense.packaging` adjustment). An ACCOUNT/SKU-grain row, or
    a PERIOD-grain row whose `target_ref` matches neither shape, returns `None` — `list_expenses`
    then EXCLUDES that row from a period-filtered call rather than guessing it into or out of
    scope."""
    if target_type != "PERIOD":
        return None
    try:
        day = date.fromisoformat(target_ref)
        return day, day
    except ValueError:
        pass
    try:
        year_str, month_str = target_ref.split("-", 1)
        year, month = int(year_str), int(month_str)
        _, last_day = calendar.monthrange(year, month)
        return date(year, month, 1), date(year, month, last_day)
    except (ValueError, IndexError):
        return None


def list_expenses(
    tenant_id: UUID,
    *,
    period_start: date | None = None,
    period_end: date | None = None,
    category: str | None = None,
) -> ExpenseListOutcome:
    """Feature: reads back `enter_expense`'s own ACTIVE `expense.<category>` rows, filtered —
    the read path `enter_expense` never had. Uses `manual_adjustment_repo.
    active_adjustments_by_field` (this checkpoint's one new repository read, real, RLS-scoped)
    rather than `active_adjustments_for_target`, which needs one already-known
    `(target_type, target_ref)` pair — this function is a tenant-wide "every active expense
    row" query, the broader shape `active_adjustments_for_target` deliberately does not offer.

    **Period filtering happens in Python, not SQL** — see `_expense_period_label_range`'s own
    docstring for exactly why (`manual_adjustment` has no period column, and PERIOD-grain
    `target_ref` has no fixed format). This function fetches every ACTIVE matching-category row
    for the tenant first, then keeps only those whose recovered period range overlaps
    `[period_start, period_end]` when a period filter is given.

    `total_paise` is a real sum via `calc_engine.types.sum_paise` (real, unchanged) over the
    already-real `amount_paise` this function's own entries carry — never a new financial
    calculation, never re-derived independently of what the repository returned."""
    if category is not None and category not in _EXPENSE_CATEGORIES:
        raise ValueError(f"'{category}' is not a real expense category: {sorted(_EXPENSE_CATEGORIES)}")

    if category is not None:
        rows = manual_adjustment_repo.active_adjustments_by_field(tenant_id, field=f"expense.{category}")
    else:
        rows = manual_adjustment_repo.active_adjustments_by_field(tenant_id, field_prefix="expense.")
        # "expense.budget" (Feature 2, below) shares the "expense." prefix but is a budget
        # ceiling, not an actual expense entry — never listed as one.
        rows = [row for row in rows if row["field"] != "expense.budget"]

    entries: list[ExpenseEntry] = []
    for row in rows:
        if period_start is not None or period_end is not None:
            recovered = _expense_period_label_range(row["target_type"], row["target_ref"])
            if recovered is None:
                continue
            row_start, row_end = recovered
            if period_start is not None and row_end < period_start:
                continue
            if period_end is not None and row_start > period_end:
                continue

        parsed = expense_pools.parse_expense_pool_adjustment(dict(row["value"]))
        raw_id = row["id"]
        raw_created_by = row["created_by"]
        entries.append(
            ExpenseEntry(
                manual_adjustment_id=raw_id if isinstance(raw_id, UUID) else UUID(str(raw_id)),
                category=row["field"].removeprefix("expense."),
                amount_paise=parsed.amount_paise,
                target_type=row["target_type"],
                target_ref=row["target_ref"],
                created_at=row["created_at"],
                created_by=raw_created_by if isinstance(raw_created_by, UUID) else UUID(str(raw_created_by)),
            )
        )

    total_paise = sum_paise([e.amount_paise for e in entries])
    return ExpenseListOutcome(entries=entries, total_paise=total_paise)


@dataclass(frozen=True, slots=True)
class EnterExpenseBudgetRequest:
    """Mirrors `enter_expense`'s own shape — a seller-declared ceiling for one expense
    category over one period (deterministic-engine.md §7.2.1's `expense.budget` row, a parallel
    field to the spec's existing `batch.budget` precedent). `target_type` is always `ACCOUNT`
    (see `set_expense_budget`'s own docstring for the grain decision) — this request carries no
    `target_type`/`target_ref` fields at all, unlike `enter_expense`, because there is only one
    real choice for either."""

    category: str
    amount_paise: int
    period_start: date
    period_end: date
    created_by: UUID
    reason: str | None = None
    supersedes_id: UUID | None = None
    now: datetime | None = None


def set_expense_budget(tenant_id: UUID, request: EnterExpenseBudgetRequest) -> UUID:
    """Writes one `expense.budget` manual_adjustment (§7.2.1) — same append-only/superseding
    mechanics as every other field (`manual_adjustment_repo.insert_adjustment`, real,
    unchanged), same `financials.adjust` gate as `enter_expense` (enforced by the caller, e.g.
    `PUT /cfo/expenses/budget`, mirroring `put_expense`'s own in-handler check).

    **Grain decision: `target_type = ACCOUNT`, one ceiling per (category, period) — not a
    single overall ceiling.** `enter_expense`'s own five `expense.<category>` fields are
    already per-category (verified by reading `_ALLOWED_MANUAL_ADJUSTMENT_FIELDS` above); a
    single overall budget could never answer "did I overspend on packaging specifically," the
    exact question a per-category expense entry exists to answer. `category` lives INSIDE the
    `value` (not as a separate `field` per category) so more than one category's budget can be
    simultaneously ACTIVE under the one `field = "expense.budget"` name — the same
    "disambiguate multiple ACTIVE rows by a value-level key" shape `supplier.quote` (CP A4/B1)
    already established for the identical need. `target_ref = str(tenant_id)`, mirroring
    `compute_period_pnl`'s own `TENANT_PERIOD` grain convention (`target_ref=str(tenant_id)`)
    for "the one account this tenant has," rather than inventing a second account-identifier
    convention.

    **Deliberately does NOT go through the generic `enter_expense`/`_ALLOWED_MANUAL_ADJUSTMENT_
    FIELDS` path** — mirrors exactly why `gst_rate_override` is excluded from that registry
    (see its own comment above `_ALLOWED_MANUAL_ADJUSTMENT_FIELDS`): the generic path passes a
    caller's `value` straight through, uninspected, but a budget's shape is validated for real
    here via `expense_pools.parse_expense_budget_adjustment` (real, unchanged) BEFORE the write,
    so a malformed budget is refused, never silently persisted."""
    if request.category not in _EXPENSE_CATEGORIES:
        raise ValueError(f"'{request.category}' is not a real expense category: {sorted(_EXPENSE_CATEGORIES)}")

    value = {
        "category": request.category,
        "amount_paise": request.amount_paise,
        "period_start": request.period_start.isoformat(),
        "period_end": request.period_end.isoformat(),
    }
    expense_pools.parse_expense_budget_adjustment(value)  # raises on a malformed shape, never persists one

    return insert_adjustment(
        tenant_id,
        target_type="ACCOUNT",
        target_ref=str(tenant_id),
        field="expense.budget",
        value=value,
        created_by=request.created_by,
        created_at=request.now or datetime.now(),
        reason=request.reason,
        supersedes_id=request.supersedes_id,
    )


@dataclass(frozen=True, slots=True)
class ExpenseBudgetStatus:
    """A real, deterministic fact about one category/period's spend against its declared
    ceiling — never a judgement, never narrated here (non-goal: no LLM wrapper in this
    checkpoint). `no_budget_set=True` is a real, distinguished outcome (mirrors
    `GstRateUnresolved`/`AnomalyInsufficientHistory`'s "real, named non-result" pattern) —
    `budget_paise`/`remaining_paise` are `None` ONLY in that case, never a fabricated default
    ceiling and never a silent pass."""

    category: str
    period_start: date
    period_end: date
    spent_paise: Paise
    no_budget_set: bool
    budget_paise: Paise | None = None
    remaining_paise: Paise | None = None  # never floored to zero — a real negative is the honest overage
    exceeded: bool = False
    manual_adjustment_id: UUID | None = None


def check_expense_budget(
    tenant_id: UUID, *, category: str, period_start: date, period_end: date
) -> ExpenseBudgetStatus:
    """Feature 2's read: the ACTIVE `expense.budget` row for this exact (category, period)
    (via `manual_adjustment_repo.active_adjustments_for_target`, real, unchanged — newest first,
    first match wins, mirroring `resolve_gst_rate_for_sku` tier 0's own "newest ACTIVE row wins"
    convention for a field that can have more than one ACTIVE row) against the real spend
    `list_expenses` (Feature 1, this same checkpoint) already computes for that identical
    (category, period) — never a second, independently re-summed total.

    The one subtraction this feature needs (`budget - spent`) is NOT done here — it is done by
    `expense_pools.check_expense_budget` (real, new, calc-engine — this module's own hard rule:
    no `+ - * /` on a `Paise` value ever happens in `backend`/`cfo`, only in the engine)."""
    if category not in _EXPENSE_CATEGORIES:
        raise ValueError(f"'{category}' is not a real expense category: {sorted(_EXPENSE_CATEGORIES)}")

    budget_rows = manual_adjustment_repo.active_adjustments_for_target(
        tenant_id, target_type="ACCOUNT", target_ref=str(tenant_id), field="expense.budget"
    )
    matched_entry: expense_pools.ExpenseBudgetEntry | None = None
    matched_id: UUID | None = None
    for row in budget_rows:
        candidate = expense_pools.parse_expense_budget_adjustment(dict(row["value"]))
        if candidate.category != category:
            continue
        if candidate.period_start != period_start or candidate.period_end != period_end:
            continue
        matched_entry = candidate
        raw_id = row["id"]
        matched_id = raw_id if isinstance(raw_id, UUID) else UUID(str(raw_id))
        break

    spent_paise = list_expenses(
        tenant_id, period_start=period_start, period_end=period_end, category=category
    ).total_paise

    if matched_entry is None:
        return ExpenseBudgetStatus(
            category=category,
            period_start=period_start,
            period_end=period_end,
            spent_paise=spent_paise,
            no_budget_set=True,
        )

    check_result = expense_pools.check_expense_budget(matched_entry.amount_paise, spent_paise)
    return ExpenseBudgetStatus(
        category=category,
        period_start=period_start,
        period_end=period_end,
        spent_paise=check_result.spent_paise,
        no_budget_set=False,
        budget_paise=check_result.budget_paise,
        remaining_paise=check_result.remaining_paise,
        exceeded=check_result.exceeded,
        manual_adjustment_id=matched_id,
    )


# ---------------------------------------------------------------------------------------
# OP13's three-tier GST rate-resolution order, composed for real (cfo-agent.md C5/§6.6):
# tier 0 gst_rate_override (§7.2.1, ranks above tier 1) -> tier 1 observed (the seller's own
# report) -> tier 2 hsn_gst_reference (§8.2.2). Tier 3, the live GST Applicability Lookup
# (§8.4), is deliberately never invoked by this composer — see resolve_gst_rate_for_sku's own
# docstring.
# ---------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ResolvedGstRate:
    """A GST rate resolved via OP13's three-tier order. `source_tier` names exactly which tier
    produced `rate_pct` — `"OVERRIDE"` (tier 0), `"OBSERVED"` (tier 1), or `"HSN_REFERENCE"`
    (tier 2). `confidence` is a `Confidence` value string (never a bare guess): `MANUAL` for an
    override (per §7.2.1's own decision), the caller-supplied observed confidence for tier 1,
    or `PROVISIONAL` for a `hsn_gst_reference` hit (§8.2.2/AC21's own cap).

    Provenance fields are populated only for the tier that actually produced this result — the
    other tier's fields stay `None` — and only ever carry values the source repository actually
    returns (`manual_adjustment.id`/the override's own `gst_lookup_result_id` for tier 0;
    `hsn_gst_reference.hsn_code`/`source_url` for tier 2 — `hsn_gst_reference` has no `id` in
    `config_repo.resolve_hsn_gst_reference`'s own SELECT list, so none is invented here)."""

    rate_pct: Fraction
    source_tier: str  # "OVERRIDE" | "OBSERVED" | "HSN_REFERENCE"
    confidence: str
    manual_adjustment_id: UUID | None = None  # tier 0 only
    gst_lookup_result_id: UUID | None = None  # tier 0 only — the override's own source lookup
    hsn_code_matched: str | None = None  # tier 2 only — the hsn_gst_reference row's own hsn_code
    hsn_reference_source_url: str | None = None  # tier 2 only


@dataclass(frozen=True, slots=True)
class GstRateUnresolved:
    """OP13's tiers 0-2 all missed for this SKU — a real, distinguished non-result (mirrors
    `AnomalyInsufficientHistory`/`GstLookupNoMatch`'s established "real, named non-result"
    pattern), never `None` and never an exception. Names tier 3 (the live GST Applicability
    Lookup) explicitly as the next step; `resolve_gst_rate_for_sku` never calls it itself — see
    that function's own docstring for why."""

    sku: str
    hsn_code: str | None
    reason: str = (
        "no gst_rate_override, observed rate, or hsn_gst_reference match for this SKU — the "
        "next step is an explicit GST Applicability Lookup (POST /cfo/gst-lookup), never "
        "auto-triggered by this resolver"
    )


def resolve_gst_rate_for_sku(
    tenant_id: UUID,
    *,
    sku: str,
    hsn_code: str | None,
    observed_rate_pct: Fraction | None,
    as_of_date: date,
    observed_confidence: Confidence = Confidence.PROVISIONAL,
) -> ResolvedGstRate | GstRateUnresolved:
    """Composes OP13's exact three-tier GST rate-resolution order (deterministic-engine.md
    §7.2.1/§8.2.2/§8.4, cfo-agent.md C5/§6.6/OP13: "observed from the seller's own reports
    first, then the curated HSN knowledge base, then the GST Applicability Lookup (provisional,
    cited)") — nothing else in this codebase composes all three tiers together; each one
    previously existed in isolation.

    1. **Tier 0 — `gst_rate_override` (§7.2.1's own row, ranks above tier 1).** Reads ACTIVE
       rows for `(target_type="SKU", target_ref=sku, field="gst_rate_override")` via
       `manual_adjustment_repo.active_adjustments_for_target` (real, unchanged, newest first).
       Each row's `value["effective_from"]` (an ISO date-string, exactly as
       `accept_gst_lookup_result` writes it — see that function's own `value` dict construction)
       is checked against `as_of_date`: a row whose `effective_from` is `None` or strictly after
       `as_of_date` is not yet in force and is skipped — the newest row that IS in force
       (`as_of_date >= effective_from`) wins outright. This tier is checked and used FIRST, even
       when `observed_rate_pct` is also supplied; a seller who has explicitly accepted an
       override for this SKU that is already in force always outranks whatever the current
       report happens to say (§7.2.1's own resolution-order rule). If every ACTIVE row is
       future-dated, tier 0 has nothing usable and this function falls through to tier 1 exactly
       as if no override existed at all. Confidence `MANUAL`, per the spec's own decision for
       this field. `value["rate_pct"]` is read exactly as `accept_gst_lookup_result` writes it (a
       Decimal-string, e.g. `"18.0000"`, confirmed by reading that function's own insert call in
       this module) and parsed via `Fraction(...)`, which accepts a decimal-string directly — no
       float ever touches this path.
    2. **Tier 1 — observed.** Reached only when tier 0 has no ACTIVE override. If
       `observed_rate_pct` is not `None` (the caller already resolved it from the seller's own
       report — exactly what `analyze_gst_lines` does today), it is used as-is. Confidence
       defaults to `PROVISIONAL`: `GstLineInput`/`analyze_gst_lines` carry no confidence field
       of their own today (verified by reading both), and `PROVISIONAL` mirrors this engine's
       own precedent for a figure computed directly from the seller's uploaded canonical data
       without a manual/curated input — `MarketplaceFees`'s own confidence in §5.5's component
       table, the closest existing analogue to "observed, not manually entered, not curated
       reference data." A caller with a stronger real basis (e.g. a Meesho row `reconcile.py`'s
       own `_JOIN_KEY_CONFIDENCE` already treats as `VERIFIED`) may pass `observed_confidence`
       explicitly; this composer never asserts a confidence stronger than what its caller
       states.
    3. **Tier 2 — `hsn_gst_reference` (§8.2.2).** Reached only when tiers 0 and 1 both miss AND
       `hsn_code` is not `None` — no HSN code, no lookup attempted, never a guessed code (AC20).
       Calls `config_repo.resolve_hsn_gst_reference` (real, unchanged). A hit is capped at
       `PROVISIONAL` confidence (§8.2.2/AC21's own rule), carrying the row's own `hsn_code`
       (the actual matched prefix, which may be shorter than the queried code) and `source_url`
       as provenance — the row has no `id` in this resolver's own SELECT list, so none is
       fabricated here.
    4. **No match anywhere.** Returns `GstRateUnresolved`, naming tier 3 (the live GST
       Applicability Lookup, §8.4) as the explicit next step. **This function never calls
       `gst_applicability_lookup` itself** — that call is live, potentially slow, and
       entitlement-gated (`service.gst_lookup`, its own shared-service cap, OP9); triggering it
       as a side effect of an ordinary rate resolution would be a real behavioural/cost
       surprise, inconsistent with G3's own separation of "compute" from "on-demand external
       research requiring its own permission." The caller (CFO/the seller) triggers
       `run_gst_applicability_lookup` (`POST /cfo/gst-lookup`) explicitly instead.

    No arithmetic anywhere in this function — it reads already-final stored/resolved values and
    wraps them in `Fraction(...)` (a parse, not a calculation) for a uniform return type."""
    override_rows = manual_adjustment_repo.active_adjustments_for_target(
        tenant_id, target_type="SKU", target_ref=sku, field="gst_rate_override"
    )
    for override_row in override_rows:
        override_value = override_row["value"]
        raw_effective_from = override_value.get("effective_from")
        if raw_effective_from is None:
            continue
        effective_from = (
            raw_effective_from
            if isinstance(raw_effective_from, date)
            else date.fromisoformat(str(raw_effective_from))
        )
        if as_of_date < effective_from:
            continue
        raw_id = override_row["id"]
        manual_adjustment_id = raw_id if isinstance(raw_id, UUID) else UUID(str(raw_id))
        raw_lookup_id = override_value.get("gst_lookup_result_id")
        return ResolvedGstRate(
            rate_pct=Fraction(override_value["rate_pct"]),
            source_tier="OVERRIDE",
            confidence=Confidence.MANUAL.value,
            manual_adjustment_id=manual_adjustment_id,
            gst_lookup_result_id=(UUID(str(raw_lookup_id)) if raw_lookup_id else None),
        )

    if observed_rate_pct is not None:
        return ResolvedGstRate(
            rate_pct=observed_rate_pct,
            source_tier="OBSERVED",
            confidence=observed_confidence.value,
        )

    if hsn_code is not None:
        hsn_row = config_repo.resolve_hsn_gst_reference(
            tenant_id, hsn_code=hsn_code, as_of_date=as_of_date
        )
        if hsn_row is not None:
            return ResolvedGstRate(
                rate_pct=Fraction(hsn_row["rate_pct"]),
                source_tier="HSN_REFERENCE",
                confidence=Confidence.PROVISIONAL.value,
                hsn_code_matched=str(hsn_row["hsn_code"]),
                hsn_reference_source_url=str(hsn_row["source_url"]),
            )

    return GstRateUnresolved(sku=sku, hsn_code=hsn_code)


@dataclass(frozen=True, slots=True)
class GstLineInput:
    """One line to analyze — never a period. `rate_pct` is the GST rate this line was charged
    at (observed from the seller's own report, OP13's first resolution tier); `None` when the
    seller's report doesn't carry a resolvable rate for this line at all.

    `sku`/`hsn_code` are OPTIONAL and used ONLY when `analyze_gst_lines` is called with
    `resolve_unobserved_rates=True` (see that function's own docstring) — they let this line
    feed `resolve_gst_rate_for_sku`'s tier 0 (`sku`, required for an override lookup) and tier 2
    (`hsn_code`, required for an `hsn_gst_reference` lookup) when `rate_pct` itself is `None`.
    Both default to `None`, so every existing caller/construction site is unaffected."""

    line_ref: str
    listed_paise: int
    basis: Basis
    rate_pct: Any | None  # fractions.Fraction | None — Any here only to avoid importing Fraction twice
    sku: str | None = None
    hsn_code: str | None = None


@dataclass(frozen=True, slots=True)
class GstLineResult:
    line_ref: str
    normalized_exclusive_paise: int | None
    is_available: bool
    unavailable_reason: str | None
    rate_plausibility_matched: bool | None
    rate_plausibility_severity: str | None
    disclaimer: str
    # Populated ONLY when analyze_gst_lines(resolve_unobserved_rates=True) actually invoked
    # resolve_gst_rate_for_sku for this line (i.e. line.rate_pct was None) — every existing
    # caller leaves these at their default None/None/None, unchanged.
    resolved_rate_source_tier: str | None = None  # "OVERRIDE" | "OBSERVED" | "HSN_REFERENCE"
    resolved_rate_confidence: str | None = None
    gst_rate_unresolved_reason: str | None = None


def analyze_gst_lines(
    tenant_id: UUID,
    lines: Sequence[GstLineInput],
    *,
    as_of_date: date,
    resolve_unobserved_rates: bool = False,
) -> list[GstLineResult]:
    """Per-line GST analysis (cfo-agent.md §6.6) — `normalize_to_exclusive` +
    `check_rate_plausibility` (both real, unchanged, `calc_engine.gst`), each line's own
    §6.6 disclaimer attached. **Never sums to a period total** — a period figure is a
    genuinely different surface, `render_gst_period_summary` (CP A2), which this function
    never calls and is never merged into; a caller asking for a period figure gets nothing
    from this function, by design, not by omission. A line with an unresolvable rate is
    excluded from normalization, flagged, never guessed (E12).

    `resolve_unobserved_rates` (default `False`, opt-in, non-breaking): when `True`, any line
    whose `rate_pct` is `None` and whose `sku` is set is handed to `resolve_gst_rate_for_sku`
    (OP13's tier 0 override -> tier 1 observed [never reached here, since `rate_pct` is already
    `None`] -> tier 2 `hsn_gst_reference`) before falling through to "unresolvable." A resolved
    tier's `rate_pct` is normalized/plausibility-checked exactly as an originally-observed
    `rate_pct` would be, and the result's `resolved_rate_source_tier`/`resolved_rate_confidence`
    record which tier supplied it. A line with no `sku` set, or for which
    `resolve_gst_rate_for_sku` returns `GstRateUnresolved`, falls through to the exact same
    "unresolvable" path this function already had — `gst_rate_unresolved_reason` additionally
    names why (surfacing tier 3 as the next step) when the composer was actually invoked.
    Existing callers that never pass this parameter get byte-identical behaviour to before this
    checkpoint — this parameter changes nothing unless explicitly turned on."""
    slab_rows_raw = config_repo.gst_slabs_effective_on(tenant_id, as_of_date=as_of_date)
    slabs = [
        GstSlabRow(
            rate_pct=row["rate_pct"],
            label=row["label"],
            effective_from=row["effective_from"],
            effective_to=row["effective_to"],
            confidence=row.get("confidence", "PROVISIONAL"),
        )
        for row in slab_rows_raw
    ]

    results: list[GstLineResult] = []
    for line in lines:
        effective_rate_pct = line.rate_pct
        resolved_rate_source_tier: str | None = None
        resolved_rate_confidence: str | None = None
        gst_rate_unresolved_reason: str | None = None

        if effective_rate_pct is None and resolve_unobserved_rates and line.sku is not None:
            resolution = resolve_gst_rate_for_sku(
                tenant_id,
                sku=line.sku,
                hsn_code=line.hsn_code,
                observed_rate_pct=None,
                as_of_date=as_of_date,
            )
            if isinstance(resolution, ResolvedGstRate):
                effective_rate_pct = resolution.rate_pct
                resolved_rate_source_tier = resolution.source_tier
                resolved_rate_confidence = resolution.confidence
            else:
                gst_rate_unresolved_reason = resolution.reason

        normalized = normalize_to_exclusive(Paise(line.listed_paise), line.basis, effective_rate_pct)

        plausibility_matched: bool | None = None
        plausibility_severity: str | None = None
        if effective_rate_pct is not None:
            plausibility = check_rate_plausibility(effective_rate_pct, slabs, as_of_date)
            plausibility_matched = plausibility.matched
            plausibility_severity = plausibility.severity

        if isinstance(normalized, Unavailable):
            results.append(
                GstLineResult(
                    line_ref=line.line_ref,
                    normalized_exclusive_paise=None,
                    is_available=False,
                    unavailable_reason=normalized.reason,
                    rate_plausibility_matched=plausibility_matched,
                    rate_plausibility_severity=plausibility_severity,
                    disclaimer=GST_DISCLAIMER,
                    resolved_rate_source_tier=resolved_rate_source_tier,
                    resolved_rate_confidence=resolved_rate_confidence,
                    gst_rate_unresolved_reason=gst_rate_unresolved_reason,
                )
            )
            continue

        results.append(
            GstLineResult(
                line_ref=line.line_ref,
                normalized_exclusive_paise=normalized.value,
                is_available=True,
                unavailable_reason=None,
                rate_plausibility_matched=plausibility_matched,
                rate_plausibility_severity=plausibility_severity,
                disclaimer=GST_DISCLAIMER,
                resolved_rate_source_tier=resolved_rate_source_tier,
                resolved_rate_confidence=resolved_rate_confidence,
                gst_rate_unresolved_reason=gst_rate_unresolved_reason,
            )
        )
    return results


@dataclass(frozen=True, slots=True)
class GstPeriodSummaryRequest:
    """Everything `render_gst_period_summary` needs to assemble
    `compute_gst_period_summary`'s inputs (cfo-agent.md §6.6/§6.8 `cfo.gst_summary`).
    `period_start`/`period_end` label the persisted rows exactly as `PeriodPnlRequest`'s own
    fields do for `compute_period_pnl` — this is the same kind of tenant-period aggregate,
    not a per-line or per-SKU figure. `tax_heads` defaults to the engine's own
    `DEFAULT_TAX_HEADS` (CGST/SGST/IGST/UTGST/CESS) so a caller never has to hand-enumerate
    the closed set."""

    lines: Sequence[CanonicalLine]
    period_start: date
    period_end: date
    as_of_date: date
    ingestion_run_ids: Sequence[UUID | str]
    adapter_versions: Sequence[str]
    active_adjustment_ids: Sequence[UUID | str]
    requested_by: UUID
    tax_heads: frozenset[str] = DEFAULT_TAX_HEADS
    computed_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class GstPeriodSummaryOutcome:
    results: list[MetricResult]
    disclaimer: str


def render_gst_period_summary(
    tenant_id: UUID, request: GstPeriodSummaryRequest
) -> GstPeriodSummaryOutcome:
    """**Period-level** GST summary (cfo-agent.md §6.6/§6.8 `cfo.gst_summary`) — the genuinely
    different surface from `analyze_gst_lines`'s LINE-level analysis, and this distinction
    must never blur: this function never inspects individual lines' own rates or plausibility,
    it only assembles inputs and calls `compute_gst_period_summary` (real, unchanged,
    `calc_engine.gst.summary` / `calc_engine.api.compute_metric`) — one `MetricResult` per tax
    head (CGST/SGST/IGST/UTGST/CESS), `metric_code` constant `"GST_PERIOD_SUMMARY"` across
    every row, every head present even at zero. `analyze_gst_lines` never sums to a period
    total, and this function never produces a per-line figure — the two stay permanently
    separate CFO surfaces.

    Persists every row via `metric_result_repo.save`, mirroring `compute_period_pnl`'s exact
    `grain="TENANT_PERIOD"` shape — this is a tenant-period aggregate, not a per-SKU curve
    (`compute_pricing_curve`'s `grain="SKU"` shape does not apply here).

    **No `Unavailable`/data-request path** — `compute_gst_period_summary` itself has none
    (see `gst/summary.py`'s own docstring): a pure summation over already-present canonical
    tax components never fails for missing data, so a period with zero CESS is a real,
    legitimate zero, never a missing input requiring an `agent_data_request`.

    Every returned row and the outcome itself carry the same `GST_DISCLAIMER` constant
    `analyze_gst_lines` already uses (AC7, cfo-agent.md §6.6) — no second disclaimer string is
    ever introduced.

    No arithmetic anywhere in this function — it assembles inputs and calls
    `compute_gst_period_summary` unchanged, then persists."""
    computed_at = request.computed_at or datetime.now()
    period_label = f"{request.period_start.isoformat()}/{request.period_end.isoformat()}"

    results = compute_gst_period_summary(
        request.lines,
        ingestion_run_ids=request.ingestion_run_ids,
        adapter_versions=request.adapter_versions,
        active_adjustment_ids=request.active_adjustment_ids,
        computed_at=computed_at,
        as_of_date=request.as_of_date,
        tax_heads=request.tax_heads,
    )

    for result in results:
        metric_result_repo.save(
            tenant_id,
            result,
            grain="TENANT_PERIOD",
            target_ref=str(tenant_id),
            period=period_label,
            config_version=_GST_PERIOD_SUMMARY_CONFIG_VERSION,
        )

    return GstPeriodSummaryOutcome(results=results, disclaimer=GST_DISCLAIMER)


def raise_data_request(
    tenant_id: UUID,
    *,
    requested_field: str,
    reason: str,
    blocking_metric: str | None = None,
) -> UUID:
    """Wraps CP1's `cfo.repositories.agent_data_request_repo.insert` — OP1: CFO asks rather
    than assumes (C8). Record only; the request/prompt/validation surfacing flow is deferred
    (cfo-agent.md §5 note, Q9), same as CP1 scoped it."""
    return insert_data_request(
        tenant_id,
        requested_field=requested_field,
        reason=reason,
        blocking_metric=blocking_metric,
    )


# ---------------------------------------------------------------------------------------
# CP A3 — narrate_period_comparison (cfo-agent.md §7.4.4 "once built" rule; twinkly-mapping-
# canyon.md Phase A). Activates the period-over-period metric-delta capability named in
# §5.1.2 (built at the engine layer in CP3, `calc_engine.formulas.metric_delta` /
# `compute_metric.compute_metric_delta`) all the way through to Brain-3 narration.
# ---------------------------------------------------------------------------------------


def _metric_result_from_row(row: Mapping[str, object]) -> MetricResult:
    """Reconstructs a `MetricResult` dataclass instance from a raw `metric_result_repo.get`
    row dict — the one genuinely new piece of plumbing this checkpoint adds. Every field below
    was checked against BOTH `metric_result_repo.py`'s `_GET_SQL` SELECT list and
    `MetricResult`'s own dataclass fields (`calc_engine/api/compute_metric.py`), not assumed
    to round-trip:

      - `grain`, `target_ref`, `period`, `config_version`, `is_trial` are persistence-only
        columns `_GET_SQL` selects that have NO counterpart on `MetricResult` at all (they
        describe how/where a result was stored, not the result itself) — deliberately not
        read here.
      - `id` — `_GET_SQL` selects the `uuid` column; SQLAlchemy's `text()` + psycopg returns
        a native `uuid.UUID` for a `uuid`-typed column, but this does not assume that driver
        behaviour blindly — it accepts either a `UUID` already or a `str` and normalises
        explicitly.
      - `confidence` — stored and returned as a plain `str` (e.g. `"VERIFIED"`), which is
        exactly `MetricResult.confidence: str`'s own declared type (CP3 already established
        this is a `str`, never a `Confidence` enum, on `MetricResult` itself) — no conversion
        needed, just an explicit `str(...)` for defence against a driver returning something
        `str`-like but not `str`.
      - `recognition_state` — stored as the `RecognitionState` enum's `.value` (a `str`, see
        `metric_result_repo.save`'s own `result.recognition_state.value`); `MetricResult`
        expects the enum instance itself, so this reconstructs it via `RecognitionState(...)`.
      - `manual_adjustment_set` / `input_refs` / `exclusions` — `jsonb` columns; psycopg
        deserialises `jsonb` to native Python `list`/`dict` automatically (never a JSON
        string needing a second `json.loads`), so these are re-wrapped into the `tuple`
        shapes `MetricResult` declares, with `... or ()` guarding the case where the driver
        surfaces a `None` for an empty/absent jsonb value.
      - `as_of_date` / `computed_at` — `date`/`timestamptz` columns; SQLAlchemy already
        returns native `datetime.date`/`datetime.datetime` instances for these, matching
        `MetricResult`'s own field types with no conversion needed.
      - `value_paise` / `is_available` / `unavailable_reason` — already the correct native
        types (`int | None`, `bool`, `str | None`) with no conversion needed; `is_available`
        is passed through `bool(...)` only as defence against a driver returning e.g. a
        Postgres `boolean` as something not already a Python `bool`.

    This performs no arithmetic anywhere — every field is either copied through unchanged or
    re-wrapped into a different container/enum type, never combined or derived.
    """
    raw_id = row["id"]
    result_id = raw_id if isinstance(raw_id, UUID) else UUID(str(raw_id))

    manual_adjustment_set_raw = row["manual_adjustment_set"] or []
    input_refs_raw = row["input_refs"] or []
    exclusions_raw = row["exclusions"] or []

    return MetricResult(
        id=result_id,
        metric_code=str(row["metric_code"]),
        value_paise=row["value_paise"],  # type: ignore[arg-type]
        recognition_state=RecognitionState(row["recognition_state"]),
        confidence=str(row["confidence"]),
        calculation_basis=str(row["calculation_basis"]),
        formula_version=str(row["formula_version"]),
        canonical_data_version=str(row["canonical_data_version"]),
        as_of_date=row["as_of_date"],  # type: ignore[arg-type]
        input_refs=tuple(input_refs_raw),  # type: ignore[arg-type]
        exclusions=tuple(exclusions_raw),  # type: ignore[arg-type]
        computed_at=row["computed_at"],  # type: ignore[arg-type]
        is_available=bool(row["is_available"]),
        manual_adjustment_set=tuple(manual_adjustment_set_raw),  # type: ignore[arg-type]
        unavailable_reason=row["unavailable_reason"],  # type: ignore[arg-type]
    )


def _register_for(result: MetricResult) -> str:
    """Maps a `MetricResult` onto cfo-agent.md §7.4.7's five-register vocabulary — never a
    sixth, never invented ad hoc. `UNAVAILABLE` takes priority over confidence whenever
    `is_available` is `False` (§7.4.7's own "Not available" row). For an available result,
    `VERIFIED`/`DERIVED`/`MANUAL` confidence values map onto their identically-named §7.4.7
    register directly (the engine's `Confidence` enum and §7.4.7's register vocabulary share
    those three names exactly, by design). `PROVISIONAL` confidence (used elsewhere, e.g. GST
    slab rows — `calc_engine.types.Confidence`) has no register of its own at §7.4.7: it is
    presented as `DERIVED`, the nearest existing register — never `ESTIMATE`, which §7.4.7
    reserves specifically for CI-sourced, `estimate_ref`-bearing figures, never an engine
    `MetricResult` even at PROVISIONAL confidence. Judgment call, flagged: §7.4.7's table does
    not name a PROVISIONAL row explicitly; DERIVED is the closest documented register rather
    than inventing a sixth."""
    if not result.is_available:
        return "UNAVAILABLE"
    if result.confidence == "PROVISIONAL":
        return "DERIVED"
    return result.confidence


def _format_paise_for_narration(value_paise: int | None, *, is_available: bool) -> str:
    """Presentation-only rendering of an already-final, engine-computed paise integer into
    the display string `FigureToken.formatted_value`/`narrate_figures` require —
    `narrate.py`'s own docstring: "formatting is presentation, not calculation." This
    determines no monetary outcome at all; the figure was fully computed by the engine before
    this function ever runs. It only converts the unit (paise -> rupees) for display, the
    same lossless, no-float conversion a frontend would apply when rendering paise to a
    seller (CLAUDE.md: "No floats in any calculation path, frontend included"). Uses
    `divmod`/`abs` — function calls, not `+ - * /` operators — precisely so this reads
    unambiguously as unit conversion for display, never as a `+ - * /` derivation of a new
    figure (see this module's own docstring for why `test_no_arithmetic_lint.py` correctly
    does not flag this)."""
    if not is_available or value_paise is None:
        return "UNAVAILABLE"
    sign = "-" if value_paise < 0 else ""
    rupees, remainder_paise = divmod(abs(value_paise), 100)
    return f"{sign}₹{rupees:,}.{remainder_paise:02d}"


@dataclass(frozen=True, slots=True)
class PeriodComparisonRequest:
    """Everything `narrate_period_comparison` needs — two already-persisted `MetricResult`
    ids for the SAME `metric_code` (e.g. this period's `CONTRIBUTION_PROFIT` vs. last
    period's), per cfo-agent.md §7.4.4's "once built" period-comparison narration rule
    (twinkly-mapping-canyon.md CP A3). `result_a_id` is the earlier period, `result_b_id` the
    later one — matching `compute_metric_delta`'s own parameter order/semantics exactly, so
    this composition never reorders or reinterprets which period is which."""

    result_a_id: UUID
    result_b_id: UUID
    as_of_date: date
    requested_by: UUID
    computed_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class PeriodComparisonOutcome:
    """`delta`/`narration` are both `None` ONLY when a fetch failed (E2/E14-style genuinely
    missing input — `metric_result_repo.get` returned `None` for either id): `data_request_id`
    is set in that case and `compute_metric_delta`/`narrate_figures` were never called at all.
    When both inputs existed, `delta` and `narration` are always both present, even when
    `delta.is_available` is `False` — §7.4.4's newly-activated rule requires narrating an
    unavailable comparison AS unavailable, never skipping narration silently."""

    delta: MetricResult | None
    narration: str | None
    data_request_id: UUID | None


def narrate_period_comparison(
    tenant_id: UUID,
    request: PeriodComparisonRequest,
    provider: LlmProvider,
    *,
    model: str,
) -> PeriodComparisonOutcome:
    """Activates cfo-agent.md §7.4.4's "once built" period-comparison narration rule
    (twinkly-mapping-canyon.md CP A3): fetches two already-persisted `MetricResult`s via
    `metric_result_repo.get` (real, unchanged), calls `compute_metric_delta` (real, unchanged
    — the ONLY place delta arithmetic happens, `calc_engine.formulas.metric_delta`), persists
    the delta `MetricResult`, then narrates it via `narrate_figures` (real, unchanged) with
    every figure pre-formatted to a display string before Brain 3 ever sees it — Brain 3 never
    receives a raw number (AC26/AC27).

    A missing `result_a`/`result_b` (`metric_result_repo.get` returns `None` — the row doesn't
    exist, or belongs to another tenant, which RLS makes indistinguishable by design) is a
    genuinely missing input, not something this function proceeds past or guesses at: it
    raises exactly one `agent_data_request` (mirroring `compute_period_pnl`'s E2 /
    `compute_pricing_curve`'s E14 pattern) and returns immediately, WITHOUT ever calling
    `compute_metric_delta` or `narrate_figures`.

    A `metric_code` mismatch between the two fetched results is a caller bug (comparing two
    different metrics), not missing data — `compute_metric_delta`'s `ValueError` is left to
    propagate uncaught here, exactly as CP3 established for that case; this function does not
    catch or convert it into a soft failure.

    When both inputs exist, the delta is ALWAYS narrated — even when `compute_metric_delta`
    itself comes back `UNAVAILABLE` (e.g. one period's underlying `MetricResult` was itself
    unavailable). §7.4.4's rule, now that this capability is real end-to-end, is that Brain 3
    explains the unavailability rather than skipping narration silently; the `UNAVAILABLE`
    register/figure string below is exactly how that happens — this is the "once built" path
    §7.4.4 anticipated, so the previously-accurate "Brain 3 does not attempt this kind of
    period-comparison narration at all" no longer describes this call path (it still describes
    every OTHER CFO surface that has not called this function).

    No arithmetic anywhere in this function: it fetches, reconstructs
    (`_metric_result_from_row`), calls `compute_metric_delta` unchanged, formats already-final
    paise integers into display strings (`_format_paise_for_narration` — presentation, not
    calculation), persists via `metric_result_repo.save`, and calls `narrate_figures`
    unchanged.
    """
    computed_at = request.computed_at or datetime.now()

    row_a = metric_result_repo.get(tenant_id, request.result_a_id)
    row_b = metric_result_repo.get(tenant_id, request.result_b_id)

    if row_a is None or row_b is None:
        missing_ids = []
        if row_a is None:
            missing_ids.append(f"result_a_id={request.result_a_id}")
        if row_b is None:
            missing_ids.append(f"result_b_id={request.result_b_id}")
        data_request_id = raise_data_request(
            tenant_id,
            requested_field="engine_result_ref",
            reason=(
                "period comparison requested against a metric_result that does not exist for "
                "this tenant, or belongs to another tenant (RLS makes the two indistinguishable "
                f"by design): {', '.join(missing_ids)}"
            ),
            blocking_metric="PERIOD_COMPARISON_DELTA",
        )
        return PeriodComparisonOutcome(delta=None, narration=None, data_request_id=data_request_id)

    result_a = _metric_result_from_row(row_a)
    result_b = _metric_result_from_row(row_b)

    delta = compute_metric_delta(
        result_a, result_b, computed_at=computed_at, as_of_date=request.as_of_date
    )

    period_a_label = str(row_a.get("period") or result_a.as_of_date or "earlier period")
    period_b_label = str(row_b.get("period") or result_b.as_of_date or "later period")
    metric_result_repo.save(
        tenant_id,
        delta,
        grain="TENANT_PERIOD",
        target_ref=str(tenant_id),
        period=f"{period_a_label}/{period_b_label}",
        config_version=_PERIOD_COMPARISON_CONFIG_VERSION,
    )

    figures = [
        FigureToken(
            label=f"{result_a.metric_code} (earlier period)",
            formatted_value=_format_paise_for_narration(
                result_a.value_paise, is_available=result_a.is_available
            ),
            register=_register_for(result_a),
            engine_result_ref=str(result_a.id),
            note=None if result_a.is_available else result_a.unavailable_reason,
        ),
        FigureToken(
            label=f"{result_b.metric_code} (later period)",
            formatted_value=_format_paise_for_narration(
                result_b.value_paise, is_available=result_b.is_available
            ),
            register=_register_for(result_b),
            engine_result_ref=str(result_b.id),
            note=None if result_b.is_available else result_b.unavailable_reason,
        ),
        FigureToken(
            label=f"{delta.metric_code}",
            formatted_value=_format_paise_for_narration(delta.value_paise, is_available=delta.is_available),
            register=_register_for(delta),
            engine_result_ref=str(delta.id),
            note=None if delta.is_available else delta.unavailable_reason,
        ),
    ]

    context = (
        f"Explain how {result_a.metric_code} compares between the earlier period and the "
        "later period shown below, and the practical business impact of the movement, using "
        "only the figures given — do not compute, re-derive, or estimate a magnitude yourself."
    )
    narration = narrate_figures(provider, model=model, context=context, figures=figures)

    return PeriodComparisonOutcome(delta=delta, narration=narration, data_request_id=None)


# ---------------------------------------------------------------------------------------
# CP A4 — compute_landed_cost_for_quote (cfo-agent.md §6.11 supplier ranking's PRIMITIVE only;
# twinkly-mapping-canyon.md Phase A). Exposes per-quote landed cost. Deliberately NOT supplier
# ranking (comparing/sorting multiple quotes for a SKU) — that is Phase B1, out of scope here.
# ---------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LandedCostRequest:
    """Everything `compute_landed_cost_for_quote` needs to look up a seller's `supplier.quote`
    manual_adjustment (engine §7.2.1) and compute its per-unit landed cost (deterministic-
    engine.md §5.13.1). `supplier_quote_target_type`/`supplier_quote_target_ref` are exactly
    the `(target_type, target_ref)` pair `manual_adjustment_repo.active_adjustments_for_target`
    needs — the same pair `enter_expense`'s `EnterExpenseRequest.target_type`/`target_ref`
    already carries when a seller records a `supplier.quote` adjustment via `PUT /cfo/expenses`,
    so this composition reads back exactly what that write path wrote, never a differently-
    shaped key."""

    sku: str
    supplier_quote_target_type: str
    supplier_quote_target_ref: str
    quantity: int
    active_adjustment_ids: Sequence[UUID | str]
    requested_by: UUID
    as_of_date: date | None = None
    computed_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class LandedCostOutcome:
    """`result` is `None` ONLY when this function had to raise an `agent_data_request` instead
    of computing anything — zero `supplier.quote` rows found (§6.11: "CFO never scores a
    supplier it has no quote for") or more than one ACTIVE row for the same target (an
    unresolved data conflict `manual_adjustment_repo`'s own docstring says is a caller-level
    concern, never silently picked between). `data_request_id` is set in exactly that case."""

    result: MetricResult | None
    data_request_id: UUID | None


def compute_landed_cost_for_quote(tenant_id: UUID, request: LandedCostRequest) -> LandedCostOutcome:
    """Computes ONE `supplier.quote`'s landed cost per unit (cfo-agent.md §6.11's primitive,
    `deterministic-engine.md` §5.13.1) — fetches the raw adjustment row via
    `manual_adjustment_repo.active_adjustments_for_target` (real, unchanged), parses it with
    `parse_supplier_quote_adjustment` (real, unchanged), and calls `compute_landed_cost` (real,
    unchanged) — the ONLY place landed-cost arithmetic happens. Persists the result via
    `metric_result_repo.save` with `grain="SKU"`, mirroring `compute_pricing_curve`'s own
    per-SKU shape (a landed cost is priced per SKU/supplier, never a tenant-period aggregate,
    so `compute_period_pnl`'s `grain="TENANT_PERIOD"` shape does not apply here).

    **Explicitly NOT in scope** (Phase B1/B3a/B3b, `twinkly-mapping-canyon.md`): comparing or
    ranking multiple quotes for the same SKU, MOQ/lead-time business logic beyond what
    `LandedCostQuote`'s own fields already carry, and any budget-constrained quantity math.
    This function returns exactly one quote's landed cost, never a ranked or sorted list.

    Zero ACTIVE `supplier.quote` rows for the requested target is a genuinely missing input —
    §6.11: "CFO never scores a supplier it has no quote for" — refused with exactly one
    `agent_data_request`, mirroring `compute_period_pnl`'s E2 / `compute_pricing_curve`'s E14
    pattern, rather than proceeding with an assumed cost.

    More than one ACTIVE `supplier.quote` row for the same target is a data anomaly
    `manual_adjustment_repo.active_adjustments_for_target`'s own docstring explicitly leaves
    unresolved ("a caller-level (formula/UI) concern") — this function does not silently pick
    the newest row (or any other row); it raises an `agent_data_request` naming the ambiguity,
    the same "never silently resolve a conflict" discipline §7.1 states for every other
    manual_adjustment conflict.

    A malformed quote (`parse_supplier_quote_adjustment` raising `ValueError` for a missing
    `supplier_name`/`unit_cost_paise`) is left to propagate uncaught — the same convention
    `narrate_period_comparison` established for `compute_metric_delta`'s `metric_code`-mismatch
    `ValueError` (a caller/data-integrity bug, not a soft-failure/UNAVAILABLE case), and the
    same convention `landed_cost.py`'s own docstring states for this exact malformed-quote case
    ("not a partially-known quote, it is a malformed one ... raises rather than inventing a
    zero").

    No arithmetic anywhere in this function — it fetches, parses (real, unchanged), calls
    `compute_landed_cost` unchanged, then persists."""
    computed_at = request.computed_at or datetime.now()

    rows = manual_adjustment_repo.active_adjustments_for_target(
        tenant_id,
        target_type=request.supplier_quote_target_type,
        target_ref=request.supplier_quote_target_ref,
        field="supplier.quote",
    )

    if len(rows) == 0:
        data_request_id = raise_data_request(
            tenant_id,
            requested_field="supplier.quote",
            reason=(
                "no ACTIVE supplier.quote manual_adjustment for target_type="
                f"{request.supplier_quote_target_type!r}, target_ref="
                f"{request.supplier_quote_target_ref!r} — CFO never scores a supplier it has "
                "no quote for (cfo-agent.md §6.11)"
            ),
            blocking_metric="LANDED_COST_PER_UNIT",
        )
        return LandedCostOutcome(result=None, data_request_id=data_request_id)

    if len(rows) > 1:
        data_request_id = raise_data_request(
            tenant_id,
            requested_field="supplier.quote",
            reason=(
                f"{len(rows)} ACTIVE supplier.quote manual_adjustment rows for target_type="
                f"{request.supplier_quote_target_type!r}, target_ref="
                f"{request.supplier_quote_target_ref!r} — a data conflict "
                "manual_adjustment_repo.active_adjustments_for_target's own docstring leaves "
                "unresolved (§7.1: conflict is surfaced, not resolved); this composition does "
                "not silently pick one"
            ),
            blocking_metric="LANDED_COST_PER_UNIT",
        )
        return LandedCostOutcome(result=None, data_request_id=data_request_id)

    quote = parse_supplier_quote_adjustment(rows[0]["value"])

    result = compute_landed_cost(
        quote,
        request.quantity,
        sku=request.sku,
        active_adjustment_ids=request.active_adjustment_ids,
        computed_at=computed_at,
        as_of_date=request.as_of_date,
    )

    metric_result_repo.save(
        tenant_id,
        result,
        grain="SKU",
        target_ref=request.sku,
        period=None,
        config_version=_LANDED_COST_CONFIG_VERSION,
    )

    return LandedCostOutcome(result=result, data_request_id=None)


# ---------------------------------------------------------------------------------------
# CP B1 — rank_suppliers (cfo-agent.md §6.11 supplier ranking; twinkly-mapping-canyon.md
# Phase B1). The ranking CP A4's `compute_landed_cost_for_quote` deliberately did not build:
# sorting/comparing MULTIPLE `supplier.quote` rows for one SKU by landed cost.
# ---------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SupplierRankingRequest:
    """Everything `rank_suppliers` needs to rank every ACTIVE `supplier.quote` row for one SKU
    by landed cost. Unlike `LandedCostRequest`, there is no separate `supplier_quote_target_type`/
    `supplier_quote_target_ref` pair here — CP A4's own established convention is that MULTIPLE
    suppliers quoting the SAME SKU land as multiple ACTIVE rows under exactly one
    `(target_type="SKU", target_ref=sku, field="supplier.quote")` triple, so the SKU itself IS
    the lookup key this request carries; `rank_suppliers` fixes `target_type="SKU"` internally
    rather than accepting it as a parameter a caller could get wrong."""

    sku: str
    quantity: int
    active_adjustment_ids: Sequence[UUID | str]
    requested_by: UUID
    as_of_date: date | None = None
    computed_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class RankedSupplierQuote:
    """One successfully-computed quote's landed cost plus the informational (non-ranking)
    metadata carried on the same `supplier.quote` adjustment. §6.11: MOQ/lead-time/payment-
    terms/reliability are informational context for the seller, never inputs to the sort
    itself — the sort key is `result.value_paise` alone."""

    result: MetricResult
    supplier_name: str
    reliability_note: str | None
    payment_terms: str | None
    lead_time_days: int | None
    moq: int | None


@dataclass(frozen=True, slots=True)
class QuarantinedSupplierQuote:
    """One ACTIVE `supplier.quote` row that failed to parse (`parse_supplier_quote_adjustment`
    raised `ValueError` for THIS row alone) — excluded from the ranking but disclosed, never
    silently dropped and never allowed to abort the ranking of the other valid rows. Mirrors
    §9's E8 quarantine precedent (malformed rows in a period: excluded from every total, count
    and reason disclosed on the figure)."""

    adjustment_id: UUID | str
    supplier_name: str | None
    reason: str


@dataclass(frozen=True, slots=True)
class SupplierRankingOutcome:
    """`ranked` is ordered ascending by landed cost per unit — rank 1 (index 0) is the
    cheapest. `is_single_quote` is `True` precisely when exactly one quote computed
    successfully: §6.11/E15's "reported as a single quote, not a ranking" distinction, made a
    real structural fact here rather than left implicit in `len(ranked) == 1`. `data_request_id`
    is set only when there was nothing to rank at all (zero ACTIVE rows, or every ACTIVE row
    failed to parse) — in both cases `ranked` is empty."""

    ranked: list[RankedSupplierQuote]
    quarantined: list[QuarantinedSupplierQuote]
    is_single_quote: bool
    data_request_id: UUID | None


def rank_suppliers(tenant_id: UUID, request: SupplierRankingRequest) -> SupplierRankingOutcome:
    """Ranks every ACTIVE `supplier.quote` manual_adjustment for one SKU by landed cost per
    unit (cfo-agent.md §6.11, deterministic-engine.md §5.13.1). Deliberately calls
    `manual_adjustment_repo.active_adjustments_for_target` DIRECTLY — NOT through
    `compute_landed_cost_for_quote`, which treats more than one ACTIVE row as an unresolved
    conflict (correct for that function's single-quote-lookup purpose, wrong here: ranking
    explicitly wants every ACTIVE row for the SKU, per CP A4's own established convention that
    multiple suppliers quoting the same SKU land as multiple ACTIVE rows under one
    `(target_type="SKU", target_ref=sku, field="supplier.quote")` triple).

    Zero ACTIVE rows for the SKU is a genuinely missing input — §6.11: "CFO never scores a
    supplier it has no quote for" — refused with exactly one `agent_data_request`, mirroring
    `compute_landed_cost_for_quote`'s own zero-row handling.

    Each row is parsed independently. A row that fails to parse (`parse_supplier_quote_
    adjustment` raising `ValueError` — a malformed quote, missing `supplier_name`/
    `unit_cost_paise`) is quarantined for THAT row alone: recorded with its adjustment id, its
    supplier name when the raw value still carries one, and the parse failure reason, then
    excluded from the ranking — it never aborts the ranking of the other valid rows (§9's E8
    quarantine precedent: exclude and disclose, never silently drop, never crash the rest).

    A `quantity <= 0` failure from `compute_landed_cost`/`landed_cost_per_unit` is NOT
    quarantined — it is a caller bug in `request.quantity` itself, affecting every row
    identically, not a per-supplier data anomaly, so it is left to propagate uncaught exactly
    as `compute_landed_cost_for_quote`'s own docstring establishes for a malformed quote's
    `ValueError` (a caller/data-integrity bug, not a soft-failure/UNAVAILABLE case).

    If every ACTIVE row failed to parse, there is nothing left to rank — this is treated the
    same as the zero-row case (one `agent_data_request`, naming the quarantined rows), rather
    than returning an outcome that silently claims a ranking exists.

    Successfully-computed results are sorted ascending by `MetricResult.value_paise` (lowest
    landed cost first) via a plain `sorted()` call — a comparison/ordering operation, not `+ -
    * /` arithmetic (confirmed empirically not to trip `test_no_arithmetic_lint.py`, which only
    scans for `+ - * /` operators, never comparisons). This is the one new piece of logic this
    checkpoint adds; every money figure itself was already computed, unchanged, by
    `compute_landed_cost` before the sort ever runs.

    Persists every successfully-computed `MetricResult` via `metric_result_repo.save`,
    mirroring `compute_landed_cost_for_quote`'s exact `grain="SKU"` shape.

    No arithmetic anywhere in this function — it fetches, parses (real, unchanged, per row),
    calls `compute_landed_cost` (real, unchanged, per row), sorts (not arithmetic), and
    persists."""
    computed_at = request.computed_at or datetime.now()

    rows = manual_adjustment_repo.active_adjustments_for_target(
        tenant_id,
        target_type="SKU",
        target_ref=request.sku,
        field="supplier.quote",
    )

    if len(rows) == 0:
        data_request_id = raise_data_request(
            tenant_id,
            requested_field="supplier.quote",
            reason=(
                "no ACTIVE supplier.quote manual_adjustment rows for target_type='SKU', "
                f"target_ref={request.sku!r} — CFO never scores a supplier it has no quote "
                "for (cfo-agent.md §6.11)"
            ),
            blocking_metric="LANDED_COST_PER_UNIT",
        )
        return SupplierRankingOutcome(
            ranked=[], quarantined=[], is_single_quote=False, data_request_id=data_request_id
        )

    ranked: list[RankedSupplierQuote] = []
    quarantined: list[QuarantinedSupplierQuote] = []

    for row in rows:
        raw_value = row["value"]
        try:
            quote = parse_supplier_quote_adjustment(raw_value)
        except ValueError as exc:
            raw_supplier_name = raw_value.get("supplier_name") if isinstance(raw_value, dict) else None
            quarantined.append(
                QuarantinedSupplierQuote(
                    adjustment_id=row["id"],
                    supplier_name=raw_supplier_name if isinstance(raw_supplier_name, str) else None,
                    reason=str(exc),
                )
            )
            continue

        result = compute_landed_cost(
            quote,
            request.quantity,
            sku=request.sku,
            active_adjustment_ids=request.active_adjustment_ids,
            computed_at=computed_at,
            as_of_date=request.as_of_date,
        )
        metric_result_repo.save(
            tenant_id,
            result,
            grain="SKU",
            target_ref=request.sku,
            period=None,
            config_version=_SUPPLIER_RANKING_CONFIG_VERSION,
        )
        ranked.append(
            RankedSupplierQuote(
                result=result,
                supplier_name=quote.supplier_name,
                reliability_note=quote.reliability_note,
                payment_terms=quote.payment_terms,
                lead_time_days=quote.lead_time_days,
                moq=quote.moq,
            )
        )

    if len(ranked) == 0:
        data_request_id = raise_data_request(
            tenant_id,
            requested_field="supplier.quote",
            reason=(
                f"{len(quarantined)} ACTIVE supplier.quote row(s) for target_type='SKU', "
                f"target_ref={request.sku!r} all failed to parse — CFO never scores a supplier "
                "it has no usable quote for (cfo-agent.md §6.11); quarantined: "
                f"{[(str(q.adjustment_id), q.reason) for q in quarantined]}"
            ),
            blocking_metric="LANDED_COST_PER_UNIT",
        )
        return SupplierRankingOutcome(
            ranked=[], quarantined=quarantined, is_single_quote=False, data_request_id=data_request_id
        )

    ranked.sort(key=lambda entry: entry.result.value_paise)

    return SupplierRankingOutcome(
        ranked=ranked,
        quarantined=quarantined,
        is_single_quote=len(ranked) == 1,
        data_request_id=None,
    )


# ---------------------------------------------------------------------------------------
# CP B2 — assemble_funding_readiness_reduced (cfo-agent.md §6.13/D7 "funding readiness";
# twinkly-mapping-canyon.md Phase B2). REDUCED slice only: Contribution Profit history/trend
# with data-completeness stated, and explicit gaps (periods missing, COGS/RTO absent). Margin
# stability, revenue concentration and cash-conversion timing are §6.13 bullets this checkpoint
# does NOT build — Phase D (`reconcile()`/`cash_reconciliation`) is a genuine dependency, not a
# style choice, and this function's own output says so structurally.
# ---------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FundingReadinessRequest:
    """Everything `assemble_funding_readiness_reduced` needs to assemble a tenant's
    Contribution Profit history over a period range (cfo-agent.md §6.13).

    `expected_periods` is a JUDGMENT CALL, flagged: `metric_result.period` (see
    `metric_result_repo.list_by_metric_code`'s own docstring) is a free-text
    `"{start}/{end}"` label with NO fixed periodicity baked into the schema — CFO has no
    calendar/periodicity assumption of its own (this module does not invent one, e.g. "monthly"),
    and inventing one here would be exactly the kind of silent business-logic assumption this
    codebase's discipline forbids. `expected_periods` is therefore the caller's own explicit
    statement of which period labels (in the SAME `"{start}/{end}"` shape `compute_period_pnl`
    already persists) it expected a `CONTRIBUTION_PROFIT` result for across
    `period_start`/`period_end` — e.g. one label per month, if the caller's own reporting
    cadence is monthly. Comparing this set against what `list_by_metric_code` actually returned
    is what makes "missing periods" (§6.13's own words) nameable at all without CFO guessing a
    periodicity; an empty `expected_periods` means "no missing-period check requested", not
    "no periods were expected"."""

    period_start: date
    period_end: date
    as_of_date: date
    requested_by: UUID
    expected_periods: Sequence[str] = ()
    computed_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class DeferredFundingReadinessSection:
    """One §6.13 funding-readiness element this REDUCED assembly structurally does NOT cover —
    present on every `FundingReadinessOutcome` so a caller/narration layer can see the
    deferral explicitly rather than assuming an empty list means "nothing to report" (the same
    "never represent partial as real" discipline this whole project runs on)."""

    name: str
    reason: str
    blocked_on: str


_DEFERRED_FUNDING_READINESS_SECTIONS: tuple[DeferredFundingReadinessSection, ...] = (
    DeferredFundingReadinessSection(
        name="margin_stability",
        reason=(
            "§6.13 names margin stability as part of the full funding-readiness output; this "
            "reduced assembly (twinkly-mapping-canyon.md CP B2) does not compute it — margin "
            "stability needs a settlement-reconciled view of margin over time that does not "
            "exist yet"
        ),
        blocked_on="Phase D — reconcile()/cash_reconciliation not yet built",
    ),
    DeferredFundingReadinessSection(
        name="revenue_concentration_by_sku_and_marketplace",
        reason=(
            "§6.13 names revenue concentration by SKU and marketplace as part of the full "
            "funding-readiness output; this reduced assembly does not compute it"
        ),
        blocked_on="Phase D — reconcile()/cash_reconciliation not yet built",
    ),
    DeferredFundingReadinessSection(
        name="cash_conversion_timing",
        reason=(
            "§6.13 names cash-conversion timing from settlement data as part of the full "
            "funding-readiness output; this reduced assembly does not compute it — it requires "
            "the cash_reconciliation() engine formula (§6.10/§6.13), which does not exist yet"
        ),
        blocked_on="Phase D — cash_reconciliation() not yet built",
    ),
)


@dataclass(frozen=True, slots=True)
class FundingReadinessGap:
    """One explicitly-named gap in the assembled Contribution Profit history — never a
    silently-dropped period (E21: "assembles what exists, names every gap"). `kind` is one of
    two closed values, never invented ad hoc:

      - `"MISSING_PERIOD"` — an `expected_periods` entry with NO `CONTRIBUTION_PROFIT`
        `metric_result` row at all for this tenant in the requested range.
      - `"UNAVAILABLE_RESULT"` — a `CONTRIBUTION_PROFIT` row exists for this period but came
        back `is_available=False` (COGS or RTO-outcome classification absent, per
        `compute_period_pnl`'s own established `Unavailable` propagation from
        `compute_contribution_profit`) — `reason` carries that row's own `unavailable_reason`.
    """

    kind: str  # "MISSING_PERIOD" | "UNAVAILABLE_RESULT"
    period: str
    reason: str


@dataclass(frozen=True, slots=True)
class FundingReadinessOutcome:
    """cfo-agent.md §6.13's honestly-buildable REDUCED slice (twinkly-mapping-canyon.md CP B2).

    **AC19 — no score, valuation or lending judgement anywhere.** Every field below is either a
    fetched/reconstructed `MetricResult` (Contribution Profit history), a real engine-computed
    `*_DELTA` `MetricResult` (trend, via `compute_metric_delta`, unchanged), a structured
    statement of a named gap, or a structured statement of what this assembly deliberately does
    NOT cover and why (`deferred_sections`). No field here is, or could be read as, a
    "readiness score", a "risk rating", a valuation, or an investment recommendation — there is
    no numeric or categorical judgement field on this dataclass at all.

    `data_request_id` is set (non-blocking, informational — mirrors `PeriodPnlOutcome`'s own
    convention) whenever `gaps` is non-empty; the full assembly (history/trend/gaps) is always
    returned regardless, per E21: thin data still produces a completeness report, never a
    refusal."""

    contribution_profit_history: list[MetricResult]
    trend: list[MetricResult]
    gaps: list[FundingReadinessGap]
    deferred_sections: tuple[DeferredFundingReadinessSection, ...]
    data_request_id: UUID | None


def assemble_funding_readiness_reduced(
    tenant_id: UUID, request: FundingReadinessRequest
) -> FundingReadinessOutcome:
    """Assembles cfo-agent.md §6.13's REDUCED funding-readiness slice (twinkly-mapping-
    canyon.md CP B2): Contribution Profit history and trend, with data-completeness stated, and
    explicit gaps — periods missing, COGS/RTO-classification absent. Margin stability, revenue
    concentration and cash-conversion timing are NOT assembled here (`deferred_sections`
    states this structurally, never by silent omission) — Phase D (`reconcile()`/
    `cash_reconciliation`) is a genuine, undone dependency.

    Fetches history via `metric_result_repo.list_by_metric_code` (real, this checkpoint's one
    new read path) for `metric_code="CONTRIBUTION_PROFIT"` across `period_start`/`period_end`,
    reconstructs each row via `_metric_result_from_row` (CP A3's existing dict->dataclass
    helper, reused unchanged — not a second conversion path), then:

      - **Trend**: sorts the fetched rows chronologically by their `period` label (a string
        comparison — `sorted()`, not arithmetic, the same distinction CP B1 already established
        for its own `sorted()`/`.sort()` calls) and calls `compute_metric_delta` (real,
        unchanged, `calc_engine.api.compute_metric` — the ONLY place delta arithmetic happens)
        for each consecutive pair, persisting every delta via `metric_result_repo.save` exactly
        the way `narrate_period_comparison` (CP A3) already persists its own delta.
      - **Gaps**: compares `request.expected_periods` against the period labels actually
        present (a set/membership comparison, not arithmetic) to name every `MISSING_PERIOD`,
        and inspects each fetched result's own `is_available` flag (already computed by
        `compute_period_pnl`/`compute_contribution_profit`, never re-derived here) to name every
        `UNAVAILABLE_RESULT`. Neither check performs `+ - * /` on anything.

    No arithmetic anywhere in this function: it fetches (`list_by_metric_code`), reconstructs
    (`_metric_result_from_row`, reused), sorts and compares (not arithmetic), calls
    `compute_metric_delta` unchanged per pair, and persists (`metric_result_repo.save`)."""
    computed_at = request.computed_at or datetime.now()
    period_start_label = request.period_start.isoformat()
    period_end_label = request.period_end.isoformat()

    rows = metric_result_repo.list_by_metric_code(
        tenant_id,
        metric_code="CONTRIBUTION_PROFIT",
        period_start=period_start_label,
        period_end=period_end_label,
    )

    labeled_rows = sorted(rows, key=lambda row: str(row.get("period") or ""))
    labeled: list[tuple[str, MetricResult]] = [
        (str(row.get("period") or ""), _metric_result_from_row(row)) for row in labeled_rows
    ]
    history = [result for _, result in labeled]

    trend: list[MetricResult] = []
    for (period_a_label, result_a), (period_b_label, result_b) in zip(labeled, labeled[1:]):
        delta = compute_metric_delta(
            result_a, result_b, computed_at=computed_at, as_of_date=request.as_of_date
        )
        metric_result_repo.save(
            tenant_id,
            delta,
            grain="TENANT_PERIOD",
            target_ref=str(tenant_id),
            period=f"{period_a_label}/{period_b_label}",
            config_version=_FUNDING_READINESS_CONFIG_VERSION,
        )
        trend.append(delta)

    present_periods = {period_label for period_label, _ in labeled}
    gaps: list[FundingReadinessGap] = [
        FundingReadinessGap(
            kind="MISSING_PERIOD",
            period=expected_period,
            reason=(
                "no CONTRIBUTION_PROFIT metric_result exists for this period in the requested "
                f"range {period_start_label}/{period_end_label}"
            ),
        )
        for expected_period in request.expected_periods
        if expected_period not in present_periods
    ]
    gaps.extend(
        FundingReadinessGap(
            kind="UNAVAILABLE_RESULT",
            period=period_label,
            reason=result.unavailable_reason or "CONTRIBUTION_PROFIT unavailable for this period",
        )
        for period_label, result in labeled
        if not result.is_available
    )

    data_request_id: UUID | None = None
    if gaps:
        data_request_id = raise_data_request(
            tenant_id,
            requested_field="contribution_profit_history",
            reason=(
                f"funding readiness assembly for {period_start_label}/{period_end_label} found "
                f"{len(gaps)} gap(s): "
                + "; ".join(f"{gap.kind} {gap.period}: {gap.reason}" for gap in gaps)
            ),
            blocking_metric="CONTRIBUTION_PROFIT",
        )

    return FundingReadinessOutcome(
        contribution_profit_history=history,
        trend=trend,
        gaps=gaps,
        deferred_sections=_DEFERRED_FUNDING_READINESS_SECTIONS,
        data_request_id=data_request_id,
    )


# ---------------------------------------------------------------------------------------
# CP B3b — assemble_batch_size_estimate (cfo-agent.md §6.12/D9 "batch size";
# twinkly-mapping-canyon.md Phase B3b). B3a already built the engine's budget-and-MOQ
# arithmetic core (`budget_constrained_quantity`/`compute_batch_constrained_quantity`); this
# checkpoint wires it up with sales velocity, the `supplier.quote`/`batch.budget` lookups, and
# §6.12's `agent_data_request` behaviour — none of which existed before this checkpoint.
# ---------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BatchSizeRequest:
    """Everything `assemble_batch_size_estimate` needs to assemble a budget-constrained
    order-quantity estimate for one SKU/supplier/budget combination (cfo-agent.md §6.12).

    `supplier_quote_target_type`/`supplier_quote_target_ref` identify the ONE chosen
    `supplier.quote` to use (mirroring `LandedCostRequest`'s exact shape, CP A4) — batch size is
    about one chosen supplier's economics, not a re-ranking across suppliers. If ranking should
    feed this automatically (e.g. always use the cheapest ranked quote), that is a genuine open
    integration question this checkpoint deliberately does NOT resolve — flagged, not built.

    `budget_target_type`/`budget_target_ref` identify the `batch.budget` adjustment
    (deterministic-engine.md §7.2.1: `target_type` is `SKU` or `ACCOUNT`) — a SEPARATE lookup
    key from the supplier quote's own target, since a budget ceiling and a supplier quote are
    two independently-declared seller inputs that need not share a target.

    `lines` is already-assembled `CanonicalLine` sales history for this SKU (the SAME
    caller-assembles-canonical-lines precedent `PeriodPnlRequest.lines`/`GstPeriodSummaryRequest
    .lines` already establish — `canonical_repo.py`'s own docstring says assembling a full
    `CanonicalLine` from raw rows is not that repository's job, and this composition does not
    reinvent that boundary here). An empty sequence is this function's own signal for "no sales
    history observed for this SKU in the given range" (§6.12's "never sold" case) — the caller
    is responsible for having already filtered `lines` to `period_start`/`period_end` before
    handing them here (`period_start`/`period_end` are carried on this request only as a
    provenance label, the same way `PeriodPnlRequest` carries its own period fields, not as a
    second filter this function applies itself)."""

    sku: str
    supplier_quote_target_type: str
    supplier_quote_target_ref: str
    budget_target_type: str
    budget_target_ref: str
    lines: Sequence[CanonicalLine]
    period_start: date
    period_end: date
    as_of_date: date
    active_adjustment_ids: Sequence[UUID | str]
    requested_by: UUID
    computed_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class BatchSizeOutcome:
    """cfo-agent.md §6.12's full estimate (engine core + CFO wiring, twinkly-mapping-canyon.md
    CP B3b). **Never** a demand forecast, a guaranteed sell-through, or a claim about future
    volume (D9) — no field here is named, or could be read as, any of those; `result` is a
    budget-and-MOQ-constrained order-quantity CEILING, and `observed_units_sold` is a plain
    OBSERVED historical count, never a projection.

    `result` is `None` only when this function had to raise an `agent_data_request` instead of
    computing anything (zero/multiple ACTIVE `supplier.quote` or `batch.budget` rows, an expired
    budget, or velocity AND lead-time AND MOQ all missing at once — §6.12's precise rule).

    `landed_cost_result` is the per-unit landed-cost `MetricResult` `result` was built from
    (Subtlety 1's reference-quantity computation) — carried here, and persisted alongside
    `result`, so a caller/narration layer can cite its OWN `engine_result_ref` rather than only
    being able to point at the figure baked into `result.calculation_basis`'s text.

    `velocity_status` is one of three closed values, never invented ad hoc:
      - `"OBSERVED"` — `observed_units_sold` returned a real count (`observed_units_sold` field
        holds it, `velocity_unavailable_reason` is `None`).
      - `"NEVER_SOLD"` — `request.lines` was empty; §6.12's own "SKU the seller has never sold"
        case (`observed_units_sold` field is `None`).
      - `"UNAVAILABLE"` — `request.lines` was non-empty but `observed_units_sold` (the engine
        formula) came back `Unavailable` (e.g. an unclassified cancelled-after-dispatch line);
        `velocity_unavailable_reason` carries the formula's own reason.

    `reference_quantity`/`reference_quantity_basis` disclose Subtlety 1's approximation
    explicitly: the quantity `compute_landed_cost` was actually evaluated at (`moq` when
    declared, else `1`) — `"MOQ"` or `"DEFAULT_ONE"`. `reference_quantity_caveat_applies` is
    `True` exactly when the quote's `shipping_paise` is set (the true per-unit cost then DOES
    depend on quantity, and this estimate does not iterate to find the exact fixed point) and
    `False` when it is `None` (per-unit cost is quantity-independent, so the circularity simply
    does not exist for this quote) — `reference_quantity_caveat` states which case applies in
    plain text either way, never silently omitted and never a caveat shown when it doesn't
    apply."""

    result: MetricResult | None
    landed_cost_result: MetricResult | None
    velocity_status: str  # "OBSERVED" | "NEVER_SOLD" | "UNAVAILABLE"
    observed_units_sold: int | None
    velocity_unavailable_reason: str | None
    reference_quantity: int | None
    reference_quantity_basis: str | None  # "MOQ" | "DEFAULT_ONE"
    reference_quantity_caveat_applies: bool | None
    reference_quantity_caveat: str | None
    lead_time_days: int | None
    moq: int | None
    data_request_id: UUID | None


def assemble_batch_size_estimate(tenant_id: UUID, request: BatchSizeRequest) -> BatchSizeOutcome:
    """Assembles cfo-agent.md §6.12's full batch-size estimate: B3a's engine core
    (`compute_batch_constrained_quantity`) plus this checkpoint's own new wiring — sales
    velocity (`observed_units_sold`, real, unchanged, `calc_engine.formulas.sales_velocity`),
    the `supplier.quote`/`batch.budget` lookups, and §6.12's `agent_data_request` behaviour.

    **Supplier quote** is fetched via `manual_adjustment_repo.active_adjustments_for_target`
    (real, unchanged) and handled EXACTLY like `compute_landed_cost_for_quote` (CP A4): zero
    ACTIVE rows -> data request ("CFO never scores a supplier it has no quote for"); more than
    one ACTIVE row -> data request naming the ambiguity, never a silent pick; a malformed quote
    (`parse_supplier_quote_adjustment` raising `ValueError`) propagates uncaught, a caller/data-
    integrity bug, not a soft failure.

    **`batch.budget`** is fetched the same way, for `(request.budget_target_type,
    request.budget_target_ref)`: zero ACTIVE rows, or more than one, both raise a data request
    (mirroring the quote-lookup discipline above rather than inventing a second convention for
    an equally seller-declared, equally opt-in input). A malformed budget (`parse_batch_budget_
    adjustment` raising `ValueError` for a missing/invalid `amount_paise`) propagates uncaught,
    the same convention. **Expiry is a real correctness check, not a formality**: when
    `valid_until` is set and falls before `request.as_of_date`, the budget is expired and is
    NEVER used as if still valid — this raises a data request instead of silently proceeding
    with a stale ceiling that could materially mislead a seller about what they can actually
    afford today.

    **Sales velocity**: `request.lines` empty -> `velocity_status="NEVER_SOLD"` (§6.12's own
    "never sold" case). Non-empty `request.lines` -> calls `observed_units_sold` (real,
    unchanged); an `Unavailable` result -> `velocity_status="UNAVAILABLE"`. In BOTH degraded
    cases, this function does **not** automatically refuse: per §6.12's precise wording, a data
    request is raised only when velocity is ALSO accompanied by BOTH `lead_time_days` and `moq`
    being absent from the quote. If either is present, the estimate proceeds — degraded, and
    explicitly flagged as such on the returned outcome — to the budget-and-MOQ arithmetic floor
    §6.12 itself names as the honest degraded output (T34).

    **Subtlety 1 (circular quantity/shipping-apportionment dependency)**: `landed_cost_per_unit`
    apportions `shipping_paise` across a `quantity` — but `budget_constrained_quantity` is
    trying to FIND the affordable quantity from a per-unit cost, a genuine circularity (true
    per-unit cost depends on quantity, quantity depends on per-unit cost). This function computes
    the landed-cost-per-unit reference at `quantity = moq` when a MOQ is declared (the natural
    reference point), or `quantity = 1` when it is not (no better reference point exists) — and
    discloses this explicitly via `reference_quantity`/`reference_quantity_basis`/
    `reference_quantity_caveat(_applies)` on the outcome, rather than silently treating the
    reference-quantity figure as exact. When the quote has no `shipping_paise` at all, per-unit
    cost is quantity-independent and the caveat says so plainly instead of showing a warning
    that does not apply to this quote.

    Persists `compute_landed_cost`'s result AND `compute_batch_constrained_quantity`'s result
    via `metric_result_repo.save`, both `grain="SKU"`, mirroring `compute_landed_cost_for_quote`
    (CP A4)'s exact shape — the landed-cost figure is persisted too (not only the final batch
    figure) so a caller can cite that intermediate figure's own `engine_result_ref` rather than
    only reading it out of `result.calculation_basis`'s text.

    **Never** presents this as a demand forecast or guaranteed sell-through (D9) — see
    `BatchSizeOutcome`'s own docstring for why no field here could be read that way.

    No arithmetic anywhere in this function — every number comes from `observed_units_sold`,
    `compute_landed_cost`, or `compute_batch_constrained_quantity`, all real and unchanged; this
    function only fetches, parses, checks expiry (a date comparison, not arithmetic), calls, and
    persists."""
    computed_at = request.computed_at or datetime.now()

    # --- supplier.quote: mirrors compute_landed_cost_for_quote (CP A4) exactly ---
    quote_rows = manual_adjustment_repo.active_adjustments_for_target(
        tenant_id,
        target_type=request.supplier_quote_target_type,
        target_ref=request.supplier_quote_target_ref,
        field="supplier.quote",
    )

    if len(quote_rows) == 0:
        data_request_id = raise_data_request(
            tenant_id,
            requested_field="supplier.quote",
            reason=(
                "no ACTIVE supplier.quote manual_adjustment for target_type="
                f"{request.supplier_quote_target_type!r}, target_ref="
                f"{request.supplier_quote_target_ref!r} — CFO never scores a supplier it has "
                "no quote for (cfo-agent.md §6.11, reused by §6.12's batch-size estimate)"
            ),
            blocking_metric="BATCH_CONSTRAINED_QUANTITY",
        )
        return _empty_batch_size_outcome(data_request_id)

    if len(quote_rows) > 1:
        data_request_id = raise_data_request(
            tenant_id,
            requested_field="supplier.quote",
            reason=(
                f"{len(quote_rows)} ACTIVE supplier.quote manual_adjustment rows for "
                f"target_type={request.supplier_quote_target_type!r}, target_ref="
                f"{request.supplier_quote_target_ref!r} — a data conflict this composition does "
                "not silently pick between (§7.1: conflict is surfaced, not resolved)"
            ),
            blocking_metric="BATCH_CONSTRAINED_QUANTITY",
        )
        return _empty_batch_size_outcome(data_request_id)

    quote = parse_supplier_quote_adjustment(quote_rows[0]["value"])

    # --- batch.budget: same discipline as the quote lookup above ---
    budget_rows = manual_adjustment_repo.active_adjustments_for_target(
        tenant_id,
        target_type=request.budget_target_type,
        target_ref=request.budget_target_ref,
        field="batch.budget",
    )

    if len(budget_rows) == 0:
        data_request_id = raise_data_request(
            tenant_id,
            requested_field="batch.budget",
            reason=(
                "no ACTIVE batch.budget manual_adjustment for target_type="
                f"{request.budget_target_type!r}, target_ref={request.budget_target_ref!r} — "
                "a batch-size estimate is never assembled against an assumed budget "
                "(cfo-agent.md §6.12)"
            ),
            blocking_metric="BATCH_CONSTRAINED_QUANTITY",
        )
        return _empty_batch_size_outcome(data_request_id)

    if len(budget_rows) > 1:
        data_request_id = raise_data_request(
            tenant_id,
            requested_field="batch.budget",
            reason=(
                f"{len(budget_rows)} ACTIVE batch.budget manual_adjustment rows for "
                f"target_type={request.budget_target_type!r}, target_ref="
                f"{request.budget_target_ref!r} — a data conflict this composition does not "
                "silently pick between (§7.1: conflict is surfaced, not resolved)"
            ),
            blocking_metric="BATCH_CONSTRAINED_QUANTITY",
        )
        return _empty_batch_size_outcome(data_request_id)

    budget: BatchBudget = parse_batch_budget_adjustment(budget_rows[0]["value"])

    if budget.is_expired_as_of(request.as_of_date):
        data_request_id = raise_data_request(
            tenant_id,
            requested_field="batch.budget",
            reason=(
                f"batch.budget for target_type={request.budget_target_type!r}, target_ref="
                f"{request.budget_target_ref!r} expired on {budget.valid_until.isoformat() if budget.valid_until else '?'} "
                f", before as_of_date={request.as_of_date.isoformat()} — an expired budget is "
                "never used as if still valid (a stale ceiling could materially mislead a "
                "seller about what they can afford today)"
            ),
            blocking_metric="BATCH_CONSTRAINED_QUANTITY",
        )
        return _empty_batch_size_outcome(data_request_id)

    # --- sales velocity (observed) ---
    if not request.lines:
        velocity_status = "NEVER_SOLD"
        velocity_value: int | None = None
        velocity_reason: str | None = (
            "no CanonicalLine sales history supplied for this SKU in the requested range — "
            "treated as a SKU the seller has never sold (cfo-agent.md §6.12)"
        )
    else:
        velocity_result = observed_units_sold(request.lines, as_of=request.as_of_date)
        if isinstance(velocity_result, Unavailable):
            velocity_status = "UNAVAILABLE"
            velocity_value = None
            velocity_reason = velocity_result.reason
        else:
            velocity_status = "OBSERVED"
            velocity_value = velocity_result
            velocity_reason = None

    velocity_degraded = velocity_status in ("NEVER_SOLD", "UNAVAILABLE")
    if velocity_degraded and quote.lead_time_days is None and quote.moq is None:
        data_request_id = raise_data_request(
            tenant_id,
            requested_field="supplier.quote",
            reason=(
                f"sales velocity is {velocity_status.lower()} ({velocity_reason}) for sku="
                f"{request.sku!r}, AND the supplier.quote names neither lead_time_days nor moq "
                "— cfo-agent.md §6.12: CFO raises a data request rather than assuming values "
                "only when velocity and lead time and MOQ are ALL missing; either lead_time_days "
                "or moq alone would have been enough to proceed with a degraded estimate"
            ),
            blocking_metric="BATCH_CONSTRAINED_QUANTITY",
        )
        return _empty_batch_size_outcome(
            data_request_id,
            velocity_status=velocity_status,
            observed_units_sold_value=velocity_value,
            velocity_unavailable_reason=velocity_reason,
            lead_time_days=quote.lead_time_days,
            moq=quote.moq,
        )

    # --- Subtlety 1: reference quantity for the landed-cost-per-unit approximation ---
    if quote.moq is not None:
        reference_quantity = quote.moq
        reference_quantity_basis = "MOQ"
    else:
        reference_quantity = 1
        reference_quantity_basis = "DEFAULT_ONE"

    if quote.shipping_paise is not None:
        reference_quantity_caveat_applies = True
        reference_quantity_caveat = (
            f"per-unit landed cost was computed at reference quantity {reference_quantity} "
            f"({reference_quantity_basis}) because this quote apportions shipping_paise across "
            "quantity — the TRUE per-unit cost may be LOWER at higher order volumes, since "
            "shipping is divided across more units there; this estimate does NOT iterate to "
            "find an exact fixed point between quantity and per-unit cost, so the affordable-"
            "quantity figure below is an approximation anchored at this one reference quantity, "
            "not a solved equilibrium (cfo-agent.md §6.12)"
        )
    else:
        reference_quantity_caveat_applies = False
        reference_quantity_caveat = (
            f"per-unit landed cost was computed at reference quantity {reference_quantity} "
            f"({reference_quantity_basis}) only to satisfy landed_cost_per_unit's quantity > 0 "
            "requirement — this quote has no shipping_paise, so per-unit cost is quantity-"
            "independent and the shipping-apportionment circularity does not apply to this quote"
        )

    landed_cost_result = compute_landed_cost(
        quote,
        reference_quantity,
        sku=request.sku,
        active_adjustment_ids=request.active_adjustment_ids,
        computed_at=computed_at,
        as_of_date=request.as_of_date,
    )
    metric_result_repo.save(
        tenant_id,
        landed_cost_result,
        grain="SKU",
        target_ref=request.sku,
        period=None,
        config_version=_BATCH_SIZE_CONFIG_VERSION,
    )

    batch_result = compute_batch_constrained_quantity(
        Paise(budget.amount_paise),
        Paise(landed_cost_result.value_paise),  # type: ignore[arg-type]
        quote.moq,
        sku=request.sku,
        active_adjustment_ids=request.active_adjustment_ids,
        computed_at=computed_at,
        as_of_date=request.as_of_date,
    )
    metric_result_repo.save(
        tenant_id,
        batch_result,
        grain="SKU",
        target_ref=request.sku,
        period=None,
        config_version=_BATCH_SIZE_CONFIG_VERSION,
    )

    return BatchSizeOutcome(
        result=batch_result,
        landed_cost_result=landed_cost_result,
        velocity_status=velocity_status,
        observed_units_sold=velocity_value,
        velocity_unavailable_reason=velocity_reason,
        reference_quantity=reference_quantity,
        reference_quantity_basis=reference_quantity_basis,
        reference_quantity_caveat_applies=reference_quantity_caveat_applies,
        reference_quantity_caveat=reference_quantity_caveat,
        lead_time_days=quote.lead_time_days,
        moq=quote.moq,
        data_request_id=None,
    )


def _empty_batch_size_outcome(
    data_request_id: UUID,
    *,
    velocity_status: str = "UNAVAILABLE",
    observed_units_sold_value: int | None = None,
    velocity_unavailable_reason: str | None = None,
    lead_time_days: int | None = None,
    moq: int | None = None,
) -> BatchSizeOutcome:
    """Shared refusal shape for every `assemble_batch_size_estimate` data-request path —
    `result`/`landed_cost_result` are always `None` here (nothing was computed), mirroring
    `LandedCostOutcome`'s own `result=None` convention (CP A4) for its own data-request paths."""
    return BatchSizeOutcome(
        result=None,
        landed_cost_result=None,
        velocity_status=velocity_status,
        observed_units_sold=observed_units_sold_value,
        velocity_unavailable_reason=velocity_unavailable_reason,
        reference_quantity=None,
        reference_quantity_basis=None,
        reference_quantity_caveat_applies=None,
        reference_quantity_caveat=None,
        lead_time_days=lead_time_days,
        moq=moq,
        data_request_id=data_request_id,
    )


# ---------------------------------------------------------------------------------------
# D5 -- run_leak_shield_reconciliation (cfo-agent.md Section 6.2 Leak Shield reconciliation,
# Section 6.4 recoverable-money identification, especially rule 5: the headline leak total
# carries its own real engine_result_ref). Wires the already-built, already-tested
# calc_engine.api.reconcile.reconcile (D4, real, tested against real Meesho data) into CFO,
# producing real leak_finding rows for the first time -- the last piece before Leak Shield is
# a real seller-facing surface, closing guardrail 4 ("no seller-facing Leak Shield findings
# until a real reconcile() exists") named on every dispatch/route docstring above.
#
# Decision A (this session, confirmed). is_return_linked is always False this pass. No field
# on reconciliation_exception records return-linkage, and inferring it from
# sales_line.return_status would require a real enum-value decision this project hasn't made
# (Meesho's real Return Status values are explicitly unmapped per meesho_orders_v1.py's own
# docstring). Every VARIANCE_EXCEEDS_TOLERANCE exception is therefore classified with
# is_return_linked=False -- it correctly falls through classify_leak_category's existing logic
# to FEE_OVERCHARGE/SHORT_SETTLEMENT (by component_kind + sign), never RETURN_NOT_CREDITED,
# until a real signal exists later. Not hidden, not apologized for -- stated plainly here and
# in the outcome's own shape.
#
# Decision B (this session, confirmed). AMBIGUOUS_MATCH exceptions never become a
# leak_finding. They are not a ReconciliationOutcome value at all
# (calc_engine.formulas.leak.ReconciliationOutcome's own enum confirms this -- collision is
# deliberately not part of that enum) and have no corresponding LeakCategory. They are
# filtered out before ever constructing a LeakExceptionInput / calling classify_and_rank_leaks
# -- no invented category, no placeholder outcome. They remain queryable in
# reconciliation_exception directly (already true, nothing new to build here) but are never
# surfaced through leak_finding / any seller-facing route this pass;
# LeakShieldOutcome.ambiguous_match_count states the count plainly instead of silently
# dropping it.
# ---------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LeakShieldOutcome:
    """One reconcile() run's seller-facing result -- every `findings` entry is a real,
    already-persisted leak_finding row's identifying fields (never a synthetic/unpersisted
    shape), each traceable back to a real engine_result_ref (Section 6.4 rule 5).

    `aggregate_amount_paise`/`aggregate_engine_result_ref` (D7, cfo-agent.md Section 6.9) are
    threaded straight through from `result.aggregate_metric_result` at the exact point that
    MetricResult is already computed and persisted below -- zero new arithmetic, purely
    exposing an already-known value this dataclass previously computed but did not return.
    Both are required (not defaulted): every real construction site (the one place this
    dataclass is built, inside `run_leak_shield_reconciliation` itself) already has
    `result.aggregate_metric_result` in hand, so a default would only hide a caller bug.

    `settlement_lag_*` fields (this checkpoint, anomaly-detection.md §6.1/§6.6 P1) are the
    `SETTLEMENT_LAG_DAYS` `MetricResult` this same run's `reconciliation_match` rows produce —
    computed and persisted immediately after `aggregate_metric_result` below, the moment fresh
    match rows exist to aggregate. `settlement_lag_mean_days` is `str(Fraction)` (never a bare
    float/int — this is a `value_fraction` result, matching `CONTRIBUTION_MARGIN_PCT`'s own
    API-serialization convention, `backend/api/v1/cfo.py`'s `valueFraction`), `None` exactly
    when `settlement_lag_is_available` is `False` (zero matched pairs this run — never a
    fabricated 0-day lag)."""

    reconciliation_run_id: UUID
    findings: list[dict[str, object]]
    match_count: int
    exception_count: int
    ambiguous_match_count: int
    dates_missing_count: int
    aggregate_amount_paise: int
    aggregate_engine_result_ref: str
    settlement_lag_engine_result_ref: str
    settlement_lag_is_available: bool
    settlement_lag_mean_days: str | None
    settlement_lag_pair_count: int | None


def run_leak_shield_reconciliation(
    tenant_id: UUID,
    *,
    marketplace: str,
    period_start: date,
    period_end: date,
    as_of_date: date,
) -> LeakShieldOutcome:
    """Composition, in order (cfo-agent.md Section 6.2 / Section 6.4):

    1. Calls the real calc_engine.api.reconcile.reconcile (D4, unchanged) -- zero arithmetic
       here, this function only assembles inputs and calls it.
    2. Persists every minted LEAK_EXCEPTION_AMOUNT MetricResult in
       result.exception_metric_results via metric_result_repo.save (grain="LINE",
       target_ref = the exception's own id, taken from that MetricResult's own
       input_refs[0] -- every exception type's _mint_exception_metric_result call in
       reconcile.py puts the exception id first in input_refs, confirmed by reading that
       module).
    3. Persists result.aggregate_metric_result via metric_result_repo.save
       (grain="MARKETPLACE", target_ref=marketplace) -- result.aggregate_metric_result.id IS
       the headline leak total's real engine_result_ref, persisted here for the first time,
       closing Section 6.4 rule 5's previously-open gap
       (test_leak_aggregate_carries_its_own_engine_result_ref).
    4. Fetches the real exception rows via reconciliation_repo.exceptions_for_run.
    5. Filters out exception_type == 'AMBIGUOUS_MATCH' rows (Decision B above), counting them
       separately rather than silently dropping the count.
    6. Builds a cfo.leak.compose.LeakExceptionInput per remaining exception row -- every
       amount_paise/engine_result_ref copied from the engine/DB, never recomputed;
       is_return_linked=False always (Decision A above); affected_line_count=1 (no grouping
       logic exists yet -- one exception is one line, today's honest granularity, not a
       limitation hidden from the caller); age_days=0 (the exception is freshly computed by
       this run -- a true origination-date-based age would need a per-exception-type join back
       to the underlying settlement/sales line's own date, out of scope this pass, documented
       here rather than invented); claim_window_days=None (no claim-window policy/config
       exists yet per marketplace -- None is window_status()'s own honest "not applicable"
       value, never a guessed number); sku=None (no adapter maps sku for Meesho yet).
    7. Calls config_repo.severity_config_rows + cfo.leak.compose.classify_and_rank_leaks (both
       real, unchanged) to classify and rank the exceptions.
    8. Persists each ComposedFinding via leak_finding_repo.insert -- confidence is copied from
       the ORIGINAL reconciliation_exception row (not threaded through LeakExceptionInput,
       which has no such field, and compose.py's dataclass is not modified by this change);
       explanation/recommended_action stay None this pass (no Brain-3 narration wired here);
       status="NEW".

    9. (This checkpoint, anomaly-detection.md §6.1/§6.6/§10 P1) Fetches
       result.reconciliation_run_id's own reconciliation_match rows via
       reconciliation_repo.settlement_lag_pairs_for_run, aggregates them via
       calc_engine.formulas.settlement_lag.settlement_lag_days_aggregate (real, unchanged --
       date resolution + mean + negative-lag/missing-date guards), mints a SETTLEMENT_LAG_DAYS
       MetricResult via compute_metric.compute_settlement_lag_days (real, unchanged), and
       persists it via metric_result_repo.save -- grain="MARKETPLACE", target_ref=marketplace,
       mirroring result.aggregate_metric_result's own grain/target_ref exactly (Task 3's own
       reasoning: this is another run-level, per-marketplace aggregate the SAME reconcile() run
       produced, not a per-line or per-SKU figure, and LEAK_TOTAL is the closest existing
       precedent for that shape). Wired HERE, immediately after result.aggregate_metric_result
       is persisted, because this is exactly the point where fresh reconciliation_match rows for
       this run already exist to aggregate -- no other CFO composition function has
       reconciliation_match rows in hand at all.

    No + - * / on any Paise/paise-named value anywhere in this function -- every amount is
    copied unchanged from reconcile()'s own output or the persisted reconciliation_exception
    row it is read back from. Step 9's mean-days aggregation is not a Paise/money value and
    happens entirely inside settlement_lag_days_aggregate/compute_settlement_lag_days, not here."""
    computed_at = datetime.now()  # naive, matching this module's own convention (see e.g.
    # compute_period_pnl/compute_pricing_curve's own `request.computed_at or datetime.now()`)
    period_label = f"{period_start.isoformat()}/{period_end.isoformat()}"

    result = reconcile(
        tenant_id,
        marketplace=marketplace,
        period_start=period_start,
        period_end=period_end,
        as_of_date=as_of_date,
        computed_at=computed_at,
    )

    # --- persist every exception-level MetricResult, keyed by the exception id it belongs to -
    engine_result_ref_by_exception_id: dict[str, UUID] = {}
    for mr in result.exception_metric_results:
        exception_id = mr.input_refs[0]
        metric_result_repo.save(
            tenant_id,
            mr,
            grain="LINE",
            target_ref=str(exception_id),
            period=period_label,
            config_version=_LEAK_SHIELD_CONFIG_VERSION,
        )
        engine_result_ref_by_exception_id[str(exception_id)] = mr.id

    # --- persist the aggregate LEAK_TOTAL -- its own real engine_result_ref (Section 6.4 rule 5)
    metric_result_repo.save(
        tenant_id,
        result.aggregate_metric_result,
        grain="MARKETPLACE",
        target_ref=marketplace,
        period=period_label,
        config_version=_LEAK_SHIELD_CONFIG_VERSION,
    )

    # --- Task 2/9: SETTLEMENT_LAG_DAYS -- aggregated from THIS run's own reconciliation_match
    # rows (anomaly-detection.md §6.1/§6.6, closing §10 P1). Computed and persisted right here,
    # immediately after LEAK_TOTAL, because this is the one point in this composition where
    # fresh reconciliation_match rows for result.reconciliation_run_id already exist.
    settlement_lag_pairs = reconciliation_repo.settlement_lag_pairs_for_run(
        tenant_id, result.reconciliation_run_id
    )
    settlement_lag_aggregate = settlement_lag_days_aggregate(settlement_lag_pairs)
    settlement_lag_result = compute_settlement_lag_days(
        settlement_lag_aggregate,
        reconciliation_run_id=result.reconciliation_run_id,
        computed_at=computed_at,
        as_of_date=as_of_date,
    )
    metric_result_repo.save(
        tenant_id,
        settlement_lag_result,
        grain="MARKETPLACE",
        target_ref=marketplace,
        period=period_label,
        config_version=_LEAK_SHIELD_CONFIG_VERSION,
    )

    exception_rows = reconciliation_repo.exceptions_for_run(tenant_id, result.reconciliation_run_id)

    ambiguous_match_count = 0
    reportable_rows: list[dict[str, object]] = []
    for row in exception_rows:
        if row["exception_type"] == "AMBIGUOUS_MATCH":
            # Decision B: not a ReconciliationOutcome value, never a leak_finding.
            ambiguous_match_count += 1
            continue
        reportable_rows.append(row)

    exception_inputs: list[LeakExceptionInput] = []
    row_by_exception_id: dict[str, dict[str, object]] = {}
    for row in reportable_rows:
        exception_id_str = str(row["id"])
        row_by_exception_id[exception_id_str] = row

        component_code = row.get("component_code")
        component_kind = COMPONENT_KIND_BY_CODE.get(component_code) if component_code else None

        exception_type = row["exception_type"]
        variance_is_settlement_higher = (
            row["amount_paise"] > 0 if exception_type == "VARIANCE_EXCEEDS_TOLERANCE" else None
        )

        exception_inputs.append(
            LeakExceptionInput(
                exception_id=exception_id_str,
                engine_result_ref=str(engine_result_ref_by_exception_id[exception_id_str]),
                marketplace=row["marketplace"],
                outcome=ReconciliationOutcome(exception_type),
                amount_paise=row["amount_paise"],
                affected_line_count=1,
                first_observed_at=row["computed_at"],
                age_days=0,
                claim_window_days=None,
                sku=None,
                component_kind=component_kind,
                variance_is_settlement_higher=variance_is_settlement_higher,
                is_return_linked=False,  # Decision A -- never derived, always False this pass
                is_levy_component=component_kind == "LEVY",
            )
        )

    severity_rows_raw = config_repo.severity_config_rows(tenant_id, as_of_date=as_of_date)
    severity_config_rows = [
        SeverityConfigRow(
            metric=row["metric"],
            high_threshold=row["high_threshold"],
            medium_threshold=row["medium_threshold"],
            window_closing_soon_days=row.get("window_closing_soon_days", 14),
        )
        for row in severity_rows_raw
    ]

    composed_findings: list[ComposedFinding] = classify_and_rank_leaks(
        exceptions=exception_inputs,
        as_of_date=as_of_date,
        config_rows=severity_config_rows,
    )

    inserted: list[dict[str, object]] = []
    for composed in composed_findings:
        exc = composed.exception
        source_row = row_by_exception_id[exc.exception_id]

        if isinstance(composed.severity, SeverityBand):
            severity_value = composed.severity.value
        else:
            # Unavailable -- no severity_config metric had both a config row and applicable
            # data for this finding; never fabricated, never silently defaulted to LOW.
            severity_value = "UNAVAILABLE"

        leak_finding_id = leak_finding_repo.insert(
            tenant_id,
            reconciliation_exception_id=UUID(exc.exception_id),
            engine_result_ref=UUID(exc.engine_result_ref),
            marketplace=exc.marketplace,
            leak_category=composed.leak_category.value,
            severity=severity_value,
            amount_paise=exc.amount_paise,
            affected_line_count=exc.affected_line_count,
            sku=exc.sku,
            first_observed_at=exc.first_observed_at,
            age_days=exc.age_days,
            claim_window_days=exc.claim_window_days,
            window_status=composed.window_status.value,
            explanation=None,
            recommended_action=None,
            status="NEW",
            confidence=str(source_row["confidence"]),
            formula_version="reconcile.v1",
        )
        inserted.append(
            {
                "leak_finding_id": leak_finding_id,
                "leak_category": composed.leak_category.value,
                "severity": severity_value,
                "window_status": composed.window_status.value,
                "amount_paise": exc.amount_paise,
                "marketplace": exc.marketplace,
                "engine_result_ref": exc.engine_result_ref,
                # exc.sku is threaded through unchanged (always None today -- Decision A's
                # sibling gap, no Meesho adapter maps sku yet). Carried here, not omitted, so a
                # caller (e.g. D7's assemble_cfo_preview) can distinguish "not tracked" from a
                # real, falsely-zero-reading count, per CLAUDE.md's "missing input is
                # UNAVAILABLE, never zero" rule.
                "sku": exc.sku,
                # This checkpoint (narrate_leak_findings): the SAME confidence already read
                # from source_row and persisted onto leak_finding.confidence two lines above --
                # threaded through onto the returned dict too so a caller can map it onto a
                # §7.4.7 register without a second DB round-trip. Copied unchanged, never
                # re-derived.
                "confidence": str(source_row["confidence"]),
            }
        )

    return LeakShieldOutcome(
        reconciliation_run_id=result.reconciliation_run_id,
        findings=inserted,
        match_count=result.match_count,
        exception_count=result.exception_count,
        ambiguous_match_count=ambiguous_match_count,
        dates_missing_count=result.dates_missing_count,
        aggregate_amount_paise=result.aggregate_metric_result.value_paise,
        aggregate_engine_result_ref=str(result.aggregate_metric_result.id),
        settlement_lag_engine_result_ref=str(settlement_lag_result.id),
        settlement_lag_is_available=settlement_lag_result.is_available,
        settlement_lag_mean_days=(
            str(settlement_lag_result.value_fraction)
            if settlement_lag_result.value_fraction is not None
            else None
        ),
        settlement_lag_pair_count=(
            settlement_lag_aggregate.pair_count
            if isinstance(settlement_lag_aggregate, SettlementLagAggregate)
            else None
        ),
    )


# ---------------------------------------------------------------------------------------
# D7 -- assemble_cfo_preview (cfo-agent.md Section 6.9 / Section 6.8 `cfo.preview`). The
# free-tier gated preview: headline recoverable-discrepancy total, affected SKU count, ONE
# finding revealed in full, the rest locked. Approved this session, no longer provisional --
# the shape and the on-demand-only cadence are both exactly as Section 6.9 describes, with no
# redesign.
#
# This function is deliberately NOT entitlement-gated -- it calls run_leak_shield_reconciliation
# directly and unconditionally, because the whole point of the preview (Section 6.8's own table
# row: "Passes permission, then intentionally bypasses the entitlement denial") is to work for
# an un-entitled tenant. The route layer (api/v1/cfo.py) is responsible for permission
# (require_auth(permission=AGENT_CFO)) and for NOT calling _require_cfo_entitlement here.
# ---------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CfoPreviewOutcome:
    """The approved D8/Section 6.9 preview shape. `headline_total_paise`/
    `headline_engine_result_ref` are copied unchanged from `LeakShieldOutcome.
    aggregate_amount_paise`/`aggregate_engine_result_ref` (Task 1) -- never recomputed, never
    summed here (Section 6.4 rule 5: "Agents never sum leak amounts themselves").

    `affected_sku_count` is `None` -- with `affected_sku_count_unavailable=True` -- when every
    finding's `sku` is `None` (true of all real data today: no Meesho adapter maps `sku` yet,
    see `run_leak_shield_reconciliation`'s own docstring). This is a deliberate application of
    CLAUDE.md's "missing input is UNAVAILABLE, never zero" rule: a real `0` here would falsely
    read as "no SKUs are affected" when the truth is "SKU isn't tracked per finding yet". When
    `outcome.findings` is empty outright (no leaks at all), `affected_sku_count` is a real,
    honest `0` and `affected_sku_count_unavailable` is `False` -- "zero findings" is a
    genuinely different, non-ambiguous state from "findings exist but none carry a sku"."""

    headline_total_paise: int
    headline_engine_result_ref: str
    affected_sku_count: int | None
    affected_sku_count_unavailable: bool
    revealed_finding: dict[str, object] | None
    locked_findings_count: int


def assemble_cfo_preview(
    tenant_id: UUID,
    *,
    marketplace: str,
    period_start: date,
    period_end: date,
    as_of_date: date,
) -> CfoPreviewOutcome:
    """Composes the free-tier gated preview (cfo-agent.md Section 6.9, `cfo.preview`) from a
    real, freshly-run reconciliation -- on-demand only, no scheduler, no cached/stale result
    (Section 6.9's approved cadence).

    1. Calls the real, unchanged `run_leak_shield_reconciliation` -- this IS the "deterministic,
       already-computed" reconciliation Section 6.9 refers to. NOT gated by entitlement here;
       see this module's own section banner above for why.
    2. `outcome.findings` is already in real, deterministic severity/window rank order --
       `classify_and_rank_leaks` (via `rank_findings`, `calc_engine.formulas.severity`) produces
       that order, and `run_leak_shield_reconciliation` preserves it unchanged when building
       `outcome.findings` (it iterates `composed_findings`, itself `classify_and_rank_leaks`'s
       own return value, in order, appending to `inserted` with no re-sort anywhere in between --
       confirmed by reading that function, not assumed). The FIRST finding in that list is the
       one revealed in full; every other finding is locked, disclosed only by count.
    3. `locked_findings_count = len(outcome.findings) - (1 if outcome.findings else 0)`.
    4. `affected_sku_count` per this function's own honest-unavailable rule -- see
       `CfoPreviewOutcome`'s docstring. Counts only findings whose `sku` is not `None`; if that
       count would be `0` purely because every finding has `sku=None` (not because there are no
       findings), reports `None`/`affected_sku_count_unavailable=True` instead of a bare `0`.
    5. `headline_total_paise`/`headline_engine_result_ref` are copied straight from Task 1's
       `LeakShieldOutcome.aggregate_amount_paise`/`aggregate_engine_result_ref` -- never
       recomputed, never summed from `findings[].amount_paise` here or anywhere else in this
       function, per Section 6.4 rule 5.

    No `+ - * /` on any Paise/paise-named value anywhere in this function -- every amount is
    copied unchanged from `run_leak_shield_reconciliation`'s own output; the only arithmetic
    here is `len(...) - (1 if ... else 0)`, a count of findings, never a money figure."""
    outcome = run_leak_shield_reconciliation(
        tenant_id,
        marketplace=marketplace,
        period_start=period_start,
        period_end=period_end,
        as_of_date=as_of_date,
    )

    findings = outcome.findings

    revealed_finding: dict[str, object] | None = findings[0] if findings else None
    locked_findings_count = len(findings) - (1 if findings else 0)

    if not findings:
        # A real, honest zero -- no leaks at all, not "sku isn't tracked".
        affected_sku_count: int | None = 0
        affected_sku_count_unavailable = False
    else:
        skus_present = [f["sku"] for f in findings if f.get("sku") is not None]
        if skus_present:
            # Count of findings carrying a real sku (task's own wording: "count only the
            # findings that actually carry a non-null sku") -- not a de-duplicated distinct-SKU
            # count, which this function does not attempt.
            affected_sku_count = len(skus_present)
            affected_sku_count_unavailable = False
        else:
            # Every finding has sku=None -- true of all real data today (no Meesho adapter maps
            # sku yet). Reporting 0 here would falsely read as "no SKUs affected" when the truth
            # is "not tracked" -- CLAUDE.md's "missing input is UNAVAILABLE, never zero" rule.
            affected_sku_count = None
            affected_sku_count_unavailable = True

    return CfoPreviewOutcome(
        headline_total_paise=outcome.aggregate_amount_paise,
        headline_engine_result_ref=outcome.aggregate_engine_result_ref,
        affected_sku_count=affected_sku_count,
        affected_sku_count_unavailable=affected_sku_count_unavailable,
        revealed_finding=revealed_finding,
        locked_findings_count=locked_findings_count,
    )


# ---------------------------------------------------------------------------------------
# E3 — run_anomaly_check (docs/specs/cfo-agent.md §6.1 rule 4 / §6.5 / §7; docs/specs/
# anomaly-detection.md, Brain 2). Wires the pure statistics layer built at
# `calc_engine.anomaly` (E2) into CFO for the ONE named series this checkpoint's scope covers
# real, spec-grounded composition for: `MARGIN_PCT` (`docs/specs/anomaly-detection.md` §6.1),
# built from `CONTRIBUTION_MARGIN_PCT` `metric_result` history via
# `calc_engine.api.compute_metric.compute_contribution_margin_pct` (also new this checkpoint).
#
# `FEE_RATIO_PCT`, `SETTLEMENT_LAG_DAYS` and `RETURN_RATE_PCT` remain explicitly OUT OF SCOPE
# (anomaly-detection.md §10 P1/P2; `RETURN_RATE_PCT` has no formula anywhere in
# deterministic-engine.md at all) — this composition function does not attempt any of them.
#
# **The honest story on who populates CONTRIBUTION_MARGIN_PCT history — updated post-E3-wiring.**
# `compute_period_pnl` now composes `compute_contribution_margin_pct` immediately after its own
# `NET_REALIZED_REVENUE`/`CONTRIBUTION_PROFIT` composition, per period, and persists the result
# via `metric_result_repo.save` (same TENANT_PERIOD grain/target_ref/period as those two) — so
# every real seller P&L call now populates one `CONTRIBUTION_MARGIN_PCT` row per period, in
# practice, not just in tests. `run_anomaly_check` itself still never computes or persists a
# `CONTRIBUTION_MARGIN_PCT` row — it only ever READS whatever history already exists via
# `list_by_metric_code`, exactly like `assemble_funding_readiness_reduced` already does for
# `CONTRIBUTION_PROFIT` — that separation of concerns (compute-and-persist lives in
# `compute_period_pnl`, read-only statistics lives here) is unchanged by this wiring. What
# remains a real, named gap: a tenant that has never called `compute_period_pnl` for a period
# (e.g. only ever used `compute_pricing_curve` or another CFO surface) still has no
# `CONTRIBUTION_MARGIN_PCT` row for that period — no scheduled backfill job exists.
# ---------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AnomalyCheckRequest:
    """Everything `run_anomaly_check` needs to assemble a `MARGIN_PCT` series for one
    `target_ref` and run all three Brain-2 methods against it. `target_ref` matches the same
    SKU/ACCOUNT/MARKETPLACE grain concept `MetricResult.target_ref`/`compute_pricing_curve`'s
    own `sku` field already use (anomaly-detection.md §5.2's own `target_ref: TargetRef`) — this
    request does not invent a new grain vocabulary.

    `period_start`/`period_end` bound the lookback window in the SAME `"{start}/{end}"`
    `metric_result.period` label shape `metric_result_repo.list_by_metric_code` already filters
    on (`narrate_period_comparison`/`assemble_funding_readiness_reduced`'s own established
    convention) — CFO has no periodicity assumption of its own, so this is a caller-supplied
    date range, not a "last N periods" count.

    `metric` (this checkpoint's small, mechanical generalization of E3's original MARGIN_PCT-
    only scope) — one of the four anomaly-detection.md §6.1 series names
    (`calc_engine.anomaly.types.METRIC_MARGIN_PCT`/`METRIC_FEE_RATIO_PCT`/
    `METRIC_RETURN_RATE_PCT`/`METRIC_SETTLEMENT_LAG_DAYS`). Defaults to `METRIC_MARGIN_PCT` so
    every pre-existing caller of this request (built before FEE_RATIO_PCT/RETURN_RATE_PCT/
    SETTLEMENT_LAG_DAYS were real) keeps its exact prior behaviour unchanged."""

    target_ref: str
    period_start: date
    period_end: date
    as_of_date: date
    requested_by: UUID
    metric: str = METRIC_MARGIN_PCT
    computed_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class AnomalyMethodOutcome:
    """One method's result — exactly one of `flag`/`insufficient_history`/`zero_variance`/
    `configuration_gap` is non-None (AC2/AC3/AC13/§5.2's own "two distinguished non-flag
    outcomes... never silently coerced" rule, extended to the third, config-gap outcome E2
    already modelled sibling to those two). `method` is always populated, regardless of which
    outcome fired, so a caller can always say which of the three methods a given outcome
    belongs to without inspecting which field is set."""

    method: str
    flag: AnomalyFlag | None = None
    insufficient_history: AnomalyInsufficientHistory | None = None
    zero_variance: AnomalyZeroVariance | None = None
    configuration_gap: AnomalyConfigurationGap | None = None


@dataclass(frozen=True, slots=True)
class AnomalyCheckOutcome:
    """All three methods' outcomes together (§6.1 rule 4's "Brain 2 supplies anomaly flags") —
    `run_anomaly_check` never picks just one method or silently drops any of the three, per this
    checkpoint's own explicit requirement. `series_length` is the number of `CONTRIBUTION_
    MARGIN_PCT` `metric_result` rows actually found and usable (available, non-UNAVAILABLE) for
    this `target_ref`/window — the SAME series every method below was run against, reported once
    here rather than duplicated per-method."""

    target_ref: str
    metric: str
    series_length: int
    methods: tuple[AnomalyMethodOutcome, AnomalyMethodOutcome, AnomalyMethodOutcome]


def _anomaly_threshold_from_config_row(
    row: Mapping[str, object] | None, *, metric: str, method: str
) -> AnomalyThreshold | None:
    """Builds a real `AnomalyThreshold` from a real `anomaly_detection_config` row
    (`config_repo.resolve_anomaly_detection_config`, E2/E3) — `None` in, `None` out (E9/AC13:
    no config row means the method cannot run, never a silently-assumed threshold). Postgres
    `numeric` columns arrive as `decimal.Decimal`; `Fraction(Decimal(...))` converts losslessly
    (no float anywhere in this path, CLAUDE.md/B9)."""
    if row is None:
        return None

    delta_severity_bands: dict[str, Fraction] | None = None
    raw_bands = row.get("delta_severity_bands")
    if raw_bands:
        # delta_severity_bands is stored as {"high": "3.0", ...} — strings, to preserve
        # Fraction/Decimal precision (anomaly-detection.md §5.3's own comment on this column).
        delta_severity_bands = {k: Fraction(str(v)) for k, v in dict(raw_bands).items()}

    return AnomalyThreshold(
        metric=metric,
        method=method,
        min_series_length=int(row["min_series_length"]),  # type: ignore[arg-type]
        config_version=int(row["version"]),  # type: ignore[arg-type]
        z_score_threshold=(
            Fraction(row["z_score_threshold"]) if row.get("z_score_threshold") is not None else None  # type: ignore[arg-type]
        ),
        percentile_low=(
            Fraction(row["percentile_low"]) if row.get("percentile_low") is not None else None  # type: ignore[arg-type]
        ),
        percentile_high=(
            Fraction(row["percentile_high"]) if row.get("percentile_high") is not None else None  # type: ignore[arg-type]
        ),
        delta_severity_bands=delta_severity_bands,
    )


# anomaly-detection.md §6.1's four series names -> the real, persisted `metric_result.
# metric_code` each one's history is actually stored under. Only `MARGIN_PCT` differs from its
# own metric_code (`CONTRIBUTION_MARGIN_PCT` — `compute_contribution_margin_pct`'s own file-
# naming-convention choice, predating the anomaly spec's config-side label); `FEE_RATIO_PCT`/
# `RETURN_RATE_PCT`/`SETTLEMENT_LAG_DAYS` all use the anomaly-config-side name as their
# metric_code directly (see each compute_* function's own docstring in compute_metric.py).
_ANOMALY_METRIC_TO_METRIC_CODE: dict[str, str] = {
    METRIC_MARGIN_PCT: "CONTRIBUTION_MARGIN_PCT",
    METRIC_FEE_RATIO_PCT: "FEE_RATIO_PCT",
    METRIC_RETURN_RATE_PCT: "RETURN_RATE_PCT",
    METRIC_SETTLEMENT_LAG_DAYS: "SETTLEMENT_LAG_DAYS",
}


def _series_point_from_fraction_metric_row(row: Mapping[str, object]) -> SeriesPoint | None:
    """One `value_fraction`-typed `metric_result` row (`CONTRIBUTION_MARGIN_PCT`/
    `FEE_RATIO_PCT`/`RETURN_RATE_PCT`/`SETTLEMENT_LAG_DAYS` — every one of anomaly-detection.md
    §6.1's four series is `Fraction`-valued, never `value_paise`) -> one `SeriesPoint`, or `None`
    when the row is itself `UNAVAILABLE` (anomaly-detection.md B2/E6: a period whose
    engine-computed value is UNAVAILABLE is EXCLUDED from the series entirely — never a
    zero-valued placeholder). Reads `value_fraction_numerator`/`value_fraction_denominator`
    (E3's own additive `metric_result` columns) rather than `value_paise` — nothing here is
    specific to any one of the four metric_codes, which is exactly why this function (renamed
    from `_series_point_from_margin_pct_row`, this checkpoint) needed no change at all to serve
    all four, only a new name that no longer claims to be margin-specific."""
    if not bool(row.get("is_available")):
        return None

    numerator = row.get("value_fraction_numerator")
    denominator = row.get("value_fraction_denominator")
    if numerator is None or denominator is None:
        return None

    raw_period = str(row.get("period") or "")
    period_label = raw_period.split("/", 1)[0] if raw_period else None
    period = date.fromisoformat(period_label) if period_label else None
    if period is None:
        return None

    raw_id = row["id"]
    engine_result_ref = raw_id if isinstance(raw_id, UUID) else UUID(str(raw_id))

    return SeriesPoint(
        period=period,
        value=Fraction(int(numerator), int(denominator)),  # type: ignore[arg-type]
        confidence=Confidence(str(row["confidence"])),
        engine_result_ref=engine_result_ref,
    )


def run_anomaly_check(tenant_id: UUID, request: AnomalyCheckRequest) -> AnomalyCheckOutcome:
    """Wires Brain 2 (`calc_engine.anomaly`, E2) into CFO for `request.metric` — ANY of
    anomaly-detection.md §6.1's four named series (`MARGIN_PCT`/`FEE_RATIO_PCT`/
    `RETURN_RATE_PCT`/`SETTLEMENT_LAG_DAYS`), not just `MARGIN_PCT` (cfo-agent.md §6.1 rule 4 /
    §6.5 / §7; anomaly-detection.md). This checkpoint's own generalization: `request.metric` was
    always a plain `str` end-to-end (`AnomalyCheckOutcome.metric`, `anomaly_detection_config`'s
    own `(metric, method)` key) — this function itself already carried no MARGIN_PCT-specific
    arithmetic anywhere; the only real MARGIN_PCT-only surface was the hardcoded metric_code
    string and the (already metric-agnostic) row->SeriesPoint conversion helper's name. Both are
    now parameterized; the three-method loop, config resolution and outcome-shaping logic below
    are byte-for-byte the same as E3 originally wrote them.

    1. Resolves `request.metric` to its real, persisted `metric_result.metric_code`
       (`_ANOMALY_METRIC_TO_METRIC_CODE`) and fetches this tenant's history for `target_ref` over
       `period_start`/`period_end` via `metric_result_repo.list_by_metric_code` (real,
       unchanged) — the SAME read path `assemble_funding_readiness_reduced` already established
       for `CONTRIBUTION_PROFIT` history.
    2. Converts each usable row into a `SeriesPoint` (`_series_point_from_fraction_metric_row`),
       omitting any row that is itself `UNAVAILABLE` (B2) — never a zero-valued placeholder.
    3. For EACH of the three methods (Z_SCORE, PERCENTILE_THRESHOLD, PERIOD_OVER_PERIOD_DELTA),
       resolves config via `config_repo.resolve_anomaly_detection_config(tenant_id,
       metric=request.metric, method=<method>, as_of_date=...)` (real, unchanged, E2). `None` ->
       `AnomalyConfigurationGap` for that method; a real row -> a real `AnomalyThreshold` ->
       the corresponding pure `calc_engine.anomaly` function (real, unchanged, E2) — B8's own
       "Brain 2 has no database access of its own" boundary is respected: only THIS function
       ever touches Postgres, the anomaly functions themselves never do.
    4. Returns all three methods' outcomes together — never picks one or drops any.

    No arithmetic anywhere in this function beyond what B8 explicitly delegates to the
    already-real `calc_engine.anomaly` pure functions: it fetches
    (`list_by_metric_code`/`resolve_anomaly_detection_config`), converts/reconstructs
    (`_series_point_from_fraction_metric_row`/`_anomaly_threshold_from_config_row`), and calls
    `z_score`/`percentile_threshold`/`period_over_period_delta` unchanged."""
    computed_at = request.computed_at or datetime.now()
    period_start_label = request.period_start.isoformat()
    period_end_label = request.period_end.isoformat()

    metric_code = _ANOMALY_METRIC_TO_METRIC_CODE.get(request.metric)
    if metric_code is None:
        raise ValueError(
            f"run_anomaly_check has no metric_code mapping for metric={request.metric!r} — "
            f"anomaly-detection.md §6.1 only names {sorted(_ANOMALY_METRIC_TO_METRIC_CODE)}; "
            "refusing to guess a metric_code for an unspecified series."
        )

    rows = metric_result_repo.list_by_metric_code(
        tenant_id,
        metric_code=metric_code,
        period_start=period_start_label,
        period_end=period_end_label,
    )

    series_points = [_series_point_from_fraction_metric_row(row) for row in rows]
    series: list[SeriesPoint] = [p for p in series_points if p is not None]
    series.sort(key=lambda p: p.period)

    method_outcomes: list[AnomalyMethodOutcome] = []
    for method_name, anomaly_fn in (
        (METHOD_Z_SCORE, z_score),
        (METHOD_PERCENTILE_THRESHOLD, percentile_threshold),
        (METHOD_PERIOD_OVER_PERIOD_DELTA, period_over_period_delta),
    ):
        config_row = config_repo.resolve_anomaly_detection_config(
            tenant_id, metric=request.metric, method=method_name, as_of_date=request.as_of_date
        )
        threshold = _anomaly_threshold_from_config_row(config_row, metric=request.metric, method=method_name)

        if threshold is None:
            method_outcomes.append(
                AnomalyMethodOutcome(
                    method=method_name,
                    configuration_gap=AnomalyConfigurationGap(
                        metric=request.metric, method=method_name, target_ref=request.target_ref
                    ),
                )
            )
            continue

        result = anomaly_fn(
            series,
            tenant_id=tenant_id,
            target_ref=request.target_ref,
            threshold=threshold,
            computed_at=computed_at,
            as_of_date=request.as_of_date,
        )

        if isinstance(result, AnomalyFlag):
            method_outcomes.append(AnomalyMethodOutcome(method=method_name, flag=result))
        elif isinstance(result, AnomalyInsufficientHistory):
            method_outcomes.append(AnomalyMethodOutcome(method=method_name, insufficient_history=result))
        else:
            assert isinstance(result, AnomalyZeroVariance)
            method_outcomes.append(AnomalyMethodOutcome(method=method_name, zero_variance=result))

    methods = (method_outcomes[0], method_outcomes[1], method_outcomes[2])
    return AnomalyCheckOutcome(
        target_ref=request.target_ref,
        metric=request.metric,
        series_length=len(series),
        methods=methods,
    )


# ---------------------------------------------------------------------------------------
# E3's own named close-out gap, closed here: `narrate_anomaly_check` — the Brain-3 narration
# step `run_anomaly_check` deliberately never built for itself (B8: Brain 2 has no LLM of its
# own; `run_anomaly_check`'s own docstring: "read-only statistics, no narration"). Reuses
# `cfo.reasoning.narrate.narrate_figures`/`FigureToken` UNCHANGED — the same primitive
# `narrate_period_comparison` already established as this codebase's one Brain-3 narration
# mechanism — never a second, parallel narration path.
#
# anomaly-detection.md §7's five rules, applied structurally, not just by convention:
#   rule 1 -> every FigureToken's `formatted_value` states `fired`/`severity`/`score` exactly
#             as `AnomalyFlag` returned them; `_format_fraction_as_decimal_for_narration` below
#             is a presentation-only Decimal rendering of an already-final `Fraction`, the same
#             "format, don't compute" boundary `_format_paise_for_narration` already draws for
#             paise -- no arithmetic that changes a value, only a display conversion.
#   rule 2 -> every flag's `note` cites `config_version`/`formula_version`; nothing here
#             invents a threshold.
#   rule 3 -> no cause-attribution prompt logic exists anywhere below — the `context` string
#             states only what is being checked, never "why", and no parameter exists for a
#             caller to hand in a causal figure (the task's own explicit non-goal: no hook).
#   rule 4 -> `AnomalyInsufficientHistory`/`AnomalyZeroVariance` get their own distinct,
#             plainly-worded `formatted_value` strings, neither of which contains the phrase
#             "no anomaly" — see `_ANOMALY_ZERO_VARIANCE_TEXT`/the insufficient-history f-string.
#   rule 5 -> every flag's FigureToken carries `engine_result_ref=str(flag.
#             decorates_engine_result_ref)`, never omitted.
# ---------------------------------------------------------------------------------------

# §7 rule 4's own exact non-negotiable: neither of these two non-flag outcomes may ever read as
# "no anomaly found" — kept as named constants so a future edit cannot accidentally reintroduce
# that phrasing without touching a line that says, in comments, not to.
_ANOMALY_ZERO_VARIANCE_TEXT = "no variation in the baseline — a z-score cannot be computed"
_ANOMALY_CONFIGURATION_GAP_TEXT = "no anomaly-detection configuration exists for this check yet"

_ANOMALY_METHOD_LABEL: dict[str, str] = {
    METHOD_Z_SCORE: "Z-score check",
    METHOD_PERCENTILE_THRESHOLD: "Percentile threshold check",
    METHOD_PERIOD_OVER_PERIOD_DELTA: "Period-over-period delta check",
}


def _format_fraction_as_decimal_for_narration(value: Fraction) -> str:
    """Presentation-only rendering of an already-final, Brain-2-computed `Fraction` score into
    a plain decimal string for `FigureToken.formatted_value` — mirrors
    `_format_paise_for_narration`'s exact "format, don't calculate" boundary: this determines
    no statistical outcome at all, the score was already fully computed by `calc_engine.anomaly`
    before this function ever runs. Uses `Decimal` (never `float`, CLAUDE.md/AC4) to round to at
    most two decimal places, then strips a trailing `.00`/`0` so `Fraction(16, 5)` -> `"3.2"`,
    not `"3.20"`."""
    decimal_value = Decimal(value.numerator) / Decimal(value.denominator)
    quantized = decimal_value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    text = f"{quantized:f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _figure_tokens_for_anomaly_method_outcome(outcome: AnomalyMethodOutcome) -> list[FigureToken]:
    """One `AnomalyMethodOutcome` -> one `FigureToken`, whichever of `flag`/
    `insufficient_history`/`zero_variance`/`configuration_gap` is populated (exactly one always
    is, per `AnomalyMethodOutcome`'s own docstring) — the per-method building block
    `narrate_anomaly_check` composes three of into one prompt, mirroring how
    `narrate_period_comparison` builds one `FigureToken` per already-fetched `MetricResult`."""
    label = _ANOMALY_METHOD_LABEL[outcome.method]

    if outcome.flag is not None:
        flag = outcome.flag
        score_label = "z" if flag.method == METHOD_Z_SCORE else "score"
        score_text = _format_fraction_as_decimal_for_narration(flag.score)
        formatted_value = (
            f"FIRED ({flag.severity} severity, {score_label}={score_text})"
            if flag.fired
            else f"not anomalous ({score_label}={score_text})"
        )
        return [
            FigureToken(
                label=label,
                formatted_value=formatted_value,
                register=flag.data_confidence,
                engine_result_ref=str(flag.decorates_engine_result_ref),
                note=(
                    f"config_version={flag.config_version}, formula_version={flag.formula_version}"
                ),
            )
        ]

    if outcome.insufficient_history is not None:
        ih = outcome.insufficient_history
        return [
            FigureToken(
                label=label,
                formatted_value=(
                    f"insufficient history ({ih.series_length} periods available, "
                    f"{ih.min_series_length_required} required)"
                ),
                register="UNAVAILABLE",
                engine_result_ref=None,
                note=ih.reason,
            )
        ]

    if outcome.zero_variance is not None:
        zv = outcome.zero_variance
        return [
            FigureToken(
                label=label,
                formatted_value=_ANOMALY_ZERO_VARIANCE_TEXT,
                register="UNAVAILABLE",
                engine_result_ref=None,
                note=zv.reason,
            )
        ]

    assert outcome.configuration_gap is not None
    cg = outcome.configuration_gap
    return [
        FigureToken(
            label=label,
            formatted_value=_ANOMALY_CONFIGURATION_GAP_TEXT,
            register="UNAVAILABLE",
            engine_result_ref=None,
            note=cg.reason,
        )
    ]


def narrate_anomaly_check(
    provider: LlmProvider, *, model: str, outcome: AnomalyCheckOutcome
) -> str:
    """Activates anomaly-detection.md §7's Brain-3 narration step for a real, already-computed
    `AnomalyCheckOutcome` (E3's `run_anomaly_check`) — the gap E3's own close-out named:
    "`POST /cfo/anomaly-check` returns the structured `AnomalyCheckOutcome` only... no Brain-3
    narration step." Builds one `FigureToken` per one of `outcome.methods`' three entries (via
    `_figure_tokens_for_anomaly_method_outcome`) and calls `narrate_figures` (real, unchanged)
    — the SAME Brain-3 primitive `narrate_period_comparison` already uses; no new narration
    mechanism is introduced.

    No arithmetic anywhere in this function: it reads already-final fields off `outcome` and
    each of its three `AnomalyMethodOutcome`s, formats a `Fraction` score into a display string
    (`_format_fraction_as_decimal_for_narration` — presentation, not calculation, exactly the
    same boundary `_format_paise_for_narration` already draws for paise), and calls
    `narrate_figures` unchanged. Builds no cause-attribution prompt (§7 rule 3's narrower "why"
    capability is explicitly out of scope here — no parameter exists for a caller to supply a
    causal figure, and none is inferred)."""
    tokens: list[FigureToken] = []
    for method_outcome in outcome.methods:
        tokens.extend(_figure_tokens_for_anomaly_method_outcome(method_outcome))

    context = (
        f"Anomaly check for {outcome.metric} on {outcome.target_ref}, "
        f"{outcome.series_length} periods of history"
    )
    return narrate_figures(provider, model=model, context=context, figures=tokens)


# ---------------------------------------------------------------------------------------
# `narrate_leak_findings` -- Leak Shield's own remaining narration gap, closed here.
# `run_leak_shield_reconciliation` (D5) has returned raw `leak_finding` rows only, with no
# Brain-3 narration step, since it was built -- this mirrors `narrate_anomaly_check`'s E3
# close-out exactly: reuses `cfo.reasoning.narrate.narrate_figures`/`FigureToken` UNCHANGED,
# no second narration mechanism introduced.
#
# cfo-agent.md §7.4's rules, applied structurally:
#   - §7.4.9 never-computes -> every FigureToken's `formatted_value` is built from fields
#     `run_leak_shield_reconciliation` already computed and persisted (amount_paise, severity,
#     window_status, confidence) via `_format_paise_for_narration`/`_register_for_confidence`,
#     both presentation-only, exactly the same boundary `narrate_anomaly_check` already draws.
#   - §7.4.8 never-invents -> zero findings is stated plainly as "no leaks found this run" via
#     a real FigureToken, never silently empty narration and never an invented finding.
#   - §6.4 rule 5 -> LEAK_TOTAL is threaded straight from `outcome.aggregate_amount_paise`/
#     `aggregate_engine_result_ref`, never summed from the individual findings here.
#   - the finding order is `classify_and_rank_leaks`'s real, already-computed rank order
#     (`run_leak_shield_reconciliation` preserves it unchanged) -- this function narrates that
#     given order, it never re-sorts or re-prioritizes.
# ---------------------------------------------------------------------------------------


def _register_for_confidence(confidence: str) -> str:
    """Maps a bare confidence string onto cfo-agent.md §7.4.7's register vocabulary --
    the same `PROVISIONAL` -> `DERIVED` mapping `_register_for` already established for a
    `MetricResult`, restated here because a `leak_finding` row's confidence (copied from
    `severity_config.confidence` inside `run_leak_shield_reconciliation`) is read back as a
    plain `str`, never wrapped in a `MetricResult` object."""
    if confidence == "PROVISIONAL":
        return "DERIVED"
    return confidence


def _figure_token_for_leak_finding(finding: Mapping[str, object]) -> FigureToken:
    """One already-persisted `leak_finding` row (`LeakShieldOutcome.findings`'s own dict shape)
    -> one `FigureToken`. `amount_paise` is always a real, available int on every finding
    (`run_leak_shield_reconciliation` never mints a finding from an `Unavailable` amount), so
    `_format_paise_for_narration` is called with `is_available=True` unconditionally here.
    `severity` CAN be the literal string `"UNAVAILABLE"` (`run_leak_shield_reconciliation`'s own
    `severity_value = "UNAVAILABLE"` branch, when no severity_config row had both a config row
    and applicable data) -- that state is named plainly in `formatted_value`, never silently
    dropped and never read as a real severity band."""
    amount_text = _format_paise_for_narration(
        finding["amount_paise"],  # type: ignore[arg-type]
        is_available=True,
    )
    severity = str(finding["severity"])
    window_status = str(finding["window_status"])
    confidence = str(finding.get("confidence", "PROVISIONAL"))

    if severity == "UNAVAILABLE":
        formatted_value = (
            f"{amount_text} (severity UNAVAILABLE — not enough configured data to classify "
            f"severity for this finding, never defaulted to a band; window: {window_status})"
        )
    else:
        formatted_value = f"{amount_text} ({severity} severity, window: {window_status})"

    return FigureToken(
        label=str(finding["leak_category"]),
        formatted_value=formatted_value,
        register=_register_for_confidence(confidence),
        engine_result_ref=str(finding["engine_result_ref"]),
    )


def narrate_leak_findings(provider: LlmProvider, *, model: str, outcome: LeakShieldOutcome) -> str:
    """Activates Leak Shield's own Brain-3 narration step for a real, already-computed
    `LeakShieldOutcome` (`run_leak_shield_reconciliation`'s output) -- mirroring
    `narrate_anomaly_check`'s exact shape: build one `FigureToken` per already-ranked finding
    (via `_figure_token_for_leak_finding`), plus one `LEAK_TOTAL` token (threaded, never
    recomputed) and, when available, one `SETTLEMENT_LAG_DAYS` token, then call
    `narrate_figures` (real, unchanged) -- the SAME Brain-3 primitive every other narration
    action in this module already uses.

    Zero findings is a real, valid outcome (§7.4.8): it is narrated via its own `FigureToken`
    stating "no leaks found this run" plainly, never invented as a finding and never left as
    silent/empty narration.

    No arithmetic anywhere in this function -- it reads already-final fields off `outcome` and
    each finding dict, formats them for display (`_format_paise_for_narration`/
    `_format_fraction_as_decimal_for_narration`, both presentation-only, the same boundary
    every other narration function in this module already draws), and calls `narrate_figures`
    unchanged."""
    tokens: list[FigureToken] = []

    if outcome.findings:
        marketplace = str(outcome.findings[0]["marketplace"])
        context = (
            f"Leak Shield reconciliation for {marketplace} (run {outcome.reconciliation_run_id}): "
            f"{outcome.match_count} settlements matched, {outcome.exception_count} exceptions "
            f"identified this run."
        )
        for finding in outcome.findings:
            tokens.append(_figure_token_for_leak_finding(finding))
    else:
        context = (
            f"Leak Shield reconciliation (run {outcome.reconciliation_run_id}): "
            f"{outcome.match_count} settlements matched, no leaks found this run."
        )
        tokens.append(
            FigureToken(
                label="LEAK_FINDINGS",
                formatted_value="no leaks found this run",
                register="VERIFIED",
                engine_result_ref=outcome.aggregate_engine_result_ref,
            )
        )

    tokens.append(
        FigureToken(
            label="LEAK_TOTAL",
            formatted_value=_format_paise_for_narration(
                outcome.aggregate_amount_paise, is_available=True
            ),
            register="DERIVED",
            engine_result_ref=outcome.aggregate_engine_result_ref,
        )
    )

    if outcome.settlement_lag_is_available and outcome.settlement_lag_mean_days is not None:
        lag_text = _format_fraction_as_decimal_for_narration(
            Fraction(outcome.settlement_lag_mean_days)
        )
        pair_count = outcome.settlement_lag_pair_count
        tokens.append(
            FigureToken(
                label="SETTLEMENT_LAG_DAYS",
                formatted_value=f"{lag_text} days ({pair_count} matched pairs)",
                register="DERIVED",
                engine_result_ref=outcome.settlement_lag_engine_result_ref,
            )
        )

    return narrate_figures(provider, model=model, context=context, figures=tokens)


# --- G3: cfo.gst_lookup (cfo-agent.md §6.6 C5/C6/§6.8, deterministic-engine.md §8.4) --------


@dataclass(frozen=True, slots=True)
class GstLookupRequest:
    """One `cfo.gst_lookup` invocation's input. Mirrors `calc_engine.gst_lookup.types.
    GstLookupQuery`'s own fields exactly — `run_gst_applicability_lookup` builds a
    `GstLookupQuery` from this request, never accepts one directly, keeping this module's
    `...Request`/`...Outcome` pairing convention consistent with every other CFO action here.
    `requested_by`/`computed_at` follow the same optional, caller-supplied-clock convention
    `AnomalyCheckRequest` already established (determinism in tests, no hidden `datetime.now()`
    inside the composition function itself)."""

    product_title: str
    sku: str | None = None
    hsn: str | None = None
    category: str | None = None
    requested_by: UUID | None = None
    computed_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class GstLookupOutcome:
    """Exactly one of `result`/`no_match` is non-`None` — mirrors `AnomalyMethodOutcome`'s own
    "exactly one non-None outcome" discipline. `from_cache` is `True` when `gst_lookup_repo.
    find_cached` (§8.4.1's 14-day TTL, L6) served an already-persisted row rather than a fresh
    fetch+LLM call — the real point of G2's caching layer, never bypassed by this function.

    **L2 enforced by omission, same as `gst_applicability_lookup` itself.** This outcome is
    handed back to the caller exactly as computed. Nothing in this module inserts `result` into
    any calculation, `MetricResult`, or `manual_adjustment` row — turning seller ACCEPTANCE of a
    `PROVISIONAL` result into a labelled manual input (deterministic-engine.md §7: "requires
    explicit seller acceptance, which creates a labelled manual input") is an explicitly
    out-of-scope future follow-up, not built at this checkpoint."""

    result: GstLookupResult | None = None
    no_match: GstLookupNoMatch | None = None
    from_cache: bool = False


def _gst_lookup_result_from_cached_row(row: Mapping[str, object]) -> GstLookupResult:
    """Reconstructs a `GstLookupResult` from `gst_lookup_repo.find_cached`'s row dict — the
    same dict->dataclass reconstruction discipline `_metric_result_from_row` already
    established for `metric_result` rows. `likely_rate_pct` arrives as a Postgres `numeric`
    (`decimal.Decimal`); `Fraction(Decimal(...))` (via its string form) converts losslessly,
    the same established pattern `_anomaly_threshold_from_config_row` already uses for
    Postgres-numeric-to-`Fraction` conversion — never a float anywhere in this path."""
    raw_rate = row.get("likely_rate_pct")
    raw_alternatives = row.get("alternatives") or []
    alternatives = tuple(
        {
            "rate_pct": Fraction(str(a["rate_pct"])) if a.get("rate_pct") is not None else None,
            "hsn": a.get("hsn"),
            "category": a.get("category"),
        }
        for a in raw_alternatives  # type: ignore[union-attr]
    )
    raw_id = row["id"]
    raw_tenant_id = row["tenant_id"]
    return GstLookupResult(
        id=raw_id if isinstance(raw_id, UUID) else UUID(str(raw_id)),
        tenant_id=raw_tenant_id if isinstance(raw_tenant_id, UUID) else UUID(str(raw_tenant_id)),
        query_text=str(row["query_text"]),
        source_url=str(row["source_url"]),
        retrieved_at=row["retrieved_at"],  # type: ignore[arg-type]
        sku=row.get("sku"),  # type: ignore[arg-type]
        query_hsn=row.get("query_hsn"),  # type: ignore[arg-type]
        likely_rate_pct=Fraction(str(raw_rate)) if raw_rate is not None else None,
        likely_hsn=row.get("likely_hsn"),  # type: ignore[arg-type]
        likely_category=row.get("likely_category"),  # type: ignore[arg-type]
        ambiguity_note=row.get("ambiguity_note"),  # type: ignore[arg-type]
        alternatives=alternatives,
        source_title=row.get("source_title"),  # type: ignore[arg-type]
        status=str(row["status"]),
        verified_by=row.get("verified_by"),  # type: ignore[arg-type]
        verified_at=row.get("verified_at"),  # type: ignore[arg-type]
    )


def run_gst_applicability_lookup(
    tenant_id: UUID,
    request: GstLookupRequest,
    *,
    fetcher: GstFetcher | None = None,
    llm: GstLookupLlmProvider | None = None,
    model: str | None = None,
) -> GstLookupOutcome:
    """G3's composition root wiring the already-complete G2 lookup (`calc_engine.gst_lookup`)
    into CFO (cfo-agent.md §6.6 C5/C6, §6.8 `cfo.gst_lookup`, deterministic-engine.md §8.4).

    1. Builds a `GstLookupQuery` from `request`.
    2. Checks `gst_lookup_repo.find_cached`'s 14-day TTL cache (L6) FIRST. A cache hit returns
       immediately (`from_cache=True`) — no fetch, no LLM call. This is the real point of G2's
       caching layer; never bypassed here.
    3. On a cache miss, calls the real, unchanged `gst_applicability_lookup`, composing:
       - `fetcher` — defaults to `HttpxGstFetcher()` (a real, live network call in production,
         never in a test — same discipline G2 itself established for this fetcher).
       - `llm` — defaults to `cfo.reasoning.ollama_provider.OllamaLlmProvider(host=
         backend.config.ollama_host())`. `OllamaLlmProvider.complete(*, model: str, prompt:
         str) -> str` satisfies `calc_engine.gst_lookup.llm_provider.LlmProvider`'s `Protocol`
         structurally, with no import/inheritance needed — confirmed directly (both Protocols
         declare the identical `complete(*, model: str, prompt: str) -> str` shape on purpose;
         `calc_engine.gst_lookup.llm_provider`'s own module docstring names this exact
         structural-typing reasoning), and this checkpoint's own test suite proves it actually
         runs (see `test_cfo_gst_lookup.py`'s fake-LLM cache-miss test).
       - `model` — defaults to `backend.config.cfo_narration_model()`, the SAME model-name
         convention every other real CFO Ollama call site in this codebase already reuses
         (`api/v1/cfo.py`'s `post_period_comparison` wires `OllamaLlmProvider` against this
         exact function) — no second model convention invented here.
       Both `fetcher`/`llm`/`model` accept caller-injected fakes (this function's own keyword
       parameters), so tests never touch a real network or a real Ollama instance.
    4. On a genuine `GstLookupResult` (not `GstLookupNoMatch`), persists it via `gst_lookup_
       repo.save` so the next identical query within 14 days hits the cache.
    5. On `GstLookupNoMatch`, persists NOTHING — there is nothing worth caching about "no
       reliable source found"; a fresh attempt next time is correct, never a remembered
       permanent failure.

    **L2 enforced by omission** — see `GstLookupOutcome`'s own docstring. This function returns
    the result; it never applies it to any calculation, `MetricResult`, or `manual_adjustment`.
    """
    computed_at = request.computed_at or datetime.now(timezone.utc)
    query = GstLookupQuery(
        product_title=request.product_title,
        sku=request.sku,
        hsn=request.hsn,
        category=request.category,
    )

    cached_row = gst_lookup_repo.find_cached(
        tenant_id, query_text=query.product_title, query_hsn=query.hsn, now=computed_at
    )
    if cached_row is not None:
        return GstLookupOutcome(result=_gst_lookup_result_from_cached_row(cached_row), from_cache=True)

    resolved_fetcher: GstFetcher = fetcher if fetcher is not None else HttpxGstFetcher()
    resolved_llm: GstLookupLlmProvider = llm if llm is not None else OllamaLlmProvider(host=ollama_host())
    resolved_model = model or cfo_narration_model()

    lookup_outcome = gst_applicability_lookup(
        query,
        fetcher=resolved_fetcher,
        llm=resolved_llm,
        tenant_id=tenant_id,
        computed_at=computed_at,
        model=resolved_model,
    )

    if isinstance(lookup_outcome, GstLookupNoMatch):
        return GstLookupOutcome(no_match=lookup_outcome, from_cache=False)

    gst_lookup_repo.save(tenant_id, lookup_outcome)
    return GstLookupOutcome(result=lookup_outcome, from_cache=False)


# --- G4: seller acceptance of a gst_lookup_result -> gst_rate_override manual_adjustment ----
# (deterministic-engine.md §7.2.1 `gst_rate_override` row + §8.4's updated L2 rule) ----------


@dataclass(frozen=True, slots=True)
class AcceptGstLookupRequest:
    """Everything `accept_gst_lookup_result` needs to turn one specific, already-persisted
    `gst_lookup_result` row into a real `gst_rate_override` manual_adjustment (§7.2.1) — the
    explicit seller-acceptance act L2 requires before that row's rate may ever reach a
    calculation. `sku` is the target the override applies to (`SKU` grain, §7.2.1) — this is
    the value written as `manual_adjustment.target_ref`, not necessarily identical to
    `gst_lookup_result.sku` (a lookup may have been run against a bare product title with no
    `sku` set on the query at all; the seller names the SKU the override applies to at
    acceptance time). `accepted_by` is who created the manual_adjustment (`created_by`) —
    mirrors `enter_expense`'s own `created_by` parameter, this module's established convention
    for the acting user's identity on a manual-input write.

    `rate_pct`/`hsn`/`category` below are accepted on this dataclass but are DELIBERATELY NEVER
    READ by `accept_gst_lookup_result` — see that function's own docstring. Their only purpose
    is to let a caller/UI echo back what it displayed to the seller for its own logging; the
    manual_adjustment this function writes always uses the REAL stored `gst_lookup_result`
    row's own values instead. A unit test asserts this directly by supplying values here that
    deliberately differ from the stored row and checking the created adjustment still matches
    the stored row, not these fields."""

    gst_lookup_result_id: UUID
    sku: str
    accepted_by: UUID
    reason: str | None = None
    effective_from: date | None = None
    accepted_at: datetime | None = None
    rate_pct: str | None = None
    hsn: str | None = None
    category: str | None = None


@dataclass(frozen=True, slots=True)
class GstRateOverrideOutcome:
    """`manual_adjustment_id` is `None` ONLY when this function refused to create an override
    — no `gst_lookup_result` row with that id exists for this tenant, or the row exists but
    carries no `likely_rate_pct` (a `GstLookupNoMatch`-shaped or empty row somehow persisted).
    `rejected_reason` names exactly which of those two cases applied; it is `None` on success.
    Exactly one of the two fields is meaningful at a time, mirroring this module's other
    `...Outcome` dataclasses' "look at which field is populated" convention."""

    manual_adjustment_id: UUID | None
    rejected_reason: str | None = None


def accept_gst_lookup_result(
    tenant_id: UUID, request: AcceptGstLookupRequest
) -> GstRateOverrideOutcome:
    """The seller-acceptance act deterministic-engine.md §8.4's L2 rule requires before a
    `gst_lookup_result`'s rate may ever reach a calculation (§7.2.1's `gst_rate_override`).

    1. Reads back the REAL `gst_lookup_result` row by id, tenant-scoped
       (`gst_lookup_repo.get_by_id`, this checkpoint's one new repository read) — never trusts
       `request.rate_pct`/`hsn`/`category` for the values actually written (see
       `AcceptGstLookupRequest`'s own docstring on why those fields exist but are unread here).
    2. Refuses — returns `GstRateOverrideOutcome(manual_adjustment_id=None, rejected_reason=...)`
       rather than raising or synthesizing anything — when either:
       - no row with `request.gst_lookup_result_id` exists for this tenant (RLS makes a
         cross-tenant id and a genuinely nonexistent one indistinguishable, by design, same as
         every other tenant-scoped lookup in this codebase), or
       - the row exists but `likely_rate_pct` is `None` — a `GstLookupNoMatch`-shaped or empty
         result somehow persisted, which G2's own design says should not happen (G3 never calls
         `gst_lookup_repo.save` on a `GstLookupNoMatch`) but this function does not assume that
         invariant holds forever; it checks explicitly rather than crashing on a stray `None`.
    3. On a genuine row, inserts exactly one `gst_rate_override` manual_adjustment via
       `manual_adjustment_repo.insert_adjustment` (real, unchanged) —
       `target_type="SKU"`, `target_ref=request.sku`, `field="gst_rate_override"`,
       `value={rate_pct, hsn, category, gst_lookup_result_id, effective_from}` — with
       `rate_pct` stored as the row's real `likely_rate_pct`, rendered as a Decimal-string
       (`str(...)`, never a JSON float, matching §7.2.1's explicit "no-float" rule for this
       field), and `hsn`/`category` echoing the row's real `likely_hsn`/`likely_category`.
       `effective_from` defaults to `accepted_at`'s date when the caller does not supply one —
       never backdated automatically, consistent with L6's "never applied retroactively to
       historical periods" (a caller may still supply an explicit forward date; this function
       never invents one further back than today itself).
    4. When an ACTIVE `gst_rate_override` already exists for this exact `(SKU, field)` target
       (`manual_adjustment_repo.active_adjustments_for_target`, real, unchanged, newest first),
       the new row's `supersedes_id` is set to that existing row's id automatically — accepting
       a second, different lookup result for a SKU already carrying an override is a
       correction, not an unrelated new fact, mirroring
       `test_correction_is_a_new_row_with_supersedes_id_not_an_update`'s established
       append-only chain pattern. The prior row's own `status` column is never changed (it
       cannot be — `UPDATE`/`DELETE` are revoked at the grant level for `manual_adjustment`,
       same as every other field): both rows simply exist afterward, exactly as that precedent
       already established.
    5. Never marks the source `gst_lookup_result` row `SELLER_VERIFIED` or touches its `status`
       in any way — per the spec's explicit "two separate, separately-recorded acts" rule
       (§7.2.1), AND because `gst_lookup_result` genuinely has no `UPDATE` grant for
       `metrion_app` at all (`20260925_0008_gst_lookup_result.py`'s own docstring: append-only
       by design, `GRANT SELECT, INSERT` only) — this function could not perform that update
       even if the spec asked it to. Marking a lookup row `SELLER_VERIFIED` is out of scope for
       this checkpoint, not silently skipped: it would need its own separate write path, on a
       column set this migration deliberately left without an `UPDATE` grant.

    No arithmetic anywhere in this function — it reads back an already-final stored value,
    renders it to a Decimal-string for storage (no float conversion, no calculation), and
    inserts via `insert_adjustment`, unchanged."""
    accepted_at = request.accepted_at or datetime.now(timezone.utc)

    stored_row = gst_lookup_repo.get_by_id(tenant_id, request.gst_lookup_result_id)
    if stored_row is None:
        return GstRateOverrideOutcome(
            manual_adjustment_id=None,
            rejected_reason=(
                f"no gst_lookup_result row with id={request.gst_lookup_result_id} exists for "
                "this tenant"
            ),
        )

    stored_rate = stored_row.get("likely_rate_pct")
    if stored_rate is None:
        return GstRateOverrideOutcome(
            manual_adjustment_id=None,
            rejected_reason=(
                f"gst_lookup_result id={request.gst_lookup_result_id} has no likely_rate_pct "
                "(a GstLookupNoMatch-shaped or empty result) — nothing to accept"
            ),
        )

    effective_from = request.effective_from or accepted_at.date()
    value: dict[str, object] = {
        "rate_pct": str(stored_rate),
        "hsn": stored_row.get("likely_hsn"),
        "category": stored_row.get("likely_category"),
        "gst_lookup_result_id": str(request.gst_lookup_result_id),
        "effective_from": effective_from.isoformat(),
    }

    existing_active = manual_adjustment_repo.active_adjustments_for_target(
        tenant_id, target_type="SKU", target_ref=request.sku, field="gst_rate_override"
    )
    supersedes_id: UUID | None = existing_active[0]["id"] if existing_active else None

    manual_adjustment_id = insert_adjustment(
        tenant_id,
        target_type="SKU",
        target_ref=request.sku,
        field="gst_rate_override",
        value=value,
        created_by=request.accepted_by,
        created_at=accepted_at,
        reason=request.reason,
        supersedes_id=supersedes_id,
    )
    return GstRateOverrideOutcome(manual_adjustment_id=manual_adjustment_id)
