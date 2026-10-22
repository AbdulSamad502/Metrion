"""Hypothetical P&L scenario (docs/specs/calculator.md §14): pure, stateless, no I/O, no tenant context, no persistence.

Not a `metric_result` and never an `engine_result_ref`: the output of this package is an ESTIMATE over seller-typed inputs. The reference
semantics are the hand-checked fixtures of the public calculator (Metrion-P-L-website `docs/CALCULATION.md`), reproduced in
`tests/unit/test_pnl_scenario.py`.
"""

from calc_engine.formulas.pnl_scenario.calculate import calculate_scenario, make_view
from calc_engine.formulas.pnl_scenario.fields import MARKETPLACE_FIELDS, FeeFieldDef, active_fields
from calc_engine.formulas.pnl_scenario.solve import solve_price
from calc_engine.formulas.pnl_scenario.types import (
    EMPTY,
    NA,
    Assumption,
    Band,
    Breakdown,
    Entry,
    FeeAmount,
    FeeInput,
    Issue,
    Line,
    LineShare,
    Metrics,
    OrderCounts,
    PriceRange,
    Recovery,
    ScenarioInputs,
    ScenarioResult,
    Segment,
    SolveResult,
    SolveTarget,
    View,
    invalid,
    set_,
)

__all__ = [
    "EMPTY", "NA", "Assumption", "Band", "Breakdown", "LineShare", "Segment", "Entry", "FeeAmount", "FeeFieldDef", "FeeInput", "Issue", "Line", "MARKETPLACE_FIELDS", "Metrics",
    "OrderCounts", "PriceRange", "Recovery", "ScenarioInputs", "ScenarioResult", "SolveResult", "SolveTarget", "View", "active_fields",
    "calculate_scenario", "invalid", "make_view", "set_", "solve_price",
]
