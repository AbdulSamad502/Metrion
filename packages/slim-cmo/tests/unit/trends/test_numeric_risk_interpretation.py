"""trends.numeric, trends.risk, trends.interpretation: the honesty rules of the trend report
(AC27, AC29, AC33, T32, T33, T40). A tactic is only ever REPORTED; news restates no figure;
the model's interpretation cites findings and adds no fact."""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from slim_cmo.trends import interpretation as ip
from slim_cmo.trends import numeric as nm
from slim_cmo.trends import risk as rk
from slim_cmo.trends.interpretation import InterpretationItem as Item, Problem as P
from slim_cmo.trends.risk import PolicyRisk as PR, RiskBasis as RB
from slim_cmo.types import TrendSection as S


# --------------------------------------------------------------------------- numeric claims
class TestNumericClaims:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("The fee rises to 12%", {"percent", "number"}),
            ("a 12 percent commission", {"percent", "number"}),
            ("twelve per cent", {"percent"}),
            ("charges of Rs. 50 per order", {"currency", "number"}),
            ("₹500 minimum", {"currency", "number"}),
            ("INR charges apply", {"currency"}),
            ("sellers lost 3 lakh in refunds", {"magnitude", "number"}),
            ("a crore of orders", {"magnitude"}),
            ("Top 5 selling tips", {"number"}),
            ("2x faster delivery", {"number"}),
            ("fees were revised", set()),
            ("Amazon announced a policy change for sellers", set()),
        ],
    )
    def test_claims_detected(self, text, expected):
        assert set(nm.find_numeric_claims(text)) == expected

    @pytest.mark.parametrize(
        "text",
        [
            "effective 1 November 2026",
            "effective 1st Nov 2026",
            "from Nov 1, 2026",
            "starting November 2026",
            "announced on 2026-11-01",
            "applies from 01/11/2026",
            "applies from 01-11-26",
            "during the 2026 festive season",
            "in Q3 and Q4",
            "for FY26 onwards",
            "on 15 August",
            "since 3rd of October 2026",
        ],
    )
    def test_dates_are_not_claims(self, text):
        assert nm.find_numeric_claims(text) == (), text

    def test_a_date_does_not_excuse_a_figure_next_to_it(self):
        assert "percent" in nm.find_numeric_claims("From 1 November 2026 the fee is 5%")
        assert "number" in nm.find_numeric_claims("From 1 November 2026, 40 categories change")

    def test_obfuscation_cannot_hide_a_figure(self):
        assert nm.contains_numeric_claim("fee １２％")  # full-width 12%
        assert nm.contains_numeric_claim("१२ percent")  # Devanagari digits
        assert nm.contains_numeric_claim("1​2%")  # zero-width inside the number

    def test_result_is_sorted_and_unique(self):
        out = nm.find_numeric_claims("5% 5% Rs 5")
        assert list(out) == sorted(set(out))

    @given(st.text(max_size=80))
    @settings(max_examples=300, deadline=None)
    def test_never_raises_and_bool_agrees(self, text):
        assert nm.contains_numeric_claim(text) == bool(nm.find_numeric_claims(text))


# --------------------------------------------------------------------------- tactic risk
def pattern_set():
    return rk.pattern_set_from_entries(
        "test-set-v1",
        [
            {"id": "fake-reviews", "regex": r"fake\s+reviews?|buy\s+reviews", "level": "LIKELY"},
            {"id": "keyword-stuffing", "regex": r"keyword\s+stuffing", "level": "POSSIBLE"},
        ],
    )


class TestPatternSet:
    def test_valid(self):
        ps = pattern_set()
        assert ps.usable and ps.version == "test-set-v1" and len(ps.patterns) == 2

    @pytest.mark.parametrize(
        "entries",
        [
            [{"id": "a", "regex": "(", "level": "LIKELY"}],  # invalid regex
            [{"id": "a", "regex": "x", "level": "NONE_IDENTIFIED"}],  # level must be POSSIBLE/LIKELY
            [{"id": "a", "regex": "x", "level": "UNASSESSED"}],
            [{"id": "a", "regex": "x", "level": "bogus"}],
            [{"id": "a", "regex": "x", "level": "LIKELY"}, {"id": "a", "regex": "y", "level": "LIKELY"}],  # duplicate id
            [{"id": " ", "regex": "x", "level": "LIKELY"}],
            [{"id": "a", "level": "LIKELY"}],  # missing regex
        ],
    )
    def test_a_malformed_set_can_never_be_loaded(self, entries):
        with pytest.raises(rk.PatternSetInvalid):
            rk.pattern_set_from_entries("v1", entries)

    def test_version_is_required(self):
        with pytest.raises(rk.PatternSetInvalid):
            rk.RiskPatternSet("  ", ())


