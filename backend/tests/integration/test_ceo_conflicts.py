"""C4: conflict handling (spec §6.32, AC46). Two stored values for one quantity that disagree are detected by CODE from persisted rows, both are shown with
their source and date, and NEITHER is chosen, averaged or listed as a plain figure — including when a later turn summarises the finding.
"""

from __future__ import annotations

import pytest

from backend.ceo import orchestrator
from backend.repositories import investigation_repo as repo
from tests.integration.ceo_support import ctx_for, later, save_metric
from tests.integration.test_ceo_turn import Grounded, Scripted, decision, runtime, start

pytestmark = pytest.mark.usefixtures("two_tenants")

SEP = "2026-09-01/2026-09-30"
STATE_Q = "How did last month go?"
STATE = decision(route="BUSINESS_STATE", route_key="BS_PNL_LATEST")


def _seed_conflict(tenant, *, other_value=250_000):
    first = save_metric(tenant, "NET_REALIZED_REVENUE", period=SEP, value_paise=100_000)
    second = save_metric(tenant, "NET_REALIZED_REVENUE", period=SEP, value_paise=other_value, computed_at=later(1))
    return first, second


def test_two_results_from_the_same_inputs_that_differ_are_shown_as_a_conflict_and_neither_is_chosen(two_tenants, app_user):
    a, _ = two_tenants
    first, second = _seed_conflict(a)
    ctx = ctx_for(a, user_id=app_user)
    rt = runtime(Scripted({STATE_Q: STATE}))
    inv = start(ctx, rt)
    res = orchestrator.run_turn(ctx, rt, inv, STATE_Q)

    assert "₹1,000.00" in res.answer and "₹2,500.00" in res.answer  # both stored values, formatted from the rows
    assert res.answer.count("₹1,000.00") == 1 and res.answer.count("₹2,500.00") == 1  # each once: not also listed as a plain figure
    assert "neither has been chosen, averaged or combined" in res.answer
    assert "₹1,750.00" not in res.answer  # no average ever appears
    [f] = repo.list_findings(a, inv, turn_id=res.turn_id)
    snap = f["presentation"]
    assert [c["kind"] for c in snap["conflicts"]] == ["C1_METRIC"] and set(snap["conflicts"][0]["refIds"]) == {str(first), str(second)}
    assert all("Net realized revenue" not in x["label"] for x in snap["figures"])  # the conflicting metric is not also a plain figure
    assert {r["id"] for r in f["figure_refs"]} >= {str(first), str(second)}  # both sides stay cited


def test_a_later_recomputation_of_the_same_value_is_not_a_conflict(two_tenants, app_user):
    a, _ = two_tenants
    _seed_conflict(a, other_value=100_000)
    ctx = ctx_for(a, user_id=app_user)
    rt = runtime(Scripted({STATE_Q: STATE}))
    inv = start(ctx, rt)
    res = orchestrator.run_turn(ctx, rt, inv, STATE_Q)
    assert "neither has been chosen" not in res.answer and res.answer.count("₹1,000.00") == 1


def test_a_conflict_is_never_reported_across_tenants(two_tenants, app_user):
    a, b = two_tenants
    _seed_conflict(b)  # only the other tenant has a disagreement
    save_metric(a, "NET_REALIZED_REVENUE", period=SEP, value_paise=777_700)
    ctx = ctx_for(a, user_id=app_user)
    rt = runtime(Scripted({STATE_Q: STATE}))
    inv = start(ctx, rt)
    res = orchestrator.run_turn(ctx, rt, inv, STATE_Q)
    assert "₹7,777.00" in res.answer and "neither has been chosen" not in res.answer and "₹2,500.00" not in res.answer


def test_summarising_a_conflict_finding_names_the_disagreement_instead_of_listing_two_plain_figures(two_tenants, app_user):
    a, _ = two_tenants
    _seed_conflict(a)
    ctx = ctx_for(a, user_id=app_user)
    comp = Grounded()
    cls = Scripted({STATE_Q: STATE, "Summarise everything.": decision(route="SYNTHESIZE")})
    rt = runtime(cls, comp)
    inv = start(ctx, rt)
    orchestrator.run_turn(ctx, rt, inv, STATE_Q)
    res = orchestrator.run_turn(ctx, rt, inv, "Summarise everything.")
    assert "two different stored values that disagree" in res.answer and "neither was chosen" in res.answer
    assert "₹1,000.00" not in res.answer and "₹2,500.00" not in res.answer
