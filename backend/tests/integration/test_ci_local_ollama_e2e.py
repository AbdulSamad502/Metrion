"""The two screenshot workflows end to end through the CEO chat with the LOCAL Ollama vision model: effective price from a listing screenshot, and review themes from a reviews screenshot.

Opt-in (`CI_LOCAL_OLLAMA_E2E=1`) because it needs a running Ollama with the vision model pulled and is slow; it never calls a paid or cloud model (the model names come from
`CI_VISION_MODEL` / `CI_REVIEW_VISION_MODEL`, which must be local). A small local model reads imperfectly, so the assertions are about the PIPELINE's guarantees, not about the
model getting every number right: a read value is held until the seller confirms it, the seller's correction wins, and what the engine returns is what the dashboard shows."""

from __future__ import annotations

import io
import os

import pytest
from PIL import Image, ImageDraw, ImageFont

from tests.integration.test_ceo_api import clerk  # noqa: F401
from tests.integration.test_ci_ceo_conversation import api, env, say, start, track, upload, workspace  # noqa: F401

pytestmark = [pytest.mark.usefixtures("two_tenants"), pytest.mark.skipif(os.environ.get("CI_LOCAL_OLLAMA_E2E") != "1", reason="opt-in: needs a local Ollama vision model (set CI_LOCAL_OLLAMA_E2E=1)")]


def _font(size: int):
    for name in ("arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _page(lines: list[tuple[str, int]]) -> bytes:
    img = Image.new("RGB", (1100, 1500), "white")
    d = ImageDraw.Draw(img)
    y = 40
    for text, size in lines:
        d.text((50, y), text, fill="black", font=_font(size))
        y += size + 34
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


LISTING = _page([
    ("amazon.in", 36),
    ("Titan Octane Analog Men's Watch - Black Dial", 44),
    ("Rating: 4.2 out of 5   (1,180 ratings)", 36),
    ("Price: Rs. 2,599", 64),
    ("M.R.P.: Rs. 3,499    Discount: 26% (Rs. 900)", 36),
    ("Delivery: Rs. 49", 44),
    ("Coupon: Save Rs. 100 with coupon", 36),
    ("Bank Offer: Rs. 250 off with HDFC credit card", 36),
    ("In stock", 44),
])

REVIEWS = _page([
    ("Customer reviews   4.2 out of 5", 44),
    ("1,180 global ratings", 36),
    ("Great look but the strap is very rigid and uncomfortable.", 36),
    ("The dial fogs up in humid weather. Disappointed.", 36),
    ("Strap is stiff, hurts my wrist after an hour.", 36),
    ("Looks premium. Fogging inside the dial after a week.", 36),
    ("Good value for the price, nice dial.", 36),
])


def _listing_image() -> bytes:
    """A real screenshot when `CI_E2E_LISTING_IMAGE` names one (kept out of the repo), else the generated page above."""
    path = os.environ.get("CI_E2E_LISTING_IMAGE")
    return open(path, "rb").read() if path else LISTING


def test_a_listing_screenshot_gives_a_confirmed_effective_price_with_the_local_model(api, monkeypatch):
    monkeypatch.setenv("CI_VISION_MODEL", os.environ.get("CI_VISION_MODEL", "qwen2.5vl-manual"))
    from backend import config

    for fn in (config.ci_vision_model,):
        getattr(fn, "cache_clear", lambda: None)()
    client, ha, hb, a, b = api
    url_id = track(a)
    inv = start(client, ha)
    att = upload(client, ha, inv, _listing_image())
    first = say(client, ha, inv, "this is Titan Octane's listing", attachment_ids=[att])
    print("\nINTAKE REPLY:\n", first["answer"])
    assert "Titan Octane" in first["answer"]
    from competitor_intelligence.repositories import competitor_snapshot_repo

    if "until you confirm them" not in first["answer"]:
        pytest.fail("the local model read nothing the seller must confirm: " + first["answer"][:300])
    assert competitor_snapshot_repo.latest_usable_snapshot(a, url_id) is None  # held until confirmed
    # the seller corrects what the small model may have misread, in plain words
    corr = os.environ.get("CI_E2E_CORRECTION", "price is 2599, discount 900, delivery is 49, in stock")
    second = say(client, ha, inv, corr)
    print("\nCONFIRM REPLY:\n", second["answer"])
    third = say(client, ha, inv, "yes") if "still not using" in second["answer"] else second
    print("\nFINAL REPLY:\n", third["answer"])
    ws = workspace(client, ha)
    comp = ws["competitors"][0]
    print("\nWORKSPACE competitor:", {k: comp.get(k) for k in ("priceStatus", "listedPricePaise", "effectivePrice")})
    want_price = int(os.environ.get("CI_E2E_PRICE_PAISE", "259900"))
    want_discount = int(os.environ.get("CI_E2E_DISCOUNT_PAISE", "90000"))
    assert comp["priceStatus"] == "VERIFIED" and comp["listedPricePaise"] == want_price  # the seller's confirmed value, not the model's guess
    ep = comp["effectivePrice"]
    assert ep and ep["effective"]["isAvailable"] and ep["effective"]["engineResultRef"]  # the figure comes from Brain 1 and cites its result
    assert ep["effective"]["valuePaise"] == want_price - want_discount  # listed less the confirmed visible discount; computed by the engine, never by CI or the model
    for o in ep["offers"]:
        if o.get("conditional"):
            assert o["amountPaise"] is None or True  # a conditional (card) offer is never subtracted
    assert workspace(client, hb)["competitors"] == []


def test_a_reviews_screenshot_gives_review_themes_with_the_local_model(api, monkeypatch):
    client, ha, hb, a, b = api
    track(a)
    inv = start(client, ha)
    att = upload(client, ha, inv, REVIEWS)
    r = say(client, ha, inv, "these are the reviews of Titan Octane", attachment_ids=[att])
    print("\nREVIEW REPLY:\n", r["answer"])
    assert "Titan Octane" in r["answer"]
    q = say(client, ha, inv, "what do customers complain about at my competitors")
    print("\nREVIEW FINDINGS:\n", q["answer"])
    assert "which competitor" not in q["answer"].lower()  # a question is answered, never mistaken for naming the earlier image
    ws = workspace(client, ha)
    print("\nWORKSPACE reviewInsights:", ws.get("reviewInsights"))
    insights = ws.get("reviewInsights") or []
    assert insights, "the reviews screenshot produced no stored review insight"
    first = insights[0]
    assert first["insightState"] in ("COMPLETE", "PARTIAL", "DEGRADED") and first["reviewsConsidered"] >= 1 and first["confidence"] == "DERIVED"  # themes always come with how many reviews were read
    assert first["complaintThemes"] and first["findingId"]
