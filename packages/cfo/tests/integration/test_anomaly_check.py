"""`backend.services.cfo_actions.run_anomaly_check` — E3, real Postgres end-to-end.

Seeds a real `CONTRIBUTION_MARGIN_PCT` `metric_result` history for a real tenant by calling
the real `calc_engine.api.compute_metric.compute_contribution_margin_pct` (E3's own new
function) once per period and persisting each result via the real
`calc_engine.repositories.metric_result_repo.save` (real `value_fraction_numerator`/
`value_fraction_denominator` columns, `20260925_0006` migration) — exactly the honest story
E3's own report names: nothing else in this codebase computes/persists this metric yet, so
this test IS that caller.

No `anomaly_detection_config` row is seeded anywhere (this checkpoint's own explicit non-goal:
"ships empty, same as every other config table") — the real, honest outcome for all three
methods is therefore `AnomalyConfigurationGap`, asserted for real against real Postgres, never
mocked. This is itself a real, structured non-flag outcome (§5.2's own three-outcome
vocabulary), not an error.
"""

from __future__ import annotations

import os
import uuid
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import create_engine, text

pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL_APP/DATABASE_URL not set — integration tests need a live Postgres",
)

_AS_OF = date(2026, 9, 25)
_COMPUTED_AT = datetime(2026, 9, 25, tzinfo=timezone.utc)


@pytest.fixture
def migrate_engine():
    engine = create_engine(os.environ["DATABASE_URL"])
    yield engine
    engine.dispose()


@pytest.fixture(autouse=True)
def _clean_metric_result(migrate_engine):
    with migrate_engine.begin() as conn:
        conn.execute(text("DELETE FROM metric_result"))
    yield
    with migrate_engine.begin() as conn:
        conn.execute(text("DELETE FROM metric_result"))


def _seed_margin_pct_history(tenant_id: uuid.UUID, *, target_ref: str, count: int):
    """Real `CONTRIBUTION_PROFIT`/`NET_REALIZED_REVENUE` MetricResults -> real
    `compute_contribution_margin_pct` -> real `metric_result_repo.save`, one period at a time —
    the only path in this codebase today that produces a `CONTRIBUTION_MARGIN_PCT` row."""
    from calc_engine.api.compute_metric import MetricResult, compute_contribution_margin_pct
    from calc_engine.repositories import metric_result_repo
    from calc_engine.types import RecognitionState

    saved_ids = []
    for i in range(count):
        nrr = MetricResult(
            id=uuid.uuid4(),
            metric_code="NET_REALIZED_REVENUE",
            value_paise=100_00,
            recognition_state=RecognitionState.RECOGNISED,
            confidence="VERIFIED",
            calculation_basis="test fixture",
            formula_version="NET_REALIZED_REVENUE.v1",
            canonical_data_version="cdv-1",
            as_of_date=_AS_OF,
            input_refs=(),
            exclusions=(),
            computed_at=_COMPUTED_AT,
            is_available=True,
        )
        cp = MetricResult(
            id=uuid.uuid4(),
            metric_code="CONTRIBUTION_PROFIT",
            value_paise=(20 + i) * 100,
            recognition_state=RecognitionState.RECOGNISED,
            confidence="VERIFIED",
            calculation_basis="test fixture",
            formula_version="CONTRIBUTION_PROFIT.v1",
            canonical_data_version="cdv-1",
            as_of_date=_AS_OF,
            input_refs=(),
            exclusions=(),
            computed_at=_COMPUTED_AT,
            is_available=True,
        )
        margin_pct = compute_contribution_margin_pct(cp, nrr, computed_at=_COMPUTED_AT, as_of_date=_AS_OF)
        assert margin_pct.is_available is True
        assert margin_pct.value_fraction is not None

        month = i + 1
        period_label = f"2026-{month:02d}-01/2026-{month:02d}-28"
        result_id = metric_result_repo.save(
            tenant_id,
            margin_pct,
            grain="SKU",
            target_ref=target_ref,
            period=period_label,
            config_version="TEST.v1",
        )
        saved_ids.append(result_id)
    return saved_ids


