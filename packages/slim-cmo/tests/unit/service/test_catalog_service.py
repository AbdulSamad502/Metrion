"""CatalogService against the in-memory store (spec §6.5, §8.1.1, AC12, AC15, AC19, AC20, AC39, T13, T18, T20)."""

from __future__ import annotations

import copy
import json
import uuid
from dataclasses import replace

import pytest

from slim_cmo import billing
from slim_cmo.catalog.attributes import CatalogAttribute as C
from slim_cmo.catalog.estimates import Estimate
from slim_cmo.generation.provider import ScriptedLlmProvider
from slim_cmo.service.catalog import CatalogRequest, CatalogService
from slim_cmo.service.errors import InvalidConfirmation, NotFound
from slim_cmo.service.generate import GenerationService, Intake
from slim_cmo.service.models import Actor, StoredAnalysis
from slim_cmo.types import AttributeBasis as B
from slim_cmo.types import GenerationStatus as S
from slim_cmo.types import ImageAnalysisState, Marketplace as M, OutputType as O, SellerFactType as F

from ..generation.helpers import MODEL, j
from .fakes import ACTOR, TENANT_A, TENANT_B, USER, InMemoryStore, clock

BASE = Intake(request_key="q1", sku="SKU1")
HINT = {"name": "color", "value": "matte blue", "basis": "IMAGE_OBSERVED", "trust_state": "UNVERIFIED_HINT"}
PASSED = {"name": "color", "value": "matte blue", "basis": "IMAGE_OBSERVED", "trust_state": "EVAL_PASSED"}


def svc(store=None, **kw):
    store = store if store is not None else InMemoryStore()
    return CatalogService(store, **kw), store


def req(*questions, intake=BASE, marketplaces=()):
    return CatalogRequest(intake, tuple(questions), tuple(marketplaces))


def answers(store, i=-1):
    return {a["attribute"]: a for a in store.rows()[i].output_structured["attributes"]}


def seed_analysis(store, attrs, state=ImageAnalysisState.COMPLETE, tenant=TENANT_A):
    aid = uuid.uuid4()
    store.analyses[(tenant, aid)] = StoredAnalysis(aid, state, tuple(attrs))
    return aid


class TestAnswer:
    def test_a_product_level_answer_is_one_row_one_unit_with_no_constraint_grounding_or_model(self):
        s, store = svc()
        run = s.answer(ACTOR, req(C.MATERIAL, C.WEIGHT, intake=replace(BASE, attributes=(("material", "stainless steel"),))))
        rec = store.rows()[0]
        assert run.units_to_bill == 1 and run.delivered_ids == (run.artefacts[0].generation_id,)
        assert rec.output_type is O.CATALOG_ANSWER and rec.marketplace is None and rec.status is S.COMPLETE
        assert rec.format_constraint_ref is None and rec.grounding_basis is None and rec.output_text is None
        a = answers(store)
        assert (a["MATERIAL"]["basis"], a["MATERIAL"]["claim_eligible"], a["MATERIAL"]["value"]) == ("SELLER_PROVIDED", True, "stainless steel")
        assert (a["WEIGHT"]["basis"], a["WEIGHT"]["value"], a["WEIGHT"]["requires_seller_input"]) == ("UNKNOWN", None, True)
        assert rec.output_structured["basis_counts"] == {"SELLER_PROVIDED": 1, "UNKNOWN": 1}

    def test_each_marketplace_is_its_own_artefact_and_unit(self):
        s, store = svc()
        run = s.answer(ACTOR, req(C.CATEGORY, marketplaces=[M.AMAZON, M.FLIPKART]))
        assert run.units_to_bill == 2 and [r.marketplace for r in store.rows()] == [M.AMAZON, M.FLIPKART]
        assert store.rows()[0].output_structured["marketplace"] == "AMAZON"

    def test_duplicate_submission_is_idempotent_and_free_and_a_new_key_is_a_new_unit(self):
        s, store = svc()
        first = s.answer(ACTOR, req(C.COLOR))
        again = s.answer(ACTOR, req(C.COLOR))
        assert again.artefacts[0].reused and again.artefacts[0].generation_id == first.artefacts[0].generation_id
        assert again.units_to_bill == 0 and again.delivered_ids == () and len(store.rows()) == 1
        assert s.answer(ACTOR, req(C.COLOR, intake=replace(BASE, request_key="q2"))).units_to_bill == 1

    def test_a_simultaneous_identical_request_is_served_the_winning_row(self):
        s, store = svc()
        winner = uuid.uuid4()
        store.before_save = lambda rec: store.generations.append((TENANT_A, winner, replace(rec)))
        run = s.answer(ACTOR, req(C.COLOR))
        assert run.artefacts[0].reused and run.artefacts[0].generation_id == winner and run.units_to_bill == 0 and len(store.rows()) == 1

    def test_the_service_has_no_model_dependency_at_all(self):
        import inspect

        from slim_cmo.service import catalog

        src = inspect.getsource(catalog)
        assert "LlmProvider" not in src and "provider" not in src.lower().replace("vision provider", "")
        assert "metered_event" not in src and "entitlement" not in src.lower()


