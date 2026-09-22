"""SellerProduct end-to-end against real Postgres — competitor-intelligence-agent.md §5.5,
§5.5.1, §5.5.2, C30/C31, D8. Derives the canonical half from real `sales_line` rows
(`packages/data-foundation`), submits a manual seller-product-profile override
(`seller_product_profile` — this package), and confirms the merged read reflects §5.5.1's
precedence rule. Also confirms RLS blocks a cross-tenant read of `seller_product_profile`
(T72) and that CI's own tenant_scope() never crosses into another tenant's row.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import text

from competitor_intelligence.repositories import seller_product_profile_repo
from competitor_intelligence.repositories.tenant_context import tenant_scope as ci_tenant_scope
from competitor_intelligence.seller_product.derive import derive_canonical
from competitor_intelligence.seller_product.merge import merge_seller_product
from competitor_intelligence.seller_product.types import FieldSource

from data_foundation.repositories.ingestion_run_repo import insert_ingestion_run, mark_finished
from data_foundation.repositories.report_file_repo import insert_report_file
from data_foundation.repositories.sales_line_repo import insert_sales_line

pytestmark = pytest.mark.usefixtures("_clean_ci_tables")


def _seed_sales_line(
    tenant_id: uuid.UUID,
    *,
    sku: str,
    item_title: str,
    order_date: date,
    uploaded_by: uuid.UUID,
) -> None:
    """Real report_file -> ingestion_run -> sales_line chain, through data-foundation's own
    repositories — never a hand-crafted INSERT that could drift from that package's own
    contract."""
    now = datetime.now(timezone.utc)
    report_file_id = insert_report_file(
        tenant_id,
        marketplace="AMAZON",
        report_category="ORDER_STATUS",
        content_sha256=uuid.uuid4().hex.rjust(64, "0"),
        original_filename="orders.csv",
        byte_size=1024,
        storage_uri="local://orders.csv",
        uploaded_by=uploaded_by,
        uploaded_at=now,
    )
    run_id = insert_ingestion_run(
        tenant_id,
        report_file_id=report_file_id,
        adapter_id="amazon_mtr_b2c_v1",
        adapter_version="1.0.0",
        started_at=now,
    )
    insert_sales_line(
        tenant_id,
        ingestion_run_id=run_id,
        marketplace="AMAZON",
        canonical_fields={
            "order_ref": f"ORDER-{uuid.uuid4().hex[:8]}",
            "line_ref": "1",
            "sku": sku,
            "item_title": item_title,
            "order_date": order_date,
            "gross_item_amount": 199900,  # a transacted amount — never read as a listing price
        },
        source_row_number=1,
        source_row_json={"sku": sku},
        confidence="VERIFIED",
    )
    mark_finished(
        tenant_id,
        run_id,
        status="VALIDATED",
        row_count_read=1,
        row_count_accepted=1,
        row_count_rejected=0,
        finished_at=now,
    )


def test_derive_reads_the_most_recent_sales_line_row(two_tenants: tuple[uuid.UUID, uuid.UUID]) -> None:
    tenant_id, _ = two_tenants
    user_id = uuid.uuid4()
    _seed_sales_line(tenant_id, sku="SKU-1", item_title="Wireless Mouse (v1)", order_date=date(2026, 1, 1), uploaded_by=user_id)
    _seed_sales_line(tenant_id, sku="SKU-1", item_title="Wireless Mouse (v2)", order_date=date(2026, 6, 1), uploaded_by=user_id)

    canonical = derive_canonical(tenant_id, sku="SKU-1")

    assert canonical is not None
    assert canonical.product_id == "SKU-1"
    assert canonical.title == "Wireless Mouse (v2)"  # the later order_date wins


def test_derive_returns_none_when_no_sales_line_matches(two_tenants: tuple[uuid.UUID, uuid.UUID]) -> None:
    tenant_id, _ = two_tenants
    assert derive_canonical(tenant_id, sku="NO-SUCH-SKU") is None


def test_manual_override_supersedes_canonical_on_merge(two_tenants: tuple[uuid.UUID, uuid.UUID]) -> None:
    """The full loop: derive from real sales_line, submit a manual override through the
    profile repo, confirm the merged read reflects §5.5.1's precedence — seller-entered wins,
    field_source records who won, blanks stay UNKNOWN."""
    tenant_id, _ = two_tenants
    user_id = uuid.uuid4()
    _seed_sales_line(tenant_id, sku="SKU-1", item_title="Wireless Mouse", order_date=date(2026, 1, 1), uploaded_by=user_id)

    canonical = derive_canonical(tenant_id, sku="SKU-1")
    assert canonical is not None

    # Before any manual entry: title is CANONICAL_DERIVED, everything else UNKNOWN.
    before = merge_seller_product(canonical, seller_product_profile_repo.profile_to_manual_overrides(None))
    assert before.field_source["title"] == FieldSource.CANONICAL_DERIVED
    assert before.category is None
    assert "category" not in before.field_source

    seller_product_profile_repo.upsert_profile(
        tenant_id,
        "SKU-1",
        category="Electronics",
        attributes=[{"key": "color", "value": "black"}],
        keywords=["wireless", "mouse"],
        price_paise=149900,
        fulfillment_type="SELLER_FULFILLED",
        updated_by=user_id,
    )

    manual_row = seller_product_profile_repo.get_profile(tenant_id, "SKU-1")
    assert manual_row is not None
    manual_overrides = seller_product_profile_repo.profile_to_manual_overrides(manual_row)

    after = merge_seller_product(canonical, manual_overrides)

    assert after.title == "Wireless Mouse"
    assert after.field_source["title"] == FieldSource.CANONICAL_DERIVED
    assert after.category == "Electronics"
    assert after.field_source["category"] == FieldSource.SELLER_ENTERED
    assert after.price_paise == 149900
    assert after.attributes == (("color", "black"),)
    assert after.keywords == ("wireless", "mouse")
    assert after.fulfillment_type == "SELLER_FULFILLED"
    # rating/review_count remain UNKNOWN regardless of anything submitted (C31, §5.5.2)
    assert after.rating is None
    assert after.review_count is None
    assert "rating" not in after.field_source
    assert "review_count" not in after.field_source


def test_manual_override_editable_and_replaced_on_resubmission(two_tenants: tuple[uuid.UUID, uuid.UUID]) -> None:
    """AC22c: editable at any time, not write-once — a second upsert fully replaces the
    first, it does not merge on top of it."""
    tenant_id, _ = two_tenants
    user_id = uuid.uuid4()

    seller_product_profile_repo.upsert_profile(
        tenant_id,
        "SKU-1",
        category="Electronics",
        attributes=None,
        keywords=["wireless"],
        price_paise=149900,
        fulfillment_type="SELLER_FULFILLED",
        updated_by=user_id,
    )
    seller_product_profile_repo.upsert_profile(
        tenant_id,
        "SKU-1",
        category="Computer Accessories",
        attributes=None,
        keywords=None,
        price_paise=159900,
        fulfillment_type=None,
        updated_by=user_id,
    )

    row = seller_product_profile_repo.get_profile(tenant_id, "SKU-1")
    assert row is not None
    assert row["category"] == "Computer Accessories"
    assert row["price_paise"] == 159900
    assert row["keywords"] is None
    assert row["fulfillment_type"] is None


def test_rls_blocks_cross_tenant_read_of_seller_product_profile(two_tenants: tuple[uuid.UUID, uuid.UUID]) -> None:
    """T72 — cross-tenant read of another tenant's seller-product profile row returns
    nothing, RLS `FORCE`d like every other tenant table in this package."""
    tenant_a, tenant_b = two_tenants
    user_id = uuid.uuid4()
    seller_product_profile_repo.upsert_profile(
        tenant_a,
        "SKU-1",
        category="Electronics",
        attributes=None,
        keywords=None,
        price_paise=149900,
        fulfillment_type="SELLER_FULFILLED",
        updated_by=user_id,
    )

    assert seller_product_profile_repo.get_profile(tenant_a, "SKU-1") is not None
    assert seller_product_profile_repo.get_profile(tenant_b, "SKU-1") is None


def test_rls_forced_even_bypassing_the_repository_layer(two_tenants: tuple[uuid.UUID, uuid.UUID], app_engine) -> None:
    """Belt-and-suspenders: a raw query scoped to tenant_b's context can never see tenant_a's
    row, independent of any application-level filtering the repository layer might add."""
    tenant_a, tenant_b = two_tenants
    user_id = uuid.uuid4()
    seller_product_profile_repo.upsert_profile(
        tenant_a,
        "SKU-1",
        category="Electronics",
        attributes=None,
        keywords=None,
        price_paise=149900,
        fulfillment_type="SELLER_FULFILLED",
        updated_by=user_id,
    )

    with ci_tenant_scope(tenant_b) as conn:
        row = conn.execute(
            text("SELECT * FROM seller_product_profile WHERE product_id = 'SKU-1'")
        ).first()
        assert row is None
