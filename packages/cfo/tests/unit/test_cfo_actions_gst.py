"""`backend.services.cfo_actions.analyze_gst_lines` — cfo-agent.md §6.6, line-level only.

`config_repo.gst_slabs_effective_on` opens a real DB connection — no live Postgres in this
session, so it is monkeypatched to return constructed slab rows (the same shape the real
repository returns: `rate_pct`/`label`/`effective_from`/`effective_to`/`confidence` dict rows).

Covers: per-line normalize + plausibility works; every result carries the §6.6 disclaimer
(AC7); an unresolvable rate excludes that line and flags it rather than defaulting (E12); and
the guardrail — the function's return shape has no period-total field, and the module contains
no summation across lines (GST must never become a period summary).
"""

from __future__ import annotations

import ast
import inspect
from dataclasses import fields
from datetime import date
from fractions import Fraction

import pytest

import backend.services.cfo_actions as cfo_actions_module
from backend.services.cfo_actions import GstLineInput, GstLineResult, analyze_gst_lines
from cfo.reasoning.prompts import GST_DISCLAIMER

_AS_OF = date(2026, 9, 23)


@pytest.fixture(autouse=True)
def _stub_gst_slabs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        cfo_actions_module.config_repo,
        "gst_slabs_effective_on",
        lambda tenant_id, *, as_of_date: [
            {
                "rate_pct": Fraction(18),
                "label": "Standard 18%",
                "effective_from": date(2020, 1, 1),
                "effective_to": None,
                "confidence": "PROVISIONAL",
            },
            {
                "rate_pct": Fraction(5),
                "label": "Reduced 5%",
                "effective_from": date(2020, 1, 1),
                "effective_to": None,
                "confidence": "PROVISIONAL",
            },
        ],
    )


def test_normalize_and_plausibility_for_inclusive_line_with_matching_rate() -> None:
    line = GstLineInput(line_ref="L1", listed_paise=1180_00, basis="INCLUSIVE", rate_pct=Fraction(18))
    [result] = analyze_gst_lines(object(), [line], as_of_date=_AS_OF)
    assert result.is_available is True
    assert result.normalized_exclusive_paise == 1000_00
    assert result.rate_plausibility_matched is True
    assert result.rate_plausibility_severity == "INFO"


def test_exclusive_line_needs_no_rate_for_normalization() -> None:
    line = GstLineInput(line_ref="L2", listed_paise=500_00, basis="EXCLUSIVE", rate_pct=None)
    [result] = analyze_gst_lines(object(), [line], as_of_date=_AS_OF)
    assert result.is_available is True
    assert result.normalized_exclusive_paise == 500_00
    # No rate supplied -> plausibility is simply not evaluated, not defaulted.
    assert result.rate_plausibility_matched is None


def test_unmatched_rate_produces_warning_but_line_still_available() -> None:
    line = GstLineInput(line_ref="L3", listed_paise=1280_00, basis="INCLUSIVE", rate_pct=Fraction(28))
    [result] = analyze_gst_lines(object(), [line], as_of_date=_AS_OF)
    assert result.is_available is True  # plausibility WARNING never blocks normalization
    assert result.rate_plausibility_matched is False
    assert result.rate_plausibility_severity == "WARNING"


def test_inclusive_line_with_unresolvable_rate_is_excluded_and_flagged_not_defaulted() -> None:
    """E12: an INCLUSIVE line with no rate_pct at all can't be normalized — it must be
    excluded and flagged, never silently treated as EXCLUSIVE or rate=0."""
    line = GstLineInput(line_ref="L4", listed_paise=1000_00, basis="INCLUSIVE", rate_pct=None)
    [result] = analyze_gst_lines(object(), [line], as_of_date=_AS_OF)
    assert result.is_available is False
    assert result.normalized_exclusive_paise is None
    assert result.unavailable_reason is not None
    assert "never guesses a rate" in result.unavailable_reason or "effective_rate" in result.unavailable_reason


def test_every_result_carries_the_section_6_6_disclaimer_verbatim() -> None:
    lines = [
        GstLineInput(line_ref="A", listed_paise=1180_00, basis="INCLUSIVE", rate_pct=Fraction(18)),
        GstLineInput(line_ref="B", listed_paise=1000_00, basis="INCLUSIVE", rate_pct=None),
        GstLineInput(line_ref="C", listed_paise=500_00, basis="EXCLUSIVE", rate_pct=None),
    ]
    results = analyze_gst_lines(object(), lines, as_of_date=_AS_OF)
    assert len(results) == 3
    for result in results:
        assert result.disclaimer == GST_DISCLAIMER


def test_guardrail_no_period_total_field_on_gst_line_result() -> None:
    """Guardrail: GstLineResult must never grow a period-total field."""
    field_names = {f.name for f in fields(GstLineResult)}
    for forbidden in ("total", "period_total", "sum", "aggregate", "summary"):
        for name in field_names:
            assert forbidden not in name.lower(), f"GstLineResult must stay line-level, found field {name!r}"


def test_guardrail_analyze_gst_lines_never_sums_across_lines() -> None:
    """Guardrail: the module performs no cross-line summation (`sum(`, `+=` accumulation
    across the `results` list, or any running total) — each line's result is appended
    independently. A crude but effective structural check via source inspection."""
    tree = ast.parse(inspect.getsource(cfo_actions_module.analyze_gst_lines))
    func_node = tree.body[0]
    assert isinstance(func_node, ast.FunctionDef)
    # Strip the docstring (prose may legitimately say "period total" while explaining the
    # guarantee) and inspect only the executable body for a `sum(...)` call or an
    # accumulator-style name/augmented-assignment.
    body = func_node.body[1:] if isinstance(func_node.body[0], ast.Expr) else func_node.body
    for node in ast.walk(ast.Module(body=body, type_ignores=[])):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "sum":
            pytest.fail("analyze_gst_lines must never call sum() — GST must stay line-level")
        if isinstance(node, ast.AugAssign):
            pytest.fail("analyze_gst_lines must never use an accumulating augmented assignment")
        if isinstance(node, ast.Name) and "total" in node.id.lower():
            pytest.fail(f"analyze_gst_lines must never name a total-style accumulator: {node.id}")
