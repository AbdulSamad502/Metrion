"""direct_path/pi_report.py — re-renders a completed run from persisted data only, no new
fetch. Repository calls monkeypatched (no live Postgres)."""

from __future__ import annotations

from uuid import uuid4

import pytest

from product_intelligence.direct_path import pi_report
from product_intelligence.repositories import (
    pi_research_run_repo,
    product_candidate_repo,
    product_review_insight_repo,
    supplier_lead_repo,
)

_TENANT_ID = uuid4()
_RUN_ID = uuid4()
_CANDIDATE_ID = uuid4()


def test_raises_when_run_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pi_research_run_repo, "get_run", lambda tenant_id, run_id: None)
    with pytest.raises(ValueError, match="no pi_research_run"):
        pi_report.render_report(_TENANT_ID, _RUN_ID)


def test_unavailable_always_names_marketplace_price_and_demand_signal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pi_research_run_repo, "get_run", lambda tenant_id, run_id: {"status": "COMPLETE"})
    monkeypatch.setattr(product_candidate_repo, "list_candidates_for_run", lambda tenant_id, run_id: [])

    report = pi_report.render_report(_TENANT_ID, _RUN_ID)

    fields = {u["field"] for u in report.unavailable}
    assert "marketplace_price_and_competition" in fields
    assert "demand_signal" in fields


def test_partial_run_adds_run_completeness_to_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        pi_research_run_repo,
        "get_run",
        lambda tenant_id, run_id: {"status": "PARTIAL", "partial_reason": "Tavily unavailable"},
    )
    monkeypatch.setattr(product_candidate_repo, "list_candidates_for_run", lambda tenant_id, run_id: [])

    report = pi_report.render_report(_TENANT_ID, _RUN_ID)
    fields = {u["field"]: u["reason"] for u in report.unavailable}
    assert fields["run_completeness"] == "Tavily unavailable"


def test_candidates_carry_final_score_from_shortlist_scoring(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pi_research_run_repo, "get_run", lambda tenant_id, run_id: {"status": "COMPLETE"})
    monkeypatch.setattr(
        product_candidate_repo,
        "list_candidates_for_run",
        lambda tenant_id, run_id: [
            {"id": str(_CANDIDATE_ID), "proxy_state": "COMPUTED", "proxy_score": "50.00"}
        ],
    )
    monkeypatch.setattr(product_review_insight_repo, "list_insights_for_candidate", lambda tenant_id, cid: [])
    monkeypatch.setattr(supplier_lead_repo, "list_leads_for_candidate", lambda tenant_id, cid: [])

    report = pi_report.render_report(_TENANT_ID, _RUN_ID)

    assert len(report.candidates) == 1
    entry = report.candidates[0]
    assert entry["final_score_state"] in ("COMPUTED", "UNAVAILABLE")
    assert "final_score_explanation" in entry
