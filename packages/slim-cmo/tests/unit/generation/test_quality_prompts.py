"""Writing-quality fixes from the first live chat: the prompts state the real target (length, count, order) from the resolved row, never invent a rule, and a thin set of confirmed
details is flagged on the result. Also the operator seed validator (a VERIFIED marketplace rule needs a real source and a check date)."""

from __future__ import annotations

import importlib.util
import sys
from datetime import date
from pathlib import Path

import pytest

from slim_cmo.constraints import FormatConstraint
from slim_cmo.generation.facts import FactInput, build_fact_context, is_thin_input
from slim_cmo.generation.prompts import component_prompt, prompt_facts, title_prompt
from slim_cmo.generation.provider import ScriptedLlmProvider
from slim_cmo.generation.standalone import generate_bullets
from slim_cmo.generation.titles import generate_title_set
from slim_cmo.types import Marketplace as M
from slim_cmo.types import SellerFactType as F

from ..factories import constraint
from .helpers import ANCHOR, MODEL, ctx, j, resolved


def pf():
    return prompt_facts(ctx())


def test_the_title_prompt_states_the_real_limit_the_order_and_forbids_padding():
    prompt = title_prompt(marketplace=M.AMAZON, facts=pf(), constraint=constraint(M.AMAZON, title_max_chars=180), count=3, existing=(), feedback=())
    assert "up to 180 characters" in prompt and "never pad" in prompt.lower().replace("never pad with filler words", "never pad")
    assert "brand, product type, key feature or material, size or capacity, colour, main use" in prompt
    assert "a style default, not a marketplace rule" in prompt  # the order is not presented as a sourced marketplace rule


def test_an_unstated_title_limit_is_not_invented_in_the_prompt():
    c = constraint(M.AMAZON, title_max_chars=None)
    prompt = title_prompt(marketplace=M.AMAZON, facts=pf(), constraint=c, count=3, existing=(), feedback=())
    assert "up to" not in prompt.split("Task:")[1].split("Reply shape")[0].replace("up to date", "")


def test_the_bullets_prompt_states_exact_count_and_length_from_the_row_and_forbids_inventing():
    c = constraint(M.AMAZON, bullet_count=5, bullet_max_chars=180)
    prompt = component_prompt(kind="BULLETS", marketplace=M.AMAZON, facts=pf(), anchor_title=ANCHOR, constraint=c, feedback=())
    assert "Write exactly 5 bullets, each at most 180 characters" in prompt
    assert "never add a fact, benefit, claim or number that DATA does not contain" in prompt


def test_description_and_keywords_guidance_come_from_the_row():
    c = constraint(M.AMAZON, description_max_chars=1500, keywords_max_count=7, keywords_max_chars=30)
    assert "at most 1500 characters" in component_prompt(kind="DESCRIPTION", marketplace=M.AMAZON, facts=pf(), anchor_title=ANCHOR, constraint=c, feedback=())
    kw = component_prompt(kind="KEYWORDS", marketplace=M.AMAZON, facts=pf(), anchor_title=ANCHOR, constraint=c, feedback=())
    assert "up to 7 keywords" in kw and "at most 30 characters" in kw


def test_thin_input_counts_only_eligible_details_beyond_product_name_and_category():
    only_name = build_fact_context([FactInput(F.ATTRIBUTE, "steel bottle", "product_name"), FactInput(F.CATEGORY, "kitchen")])
    assert is_thin_input(only_name)
    one = build_fact_context([FactInput(F.ATTRIBUTE, "steel bottle", "product_name"), FactInput(F.BRAND, "Acme")])
    assert is_thin_input(one)
    two = build_fact_context([FactInput(F.ATTRIBUTE, "steel bottle", "product_name"), FactInput(F.BRAND, "Acme"), FactInput(F.ATTRIBUTE, "1 litre", "capacity")])
    assert not is_thin_input(two)
    assert not is_thin_input(ctx())  # the shared fixture has brand, material and capacity


