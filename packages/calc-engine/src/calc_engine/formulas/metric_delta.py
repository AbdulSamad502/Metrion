"""metric_delta.py — period-over-period delta between two already-computed metric_results.

deterministic-engine.md §9. Purely compositional over `MetricResult`: takes two results for
the SAME metric_code (e.g. CONTRIBUTION_PROFIT for period A and period B) and returns the
signed paise difference, never re-deriving either side from raw lines. This is the one place
in this batch where arithmetic on money happens — `result_b.value_paise - result_a.value_paise`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from calc_engine.types import Unavailable

if TYPE_CHECKING:
    # Deferred: compute_metric.py (which defines MetricResult) imports FROM this module for
    # compute_metric_delta(), so a top-level import here would be circular. TYPE_CHECKING-only
    # import keeps the type hint accurate for static analysis without ever executing at runtime.
    from calc_engine.api.compute_metric import MetricResult


def metric_delta(result_a: "MetricResult", result_b: "MetricResult") -> int | Unavailable:
    """result_b - result_a, in paise. `result_a`/`result_b` are the earlier/later period's
    already-computed MetricResult for the SAME metric_code — comparing two different metrics
    is a caller bug, not missing data, so it raises rather than returning Unavailable.
    """
    if result_a.metric_code != result_b.metric_code:
        raise ValueError(
            f"metric_delta requires both results to share a metric_code, "
            f"got {result_a.metric_code!r} and {result_b.metric_code!r}"
        )

    a_unavailable = not result_a.is_available
    b_unavailable = not result_b.is_available
    if a_unavailable or b_unavailable:
        if a_unavailable and b_unavailable:
            reason = (
                f"both periods unavailable: result_a: {result_a.unavailable_reason}; "
                f"result_b: {result_b.unavailable_reason}"
            )
        elif a_unavailable:
            reason = f"result_a (earlier period) unavailable: {result_a.unavailable_reason}"
        else:
            reason = f"result_b (later period) unavailable: {result_b.unavailable_reason}"
        return Unavailable(reason=reason)

    return result_b.value_paise - result_a.value_paise  # type: ignore[operator]
