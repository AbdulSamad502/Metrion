"""Issue 11 (Metrion_24_Fixes): "Compare vs Seller Product" for TEST-SKU-001 answered "No SellerProduct".

That is the correct answer for a product Metrion has never seen. A SellerProduct exists once the SKU is in an uploaded sales report or the seller saves a profile for it
(`PUT /ci/seller-products/{id}`). These tests walk that sequence on the real routes and the scratch Postgres: unknown product -> 404 that names it; saved profile -> the
product reads back and the comparison answers (here, honestly unavailable until the competitor has evidence); another tenant's profile never counts."""

from __future__ import annotations

import uuid

from tests.integration.test_cfo_imports import _register_owner, app_client, fake_clerk  # noqa: F401  (fixtures and helpers)

SKU = "TEST-SKU-001"


def _competitor(client, headers) -> str:
    resp = client.post("/api/v1/ci/competitor-urls", json={"url": f"https://amazon.in/dp/{uuid.uuid4().hex[:10]}", "label": "Rival"}, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def test_unknown_product_is_a_404_that_names_it_and_a_saved_profile_makes_the_comparison_answer(app_client, fake_clerk, two_tenants):
    headers = _register_owner(fake_clerk, two_tenants[0])
    url_id = _competitor(app_client, headers)
    missing = app_client.get(f"/api/v1/ci/competitor-urls/{url_id}/comparison", params={"product_id": SKU}, headers=headers)
    assert missing.status_code == 404 and missing.json()["detail"].startswith(f"No SellerProduct for '{SKU}'")
    assert app_client.get(f"/api/v1/ci/seller-products/{SKU}", headers=headers).status_code == 404

    saved = app_client.put(f"/api/v1/ci/seller-products/{SKU}", json={"category": "Home", "price_paise": 49900, "keywords": ["jar"]}, headers=headers)
    assert saved.status_code == 200, saved.text
    assert app_client.get(f"/api/v1/ci/seller-products/{SKU}", headers=headers).json()["pricePaise"] == 49900

    answered = app_client.get(f"/api/v1/ci/competitor-urls/{url_id}/comparison", params={"product_id": SKU}, headers=headers)
    assert answered.status_code == 200, answered.text
    assert answered.json()["available"] is False and answered.json()["reason"]  # the competitor has no evidence yet: said so, not a failure


def test_another_tenants_saved_product_does_not_exist_for_this_tenant(app_client, fake_clerk, two_tenants):
    a, b = two_tenants
    ha, hb = _register_owner(fake_clerk, a), _register_owner(fake_clerk, b)
    app_client.put(f"/api/v1/ci/seller-products/{SKU}", json={"category": "Home", "price_paise": 49900}, headers=ha)
    assert app_client.get(f"/api/v1/ci/seller-products/{SKU}", headers=hb).status_code == 404
    url_id = _competitor(app_client, hb)
    assert app_client.get(f"/api/v1/ci/competitor-urls/{url_id}/comparison", params={"product_id": SKU}, headers=hb).status_code == 404
