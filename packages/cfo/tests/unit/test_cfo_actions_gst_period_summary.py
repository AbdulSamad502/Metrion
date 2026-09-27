"""`backend.services.cfo_actions.render_gst_period_summary` — cfo-agent.md §6.6/§6.8
`cfo.gst_summary`, PERIOD-level only. twinkly-mapping-canyon.md CP A2.

Mirrors `test_cfo_actions_gst.py`'s (the LINE-level one's) structure, testing the PERIOD
composition instead. Covers: known lines with CGST/SGST/IGST tax components produce correct
per-head totals with all 5 heads present even at zero; the §6.6 disclaimer is present on every
response (AC7); `metric_code` is the constant `"GST_PERIOD_SUMMARY"` across every row;
persistence goes through `metric_result_repo.save` with the `grain="TENANT_PERIOD"` shape
(mirroring `compute_period_pnl`'s own aggregate shape, not `compute_pricing_curve`'s per-SKU
one); and an explicit guardrail test proving `render_gst_period_summary` and `analyze_gst_lines`
remain genuinely separate functions/surfaces — this is the exact guardrail this session has
repeatedly protected.
"""

from __future__ import annotations

import ast
import inspect
from dataclasses import fields
from datetime import date, datetime, timezone
from uuid import uuid4

import pytest

import backend.services.cfo_actions as cfo_actions_module
from backend.services.cfo_actions import (
    GstLineResult,
    GstPeriodSummaryOutcome,
    GstPeriodSummaryRequest,
    analyze_gst_lines,
    render_gst_period_summary,
)
from calc_engine.gst.summary import DEFAULT_TAX_HEADS
from calc_engine.types import CanonicalLine, ComponentRow, Confidence, Paise
from cfo.reasoning.prompts import GST_DISCLAIMER

_TENANT_ID = uuid4()
_AS_OF = date(2026, 9, 23)
_PERIOD_START = date(2026, 9, 1)
_PERIOD_END = date(2026, 9, 30)
_NOW = datetime(2026, 9, 23, tzinfo=timezone.utc)


def _component(code: str, amount_paise: int, *, kind: str = "TAX", side: str = "INVOICE") -> ComponentRow:
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
        invoice_date=date(2026, 9, 15),
        dispatch_date=None,
        order_date=None,
        gross_item_amount=Paise(gross_paise),
        components=tuple(components),
        confidence=Confidence.PROVISIONAL,
    )


def _request(lines: list[CanonicalLine]) -> GstPeriodSummaryRequest:
    return GstPeriodSummaryRequest(
        lines=lines,
        period_start=_PERIOD_START,
        period_end=_PERIOD_END,
        as_of_date=_AS_OF,
        ingestion_run_ids=[uuid4()],
        adapter_versions=["meesho:1.0.0"],
        active_adjustment_ids=[],
        requested_by=uuid4(),
        computed_at=_NOW,
    )


@pytest.fixture(autouse=True)
def _stub_metric_result_save(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, object]]:
    saved: list[dict[str, object]] = []

    def _save(tenant_id, result, *, grain, target_ref, period, config_version):
        saved.append(
            {
                "tenant_id": tenant_id,
                "result": result,
                "grain": grain,
                "target_ref": target_ref,
                "period": period,
                "config_version": config_version,
            }
        )

    monkeypatch.setattr(cfo_actions_module.metric_result_repo, "save", _save)
    return saved


def test_known_lines_produce_correct_per_head_totals_all_five_heads_present() -> None:
    lines = [
        _line(_component("CGST", 100), _component("SGST", 100), _component("IGST", 0)),
    ]
    outcome = render_gst_period_summary(_TENANT_ID, _request(lines))
    by_head = {}
    for result in outcome.results:
        for head in DEFAULT_TAX_HEADS:
            if head in result.calculation_basis:
                by_head[head] = result.value_paise
    assert by_head == {"CGST": 100, "SGST": 100, "IGST": 0, "UTGST": 0, "CESS": 0}
    assert set(by_head.keys()) == DEFAULT_TAX_HEADS
    assert len(outcome.results) == len(DEFAULT_TAX_HEADS)


def test_igst_only_line_reconciles_correctly() -> None:
    lines = [_line(_component("IGST", 500))]
    outcome = render_gst_period_summary(_TENANT_ID, _request(lines))
    by_head = {
        head: r.value_paise for r in outcome.results for head in DEFAULT_TAX_HEADS if head in r.calculation_basis
    }
    assert by_head["IGST"] == 500
    assert by_head["CGST"] == 0
    assert by_head["SGST"] == 0


def test_disclaimer_present_on_every_response() -> None:
    """AC7 — the outcome carries the disclaimer, and it is the exact §6.6 constant, verbatim."""
    lines = [_line(_component("CGST", 50))]
    outcome = render_gst_period_summary(_TENANT_ID, _request(lines))
    assert outcome.disclaimer == GST_DISCLAIMER


