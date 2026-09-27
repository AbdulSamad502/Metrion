"""Leak Shield arithmetic — deterministic-engine.md §5.12, §5.12.1; data-foundation.md §5.

Brain 1 owns this arithmetic, never Brain 3 (§5.12): "Ranking is not judgement... it is
computed deterministically in Brain 1." This module computes the per-component leak signal,
classifies its outcome against configured tolerance/lag, and sums exception amounts —
`leak_aggregate` exists specifically so "agents never sum leak amounts themselves" (§5.13.1)
has one place to be true.

Scope note (corrected — data-foundation.md §5.7, CONFIRMED Phase C, C2): `reconciliation_run`,
`reconciliation_match` and `reconciliation_exception` are **calc-engine-owned** tables — they
are `reconcile()`'s own computed OUTPUT, not raw data-foundation facts, the same precedent as
`metric_result`/`manual_adjustment`. Their DDL will live in this package's own migrations, once
written (not yet done — no migration for them exists in this package yet either). `settlement_line`
and `settlement_document`, by contrast, *are* data-foundation-owned raw ingested facts, mirroring
`sales_line`/`line_component`'s layer (§5.7). This module is therefore pure-formula, operating on
already-fetched invoice/settlement amounts, dates and candidate-row dicts (from
`repositories/settlement_repo.py`/`canonical_repo.py`) — the same pattern as those repositories:
structurally complete, unit-tested against constructed inputs, and explicitly not
integration-tested against a real `reconciliation_match`/`settlement_line` row until both
migrations (calc-engine's own `reconciliation_*` tables, and data-foundation's `settlement_line`)
exist.

Leak *category* assignment (`FEE_OVERCHARGE`, `SHORT_SETTLEMENT`, ... — data-foundation.md
§5.3) is deliberately NOT implemented here: the spec defines the category enum but never a
rule for assigning one to an outcome, and inventing that mapping would be exactly the kind of
plausible-sounding-but-unconfirmed logic this project's rules prohibit. `classify_variance`
below returns an `outcome`, not a `category` — assigning a category is future work gated on a
spec amendment, same treatment as `cash_reconciliation` (C14).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Any, cast

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


@dataclass(frozen=True)
class NoCandidate:
    """Zero `sales_line` candidates resolved for a settlement row's join key. Not itself
    `ORPHAN_SETTLEMENT` — data-foundation.md §5.8 Path A step 3 (orphan/match check) is the
    caller's job, this type only reports "there was nothing to classify against"."""


@dataclass(frozen=True)
class SingleMatch:
    """Exactly one `sales_line` candidate resolved — the only case eligible to proceed to
    duplicate detection (`is_duplicate_settlement`) and then `classify_variance`
    (data-foundation.md §5.8 Path A, steps 2-4)."""

    candidate: dict[str, Any]


@dataclass(frozen=True)
class Collision:
    """More than one `sales_line` candidate resolved for the same join key — data-foundation.md
    §5.2, CONFIRMED Phase C, C3: "not an eighth `ReconciliationOutcome` value... its own explicit
    ambiguous/quarantined match state." Matching stops here; none of `classify_variance`,
    `classify_settlement_lag` or `is_duplicate_settlement` ever run against these candidates."""

    candidates: tuple[dict[str, Any], ...]


def resolve_match_candidates(candidates: list[dict[str, Any]]) -> "NoCandidate | SingleMatch | Collision":
    """data-foundation.md §5.8 Path A, step 1 (collision check, §5.2 C3): given the list of
    `sales_line` candidate dicts a settlement row's join key resolved to (already fetched by the
    caller — this function does no DB access, pure formula, same pattern as everything else in
    this module), return an explicit tagged result rather than a plain list.

    Design choice: a plain `list[dict]` return would force every caller to re-derive the
    zero/one/many distinction by checking `len(...)`, which is exactly the kind of silent
    inference §5.2's C3 decision rules out for the collision case specifically ("never
    auto-resolved to a 'best guess' single match... never silently inferred downstream"). Three
    small frozen dataclasses make all three states — no candidate, one candidate, more than one
    candidate — equally explicit and force a caller (a future `reconcile()`) to handle each one
    by construction (e.g. via `isinstance` or `match`), rather than only guarding the collision
    case and treating "empty" and "single" as interchangeably fine. `NoCandidate` and
    `SingleMatch` are not new `ReconciliationOutcome` values either, for the same reason
    `Collision` isn't (§5.2): resolving candidates is the matching step, prior to and separate
    from outcome classification."""
    if len(candidates) == 0:
        return NoCandidate()
    if len(candidates) == 1:
        return SingleMatch(candidate=candidates[0])
    return Collision(candidates=tuple(candidates))


def is_duplicate_settlement(candidate: dict[str, Any], already_processed: list[dict[str, Any]]) -> bool:
    """data-foundation.md §5.2, CONFIRMED Phase C, C4: `True` only when `already_processed`
    contains a row matching `candidate` on ALL THREE of (1) the same join key — here,
    `(order_ref, line_ref)`, mirroring `settlement_repo.py`'s `settlement_line` column names
    exactly (§5.6) — (2) the same `gross_settlement_amount`, and (3) the same `settlement_date`.
    Deliberately the most conservative rule available (§5.2): a genuine second, distinct charge
    on a different date against the same order/line is never wrongly flagged as a duplicate.

    Pure function, plain dicts in (the same `settlement_line` row shape `settlement_repo.py`
    returns), no DB access. `already_processed` is the caller's accumulated list of settlement
    rows already evaluated in this `reconcile()` run (data-foundation.md §5.8 Path A step 2:
    "check whether another already-processed settlement row shares the same join key, amount and
    settlement date") — building and maintaining that list is the caller's job, not this
    function's.

    **`None`-amount hardening (data-foundation.md §5.1.5 point 4, deterministic-engine.md §5.2
    amendment).** `gross_settlement_amount` is `None` on every real Amazon settlement row
    today (§5.1.4's structural gap — `amazon.settlement.v2` never populates it). Two `None`s
    compare equal in Python; unmodified, this function would wrongly flag any two same-join-key,
    same-`settlement_date` Amazon rows as `DUPLICATE_SETTLEMENT`. An unavailable amount is never
    "the same amount" as another unavailable amount, so this returns `False` unconditionally
    whenever the candidate's own `gross_settlement_amount` is `None` — checked BEFORE the
    amount-equality comparison, not as a post-hoc filter. Flipkart (real amounts) and Meesho
    (real amounts) are unaffected; this is currently only reachable for Amazon."""
    if candidate["gross_settlement_amount"] is None:
        return False
    candidate_key = (candidate["order_ref"], candidate["line_ref"])
    candidate_amount = candidate["gross_settlement_amount"]
    candidate_date = candidate["settlement_date"]
    for processed in already_processed:
        processed_key = (processed["order_ref"], processed["line_ref"])
        if (
            processed_key == candidate_key
            and processed["gross_settlement_amount"] == candidate_amount
            and processed["settlement_date"] == candidate_date
        ):
            return True
    return False


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
