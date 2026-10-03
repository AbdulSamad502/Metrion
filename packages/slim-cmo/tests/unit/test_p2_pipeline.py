"""The P2 modules composed, driven by SIMULATED model output (no model exists yet - P3).

These are the spec's headline scenarios run through the deterministic safety net exactly as P3/P5
will call it: resolve the rule -> validate what the "model" produced -> check claims -> settle
the bill. If a seam between modules is wrong, it shows up here rather than in P5."""

from __future__ import annotations

import uuid
from datetime import timedelta

from slim_cmo import billing as b
from slim_cmo import claims as cl
from slim_cmo import narration as nr
from slim_cmo import validators as v
from slim_cmo.config import load_generation_config
from slim_cmo.constraints import ConstraintUnavailable, ResolvedConstraint, UnavailableReason, resolve_constraint
from slim_cmo.types import AttributeBasis as B
from slim_cmo.types import GenerationStatus as S
from slim_cmo.types import GroundingBasis, Marketplace as M, OutputType as O, TrustState as T
from slim_cmo.billing import RequestedArtefact as RA

from .factories import NOW, constraint

TENANT = uuid.uuid4()
GEN_CFG = load_generation_config({"format_constraint_max_age_days": 30, "internal_retry_bound": 2})
MAX_AGE = GEN_CFG.format_constraint_max_age_days  # type: ignore[union-attr]

ROWS = [
    constraint(M.AMAZON, title_max_chars=60, title_option_count=3, bullet_count=3),
    constraint(M.FLIPKART, title_max_chars=45, title_option_count=3, bullet_count=2, bullet_max_chars=40),
    constraint(M.MEESHO, title_max_chars=30, title_option_count=3, bullet_count=2, bullet_max_chars=30),
]

FACTS = [
    cl.Attribute("brand", "AquaKeep", B.SELLER_PROVIDED),
    cl.Attribute("material", "stainless steel", B.SELLER_PROVIDED),
    cl.Attribute("capacity", "750 ml", B.SELLER_PROVIDED),
    cl.Attribute("claim", "keeps drinks cold for 12 hours", B.SELLER_PROVIDED),
    cl.Attribute("weight", "350 g", B.ESTIMATED),
    cl.Attribute("color", "matte blue", B.IMAGE_OBSERVED, T.UNVERIFIED_HINT),
]
PART = cl.partition(FACTS)
CONTEXT = cl.allowed_context_text(PART.eligible)

MODEL_TITLES = {
    M.AMAZON: ["AquaKeep Stainless Steel Bottle 750 ml Keeps Cold 12 Hours", "AquaKeep Insulated Steel Flask 750 ml", "AquaKeep 750 ml Steel Water Bottle"],
    M.FLIPKART: ["AquaKeep Steel Bottle 750 ml", "AquaKeep Insulated Flask 750 ml Steel", "AquaKeep Stainless Water Bottle"],
    M.MEESHO: ["AquaKeep Steel Bottle 750 ml", "AquaKeep Cold Flask 750 ml", "AquaKeep Steel Flask"],
}


def resolve(mp, output=O.TITLE_SET, rows=ROWS):
    return resolve_constraint(rows, marketplace=mp, category=None, output_type=output, now=NOW, max_age_days=MAX_AGE)


class TestT8_ThreeMarketplaceTitleSets:
    def test_each_marketplace_is_validated_against_its_own_rule_and_billed_per_marketplace(self):
        accepted = {}
        for mp in M:
            resolved = resolve(mp)
            assert isinstance(resolved, ResolvedConstraint)
            ev = v.evaluate_title_set(MODEL_TITLES[mp], resolved.row, allowed_context=CONTEXT)
            assert ev.complete, (mp, ev.rejected)
            assert all(o.char_count <= resolved.row.title_max_chars for o in ev.accepted)  # type: ignore[operator]
            accepted[mp] = ev
        # the same Amazon-length title would NOT pass Meesho's tighter limit:
        meesho = resolve(M.MEESHO).row  # type: ignore[union-attr]
        assert not v.check_title(MODEL_TITLES[M.AMAZON][0], meesho).valid
        plan = b.plan_request([RA(O.TITLE_SET, m) for m in M], request_key="r1", existing=[])
        assert plan.units_required == 3
        settled = b.settle([b.ArtefactResult(i, S.COMPLETE) for i in plan.to_generate])
        assert (settled.units_billed, settled.run_status) == (3, b.RunStatus.COMPLETE)


