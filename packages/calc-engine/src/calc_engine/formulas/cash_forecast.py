"""EXPECTED_RECEIPTS and CASH_SHORTFALL_STATUS — deterministic-engine.md §5.17.1 (10), (11).

Cash is reasoned from settlements only — never a bank balance and never a demand forecast: only lines that were **already sold** and
are still unsettled are projected, each at `document_date + L days`, where `L` is the **lower median** of that marketplace's observed
settlement lags (`sorted[(n − 1) // 2]`, an observed integer, never an interpolation). Overdue expectations (expected before
`as_of`) are reported separately and never count as future cover. Integer paise and dates only; `as_of`, thresholds and samples are
parameters (no clock, no defaults).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from enum import Enum

from calc_engine.formulas.completeness import Completeness
from calc_engine.types import Unavailable


def lower_median(samples: Sequence[int]) -> int:
    if not samples:
        raise ValueError("lower_median of no samples")
    s = sorted(samples)
    return s[(len(s) - 1) // 2]


@dataclass(frozen=True, slots=True)
class UnsettledLine:
    line_id: str
    marketplace: str
    document_date: date
    expected_amount_paise: int | None  # the amount the engine knows is still to be settled; None when unknown


@dataclass(frozen=True, slots=True)
class ReceiptBucket:
    expected_date: date
    total_paise: int
    line_count: int


@dataclass(frozen=True, slots=True)
class ExpectedReceipts:
    as_of: date
    buckets: tuple[ReceiptBucket, ...]  # future (expected_date >= as_of), ascending by date
    overdue_total_paise: int  # expected before as_of and still unsettled: reported, never counted as cover
    overdue_line_count: int
    excluded_no_amount: int
    lag_days_by_marketplace: Mapping[str, int]
    unprojected: Mapping[str, str]  # marketplace -> why none of its lines could be projected
    completeness: Completeness


def expected_receipts(
    lines: Sequence[UnsettledLine], lag_samples: Mapping[str, Sequence[int]], as_of: date, min_samples: int | None
) -> ExpectedReceipts | Unavailable:
    if min_samples is None:
        return Unavailable(reason="CONFIG_MISSING: no minimum number of observed settlement lags is configured", missing_inputs=("min_samples",))
    if min_samples < 1:
        raise ValueError("min_samples must be at least 1")
    if not lines:
        return Unavailable(reason="no unsettled sold lines to project", missing_inputs=("unsettled_lines",))
    for mp, samples in lag_samples.items():
        if any(s < 0 for s in samples):
            raise ValueError(f"negative settlement lag sample for {mp}")

    lag: dict[str, int] = {}
    unprojected: dict[str, str] = {}
    for mp in sorted({ln.marketplace for ln in lines}):
        samples = lag_samples.get(mp, ())
        if len(samples) >= min_samples:
            lag[mp] = lower_median(samples)
        else:
            unprojected[mp] = f"{len(samples)} observed settlement lag(s); at least {min_samples} are required"

    future: dict[date, list[int]] = {}
    overdue_total = overdue_count = no_amount = projected = 0
    for ln in lines:
        if ln.marketplace not in lag:
            continue
        if ln.expected_amount_paise is None:
            no_amount += 1
            continue
        projected += 1
        due = ln.document_date + timedelta(days=lag[ln.marketplace])
        if due < as_of:
            overdue_total += ln.expected_amount_paise
            overdue_count += 1
        else:
            b = future.setdefault(due, [0, 0])
            b[0] += ln.expected_amount_paise
            b[1] += 1
    if projected == 0:
        return Unavailable(reason="no line could be projected: " + ("; ".join(f"{m}: {r}" for m, r in unprojected.items()) or "no line has a known amount"),
                           missing_inputs=("settlement_lag_samples", "expected_amount"))
    partial = bool(unprojected) or no_amount > 0
    return ExpectedReceipts(
        as_of=as_of, buckets=tuple(ReceiptBucket(d, v[0], v[1]) for d, v in sorted(future.items())), overdue_total_paise=overdue_total,
        overdue_line_count=overdue_count, excluded_no_amount=no_amount, lag_days_by_marketplace=lag, unprojected=unprojected,
        completeness=Completeness.PARTIAL if partial else Completeness.COMPLETE,
    )


class ShortfallStatus(str, Enum):
    COVERED = "COVERED"
    AT_RISK = "AT_RISK"
    UNKNOWN = "UNKNOWN"  # no due date: cannot be compared, listed


@dataclass(frozen=True, slots=True)
class Payable:
    payable_id: str
    amount_paise: int
    due_date: date | None


@dataclass(frozen=True, slots=True)
class PayableStatus:
    payable_id: str
    due_date: date | None
    status: ShortfallStatus
    cumulative_payables_paise: int | None  # every payable due on or before this one's date
    cumulative_cover_paise: int | None  # future expected receipts dated on or before this due date (and not before as_of)


def cash_shortfall_status(payables: Sequence[Payable], receipts: ExpectedReceipts | Unavailable) -> tuple[PayableStatus, ...] | Unavailable:
    """COVERED when the future expected receipts up to a payable's due date cover every payable due by then (equality is COVERED);
    otherwise AT_RISK. A payable already past due has no future cover and is AT_RISK. No bank balance is read or assumed."""
    if isinstance(receipts, Unavailable):
        return Unavailable(reason="expected receipts are unavailable: " + receipts.reason, missing_inputs=receipts.missing_inputs)
    for p in payables:
        if p.amount_paise < 0:
            raise ValueError("a payable amount cannot be negative")
    dated = sorted((p for p in payables if p.due_date is not None), key=lambda p: (p.due_date or date.min, p.payable_id))
    undated = sorted((p for p in payables if p.due_date is None), key=lambda p: p.payable_id)

    out: list[PayableStatus] = []
    for p in dated:
        d = p.due_date
        assert d is not None
        due_by = sum(q.amount_paise for q in dated if q.due_date is not None and q.due_date <= d)
        cover = sum(b.total_paise for b in receipts.buckets if receipts.as_of <= b.expected_date <= d)
        out.append(PayableStatus(p.payable_id, d, ShortfallStatus.COVERED if cover >= due_by else ShortfallStatus.AT_RISK, due_by, cover))
    out.extend(PayableStatus(p.payable_id, None, ShortfallStatus.UNKNOWN, None, None) for p in undated)
    return tuple(out)
