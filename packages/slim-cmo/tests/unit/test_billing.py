"""billing: unit table, request planning, idempotent reuse, the all-or-nothing pre-check, the two
independent meters, settlement. Every expectation traces to spec §8 / §8.1.1 / §8.3 / §8.4.

No cap value is assumed anywhere: caps are plain test integers, and `cap=None` (no cap
configured) is exercised as its own state."""

from __future__ import annotations

import uuid

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from slim_cmo import billing as b
from slim_cmo.billing import Action, CapBasis, Meter, RequestedArtefact as RA, RequestError, RunStatus
from slim_cmo.types import GenerationStatus as S, Marketplace as M, OutputType as O

AMZ, FK, MS = M.AMAZON, M.FLIPKART, M.MEESHO


def req(t, m=None):
    return RA(t, m)


def existing(t, m, key, status=S.COMPLETE):
    return b.ExistingArtefact(uuid.uuid4(), t, m, key, status)


# --------------------------------------------------------------------------- the unit table
class TestUnitTable:
    def test_every_artefact_type_costs_exactly_one_unit(self):
        assert set(b.UNITS_PER_ARTEFACT) == set(O)
        assert set(b.UNITS_PER_ARTEFACT.values()) == {1}

    def test_zero_unit_actions_are_exactly_the_no_artefact_ones(self):
        assert b.ZERO_UNIT_ACTIONS == {Action.APPROVE_TITLE, Action.SUGGEST_NICHE_TERMS, Action.CONFIRM_NICHE_TERMS, Action.CONFIRM_IMAGE_HINT}
        for action in b.ZERO_UNIT_ACTIONS:
            assert b.units_for_action(action) == 0

    @pytest.mark.parametrize(
        "action,output",
        [
            (Action.GENERATE_TITLE_SETS, O.TITLE_SET), (Action.GENERATE_LISTING_COPY, O.LISTING_COPY),
            (Action.GENERATE_DESCRIPTION, O.DESCRIPTION), (Action.GENERATE_BULLETS, O.BULLETS),
            (Action.GENERATE_KEYWORDS, O.KEYWORDS), (Action.GENERATE_BACKEND_TERMS, O.BACKEND_TERMS),
            (Action.GENERATE_HASHTAGS, O.HASHTAGS), (Action.CATALOG_ANSWER, O.CATALOG_ANSWER), (Action.MARKET_TRENDS, O.TREND_REPORT),
        ],
    )
    def test_each_producing_action_costs_one_unit(self, action, output):
        assert b.ACTION_OUTPUT_TYPE[action] is output and b.units_for_action(action) == 1

    def test_action_ids_are_the_registered_trigger_ids(self):
        assert {a.value for a in Action} == {
            "cmo.generate_title_sets", "cmo.approve_title", "cmo.generate_listing_copy", "cmo.generate_description",
            "cmo.generate_bullets", "cmo.generate_keywords", "cmo.generate_backend_terms", "cmo.generate_hashtags",
            "cmo.catalog_answer", "cmo.suggest_niche_terms", "cmo.confirm_niche_terms", "cmo.confirm_image_hint", "cmo.market_trends",
        }
        assert not any("gst" in a.value for a in Action)  # C4: CMO has no GST action

    def test_event_kinds_are_the_trigger_ids(self):
        assert b.EVENT_KIND_BY_OUTPUT_TYPE[O.TITLE_SET] == "cmo.generate_title_sets"
        assert b.EVENT_KIND_BY_OUTPUT_TYPE[O.LISTING_COPY] == "cmo.generate_listing_copy"
        assert b.EVENT_KIND_BY_OUTPUT_TYPE[O.TREND_REPORT] == "cmo.market_trends"
        assert b.SHARED_TRENDS_EVENT_KIND == "research.market_trends"  # the shared meter is distinct from CMO's own
        assert b.SHARED_TRENDS_EVENT_KIND not in b.EVENT_KIND_BY_OUTPUT_TYPE.values()


