"""The closed, versioned catalog the planner may select from (cfo-query-planner.md §5.1).

Code-owned, not seller-editable, not model-editable. A plan identifier that is not in this module
is rejected by the validator — never "best matched". Adding a metric here requires its formula in
`deterministic-engine.md` (§5.17 for the CFO 2.0 metrics) and an oracle test, in the same change.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum


class MetricKind(str, Enum):
    ENGINE_FORMULA = "ENGINE_FORMULA"  # computed by a calc_engine function
    SET_SUM = "SET_SUM"
    SET_COUNT = "SET_COUNT"
    SET_DISTINCT_COUNT = "SET_DISTINCT_COUNT"
    SET_WEIGHTED_AVG = "SET_WEIGHTED_AVG"
    RATIO = "RATIO"
    COMPOSITE = "COMPOSITE"  # e.g. PROFIT_BRIDGE: several engine results combined by an engine formula


class Grain(int, Enum):
    """Finest grain first (deterministic-engine.md §6). A metric defined at grain G can be reported at
    G or any coarser grain; reporting finer than G is a grain violation (V-GRN-1)."""

    LINE = 0
    ORDER = 1
    SKU = 2
    MARKETPLACE = 3
    ACCOUNT = 4


class Basis(str, Enum):
    DOCUMENT_DATE = "DOCUMENT_DATE"
    SETTLEMENT_DATE = "SETTLEMENT_DATE"
    EXPENSE_DATE = "EXPENSE_DATE"


class Unit(str, Enum):
    PAISE = "PAISE"
    COUNT = "COUNT"
    PERCENT_FRACTION = "PERCENT_FRACTION"
    DAYS = "DAYS"


@dataclass(frozen=True, slots=True)
class MetricDef:
    id: str
    kind: MetricKind
    engine_ref: str | None  # the calc_engine callable the fast path must equal (oracle target)
    grain: Grain
    allowed_dimensions: frozenset[str]
    required_inputs: tuple[str, ...]  # absent -> UNAVAILABLE + data request
    basis: Basis
    unit: Unit
    is_pnl_metric: bool  # True: must never include TCS/TDS, owner drawings, purchases, capital, transfers (V-ACC-4)
    additive: bool  # Σ per-marketplace must equal the consolidated figure exactly (V-ACC-2)
    allocatable: bool  # an account-level pool may be reported at a finer grain via engine §5.10 (DERIVED)
    explainable_by: tuple[str, ...] = ()
    formula_version: str = "v1"
    is_new: bool = False  # defined by cfo-unified-financials.md / deterministic-engine.md §5.17 (not yet built)


@dataclass(frozen=True, slots=True)
class DimensionDef:
    id: str
    source_table: str
    column: str
    grain: Grain


@dataclass(frozen=True, slots=True)
class JoinDef:
    id: str
    left: str
    right: str
    key_columns: tuple[str, ...]
    cardinality: str  # ONE_TO_ONE | MANY_TO_ONE | ONE_TO_MANY
    uniqueness_side: str  # which side must be unique on the key ("left" | "right")
    control_total_column: str  # the column whose sum must tie out across the join
    validated: bool  # False until a real export has validated the key (Amazon/Flipkart settlement joins)


# --- Dimensions ------------------------------------------------------------------------------------
DIMENSIONS: dict[str, DimensionDef] = {
    d.id: d
    for d in (
        DimensionDef("marketplace", "sales_line", "marketplace", Grain.MARKETPLACE),
        DimensionDef("sku", "sales_line", "sku", Grain.SKU),
        DimensionDef("period", "sales_line", "document_date", Grain.LINE),  # granularity set by the group_by step
        DimensionDef("component_code", "line_component", "component_code", Grain.LINE),
        DimensionDef("expense_category", "manual_adjustment", "field", Grain.ACCOUNT),
        DimensionDef("expense_class", "expense_class_map", "class", Grain.ACCOUNT),
        DimensionDef("return_reason", "sales_line", "return_status", Grain.LINE),
    )
}

_ALL_COMMON = frozenset({"marketplace", "sku", "period"})
_MKT_PERIOD = frozenset({"marketplace", "period"})
_ACCOUNT_ONLY = frozenset({"period"})

_P = Unit.PAISE


def _m(**kw: object) -> MetricDef:
    return MetricDef(**kw)  # type: ignore[arg-type]


# --- Metrics ---------------------------------------------------------------------------------------
METRICS: dict[str, MetricDef] = {
    m.id: m
    for m in (
        _m(id="GROSS_SALES", kind=MetricKind.ENGINE_FORMULA, engine_ref="gross_sales", grain=Grain.LINE,
           allowed_dimensions=_ALL_COMMON, required_inputs=("sales_lines",), basis=Basis.DOCUMENT_DATE, unit=_P,
           is_pnl_metric=True, additive=True, allocatable=False),
        _m(id="NET_REALIZED_REVENUE", kind=MetricKind.ENGINE_FORMULA, engine_ref="net_realized_revenue", grain=Grain.LINE,
           allowed_dimensions=_ALL_COMMON, required_inputs=("sales_lines", "cancellation_state", "return_status", "rto_status"),
           basis=Basis.DOCUMENT_DATE, unit=_P, is_pnl_metric=True, additive=True, allocatable=False),
        _m(id="MARKETPLACE_FEES", kind=MetricKind.ENGINE_FORMULA, engine_ref="marketplace_fees", grain=Grain.LINE,
           allowed_dimensions=_ALL_COMMON | {"component_code"}, required_inputs=("sales_lines", "fee_components"),
           basis=Basis.DOCUMENT_DATE, unit=_P, is_pnl_metric=True, additive=True, allocatable=False),
        _m(id="FEE_RATIO_PCT", kind=MetricKind.RATIO, engine_ref="compute_fee_ratio_pct", grain=Grain.LINE,
           allowed_dimensions=_ALL_COMMON, required_inputs=("sales_lines", "fee_components"),
           basis=Basis.DOCUMENT_DATE, unit=Unit.PERCENT_FRACTION, is_pnl_metric=True, additive=False, allocatable=False),
        _m(id="RETURN_RATE_PCT", kind=MetricKind.RATIO, engine_ref="return_rate_pct", grain=Grain.LINE,
           allowed_dimensions=_ALL_COMMON | {"return_reason"}, required_inputs=("sales_lines", "return_status"),
           basis=Basis.DOCUMENT_DATE, unit=Unit.PERCENT_FRACTION, is_pnl_metric=True, additive=False, allocatable=False),
        _m(id="RETURN_RTO_LOSSES", kind=MetricKind.ENGINE_FORMULA, engine_ref="return_rto_losses", grain=Grain.LINE,
           allowed_dimensions=_ALL_COMMON, required_inputs=("sales_lines", "return_status", "rto_status", "rto_outcome"),
           basis=Basis.DOCUMENT_DATE, unit=_P, is_pnl_metric=True, additive=True, allocatable=False),
        _m(id="CONTRIBUTION_PROFIT", kind=MetricKind.ENGINE_FORMULA, engine_ref="contribution_profit", grain=Grain.LINE,
           allowed_dimensions=_ALL_COMMON,
           required_inputs=("sales_lines", "cogs_per_unit", "cancellation_state", "return_status", "rto_status"),
           basis=Basis.DOCUMENT_DATE, unit=_P, is_pnl_metric=True, additive=True, allocatable=False,
           explainable_by=("NET_REALIZED_REVENUE", "MARKETPLACE_FEES", "RETURN_RTO_LOSSES")),
        _m(id="CONTRIBUTION_MARGIN_PCT", kind=MetricKind.RATIO, engine_ref="contribution_margin_pct", grain=Grain.LINE,
           allowed_dimensions=_ALL_COMMON,
           required_inputs=("sales_lines", "cogs_per_unit", "cancellation_state", "return_status", "rto_status"),
           basis=Basis.DOCUMENT_DATE, unit=Unit.PERCENT_FRACTION, is_pnl_metric=True, additive=False, allocatable=False),
        _m(id="OPERATING_PROFIT", kind=MetricKind.ENGINE_FORMULA, engine_ref="operating_profit", grain=Grain.ACCOUNT,
           allowed_dimensions=_MKT_PERIOD, required_inputs=("contribution_profit",),  # unclassified expenses make it PROVISIONAL (exposed), never UNAVAILABLE (OQ1)
           basis=Basis.DOCUMENT_DATE, unit=_P, is_pnl_metric=True, additive=True, allocatable=True),
        _m(id="SETTLEMENT_RECEIPTS", kind=MetricKind.ENGINE_FORMULA, engine_ref="settlement_receipts", grain=Grain.LINE,
           allowed_dimensions=_MKT_PERIOD, required_inputs=("settlement_lines",),
           basis=Basis.SETTLEMENT_DATE, unit=_P, is_pnl_metric=False, additive=True, allocatable=False),
        _m(id="SETTLEMENT_LAG_DAYS", kind=MetricKind.ENGINE_FORMULA, engine_ref="settlement_lag_days_aggregate", grain=Grain.MARKETPLACE,
           allowed_dimensions=_MKT_PERIOD, required_inputs=("settlement_lines", "sales_lines"),
           basis=Basis.SETTLEMENT_DATE, unit=Unit.DAYS, is_pnl_metric=False, additive=False, allocatable=False),
        _m(id="LEAK_AGGREGATE", kind=MetricKind.ENGINE_FORMULA, engine_ref="leak_aggregate", grain=Grain.MARKETPLACE,
           allowed_dimensions=_MKT_PERIOD, required_inputs=("reconciliation_exceptions",),
           basis=Basis.DOCUMENT_DATE, unit=_P, is_pnl_metric=False, additive=True, allocatable=False),
        _m(id="EXPENSE_BY_CATEGORY", kind=MetricKind.SET_SUM, engine_ref="expense_breakdown", grain=Grain.ACCOUNT,
           allowed_dimensions=frozenset({"period", "expense_category", "expense_class"}), required_inputs=("expense_entries",),
           basis=Basis.EXPENSE_DATE, unit=_P, is_pnl_metric=False, additive=True, allocatable=True),
        _m(id="ROAS", kind=MetricKind.RATIO, engine_ref="ad_ratios", grain=Grain.ACCOUNT, allowed_dimensions=_MKT_PERIOD,
           required_inputs=("ad_source",), basis=Basis.DOCUMENT_DATE, unit=Unit.PERCENT_FRACTION,
           is_pnl_metric=False, additive=False, allocatable=True),
        _m(id="ACOS", kind=MetricKind.RATIO, engine_ref="ad_ratios", grain=Grain.ACCOUNT, allowed_dimensions=_MKT_PERIOD,
           required_inputs=("ad_source",), basis=Basis.DOCUMENT_DATE, unit=Unit.PERCENT_FRACTION,
           is_pnl_metric=False, additive=False, allocatable=True),
        _m(id="TACOS", kind=MetricKind.RATIO, engine_ref="ad_ratios", grain=Grain.ACCOUNT, allowed_dimensions=_MKT_PERIOD,
           required_inputs=("ad_source", "sales_lines"), basis=Basis.DOCUMENT_DATE, unit=Unit.PERCENT_FRACTION,
           is_pnl_metric=False, additive=False, allocatable=True),
        _m(id="PROFIT_BRIDGE", kind=MetricKind.COMPOSITE, engine_ref="profit_bridge", grain=Grain.ACCOUNT,
           allowed_dimensions=_MKT_PERIOD, required_inputs=("contribution_profit",),
           basis=Basis.DOCUMENT_DATE, unit=_P, is_pnl_metric=True, additive=False, allocatable=False,
           explainable_by=("NET_REALIZED_REVENUE", "MARKETPLACE_FEES", "RETURN_RTO_LOSSES", "CONTRIBUTION_PROFIT")),
    )
}

# --- Joins -----------------------------------------------------------------------------------------
# `validated=False` marks joins no real export has validated (cfo-agent.md V1/V6): results through
# them are PROVISIONAL, and Amazon findings stay withheld.
JOINS: dict[str, JoinDef] = {
    j.id: j
    for j in (
        JoinDef("sales_to_components", "sales_line", "line_component", ("sales_line_id",), "ONE_TO_MANY", "left",
                "amount", True),  # an order line has several fee/tax/discount component rows
        JoinDef("meesho_orders_to_settlement", "sales_line", "settlement_line", ("line_ref",), "ONE_TO_MANY", "left",
                "amount", True),  # sub_order_num verified against real Meesho exports (data-foundation §5.1)
        JoinDef("flipkart_orders_to_settlement", "sales_line", "settlement_line", ("order_ref",), "ONE_TO_MANY", "left",
                "amount", False),
        JoinDef("amazon_orders_to_settlement", "sales_line", "settlement_line", ("order_ref",), "ONE_TO_MANY", "left",
                "amount", False),
        JoinDef("sales_to_sku_cost", "sales_line", "manual_adjustment", ("sku",), "MANY_TO_ONE", "right",
                "amount", True),  # cogs_per_unit: one ACTIVE row per SKU
        JoinDef("ads_to_sales", "ad_report_line", "sales_line", ("marketplace", "sku", "report_date"), "MANY_TO_ONE", "right",
                "spend", False),
    )
}

PLAN_INTENTS: frozenset[str] = frozenset(
    {"PROFIT_BRIDGE", "METRIC_BY_DIMENSION", "RANK", "COMPARE_PERIODS", "LEAK_SUMMARY", "CASH_VIEW", "EXPENSE_BREAKDOWN"}
)
STEP_OPS: tuple[str, ...] = ("filter", "normalize", "join", "group_by", "aggregate", "metric", "compare", "rank")
FILTER_OPS: frozenset[str] = frozenset({"eq", "in"})
NORMALIZE_KINDS: frozenset[str] = frozenset({"gst_exclusive", "paise", "document_date"})
PERIOD_GRANULARITIES: frozenset[str] = frozenset({"day", "week", "month"})
COMPARE_KINDS: frozenset[str] = frozenset({"period_over_period", "marketplace"})
RANK_DIRECTIONS: frozenset[str] = frozenset({"asc", "desc"})
# Expense classes that may never feed a P&L metric (cfo-unified-financials.md §4.2).
NON_PNL_EXPENSE_CLASSES: frozenset[str] = frozenset({"OWNER_DRAWING", "INVENTORY_PURCHASE", "CAPITAL", "TAX_ASSET"})
MARKETPLACES: frozenset[str] = frozenset({"AMAZON", "FLIPKART", "MEESHO"})


def _catalog_fingerprint() -> str:
    payload = {
        "metrics": {k: [m.kind.value, m.engine_ref, m.grain.value, sorted(m.allowed_dimensions), list(m.required_inputs),
                        m.basis.value, m.unit.value, m.is_pnl_metric, m.additive, m.allocatable, list(m.explainable_by),
                        m.formula_version] for k, m in sorted(METRICS.items())},
        "dimensions": {k: [d.source_table, d.column, d.grain.value] for k, d in sorted(DIMENSIONS.items())},
        "joins": {k: [j.left, j.right, list(j.key_columns), j.cardinality, j.uniqueness_side, j.control_total_column, j.validated]
                  for k, j in sorted(JOINS.items())},
        "intents": sorted(PLAN_INTENTS),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


CATALOG_VERSION: str = _catalog_fingerprint()
