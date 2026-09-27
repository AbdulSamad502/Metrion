"""gst/summary.py / compute_gst_period_summary — deterministic-engine.md §8.3."""

from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import uuid4

from hypothesis import given
from hypothesis import strategies as st

from calc_engine.api.compute_metric import compute_gst_period_summary
from calc_engine.gst.summary import DEFAULT_TAX_HEADS, gst_period_summary
from calc_engine.types import CanonicalLine, ComponentRow, Confidence, Paise

NOW = datetime(2026, 9, 23, tzinfo=timezone.utc)
_TAX_HEAD_NAMES = ("CGST", "SGST", "IGST", "UTGST", "CESS")


def _component(
    code: str,
    amount_paise: int,
    *,
    kind: str = "TAX",
    side: str = "INVOICE",
) -> ComponentRow:
    return ComponentRow(
        id=uuid4(),
        component_kind=kind,
        component_code=code,
        source_side=side,
        amount=Paise(amount_paise),
    )


def _line(*components: ComponentRow, gross_paise: int = 0) -> CanonicalLine:
    return CanonicalLine(
        sales_line_id=uuid4(),
        marketplace="MEESHO",
        document_type="INVOICE",
        quantity=1,
        invoice_date=date(2026, 8, 15),
        dispatch_date=None,
        order_date=None,
        gross_item_amount=Paise(gross_paise),
        components=tuple(components),
        confidence=Confidence.PROVISIONAL,
    )


# --- gst_period_summary --------------------------------------------------------------------------


def test_gst_period_summary_all_heads_present_including_zero():
    lines = [
        _line(
            _component("CGST", 100),
            _component("SGST", 100),
            _component("IGST", 0),
        )
    ]
    result = gst_period_summary(lines)
    assert result == {
        "CGST": Paise(100),
        "SGST": Paise(100),
        "IGST": Paise(0),
        "UTGST": Paise(0),
        "CESS": Paise(0),
    }
    assert set(result.keys()) == DEFAULT_TAX_HEADS


def test_gst_period_summary_excludes_settlement_side_component():
    lines = [_line(_component("CGST", 100), _component("CGST", 50, side="SETTLEMENT"))]
    result = gst_period_summary(lines)
    assert result["CGST"] == Paise(100)


def test_gst_period_summary_excludes_non_tax_kind_with_matching_code():
    lines = [_line(_component("CGST", 100), _component("CGST", 999, kind="FEE"))]
    result = gst_period_summary(lines)
    assert result["CGST"] == Paise(100)


# --- compute_gst_period_summary -------------------------------------------------------------------


def test_compute_gst_period_summary_row_count_and_metric_code():
    lines = [_line(_component("CGST", 100), _component("SGST", 100))]
    results = compute_gst_period_summary(
        lines,
        ingestion_run_ids=[uuid4()],
        adapter_versions=["amazon:1.0.0"],
        active_adjustment_ids=[],
        computed_at=NOW,
    )
    assert len(results) == len(DEFAULT_TAX_HEADS)
    metric_codes = {r.metric_code for r in results}
    assert metric_codes == {"GST_PERIOD_SUMMARY"}


def test_compute_gst_period_summary_calculation_basis_names_own_head_only():
    lines = [_line(_component("CGST", 100))]
    results = compute_gst_period_summary(
        lines,
        ingestion_run_ids=[uuid4()],
        adapter_versions=["amazon:1.0.0"],
        active_adjustment_ids=[],
        computed_at=NOW,
    )
    by_head = {}
    for r in results:
        matches = [h for h in _TAX_HEAD_NAMES if h in r.calculation_basis]
        assert len(matches) == 1
        by_head[matches[0]] = r.calculation_basis
    assert set(by_head.keys()) == set(_TAX_HEAD_NAMES)


def test_compute_gst_period_summary_all_rows_available():
    lines: list[CanonicalLine] = []
    results = compute_gst_period_summary(
        lines,
        ingestion_run_ids=[uuid4()],
        adapter_versions=["amazon:1.0.0"],
        active_adjustment_ids=[],
        computed_at=NOW,
    )
    assert len(results) == len(DEFAULT_TAX_HEADS)
    assert all(r.is_available is True for r in results)
    assert all(r.value_paise == 0 for r in results)


def test_compute_gst_period_summary_deterministic_ordering():
    lines = [_line(_component("CGST", 100), _component("SGST", 200))]
    results_a = compute_gst_period_summary(
        lines,
        ingestion_run_ids=[uuid4()],
        adapter_versions=["amazon:1.0.0"],
        active_adjustment_ids=[],
        computed_at=NOW,
    )
    results_b = compute_gst_period_summary(
        lines,
        ingestion_run_ids=[uuid4()],
        adapter_versions=["amazon:1.0.0"],
        active_adjustment_ids=[],
        computed_at=NOW,
    )
    order_a = [r.calculation_basis for r in results_a]
    order_b = [r.calculation_basis for r in results_b]
    assert order_a == order_b


# --- Hypothesis property test ----------------------------------------------------------------------


_KNOWN_HEADS = list(_TAX_HEAD_NAMES)


@st.composite
def _lines_with_tax_noise(draw):
    n_lines = draw(st.integers(min_value=1, max_value=5))
    lines = []
    for _ in range(n_lines):
        n_components = draw(st.integers(min_value=0, max_value=6))
        components = []
        for _ in range(n_components):
            code = draw(st.sampled_from(_KNOWN_HEADS + ["UNKNOWN_TAX"]))
            amount = draw(st.integers(min_value=0, max_value=100_000))
            kind = draw(st.sampled_from(["TAX", "FEE", "DISCOUNT"]))
            side = draw(st.sampled_from(["INVOICE", "SETTLEMENT"]))
            components.append(_component(code, amount, kind=kind, side=side))
        lines.append(_line(*components))
    return lines


@given(lines=_lines_with_tax_noise())
def test_gst_period_summary_reconciles_to_known_head_tax_invoice_components(lines):
    result = gst_period_summary(lines)

    expected_total = 0
    for line in lines:
        for component in line.components:
            if (
                component.component_kind == "TAX"
                and component.source_side == "INVOICE"
                and component.component_code in _KNOWN_HEADS
            ):
                expected_total += component.amount.value

    actual_total = sum(v.value for v in result.values())
    assert actual_total == expected_total

    # An unrecognized tax code never appears anywhere in the closed-set output.
    unknown_total = sum(
        component.amount.value
        for line in lines
        for component in line.components
        if component.component_kind == "TAX"
        and component.source_side == "INVOICE"
        and component.component_code == "UNKNOWN_TAX"
    )
    assert unknown_total >= 0  # sanity: strategy can produce this case
    assert "UNKNOWN_TAX" not in result
