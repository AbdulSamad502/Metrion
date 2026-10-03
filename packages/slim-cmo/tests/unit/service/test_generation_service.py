"""GenerationService against an in-memory store: acceptance, idempotency, failed-row persistence,
constraint blocking, grounding, facts, the billing boundary (spec §6.4, §8, AC8-AC11, AC15, AC23-AC25)."""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import timedelta

import pytest

from slim_cmo import billing
from slim_cmo.generation.provider import ScriptedLlmProvider
from slim_cmo.service.approve import ApprovalService, Approved
from slim_cmo.service.errors import GroundingRequired, NotFound
from slim_cmo.service.generate import GenerationService, GroundingRequest, Intake
from slim_cmo.service.models import Actor, StoredAnalysis
from slim_cmo.types import ConstraintRowKind as K
from slim_cmo.types import GenerationStatus as S
from slim_cmo.types import GroundingBasis, ImageAnalysisState, Marketplace as M, OutputType as O

from ..factories import NOW, constraint
from ..generation.helpers import GOOD_PACK, GOOD_TITLES, MODEL, j
from .fakes import ACTOR, GOOD_CONFIG, TENANT_A, TENANT_B, USER, InMemoryStore, clock

TS = j(titles=GOOD_TITLES)
INTAKE = Intake(request_key="req-1", sku="SKU1", brand="AquaKeep",
                attributes=(("material", "stainless steel"), ("capacity", "750 ml")))


def make(replies=(), store=None, **kw):
    store = store if store is not None else InMemoryStore()
    provider = ScriptedLlmProvider(replies)
    now = kw.pop("now", NOW)
    return GenerationService(store, provider, model=MODEL, clock=clock(now), **kw), store, provider


def approved(store, mp=M.AMAZON, key="ts-1", option=0):
    svc, _s, _p = make([TS], store)
    run = svc.generate_title_sets(ACTOR, replace(INTAKE, request_key=key), [mp])
    gid = run.artefacts[0].generation_id
    option_id = store.option_ids[gid][option]
    res = ApprovalService(store, clock=clock()).approve_title(ACTOR, gid, option_id=option_id)
    assert isinstance(res, Approved)
    return res


class TestTitleSets:
    def test_three_marketplaces_three_rows_three_units_with_options_and_cited_constraints(self):
        svc, store, p = make([TS, TS, TS])
        run = svc.generate_title_sets(ACTOR, INTAKE, [M.AMAZON, M.FLIPKART, M.MEESHO])
        assert [a.status for a in run.artefacts] == [S.COMPLETE] * 3
        assert run.units_to_bill == 3 and run.run_status is billing.RunStatus.COMPLETE and len(run.delivered_ids) == 3
        rows = store.rows()
        assert [r.marketplace for r in rows] == [M.AMAZON, M.FLIPKART, M.MEESHO]
        assert all(len(r.options) == 3 and r.format_constraint_ref is not None and r.output_type is O.TITLE_SET for r in rows)
        assert p.models == [MODEL] * 3

    def test_every_call_is_per_marketplace_prompts_mention_only_their_own(self):
        svc, _s, p = make([TS, TS])
        svc.generate_title_sets(ACTOR, INTAKE, [M.AMAZON, M.FLIPKART])
        assert "AMAZON" in p.prompts[0] and "FLIPKART" not in p.prompts[0]
        assert "FLIPKART" in p.prompts[1] and "AMAZON" not in p.prompts[1]

    def test_duplicate_submission_serves_the_same_rows_with_no_model_call_and_no_unit(self):
        svc, store, p = make([TS, TS])
        first = svc.generate_title_sets(ACTOR, INTAKE, [M.AMAZON, M.FLIPKART])
        calls = p.calls
        again = svc.generate_title_sets(ACTOR, INTAKE, [M.AMAZON, M.FLIPKART])
        assert p.calls == calls and len(store.rows()) == 2
        assert [a.generation_id for a in again.artefacts] == [a.generation_id for a in first.artefacts]
        assert all(a.reused for a in again.artefacts) and again.units_to_bill == 0 and again.delivered_ids == ()

    def test_a_new_request_key_is_a_regeneration_a_new_row_and_a_new_unit(self):
        svc, store, _p = make([TS, TS])
        svc.generate_title_sets(ACTOR, INTAKE, [M.AMAZON])
        run = svc.generate_title_sets(ACTOR, replace(INTAKE, request_key="req-2"), [M.AMAZON])
        assert len(store.rows()) == 2 and run.units_to_bill == 1

    def test_a_failed_attempt_persists_a_failed_row_and_never_blocks_a_retry_under_the_same_key(self):
        bad = j(titles=["z" * 90])
        svc, store, _p = make([bad, bad, TS])
        first = svc.generate_title_sets(ACTOR, INTAKE, [M.AMAZON])
        assert first.artefacts[0].status is S.FAILED and first.units_to_bill == 0 and first.delivered_ids == ()
        failed = store.rows()[0]
        assert failed.status is S.FAILED and failed.failure_reason and failed.output_structured["failure_code"] == "VALIDATION_FAILED"
        assert failed.options == () and failed.output_text is None
        retry = svc.generate_title_sets(ACTOR, INTAKE, [M.AMAZON])
        assert retry.artefacts[0].status is S.COMPLETE and retry.units_to_bill == 1 and not retry.artefacts[0].reused

    def test_a_short_set_is_complete_labelled_and_billed_once(self):
        svc, store, _p = make([j(titles=[GOOD_TITLES[0], "z" * 90]), j(titles=["y" * 90])])
        run = svc.generate_title_sets(ACTOR, INTAKE, [M.AMAZON])
        assert run.units_to_bill == 1
        rec = store.rows()[0]
        assert rec.status is S.COMPLETE and len(rec.options) == 1 and rec.output_structured["short"] is True

    def test_needs_facts_failure_is_persisted_with_the_screened_names(self):
        svc, store, _p = make([j(needs_facts=["material", "use case"])])
        run = svc.generate_title_sets(ACTOR, INTAKE, [M.AMAZON])
        rec = store.rows()[0]
        assert rec.status is S.FAILED and run.artefacts[0].failure.code.value == "NEEDS_FACTS"
        assert rec.output_structured["missing_facts"] == ["material", "use case"] and "material" in rec.failure_reason


