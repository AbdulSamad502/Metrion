"""The oracle suite (cfo-query-planner.md §9, AC-P3): the set-based SQL path must equal the per-line engine to the paisa.

Datasets are deterministic (seeded) and labelled synthetic. They deliberately include what makes aggregation go wrong: credit notes
(negative amounts), NULL quantity / NULL gross amount rows, rows dated only by dispatch or order date, undated settlement lines,
settlement lines with no amount (Amazon-style), several marketplaces and SKUs, and period-boundary dates.
"""

from __future__ import annotations

import os
import random
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from cfo.planner.sql_executor import (
    Grouping, Scope, UnsupportedQuery, build_sql, execute_set_metric, reference_set_metric, run_set_metric,
)
from cfo.repositories.tenant_context import tenant_scope

pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL_APP/DATABASE_URL not set — integration tests need a live Postgres",
)

START, END = date(2026, 9, 1), date(2026, 9, 30)
MARKETPLACES = ("AMAZON", "FLIPKART", "MEESHO")
SKUS = ("SKU-A", "SKU-B", "SKU-C", None)
TIMEOUT_MS = 20_000


def _run(tenant: uuid.UUID) -> uuid.UUID:
    from data_foundation.repositories import ingestion_run_repo
    from data_foundation.repositories.tenant_context import tenant_scope as df_scope

    fid = uuid.uuid4()
    with df_scope(tenant) as conn:
        conn.execute(text(
            "INSERT INTO report_file (id, tenant_id, marketplace, report_category, content_sha256, original_filename, byte_size, storage_uri, uploaded_by, uploaded_at)"
            " VALUES (:id, :t, 'MEESHO', 'TAX', :sha, 'synthetic.csv', 100, 'file://x', :u, :at)"),
            {"id": str(fid), "t": str(tenant), "sha": uuid.uuid4().hex + uuid.uuid4().hex, "u": str(uuid.uuid4()), "at": datetime.now(timezone.utc)})
    return ingestion_run_repo.insert_ingestion_run(tenant, report_file_id=fid, adapter_id="meesho.orders.v1", adapter_version="v1", started_at=datetime.now(timezone.utc))


def _seed(tenant: uuid.UUID, seed: int, n_sales: int = 70, n_settle: int = 50) -> None:
    from data_foundation.repositories.sales_line_repo import insert_sales_line
    from data_foundation.repositories.settlement_line_repo import insert_settlement_line

    rng = random.Random(seed)
    run = _run(tenant)
    for i in range(n_sales):
        d = START + timedelta(days=rng.randint(-3, 33))  # a few rows fall outside the period on either side
        which = rng.choice(("invoice", "dispatch", "order", "order"))
        fields: dict[str, object] = {
            "order_ref": f"O{seed}-{i}", "sku": rng.choice(SKUS), "quantity": rng.choice((1, 2, 3, 5, None if rng.random() < 0.08 else 1)),
            "gross_item_amount": None if rng.random() < 0.06 else rng.choice((-10_000, 99_900, 150_050, 7, 2_500_000, 100_00)) * rng.randint(1, 4),
            "return_status": None, "invoice_date": None, "dispatch_date": None, "order_date": None,
        }
        fields[f"{which}_date"] = d
        if rng.random() < 0.15:  # a second, later date: the earlier one in the invoice->dispatch->order order must win
            fields["order_date"] = d + timedelta(days=40) if which != "order" else d
        insert_sales_line(tenant, ingestion_run_id=run, marketplace=rng.choice(MARKETPLACES), canonical_fields=fields,
                          source_row_number=i + 1, source_row_json={}, confidence="PROVISIONAL")
    for j in range(n_settle):
        mp = rng.choice(MARKETPLACES)
        insert_settlement_line(
            tenant, ingestion_run_id=run, marketplace=mp,
            canonical_fields={"order_ref": f"O{seed}-{j}", "line_ref": None, "settlement_id": f"S{j}", "currency": "INR",
                              "settlement_date": None if rng.random() < 0.1 else START + timedelta(days=rng.randint(-5, 36)),
                              "gross_settlement_amount": None if (mp == "AMAZON" or rng.random() < 0.08) else rng.choice((-5_000, 125_000, 88_800, 1)) * rng.randint(1, 3),
                              "document_type": None},
            source_row_number=j + 1, source_row_json={}, confidence="PROVISIONAL")


