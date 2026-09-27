"""`backend.services.cfo_actions.compute_pricing_curve` — end-to-end at the unit level, real
engine functions (`compute_margin_curve`, `resolve_fee_or_unavailable`). The two DB-touching
calls this composition makes (`config_repo.resolve_fee_reference`, and
`cfo.repositories.agent_data_request_repo.insert` imported as `insert_data_request`) are
monkeypatched — no live Postgres in this session, mirroring `test_cfo_actions_pnl.py`'s own
`_stub_persistence`/`insert_data_request` monkeypatch conventions exactly.

Covers: valid inputs produce one `MetricResult` per candidate price, each carrying an
`engineResultRef`/`metric_code == "MARGIN_AT_PRICE"` (AC12); missing COGS triggers exactly one
`agent_data_request` (E14, mirroring E2); an unresolvable fee_reference (config_repo returns
`None`) also triggers exactly one `agent_data_request` — the new case beyond what P&L already
tests; the curve is never collapsed to a single "optimal price" (AC12 guardrail: output length
always matches the candidate-price count); and a no-arithmetic-in-this-test-file check
(this repo's own AST-scan lint, `test_no_arithmetic_lint.py`, already covers `cfo_actions.py`/
`api/v1/cfo.py`/`ceo_hub.py` broadly — no change needed there, confirmed by inspection).
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from fractions import Fraction
from uuid import uuid4

import pytest
from calc_engine.types import Paise, Unavailable

import backend.services.cfo_actions as cfo_actions_module
from backend.services.cfo_actions import PricingCurveRequest, compute_pricing_curve

_AS_OF = date(2026, 9, 23)

_FEE_ROW = {
    "rate_pct": Decimal("10.00"),
    "rate_low_pct": None,
    "rate_high_pct": None,
    "source": "PLATFORM_PUBLISHED",
    "confidence": "PROVISIONAL",
    "version": 1,
}


def _base_request(
    *,
    candidate_prices=(Paise(500_00), Paise(550_00), Paise(600_00)),
    cogs: Paise | Unavailable = Paise(200_00),
    return_rto_losses: Paise | Unavailable = Paise(0),
) -> PricingCurveRequest:
    return PricingCurveRequest(
        sku="SKU-1",
        candidate_prices=list(candidate_prices),
        basis="EXCLUSIVE",
        gst_rate=Fraction(18),
        marketplace="MEESHO",
        category="APPAREL",
        fee_type="COMMISSION",
        as_of_date=_AS_OF,
        cogs=cogs,
        shipping_logistics=Paise(30_00),
        advertising_costs=Paise(20_00),
        return_rto_losses=return_rto_losses,
        other_allocated_costs=Paise(0),
        ingestion_run_ids=["run-1"],
        adapter_versions=["meesho.v1"],
        active_adjustment_ids=[],
        requested_by=uuid4(),
        computed_at=datetime(2026, 9, 23, tzinfo=timezone.utc),
    )


@pytest.fixture(autouse=True)
def _stub_persistence(monkeypatch: pytest.MonkeyPatch) -> None:
    """`metric_result_repo.save` opens a real DB connection — no live Postgres in this
    session, so persistence is stubbed to a no-op, exactly as `test_cfo_actions_pnl.py`'s own
    `_stub_persistence` fixture does."""
    monkeypatch.setattr(cfo_actions_module.metric_result_repo, "save", lambda *a, **k: None)


@pytest.fixture(autouse=True)
def _stub_fee_reference(monkeypatch: pytest.MonkeyPatch) -> None:
    """`config_repo.resolve_fee_reference` opens a real DB connection — stubbed to return a
    resolvable fee row by default; individual tests override this to simulate a miss."""
    monkeypatch.setattr(cfo_actions_module.config_repo, "resolve_fee_reference", lambda *a, **k: dict(_FEE_ROW))


def test_valid_inputs_yield_one_metric_result_per_candidate_price_with_provenance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _base_request()

    captured_requests: list[dict[str, object]] = []
    monkeypatch.setattr(
        cfo_actions_module,
        "insert_data_request",
        lambda tenant_id, **kwargs: captured_requests.append(kwargs) or uuid4(),
    )

    outcome = compute_pricing_curve(uuid4(), request)

    assert len(outcome.curve) == len(request.candidate_prices)
    for result in outcome.curve:
        assert result.id is not None  # engine_result_ref
        assert result.metric_code == "MARGIN_AT_PRICE"
        assert result.is_available is True
        assert result.value_paise is not None
    assert outcome.data_request_id is None
    assert captured_requests == []


def test_missing_cogs_yields_data_request_and_unavailable_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    request = _base_request(cogs=Unavailable(reason="no cost_history_row for this SKU", missing_inputs=("cogs_per_unit",)))

    captured_requests: list[dict[str, object]] = []
    monkeypatch.setattr(
        cfo_actions_module,
        "insert_data_request",
        lambda tenant_id, **kwargs: captured_requests.append(kwargs) or uuid4(),
    )

    outcome = compute_pricing_curve(uuid4(), request)

    assert len(outcome.curve) == len(request.candidate_prices)
    for result in outcome.curve:
        assert result.is_available is False
        assert result.value_paise is None
    assert outcome.data_request_id is not None
    assert len(captured_requests) == 1
    assert captured_requests[0]["requested_field"] == "cogs_per_unit"
    assert captured_requests[0]["blocking_metric"] == "MARGIN_AT_PRICE"


def test_unresolvable_fee_reference_yields_data_request(monkeypatch: pytest.MonkeyPatch) -> None:
    """The new case beyond what P&L already tests: `config_repo.resolve_fee_reference`
    returning `None` (no row covers this marketplace/category/fee_type) must be refused with a
    data request, never an assumed fee rate."""
    monkeypatch.setattr(cfo_actions_module.config_repo, "resolve_fee_reference", lambda *a, **k: None)

    request = _base_request()

    captured_requests: list[dict[str, object]] = []
    monkeypatch.setattr(
        cfo_actions_module,
        "insert_data_request",
        lambda tenant_id, **kwargs: captured_requests.append(kwargs) or uuid4(),
    )

    outcome = compute_pricing_curve(uuid4(), request)

    assert len(outcome.curve) == len(request.candidate_prices)
    for result in outcome.curve:
        assert result.is_available is False
    assert outcome.data_request_id is not None
    assert len(captured_requests) == 1
    assert captured_requests[0]["requested_field"] == "fee_reference"
    assert captured_requests[0]["blocking_metric"] == "MARGIN_AT_PRICE"


def test_ac12_curve_never_collapses_to_a_single_optimal_price(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC12 guardrail: whatever the candidate-price count, the outcome always carries exactly
    that many rows — never reduced to one 'best' price."""
    monkeypatch.setattr(cfo_actions_module, "insert_data_request", lambda tenant_id, **kwargs: uuid4())

    for candidate_prices in (
        (Paise(500_00),),
        (Paise(500_00), Paise(550_00)),
        (Paise(500_00), Paise(550_00), Paise(600_00), Paise(650_00), Paise(700_00)),
    ):
        request = _base_request(candidate_prices=candidate_prices)
        outcome = compute_pricing_curve(uuid4(), request)
        assert len(outcome.curve) == len(candidate_prices)
        # Every row is independently addressable by its own calculation_basis (which candidate
        # price it is for) — never merged/summarised into one row.
        bases = {r.calculation_basis for r in outcome.curve}
        assert len(bases) == len(candidate_prices)
