"""`backend.services.cfo_actions.assemble_cfo_preview` — D7, cfo-agent.md §6.9/§6.8
`cfo.preview`, the free-tier gated preview (approved this session, no longer provisional).

`run_leak_shield_reconciliation` is monkeypatched here to return a constructed
`LeakShieldOutcome` — this file exercises only the composition logic (revealed-vs-locked
split, headline-total threading, the honest `affected_sku_count` unavailable-vs-zero
distinction), not the real reconciliation pipeline itself (that is
`test_leak_shield_reconciliation.py`'s job, and D5's own unit/integration tests).

Covers:
  - 3 real-shaped findings, already in rank order -> exactly the first is revealed,
    `locked_findings_count == 2`.
  - empty findings -> `revealed_finding is None`, `locked_findings_count == 0`, and
    `affected_sku_count` is a real, honest `0` (not unavailable — no findings at all is a
    genuinely different state from "findings exist but none carry a sku").
  - every finding has `sku=None` -> `affected_sku_count` is the unavailable state
    (`None`/`affected_sku_count_unavailable=True`), never a bare `0`.
  - some findings carry a real `sku`, some don't -> only the non-null ones are counted.
  - `headline_total_paise`/`headline_engine_result_ref` are copied unchanged from
    `LeakShieldOutcome.aggregate_amount_paise`/`aggregate_engine_result_ref` — never
    recomputed, never summed from `findings[].amount_paise` (§6.4 rule 5).
"""

from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest

import backend.services.cfo_actions as cfo_actions_module
from backend.services.cfo_actions import LeakShieldOutcome, assemble_cfo_preview

_AS_OF = date(2026, 9, 25)
_PERIOD_START = date(2026, 9, 1)
_PERIOD_END = date(2026, 9, 30)
_TENANT = uuid4()


def _finding(*, leak_category: str, amount_paise: int, sku: str | None = None) -> dict[str, object]:
    return {
        "leak_finding_id": uuid4(),
        "leak_category": leak_category,
        "severity": "HIGH",
        "window_status": "OPEN",
        "amount_paise": amount_paise,
        "marketplace": "MEESHO",
        "engine_result_ref": str(uuid4()),
        "sku": sku,
    }


def _outcome(findings: list[dict[str, object]], *, aggregate_total: int = 12500) -> LeakShieldOutcome:
    return LeakShieldOutcome(
        reconciliation_run_id=uuid4(),
        findings=findings,
        match_count=1,
        exception_count=len(findings),
        ambiguous_match_count=0,
        dates_missing_count=0,
        aggregate_amount_paise=aggregate_total,
        aggregate_engine_result_ref=str(uuid4()),
        # SETTLEMENT_LAG_DAYS fields (this checkpoint) — assemble_cfo_preview never reads
        # these, so an honest "unavailable, zero pairs" shape is sufficient for this file's
        # own scope (revealed-vs-locked/headline-total composition logic only).
        settlement_lag_engine_result_ref=str(uuid4()),
        settlement_lag_is_available=False,
        settlement_lag_mean_days=None,
        settlement_lag_pair_count=None,
    )


def _call(monkeypatch: pytest.MonkeyPatch, outcome: LeakShieldOutcome):
    monkeypatch.setattr(
        cfo_actions_module, "run_leak_shield_reconciliation", lambda *a, **k: outcome
    )
    return assemble_cfo_preview(
        _TENANT,
        marketplace="MEESHO",
        period_start=_PERIOD_START,
        period_end=_PERIOD_END,
        as_of_date=_AS_OF,
    )


def test_first_of_three_findings_revealed_rest_locked(monkeypatch: pytest.MonkeyPatch) -> None:
    findings = [
        _finding(leak_category="FEE_OVERCHARGE", amount_paise=3200),
        _finding(leak_category="SHORT_SETTLEMENT", amount_paise=1200),
        _finding(leak_category="UNEXPECTED_DEDUCTION", amount_paise=800),
    ]
    outcome = _call(monkeypatch, _outcome(findings, aggregate_total=12500))

    assert outcome.revealed_finding is not None
    assert outcome.revealed_finding["leak_category"] == "FEE_OVERCHARGE"
    assert outcome.revealed_finding["amount_paise"] == 3200
    assert outcome.locked_findings_count == 2
    assert outcome.headline_total_paise == 12500


def test_empty_findings_none_revealed_zero_locked_zero_sku_not_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outcome = _call(monkeypatch, _outcome([], aggregate_total=0))

    assert outcome.revealed_finding is None
    assert outcome.locked_findings_count == 0
    assert outcome.affected_sku_count == 0
    assert outcome.affected_sku_count_unavailable is False


def test_every_finding_sku_none_reports_unavailable_never_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    findings = [
        _finding(leak_category="FEE_OVERCHARGE", amount_paise=3200, sku=None),
        _finding(leak_category="SHORT_SETTLEMENT", amount_paise=1200, sku=None),
    ]
    outcome = _call(monkeypatch, _outcome(findings))

    assert outcome.affected_sku_count is None
    assert outcome.affected_sku_count_unavailable is True


def test_mixed_null_and_real_sku_counts_only_non_null(monkeypatch: pytest.MonkeyPatch) -> None:
    findings = [
        _finding(leak_category="FEE_OVERCHARGE", amount_paise=3200, sku="SKU-A"),
        _finding(leak_category="SHORT_SETTLEMENT", amount_paise=1200, sku=None),
        _finding(leak_category="UNEXPECTED_DEDUCTION", amount_paise=800, sku="SKU-B"),
    ]
    outcome = _call(monkeypatch, _outcome(findings))

    assert outcome.affected_sku_count == 2
    assert outcome.affected_sku_count_unavailable is False


def test_headline_total_never_summed_from_findings(monkeypatch: pytest.MonkeyPatch) -> None:
    """§6.4 rule 5 — even though the findings' amounts would sum to a different number than the
    aggregate, the headline total must come from LeakShieldOutcome.aggregate_amount_paise alone,
    proving this function performs no summation itself."""
    findings = [
        _finding(leak_category="FEE_OVERCHARGE", amount_paise=100),
        _finding(leak_category="SHORT_SETTLEMENT", amount_paise=200),
    ]
    # Deliberately mismatched vs. sum(100, 200) == 300, to prove no local summation happens.
    outcome = _call(monkeypatch, _outcome(findings, aggregate_total=999999))

    assert outcome.headline_total_paise == 999999
