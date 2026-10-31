"""Retry #2 of a listing pack is a short targeted repair when the only problem was an unsupported claim (P10 follow-up from the real
qwen3:8b run). Scripted provider; asserts the repair prompt, the splice, the full re-validation and the billing boundary."""

from __future__ import annotations

from dataclasses import replace

from slim_cmo.service.generate import GroundingRequest
from slim_cmo.types import GenerationStatus as S
from slim_cmo.types import Marketplace as M

from ..generation.helpers import j
from .fakes import ACTOR, InMemoryStore
from .test_generation_service import INTAKE, approved, make

OK_BULLETS = ["Stainless steel build", "750 ml capacity", "Easy to carry"]
DESC = "A 750 ml stainless steel bottle from AquaKeep for everyday use."
KW = ["steel bottle", "water bottle", "750 ml"]


def pack(description=DESC, bullets=OK_BULLETS, keywords=KW):
    return j(description=description, bullets=bullets, keywords=keywords)


def run_copy(replies, intake=INTAKE):
    store = InMemoryStore()
    ap = approved(store)
    svc, _s, prov = make(replies, store)
    run = svc.generate_listing_copy(ACTOR, replace(intake, request_key="rc"), M.AMAZON, GroundingRequest(approval_id=ap.approval_id))
    return run, store, prov


def copy_prompts(prov):
    return [p for p in prov.prompts if "listing copy pack" in p or "write ONLY" in p]


def test_unsupported_performance_claim_is_repaired_by_replacing_only_that_bullet():
    bad = pack(bullets=["Stainless steel build", "Keeps drinks cold for hours", "Easy to carry"])
    run, store, prov = run_copy([bad, pack(description="", bullets=["750 ml capacity"], keywords=[])])
    a = run.artefacts[0]
    assert a.status is S.COMPLETE and run.units_to_bill == 1
    row = next(r for r in store.rows() if r.output_type.name == "LISTING_COPY")
    assert row.output_structured["bullets"] == ["Stainless steel build", "750 ml capacity", "Easy to carry"]
    assert row.output_structured["description"] == DESC and row.output_structured["attempts"] == 2
    repair_prompt = prov.prompts[-1]
    assert "write ONLY" in repair_prompt and "1 new bullet" in repair_prompt and "hot, cold or temperature" in repair_prompt
    assert "cold for hours" not in repair_prompt.lower() and "new description" not in repair_prompt  # rejected text never re-sent; untouched units not re-requested


def test_unsupported_contents_claim_in_the_description_is_repaired():
    bad = pack(description="A steel bottle. Includes a travel pouch and a cleaning brush.")
    run, store, prov = run_copy([bad, pack(description=DESC, bullets=[], keywords=[])])
    assert run.artefacts[0].status is S.COMPLETE
    assert "pouch" not in str([r.output_structured for r in store.rows()])
    assert "new description" in prov.prompts[-1] and "what is included" in prov.prompts[-1] and "in this order" not in prov.prompts[-1]


def test_unsupported_energy_claim_is_repaired():
    bad = pack(bullets=["Stainless steel build", "Energy-efficient and saves power", "Easy to carry"])
    run, _store, prov = run_copy([bad, pack(description="", bullets=["750 ml capacity"], keywords=[])])
    assert run.artefacts[0].status is S.COMPLETE and "energy" in prov.prompts[-1]


def test_a_performance_claim_the_seller_stated_is_delivered_on_the_first_attempt():
    intake = replace(INTAKE, attributes=(*INTAKE.attributes, ("insulation", "keeps drinks cold for 12 hours")))
    ok = pack(bullets=["Stainless steel build", "Keeps drinks cold for 12 hours", "Easy to carry"])
    run, _store, prov = run_copy([ok], intake)
    assert run.artefacts[0].status is S.COMPLETE and len(copy_prompts(prov)) == 1


def test_ordinary_descriptive_wording_is_not_flagged_and_needs_no_repair():
    ok = pack(description="A durable, stylish 750 ml stainless steel bottle from AquaKeep, made for everyday use.", bullets=["Durable stainless steel build", "750 ml capacity for daily needs", "Easy to carry"])
    run, _store, prov = run_copy([ok])
    assert run.artefacts[0].status is S.COMPLETE and len(copy_prompts(prov)) == 1


