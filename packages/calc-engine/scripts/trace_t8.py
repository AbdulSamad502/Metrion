"""Manual end-to-end trace of T8 (RTO, inventory recovered sellable) — Checkpoint 5.

Not a unit test; a standalone script that prints every intermediate value on the path from
raw canonical input to a metric_result-shaped MetricResult, for human review.
"""

from __future__ import annotations

import sys
from dataclasses import asdict
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))

from calc_engine.api.compute_metric import compute_contribution_profit, compute_net_realized_revenue
from calc_engine.dates import resolve_document_date
from calc_engine.formulas.contribution_profit import contribution_margin_pct
from calc_engine.formulas.cost_components import billable_quantity, cogs, weighted_average_cost, CostEntry
from calc_engine.formulas.discount_attribution import seller_funded_discounts
from calc_engine.formulas.gross_order_value import gross_order_value
from calc_engine.formulas.return_rto_losses import return_rto_losses
from calc_engine.formulas.revenue_reductions import (
    cancellation_reversal,
    return_reversal,
    rto_unrecovered_revenue,
)
from calc_engine.types import Paise, RecognitionState, ZERO
from fixtures.canonical_builder import CanonicalDataBuilder


def bearer_resolver(marketplace: str, component_code: str):
    from calc_engine.types import Bearer
    return Bearer.SELLER  # no discounts on this line; resolver is never actually consulted


def step(label: str, value: object) -> None:
    print(f"{label:45s} = {value}")


print("=" * 90)
print("T8 trace: RTO, inventory recovered sellable")
print("=" * 90)

# 1. Raw canonical input -----------------------------------------------------------------
line = (
    CanonicalDataBuilder()
    .marketplace("MEESHO")
    .quantity(1)
    .gross(100_000)  # Rs 1,000
    .document_date(date(2026, 8, 20))
    .rto(1, outcome="RECOVERED_SELLABLE")
    .logistics("SHIPPING_CHARGE", 6_000)  # forward leg, Rs 60
    .build()
)
print("\n-- 1. Raw canonical input --")
step("sales_line_id", line.sales_line_id)
step("marketplace", line.marketplace)
step("quantity", line.quantity)
step("gross_item_amount", line.gross_item_amount)
step("invoice_date", line.invoice_date)
step("cancellation_state", line.cancellation_state)
step("return_status", line.return_status)
step("rto_status", line.rto_status)
step("rto_qty", line.rto_qty)
step("rto_outcome", line.rto_outcome)

# 2. Resolved document date ---------------------------------------------------------------
doc_date = resolve_document_date(line.invoice_date, line.dispatch_date, line.order_date)
print("\n-- 2. Resolved document date --")
step("resolve_document_date(...)", doc_date)

# 3. Gross Order Value ---------------------------------------------------------------------
gov = gross_order_value([line])
print("\n-- 3. GrossOrderValue (§5.2) --")
step("gross_order_value([line])", gov)

# 4. Seller-funded discounts ----------------------------------------------------------------
sfd = seller_funded_discounts([line], bearer_resolver)
print("\n-- 4. SellerFundedDiscounts (§5.3) --")
step("seller_funded_discounts([line], ...)", sfd)

# 5. Cancellation / return / RTO treatment ---------------------------------------------------
cancel_rev = cancellation_reversal(line)
return_rev = return_reversal(line)
rto_rev = rto_unrecovered_revenue(line, bearer_resolver)
print("\n-- 5. Cancellation / Return / RTO treatment (§5.4) --")
step("cancellation_reversal(line)", cancel_rev)
step("return_reversal(line)", return_rev)
step("rto_unrecovered_revenue(line, ...)", rto_rev)

# 6. Net Realized Revenue --------------------------------------------------------------------
nrr_result = compute_net_realized_revenue(
    [line],
    bearer_resolver=bearer_resolver,
    recognition_state=RecognitionState.REALIZED,
    ingestion_run_ids=[uuid4()],
    adapter_versions=["meesho.sales.v1:1"],
    active_adjustment_ids=[],
    computed_at=datetime(2026, 9, 17, 12, 0, 0, tzinfo=timezone.utc),
    as_of_date=date(2026, 9, 17),
)
print("\n-- 6. NetRealizedRevenue metric_result (§5.5, §9) --")
step("value_paise", nrr_result.value_paise)
step("confidence", nrr_result.confidence)
step("recognition_state", nrr_result.recognition_state)
step("calculation_basis", nrr_result.calculation_basis)
step("engine_result_ref (id)", nrr_result.id)
step("canonical_data_version", nrr_result.canonical_data_version)
step("exclusions", nrr_result.exclusions)

# 7. COGS -------------------------------------------------------------------------------------
unit_cost = weighted_average_cost("SKU-DEMO-1", doc_date, cost_history=[CostEntry(Paise(8_000), date(2026, 8, 1))])
b_qty = billable_quantity(line)
cogs_value = cogs(line, unit_cost)
print("\n-- 7. COGS (§5.6, corrected billable_quantity) --")
step("weighted_average_cost(...)", unit_cost)
step("billable_quantity(line)", b_qty)
step("cogs(line, unit_cost)", cogs_value)

# 8. Logistics / loss treatment -----------------------------------------------------------------
forward_logistics = Paise(6_000)
reverse_logistics = Paise(6_000)
losses = return_rto_losses(
    line,
    unit_cost=unit_cost,
    forward_logistics=forward_logistics,
    reverse_logistics=reverse_logistics,
    non_refunded_fees_retained=ZERO,
)
print("\n-- 8. ReturnRTOLosses (§5.7, corrected) --")
step("forward_logistics", forward_logistics)
step("reverse_logistics", reverse_logistics)
step("return_rto_losses(...)", losses)

# 9. Contribution Profit --------------------------------------------------------------------
cp_result = compute_contribution_profit(
    nrr_result,
    cogs=cogs_value,
    marketplace_fees=ZERO,
    shipping_logistics=ZERO,  # the RTO line's SHIPPING_CHARGE is excluded here — it's inside ReturnRTOLosses instead
    advertising_costs=ZERO,
    return_rto_losses=losses,
    other_allocated_costs=ZERO,
    ingestion_run_ids=[uuid4()],
    adapter_versions=["meesho.sales.v1:1"],
    active_adjustment_ids=[],
    computed_at=datetime(2026, 9, 17, 12, 0, 0, tzinfo=timezone.utc),
    as_of_date=date(2026, 9, 17),
)
print("\n-- 9. ContributionProfit metric_result (§5.8, §9) --")
step("value_paise", cp_result.value_paise)
step("confidence", cp_result.confidence)
step("recognition_state", cp_result.recognition_state)
step("calculation_basis", cp_result.calculation_basis)
step("engine_result_ref (id)", cp_result.id)
step("input_refs", cp_result.input_refs)

margin = contribution_margin_pct(Paise(cp_result.value_paise), Paise(nrr_result.value_paise))
step("contribution_margin_pct(...)", margin)

print("\n" + "=" * 90)
print("FINAL metric_result-shaped outputs")
print("=" * 90)
print("NetRealizedRevenue MetricResult:")
for k, v in asdict(nrr_result).items():
    print(f"  {k}: {v}")
print("\nContributionProfit MetricResult:")
for k, v in asdict(cp_result).items():
    print(f"  {k}: {v}")
