"""`POST /api/v1/cfo/pnl-scenario` — the hypothetical P&L boundary (docs/specs/calculator.md §14, N-AC3/N-AC4/N-AC5/N-AC6).

True unit tests, no Postgres: the route is called as a plain function (the dependency-injected `AuthContext` is constructed directly) with the
`agent_run` repository and the entitlement gate replaced by spies. What these prove: the request cannot carry a tenant or a float, a missing input
stays missing, a scenario writes exactly one audit row and nothing else, and the answer is labelled an unverified estimate with an `estimateRef`
and no `engineResultRef`.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from backend.api.v1 import cfo as cfo_routes
from backend.auth.context import AuthContext
from backend.services.pnl_scenario import PnlScenarioHttpRequest


def _ctx() -> AuthContext:
    return AuthContext(
        app_user_id=uuid.uuid4(), clerk_user_id="user_test", email_verified=True, tenant_id=uuid.uuid4(), membership_status="ACTIVE",
        role="OWNER", permissions={}, onboarding_state="COMPLETE",
    )


def _set(v: str) -> dict:
    return {"state": "set", "value": v}


def _fee(amount: str) -> dict:
    return {"amount": {"state": "set", "value": {"kind": "single", "amount": amount}}}


def _a1() -> dict:
    """The reference calculator's hand-checked fixture A1 (Amazon, registered with ITC): contribution Rs 492.00 per kept order."""
    return {
        "marketplace": "amazon", "mode": "detailed", "selling_price": _set("118000"), "gst_rate_bps": _set("1800"), "product_cost": _set("35400"),
        "packaging_cost": _set("2360"), "fees": {"referral": _fee("1000"), "closing": _fee("2000"), "shipping": _fee("5000")},
        "monthly_orders": _set("100"), "rto_bps": _set("0"), "return_bps": _set("0"), "ad_spend": {"state": "na"},
    }


class _Runs:
    def __init__(self) -> None:
        self.inserted: list[dict] = []
        self.finished: list[dict] = []

    def insert_run(self, tenant_id, **kw):  # noqa: ANN001
        run_id = uuid.uuid4()
        self.inserted.append({"tenant_id": tenant_id, "run_id": run_id, **kw})
        return run_id

    def finish_run(self, tenant_id, run_id, **kw):  # noqa: ANN001
        self.finished.append({"tenant_id": tenant_id, "run_id": run_id, **kw})


@pytest.fixture
def runs(monkeypatch: pytest.MonkeyPatch) -> _Runs:
    spy = _Runs()
    monkeypatch.setattr(cfo_routes, "agent_run_repo", spy)
    monkeypatch.setattr(cfo_routes, "_require_cfo_entitlement", lambda *a, **k: None)
    return spy


def test_a1_matches_the_reference_to_the_paisa_and_is_labelled_an_unverified_estimate(runs: _Runs) -> None:
    ctx = _ctx()
    out = cfo_routes.post_pnl_scenario(PnlScenarioHttpRequest.model_validate(_a1()), ctx)
    assert out["perKept"]["contribution"] == "49200" and out["perKept"]["revenue"] == "100000"
    assert out["metrics"]["contributionMarginBps"] == "4920" and out["metrics"]["gstRecoveredPerKept"] == "9144"
    assert out["monthly"]["contribution"] == "4920000"
    assert out["status"] == "estimate" and out["missingCosts"] == []
    assert (out["kind"], out["verification"], out["persisted"]) == ("hypothetical_estimate", "unverified_estimate", False)
    assert "engineResultRef" not in str(out) and "engine_result_ref" not in str(out)
    assert out["estimateRef"] == f"pnl-scenario:{runs.inserted[0]['run_id']}"


def test_exactly_one_direct_agent_run_is_written_and_it_belongs_to_the_session_tenant(runs: _Runs) -> None:
    ctx = _ctx()
    cfo_routes.post_pnl_scenario(PnlScenarioHttpRequest.model_validate(_a1()), ctx)
    assert len(runs.inserted) == 1 and len(runs.finished) == 1
    row = runs.inserted[0]
    assert (row["agent_id"], row["trigger_type"], row["trigger_ref"], row["permission_check"], row["entitlement_check"]) == ("CFO", "DIRECT", "cfo.pnl_scenario", "PASS", "PASS")
    assert row["tenant_id"] == ctx.tenant_id and row["requested_by"] == ctx.app_user_id
    assert runs.finished[0]["status"] == "COMPLETE" and runs.finished[0]["tenant_id"] == ctx.tenant_id


