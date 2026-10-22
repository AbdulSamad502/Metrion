"""Types for the hypothetical P&L scenario (docs/specs/calculator.md §14).

Everything here is a HYPOTHETICAL estimate over seller-typed inputs. It is not a `metric_result`, never carries an `engine_result_ref`, and
is never persisted. Money is signed integer paise (`Paise` on every presented figure; plain `int` paise on inputs), rates are integer
basis points (1 bp = 0.01%). Intermediates are exact `Fraction`s; there is no float anywhere in this package.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction
from typing import Any, Literal

from calc_engine.types import Paise

MarketplaceId = Literal["amazon", "flipkart", "meesho"]
Mode = Literal["quick", "detailed"]
GstStatus = Literal["registered_itc", "registered_no_itc", "unregistered"]
AmazonFulfilment = Literal["easy_ship", "seller_flex", "fba", "self_ship"]
PriceBasis = Literal["price_incl_gst", "price_excl_gst"]
ChargedOn = Literal["shipped", "kept", "rto_return"]
ResultStatus = Literal["incomplete", "provisional", "estimate"]
LineGroup = Literal[
    "product", "stock_loss", "commission", "shipping", "fulfilment", "other_fee", "fee_gst", "fee_refund", "packaging", "advertising"
]


@dataclass(frozen=True, slots=True)
class Entry:
    """A seller input is tri-state plus invalid: nothing entered, explicitly not applicable (a CONFIRMED zero), a value, or unparseable.
    An empty entry is never zero."""

    state: Literal["empty", "na", "set", "invalid"]
    value: Any = None  # int (paise / bps / count) or FeeAmount, depending on the field
    reason: str | None = None


EMPTY = Entry("empty")
NA = Entry("na")


def set_(value: Any) -> Entry:
    return Entry("set", value)


def invalid(reason: str) -> Entry:
    return Entry("invalid", None, reason)


@dataclass(frozen=True, slots=True)
class Band:
    """`up_to` is the inclusive upper bound on the fee's price basis in paise (None = no upper limit); `amount` is bps for percent fees, paise for flat fees."""

    up_to: int | None
    amount: int


@dataclass(frozen=True, slots=True)
class FeeAmount:
    kind: Literal["single", "tiers"]
    amount: int = 0  # single
    mode: Literal["whole", "marginal"] = "whole"  # tiers
    bands: tuple[Band, ...] = ()


@dataclass(frozen=True, slots=True)
class FeeInput:
    amount: Entry = EMPTY  # Entry
    refund_bps: Entry = EMPTY  # Entry
    basis: PriceBasis | None = None


@dataclass(frozen=True, slots=True)
class Recovery:
    sellable_bps: Entry = EMPTY
    damaged_bps: Entry = EMPTY


@dataclass(frozen=True, slots=True)
class ScenarioInputs:
    marketplace: MarketplaceId
    mode: Mode = "detailed"
    amazon_fulfilment: AmazonFulfilment = "easy_ship"
    selling_price: Entry = EMPTY  # per unit, incl. GST, paise
    gst_rate_bps: Entry = EMPTY
    gst_status: GstStatus = "registered_itc"
    product_cost: Entry = EMPTY  # per unit as paid incl. GST, paise
    purchase_gst_rate_bps: Entry = EMPTY
    services_gst_rate_bps: Entry = EMPTY
    packaging_cost: Entry = EMPTY
    fees: dict[str, FeeInput] = field(default_factory=dict)
    monthly_orders: Entry = EMPTY
    rto_bps: Entry = EMPTY
    return_bps: Entry = EMPTY
    rto_recovery: Recovery = field(default_factory=Recovery)
    return_recovery: Recovery = field(default_factory=Recovery)
    salvage_bps: Entry = EMPTY
    ad_spend: Entry = EMPTY
    ad_revenue: Entry = EMPTY
    operating_expenses: Entry = EMPTY
    is_example: bool = False


@dataclass(frozen=True, slots=True)
class Issue:
    code: str
    severity: Literal["blocking", "missing", "info"]
    message: str
    field: str | None = None


@dataclass(frozen=True, slots=True)
class Assumption:
    code: str
    label: str


@dataclass(frozen=True, slots=True)
class Line:
    id: str
    label: str
    group: LineGroup
    amount: Paise  # cost positive, credit (refund) negative


@dataclass(frozen=True, slots=True)
class View:
    revenue: Paise
    lines: tuple[Line, ...]
    contribution: Paise
    operating_expenses: Paise | None = None
    operating_profit: Paise | None = None


@dataclass(frozen=True, slots=True)
class OrderCounts:
    placed: Fraction
    kept: Fraction
    rto: Fraction
    returned: Fraction


@dataclass(frozen=True, slots=True)
class Metrics:
    """Margins in bps of revenue; None = not applicable (never zero)."""

    contribution_margin_bps: int | None
    operating_margin_bps: int | None
    effective_fee_bps: int | None
    acos_bps: int | None
    tacos_bps: int | None
    roas_bps: int | None
    break_even_roas_bps: int | None
    max_cac: Paise | None
    gst_recovered_per_kept: Paise | None
    gst_recovered_monthly: Paise | None


@dataclass(frozen=True, slots=True)
class LineShare:
    """One cost line per order kept, with its share of revenue in basis points (exact ratio, rounded half away from zero once)."""

    id: str
    label: str
    group: LineGroup
    amount: Paise
    share_bps: int


@dataclass(frozen=True, slots=True)
class Segment:
    """One slice of the "where each rupee goes" chart. `start_bps`/`end_bps` are cumulative positions on 0..10000 (each rounded from the exact cumulative
    amount), so the slices tile the whole circle with no gap or overlap and the client does no arithmetic to draw them."""

    id: str
    label: str
    group: str  # a LineGroup, or "profit"
    amount: Paise
    share_bps: int
    start_bps: int
    end_bps: int


@dataclass(frozen=True, slots=True)
class Breakdown:
    """Where each rupee of revenue goes, per order kept. Present only when orders are kept and revenue is above zero.

    `segments` is None, with `chart_unavailable_reason`, when the costs cannot be drawn as slices of one whole (a fee refund is a credit, or the costs exceed
    revenue). The per-line shares and the top costs are always there."""

    lines: tuple[LineShare, ...]
    profit_share_bps: int
    segments: tuple[Segment, ...] | None
    chart_unavailable_reason: str | None
    top_costs: tuple[LineShare, ...]


@dataclass(frozen=True, slots=True)
class ScenarioResult:
    status: ResultStatus
    issues: tuple[Issue, ...]
    missing_costs: tuple[str, ...]
    assumptions: tuple[Assumption, ...]
    scope_note: str | None
    is_example: bool
    orders: OrderCounts | None
    no_kept_orders: bool
    per_kept: View | None
    per_placed: View | None
    monthly: View | None
    metrics: Metrics | None
    breakdown: Breakdown | None = None


@dataclass(frozen=True, slots=True)
class PriceRange:
    from_price: int
    to_price: int | None  # None = no upper limit


@dataclass(frozen=True, slots=True)
class SolveTarget:
    kind: Literal["breakeven", "margin"]
    bps: int = 0


@dataclass(frozen=True, slots=True)
class SolveResult:
    kind: Literal["price", "always", "unreachable", "unavailable"]
    price: Paise | None = None
    ranges: tuple[PriceRange, ...] = ()
    excludes_missing_costs: bool = False
    reason: str | None = None