class TestAssessTacticRisk:
    def test_no_pattern_set_is_unassessed_the_failsafe(self):
        out = rk.assess_tactic_risk("use fake reviews to rank", None)
        assert (out.risk, out.basis, out.matched_pattern_ids) == (PR.UNASSESSED, RB.NONE, ())
        assert out.suggested_actions_allowed == frozenset()

    def test_an_empty_pattern_set_is_not_assessed_clean(self):
        """A configured list that can match nothing must not read as 'assessed and safe'."""
        out = rk.assess_tactic_risk("anything at all", rk.RiskPatternSet("v1", ()))
        assert out.risk is PR.UNASSESSED and out.suggested_actions_allowed == frozenset()

    def test_assessed_and_clean(self):
        out = rk.assess_tactic_risk("post short videos showing the product in use", pattern_set())
        assert (out.risk, out.basis) == (PR.NONE_IDENTIFIED, RB.NONE)
        assert out.suggested_actions_allowed == frozenset({"WATCHLIST", "CONTENT_ANGLE"})

    def test_likely_and_possible_matches(self):
        likely = rk.assess_tactic_risk("sellers buy reviews to climb", pattern_set())
        assert (likely.risk, likely.basis, likely.matched_pattern_ids) == (PR.LIKELY, RB.PATTERN_MATCH, ("fake-reviews",))
        possible = rk.assess_tactic_risk("do some Keyword  Stuffing", pattern_set())
        assert possible.risk is PR.POSSIBLE and possible.suggested_actions_allowed == frozenset()

    def test_the_highest_matching_level_wins(self):
        out = rk.assess_tactic_risk("keyword stuffing and fake reviews", pattern_set())
        assert out.risk is PR.LIKELY and out.matched_pattern_ids == ("fake-reviews", "keyword-stuffing")

    def test_matching_survives_case_width_and_zero_width_obfuscation(self):
        for text in ("FAKE REVIEWS", "f​ake rev​iews", "ｆａｋｅ reviews"):
            assert rk.assess_tactic_risk(text, pattern_set()).risk is PR.LIKELY, text

    def test_a_model_flag_raises_a_clean_tactic(self):
        out = rk.assess_tactic_risk("a harmless-looking trick", pattern_set(), model_flagged=True)
        assert (out.risk, out.basis) == (PR.POSSIBLE, RB.MODEL_FLAG) and out.suggested_actions_allowed == frozenset()

    def test_a_model_flag_raises_unassessed_too(self):
        out = rk.assess_tactic_risk("trick", None, model_flagged=True)
        assert (out.risk, out.basis) == (PR.POSSIBLE, RB.MODEL_FLAG)

    def test_a_model_flag_never_lowers_a_pattern_verdict(self):
        both = rk.assess_tactic_risk("fake reviews", pattern_set(), model_flagged=True)
        assert (both.risk, both.basis) == (PR.LIKELY, RB.BOTH)

    def test_the_model_cannot_clear_a_pattern_hit(self):
        """There is no API to pass 'model says safe'; the only model input can raise."""
        assert rk.assess_tactic_risk("buy reviews", pattern_set(), model_flagged=False).risk is PR.LIKELY

    @pytest.mark.parametrize("risk,actions", [(PR.NONE_IDENTIFIED, True), (PR.POSSIBLE, False), (PR.LIKELY, False), (PR.UNASSESSED, False)])
    def test_only_a_clean_assessed_tactic_may_be_actioned(self, risk, actions):
        a = rk.RiskAssessment(risk, RB.NONE, ())
        assert rk.suggested_action_permitted("WATCHLIST", a) is actions
        assert rk.suggested_action_permitted("CONTENT_ANGLE", a) is actions
        assert rk.suggested_action_permitted("NO_ACTION", a) is True
        assert rk.suggested_action_permitted("LISTING_KEYWORD_IDEA", a) is False  # never offered for a tactic
        assert rk.suggested_action_permitted("INVESTIGATE_WITH_PI", a) is False

    def test_the_standing_policy_line_is_fixed_text(self):
        assert rk.POLICY_CHECK_LINE == "Check the marketplace's current seller policy before trying this."

    @given(st.text(max_size=100), st.booleans())
    @settings(max_examples=200, deadline=None)
    def test_a_flag_never_produces_a_safer_result(self, text, flag):
        base = rk.assess_tactic_risk(text, pattern_set(), model_flagged=False)
        flagged = rk.assess_tactic_risk(text, pattern_set(), model_flagged=flag)
        order = {PR.UNASSESSED: -1, PR.NONE_IDENTIFIED: 0, PR.POSSIBLE: 1, PR.LIKELY: 2}
        assert order[flagged.risk] >= order[base.risk]


# --------------------------------------------------------------------------- interpretation
def findings():
    return {
        "f1": ip.FindingRef("f1", S.NICHE, "Steel bottles are attracting attention in a video from Nov 2026", None),
        "f2": ip.FindingRef("f2", S.NEW_PRODUCTS_BUZZ, "A new bottle launched; 3 videos discuss it", None),
        "t_clean": ip.FindingRef("t_clean", S.REPORTED_TACTICS, "Reported by a blog: short product demos", PR.NONE_IDENTIFIED),
        "t_risky": ip.FindingRef("t_risky", S.REPORTED_TACTICS, "Reported: buying reviews", PR.LIKELY),
        "t_unassessed": ip.FindingRef("t_unassessed", S.REPORTED_TACTICS, "Reported: a ranking trick", PR.UNASSESSED),
    }