def test_the_route_touches_no_other_persistence(runs: _Runs, monkeypatch: pytest.MonkeyPatch) -> None:
    """N-AC3: no metric_result and no data request. Both writers are replaced with tripwires; the scenario must not call either."""
    from backend.services import cfo_actions

    def boom(*a, **k):  # noqa: ANN002, ANN003
        raise AssertionError("a hypothetical scenario must not write a metric_result or a data request")

    monkeypatch.setattr(cfo_actions.metric_result_repo, "save", boom)
    monkeypatch.setattr(cfo_actions, "insert_data_request", boom)
    body = _a1() | {"targets": [{"kind": "breakeven"}, {"kind": "margin", "bps": "2000"}]}
    out = cfo_routes.post_pnl_scenario(PnlScenarioHttpRequest.model_validate(body), _ctx())
    assert [s["outcome"] for s in out["solutions"]] == ["price", "price"]


def test_denied_entitlement_is_a_402_with_no_run_and_no_computation(monkeypatch: pytest.MonkeyPatch) -> None:
    spy = _Runs()
    monkeypatch.setattr(cfo_routes, "agent_run_repo", spy)

    def deny(*a, **k):  # noqa: ANN002, ANN003
        raise HTTPException(status_code=402, detail={"reason": "OVER_CAP"})

    monkeypatch.setattr(cfo_routes, "_require_cfo_entitlement", deny)
    monkeypatch.setattr(cfo_routes, "calculate_scenario", lambda *a, **k: pytest.fail("computed despite a denied entitlement"))
    with pytest.raises(HTTPException) as e:
        cfo_routes.post_pnl_scenario(PnlScenarioHttpRequest.model_validate(_a1()), _ctx())
    assert e.value.status_code == 402 and spy.inserted == []


