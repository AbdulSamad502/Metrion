"""`product_feasibility_estimate_repo` against a real Postgres — proves `save()`/`get()`
actually round-trip a `ProductFeasibilityEstimate` through the real table (RLS included), not
just that the SQL text parses. Mirrors `test_metric_result_repo_list_by_metric_code.py`'s own
seed-via-real-function, read-via-real-function, `two_tenants`/`_clean_engine_tables` pattern.

Closes a real gap found during the PI 2026-10-01 quality pass: `estimate_product_feasibility`
was unit-tested but had no persistence path at all until this repository and PI's
`discovery/feasibility.py` wiring were added.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from fractions import Fraction

import pytest
from calc_engine.api.estimate_product_feasibility import (
    ProspectiveObservationSet,
    estimate_product_feasibility,
)
from calc_engine.repositories import product_feasibility_estimate_repo
from calc_engine.types import Paise, Unavailable

pytestmark = pytest.mark.usefixtures("_clean_engine_tables")

_COMPUTED_AT = datetime(2026, 10, 1, tzinfo=timezone.utc)


def _observation(tenant_id: uuid.UUID) -> ProspectiveObservationSet:
    return ProspectiveObservationSet(
        marketplace="FLIPKART",
        category="running shoes",
        candidate_prices=(Paise(99_900), Paise(149_900)),
        stated_cogs_paise=None,
        budget_paise=Paise(5_000_000),
        as_of_date=_COMPUTED_AT.date(),
        source_url="https://example.com/shoe",
        fetched_at=_COMPUTED_AT,
    )


def test_save_then_get_round_trips_every_field(two_tenants) -> None:
    tenant_a, _ = two_tenants
    estimate = estimate_product_feasibility(
        _observation(tenant_a),
        fee_reference=Unavailable(reason="no fee_reference row covers this"),
        tenant_id=tenant_a,
        computed_at=_COMPUTED_AT,
    )

    saved_id = product_feasibility_estimate_repo.save(tenant_a, estimate)
    assert saved_id == estimate.id

    row = product_feasibility_estimate_repo.get(tenant_a, estimate.id)
    assert row is not None
    assert row["low_paise"] == estimate.low_paise.value
    assert row["high_paise"] == estimate.high_paise.value
    assert row["cogs_basis"] == "UNKNOWN"
    assert row["confidence"] == "DERIVED"
    assert row["formula_version"] == "PRODUCT_FEASIBILITY_ESTIMATE.v1"
    assert isinstance(row["assumptions"], list) and row["assumptions"]
    assert row["observation_ref"]["marketplace"] == "FLIPKART"


def test_get_returns_none_for_another_tenants_row(two_tenants) -> None:
    tenant_a, tenant_b = two_tenants
    estimate = estimate_product_feasibility(
        _observation(tenant_a),
        fee_reference=Unavailable(reason="no fee_reference row covers this"),
        tenant_id=tenant_a,
        computed_at=_COMPUTED_AT,
    )
    product_feasibility_estimate_repo.save(tenant_a, estimate)

    assert product_feasibility_estimate_repo.get(tenant_b, estimate.id) is None


def test_get_returns_none_for_unknown_id(two_tenants) -> None:
    tenant_a, _ = two_tenants
    assert product_feasibility_estimate_repo.get(tenant_a, uuid.uuid4()) is None
