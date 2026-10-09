"""B2 follow-up: the template fallbacks seen in the live run were (1) the model summarising gaps instead of writing their markers
(MISSING_REQUIRED), (2) the model copying an ISO date it was shown (NUMERAL_DIGIT_DATE), and (3) routing to a single action instead of a playbook or a
saved-result read. The fixes change what the model is SHOWN and TOLD. They must not change what the gate ACCEPTS: every old failure mode still
falls back."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from backend.ceo import classifier
from backend.ceo.composer import EvidenceTable, PROMPT_VERSION, as_of_footer, build_prompt, compose
from backend.ceo.contract import Figure, Ref, RefKind, Register
from backend.llm.model import Completion, STATIC_END


def fig(label="Fee ratio (2026-09-01/2026-09-30)", as_of=datetime(2026, 10, 1, tzinfo=timezone.utc)) -> Figure:
    return Figure(label, "27.0%", Register.DERIVED, Ref(RefKind.ENGINE_RESULT, uuid4()), as_of=as_of)


def model(text: str):
    class M:
        name = "scripted"

        def complete(self, prompt, *, schema=None, max_output_tokens=None):
            return Completion(text, 5, output_tokens=20)

    return M()


GAPS = (("G1", "The anomaly check is not configured yet."), ("G2", "No leak findings are recorded."))
T = EvidenceTable(figures=(("F1", fig()),), gaps=GAPS)


def dynamic(prompt: str) -> str:
    return prompt.split(STATIC_END, 1)[1]


# ------------------------------------------------------------------------------------------ what the model is shown
def test_the_model_is_shown_no_date_of_any_kind():
    body = dynamic(build_prompt("Why did profit drop?", "PLAYBOOK", T))
    assert "2026" not in body and "as of" not in body  # a date the model sees is a date it copies into its prose
    assert "Fee ratio (for the chosen period)" in body  # the label keeps its meaning without the dates
    assert "{{F1}}" in body and "{{G1}}" in body and "{{G2}}" in body


def test_the_rules_demand_every_gap_marker_and_forbid_typing_a_date():
    p = build_prompt("q", "PLAYBOOK", T)
    assert PROMPT_VERSION == "ceo-composer-3"
    assert "Write EVERY marker listed under GAPS" in p and "Never write a date" in p


# ------------------------------------------------------------------------------------------ the as-of date is still shown, by code
def test_the_answer_carries_the_as_of_date_written_by_code():
    out = compose(model("Here is where you stand. Your fee ratio is {{F1}}. {{G1}} {{G2}}"), "q", "ACTION", T)
    assert out.mode == "LLM"
    assert out.text.endswith("Figures as of 2026-10-01.") and "27.0%" in out.text


def test_footer_lists_each_distinct_date_and_is_empty_without_one():
    t2 = EvidenceTable(figures=(("F1", fig()), ("F2", fig(as_of=datetime(2026, 9, 30, tzinfo=timezone.utc)))))
    assert as_of_footer(t2) == "Figures as of 2026-09-30 and 2026-10-01."
    assert as_of_footer(EvidenceTable(figures=(("F1", fig(as_of=None)),))) == ""


# ------------------------------------------------------------------------------------------ the gate is NOT weaker
def test_summarising_gaps_in_prose_still_falls_back():
    out = compose(model("Your fee ratio is {{F1}}. The anomaly checks and leak findings are not configured, so look further."), "q", "ACTION", T)
    assert out.mode == "TEMPLATE_FALLBACK" and "MISSING_REQUIRED" in out.safety["violations"]


def test_a_typed_date_still_falls_back():
    out = compose(model("Your fee ratio for the period ended 2026-09-30 was {{F1}}. {{G1}} {{G2}}"), "q", "ACTION", T)
    assert out.mode == "TEMPLATE_FALLBACK" and "NUMERAL_DIGIT_DATE" in out.safety["violations"]


def test_a_typed_figure_or_unknown_marker_still_falls_back():
    assert compose(model("Your fee ratio is 27%. {{G1}} {{G2}}"), "q", "ACTION", T).mode == "TEMPLATE_FALLBACK"
    assert compose(model("Your fee ratio is {{F9}}. {{G1}} {{G2}}"), "q", "ACTION", T).mode == "TEMPLATE_FALLBACK"


def test_a_complete_grounded_draft_passes_without_the_footer_being_checked_as_model_prose():
    out = compose(model("Here is where you stand. Fees are {{F1}}. {{G1}} {{G2}}"), "q", "ACTION", T)
    assert out.mode == "LLM" and out.safety["gate"] == "PASS"  # the code-written footer contains digits but is appended after the gate


# ------------------------------------------------------------------------------------------ routing guidance
def test_the_classifier_is_told_to_prefer_a_playbook_and_a_saved_read_over_a_single_action():
    assert classifier.PROMPT_VERSION == "ceo-classifier-2"
    help_text = " ".join(classifier._ROUTE_HELP.split())
    assert "Prefer it for overview questions" in help_text and 'a "why" question is never a single ACTION' in help_text
    assert "Prefer it over a single ACTION whenever the question matches a playbook description" in help_text