def test_an_engine_failure_finishes_the_run_as_failed(runs: _Runs, monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(*a, **k):  # noqa: ANN002, ANN003
        raise RuntimeError("x")

    monkeypatch.setattr(cfo_routes, "calculate_scenario", explode)
    with pytest.raises(RuntimeError):
        cfo_routes.post_pnl_scenario(PnlScenarioHttpRequest.model_validate(_a1()), _ctx())
    assert runs.finished[0]["status"] == "FAILED"


# ---- empty is never zero ----------------------------------------------------------------------------------------------------------

def test_missing_fees_are_named_and_excluded_never_zero(runs: _Runs) -> None:
    body = _a1() | {"fees": {}}
    out = cfo_routes.post_pnl_scenario(PnlScenarioHttpRequest.model_validate(body), _ctx())
    assert out["status"] == "provisional"
    assert {"Referral fee", "Closing fee", "Shipping / weight-handling fee"} <= set(out["missingCosts"])
    assert not any(ln["id"].startswith("fee_") for ln in out["perKept"]["lines"])
    assert runs.finished[0]["status"] == "PARTIAL"


def test_nothing_entered_is_incomplete_with_no_figure(runs: _Runs) -> None:
    out = cfo_routes.post_pnl_scenario(PnlScenarioHttpRequest.model_validate({"marketplace": "flipkart"}), _ctx())
    assert out["status"] == "incomplete" and out["perKept"] is None and out["monthly"] is None and out["metrics"] is None
    assert {"price_missing", "gst_missing", "cost_missing"} <= {i["code"] for i in out["issues"]}


def test_na_is_a_confirmed_zero_but_empty_is_not(runs: _Runs) -> None:
    na = cfo_routes.post_pnl_scenario(PnlScenarioHttpRequest.model_validate(_a1() | {"packaging_cost": {"state": "na"}}), _ctx())
    empty = cfo_routes.post_pnl_scenario(PnlScenarioHttpRequest.model_validate(_a1() | {"packaging_cost": {"state": "empty"}}), _ctx())
    assert na["status"] == "estimate" and empty["status"] == "provisional" and "Packaging cost" in empty["missingCosts"]


# ---- precision ----------------------------------------------------------------------------------------------------------------------

def test_amounts_above_the_js_safe_integer_stay_exact(runs: _Runs) -> None:
    big = "9007199254740993"  # 2**53 + 1
    body = _a1() | {"gst_status": "unregistered", "gst_rate_bps": {"state": "empty"}, "selling_price": _set(big), "product_cost": _set("1")}
    # the per-field cap protects the server; a value above it is refused rather than rounded
    with pytest.raises(ValidationError):
        PnlScenarioHttpRequest.model_validate(body)
    ok = _a1() | {"gst_status": "unregistered", "gst_rate_bps": {"state": "empty"}, "selling_price": _set("9007199254740"), "product_cost": _set("1")}
    out = cfo_routes.post_pnl_scenario(PnlScenarioHttpRequest.model_validate(ok), _ctx())
    assert out["perKept"]["revenue"] == "9007199254740" and isinstance(out["perKept"]["revenue"], str)


def test_fractional_order_counts_are_exact_text(runs: _Runs) -> None:
    body = _a1() | {"monthly_orders": _set("7"), "rto_bps": _set("1500")}
    out = cfo_routes.post_pnl_scenario(PnlScenarioHttpRequest.model_validate(body), _ctx())
    assert out["orders"]["rto"] == {"num": "21", "den": "20", "text": "1.05", "exact": True}
    assert out["orders"]["kept"]["text"] == "5.95"


# ---- the request is strict ----------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize(
    "mutation",
    [
        {"tenant_id": str(uuid.uuid4())},  # N-AC5: a client can never name a tenant
        {"selling_price": {"state": "set", "value": 1180.5}},  # float
        {"selling_price": {"state": "set", "value": "1180.50"}},  # decimal point
        {"selling_price": {"state": "set", "value": "1e3"}},  # exponent
        {"selling_price": {"state": "set", "value": "-5"}},  # negative
        {"selling_price": {"state": "set", "value": "007"}},  # leading zeros
        {"selling_price": {"state": "set", "value": ""}},
        {"selling_price": {"state": "set"}},  # set without a value
        {"selling_price": {"state": "empty", "value": "100"}},  # empty carrying a value
        {"selling_price": {"state": "na", "value": "0"}},
        {"selling_price": {"state": "invalid", "value": "x"}},  # clients cannot send 'invalid'
        {"selling_price": {"state": "set", "value": "10000000000001"}},  # above the money cap
        {"gst_rate_bps": {"state": "set", "value": "10001"}},  # above 100%
        {"monthly_orders": {"state": "set", "value": "1000000001"}},
        {"fees": {"nonsense": _fee("100")}},  # a fee the marketplace does not have
        {"fees": {"referral": _fee("10001")}},  # a percent fee above 100%
        {"fees": {"closing": {"amount": {"state": "set", "value": {"kind": "single", "amount": "1", "extra": 1}}}}},
        {"fees": {"shipping": {"amount": {"state": "set", "value": {"kind": "tiers", "mode": "whole", "bands": [{"up_to": None, "amount": "1"}]}}}}},  # not tierable
        {"fees": {"referral": {"amount": {"state": "set"}}}},
        {"fees": {"referral": {"amount": {"state": "na", "value": {"kind": "single", "amount": "1"}}}}},
        {"targets": [{"kind": "margin", "bps": "10000"}]},
        {"targets": [{"kind": "margin", "bps": 2000}]},  # a number, not an integer string,
        {"targets": [{"kind": "breakeven"}] * 5},
        {"marketplace": "ebay"},
        {"unknown_field": 1},
    ],
)
def test_malformed_or_hostile_requests_are_rejected(mutation: dict) -> None:
    with pytest.raises(ValidationError):
        PnlScenarioHttpRequest.model_validate(_a1() | mutation)


def test_too_many_bands_are_rejected() -> None:
    bands = [{"up_to": str(i + 1), "amount": "1"} for i in range(12)] + [{"up_to": None, "amount": "1"}]
    body = _a1() | {"fees": {"referral": {"amount": {"state": "set", "value": {"kind": "tiers", "mode": "whole", "bands": bands}}}}}
    with pytest.raises(ValidationError):
        PnlScenarioHttpRequest.model_validate(body)


def test_inconsistent_bands_reach_the_engine_as_a_blocked_incomplete_result_not_a_crash(runs: _Runs) -> None:
    bands = [{"up_to": "500", "amount": "1000"}, {"up_to": "100", "amount": "1000"}, {"up_to": None, "amount": "1000"}]
    body = _a1() | {"fees": {"referral": {"amount": {"state": "set", "value": {"kind": "tiers", "mode": "whole", "bands": bands}}}}}
    out = cfo_routes.post_pnl_scenario(PnlScenarioHttpRequest.model_validate(body), _ctx())
    assert out["status"] == "incomplete" and any(i["code"] == "invalid_tiers_referral" for i in out["issues"])


