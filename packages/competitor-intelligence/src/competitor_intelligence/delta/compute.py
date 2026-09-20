"""The only arithmetic this package is allowed to do: a price/availability delta between two
of CI's OWN observed snapshots (front matter B8, AC1 — "CI may compute deltas over its own
observed facts... CI may never compute anything financial: no margin, fee, profit, tax or
cost figure"). A delta between two observed prices is not a financial calculation — it
derives no margin, fee, profit, tax, or cost — but the two inputs are money fields, so the
same "no float in any calculation path" hard rule applies here as it would in Brain 1: this
module uses `Fraction`, never `float`, for the percentage.

D2/D3 (readiness review): price-change detection basis is snapshot-to-snapshot delta;
default threshold ±5% (`ci_tenant_config.price_threshold_pct`); availability transition is a
second, independent threshold trigger.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction

from competitor_intelligence.evidence.snapshot import SnapshotDraft
from competitor_intelligence.types import (
    Availability,
    AvailabilityChange,
    CaptureStatus,
    Direction,
    Paise,
    Unavailable,
)

# OP3 (locked): a snapshot older than this ceiling must not be treated as current for
# alerting purposes — "report unavailable rather than mislead".
STALE_SNAPSHOT_CEILING = timedelta(days=7)


@dataclass(frozen=True, slots=True)
class PriceDelta:
    delta_paise: Paise
    delta_pct: Decimal
    direction: Direction
    availability_change: AvailabilityChange | None
    threshold_breached: bool
    observed_span: timedelta
    alert_eligible: bool


def effective_price(*, listed_price_paise: Paise | None, visible_discount_paise: Paise | None) -> Paise | None:
    """§6.3: effective selling price = listed price less visible discount. None (not zero)
    when the listed price itself was never observed."""
    if listed_price_paise is None:
        return None
    return listed_price_paise - (visible_discount_paise or 0)


def _availability_change(prior: Availability | None, current: Availability | None) -> AvailabilityChange | None:
    if prior == Availability.IN_STOCK and current == Availability.OUT_OF_STOCK:
        return AvailabilityChange.IN_TO_OUT
    if prior == Availability.OUT_OF_STOCK and current == Availability.IN_STOCK:
        return AvailabilityChange.OUT_TO_IN
    return None


def is_stale(snapshot_captured_at: datetime, *, now: datetime) -> bool:
    """Public per OP3 — also used directly by API/UI code to render a staleness badge
    without duplicating the >7-day rule (§6.8)."""
    return (now - snapshot_captured_at) > STALE_SNAPSHOT_CEILING


def compute_price_delta(
    *,
    prior: SnapshotDraft,
    current: SnapshotDraft,
    price_threshold_pct: Decimal,
    now: datetime,
    alert_on_availability_change: bool = True,
) -> PriceDelta | Unavailable:
    """Compares `current` against the most recent prior COMPLETE-or-PARTIAL snapshot for the
    same (competitor_url_id, variant_key) — that lookup is the caller's job (repositories);
    this function only ever compares the two drafts it's given. §6.3 rule 1 permits comparing
    against a PARTIAL prior snapshot too, "for fields it does have" — the actual gate here is
    per-field (the None-checks below), not the whole-snapshot status; the status check only
    excludes PENDING_MANUAL_ENTRY, since a snapshot pending the seller's own resolution has no
    business feeding an alert yet regardless of what any individual field looks like.

    Returns Unavailable, never a fabricated delta, when either snapshot is pending manual
    entry, when the price field itself wasn't resolved on either side, or when the prior
    effective price is zero (a percentage change from zero is undefined, not infinite and not
    zero).
    """
    if (
        prior.capture_status == CaptureStatus.PENDING_MANUAL_ENTRY
        or current.capture_status == CaptureStatus.PENDING_MANUAL_ENTRY
    ):
        return Unavailable(reason="one or both snapshots are still pending manual entry")

    prior_price = effective_price(
        listed_price_paise=prior.listed_price_paise, visible_discount_paise=prior.visible_discount_paise
    )
    current_price = effective_price(
        listed_price_paise=current.listed_price_paise, visible_discount_paise=current.visible_discount_paise
    )
    if prior_price is None or current_price is None:
        return Unavailable(reason="listed price not observed on one or both snapshots")
    if prior_price == 0:
        return Unavailable(reason="prior effective price is zero — percentage change is undefined")

    delta_paise = current_price - prior_price
    delta_fraction = Fraction(delta_paise * 100, prior_price)
    delta_pct = Decimal(delta_fraction.numerator) / Decimal(delta_fraction.denominator)
    delta_pct = delta_pct.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    direction = Direction.INCREASE if delta_paise > 0 else Direction.DECREASE
    availability_change = _availability_change(prior.availability, current.availability)
    threshold_breached = abs(delta_pct) >= price_threshold_pct or (
        availability_change is not None and alert_on_availability_change
    )

    observed_span = current.captured_at - prior.captured_at
    alert_eligible = not (is_stale(prior.captured_at, now=now) or is_stale(current.captured_at, now=now))

    return PriceDelta(
        delta_paise=delta_paise,
        delta_pct=delta_pct,
        direction=direction,
        availability_change=availability_change,
        threshold_breached=threshold_breached,
        observed_span=observed_span,
        alert_eligible=alert_eligible,
    )


def should_emit_price_event(delta: PriceDelta) -> bool:
    """`competitor_price_event.direction` has no NEUTRAL value in the spec (§5) — a
    zero-delta, no-availability-change comparison is not "a price change" and this package
    does not fabricate a direction label for it. Design call, not a spec requirement: only
    emit an event when something actually changed."""
    return delta.delta_paise != 0 or delta.availability_change is not None