class TestT8b_AllOrNothingPrecheck:
    def test_two_units_remaining_for_a_three_marketplace_request_denies_everything(self):
        plan = b.plan_request([RA(O.TITLE_SET, m) for m in M], request_key="r1", existing=[])
        out = b.precheck_request(plan, cmo_usage=8, cmo_cap=10)
        assert not out.allowed and out.cmo.remaining == 2 and out.cmo.shortfall == 1
        narrower = b.plan_request([RA(O.TITLE_SET, M.AMAZON), RA(O.TITLE_SET, M.FLIPKART)], request_key="r2", existing=[])
        assert b.precheck_request(narrower, cmo_usage=8, cmo_cap=10).allowed


class TestT8c_OneMarketplaceBlockedOthersDelivered:
    def test_missing_and_stale_constraints_block_only_that_marketplace(self):
        rows = [ROWS[0], constraint(M.FLIPKART, verified_at=NOW - timedelta(days=90)), ROWS[2]]  # Flipkart stale
        outcomes = {mp: resolve(mp, rows=rows) for mp in M}
        assert isinstance(outcomes[M.AMAZON], ResolvedConstraint) and isinstance(outcomes[M.MEESHO], ResolvedConstraint)
        blocked = outcomes[M.FLIPKART]
        assert isinstance(blocked, ConstraintUnavailable) and blocked.reason is UnavailableReason.STALE
        results = [b.ArtefactResult(RA(O.TITLE_SET, mp), S.FAILED if isinstance(r, ConstraintUnavailable) else S.COMPLETE) for mp, r in outcomes.items()]
        settled = b.settle(results)
        assert (settled.units_billed, settled.run_status) == (2, b.RunStatus.PARTIAL)
        assert [i.marketplace for i in settled.unbilled] == [M.FLIPKART]

    def test_with_no_staleness_policy_configured_everything_blocks(self):
        for mp in M:
            out = resolve_constraint(ROWS, marketplace=mp, category=None, output_type=O.TITLE_SET, now=NOW, max_age_days=None)
            assert isinstance(out, ConstraintUnavailable) and out.reason is UnavailableReason.CONFIG_MISSING


class TestT9_ApprovalThenGroundedPack:
    def approval(self, mp, text):
        return cl.ApprovalRef(uuid.uuid4(), TENANT, mp, text)

    def test_a_valid_flipkart_pack_grounded_on_the_flipkart_approval(self):
        row = resolve(M.FLIPKART, O.LISTING_COPY).row  # type: ignore[union-attr]
        approved = self.approval(M.FLIPKART, MODEL_TITLES[M.FLIPKART][0])
        g = cl.check_grounding(O.LISTING_COPY, tenant_id=TENANT, marketplace=M.FLIPKART,
                               grounding=cl.Grounding(GroundingBasis.APPROVED_TITLE, approval=approved), constraint=row)
        assert g.ok and g.persisted_columns() == ("APPROVED_TITLE", approved.id)
        pack = v.check_listing_copy(
            "A 750 ml stainless steel bottle from AquaKeep that keeps drinks cold for 12 hours.",
            ["Stainless steel, 750 ml", "Keeps drinks cold for 12 hours"],
            ["steel bottle", "insulated flask", "750 ml"],
            row, allowed_context=CONTEXT,
        )
        assert pack.valid, pack.violations
        prose = " ".join([pack.description, *pack.bullets, *pack.keywords])
        assert nr.check_copy_prose(prose, eligible=PART.eligible, ineligible=PART.ineligible, extra_allowed_text=[approved.approved_text]) == ()
        assert set(pack.structured()) == {"description", "bullets", "keywords"}

    def test_the_same_pack_cannot_hang_on_an_amazon_approval(self):
        row = resolve(M.FLIPKART, O.LISTING_COPY).row  # type: ignore[union-attr]
        amazon_approval = self.approval(M.AMAZON, MODEL_TITLES[M.AMAZON][0])
        g = cl.check_grounding(O.LISTING_COPY, tenant_id=TENANT, marketplace=M.FLIPKART,
                               grounding=cl.Grounding(GroundingBasis.APPROVED_TITLE, approval=amazon_approval), constraint=row)
        assert not g.ok and cl.GroundingError.MARKETPLACE_MISMATCH in g.errors
        # the 60-char Amazon title also exceeds Flipkart's tighter limit: a second, independent refusal
        assert cl.GroundingError.ANCHOR_TITLE_INVALID in g.errors


