"""CI spec C26 / C40 / C45 / AC29 / AC33 / AC47 — Competitor Intelligence narration is checked by the PRODUCTION composition gate, not by a prompt.

Scripted models stand in for a composer that misbehaves in the four ways CI cares about: it invents a number, presents stale evidence as current, recommends a price change
nobody calculated, and claims to be watching competitors live. Each draft must be rejected (the answer falls back to the fixed template) and a faithful draft must pass.
"""

from __future__ import annotations

import re
from uuid import uuid4

import pytest

from backend.ceo.composer import EvidenceTable, compose
from backend.ceo.composition_gate import check_composition, ci_narration_violations
from backend.ceo.contract import LegResult, LegStatus
from backend.ceo.evidence import EvidenceCollector
from backend.llm.model import Completion


def model(text: str):
    class M:
        name = "scripted"

        def complete(self, prompt, *, schema=None, max_output_tokens=None):
            return Completion(text, 5, output_tokens=20, error=None)

    return M()


def ci_table(*, finance: bool = False, **kw) -> EvidenceTable:
    return EvidenceTable(ci_narration=True, finance_present=finance, **kw)


GAP = (("G1", "Fossil Grant: there is no current evidence, so I cannot say what it charges now. The seller can send a fresh screenshot of Fossil Grant."),)


def codes(draft: str, **kw) -> frozenset[str]:
    return check_composition(draft, figure_tokens={}, other_tokens=["G1"], ci_narration=True, **kw).codes()


# ---- the four failure modes ---------------------------------------------------------
@pytest.mark.parametrize("draft", [
    "Titan dropped its price to 2699 rupees. {{G1}}",  # an invented number
    "Titan is now about 9 percent cheaper than you. {{G1}}",
    "Titan sells at ₹2,699. {{G1}}",
])
def test_an_invented_number_is_rejected(draft) -> None:
    assert codes(draft) & {"NUMERAL_DIGIT", "NUMERAL_CURRENCY", "NUMERAL_PERCENT"}
    c = compose(model(draft), "how is Titan priced?", "ACTION", ci_table(gaps=GAP))
    assert c.mode == "TEMPLATE_FALLBACK" and c.safety["gate"] == "FAIL"


@pytest.mark.parametrize("draft", [
    "Fossil Grant is currently priced below you. {{G1}}",
    "Fossil is selling at a lower price right now. {{G1}}",
    "Titan is currently charging less than you. {{G1}}",
])
def test_stale_evidence_presented_as_current_is_rejected(draft) -> None:
    assert "LIVE_CLAIM" in codes(draft)
    assert compose(model(draft), "q", "ACTION", ci_table(gaps=GAP)).mode == "TEMPLATE_FALLBACK"


@pytest.mark.parametrize("draft", [
    "You should lower your price to match Titan. {{G1}}",
    "I recommend that you reduce your price this week. {{G1}}",
    "Consider cutting your price to beat Fossil. {{G1}}",
    "Best to match their price. {{G1}}",
    "It is time to reprice your watch. {{G1}}",
])
def test_an_unsupported_repricing_recommendation_is_rejected(draft) -> None:
    assert "UNSUPPORTED_RECOMMENDATION" in codes(draft)
    assert compose(model(draft), "q", "ACTION", ci_table(gaps=GAP)).mode == "TEMPLATE_FALLBACK"


@pytest.mark.parametrize("draft", [
    "Your margin would fall if you match Titan. {{G1}}",
    "Your profit will drop because of this. {{G1}}",
    "The contribution is shrinking after their cut. {{G1}}",
])
def test_a_margin_claim_without_a_finance_result_is_rejected(draft) -> None:
    assert "MARGIN_CLAIM" in codes(draft)


@pytest.mark.parametrize("draft", [
    "I am tracking Titan in real time. {{G1}}",
    "Your competitors are continuously monitored. {{G1}}",
    "I am watching these competitors for you around the clock, 24/7. {{G1}}",
    "These are the live prices. {{G1}}",
    "The data is always up to date. {{G1}}",
])
def test_a_false_live_monitoring_claim_is_rejected(draft) -> None:
    assert "LIVE_CLAIM" in codes(draft)
    assert compose(model(draft), "q", "ACTION", ci_table(gaps=GAP)).mode == "TEMPLATE_FALLBACK"


# ---- a faithful draft passes --------------------------------------------------------
def test_a_faithful_ci_answer_passes_and_names_the_gap() -> None:
    draft = "Titan's newest screenshot is recent and showed a verified price drop. I do not have current evidence for Fossil. {{G1}}"
    assert codes(draft) == frozenset()
    c = compose(model(draft), "how are my competitors?", "ACTION", ci_table(gaps=GAP))
    assert c.mode == "LLM" and "cannot say what it charges now" in c.text  # the gap text is written by code after the gate


def test_dropping_the_stale_gap_is_rejected() -> None:
    c = compose(model("Titan's screenshot is recent."), "q", "ACTION", ci_table(gaps=GAP))
    assert c.mode == "TEMPLATE_FALLBACK" and "MISSING_REQUIRED" in c.safety["violations"]


