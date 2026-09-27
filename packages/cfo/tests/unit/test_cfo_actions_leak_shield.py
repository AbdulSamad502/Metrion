"""`backend.services.cfo_actions.run_leak_shield_reconciliation` — D5, composition-layer unit
test. `calc_engine.api.reconcile.reconcile` (D4, real, tested against real Meesho data
elsewhere) is monkeypatched here to return a constructed `ReconcileResult` — this file does
NOT call the real thing, it only exercises the composition logic (persistence wiring,
AMBIGUOUS_MATCH filtering, LeakExceptionInput assembly, leak_finding inserts) against a fixed,
known reconciliation outcome. `reconciliation_repo.exceptions_for_run`, `metric_result_repo.
save`, `config_repo.severity_config_rows` and `leak_finding_repo.insert` are all monkeypatched
too — no live Postgres in this session, mirroring `test_cfo_actions_pricing.py`'s own
monkeypatch conventions.

Covers: a `VARIANCE_EXCEEDS_TOLERANCE` exception against a FEE component with a positive
amount produces `FEE_OVERCHARGE`; the same outcome with a negative amount (settlement lower)
produces `SHORT_SETTLEMENT`; `ORPHAN_SETTLEMENT` -> `UNEXPECTED_DEDUCTION`;
`DUPLICATE_SETTLEMENT` -> `DUPLICATE_DEDUCTION`; `UNSETTLED_BEYOND_LAG` -> `MISSING_SETTLEMENT`;
and — critically — a run whose exceptions include an `AMBIGUOUS_MATCH` row produces ZERO
`leak_finding` inserts for that row, is counted in `ambiguous_match_count`, and never crashes
or fabricates a category. Also asserts `is_return_linked` is never derived from anything
(Decision A) — every `VARIANCE_EXCEEDS_TOLERANCE` finding here lands in
`FEE_OVERCHARGE`/`SHORT_SETTLEMENT`, never `RETURN_NOT_CREDITED`, regardless of fixture shape.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import UUID, uuid4

import pytest
from calc_engine.api.compute_metric import MetricResult
from calc_engine.api.reconcile import ReconcileResult
from calc_engine.types import RecognitionState

import backend.services.cfo_actions as cfo_actions_module
from backend.services.cfo_actions import run_leak_shield_reconciliation

_AS_OF = date(2026, 9, 25)
_PERIOD_START = date(2026, 9, 1)
_PERIOD_END = date(2026, 9, 30)
_COMPUTED_AT = datetime(2026, 9, 25, tzinfo=timezone.utc)


def _metric_result(*, exception_id: UUID, extra_refs: tuple = (), value_paise: int) -> MetricResult:
    return MetricResult(
        id=uuid4(),
        metric_code="LEAK_EXCEPTION_AMOUNT",
        value_paise=value_paise,
        recognition_state=RecognitionState.RECOGNISED,
        confidence="DERIVED",
        calculation_basis="LeakExceptionAmount(test fixture)",
        formula_version="reconcile.v1",
        canonical_data_version="non-canonical",
        as_of_date=_AS_OF,
        input_refs=(exception_id,) + extra_refs,
        exclusions=(),
        computed_at=_COMPUTED_AT,
        is_available=True,
    )


def _aggregate_metric_result(*, input_refs: tuple, total: int) -> MetricResult:
    return MetricResult(
        id=uuid4(),
        metric_code="LEAK_TOTAL",
        value_paise=total,
        recognition_state=RecognitionState.RECOGNISED,
        confidence="DERIVED",
        calculation_basis="LeakAggregate(test fixture)",
        formula_version="reconcile.v1",
        canonical_data_version="non-canonical",
        as_of_date=_AS_OF,
        input_refs=input_refs,
        exclusions=(),
        computed_at=_COMPUTED_AT,
        is_available=True,
    )


def _exception_row(
    *,
    exception_id: UUID,
    exception_type: str,
    amount_paise: int,
    component_code: str | None = None,
    marketplace: str = "MEESHO",
    confidence: str = "DERIVED",
) -> dict[str, object]:
    return {
        "id": exception_id,
        "tenant_id": uuid4(),
        "reconciliation_run_id": uuid4(),
        "reconciliation_match_id": None,
        "exception_type": exception_type,
        "sales_line_id": None,
        "settlement_line_id": None,
        "candidate_sales_line_ids": None,
        "marketplace": marketplace,
        "component_code": component_code,
        "amount_paise": amount_paise,
        "confidence": confidence,
        "formula_version": "reconcile.v1",
        "computed_at": _COMPUTED_AT,
    }


@pytest.fixture(autouse=True)
def _stub_persistence(monkeypatch: pytest.MonkeyPatch) -> None:
    """`metric_result_repo.save` / `leak_finding_repo.insert` open a real DB connection — no
    live Postgres in this session."""
    monkeypatch.setattr(cfo_actions_module.metric_result_repo, "save", lambda *a, **k: None)
    monkeypatch.setattr(
        cfo_actions_module.config_repo, "severity_config_rows", lambda *a, **k: []
    )


def _run_with_exceptions(
    monkeypatch: pytest.MonkeyPatch, rows: list[dict[str, object]], metric_results: list[MetricResult]
) -> tuple[list[dict[str, object]], object]:
    """Wires `reconcile()` and `reconciliation_repo.exceptions_for_run` to the given fixtures,
    captures every `leak_finding_repo.insert` call, and returns (captured_inserts, outcome)."""
    run_id = uuid4()
    result = ReconcileResult(
        reconciliation_run_id=run_id,
        match_count=1,
        exception_count=len(rows),
        dates_missing_count=0,
        amount_unavailable_count=0,
        exception_metric_results=tuple(metric_results),
        aggregate_metric_result=_aggregate_metric_result(
            input_refs=tuple(mr.id for mr in metric_results),
            total=sum(r["amount_paise"] for r in rows),
        ),
    )
    monkeypatch.setattr(cfo_actions_module, "reconcile", lambda *a, **k: result)
    monkeypatch.setattr(
        cfo_actions_module.reconciliation_repo, "exceptions_for_run", lambda *a, **k: rows
    )
    # This checkpoint's SETTLEMENT_LAG_DAYS wiring reads real reconciliation_match rows via
    # reconciliation_repo.settlement_lag_pairs_for_run immediately after LEAK_TOTAL is
    # persisted — stubbed here to keep this file's "no live Postgres in this session"
    # convention (module docstring) intact; an empty list is the honest "no matched pairs
    # seeded by this fixture" case, which compute_settlement_lag_days reports as UNAVAILABLE.
    monkeypatch.setattr(
        cfo_actions_module.reconciliation_repo, "settlement_lag_pairs_for_run", lambda *a, **k: []
    )

    captured: list[dict[str, object]] = []

    def _fake_insert(tenant_id, **kwargs):
        captured.append(kwargs)
        return uuid4()

    monkeypatch.setattr(cfo_actions_module.leak_finding_repo, "insert", _fake_insert)

    outcome = run_leak_shield_reconciliation(
        uuid4(),
        marketplace="MEESHO",
        period_start=_PERIOD_START,
        period_end=_PERIOD_END,
        as_of_date=_AS_OF,
    )
    return captured, outcome


def test_variance_positive_fee_component_produces_fee_overcharge(monkeypatch: pytest.MonkeyPatch) -> None:
    exception_id = uuid4()
    row = _exception_row(
        exception_id=exception_id,
        exception_type="VARIANCE_EXCEEDS_TOLERANCE",
        amount_paise=500,  # settlement > invoice
        component_code="COMMISSION",  # FEE, per COMPONENT_KIND_BY_CODE
    )
    mr = _metric_result(exception_id=exception_id, value_paise=500)

    captured, outcome = _run_with_exceptions(monkeypatch, [row], [mr])

    assert len(captured) == 1
    assert captured[0]["leak_category"] == "FEE_OVERCHARGE"
    assert outcome.ambiguous_match_count == 0


def test_variance_negative_produces_short_settlement_never_return_not_credited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exception_id = uuid4()
    row = _exception_row(
        exception_id=exception_id,
        exception_type="VARIANCE_EXCEEDS_TOLERANCE",
        amount_paise=-500,  # settlement < invoice
        component_code="COMMISSION",
    )
    mr = _metric_result(exception_id=exception_id, value_paise=-500)

    captured, _ = _run_with_exceptions(monkeypatch, [row], [mr])

    assert len(captured) == 1
    assert captured[0]["leak_category"] == "SHORT_SETTLEMENT"
    assert captured[0]["leak_category"] != "RETURN_NOT_CREDITED"


def test_orphan_settlement_produces_unexpected_deduction(monkeypatch: pytest.MonkeyPatch) -> None:
    exception_id = uuid4()
    row = _exception_row(exception_id=exception_id, exception_type="ORPHAN_SETTLEMENT", amount_paise=1200)
    mr = _metric_result(exception_id=exception_id, value_paise=1200)

    captured, _ = _run_with_exceptions(monkeypatch, [row], [mr])

    assert len(captured) == 1
    assert captured[0]["leak_category"] == "UNEXPECTED_DEDUCTION"


def test_duplicate_settlement_produces_duplicate_deduction(monkeypatch: pytest.MonkeyPatch) -> None:
    exception_id = uuid4()
    row = _exception_row(exception_id=exception_id, exception_type="DUPLICATE_SETTLEMENT", amount_paise=800)
    mr = _metric_result(exception_id=exception_id, value_paise=800)

    captured, _ = _run_with_exceptions(monkeypatch, [row], [mr])

    assert len(captured) == 1
    assert captured[0]["leak_category"] == "DUPLICATE_DEDUCTION"


def test_unsettled_beyond_lag_produces_missing_settlement(monkeypatch: pytest.MonkeyPatch) -> None:
    exception_id = uuid4()
    row = _exception_row(exception_id=exception_id, exception_type="UNSETTLED_BEYOND_LAG", amount_paise=2500)
    mr = _metric_result(exception_id=exception_id, value_paise=2500)

    captured, _ = _run_with_exceptions(monkeypatch, [row], [mr])

    assert len(captured) == 1
    assert captured[0]["leak_category"] == "MISSING_SETTLEMENT"


def test_ambiguous_match_never_becomes_a_leak_finding(monkeypatch: pytest.MonkeyPatch) -> None:
    """Decision B: AMBIGUOUS_MATCH is not a ReconciliationOutcome value at all — it must be
    filtered before ever reaching classify_and_rank_leaks, never crash, never a fabricated
    category, and counted separately."""
    ambiguous_id = uuid4()
    real_id = uuid4()
    ambiguous_row = _exception_row(
        exception_id=ambiguous_id, exception_type="AMBIGUOUS_MATCH", amount_paise=999
    )
    real_row = _exception_row(
        exception_id=real_id, exception_type="ORPHAN_SETTLEMENT", amount_paise=300
    )
    ambiguous_mr = _metric_result(exception_id=ambiguous_id, value_paise=999)
    real_mr = _metric_result(exception_id=real_id, value_paise=300)

    captured, outcome = _run_with_exceptions(
        monkeypatch, [ambiguous_row, real_row], [ambiguous_mr, real_mr]
    )

    # Only the real, non-ambiguous exception becomes a leak_finding.
    assert len(captured) == 1
    assert captured[0]["leak_category"] == "UNEXPECTED_DEDUCTION"
    assert outcome.ambiguous_match_count == 1
    assert outcome.exception_count == 2


def test_is_return_linked_never_derived_across_every_variance_finding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Decision A — every VARIANCE_EXCEEDS_TOLERANCE finding in this fixture set lands in
    FEE_OVERCHARGE or SHORT_SETTLEMENT, never RETURN_NOT_CREDITED, regardless of sign/component."""
    rows = []
    metric_results = []
    for amount, component_code in ((100, "COMMISSION"), (-100, "COMMISSION"), (50, None), (-50, None)):
        exception_id = uuid4()
        rows.append(
            _exception_row(
                exception_id=exception_id,
                exception_type="VARIANCE_EXCEEDS_TOLERANCE",
                amount_paise=amount,
                component_code=component_code,
            )
        )
        metric_results.append(_metric_result(exception_id=exception_id, value_paise=amount))

    captured, _ = _run_with_exceptions(monkeypatch, rows, metric_results)

    assert len(captured) == 4
    for entry in captured:
        assert entry["leak_category"] in ("FEE_OVERCHARGE", "SHORT_SETTLEMENT")
        assert entry["leak_category"] != "RETURN_NOT_CREDITED"