def test_metric_code_constant_across_all_returned_rows() -> None:
    lines = [_line(_component("CGST", 10), _component("SGST", 10))]
    outcome = render_gst_period_summary(_TENANT_ID, _request(lines))
    metric_codes = {r.metric_code for r in outcome.results}
    assert metric_codes == {"GST_PERIOD_SUMMARY"}


def test_zero_lines_still_returns_all_heads_available_at_zero() -> None:
    outcome = render_gst_period_summary(_TENANT_ID, _request([]))
    assert len(outcome.results) == len(DEFAULT_TAX_HEADS)
    assert all(r.is_available is True for r in outcome.results)
    assert all(r.value_paise == 0 for r in outcome.results)


def test_persistence_uses_tenant_period_aggregate_shape(
    _stub_metric_result_save: list[dict[str, object]],
) -> None:
    lines = [_line(_component("CGST", 100))]
    render_gst_period_summary(_TENANT_ID, _request(lines))

    assert len(_stub_metric_result_save) == len(DEFAULT_TAX_HEADS)
    expected_period = f"{_PERIOD_START.isoformat()}/{_PERIOD_END.isoformat()}"
    for call in _stub_metric_result_save:
        assert call["tenant_id"] == _TENANT_ID
        assert call["grain"] == "TENANT_PERIOD"
        assert call["target_ref"] == str(_TENANT_ID)
        assert call["period"] == expected_period
        assert call["config_version"] == "CFO_GST_PERIOD_SUMMARY.v1"


# --- Guardrail: render_gst_period_summary and analyze_gst_lines are genuinely distinct ------


def test_guardrail_render_gst_period_summary_and_analyze_gst_lines_are_different_functions() -> None:
    """The exact guardrail this session has repeatedly protected: these must never be merged
    or become interchangeable. A future "simplification" that collapses them into one function
    (or makes one call the other) must fail this test."""
    assert render_gst_period_summary is not analyze_gst_lines
    assert render_gst_period_summary.__name__ != analyze_gst_lines.__name__

    period_sig = inspect.signature(render_gst_period_summary)
    line_sig = inspect.signature(analyze_gst_lines)
    assert list(period_sig.parameters) != list(line_sig.parameters)

    # Source-level check on the executable body only (docstrings legitimately name the other
    # function to explain the guardrail in prose) — neither function's *code* ever calls the
    # other, and the line-level function never calls the period-level engine primitive.
    period_body = ast.parse(inspect.getsource(render_gst_period_summary))
    line_body = ast.parse(inspect.getsource(analyze_gst_lines))

    def _call_names(tree: ast.AST) -> set[str]:
        func_node = tree.body[0]
        assert isinstance(func_node, ast.FunctionDef)
        body = func_node.body[1:] if isinstance(func_node.body[0], ast.Expr) else func_node.body
        names: set[str] = set()
        for node in ast.walk(ast.Module(body=body, type_ignores=[])):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                names.add(node.func.id)
        return names

    assert "analyze_gst_lines" not in _call_names(period_body)
    assert "render_gst_period_summary" not in _call_names(line_body)
    assert "compute_gst_period_summary" not in _call_names(line_body)


def test_guardrail_period_output_has_no_per_line_granularity() -> None:
    """The period function's output type carries only a per-tax-head list and a disclaimer —
    no per-line field (`line_ref`, `normalized_exclusive_paise`, etc)."""
    outcome_field_names = {f.name for f in fields(GstPeriodSummaryOutcome)}
    assert outcome_field_names == {"results", "disclaimer"}
    for forbidden in ("line_ref", "line", "per_line"):
        assert forbidden not in outcome_field_names


def test_guardrail_line_output_has_no_period_level_aggregate_field() -> None:
    """The line function's output type carries no period-level aggregate field — mirrors
    `test_cfo_actions_gst.py`'s own guardrail test for the inverse direction."""
    field_names = {f.name for f in fields(GstLineResult)}
    for forbidden in ("total", "period_total", "sum", "aggregate", "summary"):
        for name in field_names:
            assert forbidden not in name.lower(), f"GstLineResult must stay line-level, found field {name!r}"


def test_guardrail_gst_period_summary_request_has_no_per_line_rate_or_basis_fields() -> None:
    """The period request type is genuinely a period-level assembly — it carries raw
    `CanonicalLine`s (for the engine's own summation) but no per-line rate/basis/plausibility
    fields of the kind `GstLineInput` carries; those concepts belong exclusively to the
    line-level surface."""
    field_names = {f.name for f in fields(GstPeriodSummaryRequest)}
    for forbidden in ("rate_pct", "basis", "listed_paise", "line_ref"):
        assert forbidden not in field_names
