"""CMO 3.0 M3 routing and presentation (pure code): comparing titles is its own request; writing and choosing titles keep their routes; the comparison text never shows a number score."""

from __future__ import annotations

import pytest

from backend.ceo import classifier, evidence, intent_router, question_types
from backend.ceo import input_session as ins
from backend.ceo.plans import ACTIONS, PLAYBOOKS


def decide(text):
    return intent_router.route(text, classifier.build_catalog(list(ACTIONS), list(PLAYBOOKS), question_types.descriptions()))


@pytest.mark.parametrize("text", ["compare these titles", "Which title is best?", "analyse my titles", "score my five titles", "evaluate the title options", "how good are my titles",
                                  "title comparison", "check my titles"])
def test_comparing_titles_is_routed_to_the_analyzer(text):
    d = decide(text)
    assert d is not None and d.key == "cmo.analyze_titles", (text, d)


@pytest.mark.parametrize("text,key", [("write 5 titles for my bottle on amazon", "cmo.generate_title_sets"), ("generate title options for steel bottle", "cmo.generate_title_sets"),
                                      ("use option 2", "cmo.approve_title"), ("I like title 3", "cmo.approve_title")])
def test_writing_and_choosing_titles_keep_their_routes(text, key):
    d = decide(text)
    assert d is not None and d.key == key, (text, d)


def test_the_compare_session_asks_nothing_when_there_is_one_set(monkeypatch):
    monkeypatch.setattr(ins, "_title_sets", lambda ctx: [{"generationId": "g", "marketplace": "AMAZON", "options": []}])
    import uuid
    from datetime import date

    out = ins.start("cmo.analyze_titles", ins.Ctx(uuid.uuid4(), date(2026, 10, 30), None))
    assert isinstance(out, ins.Done) and out.inputs == {}


def test_the_comparison_lines_state_hard_failures_first_and_show_no_number_score():
    class Fake:
        _title_analysis = evidence.EvidenceCollector._title_analysis

        def __init__(self):
            self.artefacts, self.facts, self.gaps = [], [], []

        def add_fact(self, label, text, basis="SOURCE_DERIVED"):
            self.facts.append((label, text, basis))

        def add_gap(self, text):
            self.gaps.append(text)

    t = Fake()
    crit_ok = {"keywordRelevance": {"status": "ASSESSED", "earned": 20, "max": 25, "deductions": [{"points": 5, "reason": "Leaves out “steel bottle”"}]},
               "factAccuracy": {"status": "ASSESSED", "earned": 25, "max": 25, "deductions": []}, "readability": {"status": "ASSESSED", "earned": 20, "max": 20, "deductions": []},
               "buyerIntent": {"status": "NOT_ASSESSED", "earned": None, "max": 15, "deductions": []}, "structure": {"status": "ASSESSED", "earned": 12, "max": 15,
                                                                                                                       "deductions": [{"points": 3, "reason": "Does not meet: brand early"}]}}
    payload = {"options": [
        {"optionId": "a", "rank": 1, "text": "AquaNest Insulated Bottle", "strategy": "Brand-first", "hardFailures": ["Says something you have not confirmed: it claims “insulated”."], "dimensions": {},
         "scores": {"criteria": {}, "overall": {"status": "ASSESSED", "score": 91, "band": "NOT_USABLE", "assessablePoints": 100}}},
        {"optionId": "b", "rank": 2, "text": "AquaNest Steel Bottle 1 Litre", "strategy": "Brand-first", "hardFailures": [], "strengths": ["Reads cleanly"], "weaknesses": [],
         "dimensions": {"marketplaceRules": {"status": "NOT_ASSESSED"}}, "scores": {"criteria": crit_ok, "overall": {"status": "ASSESSED", "score": 82, "band": "STRONG", "assessablePoints": 85}}},
        {"optionId": "c", "rank": 3, "text": "Bottle", "strategy": "Search-coverage", "hardFailures": [], "dimensions": {"marketplaceRules": {"status": "PASS"}},
         "scores": {"criteria": {}, "overall": {"status": "NOT_ASSESSED", "assessablePoints": 35, "note": "Not enough evidence"}}}],
        "recommendation": {"text": "Option 2 has the highest internal quality score (82/100)."}, "notes": ["Not assessed (left out): buyer-intent coverage."], "limits": ["Not an Amazon SEO ranking."],
        "scoring": {"criteria": {"keywordRelevance": 25, "factAccuracy": 25, "readability": 20, "buyerIntent": 15, "structure": 15}, "minimumAssessedPoints": 50}}
    t._title_analysis(payload)
    (title, items, note), (ctitle, compare, _n) = t.artefacts
    assert title == "Title quality scores" and ctitle == "Comparison of all options"
    assert items[0].startswith("Option 1 (Brand-first): AquaNest Insulated Bottle | HARD FAIL, never recommended whatever its score")
    assert "quality score 82/100 (strong) [85 of 100 points assessable]" in items[1]
    assert "keywords 20/25" in items[1] and "confirmed facts 25/25" in items[1] and "readability 20/20" in items[1] and "buyer intent not assessed" in items[1] and "structure 12/15" in items[1]
    assert "marketplace compliance (separate): NOT_ASSESSED" in items[1] and "points lost: keywords -5" in items[1] and "structure -3" in items[1]
    assert "no overall score" in items[2] and "marketplace compliance (separate): PASS" in items[2]
    assert list(compare) == ["Option 1: 91/100 (not usable), 100 of 100 points assessable - HARD FAIL", "Option 2: 82/100 (strong), 85 of 100 points assessable", "Option 3: no overall score (35 of 100 points assessable)"]
    assert ("Recommendation", "Option 2 has the highest internal quality score (82/100).", "SOURCE_DERIVED") in t.facts
    assert any(label == "How the score works" and "keywords 25" in text and "at least 50" in text.lower() for label, text, _b in t.facts)
    assert "Not a marketplace ranking" in note