class TestConstraintBlockingAndConfig:
    def test_t8c_one_marketplace_blocked_others_delivered_partial_run(self):
        rows = [constraint(M.AMAZON), constraint(M.MEESHO)]  # Flipkart has no row at all
        svc, store, _p = make([TS, TS], InMemoryStore().with_constraints(*rows))
        run = svc.generate_title_sets(ACTOR, INTAKE, [M.AMAZON, M.FLIPKART, M.MEESHO])
        assert [a.status for a in run.artefacts] == [S.COMPLETE, S.FAILED, S.COMPLETE]
        assert run.units_to_bill == 2 and run.run_status is billing.RunStatus.PARTIAL
        blocked = run.artefacts[1].failure
        assert blocked.code.value == "CONSTRAINT_BLOCKED" and blocked.detail["unavailable_reason"] == "NO_ROW"
        flip = [r for r in store.rows() if r.marketplace is M.FLIPKART][0]
        assert flip.status is S.FAILED and flip.format_constraint_ref is None

    def test_t23_a_test_fixture_row_is_invisible_to_the_production_path(self):
        fixture = constraint(M.AMAZON, row_kind=K.TEST_FIXTURE)
        svc, store, p = make([TS], InMemoryStore().with_constraints(fixture))
        run = svc.generate_title_sets(ACTOR, INTAKE, [M.AMAZON])
        assert run.artefacts[0].failure.detail["unavailable_reason"] in {"NO_ROW", "NO_VERIFIED_ROW"} and p.calls == 0  # the store itself never returns fixtures
        assert run.units_to_bill == 0 and store.rows()[0].status is S.FAILED

    def test_only_an_explicit_test_override_ever_reads_fixtures(self):
        fixture = constraint(M.AMAZON, row_kind=K.TEST_FIXTURE)
        svc, _s, _p = make([TS], InMemoryStore().with_constraints(fixture), accepted_row_kinds=frozenset({K.TEST_FIXTURE}))
        assert svc.generate_title_sets(ACTOR, INTAKE, [M.AMAZON]).units_to_bill == 1

    def test_t24_stale_constraint_blocks_and_so_does_a_missing_age_config(self):
        stale = constraint(M.AMAZON, verified_at=NOW - timedelta(days=90))
        svc, _s, p = make([TS], InMemoryStore().with_constraints(stale))
        assert svc.generate_title_sets(ACTOR, INTAKE, [M.AMAZON]).artefacts[0].failure.detail["unavailable_reason"] == "STALE"
        store = InMemoryStore(config={"internal_retry_bound": 1})
        svc, store, p = make([TS], store)
        run = svc.generate_title_sets(ACTOR, INTAKE, [M.AMAZON])
        assert run.artefacts[0].failure.code.value == "CONFIG_MISSING" and p.calls == 0

    def test_config_missing_persists_failed_rows_calls_no_model_and_bills_nothing(self):
        svc, store, p = make([TS, TS], InMemoryStore(config={}))
        run = svc.generate_title_sets(ACTOR, INTAKE, [M.AMAZON, M.FLIPKART])
        assert p.calls == 0 and run.units_to_bill == 0 and run.run_status is billing.RunStatus.FAILED
        assert [r.status for r in store.rows()] == [S.FAILED, S.FAILED]
        assert store.rows()[0].output_structured["detail"]["missing"] == ["format_constraint_max_age_days", "internal_retry_bound"]

    def test_the_hashtag_key_never_blocks_titles(self):
        cfg = {k: v for k, v in GOOD_CONFIG.items() if k != "hashtag_set_size"}
        svc, _s, _p = make([TS], InMemoryStore(config=cfg))
        assert svc.generate_title_sets(ACTOR, INTAKE, [M.AMAZON]).units_to_bill == 1

    def test_an_unverified_counting_rule_blocks_that_marketplace(self):
        row = constraint(M.AMAZON, count_rule=None)
        svc, _s, _p = make([TS], InMemoryStore().with_constraints(row))
        assert svc.generate_title_sets(ACTOR, INTAKE, [M.AMAZON]).artefacts[0].failure.detail["unavailable_reason"] == "COUNTING_RULE_UNVERIFIED"

    def test_the_category_hint_picks_a_category_row_else_the_marketplace_wide_one(self):
        store = InMemoryStore().with_constraints(constraint(M.AMAZON, title_max_chars=40), constraint(M.AMAZON, category="Kitchen", title_max_chars=12))
        svc, _s, _p = make([TS], store)
        assert svc.generate_title_sets(ACTOR, replace(INTAKE, category_hint=" kitchen "), [M.AMAZON]).artefacts[0].status is S.FAILED  # 12-char rule
        svc, _s, _p = make([TS], store)
        assert svc.generate_title_sets(ACTOR, replace(INTAKE, request_key="r2", category_hint="Toys"), [M.AMAZON]).artefacts[0].status is S.COMPLETE