def test_solver_results_are_integer_strings_and_name_missing_costs(runs: _Runs) -> None:
    body = _a1() | {"fees": {"referral": _fee("1000")}, "targets": [{"kind": "breakeven"}]}
    out = cfo_routes.post_pnl_scenario(PnlScenarioHttpRequest.model_validate(body), _ctx())
    s = out["solutions"][0]
    assert s["outcome"] == "price" and isinstance(s["price"], str) and s["excludesMissingCosts"] is True


# ---- the frontend reads what the backend sends ---------------------------------------------------------------------------------------

def _conforms(actual, contract, where: str) -> list[str]:
    """Every non-optional key of the frontend's response contract is present in the real response (extra keys are fine)."""
    if contract is None:
        return []
    if isinstance(contract, list):
        if not isinstance(actual, list):
            return [f"{where}: expected a list"]
        return [p for i, item in enumerate(actual) for p in _conforms(item, contract[0], f"{where}[{i}]")]
    if not isinstance(actual, dict):
        return [f"{where}: expected an object"]
    problems: list[str] = []
    for key, sub in contract.items():
        optional, nullable, name = key.endswith("?"), key.rstrip("?").endswith("~"), key.rstrip("?").rstrip("~")
        if name not in actual:
            if not optional:
                problems.append(f'{where}: missing "{name}"')
            continue
        if nullable and actual[name] is None:
            continue
        problems.extend(_conforms(actual[name], sub, f"{where}.{name}"))
    return problems


@pytest.mark.parametrize(
    "body",
    [_a1() | {"targets": [{"kind": "breakeven"}, {"kind": "margin", "bps": "2000"}]}, {"marketplace": "flipkart"}, _a1() | {"fees": {}}],
    ids=["complete", "incomplete", "provisional"],
)
def test_the_response_has_every_field_the_screen_reads(runs: _Runs, body: dict) -> None:
    import json
    from pathlib import Path

    contract = json.loads((Path(__file__).resolve().parents[3] / "frontend" / "test-support" / "responseContracts.json").read_text(encoding="utf-8"))
    out = cfo_routes.post_pnl_scenario(PnlScenarioHttpRequest.model_validate(body), _ctx())
    assert _conforms(out, contract["POST /api/v1/cfo/pnl-scenario"], "pnl-scenario") == []


# ---- regression against the reference calculator ------------------------------------------------------------------------------------

def _view_json(v):  # noqa: ANN001, ANN202
    if v is None:
        return None
    return {
        "revenue": str(v.revenue.value), "contribution": str(v.contribution.value), "lines": [[ln.id, str(ln.amount.value)] for ln in v.lines],
        "opex": None if v.operating_expenses is None else str(v.operating_expenses.value),
        "opProfit": None if v.operating_profit is None else str(v.operating_profit.value),
    }


def _solve_json(s):  # noqa: ANN001, ANN202
    return {"kind": s.kind, "price": None if s.price is None else str(s.price.value), "ranges": [[r.from_price, r.to_price] for r in s.ranges],
            "excl": s.excludes_missing_costs, "reason": s.reason}


def test_matches_the_reference_calculators_answers_on_recorded_random_scenarios() -> None:
    """N-AC2. 90 random scenarios through the real request model, each with the answer the reference TypeScript engine gave too (see the fixture's
    `provenance`). A change to the Python engine, the request translation or the rounding that moves any figure fails here."""
    import json
    from pathlib import Path

    from calc_engine.formulas.pnl_scenario import SolveTarget, calculate_scenario, solve_price
    from backend.services.pnl_scenario import to_inputs

    fixture = json.loads((Path(__file__).resolve().parents[1] / "fixtures" / "pnl_scenario_reference_cases.json").read_text(encoding="utf-8"))
    assert len(fixture["cases"]) >= 90
    statuses = {c["expected"]["status"] for c in fixture["cases"]}
    assert statuses == {"incomplete", "provisional", "estimate"}
    for i, case in enumerate(fixture["cases"]):
        inputs = to_inputs(PnlScenarioHttpRequest.model_validate(case["body"]))
        r = calculate_scenario(inputs)
        m = r.metrics
        got = {
            "status": r.status, "missing": list(r.missing_costs), "assumptions": [a.code for a in r.assumptions], "issues": [x.code for x in r.issues],
            "noKept": r.no_kept_orders, "perKept": _view_json(r.per_kept), "perPlaced": _view_json(r.per_placed), "monthly": _view_json(r.monthly),
            "breakeven": _solve_json(solve_price(inputs, SolveTarget("breakeven"))), "margin20": _solve_json(solve_price(inputs, SolveTarget("margin", 2000))),
            "orders": None if r.orders is None else [str(r.orders.placed), str(r.orders.kept), str(r.orders.rto), str(r.orders.returned)],
            "m": None if m is None else {
                "cm": m.contribution_margin_bps, "om": m.operating_margin_bps, "fee": m.effective_fee_bps, "acos": m.acos_bps, "tacos": m.tacos_bps,
                "roas": m.roas_bps, "beRoas": m.break_even_roas_bps, "cac": None if m.max_cac is None else m.max_cac.value,
                "gstK": None if m.gst_recovered_per_kept is None else m.gst_recovered_per_kept.value,
                "gstM": None if m.gst_recovered_monthly is None else m.gst_recovered_monthly.value,
            },
        }
        assert got == case["expected"], f"case {i}"