class TestRequestLevelErrorsPersistNothing:
    def test_bad_requests(self):
        s, store = svc()
        for bad in (req(), req(C.COLOR, intake=replace(BASE, request_key="bad key!")), req(C.COLOR, marketplaces=[M.AMAZON, M.AMAZON])):
            with pytest.raises(billing.InvalidRequest):
                s.answer(ACTOR, bad)
        with pytest.raises(billing.InvalidRequest):
            s.answer(ACTOR, CatalogRequest(BASE, ("COLOR",)))  # type: ignore[arg-type]
        assert store.generations == [] and store.facts == []

    def test_t18_an_unknown_or_cross_tenant_analysis_is_not_found_and_nothing_is_written(self):
        s, store = svc()
        foreign = seed_analysis(store, [PASSED], tenant=TENANT_B)
        for aid in (uuid.uuid4(), foreign):
            with pytest.raises(NotFound):
                s.answer(ACTOR, req(C.COLOR, intake=replace(BASE, image_analysis_id=aid, attributes=(("material", "steel"),))))
        assert store.generations == [] and store.facts == []

    def test_a_bad_target_price_is_refused_before_any_write(self):
        s, store = svc()
        with pytest.raises(ValueError):
            s.answer(ACTOR, req(C.COLOR, intake=replace(BASE, target_price_paise=4.5)))  # type: ignore[arg-type]
        assert store.facts == []


class TestFactsAndPrecedence:
    def test_inline_facts_are_stored_and_stored_facts_load_by_exact_sku_only(self):
        s, store = svc()
        s.answer(ACTOR, req(C.WEIGHT, intake=replace(BASE, attributes=(("weight", "350 g"),))))
        # T13b: a later question on the same sku sees the stated weight; another sku does not
        later = s.answer(ACTOR, req(C.WEIGHT, intake=replace(BASE, request_key="q2")))
        assert answers(store)["WEIGHT"]["basis"] == "SELLER_PROVIDED" and answers(store)["WEIGHT"]["value"] == "350 g" and later.units_to_bill == 1
        s.answer(ACTOR, req(C.WEIGHT, intake=Intake(request_key="q3", sku="OTHER")))
        assert answers(store)["WEIGHT"]["basis"] == "UNKNOWN"
        s.answer(ACTOR, req(C.WEIGHT, intake=Intake(request_key="q4")))  # no sku: only inline facts
        assert answers(store)["WEIGHT"]["basis"] == "UNKNOWN"

    def test_conflicting_seller_statements_latest_wins_and_the_earlier_value_is_reported(self):
        s, store = svc()
        s.answer(ACTOR, req(C.MATERIAL, intake=replace(BASE, attributes=(("material", "plastic"),))))
        s.answer(ACTOR, req(C.MATERIAL, intake=replace(BASE, request_key="q2", attributes=(("material", "steel"),))))
        a = answers(store)["MATERIAL"]
        assert a["value"] == "steel" and a["superseded_values"] == ["plastic"]

    def test_an_unchanged_fact_is_not_re_saved(self):
        s, store = svc()
        i = replace(BASE, attributes=(("material", "steel"),))
        s.answer(ACTOR, req(C.MATERIAL, intake=i))
        n = len(store.facts)
        s.answer(ACTOR, req(C.MATERIAL, intake=replace(i, request_key="q2")))
        assert len(store.facts) == n

    def test_the_target_price_is_stored_as_paise_and_never_reaches_an_answer(self):
        s, store = svc()
        s.answer(ACTOR, req(C.WEIGHT, C.CATEGORY, intake=replace(BASE, target_price_paise=49900)))
        assert [f.fact.value_paise for f in store.facts] == [49900]
        assert "49900" not in json.dumps(store.rows()[0].output_structured)

    def test_cross_tenant_facts_are_invisible(self):
        s, store = svc()
        s.answer(ACTOR, req(C.WEIGHT, intake=replace(BASE, attributes=(("weight", "350 g"),))))
        s.answer(Actor(TENANT_B, USER), req(C.WEIGHT, intake=replace(BASE, request_key="b1")))
        b = {a["attribute"]: a for a in store.rows(TENANT_B)[0].output_structured["attributes"]}
        assert b["WEIGHT"]["basis"] == "UNKNOWN" and b["WEIGHT"]["value"] is None  # tenant A's stated weight is invisible to B