def item(statement="Consider adding steel bottle to your keyword research.", ids=("f1",), action="LISTING_KEYWORD_IDEA"):
    return Item(statement, tuple(ids), action)


class TestInterpretation:
    def check(self, *items):
        return ip.check_interpretation(items, findings())

    def test_the_label_is_a_fixed_constant(self):
        assert ip.INTERPRETATION_LABEL == "CMO's interpretation — not a verified market fact."

    def test_a_good_item_is_accepted(self):
        out = self.check(item())
        assert len(out.accepted) == 1 and not out.rejected

    def test_uncited_or_unknown_citations_are_rejected(self):
        assert P.NO_CITATION in self.check(item(ids=())).rejected[0].problems
        assert P.UNKNOWN_FINDING in self.check(item(ids=("nope",))).rejected[0].problems
        assert P.UNKNOWN_FINDING in self.check(item(ids=("f1", "nope"))).rejected[0].problems  # T40

    def test_unknown_action_types(self):
        assert P.BAD_ACTION in self.check(item(action="BUY_NOW")).rejected[0].problems

    @pytest.mark.parametrize("action", sorted(ip.ACTION_TYPES))
    def test_all_defined_actions_are_valid_for_non_tactics(self, action):
        assert self.check(item(action=action)).accepted

    def test_numbers_must_come_from_the_cited_findings(self):
        assert self.check(item("Three videos discuss it.", ids=("f2",))).accepted  # a number WORD adds no digit; allowed
        ok = self.check(item("Run 3 experiments.", ids=("f2",)))  # '3' is in f2's text
        assert ok.accepted
        bad = self.check(item("Expect 40 new orders a week.", ids=("f2",)))
        assert P.UNSUPPORTED_NUMBER in bad.rejected[0].problems

    def test_a_number_from_an_uncited_finding_is_not_allowed(self):
        assert P.UNSUPPORTED_NUMBER in self.check(item("In 3 videos it appears.", ids=("f1",))).rejected[0].problems  # '3' lives in f2

    @pytest.mark.parametrize(
        "statement",
        ["This is selling well.", "Demand is rising for steel bottles.", "A guaranteed profit opportunity.", "It will sell fast.",
         "Clearly trending and popular.", "This proves demand."],
    )
    def test_attention_must_not_be_written_as_demand(self, statement):
        assert P.BANNED_CLAIM in self.check(item(statement)).rejected[0].problems, statement

    def test_a_risky_or_unassessed_tactic_allows_no_action_at_all(self):
        for fid in ("t_risky", "t_unassessed"):
            for action in sorted(ip.ACTION_TYPES - {"NO_ACTION"}):
                out = self.check(item(ids=(fid,), action=action))
                assert out.rejected and P.TACTIC_ACTION_NOT_ALLOWED in out.rejected[0].problems, (fid, action)
            assert self.check(item("Noted for awareness only.", ids=(fid,), action="NO_ACTION")).accepted

    def test_a_clean_tactic_allows_only_watchlist_or_content_angle(self):
        assert self.check(item("Worth watching.", ids=("t_clean",), action="WATCHLIST")).accepted
        assert self.check(item("A content idea.", ids=("t_clean",), action="CONTENT_ANGLE")).accepted
        for action in ("LISTING_KEYWORD_IDEA", "INVESTIGATE_WITH_PI"):
            assert P.TACTIC_ACTION_NOT_ALLOWED in self.check(item(ids=("t_clean",), action=action)).rejected[0].problems

    def test_mixing_a_tactic_with_other_findings_still_applies_the_tactic_rule(self):
        out = self.check(item(ids=("f1", "t_risky"), action="LISTING_KEYWORD_IDEA"))
        assert P.TACTIC_ACTION_NOT_ALLOWED in out.rejected[0].problems

    def test_empty_statements(self):
        for s in ("", "   ", "​"):
            assert P.EMPTY_STATEMENT in self.check(item(s)).rejected[0].problems

    def test_every_problem_is_reported_not_just_the_first(self):
        out = self.check(item("It is selling well, 99 sold.", ids=("nope",), action="BUY"))
        assert {P.UNKNOWN_FINDING, P.BAD_ACTION, P.BANNED_CLAIM} <= set(out.rejected[0].problems)

    def test_rejected_items_are_never_edited_into_compliance(self):
        original = item("It is selling well.")
        out = self.check(original, item())
        assert [r.index for r in out.rejected] == [0] and len(out.accepted) == 1
        assert out.accepted[0].statement == item().statement

    def test_accepted_statements_are_cleaned_of_invisible_padding(self):
        assert self.check(item("  ​Consider adding steel bottle keywords.​ ")).accepted[0].statement == "Consider adding steel bottle keywords."
