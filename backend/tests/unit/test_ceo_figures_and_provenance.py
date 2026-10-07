"""Figure formatting and the provenance gate (spec §6.5, §6.13, §6.15 R3) — pure, no database."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from backend.ceo import provenance
from backend.ceo.contract import Figure, Ref, RefKind, Register
from backend.ceo.figure_format import UNAVAILABLE, format_paise, format_percent_number, register_for

T = datetime(2026, 10, 7, tzinfo=timezone.utc)


# ----------------------------------------------------------------------------------------- formatting
@pytest.mark.parametrize("value", [0, 1, 99, 100, 101, 12345, 14230000, -5, -100, -12345, 10**15, -(10**15)])
def test_money_format_is_identical_to_the_cfo_narration_formatter(value):
    """The two formatters must never drift (the CEO's one allowed unit conversion mirrors CFO's)."""
    from backend.services.cfo_actions import _format_paise_for_narration

    assert format_paise(value) == _format_paise_for_narration(value, is_available=True)


def test_unavailable_money_is_never_rendered_as_zero():
    assert format_paise(None) == UNAVAILABLE
    assert format_paise(0, is_available=False) == UNAVAILABLE
    assert format_paise(0) == "₹0.00"  # an available zero is still a real, distinct value


@pytest.mark.parametrize("available, confidence", [(True, "VERIFIED"), (True, "DERIVED"), (True, "MANUAL"), (True, "PROVISIONAL"),
                                                  (False, "VERIFIED"), (True, "SOMETHING_NEW"), (True, None)])
def test_register_matches_the_cfo_mapping_and_never_invents_a_sixth(available, confidence):
    from backend.services.cfo_actions import _register_for

    mine = register_for(is_available=available, confidence=confidence)
    if confidence in (None, "SOMETHING_NEW") and available:
        assert mine is Register.UNAVAILABLE  # an unknown confidence is never shown as verified
    else:
        assert mine.value == _register_for(SimpleNamespace(is_available=available, confidence=confidence))


def test_provisional_is_derived_never_estimate():
    assert register_for(is_available=True, confidence="PROVISIONAL") is Register.DERIVED


@pytest.mark.parametrize("n, d, text", [(25, 2, "12.5%"), (1, 10, "0.1%"), (0, 5, "0%"), (100, 3, "33.33%"), (200, 3, "66.67%"), (-25, 2, "-12.5%"), (100, 1, "100%"), (1, 1000, "0%"), (5, 1000, "0.01%"), (1, 200, "0.01%"), (1, 10000, "0%")])
def test_percent_number_display_uses_the_percent_number_scale(n, d, text):
    assert format_percent_number(n, d) == text


def test_percent_number_without_a_denominator_is_unavailable():
    assert format_percent_number(1, 0) == UNAVAILABLE and format_percent_number(None, 5) == UNAVAILABLE


# ----------------------------------------------------------------------------------------- refs
def test_a_report_field_ref_must_name_its_source():
    with pytest.raises(ValueError):
        Ref(RefKind.AGENT_REPORT_FIELD, uuid.uuid4())
    assert Ref(RefKind.AGENT_REPORT_FIELD, uuid.uuid4(), source="leak_finding")


def test_ref_json_round_trip():
    ref = Ref(RefKind.AGENT_REPORT_FIELD, uuid.uuid4(), source="leak_finding", as_of=T)
    assert Ref.from_json(ref.to_json()) == ref
    plain = Ref(RefKind.ENGINE_RESULT, uuid.uuid4())
    assert Ref.from_json(plain.to_json()) == plain and "source" not in plain.to_json()


def test_extract_refs_collects_only_what_the_specialist_reported():
    a, b, c, d = (uuid.uuid4() for _ in range(4))
    payload = {
        "engineResultRef": str(a),
        "nested": {"headlineEngineResultRef": str(b), "list": [{"sourceEngineResultRefs": [str(c), "not-a-uuid"]}]},
        "feasibilityEstimateRef": str(d),
        "somethingElse": str(uuid.uuid4()),  # a UUID under an unrelated key is NOT a ref
        "engineResultRefs": [str(a)],  # duplicates collapse
    }
    refs = provenance.default_extract_refs(payload)
    assert {(r.kind, r.id) for r in refs} == {(RefKind.ENGINE_RESULT, a), (RefKind.ENGINE_RESULT, b), (RefKind.ENGINE_RESULT, c), (RefKind.ESTIMATE, d)}
    assert provenance.default_extract_refs({"nothing": "here"}) == []  # never invents a ref


def test_report_pointers_are_ids_of_the_specialists_own_records_only():
    gid, junk = uuid.uuid4(), uuid.uuid4()
    out = provenance.report_pointers({"generationId": str(gid), "agentRunId": "nope", "price": "123", "label": str(junk)})
    assert out == {"generationId": str(gid)}


# ----------------------------------------------------------------------------------------- the gate
def _fig(ref: Ref, register: Register = Register.VERIFIED, label: str = "Net revenue") -> Figure:
    return Figure(label=label, formatted_value="₹1.00", register=register, ref=ref)


def test_unresolvable_ref_is_dropped_and_the_gap_is_named():
    ref = Ref(RefKind.ENGINE_RESULT, uuid.uuid4())
    result = provenance.gate_figures(uuid.uuid4(), [_fig(ref)], resolvers={(RefKind.ENGINE_RESULT, None): lambda t, i: None})
    assert result.kept == () and result.gaps[0].code == "UNRESOLVED_REF" and "Net revenue" in result.gaps[0].message


def test_resolvable_ref_is_kept_and_stamped_with_as_of():
    ref = Ref(RefKind.ENGINE_RESULT, uuid.uuid4())
    res = {(RefKind.ENGINE_RESULT, None): lambda t, i: {"id": i, "computed_at": T, "is_available": True}}
    result = provenance.gate_figures(uuid.uuid4(), [_fig(ref)], resolvers=res)
    assert len(result.kept) == 1 and result.kept[0].as_of == T and result.gaps == ()


def test_engine_result_and_estimate_refs_are_never_interchangeable():
    """An ENGINE_RESULT ref must not resolve through the estimate resolver (CLAUDE.md: different contracts)."""
    ident = uuid.uuid4()
    only_estimates = {(RefKind.ESTIMATE, None): lambda t, i: {"id": i}}
    assert provenance.resolve_ref(uuid.uuid4(), Ref(RefKind.ENGINE_RESULT, ident), resolvers=only_estimates).found is False
    only_engine = {(RefKind.ENGINE_RESULT, None): lambda t, i: {"id": i}}
    assert provenance.resolve_ref(uuid.uuid4(), Ref(RefKind.ESTIMATE, ident), resolvers=only_engine).found is False


def test_an_unknown_report_source_cannot_resolve():
    ref = Ref(RefKind.AGENT_REPORT_FIELD, uuid.uuid4(), source="some_table_we_never_registered")
    assert provenance.resolve_ref(uuid.uuid4(), ref, resolvers={(RefKind.AGENT_REPORT_FIELD, "leak_finding"): lambda t, i: {"id": i}}).found is False


def test_a_figure_claiming_a_value_whose_source_is_unavailable_is_dropped():
    ref = Ref(RefKind.ENGINE_RESULT, uuid.uuid4())
    res = {(RefKind.ENGINE_RESULT, None): lambda t, i: {"id": i, "computed_at": T, "is_available": False}}
    dropped = provenance.gate_figures(uuid.uuid4(), [_fig(ref, Register.VERIFIED)], resolvers=res)
    assert dropped.kept == () and dropped.gaps[0].code == "UNAVAILABLE_AS_REAL"
    kept = provenance.gate_figures(uuid.uuid4(), [_fig(ref, Register.UNAVAILABLE)], resolvers=res)
    assert len(kept.kept) == 1  # an honestly-UNAVAILABLE figure is fine


def test_the_gate_scopes_resolution_to_the_callers_tenant():
    tenant = uuid.uuid4()
    seen: list[uuid.UUID] = []
    ref = Ref(RefKind.ENGINE_RESULT, uuid.uuid4())

    def resolver(tenant_id, ref_id):
        seen.append(tenant_id)
        return {"id": ref_id, "computed_at": T, "is_available": True}

    provenance.gate_figures(tenant, [_fig(ref)], resolvers={(RefKind.ENGINE_RESULT, None): resolver})
    assert seen == [tenant]