class TestImageEvidence:
    def test_t13_colour_from_a_passed_observation_weight_unknown(self):
        s, store = svc()
        aid = seed_analysis(store, [PASSED])
        s.answer(ACTOR, req(C.COLOR, C.WEIGHT, intake=replace(BASE, image_analysis_id=aid)))
        a = answers(store)
        assert (a["COLOR"]["basis"], a["COLOR"]["claim_eligible"]) == ("IMAGE_OBSERVED", True)
        assert (a["WEIGHT"]["basis"], a["WEIGHT"]["value"]) == ("UNKNOWN", None)
        assert store.rows()[0].image_analysis_id == aid and store.rows()[0].output_structured["provenance"]["image_analysis_state"] == "COMPLETE"

    def test_t19_an_unverified_hint_is_a_suggestion_only_in_the_persisted_answer(self):
        s, store = svc()
        aid = seed_analysis(store, [HINT])
        s.answer(ACTOR, req(C.COLOR, intake=replace(BASE, image_analysis_id=aid)))
        a = answers(store)["COLOR"]
        assert a["basis"] == "UNKNOWN" and a["value"] is None and a["claim_eligible"] is False
        assert a["suggestion"]["value"] == "matte blue" and "confirm" in a["suggestion"]["text"]

    def test_a_degraded_or_failed_analysis_is_ignored_and_recorded(self):
        s, store = svc()
        aid = seed_analysis(store, [PASSED], state=ImageAnalysisState.DEGRADED)
        s.answer(ACTOR, req(C.COLOR, intake=replace(BASE, image_analysis_id=aid)))
        assert answers(store)["COLOR"]["basis"] == "UNKNOWN"
        assert store.rows()[0].output_structured["provenance"]["image_analysis_state"] == "DEGRADED"

    def test_the_seller_wins_over_a_passed_observation_and_the_disagreement_is_recorded(self):
        s, store = svc()
        aid = seed_analysis(store, [PASSED])
        s.answer(ACTOR, req(C.COLOR, intake=replace(BASE, image_analysis_id=aid, attributes=(("colour", "red"),))))
        a = answers(store)["COLOR"]
        assert a["value"] == "red" and a["basis"] == "SELLER_PROVIDED" and a["conflicting_observation"] == "matte blue"


class FakeEstimator:
    def __init__(self, proposal=None, error=None):
        self.proposal, self.error, self.calls = proposal or {}, error, []

    def estimate(self, *, marketplace, attributes, known_facts):
        self.calls.append((marketplace, list(attributes), dict(known_facts)))
        if self.error:
            raise self.error
        return self.proposal


