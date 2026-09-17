"""AC1: "Identical inputs produce byte-identical outputs across runs and machines."

Property test, not a single fixed example: Hypothesis generates a randomised set of
CanonicalLines (varying gross amount, fee, discount, quantity), and `compute_net_realized_revenue`
/`compute_contribution_profit` are each called twice with byte-identical inputs — same lines,
same bearer_resolver, same ingestion_run_ids/adapter_versions/active_adjustment_ids, same
computed_at, same as_of_date. Every field of the two results must match except `id`
(`MetricResult.id` is a freshly-minted `engine_result_ref`, §9.1 — a reference is deliberately
unique per computation run; it is not part of what AC1 requires to be identical).

Previously only indirectly covered: test_versioning.py proves canonical_data_version is
order-independent, and test_rounding.py's Hypothesis test proves largest_remainder_allocate's
sum invariant — but nothing called a full compute_metric function twice and compared results.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timezone
from uuid import uuid4

from hypothesis import given
from hypothesis import strategies as st

from calc_engine.api.compute_metric import compute_contribution_profit, compute_net_realized_revenue
from calc_engine.types import RecognitionState, ZERO

from tests.fixtures.canonical_builder import CanonicalDataBuilder


@given(
    gross_amount=st.integers(min_value=100, max_value=10_000_000),
    discount_amount=st.integers(min_value=0, max_value=1_000_000),
    fee_amount=st.integers(min_value=0, max_value=1_000_000),
)
def test_net_realized_revenue_is_deterministic_across_identical_calls(gross_amount, discount_amount, fee_amount):
    line = (
        CanonicalDataBuilder()
        .gross(gross_amount)
        .discount("SELLER_DISCOUNT", discount_amount)
        .fee("PLATFORM_FEE", fee_amount)
        .build()
    )
    ingestion_run_ids = [uuid4()]
    adapter_versions = ["meesho.sales.v1:1"]
    active_adjustment_ids = [uuid4()]
    computed_at = datetime(2026, 9, 17, 12, 0, 0, tzinfo=timezone.utc)
    as_of_date = date(2026, 9, 17)

    def bearer_resolver(marketplace, component_code):
        from calc_engine.types import Bearer

        return Bearer.SELLER

    kwargs = dict(
        lines=[line],
        bearer_resolver=bearer_resolver,
        recognition_state=RecognitionState.RECOGNISED,
        ingestion_run_ids=ingestion_run_ids,
        adapter_versions=adapter_versions,
        active_adjustment_ids=active_adjustment_ids,
        computed_at=computed_at,
        as_of_date=as_of_date,
    )

    result_a = compute_net_realized_revenue(**kwargs)
    result_b = compute_net_realized_revenue(**kwargs)

    # id is a freshly-minted engine_result_ref per call (§9.1) — deliberately not identical.
    assert result_a.id != result_b.id
    assert replace(result_a, id=result_b.id) == result_b


@given(
    gross_amount=st.integers(min_value=100, max_value=10_000_000),
    cogs_amount=st.integers(min_value=0, max_value=1_000_000),
)
def test_contribution_profit_is_deterministic_across_identical_calls(gross_amount, cogs_amount):
    line = CanonicalDataBuilder().gross(gross_amount).build()

    def bearer_resolver(marketplace, component_code):
        from calc_engine.types import Bearer

        return Bearer.SELLER

    computed_at = datetime(2026, 9, 17, 12, 0, 0, tzinfo=timezone.utc)
    as_of_date = date(2026, 9, 17)

    nrr_kwargs = dict(
        lines=[line],
        bearer_resolver=bearer_resolver,
        recognition_state=RecognitionState.RECOGNISED,
        ingestion_run_ids=[uuid4()],
        adapter_versions=["meesho.sales.v1:1"],
        active_adjustment_ids=[],
        computed_at=computed_at,
        as_of_date=as_of_date,
    )
    nrr_result = compute_net_realized_revenue(**nrr_kwargs)

    from calc_engine.types import Paise

    cp_kwargs = dict(
        nrr_result=nrr_result,
        cogs=Paise(cogs_amount),
        marketplace_fees=ZERO,
        shipping_logistics=ZERO,
        advertising_costs=ZERO,
        return_rto_losses=ZERO,
        other_allocated_costs=ZERO,
        ingestion_run_ids=[uuid4()],
        adapter_versions=["meesho.sales.v1:1"],
        active_adjustment_ids=[],
        computed_at=computed_at,
        as_of_date=as_of_date,
    )

    result_a = compute_contribution_profit(**cp_kwargs)
    result_b = compute_contribution_profit(**cp_kwargs)

    assert result_a.id != result_b.id
    assert replace(result_a, id=result_b.id) == result_b