class TestRequestLevelErrorsPersistNothing:
    @pytest.mark.parametrize("key", ["", "bad key!", "x" * 129, "_lead"])
    def test_bad_request_key(self, key):
        svc, store, p = make([TS])
        with pytest.raises(billing.InvalidRequest):
            svc.generate_title_sets(ACTOR, replace(INTAKE, request_key=key), [M.AMAZON])
        assert store.generations == [] and store.facts == [] and p.calls == 0

    def test_empty_or_duplicate_marketplaces(self):
        svc, store, _p = make([TS])
        for mps in ([], [M.AMAZON, M.AMAZON]):
            with pytest.raises(billing.InvalidRequest):
                svc.generate_title_sets(ACTOR, INTAKE, mps)
        assert store.generations == [] and store.facts == []

    def test_backend_terms_for_flipkart_is_refused_before_anything_is_written(self):
        svc, store, _p = make([])
        with pytest.raises(billing.InvalidRequest) as exc:
            svc.generate_standalone(ACTOR, INTAKE, O.BACKEND_TERMS, M.FLIPKART, GroundingRequest(seller_title="AquaKeep Bottle"))
        assert exc.value.code is billing.RequestError.BACKEND_TERMS_AMAZON_ONLY and store.generations == []

    def test_copy_without_any_anchor_or_with_two_is_refused(self):
        svc, store, _p = make([GOOD_PACK])
        for g in (None, GroundingRequest(), GroundingRequest(approval_id=uuid.uuid4(), seller_title="AquaKeep")):
            with pytest.raises(GroundingRequired):
                svc.generate_listing_copy(ACTOR, INTAKE, M.AMAZON, g)  # type: ignore[arg-type]
        assert store.generations == [] and store.facts == []

    def test_unknown_or_cross_tenant_approval_and_analysis_ids_are_not_found(self):
        store = InMemoryStore()
        res = approved(store)
        svc, _s, p = make([GOOD_PACK], store)
        with pytest.raises(NotFound):
            svc.generate_listing_copy(ACTOR, replace(INTAKE, request_key="c1"), M.AMAZON, GroundingRequest(approval_id=uuid.uuid4()))
        other = Actor(TENANT_B, USER)
        with pytest.raises(NotFound):
            svc.generate_listing_copy(other, replace(INTAKE, request_key="c1"), M.AMAZON, GroundingRequest(approval_id=res.approval_id))
        with pytest.raises(NotFound):
            svc.generate_title_sets(ACTOR, replace(INTAKE, request_key="c2", image_analysis_id=uuid.uuid4()), [M.AMAZON])
        assert len(store.rows()) == 1 and p.calls == 0 and store.rows(TENANT_B) == []  # only the title set from `approved`

    def test_a_non_integer_target_price_is_refused_before_any_write(self):
        svc, store, _p = make([TS])
        for bad in (499.5, -1, True):
            with pytest.raises(ValueError):
                svc.generate_title_sets(ACTOR, replace(INTAKE, target_price_paise=bad), [M.AMAZON])  # type: ignore[arg-type]
        assert store.facts == [] and store.generations == []