class TestEstimatorSeam:
    def test_without_an_estimator_unresolved_estimable_questions_are_unknown(self):
        s, store = svc()
        s.answer(ACTOR, req(C.WEIGHT, C.CATEGORY))
        assert {a["basis"] for a in answers(store).values()} == {"UNKNOWN"}
        assert store.rows()[0].output_structured["provenance"]["estimator"] == "NOT_CONFIGURED"

    def test_a_valid_estimate_is_persisted_as_estimated_and_never_claim_eligible(self):
        est = FakeEstimator({C.WEIGHT: Estimate(low=300, high=450, unit="g", basis_note="typical for steel bottles")})
        s, store = svc(estimator=est)
        s.answer(ACTOR, req(C.WEIGHT, C.COLOR))
        a = answers(store)["WEIGHT"]
        assert (a["basis"], a["claim_eligible"], a["value"]) == ("ESTIMATED", False, "300-450 g") and a["requires_seller_input"]
        assert answers(store)["COLOR"]["basis"] == "UNKNOWN"
        assert est.calls[0][1] == [C.WEIGHT]  # asked only about unresolved ESTIMABLE questions, never colour

    def test_the_estimator_sees_only_claim_eligible_facts_never_hints_or_price(self):
        est = FakeEstimator()
        s, store = svc(estimator=est)
        aid = seed_analysis(store, [HINT])
        s.answer(ACTOR, req(C.WEIGHT, intake=replace(BASE, image_analysis_id=aid, target_price_paise=49900,
                                                    brand="AquaKeep", notes=("sturdy",), attributes=(("material", "steel"),))))
        known = est.calls[0][2]
        assert set(known) == {"brand", "material"} and "49900" not in json.dumps(known) and "matte blue" not in json.dumps(known)

    def test_an_estimator_never_overrides_what_the_seller_stated(self):
        est = FakeEstimator({C.WEIGHT: Estimate(low=1, high=2, unit="g", basis_note="guess")})
        s, store = svc(estimator=est)
        s.answer(ACTOR, req(C.WEIGHT, intake=replace(BASE, attributes=(("weight", "350 g"),))))
        assert answers(store)["WEIGHT"]["basis"] == "SELLER_PROVIDED" and est.calls == []

    @pytest.mark.parametrize("bad", [
        Estimate(low=350, high=350, unit="g", basis_note="typical"),       # point value
        Estimate(low=1.5, high=3, unit="g", basis_note="typical"),         # float
        Estimate(low=1, high=3, unit="lb", basis_note="typical"),          # unit
        Estimate(low=1, high=3, unit="g", basis_note="about 300 g"),       # digits in the basis
    ])
    def test_invalid_estimates_are_rejected_and_the_answer_is_unknown(self, bad):
        s, store = svc(estimator=FakeEstimator({C.WEIGHT: bad}))
        s.answer(ACTOR, req(C.WEIGHT))
        assert answers(store)["WEIGHT"]["basis"] == "UNKNOWN"
        assert "WEIGHT" in store.rows()[0].output_structured["provenance"]["rejected_estimates"]

    def test_invented_category_ids_and_non_estimable_attributes_are_discarded(self):
        est = FakeEstimator({C.CATEGORY: Estimate(text="Kitchen > 4712", basis_note="inferred"),
                             C.MATERIAL: Estimate(text="steel", basis_note="inferred")})
        s, store = svc(estimator=est)
        s.answer(ACTOR, req(C.CATEGORY, C.MATERIAL))
        a = answers(store)
        assert a["CATEGORY"]["basis"] == "UNKNOWN" and a["MATERIAL"]["basis"] == "UNKNOWN" and a["MATERIAL"]["value"] is None
        assert set(store.rows()[0].output_structured["provenance"]["rejected_estimates"]) == {"CATEGORY", "MATERIAL"}

    def test_an_estimator_outage_never_fails_the_answer(self):
        s, store = svc(estimator=FakeEstimator(error=RuntimeError("down")))
        run = s.answer(ACTOR, req(C.WEIGHT))
        assert run.artefacts[0].status is S.COMPLETE and answers(store)["WEIGHT"]["basis"] == "UNKNOWN"
        assert store.rows()[0].output_structured["provenance"]["estimator"] == "UNAVAILABLE"

    def test_the_estimator_is_asked_per_marketplace(self):
        est = FakeEstimator({C.CATEGORY: Estimate(text="Home and Kitchen > Bottles", basis_note="inferred from the product type")})
        s, store = svc(estimator=est)
        s.answer(ACTOR, req(C.CATEGORY, marketplaces=[M.AMAZON, M.FLIPKART]))
        assert [c[0] for c in est.calls] == [M.AMAZON, M.FLIPKART]