def test_a_price_implication_is_allowed_once_a_finance_result_is_part_of_the_evidence() -> None:
    draft = "Matching Titan would change your margin, as the finance figures show. {{G1}}"
    assert "MARGIN_CLAIM" in codes(draft)
    assert "MARGIN_CLAIM" not in codes(draft, finance_present=True)
    assert "UNSUPPORTED_RECOMMENDATION" not in codes("You could match their price if you accept that. {{G1}}", finance_present=True)
    assert "LIVE_CLAIM" in codes("I am tracking this in real time. {{G1}}", finance_present=True)  # a finance result never excuses a live claim


def test_the_rules_apply_only_to_answers_that_use_ci_results() -> None:
    plain = check_composition("You should lower your price.", figure_tokens={}, other_tokens=[])
    assert plain.passed  # a non-CI answer is judged by the existing rules only: nothing about CI changes any other agent's behaviour


def test_honest_negations_are_not_false_positives() -> None:
    for ok in ["I do not watch competitors between your screenshots.", "Here is the live listing link you shared.", "The price you confirmed is saved.", "I have no current evidence for Fossil."]:
        assert ci_narration_violations(ok, finance_present=False) == [], ok


# ---- the evidence the composer is given ---------------------------------------------
def leg(key: str, payload, status=LegStatus.COMPLETE) -> LegResult:
    return LegResult(action_key=key, status=status, payload=payload)


MONITOR = {
    "asOf": "2026-10-18T12:00:00+00:00", "productCount": 1,
    "products": [{"productId": "SKU-1", "competitors": [
        {"label": "Titan Octane", "freshness": "FRESH", "verifiedDeltaPct": "-9.2", "deltaDirection": "DECREASE", "requestedAction": None, "lastVerifiedPricePaise": 269900},
        {"label": "Fossil Grant", "freshness": "STALE", "verifiedDeltaPct": None, "deltaDirection": None, "requestedAction": "send a fresh screenshot of Fossil Grant", "lastVerifiedPricePaise": None},
        {"label": "Casio", "freshness": "UNAVAILABLE", "requestedAction": "send a fresh screenshot of Casio", "lastVerifiedPricePaise": None},
    ]}],
}


def test_a_monitor_result_gives_the_composer_words_not_numbers_and_names_every_competitor_without_current_evidence() -> None:
    c = EvidenceCollector(uuid4())
    c.add_leg(leg("ci.monitor_competitors", MONITOR))
    t = c.table()
    assert t.ci_narration and not t.finance_present
    text = " ".join(f"{a} {b}" for a, b, _ in t.facts) + " " + " ".join(m for _, m in t.gaps)
    assert not re.search(r"\d|₹", text), text  # no digit and no price reaches the composer from a monitoring result
    assert "recent" in text and "verified price drop" in text and "nothing is watched between screenshots" in text
    assert len(t.gaps) == 2 and {"Fossil Grant", "Casio"} <= {g.split(":")[0] for _, g in t.gaps}  # the stale and the missing one are required gaps


def test_an_empty_watchlist_is_a_named_gap_not_a_result() -> None:
    c = EvidenceCollector(uuid4())
    c.add_leg(leg("ci.monitor_competitors", {"products": []}))
    t = c.table()
    assert [g for _, g in t.gaps] == ["No competitors are tracked yet, so there is nothing to re-check."] and not t.facts or all("watched" in f[1] for f in t.facts)


def test_review_themes_are_stated_with_their_sample_limit_and_no_number() -> None:
    c = EvidenceCollector(uuid4())
    c.add_leg(leg("ci.review_findings", {"findings": [{"label": "Titan Octane", "complaintThemes": [{"theme": "rigid strap"}, {"theme": "dial fogging"}], "reviewsConsidered": 80}]}))
    t = c.table()
    text = " ".join(f"{a} {b}" for a, b, _ in t.facts)
    assert "rigid strap" in text and "small sample" in text and not re.search(r"\d", text)
    c2 = EvidenceCollector(uuid4())
    c2.add_leg(leg("ci.review_findings", {"findings": []}))
    assert "no saved competitor review evidence" in c2.table().gaps[0][1]


def test_a_failed_search_is_never_narrated_as_no_competitors() -> None:
    c = EvidenceCollector(uuid4())
    c.add_leg(leg("ci.discover_competitors", {"status": "FAILED"}))
    gap = c.table().gaps[0][1]
    assert "does not mean there are no competitors" in gap
    ok = EvidenceCollector(uuid4())
    ok.add_leg(leg("ci.discover_competitors", {"status": "COMPLETE"}))
    assert "not verified prices" in ok.table().facts[0][1]


def test_a_finance_leg_in_the_same_turn_is_what_allows_a_price_implication() -> None:
    c = EvidenceCollector(uuid4())
    c.add_leg(leg("ci.monitor_competitors", MONITOR))
    c.add_leg(leg("cfo.pricing", {}, status=LegStatus.COMPLETE))
    t = c.table()
    assert t.ci_narration and t.finance_present
    refused = EvidenceCollector(uuid4())
    refused.add_leg(leg("ci.monitor_competitors", MONITOR))
    refused.add_leg(leg("cfo.pricing", None, status=LegStatus.DENIED))
    assert refused.table().ci_narration and not refused.table().finance_present  # a refused finance leg supplies no finance result, so it excuses nothing
