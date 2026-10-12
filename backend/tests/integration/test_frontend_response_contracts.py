"""What the frontend READS from each response must be in the real response.

`frontend/test-support/responseContracts.json` is generated from the frontend's own TypeScript types (a frontend test fails when it is stale). This file
calls the real endpoints over HTTP, with the real app, auth chain (Clerk faked), tenant context, RLS and repositories on a real Postgres, seeded so that every
list in the contract has items, and fails when a field the frontend reads is missing. Extra fields in a response are fine; a missing one is a screen reading
`undefined`.

Only Clerk and the two model handles are faked, exactly as in `test_ceo_api.py` (this is a deterministic integration test, not a live-model one)."""

from __future__ import annotations

import json
import os
import uuid
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from backend.ceo import findings, memory
from backend.repositories import investigation_repo
from tests.integration.ceo_support import save_metric
from tests.integration.test_ceo_api import STATE, api, clerk, login, start  # noqa: F401  (fixtures)
from tests.integration.test_ceo_turn import seed_books

pytestmark = [
    pytest.mark.usefixtures("two_tenants"),
    pytest.mark.skipif(not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL"), reason="needs a live Postgres"),
]

CONTRACTS: dict[str, Any] = json.loads((Path(__file__).resolve().parents[3] / "frontend" / "test-support" / "responseContracts.json").read_text(encoding="utf-8"))


def conforms(actual: Any, contract: Any, where: str, seen_lists: set[str]) -> list[str]:
    """Problems: every non-optional key of the contract present in the response, recursively; a list contract needs a list (its items are checked when present)."""
    if contract is None:
        return []
    if isinstance(contract, list):
        if not isinstance(actual, list):
            return [f"{where}: expected a list, got {type(actual).__name__}"]
        if actual:
            seen_lists.add(where)
        return [p for i, item in enumerate(actual) for p in conforms(item, contract[0], f"{where}[{i}]", seen_lists)]
    if not isinstance(actual, dict):
        return [f"{where}: expected an object, got {type(actual).__name__}"]
    problems: list[str] = []
    for key, sub in contract.items():
        optional = key.endswith("?")
        nullable = key.rstrip("?").endswith("~")  # the type allows null for this nested value
        name = key.rstrip("?").rstrip("~")
        if name not in actual:
            if not optional:
                problems.append(f"{where}: missing \"{name}\"")
            continue
        if nullable and actual[name] is None:
            continue
        problems.extend(conforms(actual[name], sub, f"{where}.{name}", seen_lists))
    return problems


def check(route: str, actual: Any) -> set[str]:
    seen: set[str] = set()
    problems = conforms(actual, CONTRACTS[route], route, seen)
    assert problems == [], "\n".join(problems)
    return seen


def test_the_contract_file_covers_the_routes_the_screens_read() -> None:
    assert len(CONTRACTS) >= 13
    assert "GET /api/v1/ceo/findings" in CONTRACTS and "POST /api/v1/cfo/cash-reconciliation" in CONTRACTS


def test_a_checker_that_would_notice_a_missing_field() -> None:
    assert conforms({"items": [{"id": "x"}]}, {"items": [{"id": None, "trustLabel": None}]}, "t", set()) == ['t.items[0]: missing "trustLabel"']
    assert conforms({"a": 1}, {"a": None, "b?": None}, "t", set()) == []


def test_the_session_and_agent_lists_the_shell_reads(api):
    client, ha, _, a, _ = api
    check("GET /api/v1/session", client.get("/api/v1/session", headers=ha).json())
    agents = client.get("/api/v1/ceo-hub/agents", headers=ha).json()
    assert agents, "the contract check needs at least one agent to be meaningful"
    check("GET /api/v1/ceo-hub/agents", agents)
    check("GET /api/v1/ci/summary", client.get("/api/v1/ci/summary", headers=ha).json())
    check("GET /api/v1/ci/alerts", client.get("/api/v1/ci/alerts", params={"days": 14}, headers=ha).json())
    check("GET /api/v1/ci/digest/subscription", client.get("/api/v1/ci/digest/subscription", headers=ha).json())


def test_a_data_request_as_the_action_center_reads_it(api):
    from cfo.repositories import agent_data_request_repo

    client, ha, _, a, _ = api
    agent_data_request_repo.insert(a, requested_field="cogs_per_unit", reason="COGS is needed for contribution profit", blocking_metric="CONTRIBUTION_PROFIT")
    rows = client.get("/api/v1/cfo/data-requests", headers=ha).json()
    assert check("GET /api/v1/cfo/data-requests", rows) == {"GET /api/v1/cfo/data-requests"}  # the item shape was really checked


def test_cash_reconciliation_as_the_screen_reads_it_for_controlled_settlement_rows(api):
    from tests.integration.test_cfo_cash_reconciliation import _AS_OF, _PERIOD_END, _PERIOD_START, _insert_report_file_and_run, _insert_settlement_line

    client, ha, _, a, _ = api
    run = _insert_report_file_and_run(a, marketplace="MEESHO")
    _insert_settlement_line(a, ingestion_run_id=run, marketplace="MEESHO")
    body = {"marketplace": "MEESHO", "period_start": _PERIOD_START.isoformat(), "period_end": _PERIOD_END.isoformat(), "as_of_date": _AS_OF.isoformat()}
    resp = client.post("/api/v1/cfo/cash-reconciliation", json=body, headers=ha)
    assert resp.status_code == 200, resp.text
    check("POST /api/v1/cfo/cash-reconciliation", resp.json())


def test_shared_findings_and_memory_as_the_hub_reads_them(api, app_user):
    client, ha, _, a, _ = api
    idea = findings.record(a, agent="PI", kind="PRODUCT_IDEA", text="Product Intelligence listed this idea in its latest research.", subject="Steel bottle",
                           source_ref={"kind": "metric_result", "id": str(save_metric(a, "SOURCE", period=None))})
    metric = save_metric(a, "CONTRIBUTION_PROFIT", period="2026-09")
    findings.record(a, agent="CFO", kind="LEAK_FOUND", text="Open Leak Shield finding of high severity for the period.",
                    source_ref={"kind": "metric_result", "id": str(save_metric(a, "SOURCE", period=None))}, figure_refs=[{"label": "Profit", "kind": "ENGINE_RESULT", "id": str(metric)}])
    listed = client.get("/api/v1/ceo/findings", headers=ha).json()
    assert len(listed["items"]) == 2 and str(idea)
    assert "GET /api/v1/ceo/findings.items" in check("GET /api/v1/ceo/findings", listed)

    inv = investigation_repo.create_investigation(a, created_by=app_user)
    msg = investigation_repo.append_message(a, inv, role="USER", content="my business name is Zyquora", created_by=app_user)
    assert memory.remember_from_message(a, app_user, msg, "my business name is Zyquora")
    mem = client.get("/api/v1/ceo/memory", headers=ha).json()
    assert mem["items"]
    check("GET /api/v1/ceo/memory", mem)


def test_a_conversation_turn_and_its_restoration_as_the_hub_reads_them(api):
    client, ha, _, a, _ = api
    seed_books(a)
    inv = start(client, ha)
    turn = client.post(f"/api/v1/ceo/investigations/{inv}/turns", json={"message": STATE}, headers=ha)
    assert turn.status_code == 200, turn.text
    check("POST /api/v1/ceo/investigations/{investigation_id}/turns", turn.json())
    listed = client.get("/api/v1/ceo/investigations", headers=ha).json()
    assert [i["id"] for i in listed] == [inv]
    check("GET /api/v1/ceo/investigations", listed)
    detail = client.get(f"/api/v1/ceo/investigations/{inv}", headers=ha).json()
    seen = check("GET /api/v1/ceo/investigations/{investigation_id}", detail)
    assert any(s.endswith(".messages") for s in seen) and any(s.endswith(".findings") for s in seen)  # the messages and findings items were really checked
    check("GET /api/v1/ceo/state/health", client.get("/api/v1/ceo/state/health", headers=ha).json())
