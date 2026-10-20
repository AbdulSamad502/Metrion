"""P4: reviews (option B) and one whole seller journey through the CEO: track -> screenshot -> confirm -> compare -> pricing decision (CFO) -> listing writing (CMO).

Real Postgres, the real CEO / CI / CFO engine / CMO handlers; the only fakes are the scripted vision reader and the deterministic CMO writing model."""

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
from tests.integration.test_ci_p2 import SKU, TITLE, _with_limits
from tests.integration.test_cmo_api import RoutingProvider, _erase_cmo_rows, _install, _seed_rules, ctx_engine  # noqa: F401

pytestmark = [pytest.mark.usefixtures("two_tenants"), pytest.mark.skipif(not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL"), reason="needs a live Postgres")]

LINK = "https://www.amazon.in/Some-Bottle/dp/B0BETTERH1/ref=sr_1_1"


def _profile(a, app_user):
    seller_product_profile_repo.upsert_profile(a, SKU, category="Water Bottles", attributes=[{"key": "title", "value": TITLE}], keywords=None, price_paise=39900, fulfillment_type=None, updated_by=app_user)


def test_a_reviews_question_with_no_review_evidence_gives_source_links_and_asks_for_a_screenshot(api, app_user):
    client, ha, hb, a, b = api
    _profile(a, app_user)
    competitor_url_repo.create_url(a, marketplace=Marketplace.AMAZON, url=LINK, added_by=uuid.uuid4(), label="The Better Home", linked_sku=SKU)
    inv = start(client, ha)
    r = say(client, ha, inv, "What do customers complain about in my competitors' reviews?")
    ans = r["answer"]
    assert "https://www.amazon.in/product-reviews/B0BETTERH1" in ans and "The Better Home" in ans  # where the reviews are, built from the link the seller gave
    assert "screenshot" in ans and "I do not read review pages myself" in ans and "not a review" in ans  # never a scraped or searched review
    assert "customers mention" not in ans and "praised" not in ans  # no invented theme
    with tenant_scope(a) as conn:
        assert conn.execute(text("SELECT count(*) FROM competitor_review_insight")).scalar_one() == 0  # nothing was saved or fabricated


def test_the_whole_seller_journey_runs_through_the_ceo(api, app_user, vision, migrate_engine, monkeypatch):
    client, ha, hb, a, b = api
    _with_limits()
    _seed_rules(migrate_engine, a)  # the marketplace rules the CMO needs (test-fixture rows, labelled as such)
    provider = RoutingProvider()
    _install(monkeypatch, provider)
    monkeypatch.setenv("CMO_LLM_MODEL", "test-model")
    _profile(a, app_user)
    inv = start(client, ha)

    # 1. track a competitor by its link (the CEO names it and links it to the only product)
    r = say(client, ha, inv, f"Track this competitor for my bottle: {LINK}")
    assert "tracking" in r["answer"].lower() or "added" in r["answer"].lower(), r["answer"]
    # 2. its listing screenshot is read, held until confirmed, then confirmed in chat
    vision.queue.append(ExtractionResult(fields=(ExtractedField("listed_price_paise", 32900), ExtractedField("availability", "IN_STOCK"), ExtractedField("title", "The Better Home Steel Water Bottle 1 Litre"))))
    att = upload(client, ha, inv, _png(3))
    r = say(client, ha, inv, "here is the screenshot of its listing", attachment_ids=[att])
    r = say(client, ha, inv, "price is 329, in stock")
    assert "verified competitor data" in r["answer"], r["answer"]
    # 3. compare: the gap comes from the engine, labelled
    r = say(client, ha, inv, "How does my price compare with my competitors?")
    assert "₹70.00" in r["answer"] and "17.54%" in r["answer"], r["answer"]
    # 4. the pricing decision starts from saved data and asks only what is missing (the CFO leg)
    r = say(client, ha, inv, "Should I reduce my bottle price from ₹399 to ₹349 to compete with my competitor?")
    assert "From your saved data I already have" in r["answer"] and "Which competitor" not in r["answer"], r["answer"]
    # 5. the listing: the CEO brokers the saved competitor themes to the CMO, which writes original titles
    inv2 = start(client, ha)
    r = say(client, ha, inv2, "Improve my listing for my steel water bottle")
    for _ in range(8):
        if r["status"] != "CLARIFIED":
            break
        reply = "Amazon" if "marketplace" in r["answer"].lower() else "skip"
        r = say(client, ha, inv2, reply)
    assert r["status"] == "PLANNED", r
    plan = r["plan"]
    leg = plan["plan"]["legs"][0]
    assert leg["action_key"] == "cmo.generate_title_sets" and leg["slots"].get("ci_insight_ids"), leg  # the saved competitor listing is brokered into the plan
    ok = client.post(f"/api/v1/ceo/investigations/{inv2}/plans/{plan['id']}/approve", json={"plan_hash": plan["planHash"]}, headers=ha)
    assert ok.status_code == 200, ok.text
    with tenant_scope(a) as conn:
        mode = conn.execute(text("SELECT input_mode FROM cmo_generation ORDER BY created_at DESC LIMIT 1")).scalar_one()
        prices = conn.execute(text("SELECT count(*) FROM cmo_generation WHERE output_text ILIKE '%329%'")).scalar_one()
    assert mode == "CEO_BROKERED_CI" and prices == 0  # informed by the competitor's themes; no competitor price in anything written
    assert "329" not in provider.prompts[-1]
    assert seller_product_profile_repo.get_profile(a, SKU)["price_paise"] == 39900  # nothing in the journey changed the seller's price
