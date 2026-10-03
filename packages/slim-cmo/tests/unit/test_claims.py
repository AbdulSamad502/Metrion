"""claims: attribute eligibility, unsupported-number and ineligible-value detection, grounding.

Maps to C9, §6.2.1, §6.5, AC10/AC11/AC12/AC20/AC23. The central promise: an ESTIMATED value,
an UNKNOWN one, or an image hint nobody has verified can NEVER be asserted as a fact."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from slim_cmo import claims as cl
from slim_cmo.claims import Attribute, Citation, EligibilityReason as R, Grounding, GroundingError as GE
from slim_cmo.types import AttributeBasis as B, GroundingBasis, Marketplace, OutputType, TrustState as T

from .factories import constraint

CITE = Citation("https://example.invalid/spec", datetime(2026, 10, 1, tzinfo=UTC))


def attr(name="color", value="blue", basis=B.SELLER_PROVIDED, trust=None, citation=None):
    return Attribute(name, value, basis, trust, citation)


class TestEligibility:
    def test_seller_provided_is_eligible(self):
        assert cl.assess(attr()).eligible

    @pytest.mark.parametrize("basis,reason", [(B.ESTIMATED, R.ESTIMATED), (B.UNKNOWN, R.UNKNOWN)])
    def test_estimated_and_unknown_are_never_eligible(self, basis, reason):
        out = cl.assess(attr(basis=basis))
        assert (out.eligible, out.reason) == (False, reason)

    def test_source_derived_needs_a_citation(self):
        assert cl.assess(attr(basis=B.SOURCE_DERIVED, citation=CITE)).eligible
        out = cl.assess(attr(basis=B.SOURCE_DERIVED))
        assert (out.eligible, out.reason) == (False, R.MISSING_CITATION)
        blank = Citation("   ", CITE.retrieved_at)
        assert not cl.assess(attr(basis=B.SOURCE_DERIVED, citation=blank)).eligible

    def test_image_observed_is_a_hint_until_the_gate_passed(self):
        """AC20: UNVERIFIED_HINT is never a claim, whatever the vision model said."""
        out = cl.assess(attr(basis=B.IMAGE_OBSERVED, trust=T.UNVERIFIED_HINT))
        assert (out.eligible, out.reason) == (False, R.UNVERIFIED_IMAGE_HINT)
        assert cl.assess(attr(basis=B.IMAGE_OBSERVED, trust=T.EVAL_PASSED)).eligible

    def test_image_observed_without_any_trust_state_fails_closed(self):
        assert cl.assess(attr(basis=B.IMAGE_OBSERVED, trust=None)).reason is R.UNVERIFIED_IMAGE_HINT
        assert cl.assess(attr(basis=B.IMAGE_OBSERVED, trust="TRUSTED")).reason is R.UNVERIFIED_IMAGE_HINT

    def test_trust_state_may_arrive_as_a_plain_string(self):
        assert cl.assess(attr(basis=B.IMAGE_OBSERVED, trust="EVAL_PASSED")).eligible

    @pytest.mark.parametrize("name", ["weight", "Net Weight", "item dimensions", "height", "price", "MRP", "rating", "ratings",
                                      "certification", "length (cm)"])
    def test_image_cannot_establish_what_a_photo_cannot_show(self, name):
        """Even with a passed gate: defence in depth over the parser and the DB constraint."""
        out = cl.assess(attr(name=name, value="12", basis=B.IMAGE_OBSERVED, trust=T.EVAL_PASSED))
        assert (out.eligible, out.reason) == (False, R.IMAGE_ATTRIBUTE_NOT_OBSERVABLE)

    @pytest.mark.parametrize("name", ["lightweight", "colour", "material", "finish", "shape"])
    def test_whole_word_matching_does_not_trip_on_substrings(self, name):
        assert cl.assess(attr(name=name, basis=B.IMAGE_OBSERVED, trust=T.EVAL_PASSED)).eligible

    def test_seller_may_state_a_weight_it_is_their_own_fact(self):
        assert cl.assess(attr(name="weight", value="350 g", basis=B.SELLER_PROVIDED)).eligible

    @pytest.mark.parametrize("value", [None, "", "   "])
    def test_empty_values_are_never_eligible(self, value):
        assert cl.assess(attr(value=value)).reason is R.EMPTY_VALUE

    def test_unrecognised_basis_fails_closed_without_raising(self):
        for basis in ("VERIFIED", "", "seller_provided", None, 5):
            out = cl.assess(attr(basis=basis))  # type: ignore[arg-type]
            assert (out.eligible, out.reason) == (False, R.UNRECOGNISED_BASIS), basis

    def test_partition_splits_and_explains(self):
        items = [attr("a"), attr("b", basis=B.ESTIMATED), attr("c", basis=B.IMAGE_OBSERVED, trust=T.UNVERIFIED_HINT)]
        p = cl.partition(items)
        assert [a.name for a in p.eligible] == ["a"]
        assert [(a.name, r) for a, r in p.ineligible] == [("b", R.ESTIMATED), ("c", R.UNVERIFIED_IMAGE_HINT)]

    @given(st.sampled_from(list(B)), st.sampled_from([None, *list(T)]), st.text(max_size=12), st.text(max_size=12))
    @settings(max_examples=300, deadline=None)
    def test_eligibility_never_raises_and_estimates_never_pass(self, basis, trust, name, value):
        out = cl.assess(Attribute(name, value, basis, trust))
        if basis in (B.ESTIMATED, B.UNKNOWN):
            assert not out.eligible
        if basis is B.IMAGE_OBSERVED and trust is not T.EVAL_PASSED:
            assert not out.eligible


class TestSellerConfirmationOfAnImageHint:
    """cmo.confirm_image_hint: records the seller's assertion, costs nothing, and leaves the
    image-derived attribute untrusted until the approved vision evaluation passes."""

    def hint(self, name="material", value="ceramic", trust=T.UNVERIFIED_HINT):
        return attr(name, value, B.IMAGE_OBSERVED, trust)

    def test_a_confirmation_is_a_new_seller_provided_attribute(self):
        out = cl.seller_confirmation(self.hint())
        assert (out.name, out.value, out.basis, out.trust_state, out.citation) == ("material", "ceramic", B.SELLER_PROVIDED, None, None)
        assert cl.assess(out).eligible

    def test_the_hint_itself_stays_untrusted_after_confirmation(self):
        hint = self.hint()
        cl.seller_confirmation(hint)
        assert hint.basis is B.IMAGE_OBSERVED and hint.trust_state is T.UNVERIFIED_HINT  # frozen: nothing changed
        assert cl.assess(hint).reason is R.UNVERIFIED_IMAGE_HINT and not cl.assess(hint).eligible

    def test_the_sellers_correction_replaces_the_models_value(self):
        out = cl.seller_confirmation(self.hint(value="ceramic"), "  stainless steel ")
        assert out.value == "stainless steel" and out.basis is B.SELLER_PROVIDED

    def test_confirming_cannot_launder_a_forbidden_photo_attribute_into_a_vision_fact(self):
        weight = cl.seller_confirmation(self.hint("weight", "350 g"))
        assert weight.basis is B.SELLER_PROVIDED  # now the SELLER's statement about their own product, attributable to them
        hint = self.hint("weight", "350 g", T.EVAL_PASSED)
        assert cl.assess(hint).reason is R.IMAGE_ATTRIBUTE_NOT_OBSERVABLE  # the photo itself still cannot establish it

    def test_only_image_hints_can_be_confirmed_this_way(self):
        for basis in (B.SELLER_PROVIDED, B.ESTIMATED, B.UNKNOWN, B.SOURCE_DERIVED):
            with pytest.raises(ValueError, match="image-derived"):
                cl.seller_confirmation(attr(basis=basis))

    @pytest.mark.parametrize("value", [None, "", "   "])
    def test_an_empty_confirmation_is_refused(self, value):
        hint = Attribute("material", None, B.IMAGE_OBSERVED, T.UNVERIFIED_HINT)
        with pytest.raises(ValueError, match="non-empty"):
            cl.seller_confirmation(hint, value)

    def test_a_confirmed_value_flows_into_copy_while_the_unconfirmed_hint_is_still_blocked(self):
        from slim_cmo import narration as nr

        hint = self.hint(value="ceramic")
        confirmed = cl.seller_confirmation(self.hint("color", "matte blue"))
        p = cl.partition([hint, confirmed])
        assert [a.name for a in p.eligible] == ["color"]
        findings = nr.check_copy_prose("A matte blue ceramic bottle.", eligible=p.eligible, ineligible=p.ineligible)
        assert {(f.kind, f.rule) for f in findings} == {("INELIGIBLE_ATTRIBUTE", "material")}  # 'ceramic' was never confirmed

    def test_the_action_costs_zero_units_and_produces_no_artefact(self):
        from slim_cmo import billing as b

        assert b.Action.CONFIRM_IMAGE_HINT in b.ZERO_UNIT_ACTIONS
        assert b.ACTION_OUTPUT_TYPE[b.Action.CONFIRM_IMAGE_HINT] is None and b.units_for_action(b.Action.CONFIRM_IMAGE_HINT) == 0


class TestNumbers:
    def test_extraction_is_canonical(self):
        assert cl.extract_numbers("12 hours, 12.0 hrs, 1,200 and 007; 12.50") == ("12", "12", "1200", "7", "12.5")

    def test_indian_digit_grouping(self):
        assert cl.extract_numbers("1,00,000 units") == ("100000",)

    def test_digits_glued_to_letters_still_count(self):
        assert cl.extract_numbers("750ml A4 XL200") == ("750", "4", "200")

    def test_other_scripts_cannot_hide_a_number(self):
        assert cl.extract_numbers("१२ hours") == ("12",)  # Devanagari १२
        assert cl.extract_numbers("１２ hours") == ("12",)  # full-width

    def test_unsupported_numbers_are_those_in_no_allowed_source(self):
        out = cl.find_unsupported_numbers("Keeps cold 12 hours, holds 750 ml, 5 star", ["Seller: 12 hours cold", "capacity 750ml"])
        assert out == ("5",)

    def test_nothing_unsupported_when_no_numbers(self):
        assert cl.find_unsupported_numbers("Lovely steel bottle", []) == ()

    def test_all_unsupported_when_no_sources(self):
        assert cl.find_unsupported_numbers("12 and 7", []) == ("12", "7")

    def test_equal_values_in_different_notation_match(self):
        assert cl.find_unsupported_numbers("holds 1200 ml", ["1,200 ml"]) == ()
        assert cl.find_unsupported_numbers("holds 0.50 kg", ["0.5 kg"]) == ()

    def test_invented_year_or_count_is_caught(self):
        assert cl.find_unsupported_numbers("Trusted by 10000 customers since 2015", ["steel bottle"]) == ("10000", "2015")

    @given(st.text(max_size=60), st.lists(st.text(max_size=60), max_size=3))
    @settings(max_examples=200, deadline=None)
    def test_never_raises_and_output_is_sorted_unique(self, text, sources):
        out = cl.find_unsupported_numbers(text, sources)
        assert list(out) == sorted(set(out))


class TestIneligibleValuesInText:
    def estimated(self, name="weight", value="300 g"):
        return (attr(name, value, B.ESTIMATED), R.ESTIMATED)

    def test_an_estimate_stated_as_fact_is_caught(self):
        assert cl.find_ineligible_values_in_text("Weighs just 300 g!", [self.estimated()]) == ("weight",)

    def test_value_the_seller_also_stated_is_not_a_leak(self):
        out = cl.find_ineligible_values_in_text("Weighs 300 g", [self.estimated()], allowed_context="weight: 300 g")
        assert out == ()

    def test_unverified_image_hint_is_caught(self):
        hint = (attr("material", "ceramic", B.IMAGE_OBSERVED, T.UNVERIFIED_HINT), R.UNVERIFIED_IMAGE_HINT)
        assert cl.find_ineligible_values_in_text("A ceramic bottle", [hint]) == ("material",)

    def test_matching_is_case_and_obfuscation_insensitive(self):
        hint = (attr("material", "ceramic", B.IMAGE_OBSERVED, T.UNVERIFIED_HINT), R.UNVERIFIED_IMAGE_HINT)
        assert cl.find_ineligible_values_in_text("A C​ERAMIC bottle", [hint]) == ("material",)

    def test_whole_phrase_matching_only(self):
        hint = (attr("material", "tin", B.ESTIMATED), R.ESTIMATED)
        assert cl.find_ineligible_values_in_text("A stunning bottle", [hint]) == ()  # 'tin' inside 'stunning'

    def test_tiny_and_numeric_values_are_left_to_the_number_check(self):
        items = [(attr("a", "x", B.ESTIMATED), R.ESTIMATED), (attr("n", "300", B.ESTIMATED), R.ESTIMATED)]
        assert cl.find_ineligible_values_in_text("x marks 300 spots", items) == ()

    def test_none_values_are_skipped(self):
        assert cl.find_ineligible_values_in_text("anything", [(attr(value=None, basis=B.UNKNOWN), R.UNKNOWN)]) == ()

    def test_accepts_bare_attributes_too(self):
        assert cl.find_ineligible_values_in_text("a ceramic bottle", [attr("m", "ceramic", B.ESTIMATED)]) == ("m",)


class TestAllowedContext:
    def test_context_is_eligible_names_and_values_plus_extras(self):
        ctx = cl.allowed_context_text([attr("color", "blue")], "Approved Title", None, "seller note")
        assert "color" in ctx and "blue" in ctx and "Approved Title" in ctx and "seller note" in ctx and "None" not in ctx


class TestSharedTextDiagnostic:
    def test_identical_bullet_across_marketplaces_is_reported(self):
        packs = {
            Marketplace.AMAZON: ("Description one", ["Keeps cold 12 hours", "Wide mouth"]),
            Marketplace.FLIPKART: ("Different description", ["keeps COLD 12 hours!", "Easy grip"]),
        }
        out = cl.shared_text_findings(packs)
        assert len(out) == 1 and out[0].kind == "bullet" and {out[0].a, out[0].b} == {Marketplace.AMAZON, Marketplace.FLIPKART}

    def test_identical_description_is_reported(self):
        packs = {m: ("Same text.", ["a" + m.value]) for m in (Marketplace.AMAZON, Marketplace.MEESHO)}
        assert [f.kind for f in cl.shared_text_findings(packs)] == ["description"]

    def test_distinct_packs_have_no_findings(self):
        packs = {Marketplace.AMAZON: ("a", ["x1"]), Marketplace.FLIPKART: ("b", ["y2"]), Marketplace.MEESHO: ("c", ["z3"])}
        assert cl.shared_text_findings(packs) == ()

    def test_empty_text_never_counts_as_shared(self):
        packs = {Marketplace.AMAZON: ("", [""]), Marketplace.FLIPKART: ("", [""])}
        assert cl.shared_text_findings(packs) == ()


# ------------------------------------------------------------------------------- grounding
TENANT, OTHER_TENANT = uuid.uuid4(), uuid.uuid4()
C = constraint()  # title <= 40


def approval(text="Alpha Steel Bottle", tenant=TENANT, marketplace=Marketplace.AMAZON):
    return cl.ApprovalRef(uuid.uuid4(), tenant, marketplace, text)


def ground(output=OutputType.LISTING_COPY, grounding=None, marketplace=Marketplace.AMAZON, tenant=TENANT, constraint_=C):
    return cl.check_grounding(output, tenant_id=tenant, marketplace=marketplace, grounding=grounding, constraint=constraint_)


class TestGrounding:
    def test_approved_title_grounding_succeeds_and_persists_consistent_columns(self):
        a = approval()
        out = ground(grounding=Grounding(GroundingBasis.APPROVED_TITLE, approval=a))
        assert out.ok and out.anchor_text == "Alpha Steel Bottle"
        assert out.persisted_columns() == ("APPROVED_TITLE", a.id)

    def test_seller_supplied_title_grounding(self):
        out = ground(grounding=Grounding(GroundingBasis.SELLER_SUPPLIED_TITLE, seller_title="  My own title "))
        assert out.ok and out.anchor_text == "My own title"
        assert out.persisted_columns() == ("SELLER_SUPPLIED_TITLE", None)

    @pytest.mark.parametrize("output", sorted(cl.GROUNDED_OUTPUT_TYPES, key=lambda o: o.value))
    def test_every_grounded_type_requires_an_anchor(self, output):
        assert ground(output, None).errors == (GE.MISSING_GROUNDING,)

    @pytest.mark.parametrize("output", [OutputType.TITLE_SET, OutputType.HASHTAGS, OutputType.CATALOG_ANSWER, OutputType.TREND_REPORT])
    def test_ungrounded_types_must_not_carry_one(self, output):
        assert ground(output, None).ok
        out = ground(output, Grounding(GroundingBasis.APPROVED_TITLE, approval=approval()))
        assert out.errors == (GE.UNEXPECTED_GROUNDING,)

    def test_approved_basis_must_not_also_carry_a_seller_title(self):
        out = ground(grounding=Grounding(GroundingBasis.APPROVED_TITLE, approval=approval(), seller_title="a second, competing anchor"))
        assert GE.UNEXPECTED_GROUNDING in out.errors

    def test_approved_basis_requires_the_approval(self):
        assert ground(grounding=Grounding(GroundingBasis.APPROVED_TITLE)).errors == (GE.APPROVAL_REQUIRED,)

    def test_seller_basis_must_not_carry_an_approval(self):
        out = ground(grounding=Grounding(GroundingBasis.SELLER_SUPPLIED_TITLE, approval=approval(), seller_title="t"))
        assert GE.APPROVAL_NOT_ALLOWED in out.errors

    def test_seller_basis_needs_a_title(self):
        for title in (None, "", "   "):
            out = ground(grounding=Grounding(GroundingBasis.SELLER_SUPPLIED_TITLE, seller_title=title))
            assert GE.ANCHOR_TITLE_MISSING in out.errors

    def test_an_approval_from_another_marketplace_cannot_anchor_a_pack(self):
        """AC23: a Flipkart pack cannot hang on an Amazon approval."""
        out = ground(marketplace=Marketplace.FLIPKART, grounding=Grounding(GroundingBasis.APPROVED_TITLE, approval=approval(marketplace=Marketplace.AMAZON)))
        assert out.errors == (GE.MARKETPLACE_MISMATCH,)

    def test_an_approval_from_another_tenant_is_refused(self):
        out = ground(grounding=Grounding(GroundingBasis.APPROVED_TITLE, approval=approval(tenant=OTHER_TENANT)))
        assert out.errors == (GE.TENANT_MISMATCH,)

    def test_both_mismatches_are_reported(self):
        out = ground(marketplace=Marketplace.MEESHO, grounding=Grounding(GroundingBasis.APPROVED_TITLE, approval=approval(tenant=OTHER_TENANT)))
        assert set(out.errors) == {GE.TENANT_MISMATCH, GE.MARKETPLACE_MISMATCH}

    def test_an_anchor_that_no_longer_satisfies_the_current_constraint_is_refused(self):
        tightened = constraint(title_max_chars=10)
        out = ground(grounding=Grounding(GroundingBasis.APPROVED_TITLE, approval=approval("A title that is too long now")), constraint_=tightened)
        assert out.errors == (GE.ANCHOR_TITLE_INVALID,)

    def test_a_seller_title_with_forbidden_content_cannot_anchor(self):
        out = ground(grounding=Grounding(GroundingBasis.SELLER_SUPPLIED_TITLE, seller_title="Bestseller Bottle"))
        assert out.errors == (GE.ANCHOR_TITLE_INVALID,)

    def test_failed_grounding_has_nothing_to_persist(self):
        with pytest.raises(ValueError):
            ground(grounding=None).persisted_columns()