class TestConfirmImageHint:
    def test_ac39_a_seller_provided_fact_is_created_with_zero_units_and_the_analysis_is_untouched(self):
        s, store = svc()
        aid = seed_analysis(store, [HINT])
        before = copy.deepcopy(store.analyses[(TENANT_A, aid)])
        res = s.confirm_image_hint(ACTOR, analysis_id=aid, attribute_name="Color", sku="SKU1")
        assert res.created and res.fact_id
        row = store.facts[-1]
        assert (row.fact.fact_type, row.fact.attribute_name, row.fact.fact_value, row.fact.sku, row.fact.image_analysis_id) == (
            F.ATTRIBUTE, "color", "matte blue", "SKU1", aid)
        assert store.generations == []                      # zero units: no artefact, no row
        assert store.analyses[(TENANT_A, aid)] == before    # the analysis was not modified
        assert store.analyses[(TENANT_A, aid)].attributes[0]["trust_state"] == "UNVERIFIED_HINT"

    def test_the_hint_stays_untrusted_only_the_sellers_statement_is_usable(self):
        s, store = svc()
        aid = seed_analysis(store, [HINT])
        s.confirm_image_hint(ACTOR, analysis_id=aid, attribute_name="color", sku="SKU1")
        # catalog: answered from the SELLER's fact, basis SELLER_PROVIDED - not IMAGE_OBSERVED
        s.answer(ACTOR, req(C.COLOR, intake=replace(BASE, image_analysis_id=aid)))
        a = answers(store)["COLOR"]
        assert a["basis"] == "SELLER_PROVIDED" and a["value"] == "matte blue" and a["claim_eligible"] is True
        # a DIFFERENT hint on the same analysis is still just a suggestion, and the original is still UNVERIFIED
        other = {"name": "material", "value": "ceramic", "basis": "IMAGE_OBSERVED", "trust_state": "UNVERIFIED_HINT"}
        store.analyses[(TENANT_A, aid)] = StoredAnalysis(aid, ImageAnalysisState.COMPLETE, (HINT, other))
        s.answer(ACTOR, req(C.MATERIAL, intake=replace(BASE, request_key="q2", image_analysis_id=aid)))
        m = answers(store)["MATERIAL"]
        assert m["basis"] == "UNKNOWN" and m["value"] is None and m["suggestion"]["value"] == "ceramic"

    def test_generation_may_use_the_confirmed_value_but_never_an_unconfirmed_hint(self):
        store = InMemoryStore()
        cat = CatalogService(store)
        other = {"name": "shape", "value": "round", "basis": "IMAGE_OBSERVED", "trust_state": "UNVERIFIED_HINT"}
        aid = seed_analysis(store, [HINT, other])
        cat.confirm_image_hint(ACTOR, analysis_id=aid, attribute_name="color", sku="SKU1")
        provider = ScriptedLlmProvider([j(titles=["AquaKeep matte blue Bottle", "AquaKeep Blue Flask", "AquaKeep Blue Mug"])])
        gen = GenerationService(store, provider, model=MODEL, clock=clock())
        run = gen.generate_title_sets(ACTOR, replace(BASE, request_key="g1", brand="AquaKeep", image_analysis_id=aid), [M.AMAZON])
        assert run.artefacts[0].status is S.COMPLETE
        assert '"value": "matte blue"' in provider.prompts[0]      # the seller's own statement is usable
        assert "round" not in provider.prompts[0]                  # the untouched, unconfirmed hint is not

    def test_a_correction_is_the_sellers_own_assertion(self):
        s, store = svc()
        aid = seed_analysis(store, [HINT])
        s.confirm_image_hint(ACTOR, analysis_id=aid, attribute_name="color", sku="SKU1", confirmed_value="navy")
        assert store.facts[-1].fact.fact_value == "navy"

    def test_an_identical_confirmation_is_idempotent(self):
        s, store = svc()
        aid = seed_analysis(store, [HINT])
        s.confirm_image_hint(ACTOR, analysis_id=aid, attribute_name="color", sku="SKU1")
        again = s.confirm_image_hint(ACTOR, analysis_id=aid, attribute_name="color", sku="SKU1")
        assert not again.created and again.fact_id is None and len(store.facts) == 1

    def test_a_confirmed_weight_is_the_sellers_statement_not_something_the_photo_established(self):
        s, store = svc()
        aid = seed_analysis(store, [{"name": "weight", "value": "350 g", "basis": "IMAGE_OBSERVED", "trust_state": "UNVERIFIED_HINT"}])
        s.confirm_image_hint(ACTOR, analysis_id=aid, attribute_name="weight", sku="SKU1")
        s.answer(ACTOR, req(C.WEIGHT, intake=replace(BASE, image_analysis_id=aid)))
        a = answers(store)["WEIGHT"]
        assert a["basis"] == "SELLER_PROVIDED" and a["basis"] != "IMAGE_OBSERVED"

    def test_refusals_unknown_analysis_foreign_tenant_unknown_hint_no_sku_blank_or_non_hint(self):
        s, store = svc()
        aid = seed_analysis(store, [HINT, {"name": "pattern", "value": None, "basis": "UNKNOWN", "trust_state": "UNVERIFIED_HINT"}])
        foreign = seed_analysis(store, [HINT], tenant=TENANT_B)
        for kw in ({"analysis_id": uuid.uuid4(), "attribute_name": "color"}, {"analysis_id": foreign, "attribute_name": "color"},
                   {"analysis_id": aid, "attribute_name": "nope"}, {"analysis_id": aid, "attribute_name": ""}):
            with pytest.raises(NotFound):
                s.confirm_image_hint(ACTOR, sku="SKU1", **kw)
        with pytest.raises(InvalidConfirmation):
            s.confirm_image_hint(ACTOR, analysis_id=aid, attribute_name="color", sku=" ")
        with pytest.raises(InvalidConfirmation):
            s.confirm_image_hint(ACTOR, analysis_id=aid, attribute_name="color", sku="SKU1", confirmed_value="   ")
        with pytest.raises(InvalidConfirmation):
            s.confirm_image_hint(ACTOR, analysis_id=aid, attribute_name="pattern", sku="SKU1")  # UNKNOWN-basis item is not a hint
        assert store.facts == []
