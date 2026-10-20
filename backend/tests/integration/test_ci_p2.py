"""P2: CI -> CEO -> CFO. A pricing decision starts the finance session from what the seller's verified data already says, and asks only for what is missing; the CEO never changes a price."""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import text

from backend.tenant_context import tenant_scope
from competitor_intelligence.evidence.extraction import ExtractedField, ExtractionResult
from competitor_intelligence.repositories import competitor_url_repo, seller_product_profile_repo
from competitor_intelligence.types import Marketplace
from tests.integration.test_ceo_api import clerk  # noqa: F401
from tests.integration.test_ci_ceo_conversation import _png, api, env, say, start, upload, vision, workspace  # noqa: F401
from tests.integration.test_ceo_turn import Grounded, Scripted, runtime

pytestmark = [pytest.mark.usefixtures("two_tenants"), pytest.mark.skipif(not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL"), reason="needs a live Postgres")]

SKU = "CI-TEST-BOTTLE-001"
TITLE = "Steel Water Bottle 1L (CI TEST)"


def _with_limits():
    """The decision playbooks need the CEO's execution limits (the operator sets them in production)."""
    import dataclasses
    from datetime import datetime, timezone

    from backend.api.v1 import ceo as ceo_api
    from backend.main import app

    rt = dataclasses.replace(runtime(Scripted({}), Grounded()), clock=lambda: datetime.now(timezone.utc), max_legs=5, leg_timeout_seconds=30, max_candidate_prices=5)
    app.dependency_overrides[ceo_api.get_runtime] = lambda: rt


def _setup(client, ha, a, app_user, vision):
    _with_limits()
    seller_product_profile_repo.upsert_profile(a, SKU, category="Water Bottles", attributes=[{"key": "title", "value": TITLE}], keywords=None, price_paise=39900, fulfillment_type=None, updated_by=app_user)
    competitor_url_repo.create_url(a, marketplace=Marketplace.AMAZON, url="https://www.amazon.in/dp/B0BETTERH1", added_by=uuid.uuid4(), label="The Better Home", linked_sku=SKU)
    inv = start(client, ha)
    vision.queue.append(ExtractionResult(fields=(ExtractedField("listed_price_paise", 32900), ExtractedField("availability", "IN_STOCK"), ExtractedField("title", "The Better Home"))))
    att = upload(client, ha, inv, _png(3))
    say(client, ha, inv, "this is The Better Home", attachment_ids=[att])
    say(client, ha, inv, "price is 329, in stock")
    return inv


def test_a_pricing_decision_starts_from_saved_data_and_asks_only_for_what_is_missing(api, app_user, vision):
    client, ha, hb, a, b = api
    inv = _setup(client, ha, a, app_user, vision)
    r = say(client, ha, inv, "Should I reduce my bottle price from ₹399 to ₹349 to compete with The Better Home?")
    print("FIRST:", r["answer"])
    ans = r["answer"]
    assert "From your saved data I already have" in ans and "Steel Water Bottle 1L (CI TEST)" in ans and "₹399.00" in ans and "The Better Home's verified price ₹329.00" in ans, ans
    assert "Which competitor" not in ans and "Which SKU" not in ans and "current selling price" not in ans
    assert r["status"] == "CLARIFIED"
    with tenant_scope(a) as conn:  # nothing was changed or run yet
        assert conn.execute(text("SELECT count(*) FROM metric_result")).scalar_one() == 0
    assert "(6 of 8)" in ans  # five of the questions were answered from saved data


def test_the_decision_finishes_with_ci_and_finance_results_and_names_what_is_missing(api, app_user, vision):
    client, ha, hb, a, b = api
    inv = _setup(client, ha, a, app_user, vision)
    r = say(client, ha, inv, "Should I reduce my bottle price from ₹399 to ₹349 to compete with The Better Home?")
    for reply in ("Prices include GST", "18", "I do not know them yet"):  # GST basis and rate, then one question: the extra per-unit costs are not known yet (left out, never guessed)
        r = say(client, ha, inv, reply)
    print("FINAL:", r["answer"])
    ans = r["answer"]
    assert "Here is what the saved results show" in ans, ans
    assert "cost per unit" in ans.lower()  # the missing input is named, not guessed
    with tenant_scope(a) as conn:
        routes = {x[0] for x in conn.execute(text("SELECT route_key FROM investigation_turn WHERE route_key IS NOT NULL"))}
        codes = {x[0] for x in conn.execute(text("SELECT metric_code FROM metric_result"))}
    assert "COMPETITOR_PRICE_IMPACT" in routes and "PRICE_POSITIONING" in codes  # CI's comparison and finance's margins came from one decision
    assert seller_product_profile_repo.get_profile(a, SKU)["price_paise"] == 39900  # the CEO never changed the seller's price
