"""Bulk line writers (`*_lines_with_components`) — real Postgres. Same rows/components the
per-row writers produce, but in one transaction with executemany (perf: the per-row path cost a
transaction per row + one round trip per component; measured ~11 ms/row vs ~0.3 ms/row)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from data_foundation.repositories import (
    ingestion_run_repo,
    report_file_repo,
    sales_line_repo,
    settlement_line_repo,
)
from data_foundation.repositories.tenant_context import tenant_scope
from data_foundation.types import ComponentValue


def _run(tenant_id: uuid.UUID, report_category: str) -> uuid.UUID:
    file_id = report_file_repo.insert_report_file(
        tenant_id, marketplace="AMAZON", report_category=report_category, content_sha256=uuid.uuid4().hex * 2,
        original_filename="f.csv", byte_size=1, storage_uri="file://x", uploaded_by=uuid.uuid4(),
        uploaded_at=datetime.now(timezone.utc),
    )
    return ingestion_run_repo.insert_ingestion_run(
        tenant_id, report_file_id=file_id, adapter_id="t", adapter_version="v1", started_at=datetime.now(timezone.utc)
    )


def _components(n: int, base: int = 100) -> tuple[ComponentValue, ...]:
    return tuple(ComponentValue("FEE", f"FEE_{k}", "SETTLEMENT", base + k, None, None, f"c{k}", True, None) for k in range(n))


def _row(i: int, *, components: tuple[ComponentValue, ...]) -> SimpleNamespace:
    return SimpleNamespace(
        canonical_fields={"order_ref": f"O{i}", "line_ref": "1", "settlement_id": "S", "gross_settlement_amount": 1000 + i,
                          "invoice_ref": f"I{i}", "quantity": 1},
        source_row_number=i, source_row_json={"k": str(i)}, components=components,
    )


def _count(tenant_id: uuid.UUID, table: str) -> int:
    with tenant_scope(tenant_id) as conn:
        return conn.execute(text(f"SELECT count(*) FROM {table} WHERE tenant_id = :t"), {"t": str(tenant_id)}).scalar_one()


@pytest.mark.parametrize("side", ["settlement", "sales"])
def test_batch_persists_lines_and_links_components_to_the_right_line(two_tenants, side) -> None:
    tenant_id, _ = two_tenants
    run_id = _run(tenant_id, "SETTLEMENT" if side == "settlement" else "TAX")
    # row i carries i+1 components, so a mis-linked component shows up as a wrong per-line count
    rows = [_row(i, components=_components(i + 1, base=1000 * i)) for i in range(20)]
    writer = (
        settlement_line_repo.insert_settlement_lines_with_components
        if side == "settlement"
        else sales_line_repo.insert_sales_lines_with_components
    )
    parent_col, line_table = ("settlement_line_id", "settlement_line") if side == "settlement" else ("sales_line_id", "sales_line")

    ids = writer(tenant_id, ingestion_run_id=run_id, marketplace="AMAZON", confidence="PROVISIONAL", rows=rows)

    assert len(ids) == len(set(ids)) == 20
    with tenant_scope(tenant_id) as conn:
        by_id = {
            r.id: r.source_row_number
            for r in conn.execute(text(f"SELECT id, source_row_number FROM {line_table} WHERE tenant_id = :t"), {"t": str(tenant_id)})
        }
        comp_rows = conn.execute(
            text(f"SELECT {parent_col} AS parent, amount FROM line_component WHERE tenant_id = :t"), {"t": str(tenant_id)}
        ).all()
    # returned ids are in `rows` order
    assert [by_id[i] for i in ids] == list(range(20))
    per_line: dict[uuid.UUID, list[int]] = {}
    for parent, amount in comp_rows:
        per_line.setdefault(parent, []).append(amount)
    for pos, line_id in enumerate(ids):
        assert sorted(per_line[line_id]) == [1000 * pos + k for k in range(pos + 1)]


def test_empty_batch_is_a_noop(two_tenants) -> None:
    tenant_id, _ = two_tenants
    run_id = _run(tenant_id, "SETTLEMENT")
    assert settlement_line_repo.insert_settlement_lines_with_components(
        tenant_id, ingestion_run_id=run_id, marketplace="AMAZON", confidence="PROVISIONAL", rows=[]
    ) == []
    assert _count(tenant_id, "settlement_line") == 0


def test_batch_is_all_or_nothing(two_tenants) -> None:
    tenant_id, _ = two_tenants
    run_id = _run(tenant_id, "SETTLEMENT")
    good = [_row(i, components=_components(2)) for i in range(5)]
    # `amount` is NOT NULL on line_component — the last row's component violates it, after every
    # line insert and most component inserts have already been issued in the same transaction.
    bad = _row(
        5,
        components=(ComponentValue("FEE", "FEE_X", "SETTLEMENT", None, None, None, "cx", True, None),),  # type: ignore[arg-type]
    )
    with pytest.raises(Exception):
        settlement_line_repo.insert_settlement_lines_with_components(
            tenant_id, ingestion_run_id=run_id, marketplace="AMAZON", confidence="PROVISIONAL", rows=[*good, bad]
        )
    assert _count(tenant_id, "settlement_line") == 0
    assert _count(tenant_id, "line_component") == 0


def test_batch_rows_are_invisible_to_another_tenant(two_tenants) -> None:
    tenant_a, tenant_b = two_tenants
    run_id = _run(tenant_a, "SETTLEMENT")
    settlement_line_repo.insert_settlement_lines_with_components(
        tenant_a, ingestion_run_id=run_id, marketplace="AMAZON", confidence="PROVISIONAL",
        rows=[_row(i, components=_components(2)) for i in range(3)],
    )
    assert _count(tenant_a, "settlement_line") == 3
    assert _count(tenant_a, "line_component") == 6
    assert _count(tenant_b, "settlement_line") == 0
    assert _count(tenant_b, "line_component") == 0


def test_scoped_natural_key_lookup_gives_the_same_duplicate_decisions_as_the_full_load(two_tenants) -> None:
    """`existing_natural_keys_for_orders` must be result-equivalent (for dedup) to loading the
    tenant's whole history — including keys with no `order_ref`, which `natural_key()` allows."""
    from data_foundation.ingestion.dedup import find_natural_key_duplicates

    tenant_id, other_tenant = two_tenants
    run_id = _run(tenant_id, "TAX")

    def hist(i: int, order_ref: str | None, line_ref: str | None, invoice_ref: str | None) -> SimpleNamespace:
        return SimpleNamespace(
            canonical_fields={"order_ref": order_ref, "line_ref": line_ref, "invoice_ref": invoice_ref, "quantity": 1},
            source_row_number=i, source_row_json={}, components=(),
        )

    history = [hist(i, f"ORD-{i}", "1", f"INV-{i}") for i in range(30)]
    history += [hist(100 + i, None, None, f"ONLYINV-{i}") for i in range(5)]  # keys with NO order_ref
    sales_line_repo.insert_sales_lines_with_components(
        tenant_id, ingestion_run_id=run_id, marketplace="AMAZON", confidence="PROVISIONAL", rows=history
    )
    # another tenant's identical keys must never leak into (or hide) this tenant's decisions
    run_other = _run(other_tenant, "TAX")
    sales_line_repo.insert_sales_lines_with_components(
        other_tenant, ingestion_run_id=run_other, marketplace="AMAZON", confidence="PROVISIONAL",
        rows=[hist(i, f"ORD-{i}", "1", f"INV-{i}") for i in range(30, 60)],
    )

    incoming = [
        hist(1, "ORD-3", "1", "INV-3"),          # exact duplicate
        hist(2, "ORD-3", "2", "INV-3"),          # same order, different line -> NOT a duplicate
        hist(3, "ORD-45", "1", "INV-45"),        # only exists for the OTHER tenant -> NOT a duplicate
        hist(4, "ORD-999", "1", "INV-999"),      # brand new
        hist(5, None, None, "ONLYINV-2"),        # NULL-order_ref duplicate
        hist(6, None, None, "ONLYINV-77"),       # NULL-order_ref, new
        hist(7, None, None, None),               # keyless -> never matched
    ]
    full = find_natural_key_duplicates("AMAZON", incoming, sales_line_repo.existing_natural_keys(tenant_id))
    scoped = find_natural_key_duplicates(
        "AMAZON", incoming,
        sales_line_repo.existing_natural_keys_for_orders(tenant_id, {r.canonical_fields["order_ref"] for r in incoming}),
    )
    assert sorted(scoped) == sorted(full) == [1, 5]