class TestT9d_T25_AnInvalidPackIsFailedAndFree:
    def row(self):
        return resolve(M.AMAZON, O.LISTING_COPY).row  # type: ignore[union-attr]

    def test_over_limit_bullets_a_price_and_a_gst_rate_all_fail_the_pack(self):
        pack = v.check_listing_copy(
            "Great steel bottle. Only Rs. 499 with 18% GST included.",
            ["Keeps cold", "Leak resistant", "Easy to clean", "A fourth bullet"],
            ["steel bottle"], self.row(), allowed_context=CONTEXT,
        )
        assert not pack.valid
        details = {x.detail for x in pack.violations}
        assert any("PRICE" in d for d in details) and any("TAX" in d for d in details)
        assert any(x.code is v.ViolationCode.TOO_MANY for x in pack.violations)
        with __import__("pytest").raises(ValueError):
            pack.structured()
        settled = b.settle([b.ArtefactResult(RA(O.LISTING_COPY, M.AMAZON), S.FAILED)])
        assert (settled.units_billed, settled.run_status) == (0, b.RunStatus.FAILED)

    def test_a_pack_that_only_breaks_the_description_still_fails_whole(self):
        pack = v.check_listing_copy("", ["a1", "b2", "c3"], ["steel"], self.row())
        assert not pack.valid


class TestT26_InventedFactsAreCaught:
    def test_estimates_hints_and_invented_numbers_fail_the_narration_check(self):
        prose = "A 350 g bottle with a matte blue finish, trusted by 10000 sellers."
        findings = nr.check_copy_prose(prose, eligible=PART.eligible, ineligible=PART.ineligible)
        got = {(f.kind, f.rule) for f in findings}
        assert ("INELIGIBLE_ATTRIBUTE", "weight") in got      # the ESTIMATED weight, stated as fact
        assert ("INELIGIBLE_ATTRIBUTE", "color") in got       # the unverified image hint, stated as fact
        assert ("UNSUPPORTED_NUMBER", "10000") in got          # a number in no input
        assert ("UNSUPPORTED_NUMBER", "350") in got

    def test_only_eligible_facts_are_available_to_ground_copy(self):
        assert {a.name for a in PART.eligible} == {"brand", "material", "capacity", "claim"}
        reasons = {a.name: r for a, r in PART.ineligible}
        assert reasons == {"weight": cl.EligibilityReason.ESTIMATED, "color": cl.EligibilityReason.UNVERIFIED_IMAGE_HINT}


class TestFailSafesForMissingOptionalConfiguration:
    """Decision (P2 review): missing tactic-risk patterns and official-domain configuration
    fail SAFE - they never default to 'assessed clean' or 'official'."""

    def test_end_to_end_with_neither_optional_key_configured(self):
        from slim_cmo.config import TrendConfig, load_trend_config
        from slim_cmo.trends.risk import PolicyRisk, assess_tactic_risk
        from slim_cmo.trends.sources import SourceClass, classify_source

        from .factories import trend_values
        from .trends.helpers import item

        cfg = load_trend_config(trend_values())
        assert isinstance(cfg, TrendConfig)
        assert cfg.tactic_risk_pattern_set_ref is None and cfg.official_marketplace_domains == frozenset()
        risk = assess_tactic_risk("use fake reviews to climb the rankings", None)  # no pattern set loaded
        assert risk.risk is PolicyRisk.UNASSESSED and risk.suggested_actions_allowed == frozenset()
        assert classify_source(item("https://amazon.in/seller-news"), cfg.official_marketplace_domains) is SourceClass.THIRD_PARTY

    def test_configuring_them_enables_assessment_and_classification(self):
        from slim_cmo.config import TrendConfig, load_trend_config

        from .factories import trend_values

        cfg = load_trend_config(trend_values(tactic_risk_pattern_set_ref="risk-v1", official_marketplace_domains=["amazon.in"]))
        assert isinstance(cfg, TrendConfig)
        assert cfg.tactic_risk_pattern_set_ref == "risk-v1" and cfg.official_marketplace_domains == frozenset({"amazon.in"})