class TestListingCopyGrounding:
    def test_t9_a_pack_is_grounded_on_the_approval_and_cites_it(self):
        store = InMemoryStore()
        res = approved(store)
        svc, _s, p = make([GOOD_PACK], store)
        run = svc.generate_listing_copy(ACTOR, replace(INTAKE, request_key="c1"), M.AMAZON, GroundingRequest(approval_id=res.approval_id))
        rec = store.rows()[-1]
        assert run.units_to_bill == 1 and rec.output_type is O.LISTING_COPY and rec.status is S.COMPLETE
        assert rec.grounding_basis is GroundingBasis.APPROVED_TITLE and rec.grounding_approval_id == res.approval_id
        assert rec.format_constraint_ref is not None and res.approved_text in p.prompts[0]
        assert {"description", "bullets", "keywords"} <= set(rec.output_structured)

    def test_a_pack_cannot_hang_on_another_marketplaces_approval(self):
        store = InMemoryStore()
        amazon = approved(store, M.AMAZON, key="a")
        svc, _s, p = make([GOOD_PACK], store)
        run = svc.generate_listing_copy(ACTOR, replace(INTAKE, request_key="c1"), M.FLIPKART, GroundingRequest(approval_id=amazon.approval_id))
        assert run.artefacts[0].failure.code.value == "GROUNDING_INVALID" and p.calls == 0
        assert "MARKETPLACE_MISMATCH" in run.artefacts[0].failure.detail["errors"] and run.units_to_bill == 0
        assert store.rows()[-1].status is S.FAILED

    def test_an_approval_for_a_different_sku_is_refused(self):
        store = InMemoryStore()
        res = approved(store)
        svc, _s, p = make([GOOD_PACK], store)
        run = svc.generate_listing_copy(ACTOR, replace(INTAKE, request_key="c1", sku="OTHER"), M.AMAZON, GroundingRequest(approval_id=res.approval_id))
        assert run.artefacts[0].failure.detail["errors"] == ["SKU_MISMATCH"] and p.calls == 0

    def test_a_seller_supplied_title_is_an_explicit_separate_path_with_no_approval_row(self):
        svc, store, p = make([GOOD_PACK])
        title = "AquaKeep Steel Bottle 750 ml"
        run = svc.generate_listing_copy(ACTOR, INTAKE, M.AMAZON, GroundingRequest(seller_title=title))
        rec = store.rows()[0]
        assert run.units_to_bill == 1 and rec.grounding_basis is GroundingBasis.SELLER_SUPPLIED_TITLE and rec.grounding_approval_id is None
        assert rec.output_structured["provenance"]["grounding_title"] == title and title in p.prompts[0]

    def test_a_seller_title_that_breaks_the_current_constraint_is_refused(self):
        svc, _s, p = make([GOOD_PACK])
        run = svc.generate_listing_copy(ACTOR, INTAKE, M.AMAZON, GroundingRequest(seller_title="AquaKeep " * 20))
        assert run.artefacts[0].failure.detail["errors"] == ["ANCHOR_TITLE_INVALID"] and p.calls == 0

    def test_an_invalid_pack_is_failed_free_and_partial_nothing_is_stored(self):
        bad = j(description="Only Rs. 499", bullets=["a", "b"], keywords=["k"])
        svc, store, _p = make([bad, bad])
        run = svc.generate_listing_copy(ACTOR, INTAKE, M.AMAZON, GroundingRequest(seller_title="AquaKeep Steel Bottle 750 ml"))
        rec = store.rows()[0]
        assert run.units_to_bill == 0 and rec.status is S.FAILED and rec.output_text is None
        assert "description" not in rec.output_structured and rec.failure_reason

    def test_t27_a_standalone_after_a_pack_is_a_new_artefact_and_unit_and_the_pack_row_is_untouched(self):
        svc, store, _p = make([GOOD_PACK, j(bullets=["Stainless steel", "750 ml", "Easy to carry"])])
        title = GroundingRequest(seller_title="AquaKeep Steel Bottle 750 ml")
        svc.generate_listing_copy(ACTOR, INTAKE, M.AMAZON, title)
        before = store.rows()[0]
        run = svc.generate_standalone(ACTOR, INTAKE, O.BULLETS, M.AMAZON, title)
        assert run.units_to_bill == 1 and len(store.rows()) == 2 and store.rows()[0] is before

    def test_shared_text_across_marketplace_packs_is_recorded_diagnostically_never_failing(self):
        same = j(description="A 750 ml stainless steel bottle from AquaKeep for everyday use.", bullets=["Stainless steel build", "750 ml capacity", "Easy to carry"], keywords=["steel bottle"])
        svc, store, _p = make([same, same])
        title = GroundingRequest(seller_title="AquaKeep Steel Bottle 750 ml")
        svc.generate_listing_copy(ACTOR, INTAKE, M.AMAZON, title)
        run = svc.generate_listing_copy(ACTOR, INTAKE, M.FLIPKART, title)
        assert run.artefacts[0].status is S.COMPLETE
        kinds = {d["kind"] for d in store.rows()[1].output_structured["diagnostics"]["shared_text"]}
        assert kinds == {"description", "bullet"} and store.rows()[0].output_structured["diagnostics"]["shared_text"] == []


