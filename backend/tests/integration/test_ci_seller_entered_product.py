"""A product the seller entered in their own profile (CI spec 5.5.1 source 2, C31) is a product the CEO can name and CI can link competitors to, with no sales report and no sales row."""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import text

from backend.ceo import slot_resolvers as sr
from backend.services import ceo_reads
from backend.tenant_context import tenant_scope
from competitor_intelligence.repositories import competitor_url_repo, seller_product_profile_repo
from competitor_intelligence.seller_product.derive import list_products

pytestmark = [pytest.mark.usefixtures("two_tenants"), pytest.mark.skipif(not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL"), reason="needs a live Postgres")]

SKU = "CI-TEST-BOTTLE-001"
TITLE = "Steel Water Bottle 1L (CI TEST)"


def _enter(tenant, app_user):
    seller_product_profile_repo.upsert_profile(
        tenant, SKU, category="Water Bottles", attributes=[{"key": "title", "value": TITLE}, {"key": "material", "value": "Stainless Steel"}],
        keywords=["steel water bottle"], price_paise=39900, fulfillment_type=None, updated_by=app_user,
    )


def test_a_profile_only_product_is_listed_named_and_linkable_without_any_sale(two_tenants, app_user):
    a, b = two_tenants
    assert list_products(a) == []
    _enter(a, app_user)
    assert list_products(a) == [(SKU, TITLE)]
    assert ceo_reads.list_seller_products(a) == [(SKU, TITLE)]
    with tenant_scope(a) as conn:  # no sale was created by entering a product
        assert conn.execute(text("SELECT count(*) FROM sales_line")).scalar_one() == 0
    match = sr.resolve_seller_product(a, "steel water bottle 1L (CI TEST)")
    assert isinstance(match, sr.ProductMatch) and match.product_id == SKU
    assert isinstance(sr.resolve_seller_product(a, "steel water bottle"), sr.ProductMatch)  # a seller's natural words reach it
    url_id = competitor_url_repo.create_url(a, marketplace=__import__("competitor_intelligence.types", fromlist=["Marketplace"]).Marketplace.AMAZON, url="https://www.amazon.in/dp/B0F2Y8WFPP", added_by=app_user, label="Rival", linked_sku=SKU)
    assert [c["id"] for c in competitor_url_repo.list_active_by_linked_sku(a, SKU)] == [url_id]
    assert list_products(b) == [] and not isinstance(sr.resolve_seller_product(b, TITLE), sr.ProductMatch)  # another tenant never sees it
