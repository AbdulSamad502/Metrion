"""compute_settlement_lag_days — anomaly-detection.md §6.1/§6.6, closing §10 P1 ("no
period-level aggregate function anywhere in packages/calc-engine")."""

from __future__ import annotations

from datetime import date, datetime, timezone
from fractions import Fraction
from uuid import uuid4

from calc_engine.api.compute_metric import compute_settlement_lag_days
from calc_engine.formulas.settlement_lag import SettlementLagAggregate
from calc_engine.types import Confidence, Unavailable

_AS_OF = date(2026, 9, 25)
_COMPUTED_AT = datetime(2026, 9, 25, tzinfo=timezone.utc)


def test_happy_path_mints_a_value_fraction_never_value_paise():
    aggregate = SettlementLagAggregate(
        mean_lag_days=Fraction(15),
        pair_count=3,
        confidences=(Confidence.VERIFIED, Confidence.VERIFIED, Confidence.VERIFIED),
        dates_missing_count=0,
        negative_lag_excluded_count=0,
    )
    run_id = uuid4()
    result = compute_settlement_lag_days(
        aggregate, reconciliation_run_id=run_id, computed_at=_COMPUTED_AT, as_of_date=_AS_OF
    )

    assert result.metric_code == "SETTLEMENT_LAG_DAYS"
    assert result.is_available is True
    assert result.value_paise is None
    assert result.value_fraction == Fraction(15)
    assert result.confidence == "VERIFIED"
    assert result.formula_version == "SETTLEMENT_LAG_DAYS.v1"
    assert result.input_refs == (run_id,)
    assert result.id is not None


def test_unavailable_on_zero_matched_pairs_never_a_fabricated_zero_day_lag():
    run_id = uuid4()
    result = compute_settlement_lag_days(
        Unavailable(reason="no pairs"),
        reconciliation_run_id=run_id,
        computed_at=_COMPUTED_AT,
        as_of_date=_AS_OF,
    )

    assert result.is_available is False
    assert result.value_paise is None
    assert result.value_fraction is None
    assert result.unavailable_reason == "no pairs"
    assert result.id is not None  # still a real, minted engine_result_ref


def test_confidence_derived_via_combine_confidence_weakest_wins():
    aggregate = SettlementLagAggregate(
        mean_lag_days=Fraction(10),
        pair_count=2,
        confidences=(Confidence.VERIFIED, Confidence.PROVISIONAL),
        dates_missing_count=0,
        negative_lag_excluded_count=0,
    )
    result = compute_settlement_lag_days(
        aggregate, reconciliation_run_id=uuid4(), computed_at=_COMPUTED_AT, as_of_date=_AS_OF
    )
    assert result.confidence == "PROVISIONAL"


def test_confidence_all_provisional_stays_provisional_amazon_flipkart_cap_shape():
    """Structurally proves the shape of the Amazon/Flipkart PROVISIONAL join-key cap flowing
    through: every contributing pair's confidence already PROVISIONAL (as reconcile() would
    cap it for a non-Meesho marketplace) -> the resulting SETTLEMENT_LAG_DAYS MetricResult
    itself never presents better than PROVISIONAL."""
    aggregate = SettlementLagAggregate(
        mean_lag_days=Fraction(20),
        pair_count=2,
        confidences=(Confidence.PROVISIONAL, Confidence.PROVISIONAL),
        dates_missing_count=0,
        negative_lag_excluded_count=0,
    )
    result = compute_settlement_lag_days(
        aggregate, reconciliation_run_id=uuid4(), computed_at=_COMPUTED_AT, as_of_date=_AS_OF
    )
    assert result.confidence == "PROVISIONAL"


def test_confidence_all_verified_stays_verified_meesho_shape():
    aggregate = SettlementLagAggregate(
        mean_lag_days=Fraction(5),
        pair_count=1,
        confidences=(Confidence.VERIFIED,),
        dates_missing_count=0,
        negative_lag_excluded_count=0,
    )
    result = compute_settlement_lag_days(
        aggregate, reconciliation_run_id=uuid4(), computed_at=_COMPUTED_AT, as_of_date=_AS_OF
    )
    assert result.confidence == "VERIFIED"


def test_calculation_basis_discloses_negative_lag_and_missing_date_counts():
    aggregate = SettlementLagAggregate(
        mean_lag_days=Fraction(15),
        pair_count=1,
        confidences=(Confidence.VERIFIED,),
        dates_missing_count=2,
        negative_lag_excluded_count=3,
    )
    result = compute_settlement_lag_days(
        aggregate, reconciliation_run_id=uuid4(), computed_at=_COMPUTED_AT, as_of_date=_AS_OF
    )
    assert "3 pair(s) excluded for a negative lag" in result.calculation_basis
    assert "2 pair(s) excluded for a missing date" in result.calculation_basis
    assert "MEAN" in result.calculation_basis


def test_canonical_data_version_is_non_canonical_mirroring_reconcile_precedent():
    aggregate = SettlementLagAggregate(
        mean_lag_days=Fraction(1),
        pair_count=1,
        confidences=(Confidence.VERIFIED,),
        dates_missing_count=0,
        negative_lag_excluded_count=0,
    )
    result = compute_settlement_lag_days(
        aggregate, reconciliation_run_id=uuid4(), computed_at=_COMPUTED_AT, as_of_date=_AS_OF
    )
    assert result.canonical_data_version == "non-canonical"
