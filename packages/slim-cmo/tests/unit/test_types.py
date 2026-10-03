"""`slim_cmo.types` — the shared vocabulary and the artefact groupings the schema enforces.

The DB-agreement half of this contract lives in tests/integration/test_schema_constraints.py;
here we pin the in-process invariants that need no database.
"""

from __future__ import annotations

import pytest

from slim_cmo import types as t


def test_every_enum_is_string_valued_and_upper_snake():
    enums = [
        t.Marketplace, t.OutputType, t.InputMode, t.GenerationStatus, t.GroundingBasis,
        t.AttributeBasis, t.TrustState, t.ImageAnalysisState, t.ImageAssetStatus,
        t.SellerFactType, t.NicheTermOrigin, t.NicheTermStatus, t.ConstraintRowKind, t.TrendSection,
    ]
    for enum in enums:
        for member in enum:
            assert isinstance(member.value, str)
            assert member.value == member.name, f"{enum.__name__}.{member.name} must equal its value"
            assert member.value.isupper() and " " not in member.value


def test_marketplaces_are_exactly_the_three_v1_marketplaces():
    assert {m.value for m in t.Marketplace} == {"AMAZON", "FLIPKART", "MEESHO"}


def test_output_types_cover_every_c3_artefact():
    assert {o.value for o in t.OutputType} == {
        "TITLE_SET", "LISTING_COPY", "DESCRIPTION", "BULLETS", "KEYWORDS",
        "BACKEND_TERMS", "HASHTAGS", "CATALOG_ANSWER", "TREND_REPORT",
    }


def test_gst_is_not_a_cmo_output_type():
    """C4: CMO has no GST path, so no output type may name one."""
    assert not any("GST" in o.value or "TAX" in o.value for o in t.OutputType)


def test_artefact_groupings_are_consistent():
    assert t.GROUNDED_OUTPUT_TYPES <= t.MARKETPLACE_SCOPED_OUTPUT_TYPES
    assert t.MARKETPLACE_SCOPED_OUTPUT_TYPES == t.CONSTRAINT_BOUND_OUTPUT_TYPES
    assert t.OutputType.TITLE_SET in t.CONSTRAINT_BOUND_OUTPUT_TYPES
    assert t.OutputType.TITLE_SET not in t.GROUNDED_OUTPUT_TYPES  # a title set is what grounds the others
    for free in (t.OutputType.HASHTAGS, t.OutputType.CATALOG_ANSWER, t.OutputType.TREND_REPORT):
        assert free not in t.MARKETPLACE_SCOPED_OUTPUT_TYPES


def test_only_complete_consumes_a_unit_so_there_are_exactly_two_terminal_states():
    assert {s.value for s in t.GenerationStatus} == {"COMPLETE", "FAILED"}


def test_trust_states_and_vision_bases():
    assert {s.value for s in t.TrustState} == {"UNVERIFIED_HINT", "EVAL_PASSED"}
    assert {b.value for b in t.AttributeBasis} == {
        "SELLER_PROVIDED", "IMAGE_OBSERVED", "SOURCE_DERIVED", "ESTIMATED", "UNKNOWN",
    }


def test_trend_sections_are_the_five_researched_ones():
    assert {s.value for s in t.TrendSection} == {
        "NICHE", "MARKET_NEWS", "REPORTED_TACTICS", "NEW_PRODUCTS_BUZZ", "ADJACENT",
    }


@pytest.mark.parametrize("name", ["INTERPRETATION", "EVIDENCE"])
def test_derived_sections_are_not_researched_sections(name):
    assert name not in {s.value for s in t.TrendSection}
