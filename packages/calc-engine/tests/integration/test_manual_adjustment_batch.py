"""`active_adjustments_for_targets` — the batched form of `active_adjustments_for_target`
(perf: the CFO's canonical assembly issued ~7 queries per sales line; measured 13.45 s for 1,000
lines vs 0.15 s batched). It must return, per (target_ref, field), exactly what the single-target
function returns — same rows, same newest-first order — and never cross tenants."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from calc_engine.repositories import manual_adjustment_repo as repo

pytestmark = pytest.mark.usefixtures("_clean_engine_tables")

_BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _add(tenant, ref, field, value, minutes=0, target_type="LINE"):
    return repo.insert_adjustment(
        tenant, target_type=target_type, target_ref=ref, field=field, value=value,
        created_by=uuid.uuid4(), created_at=_BASE + timedelta(minutes=minutes),
    )


def test_batch_matches_the_single_target_function_for_every_pair(two_tenants):
    tenant, _ = two_tenants
    refs = [f"line-{i}" for i in range(12)]
    fields = ["return_status_override", "rto_outcome", "returned_qty_override"]
    # varied population: some pairs empty, some with one row, some with several (newest must be first)
    _add(tenant, "line-1", "rto_outcome", "A", minutes=1)
    _add(tenant, "line-1", "rto_outcome", "B", minutes=5)   # newer
    _add(tenant, "line-1", "rto_outcome", "C", minutes=3)
    _add(tenant, "line-2", "return_status_override", "RETURNED", minutes=2)
    _add(tenant, "line-7", "returned_qty_override", 2, minutes=9)
    _add(tenant, "line-7", "something_else", "ignored", minutes=9)          # field not requested
    _add(tenant, "SKU-9", "rto_outcome", "wrong-type", minutes=4, target_type="SKU")  # other target_type

    batch = repo.active_adjustments_for_targets(tenant, target_type="LINE", target_refs=refs, fields=fields)

    for ref in refs:
        for field in fields:
            single = repo.active_adjustments_for_target(tenant, target_type="LINE", target_ref=ref, field=field)
            assert batch.get((ref, field), []) == single, (ref, field)
    # newest first, and genuinely populated (guards against both sides being trivially empty)
    assert [r["value"] for r in batch[("line-1", "rto_outcome")]] == ["B", "C", "A"]
    assert ("line-3", "rto_outcome") not in batch
    assert ("line-7", "something_else") not in batch


def test_batch_never_crosses_tenants(two_tenants):
    tenant_a, tenant_b = two_tenants
    _add(tenant_a, "line-1", "rto_outcome", "mine")
    _add(tenant_b, "line-1", "rto_outcome", "theirs")

    a = repo.active_adjustments_for_targets(tenant_a, target_type="LINE", target_refs=["line-1"], fields=["rto_outcome"])
    b = repo.active_adjustments_for_targets(tenant_b, target_type="LINE", target_refs=["line-1"], fields=["rto_outcome"])

    assert [r["value"] for r in a[("line-1", "rto_outcome")]] == ["mine"]
    assert [r["value"] for r in b[("line-1", "rto_outcome")]] == ["theirs"]


def test_batch_with_no_refs_or_no_fields_is_empty_without_querying(two_tenants):
    tenant, _ = two_tenants
    assert repo.active_adjustments_for_targets(tenant, target_type="LINE", target_refs=[], fields=["x"]) == {}
    assert repo.active_adjustments_for_targets(tenant, target_type="LINE", target_refs=["a"], fields=[]) == {}


def test_batch_spans_multiple_ref_chunks(two_tenants, monkeypatch):
    tenant, _ = two_tenants
    monkeypatch.setattr(repo, "_TARGETS_CHUNK", 3)  # force several chunks with a handful of refs
    refs = [f"line-{i}" for i in range(10)]
    for i in (0, 4, 9):
        _add(tenant, refs[i], "rto_outcome", f"v{i}")
    batch = repo.active_adjustments_for_targets(tenant, target_type="LINE", target_refs=refs, fields=["rto_outcome"])
    assert {k: [r["value"] for r in v] for k, v in batch.items()} == {
        ("line-0", "rto_outcome"): ["v0"], ("line-4", "rto_outcome"): ["v4"], ("line-9", "rto_outcome"): ["v9"],
    }
