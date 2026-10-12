"""Hardening Fix 1 (unit): when a message is a compound request, and (just as important) when it is not."""

from __future__ import annotations

import pytest

from backend.ceo import classifier, compound, question_types
from backend.ceo.approval_gate import evaluate_playbook, plan_required
from backend.ceo.plans import ACTIONS, PLAYBOOKS

CAT = classifier.build_catalog(list(ACTIONS), list(PLAYBOOKS), {**question_types.descriptions()})


def gated(d):
    if d.route == "ACTION" and d.key in ACTIONS:
        return plan_required([d.key])
    return d.route == "PLAYBOOK" and d.key in PLAYBOOKS and evaluate_playbook(PLAYBOOKS[d.key]).plan_required


@pytest.mark.parametrize(
    "text",
    [
        "Write a title and description for my steel bottle",  # two nouns, one request
        "Find trending products that are cheap and are popular",  # 'and' not followed by a request verb
        "I also sell shoes",  # a statement, no second request
        "Where am I losing money?",
        "What GST rate applies to steel bottles",
        "My niche is shoes and my business name is Zyquora",
        "",
    ],
)
def test_not_a_compound_request(text):
    assert compound.analyse(text, CAT, needs_approval=gated) is None


def test_the_connectors_that_start_a_new_request():
    parts = [c for _, c in compound.split_clauses("What GST rate applies to steel bottles; also where am I losing money, then write hashtags for it")]
    assert parts == ["What GST rate applies to steel bottles", "where am I losing money", "write hashtags for it"]


def test_the_first_runnable_independent_requirement_is_chosen_even_when_a_gated_one_comes_first():
    plan = compound.analyse("Write hashtags for my bottle and also what GST rate applies to steel bottles", CAT, needs_approval=gated)
    assert plan is not None and plan.chosen_text == "what GST rate applies to steel bottles"
    assert plan.not_handled == (("Write hashtags for my bottle", "APPROVAL"),)


def test_a_dependent_clause_is_never_chosen_ahead_of_its_predecessor():
    plan = compound.analyse("Find trending products in kitchenware and then show what competitors charge for it", CAT, needs_approval=gated)
    assert plan is not None and plan.chosen_text is None
    assert [r for _, r in plan.not_handled] == ["APPROVAL", "DEPENDENT"]


def test_long_requests_are_quoted_short():
    long = "write hashtags for " + "very " * 60 + "long bottle"
    plan = compound.analyse(f"{long} and also what GST rate applies to steel bottles", CAT, needs_approval=gated)
    assert plan is not None and all(len(t) <= compound.MAX_QUOTE for t, _ in plan.not_handled)


@pytest.mark.parametrize(
    "text",
    [
        "Find competitors and summarize their product reviews",  # neither half is a request the explicit rules recognise
        "Compare my price with a rival and then tell me what to do",
    ],
)
def test_a_compound_message_no_rule_recognises_is_left_to_the_model_and_no_block_is_claimed(text):
    """DOCUMENTED LIMITATION: compound detection is rule-based. When no clause is recognised by a rule the model decides the route as it always did, and this module says nothing
    (a 'Handled: nothing' block could contradict what the model then runs)."""
    assert compound.analyse(text, CAT, needs_approval=gated) is None