# ---- where each rupee goes -----------------------------------------------------------------------------------------------------------

def test_the_response_carries_the_server_computed_breakdown_as_integer_strings(runs: _Runs) -> None:
    out = cfo_routes.post_pnl_scenario(PnlScenarioHttpRequest.model_validate(_a1()), _ctx())
    b = out["breakdown"]
    assert b["profitShareBps"] == "4920"
    assert {ln["id"]: ln["shareBps"] for ln in b["lines"]}["fee_referral"] == "1180"
    assert [t["id"] for t in b["topCosts"]] == ["product", "fee_referral", "fee_shipping"]
    assert [(g["id"], g["startBps"], g["endBps"]) for g in b["segments"]][-1] == ("profit", "5080", "10000")
    assert b["chartUnavailableReason"] is None
    for g in b["segments"] + b["lines"] + b["topCosts"]:
        assert all(isinstance(g[k], str) for k in ("amount", "shareBps"))


def test_the_breakdown_is_absent_when_there_is_no_figure_to_break_down(runs: _Runs) -> None:
    out = cfo_routes.post_pnl_scenario(PnlScenarioHttpRequest.model_validate({"marketplace": "flipkart"}), _ctx())
    assert out["breakdown"] is None


def test_a_loss_has_shares_and_top_costs_but_no_chart(runs: _Runs) -> None:
    out = cfo_routes.post_pnl_scenario(PnlScenarioHttpRequest.model_validate(_a1() | {"product_cost": _set("200000")}), _ctx())
    b = out["breakdown"]
    assert b["segments"] is None and "no profit slice" in b["chartUnavailableReason"] and b["topCosts"][0]["id"] == "product"


def test_on_every_recorded_reference_scenario_the_slices_tile_the_circle_and_the_profit_share_is_the_margin() -> None:
    """Invariants over the 90 recorded random scenarios (provisional and complete): the chart tiles 0..10000 with no gap, its last slice is the profit, the
    profit share equals the contribution margin, and no biggest cost is zero or a credit."""
    import json
    from pathlib import Path

    from calc_engine.formulas.pnl_scenario import calculate_scenario
    from backend.services.pnl_scenario import to_inputs

    cases = json.loads((Path(__file__).resolve().parents[1] / "fixtures" / "pnl_scenario_reference_cases.json").read_text(encoding="utf-8"))["cases"]
    seen_chart = seen_none = 0
    for i, case in enumerate(cases):
        r = calculate_scenario(to_inputs(PnlScenarioHttpRequest.model_validate(case["body"])))
        b = r.breakdown
        if r.per_kept is None:
            assert b is None, i
            continue
        assert b is not None and b.profit_share_bps == r.metrics.contribution_margin_bps, i
        assert all(t.amount.value > 0 for t in b.top_costs) and len(b.top_costs) <= 3, i
        if b.segments is None:
            seen_none += 1
            assert b.chart_unavailable_reason, i
            continue
        seen_chart += 1
        assert b.segments[0].start_bps == 0 and b.segments[-1].end_bps == 10000 and b.segments[-1].id == "profit", i
        assert all(a.end_bps == c.start_bps for a, c in zip(b.segments, b.segments[1:])), i
    # Most random scenarios are losses or have fee-refund credits (no chart), so only a few draw one; the engine suite checks tiling on many generated ones.
    assert seen_chart >= 3 and seen_none >= 3, (seen_chart, seen_none)
