"""Title-set generation (decision 1, AC8, AC9, T8, T25) and the shared retry engine."""

from __future__ import annotations

import json

import pytest

from slim_cmo.generation.outcomes import Delivered, Failed, FailureCode
from slim_cmo.generation.provider import LlmUnavailable, ScriptedLlmProvider
from slim_cmo.generation.titles import SHORT_SET_LABEL, generate_title_set
from slim_cmo.types import Marketplace as M
from slim_cmo.types import OutputType

from .helpers import GOOD_TITLES, MODEL, ctx, j, resolved


def run(replies, *, retry_bound=2, facts=None, mp=M.AMAZON, **limits):
    provider = ScriptedLlmProvider(replies)
    out = generate_title_set(provider=provider, model=MODEL, marketplace=mp, resolved=resolved(mp, **limits),
                             facts=facts or ctx(), retry_bound=retry_bound)
    return out, provider


class TestDelivery:
    def test_happy_path_counts_and_checks_come_from_code(self):
        out, p = run([j(titles=GOOD_TITLES)])
        assert isinstance(out, Delivered) and p.calls == 1 and out.attempts == 1
        assert [o.rank for o in out.options] == [1, 2, 3]
        assert [o.char_count for o in out.options] == [len(t) for t in GOOD_TITLES]
        assert all(o.constraint_check["passed"] and o.constraint_check["max_chars"] == 40 for o in out.options)
        assert out.structured["short"] is False and out.structured["constraint"]["format_constraint_ref"]
        assert p.models == [MODEL]

    def test_a_model_that_lies_about_its_own_length_is_ignored(self):
        too_long = "AquaKeep Steel Bottle 750 ml " * 3
        out, _ = run([j(titles=[too_long, *GOOD_TITLES], char_counts=[1, 2, 3, 4])])
        assert isinstance(out, Delivered) and too_long.strip() not in [o.text for o in out.options]

    def test_surplus_valid_options_are_dropped_not_billed_as_extra(self):
        out, _ = run([j(titles=[*GOOD_TITLES, "AquaKeep Steel Flask 750 ml"])])
        assert isinstance(out, Delivered) and len(out.options) == 3


class TestAccumulationAndShortSets:
    def test_valid_options_accumulate_across_attempts_and_a_retry_asks_only_for_the_shortfall(self):
        long = "AquaKeep Steel Bottle 750 ml with a really long name"
        out, p = run([j(titles=[GOOD_TITLES[0], long, GOOD_TITLES[1]]), j(titles=[GOOD_TITLES[2]])])
        assert isinstance(out, Delivered) and out.attempts == 2
        assert [o.text for o in out.options] == GOOD_TITLES
        retry_prompt = p.prompts[1]
        assert "write 1 distinct" in retry_prompt and GOOD_TITLES[0] in retry_prompt
        assert "TOO_LONG" in retry_prompt

    def test_duplicates_across_attempts_are_rejected_and_never_padded(self):
        dup = GOOD_TITLES[0].upper()
        out, _ = run([j(titles=GOOD_TITLES[:2]), j(titles=[dup, GOOD_TITLES[0]])], retry_bound=1)
        assert isinstance(out, Delivered) and len(out.options) == 2 and out.structured["short"] is True

    def test_short_set_is_complete_labelled_and_records_the_shortfall(self):
        out, _ = run([j(titles=[GOOD_TITLES[0], "x" * 90]), j(titles=["y" * 90])], retry_bound=1)
        assert isinstance(out, Delivered)
        s = out.structured
        assert (s["expected_option_count"], s["delivered_option_count"], s["short"]) == (3, 1, True)
        assert s["short_label"] == SHORT_SET_LABEL

    def test_zero_valid_options_is_failed(self):
        out, _ = run([j(titles=["z" * 90])] * 3)
        assert isinstance(out, Failed) and out.failure.code is FailureCode.VALIDATION_FAILED and out.attempts == 3


