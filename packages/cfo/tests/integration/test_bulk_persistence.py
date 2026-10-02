"""Bulk persistence for the Leak Shield path (`metric_result_repo.save_many`,
`leak_finding_repo.insert_many`) — real Postgres.

Why: a traced CEO Hub `cfo.reconcile` request spent 3.4 s of 4.6 s (74%) on 128 one-row
`metric_result.save` calls and 126 one-row `leak_finding.insert` calls, each its own transaction.
The bulk functions must persist exactly what the one-row functions persist."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import pytest

from calc_engine.api.compute_metric import MetricResult
from calc_engine.repositories import metric_result_repo
from calc_engine.types import RecognitionState
from cfo.repositories import leak_finding_repo

_AS_OF = date(2026, 1, 20)
_AT = datetime(2026, 1, 20, tzinfo=timezone.utc)


def _metric(value: int, *, ref: uuid.UUID | None = None) -> MetricResult:
    return MetricResult(
        id=uuid.uuid4(), metric_code="LEAK_EXCEPTION_AMOUNT", value_paise=value,
        recognition_state=RecognitionState.RECOGNISED, confidence="DERIVED", calculation_basis="test",
        formula_version="reconcile.v1", canonical_data_version="non-canonical", as_of_date=_AS_OF,
        input_refs=(ref or uuid.uuid4(),), exclusions=(), computed_at=_AT, is_available=True,
    )


def _kw(ref: uuid.UUID) -> dict:
    return dict(grain="LINE", target_ref=str(ref), period="2026-01-01/2026-01-31", config_version="leak_shield.v1")


def _strip(row: dict) -> dict:
    return {k: v for k, v in row.items() if k not in ("id", "target_ref", "input_refs")}


def test_save_many_persists_the_same_row_save_does(two_tenants) -> None:
    tenant, _ = two_tenants
    a, b = _metric(500), _metric(500)
    metric_result_repo.save(tenant, a, **_kw(uuid.uuid4()))
    metric_result_repo.save_many(tenant, [(b, _kw(uuid.uuid4()))])

    row_a, row_b = metric_result_repo.get(tenant, a.id), metric_result_repo.get(tenant, b.id)
    assert row_a is not None and row_b is not None
    assert _strip(row_a) == _strip(row_b)  # every persisted column identical apart from ids/refs


def test_save_many_writes_every_item_in_one_call_and_returns_ids_in_order(two_tenants) -> None:
    tenant, _ = two_tenants
    refs = [uuid.uuid4() for _ in range(40)]
    results = [_metric(100 + i, ref=r) for i, r in enumerate(refs)]

    ids = metric_result_repo.save_many(tenant, [(res, _kw(r)) for res, r in zip(results, refs)])

    assert ids == [r.id for r in results]
    for res, ref in zip(results, refs):
        row = metric_result_repo.get(tenant, res.id)
        assert row is not None and row["value_paise"] == res.value_paise and row["target_ref"] == str(ref)


def test_save_many_is_all_or_nothing_and_tenant_scoped(two_tenants) -> None:
    tenant, other = two_tenants
    good, dup = _metric(1), _metric(2)
    dup_again = dup  # same primary key twice in one batch -> constraint violation -> whole batch rolls back
    with pytest.raises(Exception):
        metric_result_repo.save_many(tenant, [(good, _kw(uuid.uuid4())), (dup, _kw(uuid.uuid4())), (dup_again, _kw(uuid.uuid4()))])
    assert metric_result_repo.get(tenant, good.id) is None  # nothing from the failed batch persisted

    ok = _metric(3)
    metric_result_repo.save_many(tenant, [(ok, _kw(uuid.uuid4()))])
    assert metric_result_repo.get(other, ok.id) is None  # another tenant never sees it


def test_save_many_empty_is_a_noop(two_tenants) -> None:
    assert metric_result_repo.save_many(two_tenants[0], []) == []


def _finding_kwargs(i: int) -> dict:
    return dict(
        reconciliation_exception_id=uuid.uuid4(), engine_result_ref=uuid.uuid4(), marketplace="MEESHO",
        leak_category="FEE_OVERCHARGE", severity="UNAVAILABLE", amount_paise=1000 + i, affected_line_count=1,
        first_observed_at=_AT, age_days=0, status="NEW", confidence="DERIVED", formula_version="reconcile.v1",
        window_status="NOT_APPLICABLE",
    )


def test_insert_many_persists_the_same_row_insert_does_and_returns_ids_in_order(two_tenants) -> None:
    tenant, other = two_tenants
    single_id = leak_finding_repo.insert(tenant, **_finding_kwargs(0))
    ids = leak_finding_repo.insert_many(tenant, [_finding_kwargs(i) for i in range(1, 26)])

    assert len(ids) == 25 and len(set(ids)) == 25
    rows = {r["id"]: r for r in leak_finding_repo.list_for_tenant(tenant)}
    assert set(rows) == {single_id, *ids}
    # bulk rows are written in input order: amount_paise 1001..1025 line up with the returned ids
    assert [rows[i]["amount_paise"] for i in ids] == [1000 + n for n in range(1, 26)]
    comparable = ("marketplace", "leak_category", "severity", "affected_line_count", "age_days", "status", "confidence",
                  "formula_version", "window_status", "sku", "claim_window_days", "explanation", "recommended_action")
    assert {k: rows[single_id][k] for k in comparable} == {k: rows[ids[0]][k] for k in comparable}
    assert leak_finding_repo.list_for_tenant(other) == []  # tenant isolation


def test_insert_many_empty_is_a_noop(two_tenants) -> None:
    assert leak_finding_repo.insert_many(two_tenants[0], []) == []
