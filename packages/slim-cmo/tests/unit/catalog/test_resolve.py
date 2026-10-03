"""Catalog Q&A resolution (spec §6.5, AC12, AC20, T13, T13b, E14): evidence-first, nothing invented."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from slim_cmo.catalog.attributes import SPECS, CatalogAttribute as C, EstimateKind, normalise_name
from slim_cmo.catalog.estimates import Estimate, RejectedEstimate, ValidEstimate, validate_estimate
from slim_cmo.catalog.resolve import SELLER_INPUT_NOTE, resolve_answers, unresolved_estimable
from slim_cmo.claims import Attribute, assess
from slim_cmo.generation.facts import FactInput, build_fact_context
from slim_cmo.types import AttributeBasis as B
from slim_cmo.types import SellerFactType as F
from slim_cmo.types import TrustState as T


def at(day: int) -> datetime:
    return datetime(2026, 9, day, tzinfo=UTC)


def fact(name, value, day=1, ftype=F.ATTRIBUTE, fid=None):
    return FactInput(ftype, value, name, at(day), fid or f"f-{name}-{day}")


def one(answers, attribute):
    return next(a for a in answers.answers if a.attribute is attribute)


HINT = Attribute("color", "matte blue", B.IMAGE_OBSERVED, T.UNVERIFIED_HINT)
PASSED = Attribute("color", "matte blue", B.IMAGE_OBSERVED, T.EVAL_PASSED)


class TestSellerProvided:
    def test_a_seller_fact_answers_with_its_basis_eligibility_and_source(self):
        res = resolve_answers([C.MATERIAL], [fact("material", "stainless steel", fid="m1")])
        a = one(res, C.MATERIAL)
        assert (a.value, a.basis, a.claim_eligible, a.source_fact_id, a.requires_seller_input) == ("stainless steel", B.SELLER_PROVIDED, True, "m1", False)

    def test_brand_and_category_facts_use_their_own_fact_types(self):
        facts = [FactInput(F.BRAND, "AquaKeep", None, at(1), "b"), FactInput(F.CATEGORY, "Kitchen > Bottles", None, at(1), "c")]
        res = resolve_answers([C.BRAND, C.CATEGORY], facts)
        assert (one(res, C.BRAND).value, one(res, C.CATEGORY).value) == ("AquaKeep", "Kitchen > Bottles")
        assert one(res, C.CATEGORY).basis is B.SELLER_PROVIDED  # the seller stated it: not an estimate

    def test_aliases_spelling_and_separators_are_recognised(self):
        for name in ("Colour", "COLOR", "product_colour", "Product-Color"):
            assert one(resolve_answers([C.COLOR], [fact(name, "blue")]), C.COLOR).value == "blue"
        assert normalise_name("Net_Weight") == "net weight"

    def test_latest_row_wins_across_alias_spellings_and_earlier_values_are_reported(self):
        facts = [fact("color", "red", 1), fact("colour", "blue", 5), fact("Color", "green", 3)]
        a = one(resolve_answers([C.COLOR], facts), C.COLOR)
        assert a.value == "blue" and a.basis is B.SELLER_PROVIDED
        assert set(a.superseded_values) == {"red", "green"} and "replaced" in a.note

    def test_a_later_empty_statement_clears_the_attribute_the_old_value_is_not_resurrected(self):
        facts = [fact("material", "plastic", 1), fact("material", "", 4)]
        a = one(resolve_answers([C.MATERIAL], facts), C.MATERIAL)
        assert a.value is None and a.basis is B.UNKNOWN and a.requires_seller_input

    def test_same_precedence_as_the_p3_fact_context(self):
        facts = [fact("material", "plastic", 1), fact("material", "steel", 5), fact("material", "copper", 3), fact("size", "L", 2)]
        ctx = build_fact_context(facts)
        res = resolve_answers([C.MATERIAL, C.SIZE], facts)
        by_name = {a.name: a.value for a in ctx.eligible}
        assert one(res, C.MATERIAL).value == by_name["material"] and one(res, C.SIZE).value == by_name["size"]

    def test_t13b_a_stated_weight_is_a_seller_provided_claim_eligible_answer(self):
        a = one(resolve_answers([C.WEIGHT], [fact("weight", "350 g")]), C.WEIGHT)
        assert (a.value, a.basis, a.claim_eligible) == ("350 g", B.SELLER_PROVIDED, True)


class TestImageEvidence:
    def test_t13_a_passed_gate_observation_answers_colour_as_image_observed(self):
        a = one(resolve_answers([C.COLOR, C.WEIGHT], [], [PASSED]), C.COLOR)
        assert (a.value, a.basis, a.claim_eligible) == ("matte blue", B.IMAGE_OBSERVED, True)

    def test_t13_weight_is_never_image_observed_even_if_a_passed_attribute_claims_it(self):
        weight = Attribute("weight", "350 g", B.IMAGE_OBSERVED, T.EVAL_PASSED)
        dims = Attribute("item dimensions", "10 x 5 cm", B.IMAGE_OBSERVED, T.EVAL_PASSED)
        res = resolve_answers([C.WEIGHT, C.DIMENSIONS], [], [weight, dims])
        for attr in (C.WEIGHT, C.DIMENSIONS):
            a = one(res, attr)
            assert a.basis is B.UNKNOWN and a.value is None and not a.claim_eligible and a.suggestion is None

    def test_t19_an_unverified_hint_is_only_a_suggestion_the_attribute_stays_unknown(self):
        a = one(resolve_answers([C.COLOR], [], [HINT]), C.COLOR)
        assert a.basis is B.UNKNOWN and a.value is None and not a.claim_eligible and a.requires_seller_input
        assert a.suggestion is not None and a.suggestion.value == "matte blue" and "please confirm" in a.suggestion.text
        assert a.basis is not B.IMAGE_OBSERVED  # never labelled IMAGE_OBSERVED while the gate has not passed

    def test_a_hint_for_a_non_observable_question_is_not_even_suggested(self):
        res = resolve_answers([C.CATEGORY, C.WEIGHT], [], [Attribute("category", "bottle", B.IMAGE_OBSERVED, T.UNVERIFIED_HINT),
                                                           Attribute("weight", "350 g", B.IMAGE_OBSERVED, T.UNVERIFIED_HINT)])
        assert all(a.suggestion is None and a.basis is B.UNKNOWN for a in res.answers)

    def test_the_seller_beats_the_image_and_a_passed_disagreement_is_reported_not_adopted(self):
        a = one(resolve_answers([C.COLOR], [fact("colour", "red")], [PASSED]), C.COLOR)
        assert a.value == "red" and a.basis is B.SELLER_PROVIDED and a.conflicting_observation == "matte blue"

    def test_an_unverified_hint_that_disagrees_is_never_surfaced_as_a_conflict(self):
        a = one(resolve_answers([C.COLOR], [fact("colour", "red")], [HINT]), C.COLOR)
        assert a.value == "red" and a.conflicting_observation is None and a.suggestion is None

    def test_agreement_between_seller_and_a_passed_observation_is_not_a_conflict(self):
        a = one(resolve_answers([C.COLOR], [fact("colour", "Matte  Blue")], [PASSED]), C.COLOR)
        assert a.conflicting_observation is None

    def test_an_unrecognised_basis_or_empty_value_fails_closed(self):
        odd = Attribute("color", "blue", "TOTALLY_NEW", T.EVAL_PASSED)
        blank = Attribute("material", "  ", B.IMAGE_OBSERVED, T.EVAL_PASSED)
        res = resolve_answers([C.COLOR, C.MATERIAL], [], [odd, blank])
        assert all(a.basis is B.UNKNOWN for a in res.answers)

    def test_a_seller_clearing_a_value_does_not_fall_back_to_an_older_one_but_may_use_a_passed_image(self):
        facts = [fact("colour", "red", 1), fact("colour", "", 3)]
        a = one(resolve_answers([C.COLOR], facts, [PASSED]), C.COLOR)
        assert a.basis is B.IMAGE_OBSERVED and a.value == "matte blue"


class TestNothingIsInvented:
    def test_no_evidence_means_unknown_with_a_seller_input_requirement_for_every_question(self):
        res = resolve_answers(list(C), [])
        assert all(a.basis is B.UNKNOWN and a.value is None and a.requires_seller_input and not a.claim_eligible for a in res.answers)
        assert all(SELLER_INPUT_NOTE in a.note for a in res.answers)

    def test_dimensions_are_not_composed_from_length_width_height_facts(self):
        facts = [fact("length", "10 cm"), fact("width", "5 cm"), fact("height", "5 cm")]
        assert one(resolve_answers([C.DIMENSIONS], facts), C.DIMENSIONS).basis is B.UNKNOWN

    def test_free_text_niche_and_target_price_are_never_answers(self):
        facts = [FactInput(F.FREE_TEXT, "weighs 350 g and is steel", None, at(1)), FactInput(F.NICHE, "steel", "material", at(1)),
                 FactInput(F.TARGET_PRICE, "49900", "weight", at(1))]
        res = resolve_answers([C.WEIGHT, C.MATERIAL], facts)
        assert all(a.basis is B.UNKNOWN for a in res.answers) and "49900" not in json.dumps([a.to_json() for a in res.answers])

    def test_no_category_or_browse_node_id_can_come_from_anywhere_but_the_seller(self):
        res = resolve_answers([C.CATEGORY, C.VERTICAL], [])
        assert all(a.value is None for a in res.answers)

    def test_the_vocabulary_is_closed_and_complete(self):
        assert set(SPECS) == set(C) and len(C) == 8
        assert {c for c, s in SPECS.items() if s.estimate_kind} == {C.WEIGHT, C.DIMENSIONS, C.CATEGORY, C.VERTICAL}
        assert not SPECS[C.WEIGHT].image_observable and not SPECS[C.DIMENSIONS].image_observable

    def test_duplicate_questions_are_answered_once_in_order(self):
        res = resolve_answers([C.SIZE, C.COLOR, C.SIZE], [])
        assert [a.attribute for a in res.answers] == [C.SIZE, C.COLOR]


WEIGHT_EST = ValidEstimate(C.WEIGHT, EstimateKind.RANGE, "300-450 g", 300, 450, "g", "typical for steel bottles of this capacity")
CAT_EST = ValidEstimate(C.CATEGORY, EstimateKind.PATH, "Home and Kitchen > Bottles", None, None, None, "inferred from the stated product type")


class TestEstimates:
    def test_an_estimate_is_labelled_estimated_never_claim_eligible_and_asks_for_confirmation(self):
        a = one(resolve_answers([C.WEIGHT], [], [], {C.WEIGHT: WEIGHT_EST}), C.WEIGHT)
        assert (a.basis, a.claim_eligible, a.requires_seller_input, a.value) == (B.ESTIMATED, False, True, "300-450 g")
        assert "confirm before listing" in a.note.lower() and a.estimate.to_json()["low"] == 300  # type: ignore[union-attr]
        assert assess(Attribute("weight", a.value, B.ESTIMATED)).eligible is False

    def test_category_estimate_carries_the_no_ids_note(self):
        a = one(resolve_answers([C.CATEGORY], [], [], {C.CATEGORY: CAT_EST}), C.CATEGORY)
        assert a.basis is B.ESTIMATED and "no category or browse-node id" in a.note

    def test_an_estimate_never_overrides_a_seller_fact_or_a_passed_observation(self):
        a = one(resolve_answers([C.WEIGHT], [fact("weight", "500 g")], [], {C.WEIGHT: WEIGHT_EST}), C.WEIGHT)
        assert a.basis is B.SELLER_PROVIDED and a.value == "500 g" and a.estimate is None

    def test_an_estimate_for_a_non_estimable_question_is_ignored(self):
        bogus = ValidEstimate(C.COLOR, EstimateKind.PATH, "blue", None, None, None, "guess")
        a = one(resolve_answers([C.COLOR], [], [], {C.COLOR: bogus}), C.COLOR)
        assert a.basis is B.UNKNOWN and a.value is None

    def test_a_mismatched_kind_is_ignored(self):
        wrong = ValidEstimate(C.WEIGHT, EstimateKind.PATH, "heavy", None, None, None, "guess")
        assert one(resolve_answers([C.WEIGHT], [], [], {C.WEIGHT: wrong}), C.WEIGHT).basis is B.UNKNOWN

    def test_a_hint_and_an_estimate_can_coexist_without_the_hint_becoming_the_value(self):
        a = one(resolve_answers([C.CATEGORY, C.WEIGHT], [], [HINT], {C.WEIGHT: WEIGHT_EST}), C.WEIGHT)
        assert a.basis is B.ESTIMATED

    def test_unresolved_estimable_lists_only_unknown_estimable_questions(self):
        got = unresolved_estimable(list(C), [fact("weight", "300 g"), fact("colour", "red")], [PASSED])
        assert set(got) == {C.DIMENSIONS, C.CATEGORY, C.VERTICAL}


class TestEstimateValidation:
    def ok(self, attr, **kw):
        base = dict(basis_note="typical for products of this kind")
        base.update(kw)
        return validate_estimate(attr, Estimate(**base))

    def reason(self, attr, **kw):
        out = self.ok(attr, **kw)
        assert isinstance(out, RejectedEstimate), out
        return out.reason

    def test_valid_ranges_and_paths(self):
        assert isinstance(self.ok(C.WEIGHT, low=300, high=450, unit="g"), ValidEstimate)
        assert isinstance(self.ok(C.DIMENSIONS, low=10, high=15, unit="cm"), ValidEstimate)
        assert isinstance(self.ok(C.CATEGORY, text="Home and Kitchen > Water Bottles"), ValidEstimate)
        assert isinstance(self.ok(C.VERTICAL, text="Kitchen & Dining"), ValidEstimate)

    @pytest.mark.parametrize("attr", [C.COLOR, C.MATERIAL, C.SIZE, C.BRAND])
    def test_only_the_four_estimable_questions_may_be_estimated(self, attr):
        assert self.reason(attr, text="steel") == "NOT_ESTIMABLE"

    def test_a_point_value_is_never_allowed(self):
        assert self.reason(C.WEIGHT, low=350, high=350, unit="g") == "POINT_VALUE_NOT_ALLOWED"

    @pytest.mark.parametrize("kw,why", [
        (dict(low=300.5, high=450, unit="g"), "INTEGER_RANGE_REQUIRED"), (dict(low=True, high=450, unit="g"), "INTEGER_RANGE_REQUIRED"),
        (dict(low=None, high=450, unit="g"), "INTEGER_RANGE_REQUIRED"), (dict(low="300", high=450, unit="g"), "INTEGER_RANGE_REQUIRED"),
        (dict(low=-1, high=5, unit="g"), "INVALID_RANGE"), (dict(low=500, high=300, unit="g"), "INVALID_RANGE"),
        (dict(low=3, high=5, unit="lbs"), "UNIT_NOT_ALLOWED"), (dict(low=3, high=5, unit=None), "UNIT_NOT_ALLOWED"),
        (dict(low=3, high=5, unit="cm"), "UNIT_NOT_ALLOWED"), (dict(low=3, high=5, unit="g", text="heavy"), "RANGE_ONLY"),
    ])
    def test_weight_range_violations(self, kw, why):
        assert self.reason(C.WEIGHT, **kw) == why

    @pytest.mark.parametrize("text", ["Kitchen > 1234", "node 5678", "Home > Kitchen > Bottles (12345)", "9876543", "", "   ", "> Kitchen",
                                      "x" * 121, "Bottles GST 18", "Best price bottles", "Kitchen @ home"])
    def test_a_category_text_with_ids_digits_symbols_or_forbidden_words_is_refused(self, text):
        assert self.reason(C.CATEGORY, text=text) in {"PLAIN_WORDS_REQUIRED_NO_IDS"}

    def test_whitespace_in_a_category_path_is_normalised_never_multiline(self):
        out = self.ok(C.CATEGORY, text="Kitchen\nBottles")
        assert isinstance(out, ValidEstimate) and out.value_text == "Kitchen Bottles"

    def test_category_text_cannot_carry_range_fields(self):
        assert self.reason(C.CATEGORY, text="Kitchen", low=1, high=2, unit="g") == "TEXT_ONLY"

    @pytest.mark.parametrize("note", ["", "  ", "about 300 g", "x" * 201, "best price ever", None, 5])
    def test_the_basis_note_is_required_words_only_and_clean(self, note):
        out = validate_estimate(C.WEIGHT, Estimate(low=3, high=5, unit="g", basis_note=note))  # type: ignore[arg-type]
        assert isinstance(out, RejectedEstimate) and out.reason == "BASIS_NOTE_REQUIRED_AND_WORDS_ONLY"

    def test_garbage_is_rejected_not_raised(self):
        assert validate_estimate(C.WEIGHT, "300 g").reason == "BAD_SHAPE"  # type: ignore[union-attr]
        assert validate_estimate(C.WEIGHT, None).reason == "BAD_SHAPE"  # type: ignore[union-attr]

    def test_rejections_carry_a_rule_id_never_the_proposed_text(self):
        out = validate_estimate(C.CATEGORY, Estimate(text="Kitchen > 99999", basis_note="inferred"))
        assert isinstance(out, RejectedEstimate) and "99999" not in repr(out)


@pytest.mark.parametrize("seed", range(6))
def test_estimated_and_unknown_answers_are_never_claim_eligible_and_every_answer_has_a_basis(seed):
    import random

    rnd = random.Random(seed)
    facts = [fact(rnd.choice(["colour", "weight", "size", "material", "brand name"]), rnd.choice(["x", "", "blue", "350 g"]), rnd.randint(1, 9)) for _ in range(6)]
    image = [rnd.choice([HINT, PASSED, Attribute("weight", "9 g", B.IMAGE_OBSERVED, T.EVAL_PASSED)]) for _ in range(2)]
    est = {C.WEIGHT: WEIGHT_EST, C.CATEGORY: CAT_EST}
    for a in resolve_answers(list(C), facts, image, est).answers:
        assert a.basis in set(B)
        if a.basis in (B.ESTIMATED, B.UNKNOWN):
            assert not a.claim_eligible
        if a.basis is B.IMAGE_OBSERVED:
            assert a.attribute not in (C.WEIGHT, C.DIMENSIONS, C.CATEGORY, C.VERTICAL)
        if a.claim_eligible:
            assert a.basis in (B.SELLER_PROVIDED, B.IMAGE_OBSERVED) and a.value
        assert json.dumps(a.to_json())  # JSON-safe, no floats needed