# --------------------------------------------------------------------------- worked examples
class TestSpecWorkedTotals:
    def plan(self, items):
        return b.plan_request(items, request_key="r1", existing=[])

    def test_three_title_sets_cost_three_units(self):
        assert self.plan([req(O.TITLE_SET, m) for m in (AMZ, FK, MS)]).units_required == 3

    def test_full_workflow_all_three_marketplaces_is_six_units(self):
        items = [req(O.TITLE_SET, m) for m in (AMZ, FK, MS)] + [req(O.LISTING_COPY, m) for m in (AMZ, FK, MS)]
        assert self.plan(items).units_required == 6

    def test_one_marketplace_full_workflow_is_two_units(self):
        assert self.plan([req(O.TITLE_SET, AMZ), req(O.LISTING_COPY, AMZ)]).units_required == 2

    def test_hashtags_and_backend_terms_are_extra_units(self):
        base = [req(O.TITLE_SET, m) for m in (AMZ, FK, MS)] + [req(O.LISTING_COPY, m) for m in (AMZ, FK, MS)]
        with_tags = base + [req(O.HASHTAGS, m) for m in (AMZ, FK, MS)]
        assert self.plan(with_tags).units_required == 9
        assert self.plan(with_tags + [req(O.BACKEND_TERMS, AMZ)]).units_required == 10

    def test_standalone_components_after_a_pack_are_new_units_no_dedupe(self):
        items = [req(O.LISTING_COPY, AMZ), req(O.DESCRIPTION, AMZ), req(O.BULLETS, AMZ), req(O.KEYWORDS, AMZ)]
        assert self.plan(items).units_required == 4

    def test_a_trend_report_is_one_cmo_unit_plus_one_shared_unit(self):
        p = self.plan([req(O.TREND_REPORT)])
        assert (p.units_required, p.shared_units_required) == (1, 1)

    def test_other_artefacts_never_touch_the_shared_meter(self):
        assert self.plan([req(O.TITLE_SET, AMZ), req(O.CATALOG_ANSWER)]).shared_units_required == 0


# --------------------------------------------------------------------------- request validation
class TestRequestValidation:
    def bad(self, items):
        with pytest.raises(b.InvalidRequest) as exc:
            b.validate_request(items)
        return exc.value.code

    def test_empty_request(self):
        assert self.bad([]) is RequestError.EMPTY_REQUEST

    @pytest.mark.parametrize("t", sorted(b.MARKETPLACE_SCOPED_OUTPUT_TYPES, key=lambda x: x.value))
    def test_marketplace_scoped_artefacts_need_a_marketplace(self, t):
        assert self.bad([req(t)]) is RequestError.MARKETPLACE_REQUIRED

    def test_backend_terms_are_amazon_only(self):
        assert self.bad([req(O.BACKEND_TERMS, FK)]) is RequestError.BACKEND_TERMS_AMAZON_ONLY
        assert self.bad([req(O.BACKEND_TERMS, MS)]) is RequestError.BACKEND_TERMS_AMAZON_ONLY
        b.validate_request([req(O.BACKEND_TERMS, AMZ)])

    def test_trend_report_has_no_marketplace(self):
        assert self.bad([req(O.TREND_REPORT, AMZ)]) is RequestError.MARKETPLACE_NOT_ALLOWED

    def test_the_same_artefact_twice_in_one_request_is_refused(self):
        assert self.bad([req(O.TITLE_SET, AMZ), req(O.TITLE_SET, AMZ)]) is RequestError.DUPLICATE_ARTEFACT

    def test_same_type_for_different_marketplaces_is_fine(self):
        b.validate_request([req(O.TITLE_SET, AMZ), req(O.TITLE_SET, FK)])

    def test_marketplace_optional_for_hashtags_and_catalog_answers(self):
        b.validate_request([req(O.HASHTAGS), req(O.CATALOG_ANSWER)])
        b.validate_request([req(O.HASHTAGS, AMZ), req(O.CATALOG_ANSWER, AMZ)])