def test_second_attempt_that_still_contains_a_claim_fails_the_pack_and_bills_nothing():
    bad = pack(bullets=["Stainless steel build", "Keeps drinks cold for hours", "Easy to carry"])
    still_bad = pack(description="", bullets=["Leak-proof and rust-proof"], keywords=[])
    run, store, prov = run_copy([bad, still_bad])
    a = run.artefacts[0]
    assert a.status is S.FAILED and run.units_to_bill == 0 and len(prov.prompts) >= 2 and len([p for p in prov.prompts if "write ONLY" in p]) == 1
    row = next(r for r in store.rows() if r.output_type.name == "LISTING_COPY")
    assert row.status is S.FAILED and row.output_text is None
    assert "proof" not in str(row.output_structured).lower() and "cold for hours" not in str(row.output_structured).lower()


def test_a_repair_reply_with_too_few_bullets_is_never_spliced():
    bad = pack(bullets=["Stainless steel build", "Keeps drinks cold for hours", "Keeps it hot for hours"])
    run, _store, _prov = run_copy([bad, pack(description="", bullets=["750 ml capacity"], keywords=[])])
    assert run.artefacts[0].status is S.FAILED and run.units_to_bill == 0


def test_extra_units_in_a_repair_reply_are_discarded_not_used():
    bad = pack(bullets=["Stainless steel build", "Keeps drinks cold for hours", "Easy to carry"])
    chatty = pack(description="Keeps cold for hours", bullets=["750 ml capacity", "Leak-proof extra"], keywords=["leak proof"])
    run, store, _prov = run_copy([bad, chatty])
    row = next(r for r in store.rows() if r.output_type.name == "LISTING_COPY")
    assert row.status is S.COMPLETE and row.output_structured["bullets"] == ["Stainless steel build", "750 ml capacity", "Easy to carry"]
    assert row.output_structured["description"] == DESC and row.output_structured["keywords"] == KW


def test_a_structural_violation_still_regenerates_the_whole_pack_not_a_repair():
    too_long = pack(bullets=["Stainless steel build " * 10, "750 ml capacity", "Easy to carry"])
    run, _store, prov = run_copy([too_long, pack()])
    assert run.artefacts[0].status is S.COMPLETE
    assert not [p for p in prov.prompts if "write ONLY" in p]


# ---------------------------------------------------------------- repair reliability (real-model finding, 2026-10-31): a mis-shaped repair no longer ends the run
def test_a_repair_reply_that_returns_the_whole_bullet_list_is_accepted_for_the_asked_positions_and_still_fully_validated():
    bad = pack(bullets=["Stainless steel build", "Keeps drinks cold for hours", "Easy to carry"])
    whole = pack(description="", bullets=["Stainless steel build", "750 ml capacity", "Easy to carry"], keywords=[])
    run, store, _prov = run_copy([bad, whole])
    assert run.artefacts[0].status is S.COMPLETE
    row = next(r for r in store.rows() if r.output_type.name == "LISTING_COPY")
    assert row.output_structured["bullets"] == ["Stainless steel build", "750 ml capacity", "Easy to carry"]


def test_a_whole_list_reply_that_still_carries_a_claim_in_the_asked_position_still_fails_and_bills_nothing():
    bad = pack(bullets=["Stainless steel build", "Keeps drinks cold for hours", "Easy to carry"])
    whole_bad = pack(description="", bullets=["Stainless steel build", "Leak-proof and rust-proof", "Easy to carry"], keywords=[])
    run, store, _prov = run_copy([bad, whole_bad])
    assert run.artefacts[0].status is S.FAILED and run.units_to_bill == 0
    assert not [r for r in store.rows() if r.output_type.name == "LISTING_COPY" and r.status is S.COMPLETE]


def test_a_mis_shaped_repair_falls_back_to_a_full_regeneration_with_the_same_feedback_when_an_attempt_remains():
    from .fakes import GOOD_CONFIG

    bad = pack(bullets=["Stainless steel build", "Keeps drinks cold for hours", "Easy to carry"])
    store = InMemoryStore(config={**GOOD_CONFIG, "internal_retry_bound": 2})
    ap = approved(store)
    svc, _s, prov = make([bad, pack(description="", bullets=[], keywords=[]), pack()], store)  # attempt 2 is mis-shaped (no replacement); attempt 3 is a clean full pack
    run = svc.generate_listing_copy(ACTOR, replace(INTAKE, request_key="rc3"), M.AMAZON, GroundingRequest(approval_id=ap.approval_id))
    prompts = copy_prompts(prov)
    assert run.artefacts[0].status is S.COMPLETE and run.units_to_bill == 1 and len(prompts) == 3
    assert "1 new bullet" in prompts[1] and "1 new bullet" not in prompts[2] and "write the listing copy pack" in prompts[2] and "hot/cold or temperature" in prompts[2]  # the third prompt is the FULL prompt carrying the rule feedback
