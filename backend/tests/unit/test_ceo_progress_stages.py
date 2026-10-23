"""The CFO planner's stage names reach the CEO turn as live progress (names only, never figures)."""

from __future__ import annotations

from uuid import uuid4

from backend.services import cfo_query, ceo_progress


def _run(monkeypatch, **kw):
    seen = {}

    def fake(question, periods, **k):
        seen["on_stage"] = k["on_stage"]
        return "ok"

    monkeypatch.setattr(cfo_query, "run_financial_query", fake)
    monkeypatch.setattr(cfo_query, "cfo_planner_settings", lambda: {"fee_codes": (), "forward_logistics_codes": (), "reverse_logistics_codes": (), "non_refunded_fee_codes": (), "statement_timeout_ms": 1, "min_coverage": {}, "cash_min_samples": 1, "cache_ttl_seconds": 1, "max_rows_scanned": 1, "max_groups": 1, "max_limit": 1, "low_explainability_share": 0, "oracle_sample_size": 1, "max_ranking_groups": 1})
    monkeypatch.setattr(cfo_query, "planner_limits", lambda s: None)
    monkeypatch.setattr(cfo_query, "_cache", lambda ttl: None)
    monkeypatch.setattr(cfo_query, "PostgresPlannerBackend", lambda **k: None)
    cfo_query.answer_financial_query(uuid4(), requested_by=uuid4(), question="q", periods=[], provider=object(), **kw)
    return seen["on_stage"]


def test_without_a_sink_no_stage_is_reported(monkeypatch):
    assert _run(monkeypatch) is None


def test_the_turn_sink_receives_the_planner_stages(monkeypatch):
    got: list[str] = []
    token = ceo_progress.STAGE_SINK.set(got.append)
    try:
        _run(monkeypatch)("PLANNING")
    finally:
        ceo_progress.STAGE_SINK.reset(token)
    assert got == ["PLANNING"]


def test_an_explicit_callback_wins_over_the_sink(monkeypatch):
    mine: list[str] = []
    assert _run(monkeypatch, on_stage=mine.append) == mine.append
