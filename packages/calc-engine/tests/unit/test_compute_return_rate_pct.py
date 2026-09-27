"""compute_return_rate_pct — anomaly-detection.md §6.1 `RETURN_RATE_PCT`. A fresh computation
over canonical lines (not a composition of two prior `MetricResult`s), mirroring
`compute_net_realized_revenue`/`compute_gst_period_summary`'s own "derive canonical_data_version
the normal way" convention.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from fractions import Fraction
from uuid import uuid4

from calc_engine.api.compute_metric import compute_return_rate_pct
from calc_engine.types import CanonicalLine, Confidence, Paise

_AS_OF = date(2026, 9, 25)
_COMPUTED_AT = datetime(2026, 9, 25, tzinfo=timezone.utc)


def _line(*, quantity: int, returned_qty: int = 0, rto_qty: int = 0, confidence: Confidence = Confidence.VERIFIED) -> CanonicalLine:
    return CanonicalLine(
        sales_line_id=uuid4(),
        marketplace="MEESHO",
        document_type="INVOICE",
        quantity=quantity,
        invoice_date=_AS_OF,
        dispatch_date=_AS_OF,
        order_date=_AS_OF,
        gross_item_amount=Paise(1_000_00),
        components=(),
        confidence=confidence,
        returned_qty=returned_qty,
        rto_qty=rto_qty,
    )


def _compute(lines, **overrides):
    kwargs = dict(
        ingestion_run_ids=["run-1"],
        adapter_versions=["meesho.v1"],
        active_adjustment_ids=[],
        computed_at=_COMPUTED_AT,
        as_of_date=_AS_OF,
    )
    kwargs.update(overrides)
    return compute_return_rate_pct(lines, **kwargs)


def test_happy_path_computes_fraction_percentage_not_paise():
    lines = [_line(quantity=10, returned_qty=2, rto_qty=1), _line(quantity=10)]
    result = _compute(lines)

    assert result.metric_code == "RETURN_RATE_PCT"
    assert result.is_available is True
    assert result.value_paise is None
    assert result.value_fraction == Fraction(3, 20) * 100
    assert result.formula_version == "RETURN_RATE_PCT.v1"
    assert result.input_refs == tuple(line.sales_line_id for line in lines)


def test_empty_lines_is_unavailable_never_zero_or_undefined():
    result = _compute([])

    assert result.is_available is False
    assert result.value_paise is None
    assert result.value_fraction is None
    assert result.unavailable_reason is not None
    assert result.id is not None  # still a real, minted engine_result_ref, even UNAVAILABLE


def test_all_zero_quantity_lines_is_unavailable():
    lines = [_line(quantity=0)]
    result = _compute(lines)

    assert result.is_available is False
    assert result.value_fraction is None


def test_confidence_derived_from_weakest_line_confidence():
    lines = [
        _line(quantity=10, returned_qty=1, confidence=Confidence.VERIFIED),
        _line(quantity=10, confidence=Confidence.MANUAL),
    ]
    result = _compute(lines)

    assert result.confidence == "MANUAL"


def test_confidence_all_verified_stays_verified():
    lines = [_line(quantity=10, returned_qty=1, confidence=Confidence.VERIFIED)]
    result = _compute(lines)

    assert result.confidence == "VERIFIED"


def test_manual_adjustment_set_reflects_active_adjustment_ids():
    lines = [_line(quantity=10, returned_qty=1)]
    adjustment_id = uuid4()
    result = _compute(lines, active_adjustment_ids=[adjustment_id])

    assert str(adjustment_id) in result.manual_adjustment_set
