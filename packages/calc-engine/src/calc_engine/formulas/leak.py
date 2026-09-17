"""Leak Shield arithmetic — deterministic-engine.md §5.12, §5.12.1; data-foundation.md §5.

Brain 1 owns this arithmetic, never Brain 3 (§5.12): "Ranking is not judgement... it is
computed deterministically in Brain 1." This module computes the per-component leak signal,
classifies its outcome against configured tolerance/lag, and sums exception amounts —
`leak_aggregate` exists specifically so "agents never sum leak amounts themselves" (§5.13.1)
has one place to be true.

Scope note: `reconciliation_match`/`reconciliation_exception` are data-foundation-owned
tables (its table-ownership tree lists them, mirroring `sales_line`/`line_component`) that do
not exist in any migration yet. This module is therefore pure-formula, operating on
already-fetched invoice/settlement amounts and dates — the same pattern as
`repositories/canonical_repo.py`: structurally complete, unit-tested against constructed
inputs, and explicitly not integration-tested against a real reconciliation_match row until
data-foundation's own migration exists.

Leak *category* assignment (`FEE_OVERCHARGE`, `SHORT_SETTLEMENT`, ... — data-foundation.md
§5.3) is deliberately NOT implemented here: the spec defines the category enum but never a
rule for assigning one to an outcome, and inventing that mapping would be exactly the kind of
plausible-sounding-but-unconfirmed logic this project's rules prohibit. `classify_variance`
below returns an `outcome`, not a `category` — assigning a category is future work gated on a
spec amendment, same treatment as `cash_reconciliation` (C14).
"""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import cast

from calc_engine.types import Paise, Unavailable

_BPS_DENOMINATOR = 10_000


class ReconciliationOutcome(str, Enum):
    MATCHED_EXACT = "MATCHED_EXACT"
    MATCHED_WITHIN_TOLERANCE = "MATCHED_WITHIN_TOLERANCE"
    VARIANCE_EXCEEDS_TOLERANCE = "VARIANCE_EXCEEDS_TOLERANCE"
    UNSETTLED_WITHIN_LAG = "UNSETTLED_WITHIN_LAG"
    UNSETTLED_BEYOND_LAG = "UNSETTLED_BEYOND_LAG"
    ORPHAN_SETTLEMENT = "ORPHAN_SETTLEMENT"
    DUPLICATE_SETTLEMENT = "DUPLICATE_SETTLEMENT"


def leak_amount(invoice_amount: Paise, settlement_amount: Paise) -> Paise:
    """data-foundation.md §5.4: leak_amount = Σ component[SETTLEMENT] − Σ component[INVOICE],
    per component_code, per line. Positive = settlement paid more than invoiced (an
    overcharge signal on a fee, say); negative = settlement paid less (a short-settlement
    signal on revenue). The sign is never normalised away — it is the leak's direction."""
    return settlement_amount - invoice_amount


def is_within_tolerance(
    variance: Paise, invoice_amount: Paise, *, tolerance_paise: Paise, tolerance_bps: int
) -> bool:
    """§5.12.1, confirmed: a variance is within tolerance if it satisfies EITHER the flat
    paise tolerance OR the basis-points tolerance computed against the invoice-side amount —
    not both. Comparison is on magnitude: a variance's sign indicates direction, not size."""
    magnitude = abs(variance)
    if magnitude <= abs(tolerance_paise):
        return True
    bps_amount = Paise((abs(invoice_amount.value) * tolerance_bps) // _BPS_DENOMINATOR)
    return magnitude <= bps_amount


def classify_variance(
    invoice_amount: Paise,
    settlement_amount: Paise,
    *,
    tolerance_paise: Paise,
    tolerance_bps: int,
) -> ReconciliationOutcome:
    """§5.2: MATCHED_EXACT (zero variance) / MATCHED_WITHIN_TOLERANCE / VARIANCE_EXCEEDS_TOLERANCE.
    Requires both sides to already be known present (settlement exists, matched to this
    invoice line) — orphan/duplicate/unsettled cases are classified by the other functions in
    this module, which run before this one is ever reached for a given line."""
    variance = leak_amount(invoice_amount, settlement_amount)
    if variance.value == 0:
        return ReconciliationOutcome.MATCHED_EXACT
    if is_within_tolerance(variance, invoice_amount, tolerance_paise=tolerance_paise, tolerance_bps=tolerance_bps):
        return ReconciliationOutcome.MATCHED_WITHIN_TOLERANCE
    return ReconciliationOutcome.VARIANCE_EXCEEDS_TOLERANCE


def classify_settlement_lag(
    *, document_date: date, as_of_date: date, settlement_lag_days: int
) -> ReconciliationOutcome:
    """§5.2/§5.12.1: for an invoiced line with no matching settlement yet. UNSETTLED_WITHIN_LAG
    while still inside the configured lag; UNSETTLED_BEYOND_LAG once it's crossed. This
    outcome alone does not mean the line should be reported as a leak yet — see
    `should_report_unsettled_as_leak` for the grace-period gate on top of it (§5.12.1)."""
    elapsed_days = (as_of_date - document_date).days
    if elapsed_days <= settlement_lag_days:
        return ReconciliationOutcome.UNSETTLED_WITHIN_LAG
    return ReconciliationOutcome.UNSETTLED_BEYOND_LAG


def should_report_unsettled_as_leak(
    *, document_date: date, as_of_date: date, settlement_lag_days: int, grace_period_days: int
) -> bool:
    """§5.12.1, confirmed: the grace period is a reporting buffer on top of the lag threshold,
    not a second lag — a line is only surfaced as a reportable leak exception once elapsed
    time exceeds settlement_lag_days + grace_period_days, even though its reconciliation
    outcome already reads UNSETTLED_BEYOND_LAG before that point."""
    elapsed_days = (as_of_date - document_date).days
    return elapsed_days > settlement_lag_days + grace_period_days


def leak_aggregate(exception_amounts: "list[Paise] | tuple[Paise, ...]") -> Paise:
    """§5.13.1: leak_aggregate sums reconciliation exception amounts — the one place this
    happens, so "agents never sum leak amounts themselves" is mechanically true rather than a
    convention someone could violate."""
    total = Paise(0)
    for amount in exception_amounts:
        total = total + amount
    return total


def resolve_tolerance_or_unavailable(
    tolerance_row: dict[str, object] | None,
) -> tuple[Paise, int] | Unavailable:
    """§5.12.1: a missing tolerance config row is never treated as zero tolerance (which
    would over-report leaks) or infinite tolerance (which would hide them) — it makes the
    line's reconciliation outcome UNAVAILABLE. `tolerance_row` is whatever
    config_repo.resolve_reconciliation_tolerance() returned (None on a miss)."""
    if tolerance_row is None:
        return Unavailable(
            reason="no reconciliation_tolerance_config row covers this (marketplace, component_code)",
            missing_inputs=("reconciliation_tolerance_config",),
        )
    tolerance_paise = cast(int, tolerance_row["tolerance_paise"])
    tolerance_bps = cast(int, tolerance_row["tolerance_bps"])
    return Paise(tolerance_paise), tolerance_bps