def test_real_end_to_end_run_with_no_config_returns_configuration_gap_for_all_three_methods() -> None:
    import backend.services.cfo_actions as cfo_actions_module

    tenant_id = uuid.uuid4()
    saved_ids = _seed_margin_pct_history(tenant_id, target_ref="SKU-1", count=10)

    request = cfo_actions_module.AnomalyCheckRequest(
        target_ref="SKU-1",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 12, 31),
        as_of_date=_AS_OF,
        requested_by=uuid.uuid4(),
    )
    outcome = cfo_actions_module.run_anomaly_check(tenant_id, request)

    assert outcome.target_ref == "SKU-1"
    assert outcome.metric == "MARGIN_PCT"
    assert outcome.series_length == 10  # every real seeded row was found and converted
    assert len(outcome.methods) == 3

    from calc_engine.anomaly.types import AnomalyConfigurationGap

    for method_outcome in outcome.methods:
        assert isinstance(method_outcome.configuration_gap, AnomalyConfigurationGap)
        assert method_outcome.configuration_gap.metric == "MARGIN_PCT"
        assert method_outcome.flag is None
        assert method_outcome.insufficient_history is None
        assert method_outcome.zero_variance is None

    assert len(saved_ids) == 10
    assert len(set(saved_ids)) == 10  # every row got a real, distinct engine_result_ref


def test_real_end_to_end_run_with_seeded_config_produces_a_real_flag_or_non_flag_outcome() -> None:
    """Seeds one real `anomaly_detection_config` row (platform default) for `Z_SCORE` only —
    proving the config-resolved path is real end-to-end against real Postgres too, not just the
    empty-config path above. `PERCENTILE_THRESHOLD`/`PERIOD_OVER_PERIOD_DELTA` remain
    `AnomalyConfigurationGap` (no row seeded for them), proving per-method resolution is real."""
    import backend.services.cfo_actions as cfo_actions_module
    from calc_engine.anomaly.types import AnomalyConfigurationGap, AnomalyFlag

    migrate_url = os.environ["DATABASE_URL"]
    engine = create_engine(migrate_url)
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO anomaly_detection_config
                      (id, tenant_id, metric, method, min_series_length, z_score_threshold,
                       effective_from, version)
                    VALUES
                      (:id, NULL, 'MARGIN_PCT', 'Z_SCORE', 8, 0.001, :effective_from, 1)
                    """
                ),
                {"id": str(uuid.uuid4()), "effective_from": date(2026, 1, 1)},
            )

        tenant_id = uuid.uuid4()
        _seed_margin_pct_history(tenant_id, target_ref="SKU-2", count=10)

        request = cfo_actions_module.AnomalyCheckRequest(
            target_ref="SKU-2",
            period_start=date(2026, 1, 1),
            period_end=date(2026, 12, 31),
            as_of_date=_AS_OF,
            requested_by=uuid.uuid4(),
        )
        outcome = cfo_actions_module.run_anomaly_check(tenant_id, request)

        z_outcome = next(m for m in outcome.methods if m.method == "Z_SCORE")
        # A tiny z_score_threshold (0.001) against a strictly increasing series guarantees the
        # real z_score() function fires — a real AnomalyFlag, not a mock.
        assert isinstance(z_outcome.flag, AnomalyFlag)
        assert z_outcome.flag.metric == "MARGIN_PCT"
        assert z_outcome.flag.method == "Z_SCORE"
        assert z_outcome.flag.config_version == 1

        percentile_outcome = next(m for m in outcome.methods if m.method == "PERCENTILE_THRESHOLD")
        assert isinstance(percentile_outcome.configuration_gap, AnomalyConfigurationGap)
        delta_outcome = next(m for m in outcome.methods if m.method == "PERIOD_OVER_PERIOD_DELTA")
        assert isinstance(delta_outcome.configuration_gap, AnomalyConfigurationGap)
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM anomaly_detection_config"))
        engine.dispose()
