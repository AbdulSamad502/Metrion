"""Hardening Fix 1: a message that asks for more than one thing must never silently lose a part of it.

Current contract (unchanged): ONE route per turn. So the CEO handles at most one requirement per message and says, in a code-written block, exactly what it handled
and what it did not (and why). Evidence category: real-dispatcher integration + persistence, fake classifier (never consulted here: the explicit rules decide), spy
handlers that record what actually ran. Nothing financial is evaluated."""

from __future__ import annotations

from dataclasses import replace

import pytest

from backend.ceo import orchestrator
from backend.ceo.registry import ActionRegistry
from backend.repositories import investigation_repo as repo
from tests.integration.ceo_support import ctx_for
from tests.integration.test_ceo_campaign_routing_e2e import build
from tests.integration.test_ceo_campaign_safety import spied
from tests.integration.test_ceo_turn import start

pytestmark = pytest.mark.usefixtures("two_tenants")

HEADER = "Your message asked for more than one thing"
GST = "What GST rate applies to steel water bottles"
LEAKS = "where am I losing money"


def run(text, two_tenants, app_user, *, failing=()):
    a, _ = two_tenants
    ctx = ctx_for(a, user_id=app_user)
    rt, called, _ = build(None)
    if failing:
        def boom(slots, c, leg):
            raise RuntimeError("handler failed")

        rt = replace(rt, registry=ActionRegistry([replace(s, invoke=boom) if s.key in failing else s for s in rt.registry.specs()]))
    inv = start(ctx, rt)
    res = orchestrator.run_turn(ctx, rt, inv, text)
    return a, inv, res, called


def not_handled(answer: str) -> list[str]:
    return [line for line in answer.splitlines() if line.startswith("• Not handled")]


def test_two_independent_supported_requests_run_one_and_name_the_other_as_not_started(two_tenants, app_user):
    a, inv, res, called = run(f"{GST} and also {LEAKS}?", two_tenants, app_user)
    assert called == ["cfo.gst_lookup"]  # exactly one action, once
    assert HEADER in res.answer and "• Handled: “" + GST in res.answer
    [line] = not_handled(res.answer)
    assert LEAKS in line and "not started" in line and "own message" in line
    assert "completed" not in res.answer.lower().replace("could not be completed", "")  # the whole request is not reported as done
    turn = repo.get_turn(a, res.turn_id)
    assert turn["route_key"] == "gst_lookup" and turn["classifier_result"]["compound"]["handled"].startswith(GST)
    assert [m["role"] for m in repo.list_messages(a, inv)] == ["USER", "CEO"]


def test_a_supported_request_with_an_approval_gated_one_runs_the_supported_part_and_says_the_other_needs_approval(two_tenants, app_user):
    _, _, res, called = run(f"Write hashtags for my steel water bottle and also {GST}?", two_tenants, app_user)
    assert called == ["cfo.gst_lookup"]  # the gated action was NOT run, the supported one was, even though it came second
    [line] = not_handled(res.answer)
    assert "hashtags" in line and "approved plan" in line and "Nothing was run for it" in line


def test_a_supported_request_with_an_unsupported_one_names_the_unsupported_part(two_tenants, app_user):
    _, _, res, called = run("Where am I losing money and also upload my sales file", two_tenants, app_user)
    assert called == []  # a saved-results read needs no handler
    [line] = not_handled(res.answer)
    assert "upload my sales file" in line and "could not match" in line
    assert "• Handled: “Where am I losing money" in res.answer


def test_a_dependent_second_step_is_not_started_without_the_first_result(two_tenants, app_user):
    _, _, res, called = run(f"{GST} and then show what competitors charge for it", two_tenants, app_user)
    assert called == ["cfo.gst_lookup"]
    [line] = not_handled(res.answer)
    assert "competitors charge for it" in line and "depends on the result" in line


def test_a_dependent_pair_where_nothing_can_run_says_so_for_both_and_runs_nothing(two_tenants, app_user):
    _, _, res, called = run("Find trending products in kitchenware and then write titles for the top one", two_tenants, app_user)
    assert called == [] and res.status == "DENIED"
    lines = not_handled(res.answer)
    assert len(lines) == 2 and all("approved plan" in l for l in lines)
    assert "• Handled: nothing" in res.answer


def test_when_the_handled_request_fails_the_answer_says_so_and_still_lists_the_rest(two_tenants, app_user):
    _, _, res, called = run(f"{GST} and also {LEAKS}?", two_tenants, app_user, failing=("cfo.gst_lookup",))
    assert "could not be completed" in res.answer or "could not complete" in res.answer
    assert not_handled(res.answer) and LEAKS in not_handled(res.answer)[0]
    assert res.status in ("FAILED", "DELIVERED") and "• Handled" in res.answer


def test_when_the_second_request_is_the_one_that_runs_and_fails_the_gated_first_is_still_reported(two_tenants, app_user):
    _, _, res, called = run(f"Write hashtags for my steel water bottle and also {GST}?", two_tenants, app_user, failing=("cfo.gst_lookup",))
    assert "could not be completed" in res.answer or "could not complete" in res.answer
    [line] = not_handled(res.answer)
    assert "hashtags" in line and "approved plan" in line


def test_every_requirement_appears_exactly_once_and_nothing_runs_twice(two_tenants, app_user):
    text = f"{GST} and also {LEAKS} and also write hashtags for my bottle"
    _, _, res, called = run(text, two_tenants, app_user)
    assert called == ["cfo.gst_lookup"]
    handled = [l for l in res.answer.splitlines() if l.startswith("• Handled")]
    assert len(handled) == 1 and len(not_handled(res.answer)) == 2
    for part in (GST, LEAKS, "write hashtags for my bottle"):
        assert sum(part in l for l in res.answer.splitlines() if l.startswith("• ")) == 1


@pytest.mark.parametrize(
    "text",
    [
        "Write a title and description for my steel bottle",  # one request with two nouns
        "Where am I losing money?",
        "What are my competitors charging for steel bottles?",
        "Show me profit and loss",
    ],
)
def test_a_single_request_is_unchanged_and_carries_no_compound_block(text, two_tenants, app_user):
    a, _, res, _ = run(text, two_tenants, app_user)
    assert HEADER not in res.answer
    assert "compound" not in (repo.get_turn(a, res.turn_id)["classifier_result"] or {})