GROUPINGS = {
    "GROSS_SALES": [Grouping(), Grouping(("marketplace",)), Grouping(("sku",)), Grouping(("period",), "day"), Grouping(("period",), "week"),
                    Grouping(("period",), "month"), Grouping(("marketplace", "period"), "month"), Grouping(("marketplace", "sku"))],
    "SETTLEMENT_RECEIPTS": [Grouping(), Grouping(("marketplace",)), Grouping(("period",), "day"), Grouping(("period",), "week"),
                            Grouping(("marketplace", "period"), "week")],
}
SCOPES = [Scope(START, END), Scope(START, END, marketplaces=("MEESHO", "AMAZON")), Scope(START, END, skus=("SKU-A", "SKU-C")),
          Scope(date(2026, 9, 10), date(2026, 9, 10))]  # a single-day period


def _assert_equal(tenant: uuid.UUID, metric: str, scope: Scope, group: Grouping) -> None:
    if metric == "SETTLEMENT_RECEIPTS" and scope.skus is not None:
        return  # settlement lines carry no SKU: the plan validator rejects this combination before it reaches SQL
    with tenant_scope(tenant) as conn:
        fast = run_set_metric(conn, tenant, metric, scope, group, limit=10_000, statement_timeout_ms=TIMEOUT_MS)
        ref_rows, ref_total = reference_set_metric(conn, tenant, metric, scope, group)
    label = f"{metric} {group} {scope}"
    assert not fast.truncated
    assert fast.consolidated == ref_total, f"consolidated differs: {label}\nSQL {fast.consolidated}\nREF {ref_total}"
    if not group.dimensions:
        return  # nothing is grouped: the consolidated comparison above is the whole check
    got = {r.keys: r for r in fast.rows}
    assert set(got) == set(ref_rows), f"group keys differ: {label}\nSQL-only {set(got) - set(ref_rows)}\nREF-only {set(ref_rows) - set(got)}"
    for k, r in got.items():
        assert r == ref_rows[k], f"group {k} differs: {label}\nSQL {r}\nREF {ref_rows[k]}"


@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5, 6])
def test_fast_path_equals_the_per_line_engine_on_seeded_datasets(seed: int) -> None:
    tenant = uuid.uuid4()
    _seed(tenant, seed)
    for metric, groupings in GROUPINGS.items():
        for scope in SCOPES:
            for group in groupings:
                _assert_equal(tenant, metric, scope, group)


def test_marketplaces_add_up_to_the_consolidated_figure_exactly() -> None:
    tenant = uuid.uuid4()
    _seed(tenant, 11)
    for metric in ("GROSS_SALES", "SETTLEMENT_RECEIPTS"):
        r = execute_set_metric(tenant, metric, Scope(START, END), Grouping(("marketplace",)), limit=100, statement_timeout_ms=TIMEOUT_MS)
        parts = [x.value_paise for x in r.rows]
        assert all(p is not None for p in parts) or metric == "SETTLEMENT_RECEIPTS"
        measured = [p for p in parts if p is not None]
        assert r.consolidated.value_paise is not None
        assert sum(measured) == r.consolidated.value_paise  # test-side check of the invariant; production uses the engine's check_additive


def test_a_group_with_nothing_measurable_is_unavailable_never_zero() -> None:
    tenant = uuid.uuid4()
    from data_foundation.repositories.sales_line_repo import insert_sales_line

    run = _run(tenant)
    insert_sales_line(tenant, ingestion_run_id=run, marketplace="AMAZON",
                      canonical_fields={"order_ref": "X", "quantity": None, "gross_item_amount": 5_000, "order_date": date(2026, 9, 5), "sku": "S"},
                      source_row_number=1, source_row_json={}, confidence="PROVISIONAL")
    r = execute_set_metric(tenant, "GROSS_SALES", Scope(START, END), Grouping(("marketplace",)), limit=10, statement_timeout_ms=TIMEOUT_MS)
    assert r.consolidated.value_paise is None and r.consolidated.excluded == (("NO_QUANTITY_OR_GROSS_AMOUNT", 1),)
    assert r.rows[0].value_paise is None and r.rows[0].line_count == 0
    _assert_equal(tenant, "GROSS_SALES", Scope(START, END), Grouping(("marketplace",)))