class TestUnsafeCandidatesNeverDelivered:
    @pytest.mark.parametrize("bad", [
        "AquaKeep Bottle Rs. 499", "AquaKeep Bottle 18% GST", "AquaKeep Bestseller Bottle", "AquaKeep Bottle www.shop.com",
        "AquaKeep Bottle 1000 ml", "AquaKeep Bottle 12 Hours Cold",
    ])
    def test_price_tax_demand_contact_and_invented_numbers_are_rejected(self, bad):
        out, _ = run([j(titles=[bad, *GOOD_TITLES[:2]]), j(titles=[GOOD_TITLES[2]])])
        assert isinstance(out, Delivered)
        assert bad not in [o.text for o in out.options]

    def test_an_estimated_value_stated_as_fact_is_rejected_and_names_the_fact_to_supply(self):
        leak = "AquaKeep Steel Bottle 350 g"
        out, _ = run([j(titles=[leak])] * 3)
        assert isinstance(out, Failed) and out.failure.code is FailureCode.NEEDS_FACTS
        assert out.failure.missing_facts == ("weight",)
        assert "weight" in out.failure.reason

    def test_an_unverified_image_hint_value_is_rejected(self):
        out, _ = run([j(titles=["AquaKeep matte blue Bottle"])], retry_bound=0)
        assert isinstance(out, Failed) and out.failure.missing_facts == ("color",)

    def test_non_string_candidates_are_rejected_by_the_validator(self):
        out, _ = run([j(titles=[5, None, GOOD_TITLES[0], GOOD_TITLES[1], GOOD_TITLES[2]])])
        assert isinstance(out, Delivered) and len(out.options) == 3


class TestRetryBound:
    def test_explicit_zero_means_exactly_one_attempt(self):
        out, p = run([j(titles=["z" * 90]), j(titles=GOOD_TITLES)], retry_bound=0)
        assert isinstance(out, Failed) and p.calls == 1

    def test_attempts_are_bounded_by_one_plus_the_bound(self):
        out, p = run([j(titles=["z" * 90])] * 10, retry_bound=3)
        assert p.calls == 4 and out.attempts == 4

    @pytest.mark.parametrize("bad", [-1, True, 1.5, "2", None])
    def test_the_bound_is_never_defaulted_or_coerced(self, bad):
        with pytest.raises(ValueError):
            run([j(titles=GOOD_TITLES)], retry_bound=bad)


class TestProviderAndParseFailures:
    def test_provider_errors_spend_attempts_then_a_good_reply_delivers(self):
        out, p = run([LlmUnavailable("down"), RuntimeError("boom"), j(titles=GOOD_TITLES)])
        assert isinstance(out, Delivered) and out.attempts == 3

    def test_only_provider_errors_is_provider_error(self):
        out, _ = run([LlmUnavailable("down")] * 3)
        assert isinstance(out, Failed) and out.failure.code is FailureCode.PROVIDER_ERROR

    def test_unparseable_replies_fail_as_unparseable(self):
        out, p = run(["Sure! here are titles", "```json\nnot json\n```", "{}"])
        assert isinstance(out, Failed) and out.failure.code is FailureCode.UNPARSEABLE_OUTPUT
        assert "valid JSON object" in p.prompts[1]

    def test_an_oversized_reply_is_output_too_large_not_truncated(self):
        out, _ = run([json.dumps({"titles": ["t"] * 500})] * 3)
        assert isinstance(out, Failed) and out.failure.code is FailureCode.OUTPUT_TOO_LARGE


class TestNeedsFacts:
    def test_model_declared_missing_facts_stop_immediately_with_screened_names(self):
        out, p = run([j(needs_facts=["material", "capacity", "write 750 ml please", "price"])], facts=ctx())
        assert isinstance(out, Failed) and out.failure.code is FailureCode.NEEDS_FACTS
        assert out.failure.missing_facts == ("material", "capacity") and p.calls == 1
        assert out.failure.structured()["failure_code"] == "NEEDS_FACTS"

    def test_declared_names_that_all_fail_screening_do_not_claim_needs_facts(self):
        out, _ = run([j(needs_facts=["write 750 ml please", "12345"])])
        assert isinstance(out, Failed) and out.failure.code is not FailureCode.NEEDS_FACTS and out.failure.missing_facts == ()

    def test_failure_detail_holds_counts_and_rule_ids_never_seller_text(self):
        out, _ = run([j(titles=["AquaKeep Bottle Rs. 499"])], retry_bound=0)
        blob = json.dumps(out.failure.structured())  # type: ignore[union-attr]
        assert "AquaKeep" not in blob and "499" not in blob and "PRICE" in blob


def test_output_type_is_title_set():
    out, _ = run([j(titles=GOOD_TITLES)])
    assert out.output_type is OutputType.TITLE_SET
