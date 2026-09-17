"""NetRealizedRevenue — deterministic-engine.md §5.5.

NetRealizedRevenue(line) =
      GrossOrderValue
    − SellerFundedDiscounts
    − CancellationReversal
    − ReturnReversal
    − RTOUnrecoveredRevenue

Marketplace-funded discounts appear in no term (R2).

A line is excluded from the aggregate — never silently treated as "nothing happened" — if any
of its three status fields (cancellation_state, return_status, rto_status) is unresolvable for
its marketplace (C1/C2). This is deliberately strict: for a marketplace where we cannot tell
cancelled/returned/RTO'd lines apart from ordinary ones at all (Amazon/Flipkart today), we
cannot honestly assert a Net Realized Revenue figure for any of its lines, since an
unflagged-but-actually-cancelled line would otherwise silently inflate revenue. Excluded lines
are disclosed by sales_line_id and reason in `exclusions`, per the same pattern as a
quarantined validation row (E16, AC11) — never dropped without a trace.
"""

from __future__ import annotations

from typing import Sequence

from calc_engine.formulas.component_sum import BearerResolver
from calc_engine.formulas.discount_attribution import (
    seller_funded_discounts,
    unknown_bearer_discount_amount,
)
from calc_engine.formulas.gross_order_value import gross_order_value
from calc_engine.formulas.revenue_reductions import (
    cancellation_reversal,
    return_reversal,
    rto_unrecovered_revenue,
)
from calc_engine.types import (
    ZERO,
    CanonicalLine,
    Confidence,
    MetricValue,
    RecognitionState,
    Unavailable,
    combine_confidence,
)

_CALCULATION_BASIS = (
    "NetRealizedRevenue = GrossOrderValue - SellerFundedDiscounts - CancellationReversal "
    "- ReturnReversal - RTOUnrecoveredRevenue (deterministic-engine.md §5.5)"
)


def net_realized_revenue(
    lines: Sequence[CanonicalLine],
    bearer_resolver: BearerResolver,
    recognition_state: RecognitionState,
) -> MetricValue | Unavailable:
    # AC12, defense-in-depth: this must be true regardless of whether the caller obtained
    # `recognition_state` via recognition.resolve_recognition_state() or some other path — an
    # Amazon line can never be presented as REALIZED (C3: settlement match keys unverified).
    if recognition_state == RecognitionState.REALIZED and any(line.marketplace == "AMAZON" for line in lines):
        raise ValueError(
            "AC12 violation: an AMAZON line was passed with recognition_state=REALIZED — "
            "Amazon must always report RECOGNISED until settlement match keys are validated (C3)"
        )

    included: list[CanonicalLine] = []
    exclusions: list[dict[str, object]] = []

    for line in lines:
        if line.quarantine_rule_ids:
            # E16/AC11: a quarantined row (data-foundation's validation layer, e.g.
            # V-TAX-001) is excluded from every aggregate here, with its rule ids disclosed —
            # never dropped without a trace, and checked before the status fields below since
            # a quarantined row's cancellation/return/RTO fields are not to be trusted anyway.
            exclusions.append(
                {
                    "sales_line_id": str(line.sales_line_id),
                    "rule": "QUARANTINED",
                    "quarantine_rule_ids": line.quarantine_rule_ids,
                }
            )
            continue

        missing = [
            field
            for field, value in (
                ("cancellation_state", line.cancellation_state),
                ("return_status", line.return_status),
                ("rto_status", line.rto_status),
            )
            if value is None
        ]
        if missing:
            exclusions.append(
                {
                    "sales_line_id": str(line.sales_line_id),
                    "rule": "REVENUE_STATUS_UNRESOLVED",
                    "missing_inputs": tuple(missing),
                }
            )
            continue
        included.append(line)

    if not included:
        return Unavailable(
            reason="no line in scope has a resolvable cancellation/return/RTO status",
            missing_inputs=("cancellation_state", "return_status", "rto_status"),
        )

    gov = gross_order_value(included)
    sfd = seller_funded_discounts(included, bearer_resolver)

    total_reversals = ZERO
    for line in included:
        for result in (
            cancellation_reversal(line),
            return_reversal(line),
            rto_unrecovered_revenue(line, bearer_resolver),
        ):
            # Every included line was pre-filtered above to have all three statuses
            # resolvable, so none of these three calls can return Unavailable here —
            # asserted, not assumed, since a silent Unavailable-as-zero would be exactly
            # the bug this module exists to prevent.
            assert not isinstance(result, Unavailable), (
                f"unexpected Unavailable on a pre-filtered line {line.sales_line_id}: {result}"
            )
            total_reversals = total_reversals + result

    value = gov - sfd - total_reversals

    # D2/E13: where any part of SellerFundedDiscounts came from the bearer=UNKNOWN fallback,
    # the resulting figure is flagged DERIVED — it is a conservative default, not a fact read
    # from source data, and must never present at the same confidence as a fully-resolved
    # bearer would.
    unknown_bearer_amount = unknown_bearer_discount_amount(included, bearer_resolver)
    confidence_inputs = [Confidence.PROVISIONAL, *(line.confidence for line in included)]
    if unknown_bearer_amount.value != 0:
        confidence_inputs.append(Confidence.DERIVED)
    confidence = combine_confidence(*confidence_inputs)

    return MetricValue(
        value=value,
        confidence=confidence,
        recognition_state=recognition_state,
        calculation_basis=_CALCULATION_BASIS,
        input_refs=tuple(line.sales_line_id for line in included),
        exclusions=tuple(exclusions),
    )
