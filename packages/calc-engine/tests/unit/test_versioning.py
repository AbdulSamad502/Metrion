"""canonical_data_version derivation — deterministic-engine.md §4.3. Order-independence proves AC1."""

from __future__ import annotations

from uuid import uuid4

from calc_engine.versioning import derive_canonical_data_version


def test_order_independent_across_shuffled_inputs():
    run_a, run_b, run_c = uuid4(), uuid4(), uuid4()
    adj_a, adj_b = uuid4(), uuid4()

    v1 = derive_canonical_data_version(
        ingestion_run_ids=[run_a, run_b, run_c],
        adapter_versions=["meesho.sales.v1:1", "meesho.settlement.v1:2"],
        active_adjustment_ids=[adj_a, adj_b],
    )
    v2 = derive_canonical_data_version(
        ingestion_run_ids=[run_c, run_a, run_b],  # shuffled
        adapter_versions=["meesho.settlement.v1:2", "meesho.sales.v1:1"],  # shuffled
        active_adjustment_ids=[adj_b, adj_a],  # shuffled
    )
    assert v1 == v2


def test_different_inputs_produce_different_versions():
    run_a, run_b = uuid4(), uuid4()
    v1 = derive_canonical_data_version([run_a], ["meesho.sales.v1:1"], [])
    v2 = derive_canonical_data_version([run_b], ["meesho.sales.v1:1"], [])
    assert v1 != v2
