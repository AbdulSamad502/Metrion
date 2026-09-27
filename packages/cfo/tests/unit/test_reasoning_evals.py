"""LLM evals for Brain-3 narration — required for any new `narrate_*` composition
(`CLAUDE.md`'s "LLM evals" rule). This file cannot eval a live model's actual prose
deterministically, so it evals what THIS layer guarantees structurally, before/regardless of
whatever a real model returns:

  1. `SYSTEM_PROMPT` states the never-compute / never-invent-a-rate contract, plus the three
     new domain rules this checkpoint adds (RTO outcomes never collapsed, TCS/TDS never
     described as reducing profit, discount bearer stated as given / never reclassified,
     reconciliation never called an audit, Contribution Profit vs EBITDA/PAT never stated as
     a figure).
  2. `narrate_leak_findings` on a zero-findings `LeakShieldOutcome` produces a real "no leaks"
     figure — never silently empty narration, never an invented finding.
  3. Neither `narrate_leak_findings` nor `narrate_anomaly_check` ever builds a `FigureToken`
     whose `formatted_value` is a raw `int`/`Fraction`/`Paise` — type-checked on the actual
     tokens each function builds, not just eyeballed.
  4. A `leak_finding` with an `UNAVAILABLE`-equivalent state (severity `"UNAVAILABLE"`, the
     real value `run_leak_shield_reconciliation` mints when no severity_config row applies) is
     narrated as unavailable, never defaulted to a formatted zero or a fabricated band.

Mirrors `test_narrate_no_numbers.py`'s `_StubProvider` convention — a deterministic
`LlmProvider` stand-in, never a real model call anywhere in this file.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from fractions import Fraction
from uuid import uuid4

import backend.services.cfo_actions as cfo_actions_module
from backend.services.cfo_actions import (
    AnomalyCheckOutcome,
    AnomalyMethodOutcome,
    LeakShieldOutcome,
    narrate_anomaly_check,
    narrate_leak_findings,
)
from calc_engine.anomaly.types import AnomalyFlag, AnomalyThreshold
from cfo.reasoning.narrate import FigureToken
from cfo.reasoning.prompts import SYSTEM_PROMPT

_AS_OF = date(2026, 9, 25)
_COMPUTED_AT = datetime(2026, 9, 25, tzinfo=timezone.utc)
_MODEL = "test-model"  # never the real cfo_narration_model() name — this file never calls Ollama


@dataclass
class _StubProvider:
    """Deterministic `LlmProvider` stand-in — captures every prompt it is handed, returns a
    fixed response. Never a real model call."""

    response: str = "narration"
    captured_prompts: list[str] | None = None

    def __post_init__(self) -> None:
        if self.captured_prompts is None:
            self.captured_prompts = []

    def complete(self, *, model: str, prompt: str) -> str:
        self.captured_prompts.append(prompt)
        return self.response


def _captured_tokens(monkeypatch, call) -> list[FigureToken]:
    """Monkeypatches `cfo_actions_module.narrate_figures` to capture the `figures` list a
    narration function builds, then runs `call()` (which must invoke `narrate_figures` exactly
    once) and returns the captured tokens — lets this file assert on the actual `FigureToken`
    objects a function builds, not merely on the resulting prompt string."""
    captured: list[FigureToken] = []

    def _fake_narrate_figures(provider, *, model, context, figures, gst_context=False):
        captured.extend(figures)
        return "narration"

    monkeypatch.setattr(cfo_actions_module, "narrate_figures", _fake_narrate_figures)
    call()
    return captured


# ---------------------------------------------------------------------------------------
# 1. SYSTEM_PROMPT — the never-compute / never-invent-a-rate contract, plus the three new
#    domain rules this checkpoint adds.
# ---------------------------------------------------------------------------------------


def test_system_prompt_still_states_never_compute_and_never_invent_a_rate() -> None:
    lowered = SYSTEM_PROMPT.lower()
    assert "never calculate" in lowered or "you never calculate" in lowered
    assert "re-derive" in lowered
    assert "gst rate" in lowered and "training knowledge" in lowered


def test_system_prompt_never_collapses_the_three_rto_outcomes() -> None:
    lowered = SYSTEM_PROMPT.lower()
    assert "recovered-sellable" in lowered
    assert "recovered-damaged" in lowered
    assert "lost-in-transit" in lowered
    assert "never" in lowered and "collapsed" in lowered


def test_system_prompt_states_tcs_tds_are_cash_items_never_pl() -> None:
    lowered = SYSTEM_PROMPT.lower()
    assert "tcs" in lowered and "tds" in lowered
    assert "cash item" in lowered
    assert "never describe them as reducing profit" in lowered


def test_system_prompt_forbids_reclassifying_discount_bearer() -> None:
    lowered = SYSTEM_PROMPT.lower()
    assert "bearer" in lowered
    assert "never infer or reclassify" in lowered


def test_system_prompt_forbids_calling_reconciliation_an_audit() -> None:
    lowered = SYSTEM_PROMPT.lower()
    assert "invoice-vs-settlement delta" in lowered or "invoice-vs-\nsettlement delta" in lowered
    assert "audit" in lowered


def test_system_prompt_forbids_stating_ebitda_or_pat_as_a_figure() -> None:
    lowered = SYSTEM_PROMPT.lower()
    assert "contribution profit" in lowered
    assert "ebitda" in lowered
    assert "pat" in lowered
    assert "never as a number you state as a result" in lowered


# ---------------------------------------------------------------------------------------
# 2. Zero findings -> a real "no leaks" figure, never silent/empty narration.
# ---------------------------------------------------------------------------------------


def _leak_shield_outcome(
    *,
    findings: list[dict[str, object]] | None = None,
    aggregate_amount_paise: int = 0,
    settlement_lag_is_available: bool = False,
    settlement_lag_mean_days: str | None = None,
    settlement_lag_pair_count: int | None = None,
) -> LeakShieldOutcome:
    return LeakShieldOutcome(
        reconciliation_run_id=uuid4(),
        findings=findings if findings is not None else [],
        match_count=3,
        exception_count=len(findings) if findings else 0,
        ambiguous_match_count=0,
        dates_missing_count=0,
        aggregate_amount_paise=aggregate_amount_paise,
        aggregate_engine_result_ref=str(uuid4()),
        settlement_lag_engine_result_ref=str(uuid4()),
        settlement_lag_is_available=settlement_lag_is_available,
        settlement_lag_mean_days=settlement_lag_mean_days,
        settlement_lag_pair_count=settlement_lag_pair_count,
    )


def test_zero_findings_produces_a_real_no_leaks_figure_never_silent_narration(monkeypatch) -> None:
    outcome = _leak_shield_outcome(findings=[], aggregate_amount_paise=0)
    provider = _StubProvider()

    tokens = _captured_tokens(
        monkeypatch,
        lambda: narrate_leak_findings(provider, model=_MODEL, outcome=outcome),
    )

    no_leaks_tokens = [t for t in tokens if "no leaks found this run" in t.formatted_value]
    assert len(no_leaks_tokens) == 1
    assert no_leaks_tokens[0].register != "UNAVAILABLE"  # a real, positive zero-leak result


def test_zero_findings_result_is_never_empty_narration() -> None:
    outcome = _leak_shield_outcome(findings=[], aggregate_amount_paise=0)
    provider = _StubProvider(response="No leaks were found in this reconciliation run.")
    result = narrate_leak_findings(provider, model=_MODEL, outcome=outcome)
    assert result != ""
    assert provider.captured_prompts is not None and len(provider.captured_prompts) == 1
    assert "no leaks found this run" in provider.captured_prompts[0].lower()


# ---------------------------------------------------------------------------------------
# 3. Type-check the actual FigureTokens each narration function builds — never a raw
#    int/Fraction/Paise in `formatted_value`.
# ---------------------------------------------------------------------------------------


def _real_finding(
    *,
    amount_paise: int = 123_45,
    severity: str = "HIGH",
    window_status: str = "OPEN",
    confidence: str = "DERIVED",
    leak_category: str = "FEE_OVERCHARGE",
    marketplace: str = "MEESHO",
) -> dict[str, object]:
    return {
        "leak_finding_id": uuid4(),
        "leak_category": leak_category,
        "severity": severity,
        "window_status": window_status,
        "amount_paise": amount_paise,
        "marketplace": marketplace,
        "engine_result_ref": str(uuid4()),
        "sku": None,
        "confidence": confidence,
    }


def test_narrate_leak_findings_never_builds_a_token_with_a_raw_numeric_formatted_value(
    monkeypatch,
) -> None:
    outcome = _leak_shield_outcome(
        findings=[_real_finding(), _real_finding(amount_paise=99_00, severity="LOW")],
        aggregate_amount_paise=222_45,
        settlement_lag_is_available=True,
        settlement_lag_mean_days=str(Fraction(16, 5)),
        settlement_lag_pair_count=5,
    )
    provider = _StubProvider()

    tokens = _captured_tokens(
        monkeypatch,
        lambda: narrate_leak_findings(provider, model=_MODEL, outcome=outcome),
    )

    assert len(tokens) >= 3  # 2 findings + LEAK_TOTAL + SETTLEMENT_LAG_DAYS
    for token in tokens:
        assert isinstance(token.formatted_value, str)
        assert not isinstance(token.formatted_value, (int, Fraction))
        assert isinstance(token.label, str)
        assert isinstance(token.register, str)


def _anomaly_flag(*, fired: bool = True, severity: str = "HIGH") -> AnomalyFlag:
    threshold = AnomalyThreshold(
        metric="MARGIN_PCT",
        method="Z_SCORE",
        min_series_length=8,
        config_version=1,
        z_score_threshold=Fraction(5, 2),
    )
    return AnomalyFlag(
        id=uuid4(),
        tenant_id=uuid4(),
        metric="MARGIN_PCT",
        target_ref="SKU-1",
        period=_AS_OF,
        method="Z_SCORE",
        decorates_engine_result_ref=uuid4(),
        source_engine_result_refs=(),
        score=Fraction(31, 10),
        threshold_used=threshold,
        fired=fired,
        severity=severity,
        data_confidence="VERIFIED",
        series_length=10,
        min_series_length_required=8,
        config_version=1,
        formula_version="anomaly.v1",
        as_of_date=_AS_OF,
        computed_at=_COMPUTED_AT,
    )


def test_narrate_anomaly_check_never_builds_a_token_with_a_raw_numeric_formatted_value(
    monkeypatch,
) -> None:
    outcome = AnomalyCheckOutcome(
        target_ref="SKU-1",
        metric="MARGIN_PCT",
        series_length=10,
        methods=(
            AnomalyMethodOutcome(method="Z_SCORE", flag=_anomaly_flag()),
            AnomalyMethodOutcome(method="PERCENTILE_THRESHOLD", flag=_anomaly_flag(fired=False, severity="NOT_ANOMALOUS")),
            AnomalyMethodOutcome(method="PERIOD_OVER_PERIOD_DELTA", flag=_anomaly_flag()),
        ),
    )
    provider = _StubProvider()

    tokens = _captured_tokens(
        monkeypatch,
        lambda: narrate_anomaly_check(provider, model=_MODEL, outcome=outcome),
    )

    assert len(tokens) == 3
    for token in tokens:
        assert isinstance(token.formatted_value, str)
        assert not isinstance(token.formatted_value, (int, Fraction))


# ---------------------------------------------------------------------------------------
# 4. A leak finding at UNAVAILABLE-equivalent state is narrated as unavailable, never
#    defaulted to a formatted zero or a fabricated severity band.
# ---------------------------------------------------------------------------------------


def test_leak_finding_with_unavailable_severity_is_narrated_as_unavailable_not_zero(
    monkeypatch,
) -> None:
    outcome = _leak_shield_outcome(
        findings=[_real_finding(amount_paise=50_00, severity="UNAVAILABLE")],
        aggregate_amount_paise=50_00,
    )
    provider = _StubProvider()

    tokens = _captured_tokens(
        monkeypatch,
        lambda: narrate_leak_findings(provider, model=_MODEL, outcome=outcome),
    )

    finding_tokens = [t for t in tokens if t.label == "FEE_OVERCHARGE"]
    assert len(finding_tokens) == 1
    token = finding_tokens[0]
    assert "UNAVAILABLE" in token.formatted_value
    # the real amount (₹50.00) is still stated — never suppressed and never replaced by a
    # fabricated zero just because severity is unavailable.
    assert "50.00" in token.formatted_value
    assert "not enough configured data" in token.formatted_value