def test_a_tenant_sees_only_its_own_rows() -> None:
    a, b = uuid.uuid4(), uuid.uuid4()
    _seed(a, 21, n_sales=20, n_settle=10)
    _seed(b, 22, n_sales=20, n_settle=10)
    ra = execute_set_metric(a, "GROSS_SALES", Scope(START, END), Grouping(), limit=10, statement_timeout_ms=TIMEOUT_MS)
    rb = execute_set_metric(b, "GROSS_SALES", Scope(START, END), Grouping(), limit=10, statement_timeout_ms=TIMEOUT_MS)
    both = ra.consolidated.line_count + rb.consolidated.line_count
    with tenant_scope(a) as conn:
        ref_a, tot_a = reference_set_metric(conn, a, "GROSS_SALES", Scope(START, END), Grouping())
    assert ra.consolidated == tot_a and ra.consolidated != rb.consolidated and both > 0
    # a SKU that only exists for the other tenant yields an empty scope, never foreign data (AC-P9)
    other = execute_set_metric(a, "GROSS_SALES", Scope(START, END, skus=("NOT-MINE",)), Grouping(("sku",)), limit=10, statement_timeout_ms=TIMEOUT_MS)
    assert other.rows == () and other.consolidated.value_paise is None


def test_truncation_is_reported_and_the_consolidated_total_still_covers_everything() -> None:
    tenant = uuid.uuid4()
    _seed(tenant, 31)
    full = execute_set_metric(tenant, "GROSS_SALES", Scope(START, END), Grouping(("period",), "day"), limit=1000, statement_timeout_ms=TIMEOUT_MS)
    cut = execute_set_metric(tenant, "GROSS_SALES", Scope(START, END), Grouping(("period",), "day"), limit=3, statement_timeout_ms=TIMEOUT_MS)
    assert cut.truncated and len(cut.rows) == 3 and cut.rows == full.rows[:3]  # deterministic order: highest value first
    assert cut.consolidated == full.consolidated


def test_statement_timeout_is_enforced_by_the_database() -> None:
    tenant = uuid.uuid4()
    with tenant_scope(tenant) as conn:
        conn.execute(text("SELECT set_config('statement_timeout', '50', true)"))
        with pytest.raises(Exception, match="statement timeout"):
            conn.execute(text("SELECT pg_sleep(2)"))


def test_unsupported_shapes_are_refused_before_any_sql_is_built() -> None:
    with pytest.raises(UnsupportedQuery):
        build_sql("NET_REALIZED_REVENUE", Grouping(), filter_marketplaces=False, filter_skus=False, limited=False)
    with pytest.raises(UnsupportedQuery):
        build_sql("SETTLEMENT_RECEIPTS", Grouping(("sku",)), filter_marketplaces=False, filter_skus=False, limited=True)
    with pytest.raises(UnsupportedQuery):
        build_sql("GROSS_SALES", Grouping(("period",), None), filter_marketplaces=False, filter_skus=False, limited=True)
    with pytest.raises(UnsupportedQuery):
        build_sql("GROSS_SALES", Grouping(("marketplace",), "month"), filter_marketplaces=False, filter_skus=False, limited=True)
    with pytest.raises(UnsupportedQuery):
        build_sql("GROSS_SALES", Grouping(("period",), "quarter"), filter_marketplaces=False, filter_skus=False, limited=True)


def test_no_plan_value_can_reach_the_statement_text() -> None:
    sql = build_sql("GROSS_SALES", Grouping(("marketplace", "sku")), filter_marketplaces=True, filter_skus=True, limited=True)
    for hostile in ("'; DROP TABLE sales_line; --", "AMAZON'", "SKU-A"):
        assert hostile not in sql
    assert ":marketplaces" in sql and ":skus" in sql and ":limit" in sql  # values are bound parameters
    r = execute_set_metric(uuid.uuid4(), "GROSS_SALES", Scope(START, END, marketplaces=("'; DROP TABLE sales_line; --",), skus=("x' OR '1'='1",)),
                           Grouping(("marketplace",)), limit=5, statement_timeout_ms=TIMEOUT_MS)
    assert r.rows == ()


def test_missing_tenant_context_fails_closed() -> None:
    with pytest.raises(ValueError):
        execute_set_metric(None, "GROSS_SALES", Scope(START, END), Grouping(), limit=5, statement_timeout_ms=TIMEOUT_MS)  # type: ignore[arg-type]
