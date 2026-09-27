"""`cfo.pnl.inputs` resolvers — twinkly-mapping-canyon.md CP2/CP3.

Constructed `CanonicalLine`s only (no DB). Confirms: missing COGS/SKU-mapping path returns
`Unavailable` (never zero, CLAUDE.md hard rule); the resolvers return correct `Paise` values
for known inputs.
"""

from __future__ import annotations

from datetime import date
from uuid import uuid4

from calc_engine.formulas.cost_components import CostEntry
from calc_engine.types import CanonicalLine, ComponentRow, Confidence, Paise, Unavailable

from cfo.pnl.inputs import (
    DEFAULT_SHIPPING_COMPONENT_CODES,
    resolve_cogs,
    resolve_expense_pool_total,
    resolve_marketplace_fees,
    resolve_return_rto_losses,
    resolve_shipping_logistics,
)

_AS_OF = date(2026, 9, 23)


def _line(
    *,
    line_id=None,
    components: tuple[ComponentRow, ...] = (),
    quantity: int = 1,
    return_status: str | None = "DELIVERED",
    rto_status: str | None = "NOT_RTO",
    returned_qty: int = 0,
    rto_qty: int = 0,
    rto_outcome: str | None = None,
) -> CanonicalLine:
    return CanonicalLine(
        sales_line_id=line_id or uuid4(),
        marketplace="MEESHO",
        document_type="INVOICE",
        quantity=quantity,
        invoice_date=_AS_OF,
        dispatch_date=_AS_OF,
        order_date=_AS_OF,
        gross_item_amount=Paise(1_000_00),
        components=components,
        confidence=Confidence.VERIFIED,
        cancellation_state="NOT_CANCELLED",
        return_status=return_status,
        returned_qty=returned_qty,
        rto_status=rto_status,
        rto_qty=rto_qty,
        rto_outcome=rto_outcome,
    )


def _component(*, kind: str, code: str, amount_paise: int, side: str = "INVOICE") -> ComponentRow:
    return ComponentRow(
        id=uuid4(),
        component_kind=kind,
        component_code=code,
        source_side=side,
        amount=Paise(amount_paise),
    )


# ---------------------------------------------------------------------------
# resolve_cogs
# ---------------------------------------------------------------------------


def test_resolve_cogs_missing_sku_mapping_is_unavailable() -> None:
    line = _line()
    result = resolve_cogs(
        [line],
        sku_by_line={},  # no mapping at all for this line
        cost_history_by_sku={},
        as_of=_AS_OF,
    )
    assert isinstance(result, Unavailable)
    assert "sku_by_line" in result.missing_inputs


def test_resolve_cogs_missing_cost_history_is_unavailable() -> None:
    line = _line()
    sku = "SKU-1"
    result = resolve_cogs(
        [line],
        sku_by_line={str(line.sales_line_id): sku},
        cost_history_by_sku={},  # no cost entries for this sku
        as_of=_AS_OF,
    )
    assert isinstance(result, Unavailable)


def test_resolve_cogs_known_inputs_returns_correct_paise() -> None:
    line = _line(quantity=3)
    sku = "SKU-1"
    result = resolve_cogs(
        [line],
        sku_by_line={str(line.sales_line_id): sku},
        cost_history_by_sku={sku: [CostEntry(amount_paise=Paise(200_00), effective_from=date(2026, 1, 1))]},
        as_of=_AS_OF,
    )
    assert isinstance(result, Paise)
    assert result.value == 200_00 * 3


# ---------------------------------------------------------------------------
# resolve_marketplace_fees (pass-through)
# ---------------------------------------------------------------------------


def test_resolve_marketplace_fees_sums_fee_components() -> None:
    line = _line(components=(_component(kind="FEE", code="COMMISSION", amount_paise=50_00),))
    total, flags = resolve_marketplace_fees(
        [line], fee_component_codes=frozenset({"COMMISSION"})
    )
    assert total.value == 50_00
    assert flags == ()


# ---------------------------------------------------------------------------
# resolve_shipping_logistics
# ---------------------------------------------------------------------------


