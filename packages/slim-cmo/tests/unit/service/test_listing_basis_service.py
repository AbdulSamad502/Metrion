"""CMO 3.0 M6 on GenerationService (spec 6.18.3, 6.18.11; acceptance N-05, N-05m, N-05u-w, N-16a-c, N-08a-b): the rules-unavailable basis is reachable only inside a full-listing request with the
operator flag on; a usable VERIFIED row always wins; configuration faults never open it; keywords are traceable; competitor input is limited to supported themes; nothing unverified is
manufactured by anything the client sends."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest

from slim_cmo.ci_inputs import CiInputs, CiInsight
from slim_cmo.generation.provider import ScriptedLlmProvider
from slim_cmo.listing.basis import FULL_LISTING
from slim_cmo.listing.context import ListingContext
from slim_cmo.service.generate import GenerationService, GroundingRequest, Intake
from slim_cmo.types import ConstraintRowKind as K
from slim_cmo.types import GenerationStatus as S
from slim_cmo.types import Marketplace as M
from slim_cmo.types import OutputType as O

from ..factories import NOW, constraint
from ..generation.helpers import GOOD_PACK, MODEL, j
from .fakes import ACTOR, GOOD_CONFIG, InMemoryStore, clock

TITLES5 = ["AquaKeep Steel Bottle 750 ml", "AquaKeep Stainless Water Bottle", "AquaKeep Steel Water Bottle 750 ml", "AquaKeep 750 ml Steel Flask", "AquaKeep Everyday Steel Bottle"]
TS5 = j(titles=TITLES5)
VOCAB = ("steel bottle", "water bottle", "750 ml")
LISTING = ListingContext(workflow=FULL_LISTING, keyword_vocab=VOCAB, do_not_claim=("Leakproof",))
INTAKE = Intake(request_key="r1", sku="SKU1", brand="AquaKeep", attributes=(("material", "stainless steel"), ("capacity", "750 ml")))
RU_ON = {**GOOD_CONFIG, "listing_unverified_rules_enabled": True, "rules_unavailable_bullet_target": 3}
TITLE = "AquaKeep Steel Bottle 750 ml"
GOOD_TERMS = j(terms=["steel bottle", "water bottle"])


def make(replies=(), *, constraints=None, config=None):
    store = InMemoryStore(constraints=[] if constraints is None else constraints, config=dict(config or RU_ON))
    provider = ScriptedLlmProvider(replies)
    return GenerationService(store, provider, model=MODEL, clock=clock(NOW)), store, provider


def only(run):
    assert len(run.artefacts) == 1
    return run.artefacts[0]


# ------------------------------------------------------------------ titles inside the workflow (Q32)
def test_title_steps_inside_the_workflow_run_on_the_unverified_basis_with_no_constraint_reference():
    svc, store, _p = make([TS5])
    run = svc.generate_title_sets(ACTOR, replace(INTAKE, listing=LISTING), [M.AMAZON])
    a = only(run)
    assert a.status is S.COMPLETE and run.units_to_bill == 1
    rec = store.rows()[0]
    assert rec.format_constraint_ref is None
    s = rec.output_structured
    assert s["rules_basis"] == "UNVERIFIED" and s["workflow"] == FULL_LISTING and s["constraint"]["rules_basis"] == "UNVERIFIED" and s["constraint"]["source_url"] is None
    assert s["count_rule"] is None and s["delivered_option_count"] == 5 and not s["short"]
    assert "title_max_chars" in s["unverified_limits"]


def test_a_title_request_on_its_own_keeps_c13_even_with_the_flag_on():
    svc, store, p = make([TS5])
    a = only(svc.generate_title_sets(ACTOR, INTAKE, [M.AMAZON]))  # no listing context = not a full-listing workflow
    assert a.status is S.FAILED and a.failure is not None and a.failure.detail["unavailable_reason"] in {"NO_ROW", "NO_VERIFIED_ROW"}
    assert p.calls == 0 and store.rows()[0].format_constraint_ref is None and "rules_basis" not in store.rows()[0].output_structured


@pytest.mark.parametrize("workflow", [None, "STANDALONE", "full_listing", "", "FULL-LISTING"])
def test_only_the_exact_server_side_marker_opens_the_basis(workflow):
    svc, _s, p = make([TS5])
    ctx = None if workflow is None else ListingContext(workflow=workflow)
    a = only(svc.generate_title_sets(ACTOR, replace(INTAKE, listing=ctx), [M.AMAZON]))
    assert a.status is S.FAILED and p.calls == 0


@pytest.mark.parametrize("flag", [False, None, "false", "yes", 1, "1", 0, "", "TRUE_"])
def test_the_flag_defaults_to_off_and_blocks_with_the_reason(flag):
    cfg = {k: v for k, v in RU_ON.items() if k != "listing_unverified_rules_enabled"}
    if flag is not None:
        cfg["listing_unverified_rules_enabled"] = flag
    svc, _s, p = make([TS5], config=cfg)
    a = only(svc.generate_title_sets(ACTOR, replace(INTAKE, listing=LISTING), [M.AMAZON]))
    assert a.status is S.FAILED and "unverified drafts are not enabled" in a.failure.reason and p.calls == 0


# ------------------------------------------------------------------ priority and scope
def test_a_usable_verified_row_always_wins_even_with_the_flag_on():
    svc, store, _p = make([j(titles=["AquaKeep Steel Bottle 750 ml", "AquaKeep Stainless Water Bottle", "AquaKeep Bottle 750 ml"])], constraints=[constraint(M.AMAZON)])
    a = only(svc.generate_title_sets(ACTOR, replace(INTAKE, listing=LISTING), [M.AMAZON]))
    rec = store.rows()[0]
    assert a.status is S.COMPLETE and rec.format_constraint_ref is not None
    assert rec.output_structured["rules_basis"] == "VERIFIED" and rec.output_structured["constraint"]["source_url"]
    assert rec.output_structured["count_rule"] == "UTF16_CODE_UNITS"


def test_a_stale_row_opens_the_basis_and_a_fixture_row_is_invisible_in_production():
    stale = constraint(M.AMAZON, verified_at=NOW - timedelta(days=400))
    svc, store, _p = make([TS5], constraints=[stale])
    assert only(svc.generate_title_sets(ACTOR, replace(INTAKE, listing=LISTING), [M.AMAZON])).status is S.COMPLETE
    assert store.rows()[0].output_structured["rules_basis"] == "UNVERIFIED"
    fixture_only = [constraint(M.AMAZON, row_kind=K.TEST_FIXTURE)]
    svc2, store2, _p2 = make([TS5], constraints=fixture_only)
    assert only(svc2.generate_title_sets(ACTOR, replace(INTAKE, listing=LISTING), [M.AMAZON])).status is S.COMPLETE
    assert store2.rows()[0].output_structured["rules_basis"] == "UNVERIFIED"


def test_a_row_without_a_counting_rule_opens_the_basis():
    svc, store, _p = make([TS5], constraints=[constraint(M.AMAZON, count_rule=None)])
    assert only(svc.generate_title_sets(ACTOR, replace(INTAKE, listing=LISTING), [M.AMAZON])).status is S.COMPLETE
    assert store.rows()[0].output_structured["rules_basis"] == "UNVERIFIED"


@pytest.mark.parametrize("bad", [{"format_constraint_max_age_days": None}, {"format_constraint_max_age_days": 0}, {"internal_retry_bound": -1}])
def test_a_configuration_fault_never_opens_the_basis(bad):
    cfg = {**RU_ON, **bad}
    cfg = {k: v for k, v in cfg.items() if v is not None}
    svc, _s, p = make([TS5], config=cfg)
    a = only(svc.generate_title_sets(ACTOR, replace(INTAKE, listing=LISTING), [M.AMAZON]))
    assert a.status is S.FAILED and a.failure.code.value == "CONFIG_MISSING" and p.calls == 0


@pytest.mark.parametrize("output_type", [O.DESCRIPTION, O.BULLETS, O.KEYWORDS])
def test_other_artefact_actions_keep_c13_inside_a_listing_request(output_type):
    svc, _s, p = make([j(description="x", bullets=["a"], keywords=["k"])])
    a = only(svc.generate_standalone(ACTOR, replace(INTAKE, listing=LISTING), output_type, M.AMAZON, GroundingRequest(seller_title=TITLE)))
    assert a.status is S.FAILED and p.calls == 0


def test_hashtags_are_unaffected_by_the_basis():
    svc, store, _p = make([j(hashtags=["#steelbottle"])])
    a = only(svc.generate_hashtags(ACTOR, replace(INTAKE, listing=LISTING)))
    assert a.status is S.COMPLETE and "rules_basis" not in store.rows()[0].output_structured


# ------------------------------------------------------------------ the listing copy pack
def test_the_pack_follows_the_draft_bullet_target_and_is_labelled_unverified():
    svc, store, p = make([GOOD_PACK])
    run = svc.generate_listing_copy(ACTOR, replace(INTAKE, listing=LISTING), M.AMAZON, GroundingRequest(seller_title=TITLE))
    a = only(run)
    s = store.rows()[0].output_structured
    assert a.status is S.COMPLETE and run.units_to_bill == 1 and store.rows()[0].format_constraint_ref is None
    assert s["rules_basis"] == "UNVERIFIED" and len(s["bullets"]) == 3 and s["workflow"] == FULL_LISTING
    assert "keywords_allowed" in p.prompts[0] and "do_not_claim" in p.prompts[0] and "character_counting" not in p.prompts[0]


def test_a_missing_or_invalid_bullet_target_blocks_the_pack_with_no_hidden_default():
    for bad in (None, 0, "five", -2, True):
        cfg = {k: v for k, v in RU_ON.items() if k != "rules_unavailable_bullet_target"}
        if bad is not None:
            cfg["rules_unavailable_bullet_target"] = bad
        svc, store, p = make([GOOD_PACK], config=cfg)
        a = only(svc.generate_listing_copy(ACTOR, replace(INTAKE, listing=LISTING), M.AMAZON, GroundingRequest(seller_title=TITLE)))
        assert a.status is S.FAILED and a.failure.detail["unavailable_reason"] == "CONFIG_MISSING" and p.calls == 0
        assert "rules_unavailable_bullet_target" in a.failure.detail["missing"]


def test_a_keyword_outside_the_researched_candidates_is_rejected_and_retried():
    loose = j(description="A 750 ml stainless steel bottle from AquaKeep.", bullets=["Stainless steel build", "750 ml capacity", "Easy to carry"], keywords=["steel bottle", "cheap flask"])
    svc, store, p = make([loose, GOOD_PACK])
    a = only(svc.generate_listing_copy(ACTOR, replace(INTAKE, listing=LISTING), M.AMAZON, GroundingRequest(seller_title=TITLE)))
    assert a.status is S.COMPLETE and p.calls == 2 and store.rows()[0].output_structured["keywords"] == ["steel bottle", "water bottle", "750 ml"]
    assert "NOT_TRACEABLE" in p.prompts[1]


def test_a_pack_that_keeps_an_untraceable_keyword_fails_with_zero_units_and_no_partial_text():
    loose = j(description="A 750 ml stainless steel bottle from AquaKeep.", bullets=["Stainless steel build", "750 ml capacity", "Easy to carry"], keywords=["cheap flask"])
    svc, store, _p = make([loose, loose])
    run = svc.generate_listing_copy(ACTOR, replace(INTAKE, listing=LISTING), M.AMAZON, GroundingRequest(seller_title=TITLE))
    rec = store.rows()[0]
    assert only(run).status is S.FAILED and run.units_to_bill == 0 and rec.output_text is None and "description" not in rec.output_structured


def test_a_normal_request_without_a_listing_context_is_unchanged():
    svc, store, p = make([GOOD_PACK], constraints=[constraint(M.AMAZON)], config=GOOD_CONFIG)
    a = only(svc.generate_listing_copy(ACTOR, INTAKE, M.AMAZON, GroundingRequest(seller_title=TITLE)))
    assert a.status is S.COMPLETE and "keywords_allowed" not in p.prompts[0] and store.rows()[0].output_structured["rules_basis"] == "VERIFIED"
    assert "workflow" not in store.rows()[0].output_structured


# ------------------------------------------------------------------ backend terms (Amazon only, cap unstated)
def test_backend_terms_measure_the_bytes_and_enforce_no_cap_on_the_unverified_basis():
    svc, store, _p = make([GOOD_TERMS])
    a = only(svc.generate_standalone(ACTOR, replace(INTAKE, listing=LISTING), O.BACKEND_TERMS, M.AMAZON, GroundingRequest(seller_title=TITLE)))
    s = store.rows()[0].output_structured
    assert a.status is S.COMPLETE and s["max_bytes"] is None and s["byte_count"] == len("steel bottle water bottle") and s["rules_basis"] == "UNVERIFIED"


def test_backend_terms_must_be_researched_candidates_and_exist_only_for_amazon():
    svc, store, _p = make([j(terms=["steel bottle", "cheap flask"]), j(terms=["cheap flask"])])
    a = only(svc.generate_standalone(ACTOR, replace(INTAKE, listing=LISTING), O.BACKEND_TERMS, M.AMAZON, GroundingRequest(seller_title=TITLE)))
    assert a.status is S.FAILED and store.rows()[0].output_text is None
    svc2, _s2, _p2 = make([GOOD_TERMS])
    with pytest.raises(ValueError):
        svc2.generate_standalone(ACTOR, replace(INTAKE, listing=LISTING), O.BACKEND_TERMS, M.FLIPKART, GroundingRequest(seller_title=TITLE))


def test_the_verified_cap_is_still_required_and_enforced_when_a_verified_row_exists():
    svc, _s, _p = make([j(terms=["steel bottle", "water bottle"] * 20)], constraints=[constraint(M.AMAZON, backend_terms_max_bytes=20)])
    a = only(svc.generate_standalone(ACTOR, replace(INTAKE, listing=LISTING), O.BACKEND_TERMS, M.AMAZON, GroundingRequest(seller_title=TITLE)))
    assert a.status is S.FAILED  # over the verified cap: never delivered


# ------------------------------------------------------------------ competitor input is limited to supported themes
def _ci():
    return CiInputs(insights=(CiInsight("i1", keyword_themes=("steel", "insulated", "bpa")),), references=("Competitor wording about a wide mouth",))


def test_the_model_sees_only_competitor_themes_the_confirmed_facts_support():
    svc, store, p = make([GOOD_PACK])
    svc.generate_listing_copy(ACTOR, replace(INTAKE, listing=LISTING, ci_inputs=_ci()), M.AMAZON, GroundingRequest(seller_title=TITLE))
    prompt = p.prompts[0]
    assert "market_themes_other_sellers_use" in prompt and '"steel"' in prompt
    assert "insulated" not in prompt and "bpa" not in prompt
    rec = store.rows()[0]
    assert rec.input_mode == "CEO_BROKERED_CI" and rec.ci_inputs_snapshot["themes_offered"] == ["steel"]


def test_without_a_supported_theme_the_pack_is_independent_and_no_competitor_data_is_stored():
    ci = CiInputs(insights=(CiInsight("i1", keyword_themes=("insulated", "bpa")),), references=("x y z",))
    svc, store, p = make([GOOD_PACK])
    svc.generate_listing_copy(ACTOR, replace(INTAKE, listing=LISTING, ci_inputs=ci), M.AMAZON, GroundingRequest(seller_title=TITLE))
    assert "market_themes" not in p.prompts[0] and store.rows()[0].input_mode == "INDEPENDENT" and store.rows()[0].ci_inputs_snapshot is None


# ------------------------------------------------------------------ idempotency and tenant
def test_a_repeated_request_serves_the_same_rows_with_no_second_call_and_no_second_unit():
    svc, store, p = make([GOOD_PACK, GOOD_PACK])
    g = GroundingRequest(seller_title=TITLE)
    first = svc.generate_listing_copy(ACTOR, replace(INTAKE, listing=LISTING), M.AMAZON, g)
    again = svc.generate_listing_copy(ACTOR, replace(INTAKE, listing=LISTING), M.AMAZON, g)
    assert p.calls == 1 and len(store.rows()) == 1 and first.units_to_bill == 1 and again.units_to_bill == 0
    assert again.artefacts[0].reused and again.artefacts[0].generation_id == first.artefacts[0].generation_id