class TestIdempotencyAtTheCap:
    def test_a_duplicate_submission_at_the_cap_is_still_served_and_free(self):
        delivered = [b.ExistingArtefact(uuid.uuid4(), O.TITLE_SET, m, "r1", S.COMPLETE) for m in M]
        plan = b.plan_request([RA(O.TITLE_SET, m) for m in M], request_key="r1", existing=delivered)
        assert plan.units_required == 0 and len(plan.reused) == 3
        assert b.precheck_request(plan, cmo_usage=10, cmo_cap=10).allowed  # exhausted allowance, nothing to bill

    def test_a_regeneration_under_a_new_key_costs_again(self):
        delivered = [b.ExistingArtefact(uuid.uuid4(), O.TITLE_SET, M.AMAZON, "r1", S.COMPLETE)]
        plan = b.plan_request([RA(O.TITLE_SET, M.AMAZON)], request_key="r2", existing=delivered)
        assert plan.units_required == 1 and not b.precheck_request(plan, cmo_usage=10, cmo_cap=10).allowed


class TestT30_TrendEvidenceEndToEnd:
    def test_config_budget_evidence_report_and_interpretation_compose(self):
        from slim_cmo.config import TrendConfig, load_trend_config
        from slim_cmo.trends import interpretation as ip
        from slim_cmo.trends.budget import QueryBudget
        from slim_cmo.trends.evidence import Thresholds, evaluate_evidence
        from slim_cmo.trends.report import SectionOutcome, SectionState, Verdict, assess_report
        from slim_cmo.trends.risk import PolicyRisk
        from slim_cmo.types import TrendSection as TS

        from .factories import trend_values
        from .trends.helpers import days, item

        cfg = load_trend_config(trend_values())
        assert isinstance(cfg, TrendConfig)
        budget = QueryBudget(cfg, [TS.NICHE, TS.MARKET_NEWS])
        assert budget.try_spend(TS.NICHE).allowed and not budget.try_spend(TS.ADJACENT).allowed

        wire = [item(f"https://{d}.com/w", title="Marketplace Fee Policy Updated", age=days(2 + i)) for i, d in enumerate("xyz")]
        own = [item(f"https://home.com/a{i}", title=f"Home piece {i}", age=days(1)) for i in range(10)]
        ev = evaluate_evidence(wire + own, Thresholds.from_config(cfg))
        assert (ev.mention_count, ev.independent_source_count) == (13, 2)

        outcomes = [SectionOutcome(TS.NICHE, SectionState.COMPLETE, 1), SectionOutcome(TS.MARKET_NEWS, SectionState.COMPLETE, 1)] + [
            SectionOutcome(s, SectionState.UNAVAILABLE, 0, "NOT_REQUESTED") for s in (TS.REPORTED_TACTICS, TS.NEW_PRODUCTS_BUZZ, TS.ADJACENT)]
        assessment = assess_report(outcomes)
        assert assessment.verdict is Verdict.COMPLETE and assessment.units_to_bill == 1 and len(assessment.degraded) == 3

        refs = {"n1": ip.FindingRef("n1", TS.NICHE, "Steel bottles attract attention across 2 independent sources", None)}
        checked = ip.check_interpretation(
            [ip.InterpretationItem("Watch this theme while it develops.", ("n1",), "WATCHLIST"),
             ip.InterpretationItem("This will sell fast.", ("n1",), "WATCHLIST")], refs)
        assert len(checked.accepted) == 1 and checked.rejected[0].index == 1
        assert PolicyRisk.NONE_IDENTIFIED.value == "NONE_IDENTIFIED"