class TestFacts:
    def test_inline_facts_are_stored_and_the_stored_ones_are_used_by_exact_sku_only(self):
        svc, store, p = make([TS, TS, TS])
        svc.generate_title_sets(ACTOR, replace(INTAKE, request_key="a", attributes=(("capacity", "750 ml"),)), [M.AMAZON])
        # T13b: the seller states a weight in one turn ...
        svc.generate_title_sets(ACTOR, replace(INTAKE, request_key="b", attributes=(("weight", "350 g"),)), [M.AMAZON])
        # ... and a later request with the same sku sees it; another sku does not
        svc.generate_title_sets(ACTOR, Intake(request_key="c", sku="SKU1", brand="AquaKeep"), [M.AMAZON])
        assert '"value": "350 g"' in p.prompts[2] and '"value": "750 ml"' in p.prompts[2]
        other = Intake(request_key="d", sku="SKU2", brand="Other")
        svc2, _s, p2 = make([TS], store)
        svc2.generate_title_sets(ACTOR, other, [M.AMAZON])
        assert "350 g" not in p2.prompts[0] and "AquaKeep" not in p2.prompts[0]

    def test_without_a_sku_only_inline_facts_are_used(self):
        store = InMemoryStore()
        svc, _s, _p = make([TS], store)
        svc.generate_title_sets(ACTOR, Intake(request_key="a", sku="SKU1", attributes=(("material", "steel"),)), [M.AMAZON])
        svc, _s, p = make([TS], store)
        svc.generate_title_sets(ACTOR, Intake(request_key="b", brand="AquaKeep"), [M.AMAZON])
        assert "steel" not in p.prompts[0] and "AquaKeep" in p.prompts[0]

    def test_an_unchanged_fact_is_not_re_saved(self):
        svc, store, _p = make([TS, TS])
        svc.generate_title_sets(ACTOR, INTAKE, [M.AMAZON])
        n = len(store.facts)
        svc.generate_title_sets(ACTOR, replace(INTAKE, request_key="again"), [M.AMAZON])
        assert len(store.facts) == n

    def test_identical_free_text_notes_are_inserted_once_across_and_within_requests(self):
        svc, store, _p = make([TS, TS])
        notes = ("sturdy build", "sturdy  build", "gift ready")  # the first two are the same note
        svc.generate_title_sets(ACTOR, replace(INTAKE, request_key="a", notes=notes), [M.AMAZON])
        n = [f.fact.fact_value for f in store.facts if f.fact.fact_type.value == "FREE_TEXT"]
        assert sorted(n) == ["gift ready", "sturdy build"]
        svc.generate_title_sets(ACTOR, replace(INTAKE, request_key="b", notes=("sturdy build", "new note")), [M.AMAZON])
        n = [f.fact.fact_value for f in store.facts if f.fact.fact_type.value == "FREE_TEXT"]
        assert sorted(n) == ["gift ready", "new note", "sturdy build"]

    def test_a_later_correction_wins_over_an_earlier_value(self):
        plain = j(titles=["AquaKeep Steel Bottle", "AquaKeep Insulated Flask", "AquaKeep Stainless Water Bottle"])
        svc, _store, p = make([plain, plain])
        svc.generate_title_sets(ACTOR, replace(INTAKE, request_key="a", attributes=(("material", "plastic"),)), [M.AMAZON])
        svc.generate_title_sets(ACTOR, replace(INTAKE, request_key="b", attributes=(("material", "steel"),)), [M.AMAZON])
        assert "steel" in p.prompts[1] and "plastic" not in p.prompts[1]

    def test_t17_target_price_is_stored_as_integer_paise_and_never_reaches_a_prompt_or_output(self):
        svc, store, p = make([TS])
        svc.generate_title_sets(ACTOR, replace(INTAKE, target_price_paise=49900), [M.AMAZON])
        tp = [f for f in store.facts if f.fact.value_paise is not None]
        assert len(tp) == 1 and tp[0].fact.value_paise == 49900 and tp[0].fact.fact_value is None
        assert "49900" not in p.prompts[0] and "499" not in p.prompts[0]
        assert "49900" not in repr(store.rows()[0].output_structured)

    def test_provenance_lists_the_fact_ids_used_and_excluded_facts(self):
        svc, store, _p = make([TS])
        svc.generate_title_sets(ACTOR, replace(INTAKE, target_price_paise=100, notes=("sturdy",)), [M.AMAZON])
        prov = store.rows()[0].output_structured["provenance"]
        assert len(prov["fact_ids"]) >= 3 and prov["text_only_confirmed"] is False
        assert any(e.startswith("TARGET_PRICE") for e in store.rows()[0].output_structured["excluded_facts"])

    def test_product_name_is_the_product_name_attribute_fact(self):
        svc, store, p = make([TS])
        svc.generate_title_sets(ACTOR, replace(INTAKE, product_name="Steel Bottle"), [M.AMAZON])
        assert any(f.fact.attribute_name == "product_name" for f in store.facts) and '"name": "product_name"' in p.prompts[0]