def test_resolve_shipping_logistics_sums_default_codes() -> None:
    line = _line(
        components=(
            _component(kind="CHARGE", code="LOGISTICS_FEE", amount_paise=30_00),
            _component(kind="CHARGE", code="SHIPPING_CHARGE", amount_paise=20_00),
            _component(kind="FEE", code="COMMISSION", amount_paise=999_00),  # not a shipping code
        )
    )
    total = resolve_shipping_logistics([line])
    assert total.value == 50_00
    assert DEFAULT_SHIPPING_COMPONENT_CODES == frozenset({"LOGISTICS_FEE", "SHIPPING_CHARGE"})


def test_resolve_shipping_logistics_excludes_actual_return_rto_lines() -> None:
    returned_line = _line(
        return_status="RETURNED",
        components=(_component(kind="CHARGE", code="LOGISTICS_FEE", amount_paise=30_00),),
    )
    total = resolve_shipping_logistics([returned_line])
    assert total.value == 0


# ---------------------------------------------------------------------------
# resolve_expense_pool_total — absent adjustment = zero, confirmed (not Unavailable)
# ---------------------------------------------------------------------------


def test_resolve_expense_pool_total_empty_input_is_zero() -> None:
    total = resolve_expense_pool_total([])
    assert total.value == 0


def test_resolve_expense_pool_total_sums_entries() -> None:
    total = resolve_expense_pool_total(
        [{"amount_paise": 1000_00}, {"amount_paise": 250_00, "marketplace": "AMAZON"}]
    )
    assert total.value == 1250_00


# ---------------------------------------------------------------------------
# resolve_return_rto_losses
# ---------------------------------------------------------------------------


def test_resolve_return_rto_losses_no_return_or_rto_is_zero() -> None:
    line = _line(return_status="DELIVERED", rto_status="NOT_RTO")
    result = resolve_return_rto_losses(
        [line],
        sku_by_line={},
        cost_history_by_sku={},
        as_of=_AS_OF,
        forward_logistics_codes=frozenset(),
        reverse_logistics_codes=frozenset(),
        non_refunded_fee_codes=frozenset(),
    )
    assert isinstance(result, Paise)
    assert result.value == 0


def test_resolve_return_rto_losses_unclassified_outcome_is_unavailable() -> None:
    """A return with no rto_outcome classified yet propagates Unavailable (E9) — never a
    silent zero."""
    line = _line(return_status="RETURNED", returned_qty=1, rto_outcome=None)
    result = resolve_return_rto_losses(
        [line],
        sku_by_line={str(line.sales_line_id): "SKU-1"},
        cost_history_by_sku={"SKU-1": [CostEntry(amount_paise=Paise(100_00), effective_from=date(2026, 1, 1))]},
        as_of=_AS_OF,
        forward_logistics_codes=frozenset(),
        reverse_logistics_codes=frozenset(),
        non_refunded_fee_codes=frozenset(),
    )
    assert isinstance(result, Unavailable)


def test_resolve_return_rto_losses_recovered_sellable_has_no_cogs_leg() -> None:
    line = _line(
        return_status="RETURNED",
        returned_qty=1,
        rto_outcome="RECOVERED_SELLABLE",
        components=(_component(kind="CHARGE", code="REVERSE_LOGISTICS", amount_paise=15_00, side="SETTLEMENT"),),
    )
    result = resolve_return_rto_losses(
        [line],
        sku_by_line={str(line.sales_line_id): "SKU-1"},
        cost_history_by_sku={"SKU-1": [CostEntry(amount_paise=Paise(100_00), effective_from=date(2026, 1, 1))]},
        as_of=_AS_OF,
        forward_logistics_codes=frozenset(),
        reverse_logistics_codes=frozenset({"REVERSE_LOGISTICS"}),
        non_refunded_fee_codes=frozenset(),
    )
    assert isinstance(result, Paise)
    # RECOVERED_SELLABLE: zero COGS leg, only the reverse-logistics leg (15_00)
    assert result.value == 15_00
