"""Assembles the six cost inputs `calc_engine.api.compute_metric.compute_contribution_profit`
needs (`cogs`, `marketplace_fees`, `shipping_logistics`, `advertising_costs`,
`return_rto_losses`, `other_allocated_costs`) — twinkly-mapping-canyon.md CP2.

**No money arithmetic lives here.** Every `+`/`-`/`*` on a `Paise` value happens inside
`calc_engine` itself (`cost_components.cogs`, `return_rto_losses.return_rto_losses`,
`formulas.component_sum.sum_components`, `types.sum_paise`, ...) — this module only calls
those real, unchanged functions per line and collects their results into a list that
`calc_engine.types.sum_paise` (also real, unchanged) folds into one `Paise`. A missing
per-line COGS or RTO-outcome classification propagates as `Unavailable` — the first
`Unavailable` line makes the whole period's figure `Unavailable`, exactly as
`cost_components.py`/`return_rto_losses.py` already document; never a silent zero (CLAUDE.md
hard rule, E9).

Component-code taxonomy (which `component_code`s mean "forward logistics" vs "reverse
logistics" vs "a non-refunded retained fee" for a given marketplace) is owned by
`data-foundation.md`'s adapters, not decided here (see `return_rto_losses.py`'s own
docstring) — callers must supply those code sets explicitly; this module invents no default
for them. `ShippingLogistics`'s two codes (`LOGISTICS_FEE`, `SHIPPING_CHARGE`) ARE named
directly in `deterministic-engine.md` §5.6, so those two are safe, spec-cited defaults.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Mapping, Sequence

from calc_engine.formulas import cost_components, expense_pools
from calc_engine.formulas import marketplace_fees as marketplace_fees_formula
from calc_engine.formulas import return_rto_losses as return_rto_losses_formula
from calc_engine.formulas.component_sum import sum_components
from calc_engine.types import CanonicalLine, Paise, Unavailable, sum_paise

# deterministic-engine.md §5.6: "ShippingLogistics = Σ[LOGISTICS_FEE, SHIPPING_CHARGE(seller-borne)]"
DEFAULT_SHIPPING_COMPONENT_CODES: frozenset[str] = frozenset({"LOGISTICS_FEE", "SHIPPING_CHARGE"})


def resolve_cogs(
    lines: Sequence[CanonicalLine],
    *,
    sku_by_line: Mapping[str, str],
    cost_history_by_sku: Mapping[str, Sequence[cost_components.CostEntry]],
    as_of: date,
) -> Paise | Unavailable:
    """`COGS` input — per line via `cost_components.weighted_average_cost` +
    `cost_components.cogs` (both real, unchanged), summed via `calc_engine.types.sum_paise`.
    A line with no `sku_by_line` entry or no matching cost history is `Unavailable`, same as a
    missing `cogs_per_unit` adjustment (E9, D3) — never treated as zero cost."""
    per_line_costs: list[Paise] = []
    for line in lines:
        sku = sku_by_line.get(str(line.sales_line_id))
        if sku is None:
            return Unavailable(
                reason=f"no sku mapping for sales_line {line.sales_line_id}",
                missing_inputs=("sku_by_line",),
            )
        unit_cost = cost_components.weighted_average_cost(sku, as_of, cost_history_by_sku.get(sku, ()))
        line_cogs = cost_components.cogs(line, unit_cost)
        if isinstance(line_cogs, Unavailable):
            return line_cogs
        per_line_costs.append(line_cogs)
    return sum_paise(per_line_costs)


def resolve_marketplace_fees(
    lines: Sequence[CanonicalLine],
    *,
    fee_component_codes: frozenset[str],
    duplicate_candidate_codes: frozenset[str] = frozenset(),
    side: str = "SETTLEMENT_ELSE_INVOICE",
) -> tuple[Paise, tuple[dict[str, object], ...]]:
    """`MarketplaceFees` input — a direct, unchanged pass-through to
    `calc_engine.formulas.marketplace_fees.marketplace_fees`, including its V-FEE-002
    duplicate-candidate flags (never resolved here — E12, "seller resolves").

    **Default changed from `"INVOICE"` to `"SETTLEMENT_ELSE_INVOICE"`** (CFO end-to-end
    evaluation, 2026-09-27) — mirrors `resolve_shipping_logistics`'s own default immediately
    below. The old `"INVOICE"` default silently computed `MarketplaceFees` as 0 (never
    `Unavailable`) for Meesho — the one marketplace with a validated join key — because no
    Meesho adapter produces an invoice-side fee `ComponentRow` at all; commission is deducted
    entirely on the settlement side (`data-foundation.md` §5.1, `reconcile.py`'s own
    "Decision A" docstring). That silently violated the hard rule that a missing input is
    `Unavailable`, never zero, for exactly the CFO's most common real-world data shape."""
    return marketplace_fees_formula.marketplace_fees(
        lines,
        fee_component_codes,
        duplicate_candidate_codes,
        side=side,
    )