class TestRequestKey:
    def test_the_length_cap_is_an_internal_implementation_limit_not_a_business_or_marketplace_rule(self):
        """Documented decision: 128 characters bounds a client-supplied identifier (index size,
        abuse resistance). It is not tied to any marketplace, plan or entitlement."""
        assert b.MAX_REQUEST_KEY_CHARS == 128

    @pytest.mark.parametrize(
        "raw", ["a", "req-1", "abc.def_ghi:jkl-mno", "X" * 128, "  padded-key  ", "9start", "trailing\t", "\nleading"]
    )
    def test_accepted(self, raw):
        assert b.normalise_request_key(raw) == raw.strip()  # surrounding whitespace is trimmed, not rejected

    @pytest.mark.parametrize("raw", ["", "   ", "X" * 129, "-leading", ".leading", "has space", "new\nline", "inner\ttab", "unié", "emoji\U0001F600",
                                      "semi;colon", "quote'", None, 5, ["k"], b"bytes"])
    def test_rejected(self, raw):
        with pytest.raises(b.InvalidRequest) as exc:
            b.normalise_request_key(raw)
        assert exc.value.code is RequestError.BAD_REQUEST_KEY


# --------------------------------------------------------------------------- idempotent reuse
class TestPlanRequestReuse:
    ITEMS = [req(O.TITLE_SET, AMZ), req(O.TITLE_SET, FK), req(O.TITLE_SET, MS)]

    def test_complete_artefacts_under_the_same_key_are_reused_and_free(self):
        have = [existing(O.TITLE_SET, AMZ, "k1"), existing(O.TITLE_SET, FK, "k1")]
        p = b.plan_request(self.ITEMS, request_key="k1", existing=have)
        assert [i.marketplace for i in p.to_generate] == [MS]
        assert {r.item.marketplace for r in p.reused} == {AMZ, FK}
        assert {r.existing_id for r in p.reused} == {have[0].id, have[1].id}
        assert p.units_required == 1

    def test_everything_already_delivered_costs_nothing(self):
        have = [existing(O.TITLE_SET, m, "k1") for m in (AMZ, FK, MS)]
        p = b.plan_request(self.ITEMS, request_key="k1", existing=have)
        assert p.to_generate == () and p.units_required == 0 and len(p.reused) == 3

    def test_failed_attempts_are_ignored_so_the_retry_runs(self):
        have = [existing(O.TITLE_SET, AMZ, "k1", S.FAILED)]
        p = b.plan_request([req(O.TITLE_SET, AMZ)], request_key="k1", existing=have)
        assert len(p.to_generate) == 1 and p.reused == () and p.units_required == 1

    def test_a_different_key_is_a_regeneration_a_new_artefact_and_a_new_unit(self):
        have = [existing(O.TITLE_SET, AMZ, "k1")]
        p = b.plan_request([req(O.TITLE_SET, AMZ)], request_key="k2", existing=have)
        assert len(p.to_generate) == 1 and p.units_required == 1

    def test_reuse_is_scoped_to_type_and_marketplace(self):
        have = [existing(O.LISTING_COPY, AMZ, "k1"), existing(O.TITLE_SET, FK, "k1")]
        p = b.plan_request([req(O.TITLE_SET, AMZ)], request_key="k1", existing=have)
        assert len(p.to_generate) == 1

    def test_key_is_normalised_before_matching(self):
        have = [existing(O.TITLE_SET, AMZ, "k1")]
        assert b.plan_request([req(O.TITLE_SET, AMZ)], request_key="  k1 ", existing=have).units_required == 0

    def test_an_invalid_request_is_rejected_before_any_planning(self):
        with pytest.raises(b.InvalidRequest):
            b.plan_request([req(O.TITLE_SET)], request_key="k", existing=[])
        with pytest.raises(b.InvalidRequest):
            b.plan_request([req(O.TITLE_SET, AMZ)], request_key="bad key", existing=[])

    def test_a_reused_trend_report_is_free_on_both_meters(self):
        p = b.plan_request([req(O.TREND_REPORT)], request_key="k1", existing=[existing(O.TREND_REPORT, None, "k1")])
        assert (p.units_required, p.shared_units_required) == (0, 0)