class TestImageAnalysis:
    def seed(self, store, state, attrs):
        aid = uuid.uuid4()
        store.analyses[(TENANT_A, aid)] = StoredAnalysis(aid, state, tuple(attrs))
        return aid

    def test_a_failed_analysis_needs_explicit_text_only_confirmation(self):
        store = InMemoryStore()
        aid = self.seed(store, ImageAnalysisState.FAILED, [])
        svc, _s, p = make([TS], store)
        run = svc.generate_title_sets(ACTOR, replace(INTAKE, image_analysis_id=aid), [M.AMAZON])
        assert run.artefacts[0].failure.code.value == "IMAGE_ANALYSIS_NEEDS_CONFIRMATION" and p.calls == 0 and run.units_to_bill == 0
        ok = svc.generate_title_sets(ACTOR, replace(INTAKE, request_key="r2", image_analysis_id=aid, text_only_confirmed=True), [M.AMAZON])
        assert ok.artefacts[0].status is S.COMPLETE
        assert store.rows()[-1].output_structured["provenance"]["text_only_confirmed"] is True and store.rows()[-1].image_analysis_id == aid

    def test_t19_an_unverified_hint_is_never_prompted_and_never_accepted_as_a_claim(self):
        store = InMemoryStore()
        aid = self.seed(store, ImageAnalysisState.COMPLETE,
                        [{"name": "color", "value": "matte blue", "basis": "IMAGE_OBSERVED", "trust_state": "UNVERIFIED_HINT"}])
        leak = j(titles=["AquaKeep matte blue Bottle"])
        svc, _s, p = make([leak, TS], store)
        run = svc.generate_title_sets(ACTOR, replace(INTAKE, image_analysis_id=aid), [M.AMAZON])
        assert all("matte blue" not in pr for pr in p.prompts) and run.artefacts[0].status is S.COMPLETE
        assert all("matte blue" not in o.text for o in store.rows()[0].options)

    def test_a_passed_gate_hint_may_be_used_as_a_fact(self):
        store = InMemoryStore()
        aid = self.seed(store, ImageAnalysisState.COMPLETE,
                        [{"name": "shape", "value": "round", "basis": "IMAGE_OBSERVED", "trust_state": "EVAL_PASSED"}])
        svc, _s, p = make([TS], store)
        svc.generate_title_sets(ACTOR, replace(INTAKE, image_analysis_id=aid), [M.AMAZON])
        assert '"value": "round"' in p.prompts[0]


