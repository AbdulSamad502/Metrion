"""Base-versus-what-if comparison of two scenario results (docs/specs/calculator.md §14; the public calculator's "What if...?" panel).

A difference between two money results is money arithmetic, so it is made here and not in the browser. Pure integer subtraction of paise and of basis points:
a change is `None` (not available) when either side has no figure for it; a missing figure is never read as zero. Both inputs are hypothetical estimates, and so is the
comparison: it is never a metric result.
"""

from __future__ import annotations

from dataclasses import dataclass

from calc_engine.formulas.pnl_scenario.types import ScenarioResult, View
from calc_engine.types import Paise


@dataclass(frozen=True, slots=True)
class Comparison:
    per_kept_change: Paise | None  # what-if minus base, contribution profit per order kept
    per_placed_change: Paise | None
    monthly_change: Paise | None
    margin_change_bps: int | None  # what-if minus base, contribution margin on revenue


def _change(base: View | None, what_if: View | None) -> Paise | None:
    if base is None or what_if is None:
        return None
    return Paise(what_if.contribution.value - base.contribution.value)


def compare_results(base: ScenarioResult, what_if: ScenarioResult) -> Comparison:
    b, w = base.metrics, what_if.metrics
    margin = None if b is None or w is None or b.contribution_margin_bps is None or w.contribution_margin_bps is None else w.contribution_margin_bps - b.contribution_margin_bps
    return Comparison(_change(base.per_kept, what_if.per_kept), _change(base.per_placed, what_if.per_placed), _change(base.monthly, what_if.monthly), margin)
