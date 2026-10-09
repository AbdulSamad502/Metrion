"""C4: conflict detection and composition (spec §6.32). Detection is pure code over stored rows; the block that states both values is rendered by code; a draft that
does not write a conflict's marker is never shipped."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from backend.ceo import conflicts
from backend.ceo.composer import EvidenceTable, build_prompt, compose, render_template
from backend.ceo.contract import Conflict, Figure, Ref, RefKind, Register
from backend.llm.model import Completion

T0 = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)


def _row(value: int, *, at: int = 0, **over):
    base = {
        "id": uuid.uuid4(), "metric_code": "NET_REALIZED_REVENUE", "period": "2026-09-01/2026-09-30", "grain": "TENANT_PERIOD", "target_ref": "t",
        "recognition_state": "RECOGNISED", "calculation_basis": "b", "canonical_data_version": "d1", "config_version": "1", "formula_version": "f1",
        "manual_adjustment_set": None, "is_available": True, "value_paise": value, "value_fraction_numerator": None, "value_fraction_denominator": None,
        "computed_at": T0 + timedelta(hours=at),
    }
    return {**base, **over}


def _fig(row) -> Figure:
    return Figure("Net revenue", f"₹{row['value_paise']}", Register.DERIVED, Ref(RefKind.ENGINE_RESULT, row["id"], as_of=row["computed_at"]), as_of=row["computed_at"])


def _detect(rows):
    return conflicts.metric_conflicts(rows, figure_for=_fig, what_for=lambda r: "Net revenue")


def test_same_inputs_different_values_is_a_conflict_between_the_two_most_recent_distinct_values():
    old, mid, new = _row(100, at=0), _row(200, at=1), _row(300, at=2)
    [c] = _detect([old, mid, new])
    assert c.kind == "C1_METRIC" and (c.a.ref.id, c.b.ref.id) == (new["id"], mid["id"])


def test_identical_values_are_not_a_conflict():
    assert _detect([_row(100, at=0), _row(100, at=1)]) == []


def test_different_inputs_are_an_update_not_a_conflict():
    for field, other in (("canonical_data_version", "d2"), ("config_version", "2"), ("formula_version", "f2"), ("period", "2026-08-01/2026-08-31"),
                         ("calculation_basis", "other"), ("manual_adjustment_set", [{"id": "x"}])):
        assert _detect([_row(100, at=0), _row(200, at=1, **{field: other})]) == [], field


def test_unavailable_results_are_never_compared():
    assert _detect([_row(100, at=0), _row(200, at=1, is_available=False)]) == []


def test_fractions_compare_exactly_not_as_floats():
    a = _row(0, value_paise=None, value_fraction_numerator=1, value_fraction_denominator=3)
    b = _row(0, at=1, value_paise=None, value_fraction_numerator=2, value_fraction_denominator=6)
    assert _detect([a, b]) == []  # 1/3 == 2/6


def test_manual_inputs_conflict_only_when_two_active_values_differ():
    rows = [{"id": uuid.uuid4(), "v": "25", "created_at": T0}, {"id": uuid.uuid4(), "v": "30", "created_at": T0 + timedelta(hours=1)}]

    def fig(r):
        return Figure("Target margin", f"{r['v']}%", Register.MANUAL, Ref(RefKind.SELLER_PROVIDED, r["id"], as_of=r["created_at"]), as_of=r["created_at"])

    [c] = conflicts.manual_input_conflicts(rows, comparable=lambda r: r["v"], figure_for=fig, what="Your saved target margin")
    assert c.kind == "C2_MANUAL_INPUT" and c.a.formatted_value == "30%" and c.b.formatted_value == "25%"
    assert conflicts.manual_input_conflicts(rows[:1], comparable=lambda r: r["v"], figure_for=fig, what="x") == []
    assert conflicts.manual_input_conflicts(rows, comparable=lambda r: None, figure_for=fig, what="x") == []


def _conflict() -> Conflict:
    return Conflict("C1_METRIC", "Net revenue", _fig(_row(100, at=0)), _fig(_row(200, at=1)))


def test_the_rendered_block_states_both_values_both_sources_and_that_neither_was_chosen():
    text = conflicts.render(_conflict())
    assert "₹100" in text and "₹200" in text and "Metrion's calculation" in text and "as of 2026-10-01" in text
    assert "neither has been chosen, averaged or combined" in text


def _table() -> EvidenceTable:
    return EvidenceTable(conflicts=(("C1", "Net revenue", conflicts.render(_conflict())),))


class _Model:
    def __init__(self, text: str) -> None:
        self.text = text

    def complete(self, prompt, *, max_output_tokens, **_):
        return Completion(text=self.text, wall_ms=1, output_tokens=20)


def test_the_prompt_shows_the_conflict_marker_and_no_value():
    prompt = build_prompt("Where do I stand?", "BUSINESS_STATE", _table())
    assert "{{C1}} | Net revenue has two stored values that differ" in prompt and "₹100" not in prompt and "₹200" not in prompt


def test_a_draft_that_writes_the_marker_is_shipped_with_both_values_rendered_by_code():
    out = compose(_Model("The two stored values differ, so please check the source. {{C1}}"), "q", "BUSINESS_STATE", _table())
    assert out.mode == "LLM" and "₹100" in out.text and "₹200" in out.text and "neither has been chosen" in out.text


def test_a_draft_that_omits_the_conflict_marker_falls_back_to_the_template():
    out = compose(_Model("Your revenue looks fine."), "q", "BUSINESS_STATE", _table())
    assert out.mode == "TEMPLATE_FALLBACK" and out.safety["violations"] == ["MISSING_REQUIRED"]
    assert "Conflict:" in out.text and "₹100" in out.text and "₹200" in out.text and "looks fine" not in out.text


def test_a_draft_that_states_a_value_itself_is_rejected():
    out = compose(_Model("It is ₹150 on average. {{C1}}"), "q", "BUSINESS_STATE", _table())
    assert out.mode == "TEMPLATE_FALLBACK" and "NUMERAL_CURRENCY" in out.safety["violations"]


def test_the_template_lists_the_conflict_and_a_conflict_alone_is_not_an_empty_table():
    assert not _table().is_empty() and "- Conflict: Net revenue has two different stored values" in render_template(_table())