def resolve_shipping_logistics(
    lines: Sequence[CanonicalLine],
    *,
    shipping_component_codes: frozenset[str] = DEFAULT_SHIPPING_COMPONENT_CODES,
    side: str = "SETTLEMENT_ELSE_INVOICE",
) -> Paise:
    """`ShippingLogistics` input — `Σ[LOGISTICS_FEE, SHIPPING_CHARGE]` excluding actual
    return/RTO lines (§5.6: that logistics belongs to `ReturnRTOLosses`, never counted twice).
    A single call into `component_sum.sum_components` (real, unchanged) does the summation."""
    return sum_components(
        lines,
        component_codes=shipping_component_codes,
        exclude_rto_lines=True,
        side=side,
    )


def resolve_expense_pool_total(adjustment_values: Sequence[Mapping[str, object]]) -> Paise:
    """`AdvertisingCosts` / `OtherAllocatedCosts` inputs at period grain — sums whichever
    `expense.advertising` / `expense.other` (engine §7.2.1) `manual_adjustment.value` rows are
    ACTIVE and in scope for this period, via `expense_pools.parse_expense_pool_adjustment`
    (real, unchanged) per entry and `sum_paise` (real, unchanged) across entries. A period
    P&L wants one total, not a per-SKU allocation — `expense_pools.allocate_account_level_
    expense_pool` is for SKU-level attribution elsewhere in CFO, not this composition. No
    adjustment in scope -> ZERO, confirmed by `expense_pools.py`'s own docstring ("Absent
    adjustment = zero, confirmed") — this is the one input in this module that a legitimate
    absence resolves to zero rather than Unavailable, because advertising/other spend is
    opt-in seller-declared data, not a cost every sold unit necessarily carries."""
    entries = [expense_pools.parse_expense_pool_adjustment(dict(v)) for v in adjustment_values]
    return sum_paise([e.amount_paise for e in entries])


def resolve_return_rto_losses(
    lines: Sequence[CanonicalLine],
    *,
    sku_by_line: Mapping[str, str],
    cost_history_by_sku: Mapping[str, Sequence[cost_components.CostEntry]],
    as_of: date,
    forward_logistics_codes: frozenset[str],
    reverse_logistics_codes: frozenset[str],
    non_refunded_fee_codes: frozenset[str],
) -> Paise | Unavailable:
    """`ReturnRTOLosses` input — per line via `return_rto_losses.return_rto_losses` (real,
    unchanged), with its three logistics/fee legs extracted per line via `sum_components`
    (also real, unchanged) rather than invented here. `forward_logistics_codes` /
    `reverse_logistics_codes` / `non_refunded_fee_codes` are caller-supplied because that
    component-code taxonomy is data-foundation's adapter concern, not decided in this module
    (see `return_rto_losses.py`'s own docstring) — no default is invented for them. A line
    whose RTO/return outcome isn't yet classified propagates `Unavailable` for the whole
    period figure, exactly as the engine formula documents."""
    per_line_losses: list[Paise] = []
    for line in lines:
        unit_cost: Paise | Unavailable
        sku = sku_by_line.get(str(line.sales_line_id))
        if sku is None:
            unit_cost = Unavailable(
                reason=f"no sku mapping for sales_line {line.sales_line_id}",
                missing_inputs=("sku_by_line",),
            )
        else:
            unit_cost = cost_components.weighted_average_cost(sku, as_of, cost_history_by_sku.get(sku, ()))

        single_line = (line,)
        forward = sum_components(single_line, component_codes=forward_logistics_codes, side="SETTLEMENT_ELSE_INVOICE")
        reverse = sum_components(single_line, component_codes=reverse_logistics_codes, side="SETTLEMENT_ELSE_INVOICE")
        non_refunded = sum_components(single_line, component_codes=non_refunded_fee_codes, side="SETTLEMENT_ELSE_INVOICE")

        loss = return_rto_losses_formula.return_rto_losses(line, unit_cost, forward, reverse, non_refunded)
        if isinstance(loss, Unavailable):
            return loss
        per_line_losses.append(loss)
    return sum_paise(per_line_losses)


@dataclass(frozen=True, slots=True)
class ContributionProfitInputs:
    """The exact six keyword arguments `compute_contribution_profit` accepts beyond the NRR
    result — bundled so `cfo_actions.compute_period_pnl` can assemble them in one place and
    pass them through unchanged (`**dataclasses.asdict`-free, explicit keywords at the call
    site, to keep the "calls the real engine function unchanged" contract visibly true)."""

    cogs: Paise | Unavailable
    marketplace_fees: Paise
    shipping_logistics: Paise
    advertising_costs: Paise
    return_rto_losses: Paise | Unavailable
    other_allocated_costs: Paise