# --------------------------------------------------------------------------- the pre-check
class TestPrecheck:
    def test_fits_exactly_at_the_boundary(self):
        out = b.precheck(3, usage=7, cap=10)
        assert out.allowed and out.basis is CapBasis.WITHIN_CAP and out.remaining == 3 and out.shortfall == 0

    def test_one_over_is_denied_whole(self):
        out = b.precheck(4, usage=7, cap=10)
        assert not out.allowed and out.basis is CapBasis.OVER_CAP and out.remaining == 3 and out.shortfall == 1

    def test_already_exhausted(self):
        out = b.precheck(1, usage=10, cap=10)
        assert not out.allowed and out.remaining == 0 and out.shortfall == 1

    def test_usage_above_cap_never_goes_negative(self):
        out = b.precheck(1, usage=15, cap=10)
        assert not out.allowed and out.remaining == 0 and out.shortfall == 1

    def test_zero_cap_denies_everything_that_costs_a_unit(self):
        assert not b.precheck(1, usage=0, cap=0).allowed

    def test_no_cap_configured_passes_and_says_so(self):
        out = b.precheck(99, usage=500, cap=None)
        assert out.allowed and out.basis is CapBasis.NO_CAP_CONFIGURED and out.remaining is None

    def test_nothing_to_bill_always_passes_even_over_cap(self):
        out = b.precheck(0, usage=100, cap=10)
        assert out.allowed and out.basis is CapBasis.NOTHING_TO_BILL and out.remaining == 0

    def test_matches_the_single_unit_semantics_of_the_existing_chokepoint(self):
        """backend.entitlement denies a 1-unit action when usage >= cap; so must we."""
        for usage in range(0, 6):
            for cap in range(0, 6):
                assert b.precheck(1, usage=usage, cap=cap).allowed == (not (usage >= cap))

    @pytest.mark.parametrize("kw", [dict(requested=-1, usage=0, cap=1), dict(requested=1, usage=-1, cap=1), dict(requested=1, usage=0, cap=-1),
                                    dict(requested=True, usage=0, cap=1), dict(requested=1, usage=0.5, cap=1), dict(requested="1", usage=0, cap=1)])
    def test_invalid_numbers_are_programming_errors(self, kw):
        with pytest.raises(ValueError):
            b.precheck(kw["requested"], usage=kw["usage"], cap=kw["cap"])

    @given(st.integers(0, 50), st.integers(0, 50), st.one_of(st.none(), st.integers(0, 50)))
    @settings(max_examples=300, deadline=None)
    def test_allowed_iff_it_fits(self, requested, usage, cap):
        out = b.precheck(requested, usage=usage, cap=cap)
        fits = requested == 0 or cap is None or usage + requested <= cap
        assert out.allowed == fits
        # shortfall is what the seller is told: units requested beyond what REMAINS (usage already
        # over the cap leaves 0 remaining; the pre-existing overage is not part of this request)
        assert out.shortfall == (0 if out.allowed else requested - max(cap - usage, 0))  # type: ignore[operator]

    def test_all_or_nothing_never_partially_admits(self):
        """Remaining 2, request 3: the answer is no for the whole request - never 'run two'."""
        out = b.precheck(3, usage=8, cap=10)
        assert not out.allowed and out.remaining == 2