def test_the_result_carries_the_thin_flag():
    thin = build_fact_context([FactInput(F.ATTRIBUTE, "AquaKeep Steel Bottle", "product_name")])
    out = generate_title_set(provider=ScriptedLlmProvider([j(titles=["AquaKeep Steel Bottle"])]), model=MODEL, marketplace=M.AMAZON, resolved=resolved(), facts=thin, retry_bound=0)
    assert out.structured["thin_input"] is True
    full = generate_title_set(provider=ScriptedLlmProvider([j(titles=["AquaKeep Steel Bottle 750 ml"])]), model=MODEL, marketplace=M.AMAZON, resolved=resolved(), facts=ctx(), retry_bound=0)
    assert full.structured["thin_input"] is False


def test_the_constraint_citation_records_whether_the_rule_is_verified_or_a_fixture():
    row: FormatConstraint = constraint(M.AMAZON)
    assert row.cite()["row_kind"] == row.row_kind.value


# ------------------------------------------------------------------------------------------------ the operator seed tool
def load_seed():
    path = Path(__file__).resolve().parents[3] / "scripts" / "seed_format_constraints.py"
    spec = importlib.util.spec_from_file_location("seed_format_constraints", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod  # a dataclass in the module looks itself up here
    spec.loader.exec_module(mod)
    return mod


def rule(**over):
    base = {"marketplace": "AMAZON", "category": None, "source_url": "https://sellercentral.amazon.in/help", "verified_at": "2026-10-01", "count_rule": "UTF16_CODE_UNITS",
            "title_max_chars": 150, "title_option_count": 3, "bullet_count": 5, "bullet_max_chars": 200, "description_type": "plain", "description_max_chars": 2000,
            "keywords_max_count": 10, "keywords_max_chars": 40, "backend_terms_max_bytes": 249, "hashtags_supported": None}
    base.update(over)
    return {"rules": [base]}


TODAY = date(2026, 10, 13)


def test_a_complete_sourced_dated_rule_is_accepted():
    rows, problems = load_seed().validate(rule(), today=TODAY)
    assert problems == [] and len(rows) == 1 and rows[0].values["title_max_chars"] == 150


@pytest.mark.parametrize(("over", "needle"), [
    ({"source_url": ""}, "source_url"), ({"source_url": "https://example.invalid/test-fixture-dev"}, "source_url"), ({"source_url": "ftp://x"}, "source_url"),
    ({"verified_at": ""}, "verified_at"), ({"verified_at": "2027-01-01"}, "future"), ({"count_rule": ""}, "count_rule"), ({"count_rule": "GRAPHEMES"}, "count_rule"),
    ({"title_max_chars": None}, "title_max_chars is required"), ({"title_max_chars": 0}, "positive whole number"), ({"title_max_chars": "150"}, "positive whole number"),
    ({"title_max_chars": True}, "positive whole number"), ({"bullet_count": None}, "bullet_count is required"), ({"marketplace": "EBAY"}, "marketplace"),
    ({"backend_terms_max_bytes": None}, "backend_terms_max_bytes is required for Amazon"),
])
def test_a_rule_without_a_real_source_date_counting_rule_or_required_limit_is_refused(over, needle):
    rows, problems = load_seed().validate(rule(**over), today=TODAY)
    assert any(needle in p for p in problems), problems


def test_backend_terms_are_amazon_only_and_the_empty_template_is_refused():
    seed = load_seed()
    _, problems = seed.validate(rule(marketplace="FLIPKART", backend_terms_max_bytes=249), today=TODAY)
    assert any("only for Amazon" in p for p in problems)
    import json
    template = json.loads((Path(__file__).resolve().parents[3] / "scripts" / "format_constraints.template.json").read_text(encoding="utf-8"))
    rows, problems = seed.validate(template, today=TODAY)
    assert problems and rows is not None  # the shipped template carries no rule: it can never be loaded as is