def test_aggregate_metric_result_is_persisted_with_its_own_grain(monkeypatch: pytest.MonkeyPatch) -> None:
    """§6.4 rule 5 — the headline leak total is persisted via metric_result_repo.save with
    grain=MARKETPLACE, closing the previously-open engine_result_ref gap."""
    saved_calls: list[dict[str, object]] = []

    def _fake_save(tenant_id, result, **kwargs):
        saved_calls.append({"result": result, **kwargs})

    monkeypatch.setattr(cfo_actions_module.metric_result_repo, "save", _fake_save)

    exception_id = uuid4()
    row = _exception_row(exception_id=exception_id, exception_type="ORPHAN_SETTLEMENT", amount_paise=400)
    mr = _metric_result(exception_id=exception_id, value_paise=400)

    _, outcome = _run_with_exceptions(monkeypatch, [row], [mr])

    # Two MARKETPLACE-grain saves now exist this checkpoint: LEAK_TOTAL (unchanged) and the new
    # SETTLEMENT_LAG_DAYS aggregate (this checkpoint, always UNAVAILABLE here since
    # settlement_lag_pairs_for_run is stubbed to return no pairs) — distinguished by metric_code,
    # not by grain alone, since both share the same MARKETPLACE grain/target_ref shape.
    marketplace_saves = [c for c in saved_calls if c["grain"] == "MARKETPLACE"]
    assert len(marketplace_saves) == 2

    leak_total_saves = [c for c in marketplace_saves if c["result"].metric_code == "LEAK_TOTAL"]
    assert len(leak_total_saves) == 1
    assert leak_total_saves[0]["target_ref"] == "MEESHO"

    settlement_lag_saves = [
        c for c in marketplace_saves if c["result"].metric_code == "SETTLEMENT_LAG_DAYS"
    ]
    assert len(settlement_lag_saves) == 1
    assert settlement_lag_saves[0]["target_ref"] == "MEESHO"
    assert settlement_lag_saves[0]["result"].is_available is False