class TestTwoMeters:
    def trend_plan(self):
        return b.plan_request([req(O.TREND_REPORT)], request_key="k", existing=[])

    def test_either_meter_denying_denies_the_report_and_names_which(self):
        plan = self.trend_plan()
        only_cmo = b.precheck_request(plan, cmo_usage=5, cmo_cap=5, shared_usage=0, shared_cap=5)
        assert not only_cmo.allowed and only_cmo.denied_by == (Meter.CMO,)
        only_shared = b.precheck_request(plan, cmo_usage=0, cmo_cap=5, shared_usage=5, shared_cap=5)
        assert not only_shared.allowed and only_shared.denied_by == (Meter.SHARED_TRENDS,)
        both = b.precheck_request(plan, cmo_usage=5, cmo_cap=5, shared_usage=5, shared_cap=5)
        assert both.denied_by == (Meter.CMO, Meter.SHARED_TRENDS)

    def test_exhausting_one_meter_does_not_affect_the_other_artefacts(self):
        """AC17: the shared meter only matters for trend reports."""
        plan = b.plan_request([req(O.TITLE_SET, AMZ)], request_key="k", existing=[])
        out = b.precheck_request(plan, cmo_usage=0, cmo_cap=5, shared_usage=999, shared_cap=1)
        assert out.allowed and out.shared is None

    def test_both_pass(self):
        out = b.precheck_request(self.trend_plan(), cmo_usage=0, cmo_cap=5, shared_usage=0, shared_cap=5)
        assert out.allowed and out.denied_by == () and out.shared is not None

    def test_uncapped_meters_pass(self):
        assert b.precheck_request(self.trend_plan(), cmo_usage=10, cmo_cap=None).allowed

    def test_a_mixed_request_checks_cmo_units_for_everything_and_shared_only_for_the_report(self):
        plan = b.plan_request([req(O.TITLE_SET, AMZ), req(O.TREND_REPORT)], request_key="k", existing=[])
        assert (plan.units_required, plan.shared_units_required) == (2, 1)
        out = b.precheck_request(plan, cmo_usage=4, cmo_cap=5, shared_usage=0, shared_cap=1)
        assert not out.allowed and out.denied_by == (Meter.CMO,) and out.cmo.shortfall == 1


# --------------------------------------------------------------------------- settlement
class TestSettlement:
    def test_all_complete(self):
        s = b.settle([b.ArtefactResult(req(O.TITLE_SET, m), S.COMPLETE) for m in (AMZ, FK, MS)])
        assert (s.units_billed, s.run_status, s.unbilled) == (3, RunStatus.COMPLETE, ())

    def test_failures_are_never_billed(self):
        s = b.settle([b.ArtefactResult(req(O.TITLE_SET, AMZ), S.FAILED)])
        assert (s.units_billed, s.run_status) == (0, RunStatus.FAILED) and s.billed == ()

    def test_partial_multi_marketplace_bills_only_the_delivered(self):
        results = [b.ArtefactResult(req(O.TITLE_SET, AMZ), S.COMPLETE), b.ArtefactResult(req(O.TITLE_SET, FK), S.FAILED),
                   b.ArtefactResult(req(O.TITLE_SET, MS), S.COMPLETE)]
        s = b.settle(results)
        assert s.units_billed == 2 and s.run_status is RunStatus.PARTIAL
        assert [i.marketplace for i in s.unbilled] == [FK]

    def test_a_delivered_trend_report_bills_the_shared_meter_too(self):
        s = b.settle([b.ArtefactResult(req(O.TREND_REPORT), S.COMPLETE)])
        assert (s.units_billed, s.shared_units_billed) == (1, 1)
        failed = b.settle([b.ArtefactResult(req(O.TREND_REPORT), S.FAILED)])
        assert (failed.units_billed, failed.shared_units_billed) == (0, 0)

    def test_empty_run_cannot_be_settled(self):
        with pytest.raises(ValueError):
            b.settle([])

    @given(st.lists(st.sampled_from(list(S)), min_size=1, max_size=8))
    @settings(max_examples=200, deadline=None)
    def test_billed_units_equal_the_number_of_complete_artefacts(self, statuses):
        results = [b.ArtefactResult(req(O.DESCRIPTION, AMZ if i % 2 else FK), st_) for i, st_ in enumerate(statuses)]
        out = b.settle(results)
        assert out.units_billed == sum(1 for s_ in statuses if s_ is S.COMPLETE)
        assert len(out.billed) + len(out.unbilled) == len(results)
