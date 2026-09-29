"""line_status_overrides.py — deterministic-engine.md §7.2.1's `cancellation_state_override` /
`return_status_override` / `rto_status_override`, added this session to close the CFO
end-to-end evaluation's headline finding (real MTR files with no resolvable
cancellation/return/RTO status at all).

Covers `resolve_line_status`'s entire precedence rule: observed wins whenever it is not
`None` (including a "resolved, not cancelled/returned/RTO'd" value), override fills the gap
only when observed is genuinely `None`, and both `None` stays `None`.
"""

from __future__ import annotations

from calc_engine.formulas.line_status_overrides import resolve_line_count, resolve_line_status


def test_observed_value_wins_over_override():
    assert resolve_line_status("CANCELLED", "NOT_CANCELLED") == "CANCELLED"


def test_observed_resolved_not_cancelled_value_still_wins_over_override():
    # A marketplace report resolving to "not cancelled" is real, resolved data — never
    # silently overruled by a seller's override, even one saying the opposite.
    assert resolve_line_status("DELIVERED", "CANCELLED") == "DELIVERED"


def test_override_fills_the_gap_when_observed_is_none():
    assert resolve_line_status(None, "RTO") == "RTO"


def test_none_and_none_stays_none():
    assert resolve_line_status(None, None) is None


def test_observed_present_and_no_override_returns_observed():
    assert resolve_line_status("RETURNED", None) == "RETURNED"


# --- resolve_line_count (returned_qty_override / rto_qty_override) -------------------------


def test_observed_count_wins_over_override_count():
    assert resolve_line_count(3, 5) == 3


def test_observed_zero_is_a_real_count_not_treated_as_missing():
    assert resolve_line_count(0, 5) == 0


def test_override_count_fills_the_gap_when_observed_is_none():
    assert resolve_line_count(None, 2) == 2


def test_both_none_stays_none_never_defaulted_to_zero():
    assert resolve_line_count(None, None) is None
