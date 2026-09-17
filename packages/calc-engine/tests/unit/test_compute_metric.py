"""compute_metric.py — MetricResult.manual_adjustment_set (§9) must actually be stamped from
the active_adjustment_ids the caller passed in, not left empty. This was a real gap: the
field didn't exist on MetricResult at all, so metric_result_repo.save() had nothing honest to
write and stored '[]' unconditionally, silently discarding provenance §9 requires every
stored metric to carry.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import uuid4

from calc_engine.api.compute_metric import compute_contribution_profit, compute_net_realized_revenue
from calc_engine.types import RecognitionState, Unavailable, ZERO

from tests.fixtures.canonical_builder import CanonicalDataBuilder


def test_nrr_stamps_the_active_adjustment_ids_it_was_given(empty_bearer_resolver):
    line = CanonicalDataBuilder().gross(100_000).build()
    adjustment_id = uuid4()

    result = compute_net_realized_revenue(
        [line],
        bearer_resolver=empty_bearer_resolver,
        recognition_state=RecognitionState.RECOGNISED,
        ingestion_run_ids=[uuid4()],
        adapter_versions=["meesho.sales.v1:1"],
        active_adjustment_ids=[adjustment_id],
        computed_at=datetime(2026, 9, 17, tzinfo=timezone.utc),
        as_of_date=date(2026, 9, 17),
    )

    assert result.manual_adjustment_set == (str(adjustment_id),)


def test_nrr_unavailable_still_stamps_the_active_adjustment_ids(empty_bearer_resolver):
    unresolved_line = CanonicalDataBuilder().gross(100_000).unresolved_cancellation().build()
    adjustment_id = uuid4()

    result = compute_net_realized_revenue(
        [unresolved_line],
        bearer_resolver=empty_bearer_resolver,
        recognition_state=RecognitionState.RECOGNISED,
        ingestion_run_ids=[uuid4()],
        adapter_versions=["amazon.mtr.v1:1"],
        active_adjustment_ids=[adjustment_id],
        computed_at=datetime(2026, 9, 17, tzinfo=timezone.utc),
        as_of_date=date(2026, 9, 17),
    )

    assert not result.is_available
    assert result.manual_adjustment_set == (str(adjustment_id),)


def test_contribution_profit_stamps_its_own_active_adjustment_ids_not_nrrs(empty_bearer_resolver):
    """ContributionProfit can incorporate adjustments (e.g. cogs_per_unit) that NetRealizedRevenue
    never saw — its manual_adjustment_set must reflect its own scope, not silently inherit NRR's."""
    line = CanonicalDataBuilder().gross(100_000).build()
    nrr_adjustment_id = uuid4()
    cogs_adjustment_id = uuid4()

    nrr_result = compute_net_realized_revenue(
        [line],
        bearer_resolver=empty_bearer_resolver,
        recognition_state=RecognitionState.RECOGNISED,
        ingestion_run_ids=[uuid4()],
        adapter_versions=["meesho.sales.v1:1"],
        active_adjustment_ids=[nrr_adjustment_id],
        computed_at=datetime(2026, 9, 17, tzinfo=timezone.utc),
        as_of_date=date(2026, 9, 17),
    )

    cp_result = compute_contribution_profit(
        nrr_result,
        cogs=ZERO,
        marketplace_fees=ZERO,
        shipping_logistics=ZERO,
        advertising_costs=ZERO,
        return_rto_losses=ZERO,
        other_allocated_costs=ZERO,
        ingestion_run_ids=[uuid4()],
        adapter_versions=["meesho.sales.v1:1"],
        active_adjustment_ids=[nrr_adjustment_id, cogs_adjustment_id],
        computed_at=datetime(2026, 9, 17, tzinfo=timezone.utc),
        as_of_date=date(2026, 9, 17),
    )

    assert cp_result.manual_adjustment_set == (str(nrr_adjustment_id), str(cogs_adjustment_id))


def test_contribution_profit_unavailable_from_upstream_nrr_still_stamps_its_own_ids(empty_bearer_resolver):
    unresolved_line = CanonicalDataBuilder().gross(100_000).unresolved_cancellation().build()
    adjustment_id = uuid4()

    nrr_result = compute_net_realized_revenue(
        [unresolved_line],
        bearer_resolver=empty_bearer_resolver,
        recognition_state=RecognitionState.RECOGNISED,
        ingestion_run_ids=[uuid4()],
        adapter_versions=["amazon.mtr.v1:1"],
        active_adjustment_ids=[],
        computed_at=datetime(2026, 9, 17, tzinfo=timezone.utc),
        as_of_date=date(2026, 9, 17),
    )
    assert not nrr_result.is_available

    cp_result = compute_contribution_profit(
        nrr_result,
        cogs=ZERO,
        marketplace_fees=ZERO,
        shipping_logistics=ZERO,
        advertising_costs=ZERO,
        return_rto_losses=ZERO,
        other_allocated_costs=ZERO,
        ingestion_run_ids=[uuid4()],
        adapter_versions=["amazon.mtr.v1:1"],
        active_adjustment_ids=[adjustment_id],
        computed_at=datetime(2026, 9, 17, tzinfo=timezone.utc),
        as_of_date=date(2026, 9, 17),
    )

    assert not cp_result.is_available
    assert cp_result.manual_adjustment_set == (str(adjustment_id),)
