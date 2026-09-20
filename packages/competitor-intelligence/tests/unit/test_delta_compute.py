"""compute_price_delta() — the one arithmetic CI is allowed (B8/AC1), no float in the
calculation path, never a fabricated delta when an input is missing."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

from hypothesis import given
from hypothesis import strategies as st

from competitor_intelligence.evidence.snapshot import SnapshotDraft
from competitor_intelligence.delta.compute import (
    STALE_SNAPSHOT_CEILING,
    compute_price_delta,
    effective_price,
    should_emit_price_event,
)
from competitor_intelligence.types import Availability, CaptureStatus, Confidence, Direction, Unavailable

NOW = datetime(2026, 9, 19, tzinfo=timezone.utc)


def _snapshot(
    *,
    captured_at: datetime,
    listed_price_paise: int | None,
    visible_discount_paise: int | None = 0,
    availability: Availability | None = Availability.IN_STOCK,
    capture_status: CaptureStatus = CaptureStatus.COMPLETE,
) -> SnapshotDraft:
    return SnapshotDraft(
        captured_at=captured_at,
        capture_status=capture_status,
        source_url="https://amazon.in/dp/x",
        confidence=Confidence.VISION_EXTRACTED,
        research_session_id=uuid4(),
        listed_price_paise=listed_price_paise,
        visible_discount_paise=visible_discount_paise,
        availability=availability,
    )


def test_effective_price_subtracts_discount() -> None:
    assert effective_price(listed_price_paise=100000, visible_discount_paise=5000) == 95000


def test_effective_price_none_when_no_listed_price() -> None:
    assert effective_price(listed_price_paise=None, visible_discount_paise=5000) is None


def test_effective_price_defaults_missing_discount_to_zero() -> None:
    assert effective_price(listed_price_paise=100000, visible_discount_paise=None) == 100000


def test_price_decrease_breaches_threshold() -> None:
    prior = _snapshot(captured_at=NOW, listed_price_paise=100000)
    current = _snapshot(captured_at=NOW + timedelta(days=1), listed_price_paise=80000)

    delta = compute_price_delta(
        prior=prior, current=current, price_threshold_pct=Decimal("5.00"), now=NOW + timedelta(days=1)
    )

    assert delta.direction == Direction.DECREASE
    assert delta.delta_paise == -20000
    assert delta.delta_pct == Decimal("-20.00")
    assert delta.threshold_breached is True
    assert delta.alert_eligible is True


def test_price_change_below_threshold_not_breached() -> None:
    prior = _snapshot(captured_at=NOW, listed_price_paise=100000)
    current = _snapshot(captured_at=NOW + timedelta(days=1), listed_price_paise=99000)

    delta = compute_price_delta(
        prior=prior, current=current, price_threshold_pct=Decimal("5.00"), now=NOW + timedelta(days=1)
    )

    assert delta.delta_pct == Decimal("-1.00")
    assert delta.threshold_breached is False


def test_availability_transition_breaches_threshold_regardless_of_price() -> None:
    prior = _snapshot(captured_at=NOW, listed_price_paise=100000, availability=Availability.IN_STOCK)
    current = _snapshot(
        captured_at=NOW + timedelta(days=1), listed_price_paise=100000, availability=Availability.OUT_OF_STOCK
    )

    delta = compute_price_delta(
        prior=prior, current=current, price_threshold_pct=Decimal("5.00"), now=NOW + timedelta(days=1)
    )

    assert delta.delta_pct == Decimal("0.00")
    assert delta.threshold_breached is True  # availability change alone breaches (D3)


def test_missing_price_on_either_snapshot_is_unavailable_not_fabricated() -> None:
    prior = _snapshot(captured_at=NOW, listed_price_paise=None)
    current = _snapshot(captured_at=NOW + timedelta(days=1), listed_price_paise=80000)

    result = compute_price_delta(
        prior=prior, current=current, price_threshold_pct=Decimal("5.00"), now=NOW + timedelta(days=1)
    )

    assert isinstance(result, Unavailable)


def test_zero_prior_price_is_unavailable_not_divide_by_zero() -> None:
    prior = _snapshot(captured_at=NOW, listed_price_paise=5000, visible_discount_paise=5000)  # effective 0
    current = _snapshot(captured_at=NOW + timedelta(days=1), listed_price_paise=80000)

    result = compute_price_delta(
        prior=prior, current=current, price_threshold_pct=Decimal("5.00"), now=NOW + timedelta(days=1)
    )

    assert isinstance(result, Unavailable)


def test_pending_manual_entry_snapshot_is_unavailable() -> None:
    prior = _snapshot(
        captured_at=NOW, listed_price_paise=100000, capture_status=CaptureStatus.PENDING_MANUAL_ENTRY
    )
    current = _snapshot(captured_at=NOW + timedelta(days=1), listed_price_paise=80000)

    result = compute_price_delta(
        prior=prior, current=current, price_threshold_pct=Decimal("5.00"), now=NOW + timedelta(days=1)
    )

    assert isinstance(result, Unavailable)


def test_partial_snapshot_with_resolved_price_is_still_comparable() -> None:
    """§6.3 rule 1: a PARTIAL prior snapshot (some non-price field unresolved) is still
    comparable for the fields it does have — this is a deliberate relaxation from the old
    OK-only gate."""
    prior = _snapshot(captured_at=NOW, listed_price_paise=100000, capture_status=CaptureStatus.PARTIAL)
    current = _snapshot(
        captured_at=NOW + timedelta(days=1), listed_price_paise=80000, capture_status=CaptureStatus.PARTIAL
    )

    result = compute_price_delta(
        prior=prior, current=current, price_threshold_pct=Decimal("5.00"), now=NOW + timedelta(days=1)
    )

    assert not isinstance(result, Unavailable)
    assert result.delta_paise == -20000


def test_stale_prior_snapshot_is_not_alert_eligible() -> None:
    """OP3 (locked): a snapshot past the 7-day ceiling is stale — report unavailable rather
    than mislead. alert_eligible=False is how that surfaces here; the delta itself is still
    computed (it isn't Unavailable), but a caller must not alert on it."""
    prior = _snapshot(captured_at=NOW, listed_price_paise=100000)
    later = NOW + STALE_SNAPSHOT_CEILING + timedelta(days=1)
    current = _snapshot(captured_at=later, listed_price_paise=80000)

    delta = compute_price_delta(prior=prior, current=current, price_threshold_pct=Decimal("5.00"), now=later)

    assert delta.alert_eligible is False


def test_availability_override_off_suppresses_threshold_breach() -> None:
    """Per-URL alert_on_availability_change_override=False (§5, D2/Q5): the availability
    change is still recorded (availability_change is not None), but it no longer breaches
    the alert threshold on its own — the caller resolves this override and passes it in."""
    prior = _snapshot(captured_at=NOW, listed_price_paise=100000, availability=Availability.IN_STOCK)
    current = _snapshot(
        captured_at=NOW + timedelta(days=1), listed_price_paise=100000, availability=Availability.OUT_OF_STOCK
    )

    delta = compute_price_delta(
        prior=prior,
        current=current,
        price_threshold_pct=Decimal("5.00"),
        now=NOW + timedelta(days=1),
        alert_on_availability_change=False,
    )

    assert delta.availability_change is not None
    assert delta.threshold_breached is False


def test_should_emit_event_false_for_no_change() -> None:
    prior = _snapshot(captured_at=NOW, listed_price_paise=100000)
    current = _snapshot(captured_at=NOW + timedelta(days=1), listed_price_paise=100000)

    delta = compute_price_delta(
        prior=prior, current=current, price_threshold_pct=Decimal("5.00"), now=NOW + timedelta(days=1)
    )

    assert delta.delta_paise == 0
    assert should_emit_price_event(delta) is False


@given(
    prior_price=st.integers(min_value=1, max_value=10_000_000),
    delta=st.integers(min_value=-10_000_000, max_value=10_000_000),
)
def test_delta_pct_sign_never_flips_relative_to_delta_paise_sign(prior_price: int, delta: int) -> None:
    """Property: delta_pct's sign never CONTRADICTS delta_paise's sign — a positive
    delta_paise never produces a negative delta_pct or vice versa. It can round to exactly
    0.00 at the 2dp scale (e.g. +1 paise on a ~20,000 paise base) without that being a bug —
    numeric(6,2) is the column's actual precision, so this is a real boundary, not a rounding
    defect. What Fraction-based arithmetic rules out is a SIGN FLIP, not a rounding-to-zero;
    this property checks exactly that, not strict positivity/negativity."""
    current_price = prior_price + delta
    prior = _snapshot(captured_at=NOW, listed_price_paise=prior_price)
    current = _snapshot(captured_at=NOW + timedelta(days=1), listed_price_paise=max(current_price, 0))

    result = compute_price_delta(
        prior=prior, current=current, price_threshold_pct=Decimal("5.00"), now=NOW + timedelta(days=1)
    )

    if isinstance(result, Unavailable):
        return
    if result.delta_paise > 0:
        assert result.delta_pct >= 0
    elif result.delta_paise < 0:
        assert result.delta_pct <= 0
    else:
        assert result.delta_pct == 0
