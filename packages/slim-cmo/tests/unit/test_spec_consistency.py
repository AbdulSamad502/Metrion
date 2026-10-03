"""Anti-drift: the identifiers the code uses must be the ones the approved spec names.

Skipped when the docs tree is not present (e.g. the package is installed outside the
monorepo). These checks read the spec as text - they prove names agree, not that prose is
right; the behaviour is proven elsewhere."""

from __future__ import annotations

import pathlib
import re

import pytest

from slim_cmo import billing, config, forbidden, narration
from slim_cmo.trends import interpretation, risk
from slim_cmo.types import OutputType, TrendSection

ROOT = pathlib.Path(__file__).resolve().parents[4]
SPEC = ROOT / "docs" / "specs" / "slim-cmo-agent.md"

pytestmark = pytest.mark.skipif(not SPEC.exists(), reason="docs/specs not available in this checkout")


@pytest.fixture(scope="module")
def spec() -> str:
    return SPEC.read_text(encoding="utf-8")


def test_every_config_key_is_documented_in_the_spec(spec):
    for key in (*config.TREND_REQUIRED_KEYS, *config.TREND_OPTIONAL_KEYS, *config.GENERATION_REQUIRED_KEYS, *config.HASHTAG_REQUIRED_KEYS):
        assert f"`{key}`" in spec, f"config key {key} is not named in slim-cmo-agent.md"


def test_every_action_id_is_documented_in_the_spec(spec):
    for action in billing.Action:
        assert f"`{action.value}`" in spec, f"{action.value} is not named in slim-cmo-agent.md"


def test_no_gst_action_exists_and_the_spec_agrees(spec):
    assert "`cmo.gst_answer` is **removed**" in spec
    assert not any("gst" in a.value for a in billing.Action)


def test_every_output_type_and_section_is_documented(spec):
    for t in OutputType:
        assert t.value in spec
    for s in TrendSection:
        assert s.value in spec


def test_the_policy_and_interpretation_lines_match_the_spec_wording(spec):
    assert risk.POLICY_CHECK_LINE in spec
    assert interpretation.INTERPRETATION_LABEL.replace("—", "—") in spec


def test_action_types_match_the_spec(spec):
    for action in interpretation.ACTION_TYPES:
        assert action in spec


def test_the_unit_table_in_the_spec_says_one_unit_per_artefact(spec):
    section = spec[spec.index("#### 8.1.1"): spec.index("### 8.2")]
    for needle in ("`TITLE_SET`", "`LISTING_COPY`", "`HASHTAGS`", "`BACKEND_TERMS`", "`TREND_REPORT`"):
        assert needle in section
    assert "**1 per marketplace delivered**" in section
    assert billing.UNITS_PER_ARTEFACT[OutputType.LISTING_COPY] == 1  # the pack is ONE unit (round 2)


def test_forbidden_categories_cover_what_the_spec_lists(spec):
    text = spec[spec.index("Deterministic enforcement in code"): spec.index("**Atomic outcome.**")]
    for word in ("price figures", "GST/tax", "trending/bestseller", "unsupported claims", "URLs/contact"):
        assert word in text
    assert {c.value for c in forbidden.ForbiddenCategory} == {"PRICE", "TAX", "DEMAND_CLAIM", "REGULATED", "CONTACT"}


def test_the_spec_names_every_narration_surface_we_implement(spec):
    assert "narration" in spec.lower() and callable(narration.check_trend_prose) and callable(narration.check_copy_prose)
    assert re.search(r"attention.{0,20}demand", spec, re.I)


def test_the_p2_review_decisions_are_recorded_in_the_spec(spec):
    for needle in (
        "exact only", "no similarity threshold", "`count_rule`", "COUNTING_RULE_UNVERIFIED", "implementation fallback, not a marketplace rule",
        "internal implementation limit", "niche_stopwords_extra", "niche_stopwords_exclude", "does not modify the stored `product_image_analysis` row",
        "fair price", "UNASSESSED", "OFFICIAL_MARKETPLACE",
    ):
        assert needle in spec, needle
    for ac in ("AC36", "AC37", "AC38", "AC39", "AC40"):
        assert f"| {ac} |" in spec


def test_the_request_key_limit_in_the_spec_is_the_one_in_the_code(spec):
    assert f"1–{billing.MAX_REQUEST_KEY_CHARS} characters" in spec


def test_the_supported_counting_rules_in_the_spec_are_the_ones_in_the_code(spec):
    from slim_cmo.types import CountRule

    for rule in CountRule:
        assert rule.value in spec
