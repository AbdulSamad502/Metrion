"""margin_curve / margin_at_price — deterministic-engine.md §5.13.1.

MarginAtPrice(candidate_price) =
      ContributionProfit(
          net_realized_revenue = NormalizeToExclusive(candidate_price, basis, gst_rate),
          cogs, marketplace_fees = TaxableRevenue x fee_reference.rate_pct / 100,
          shipping_logistics, advertising_costs, return_rto_losses, other_allocated_costs
      )

Reserved for a seller's own owned `sku` (`cfo-agent.md` §6.7) — never for a candidate the
seller has not committed to buying (§5.13.2 covers that, unrelated formula/table).

**`FIXED`-type `fee_reference` rows cannot be represented by this formula.** `fee_reference`
(§5.14) has no flat-amount column — only `rate_pct`/`rate_low_pct`/`rate_high_pct` — so this
formula assumes a percentage-bearing `FeeReference` throughout. Callers must not pass a
`FIXED`-fee-type resolution here; that is a documented schema gap tracked separately in this
batch's engine-extension notes, not something this formula silently coerces or guesses around.

This formula delegates every step to an existing, unchanged primitive:
- Step 1 (GST normalisation) -> `gst.normalization.normalize_to_exclusive`.
- Step 3 (the ONLY new arithmetic here: fee amount) -> `rounding.round_half_up_paise`.
- Step 4 (the subtraction chain) -> `formulas.contribution_profit.contribution_profit`.
"""

from __future__ import annotations

from fractions import Fraction

from calc_engine.formulas.contribution_profit import contribution_profit
from calc_engine.formulas.fee_resolution import FeeReference
from calc_engine.gst.normalization import Basis, normalize_to_exclusive
from calc_engine.rounding import round_half_up_paise
from calc_engine.types import Paise, Unavailable


def margin_at_price(
    candidate_price: Paise,
    *,
    basis: Basis,
    gst_rate: Fraction | None,
    cogs: Paise | Unavailable,
    fee_reference: FeeReference | Unavailable,
    shipping_logistics: Paise | Unavailable,
    advertising_costs: Paise | Unavailable,
    return_rto_losses: Paise | Unavailable,
    other_allocated_costs: Paise | Unavailable,
) -> Paise | Unavailable:
    """Contribution Profit implied by selling at `candidate_price`, using an
    already-resolved `fee_reference` (this function does not call
    `config_repo.resolve_fee_reference` itself — that is the caller's job, exactly the
    separation `contribution_profit` already has from its own cost inputs).

    Never usable with a `FIXED`-type fee resolution — see module docstring.
    """
    taxable_revenue = normalize_to_exclusive(candidate_price, basis, gst_rate)
    if isinstance(taxable_revenue, Unavailable):
        return taxable_revenue

    if isinstance(fee_reference, Unavailable):
        return fee_reference
    if fee_reference.rate_pct is None:
        # Range-only FeeReference (§5.14's "never collapse a range" rule, mirrored from
        # fee_resolution.py) — this formula must not invent which end of the range to use,
        # so it fails UNAVAILABLE rather than guessing low/high/midpoint.
        return Unavailable(
            reason=(
                "fee_reference provides only a rate range (rate_low_pct/rate_high_pct), not a "
                "point rate_pct — margin_curve requires a resolved point rate"
            ),
            missing_inputs=("fee_reference.rate_pct",),
        )

    fee_amount = round_half_up_paise(Fraction(taxable_revenue.value) * fee_reference.rate_pct / 100)

    # A cost the seller marked "unknown" is UNAVAILABLE, never a zero (spec ceo 6.33 / Q31). The order matches `contribution_profit`'s own precedence
    # (cogs, then return/RTO) so existing results are unchanged; the three allocated costs follow.
    for cost in (cogs, return_rto_losses, shipping_logistics, advertising_costs, other_allocated_costs):
        if isinstance(cost, Unavailable):
            return cost

    return contribution_profit(
        net_realized_revenue=taxable_revenue,
        cogs=cogs,
        marketplace_fees=fee_amount,
        shipping_logistics=shipping_logistics,
        advertising_costs=advertising_costs,
        return_rto_losses=return_rto_losses,
        other_allocated_costs=other_allocated_costs,
    )