class TestHashtagsAndBilling:
    def test_hashtags_are_a_separate_artefact_with_no_constraint_or_grounding(self):
        svc, store, _p = make([j(hashtags=["#steelbottle", "#AquaKeep"])])
        run = svc.generate_hashtags(ACTOR, INTAKE)
        rec = store.rows()[0]
        assert run.units_to_bill == 1 and rec.output_type is O.HASHTAGS and rec.marketplace is None
        assert rec.format_constraint_ref is None and rec.grounding_basis is None and rec.output_structured["listing_field"] is False

    def test_missing_hashtag_config_is_config_missing_with_a_failed_row(self):
        cfg = {k: v for k, v in GOOD_CONFIG.items() if k != "hashtag_set_size"}
        svc, store, p = make([], InMemoryStore(config=cfg))
        run = svc.generate_hashtags(ACTOR, INTAKE)
        assert run.artefacts[0].failure.code.value == "CONFIG_MISSING" and p.calls == 0 and store.rows()[0].status is S.FAILED
        assert store.rows()[0].output_structured["detail"]["missing"] == ["hashtag_set_size"]

    def test_a_simultaneous_identical_request_is_served_its_row_with_no_second_unit(self):
        store = InMemoryStore()
        svc, _s, _p = make([TS], store)
        competitor = uuid.uuid4()

        def race(rec):
            store.generations.append((TENANT_A, competitor, replace(rec)))

        store.before_save = race
        run = svc.generate_title_sets(ACTOR, INTAKE, [M.AMAZON])
        assert run.artefacts[0].reused and run.artefacts[0].generation_id == competitor
        assert run.units_to_bill == 0 and run.delivered_ids == () and len(store.rows()) == 1

    def test_only_the_delivered_new_artefacts_are_returned_for_metering(self):
        svc, store, _p = make([TS, j(titles=["z" * 90]), j(titles=["z" * 90]), TS])
        run = svc.generate_title_sets(ACTOR, INTAKE, [M.AMAZON, M.FLIPKART, M.MEESHO])
        done = [a for a in run.artefacts if a.status is S.COMPLETE]
        assert run.delivered_ids == tuple(a.generation_id for a in done) and run.units_to_bill == len(done) == 2

    def test_the_service_never_meters_or_touches_entitlement(self):
        import inspect

        from slim_cmo.service import approve, generate

        for mod in (generate, approve):
            assert "metered_event" not in inspect.getsource(mod) and "entitlement" not in inspect.getsource(mod).lower().replace("entitlement.md", "")


def test_tenant_comes_from_the_actor_only():
    import inspect

    assert "tenant_id" not in {f.name for f in __import__("dataclasses").fields(Intake)}
    assert "tenant_id" not in inspect.signature(GenerationService.generate_title_sets).parameters
