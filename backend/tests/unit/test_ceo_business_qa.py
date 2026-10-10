"""CEO business Q&A, no database (spec agent-needs-and-shared-knowledge.md section 7, 8.3, 12 AC-Q1..Q7):

* the question-type catalog is closed, complete (nine types plus the explicit "not stored" type), and every sentence in it is written by code;
* the rules router and the classifier's closed catalog reach each type (and an unknown type is a clarification, never a read);
* the answer evals (deterministic scorer, scripted model) hold: no ungrounded number, no non-result narrated as a result, required wording kept, and the scorer
  itself catches deliberately bad answers (negative controls);
* no SQL generation, no embedding or free-text search exists in the Q&A modules (AC-Q5).
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

from backend.ceo import business_state, capabilities, classifier, intent_router, question_types
from backend.ceo.plans import ACTIONS
from backend.ceo_eval import business_qa, fixtures

QT = question_types.QUESTION_TYPES
NINE = (
    "QT_PROFIT_BY_PERIOD", "QT_LEAKS", "QT_DATA_GAPS", "QT_COMPETITORS_PRICES", "QT_PRODUCT_IDEAS", "QT_LISTING_CONTENT", "QT_GOALS", "QT_AGENT_FINDINGS", "QT_SELLER_FACTS",
)
SRC = Path(__file__).resolve().parents[2] / "src" / "backend"


def _catalog() -> classifier.Catalog:
    return classifier.build_catalog([], [], question_types.descriptions())


# ------------------------------------------------------------------------------------------------ the catalog
def test_the_catalog_has_the_nine_spec_types_plus_the_explicit_not_stored_type():
    assert set(QT) == {*NINE, "QT_NOT_STORED"}


def test_every_type_reads_only_known_entries_and_the_only_unbuilt_one_is_the_shared_findings_extension_point():
    named = {u.key for qt in QT.values() for u in qt.entries}
    unbuilt = named - set(business_state.ENTRIES)
    assert unbuilt <= {"BS_SHARED_FINDINGS"}  # built by the findings slice; until then its type answers "not stored yet" (extension point, no stub entry)
    assert {"BS_PNL_RECENT", "BS_SELLER_FACTS", "BS_CMO_CONTENT_LATEST"} <= set(business_state.ENTRIES)


def test_the_type_to_entries_mapping_is_the_spec_table():
    expect = {
        "QT_PROFIT_BY_PERIOD": ("BS_PNL_RECENT", "BS_HEALTH_BANDS"), "QT_LEAKS": ("BS_LEAK_OPEN", "BS_DATA_GAPS"), "QT_DATA_GAPS": ("BS_DATA_GAPS", "BS_INGEST_STATUS"),
        "QT_COMPETITORS_PRICES": ("BS_COMPETITOR_SNAPSHOT",), "QT_PRODUCT_IDEAS": ("BS_PI_REPORT_LATEST",), "QT_LISTING_CONTENT": ("BS_CMO_WORKFLOW", "BS_CMO_CONTENT_LATEST"),
        "QT_GOALS": ("BS_SELLER_CONTEXT", "BS_SELLER_FACTS"), "QT_AGENT_FINDINGS": ("BS_SHARED_FINDINGS",), "QT_SELLER_FACTS": ("BS_SELLER_FACTS",), "QT_NOT_STORED": (),
    }
    assert {k: tuple(u.key for u in qt.entries) for k, qt in QT.items()} == expect


def test_every_sentence_is_code_written_begins_not_stored_and_states_no_number():
    for qt in QT.values():
        sentences = [qt.not_stored, *qt.always_gaps, *(u.not_stored for u in qt.entries if u.not_stored)]
        for s in sentences:
            assert s.startswith(question_types.NOT_STORED_PREFIX), (qt.id, s)
            assert not re.search(r"\d", s), (qt.id, s)  # a status sentence never carries a number
    for text in (question_types.NOT_PERMITTED_TEXT, question_types.NOT_ENTITLED_TEXT, question_types.NOT_ATTACHED_TEXT):
        assert not re.search(r"\d", text)


def test_offered_actions_are_registered_closed_catalog_keys():
    from backend.ceo.registry import get_registry

    registered = {s.key for s in get_registry().specs()}
    offered = {o[0] for qt in QT.values() for o in (qt.offer, qt.available_offer) if o is not None}
    assert offered <= registered  # never a free string
    # Spec 7.2 names cfo.pnl_for_tenant for the profit chip. It is registered but is not (yet) a chat ACTION in plans.ACTIONS, so the chip is shown as an offer and a
    # seller-click would be refused as out of catalog until plans.py (owned by the orchestration slice) adds it. Pinned so the gap cannot become silent.
    assert offered - set(ACTIONS) == {"cfo.pnl_for_tenant"}


def test_the_question_types_are_in_the_classifier_catalog_for_a_member_who_may_talk_to_the_ceo_only():
    desc = question_types.descriptions()
    assert set(desc) == set(QT) and all(d.strip() for d in desc.values())
    src = (SRC / "ceo" / "capabilities.py").read_text(encoding="utf-8")
    assert "question_types.descriptions()" in src and src.index("permitted(AGENT_CEO)") < src.index("question_types.descriptions()")


# ------------------------------------------------------------------------------------------------ routing
ROUTES = {
    "What was my profit in September?": "QT_PROFIT_BY_PERIOD",
    "how much revenue did we make last month": "QT_PROFIT_BY_PERIOD",
    "Where am I losing money?": "QT_LEAKS",
    "What data are you missing?": "QT_DATA_GAPS",
    "What are my competitors charging?": "QT_COMPETITORS_PRICES",
    "What product ideas did you find?": "QT_PRODUCT_IDEAS",
    "What titles did we write?": "QT_LISTING_CONTENT",
    "What is my goal?": "QT_GOALS",
    "What has each agent found?": "QT_AGENT_FINDINGS",
    "What do you know about my business?": "QT_SELLER_FACTS",
    "How much stock do I have?": "QT_NOT_STORED",
    "what is my ad spend": "QT_NOT_STORED",
}


@pytest.mark.parametrize("question,expected", list(ROUTES.items()))
def test_each_question_routes_to_its_type_by_rule_without_a_model(question, expected):
    d = intent_router.route(question, _catalog())
    assert d is not None and (d.route, d.key, dict(d.slots)) == ("BUSINESS_STATE", expected, {}) and "RULE_ROUTED" in d.flags


@pytest.mark.parametrize(
    "question",
    ["Why did my profit drop last month?", "find me trending products for mens shoes", "write titles for my steel bottle on amazon", "give me hashtags for my bottle",
     "what margin do I make if the competitor price is 499", "what is the GST rate on a steel bottle"],
)
def test_requests_to_do_work_and_why_questions_are_not_taken_by_the_state_rules(question):
    d = intent_router.route(question, _catalog())
    assert d is None or d.route != "BUSINESS_STATE" or d.key not in QT


def test_a_rule_for_a_type_the_member_cannot_be_offered_explains_instead_of_reading():
    d = intent_router.route("Where am I losing money?", classifier.build_catalog([], [], {}))  # no CEO permission: no type in the catalog
    assert d is not None and d.route == "ADVISORY" and d.needs_agent == "CFO"


def test_a_classifier_choosing_a_type_outside_the_closed_enum_is_a_clarification():
    cat = _catalog()
    ok = classifier.parse_decision(json.dumps({"route": "BUSINESS_STATE", "route_key": "QT_LEAKS", "slots": {}, "needs_agent": None, "clarify_for": None}), cat)
    bad = classifier.parse_decision(json.dumps({"route": "BUSINESS_STATE", "route_key": "QT_EVERYTHING", "slots": {}, "needs_agent": None, "clarify_for": None}), cat)
    sql = classifier.parse_decision(json.dumps({"route": "BUSINESS_STATE", "route_key": "SELECT * FROM metric_result", "slots": {}, "needs_agent": None, "clarify_for": None}), cat)
    assert (ok.route, ok.key) == ("BUSINESS_STATE", "QT_LEAKS")
    for d in (bad, sql):
        assert d.route == "CLARIFY" and d.key is None and "OUT_OF_CATALOG" in d.flags
    assert set(question_types.descriptions()) <= set(classifier.output_schema(cat)["properties"]["route_key"]["enum"])


def test_the_new_state_entries_have_a_description_for_the_classifier_and_a_cache_source():
    for key in ("BS_PNL_RECENT", "BS_SELLER_FACTS", "BS_CMO_CONTENT_LATEST"):
        assert capabilities.STATE_DESCRIPTIONS[key].strip()
        assert business_state.ENTRIES[key].source_tables


# ------------------------------------------------------------------------------------------------ evals
CASES = fixtures.load_business_qa_cases()
BY_ID = {c.id: c for c in CASES}


def test_the_fixture_set_covers_every_eval_category_and_each_type_that_can_be_empty():
    assert len({c.id for c in CASES}) == len(CASES)
    assert {c.category for c in CASES} >= {"GROUNDED_NUMBER", "NON_RESULT", "WORDING", "INJECTION"}
    assert all(c.qt in QT for c in CASES)
    assert {c.qt for c in CASES if c.status == "UNAVAILABLE"} >= {"QT_PROFIT_BY_PERIOD", "QT_LEAKS", "QT_COMPETITORS_PRICES", "QT_PRODUCT_IDEAS", "QT_LISTING_CONTENT",
                                                                    "QT_AGENT_FINDINGS", "QT_SELLER_FACTS", "QT_NOT_STORED"}
    assert {c.status for c in CASES} >= {"UNAVAILABLE", "NOT_ATTACHED", "NOT_ENTITLED", "NOT_PERMITTED", "AVAILABLE", "PARTIAL"}


def test_fixture_not_stored_sentences_are_the_ones_the_code_writes():
    written = {s for qt in QT.values() for s in (qt.not_stored, *qt.always_gaps, *(u.not_stored for u in qt.entries if u.not_stored))}
    for c in CASES:
        for gap in c.entry.get("gaps", []):
            if gap.startswith(question_types.NOT_STORED_PREFIX):
                assert gap in written, (c.id, gap)


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_eval_case_is_clean_or_its_negative_control_is_caught(case):
    result = business_qa.run_case(case)
    assert result.ok, (case.id, result.mode, result.violations, result.text)


def test_hostile_scripted_drafts_never_reach_the_seller():
    """A scripted model that invents a rupee amount, a percentage, a magnitude word or good news is rejected by the production gate (-> the fixed template), and
    the text the seller reads scores clean."""
    for case_id in ("QA-G03", "QA-G04", "QA-G05", "QA-G10", "QA-N12", "QA-N13"):
        result = business_qa.run_case(BY_ID[case_id])
        assert result.mode == "TEMPLATE_FALLBACK" and not result.violations, (case_id, result.mode, result.violations)


def test_an_honest_scripted_draft_is_accepted_and_its_figure_is_the_stored_string():
    result = business_qa.run_case(BY_ID["QA-G02"])
    assert result.mode == "LLM" and "₹1,42,300.00" in result.text and not result.violations


def test_the_scorer_flags_each_failure_it_exists_to_catch():
    c = BY_ID["QA-G01"]
    assert "UNGROUNDED_NUMBER" in business_qa.score_text(c, "Contribution profit: ₹1,42,300.00, up 12% on August.")
    assert "UNGROUNDED_NUMBER" in business_qa.score_text(c, "Contribution profit: ₹1,42,301.00.")  # one digit off is a different number
    assert "NUMBER_WORD" in business_qa.score_text(c, "Contribution profit: ₹1,42,300.00, about two lakh.")
    n = BY_ID["QA-N02"]
    assert "NON_RESULT_AS_RESULT" in business_qa.score_text(n, "Not stored yet. Good news: no leaks, all good.")
    assert "NON_RESULT_SENTENCE_MISSING" in business_qa.score_text(n, "Please upload your reports.")
    assert business_qa.score_text(BY_ID["QA-W01"], "Written by Slim CMO: titles. Quoted as written; not verified by Metrion. Steel Bottle 1 L Insulated") == []


def test_the_summary_reports_counts_only_and_the_negative_controls_all_fire():
    results = business_qa.run_cases(CASES)
    summary = business_qa.summarize(results, BY_ID)
    assert summary["clean"]["n"] == summary["clean"]["of"] == summary["cases"]
    assert summary["ungrounded_number"]["n"] == 0 and summary["non_result_narrated_as_result"]["n"] == 0
    assert summary["scorer_negative_controls"]["n"] == summary["scorer_negative_controls"]["of"] > 0


# ------------------------------------------------------------------------------------------------ AC-Q5: no SQL generation, no semantic search
QA_MODULES = ("question_types.py", "business_state.py", "intent_router.py", "capabilities.py")


@pytest.mark.parametrize("name", QA_MODULES)
def test_no_sql_embedding_or_free_text_search_in_the_qa_path(name):
    tree = ast.parse((SRC / "ceo" / name).read_text(encoding="utf-8"))
    imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names} | {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert not [m for m in imported if m.split(".")[0] in {"sqlalchemy", "psycopg", "numpy", "pgvector", "sentence_transformers", "faiss"}]
    source = (SRC / "ceo" / name).read_text(encoding="utf-8").lower()
    for forbidden in ("select ", "ilike", "tsvector", "embedding", "cosine", "pgvector"):
        assert forbidden not in source.replace("select one", "").replace("select the", ""), (name, forbidden)
