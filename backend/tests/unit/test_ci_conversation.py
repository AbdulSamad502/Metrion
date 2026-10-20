"""CI spec §6.21–§6.25 — the CEO's deterministic CI conversations: what it plans from the seller's words and what it says back. No database, no model."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.ceo import ci_conversation as cc
from backend.ceo import slot_resolvers as sr
from backend.services import ci_conv_data

TENANT, INV = uuid4(), uuid4()
TITAN, FOSSIL = uuid4(), uuid4()
IMG = {"id": uuid4(), "detected_type": "PNG", "sha256": "a" * 64}
PDF = {"id": uuid4(), "detected_type": "PDF", "sha256": "b" * 64}


class World:
    def __init__(self, monkeypatch, *, competitors=(("Titan Octane", TITAN), ("Fossil Grant", FOSSIL)), products=(("SKU-1", "Emerald Chrono"),), open_requests=(), queue=(), ingested=(), tz=None):
        self.competitors, self.products = list(competitors), list(products)
        self.open_requests, self.queue, self.ingested = list(open_requests), list(queue), set(ingested)
        self.tz = tz
        self.free_slots = 5
        w = self

        def resolve_competitor(tenant, raw):
            text = (raw or "").casefold()
            if not w.competitors:
                return sr.CompetitorUnresolved("NONE_TRACKED")
            hits = [(i, n) for n, i in w.competitors if n.casefold() in text]
            if len(hits) == 1:
                return sr.CompetitorMatch(*hits[0])
            names = tuple(n for n, _ in w.competitors)
            return sr.CompetitorUnresolved("AMBIGUOUS" if hits else "NOT_FOUND", names)

        def resolve_product(tenant, raw):
            text = (raw or "").casefold()
            hits = [(p, t) for p, t in w.products if t.casefold() in text or p.casefold() == text]
            return sr.ProductMatch(*hits[0]) if len(hits) == 1 else sr.ProductUnresolved("NOT_FOUND", tuple(t for _, t in w.products))

        monkeypatch.setattr(sr, "resolve_competitor", resolve_competitor)
        monkeypatch.setattr(sr, "resolve_seller_product", resolve_product)
        monkeypatch.setattr(cc, "ceo_reads", SimpleNamespace(list_seller_products=lambda t, limit=200: list(w.products)))
        monkeypatch.setattr(
            cc, "data",
            SimpleNamespace(
                linked_skus=lambda t: ["SKU-1"], evidence_exists=lambda t, sha: sha in w.ingested, open_requests=lambda t: list(w.open_requests),
                latest_run_candidates=lambda t: list(w.queue), currency_claims=ci_conv_data.currency_claims, tenant_timezone=lambda t: w.tz, identity_note=ci_conv_data.identity_note,
                watchlist_status=lambda t: {"limit": 5, "active": [], "free": w.free_slots}, archived_competitors=lambda t: [], review_sources=lambda t: {"competitors": [], "minSample": 10},
            ),
        )


def req(field, proposed, snap, n=0):
    return {"id": uuid4(), "snapshot_id": snap, "field_name": field, "consequential": True, "proposed_value": proposed, "created_at": n}


def cand(n, tier="RECOMMENDED", rel="DIRECT_COMPETITOR", decision="NONE", url_id=None):
    return {"id": uuid4(), "tier": tier, "seller_decision": decision, "competitor_url_id": url_id, "marketplace": "AMAZON", "relationship_class": rel,
            "created_at": datetime(2026, 10, 18, 12, n, tzinfo=timezone.utc)}


def plan(text, attachments=(), **kw):
    return cc.plan_turn(TENANT, INV, text, attachments, **kw)


def leg(payload=None, status="COMPLETE", reason=None):
    return SimpleNamespace(status=SimpleNamespace(value=status), payload=payload, reason=reason)


# ---- screenshots --------------------------------------------------------------------
def test_a_screenshot_naming_a_tracked_competitor_becomes_an_intake_step(monkeypatch) -> None:
    World(monkeypatch)
    p = plan("this is Titan Octane's listing", [IMG])
    assert p.kind == "INTAKE" and p.steps[0].key == "ci.evidence_intake"
    assert p.steps[0].slots == {"attachment_id": str(IMG["id"]), "competitor_url_id": str(TITAN), "sha256": "a" * 64, "allow_near_duplicate": False}


def test_a_reviews_screenshot_goes_to_review_intake(monkeypatch) -> None:
    World(monkeypatch)
    p = plan("here are the reviews for Fossil Grant", [IMG])
    assert p.kind == "REVIEW_INTAKE" and p.steps[0].key == "ci.review_intake" and p.steps[0].slots["competitor_url_id"] == str(FOSSIL)


def test_an_unnamed_competitor_is_asked_for_and_nothing_is_stored(monkeypatch) -> None:
    World(monkeypatch)
    p = plan("here is a competitor screenshot", [IMG])
    assert p.kind == "NEEDS_COMPETITOR" and not p.steps and "Nothing has been stored" in p.text
    assert p.card and p.card["kind"] == "PICK" and p.card["mode"] == "single" and "Titan Octane" in [i["label"] for i in p.card["items"]]  # a pick card, not typing


def test_no_tracked_competitors_means_the_seller_is_pointed_to_the_find_and_tick_flow(monkeypatch) -> None:
    World(monkeypatch, competitors=())
    p = plan("a competitor screenshot", [IMG])
    assert p.kind == "NEEDS_COMPETITOR" and not p.steps and "find my competitors" in p.text and "link" not in p.text


def test_the_name_in_a_later_message_picks_up_the_waiting_image(monkeypatch) -> None:
    World(monkeypatch)
    p = plan("it's Titan Octane", [], latest_attachments=[IMG])
    assert p.kind == "INTAKE" and p.steps[0].slots["attachment_id"] == str(IMG["id"])


def test_an_image_already_read_is_not_picked_up_again(monkeypatch) -> None:
    World(monkeypatch, ingested={"a" * 64})
    assert plan("it's Titan Octane", [], latest_attachments=[IMG]) is None


def test_a_fresh_capture_message_allows_a_near_duplicate(monkeypatch) -> None:
    World(monkeypatch)
    p = plan("Titan Octane, it's a fresh capture", [], latest_attachments=[IMG])
    assert p.steps[0].slots["allow_near_duplicate"] is True


def test_a_photo_for_another_agent_or_a_message_with_no_competitor_signal_is_not_ours(monkeypatch) -> None:
    World(monkeypatch)
    assert plan("write titles for this bottle", [IMG], other_agent_intent=True) is None
    assert plan("what do you think of this?", [IMG]) is None
    assert plan("hello", [PDF]) is None


# ---- confirmation -------------------------------------------------------------------
def _asked(monkeypatch, **kw):
    snap = uuid4()
    reqs = [req("listed_price_paise", 269900, snap, 1), req("availability", "IN_STOCK", snap, 2)]
    World(monkeypatch, open_requests=reqs, **kw)
    return reqs


def test_yes_after_the_ceos_question_accepts_what_was_read(monkeypatch) -> None:
    reqs = _asked(monkeypatch)
    p = plan("yes", last_ceo_text="I am not using these " + cc.CONFIRM_MARKER)
    assert p.kind == "CONFIRM"
    assert {a["info_request_id"]: a["value"] for a in p.steps[0].slots["answers"]} == {str(reqs[0]["id"]): 269900, str(reqs[1]["id"]): "IN_STOCK"}


def test_a_bare_yes_or_number_is_not_a_confirmation_unless_ci_just_asked(monkeypatch) -> None:
    _asked(monkeypatch)
    assert plan("yes") is None and plan("ok") is None and plan("2899") is None
    assert plan("yes", last_ceo_text="something unrelated") is None


def test_a_correction_overrides_what_was_read_and_is_explicit(monkeypatch) -> None:
    reqs = _asked(monkeypatch)
    p = plan("no, the price is 2899 and it is out of stock", last_ceo_text=cc.CONFIRM_MARKER)
    vals = {a["info_request_id"]: a["value"] for a in p.steps[0].slots["answers"]}
    assert vals == {str(reqs[0]["id"]): 289900, str(reqs[1]["id"]): "OUT_OF_STOCK"}
    assert p.context["corrected"] == ["availability", "listed_price_paise"]


def test_an_explicit_price_statement_counts_even_without_the_marker(monkeypatch) -> None:
    reqs = _asked(monkeypatch)
    p = plan("the price is 2899")
    assert p.kind == "CONFIRM" and p.steps[0].slots["answers"] == [{"info_request_id": str(reqs[0]["id"]), "value": 289900}]


def test_two_different_amounts_are_ambiguous_and_correct_nothing(monkeypatch) -> None:
    _asked(monkeypatch)
    assert plan("the price is 2899 or 2999", last_ceo_text=cc.CONFIRM_MARKER) is None


def test_skip_declines_everything_it_was_asked_about(monkeypatch) -> None:
    reqs = _asked(monkeypatch)
    p = plan("skip, I'm not sure", last_ceo_text=cc.CONFIRM_MARKER)
    assert p.steps[0].slots["answers"] == [] and set(p.steps[0].slots["declined"]) == {str(r["id"]) for r in reqs}


def test_a_discount_correction_is_read_separately_from_the_price(monkeypatch) -> None:
    snap = uuid4()
    reqs = [req("listed_price_paise", 269900, snap, 1), req("visible_discount_paise", 10000, snap, 2)]
    World(monkeypatch, open_requests=reqs)
    p = plan("price is 2699, discount 150", last_ceo_text=cc.CONFIRM_MARKER)
    vals = {a["info_request_id"]: a["value"] for a in p.steps[0].slots["answers"]}
    assert vals == {str(reqs[0]["id"]): 269900, str(reqs[1]["id"]): 15000}


def test_no_open_questions_means_no_confirmation_plan(monkeypatch) -> None:
    World(monkeypatch)
    assert plan("yes", last_ceo_text=cc.CONFIRM_MARKER) is None


# ---- track a link -------------------------------------------------------------------
def test_track_a_link_for_the_only_product(monkeypatch) -> None:
    World(monkeypatch)
    p = plan("track https://www.amazon.in/dp/B09ABC1234 called Sonata Poze")
    assert p.kind == "ADD_COMPETITORS" and p.steps[0].key == "ci.competitor_add"
    assert p.steps[0].slots == {"url": "https://www.amazon.in/dp/B09ABC1234", "product_id": "SKU-1", "label": "Sonata Poze"}


def test_several_links_are_echoed_back_and_nothing_is_added_until_the_seller_says_yes(monkeypatch) -> None:
    World(monkeypatch)
    p = plan("monitor https://www.amazon.in/dp/B09AAAAAA1 and https://www.flipkart.com/x/p/itm1?pid=Q1 as rivals")
    assert p.kind == "BULK_CONFIRM" and not p.steps and cc.BULK_MARKER in p.text and "Nothing has been added yet" in p.text
    assert "https://www.amazon.in/dp/B09AAAAAA1" in p.text and "Emerald Chrono" in p.text


def test_a_yes_to_the_bulk_question_adds_every_link_for_the_named_product(monkeypatch) -> None:
    World(monkeypatch)
    ask = plan("monitor https://www.amazon.in/dp/B09AAAAAA1 and https://www.flipkart.com/x/p/itm1?pid=Q1").text
    p = plan("yes", last_ceo_text=ask)
    assert p.kind == "ADD_COMPETITORS" and [s.key for s in p.steps] == ["ci.competitor_add"] * 2
    assert all(s.slots["product_id"] == "SKU-1" and "label" not in s.slots for s in p.steps)
    assert [s.slots["url"] for s in p.steps] == ["https://www.amazon.in/dp/B09AAAAAA1", "https://www.flipkart.com/x/p/itm1?pid=Q1"]


def test_a_bare_yes_without_the_bulk_question_adds_nothing(monkeypatch) -> None:
    World(monkeypatch)
    assert plan("yes", last_ceo_text="Here is what I found.") is None or plan("yes", last_ceo_text="Here is what I found.").kind != "ADD_COMPETITORS"
    ask = plan("track https://www.amazon.in/dp/B09AAAAAA1 https://www.flipkart.com/x/p/itm1?pid=Q1").text
    other = plan("no, only the first", last_ceo_text=ask)
    assert other is None or other.kind != "ADD_COMPETITORS"


def test_a_single_link_is_still_added_directly(monkeypatch) -> None:
    World(monkeypatch)
    assert plan("track https://www.amazon.in/dp/B09ABC1234").kind == "ADD_COMPETITORS"


def test_with_several_products_the_seller_is_asked_which(monkeypatch) -> None:
    World(monkeypatch, products=(("SKU-1", "Emerald Chrono"), ("SKU-2", "Steel Bottle")))
    monkeypatch.setattr(cc.data, "linked_skus", lambda t: ["SKU-1", "SKU-2"])
    p = plan("track https://www.amazon.in/dp/B09ABC1234")
    assert p.kind == "NEEDS_PRODUCT" and not p.steps and "Emerald Chrono" in p.text
    p2 = plan("track https://www.amazon.in/dp/B09ABC1234 for my Steel Bottle")
    assert p2.steps[0].slots["product_id"] == "SKU-2"


def test_a_link_without_a_tracking_verb_is_left_alone(monkeypatch) -> None:
    World(monkeypatch)
    assert plan("what is wrong with https://www.amazon.in/dp/B09ABC1234") is None


# ---- candidates ---------------------------------------------------------------------
def test_candidates_are_numbered_in_the_dashboards_order_and_decided_by_number(monkeypatch) -> None:
    q = [cand(3, "ANALYZED"), cand(1), cand(2), cand(4, decision="REJECTED"), cand(5, url_id=uuid4())]
    World(monkeypatch, queue=q)
    queue = cc.candidate_queue(TENANT)
    assert [c["id"] for c in queue] == [q[1]["id"], q[2]["id"], q[0]["id"]]  # recommended first, decided and tracked ones gone
    p = plan("track 1 and 3")
    assert p.kind == "DECIDE_CANDIDATES" and [s.slots["candidate_id"] for s in p.steps] == [str(q[1]["id"]), str(q[0]["id"])] and p.steps[0].key == "ci.competitor_approve"
    r = plan("reject 2")
    assert r.steps[0].key == "ci.competitor_reject" and r.steps[0].slots["candidate_id"] == str(q[2]["id"])
    assert [s.key for s in plan("approve the first two").steps] == ["ci.competitor_approve"] * 2


def test_an_out_of_range_number_is_not_guessed(monkeypatch) -> None:
    World(monkeypatch, queue=[cand(1), cand(2)])
    p = plan("track 7")
    assert p.kind == "CANDIDATES" and not p.steps and "Which ones" in p.text


def test_without_candidates_a_decision_phrase_falls_through_and_the_list_says_none(monkeypatch) -> None:
    World(monkeypatch)
    assert plan("track 2") is None
    assert "no competitor candidates" in plan("show me what you found").text


def test_the_candidate_list_labels_them_as_leads_not_prices(monkeypatch) -> None:
    World(monkeypatch, queue=[cand(1), cand(2, rel="UNKNOWN")])
    text = plan("show me the candidates").text
    assert "not verified prices" in text and "1. A listing on Amazon" in text and "2. A listing on Amazon that is not classified yet" in text and "₹" not in text


def test_yes_is_never_a_candidate_approval(monkeypatch) -> None:
    World(monkeypatch, queue=[cand(1)])
    assert plan("yes 1") is None and plan("no 1") is None


# ---- finding ------------------------------------------------------------------------
def test_a_finding_id_plans_a_single_explain_step(monkeypatch) -> None:
    World(monkeypatch)
    fid = uuid4()
    p = plan("tell me about this", finding_id=fid)
    assert p.kind == "EXPLAIN_FINDING" and p.steps == (cc.Step("ci.explain_finding", {"finding_id": str(fid)}),)


# ---- composing ----------------------------------------------------------------------
def _intake_plan(label="Titan Octane"):
    return cc.Plan("INTAKE", steps=(cc.Step("ci.evidence_intake", {}),), context={"label": label})


def test_the_intake_reply_shows_what_was_read_as_unconfirmed_and_says_how_to_answer() -> None:
    payload = {"status": "NEEDS_CONFIRMATION", "summary": {"rating": "4.2", "ratingCount": 5400},
               "questions": [{"field": "listed_price_paise", "proposedValue": 269900}, {"field": "availability", "proposedValue": "IN_STOCK"}]}
    text = cc.compose(_intake_plan(), [(None, leg(payload))])
    assert "₹2,699.00" in text and "in stock" in text and "rating 4.2 from 5400 ratings" in text and cc.CONFIRM_MARKER in text and "skip" in text
    assert "not using these" in text


def test_a_rejected_or_duplicate_screenshot_says_so_and_that_nothing_was_stored() -> None:
    assert "too blurry" in cc.compose(_intake_plan(), [(None, leg({"status": "REJECTED_QUALITY", "qualityReason": "TOO_BLURRY"}))])
    assert "Nothing was stored" in cc.compose(_intake_plan(), [(None, leg({"status": "REJECTED_QUALITY", "qualityReason": "TOO_BLURRY"}))])
    assert "already have exactly this screenshot" in cc.compose(_intake_plan(), [(None, leg({"status": "DUPLICATE"}))])
    assert "fresh capture" in cc.compose(_intake_plan(), [(None, leg({"status": "NEAR_DUPLICATE"}))])


def test_a_denied_or_failed_leg_never_claims_success() -> None:
    assert "did not do that" in cc.compose(_intake_plan(), [(None, leg(None, status="DENIED"))])
    assert "nothing was changed" in cc.compose(_intake_plan(), [(None, leg(None, status="FAILED"))])
    assert "screenshot reader is not switched on" in cc.compose(_intake_plan(), [(None, leg({"status": "REFUSED", "code": "VISION_ENDPOINT_NOT_VERIFIED"}))])
    assert "could not find that attachment" in cc.compose(_intake_plan(), [(None, leg({"status": "REFUSED", "code": "ATTACHMENT_NOT_FOUND"}))])


def test_a_confirmed_reply_states_a_verified_change_only_when_there_is_one() -> None:
    plan_ = cc.Plan("CONFIRM", steps=(cc.Step("ci.confirm_field", {}),), context={"corrected": ["listed_price_paise"], "declined": []})
    text = cc.compose(plan_, [(None, leg({"priceConfirmation": "CONFIRMED", "stillOpen": [], "verifiedChange": {"deltaPct": "-9.2", "direction": "DECREASE"}}))])
    assert "confirmed" in text.lower() and "down 9.2%" in text and "your corrected price" in text
    assert "down" not in cc.compose(plan_, [(None, leg({"priceConfirmation": "CONFIRMED", "stillOpen": [], "verifiedChange": None}))])
    waiting = cc.compose(plan_, [(None, leg({"priceConfirmation": "PENDING", "stillOpen": [{"field": "availability"}]}))])
    assert "stock status" in waiting and cc.CONFIRM_MARKER in waiting  # still awaiting, so a short "yes" next is read as the answer


def test_a_declined_reply_says_the_screenshot_will_not_be_used() -> None:
    plan_ = cc.Plan("CONFIRM", steps=(cc.Step("ci.confirm_field", {}),), context={"declined": ["x"]})
    assert "will not be used for prices" in cc.compose(plan_, [(None, leg({"priceConfirmation": "DECLINED", "stillOpen": []}))])


def test_the_finding_reply_cites_evidence_and_refuses_margin_claims() -> None:
    payload = {"findingType": "PRICE_CHANGE", "confidence": "DERIVED", "sellerConfirmation": "CONFIRMED", "sampleSize": None,
               "payload": {"label": "Titan Octane", "deltaPaise": -27100, "deltaPct": "-9.2", "direction": "DECREASE", "fromPricePaise": 297000, "toPricePaise": 269900, "evidenceDate": "2026-10-18T08:00:00+00:00"},
               "evidence": [{"evidenceId": "e1"}]}
    text = cc.compose(cc.Plan("EXPLAIN_FINDING", steps=(cc.Step("ci.explain_finding", {}),)), [(None, leg(payload))])
    assert "₹2,970.00 to ₹2,699.00" in text and "9.2%" in text and "1 screenshot you sent" in text and "2026-10-18" in text
    assert "not worked out what this means for your margin" in text
    assert "margin is" not in text.lower() and "contribution" not in text.lower() and "break-even" not in text.lower()  # no margin claim: Layer 1 only (C26)


def test_a_finding_without_evidence_is_not_relied_on() -> None:
    payload = {"findingType": "FRESHNESS", "confidence": "DERIVED", "sellerConfirmation": "NOT_REQUIRED", "payload": {"label": "Fossil", "evidenceDate": "2026-09-01"}, "evidence": []}
    text = cc.compose(cc.Plan("EXPLAIN_FINDING", steps=(cc.Step("ci.explain_finding", {}),)), [(None, leg(payload))])
    assert "no screenshot behind it" in text and "cannot say what it costs now" in text


def test_a_missing_finding_is_not_found_not_an_error() -> None:
    text = cc.compose(cc.Plan("EXPLAIN_FINDING", steps=(cc.Step("ci.explain_finding", {}),)), [(None, leg({"status": "REFUSED", "code": "FINDING_NOT_FOUND"}))])
    assert "could not find that finding" in text


def test_every_reply_passes_the_no_live_monitoring_rule() -> None:
    samples = [
        cc.compose(_intake_plan(), [(None, leg({"status": "STORED", "questions": [], "summary": {}}))]),
        cc.compose(cc.Plan("ADD_COMPETITORS", steps=(cc.Step("ci.competitor_add", {"url": "https://www.amazon.in/dp/B09ABC1234"}),)), [(cc.Step("ci.competitor_add", {"url": "https://www.amazon.in/dp/B09ABC1234"}), leg({"status": "OK"}))]),
        cc.compose(cc.Plan("DECIDE_CANDIDATES", steps=(cc.Step("x", {}),), context={"positions": [1, 3], "decision": "APPROVE"}), [(None, leg({"status": "OK"}))]),
    ]
    for t in samples:
        assert ci_conv_data.currency_claims(t) == [], t


def test_a_reply_that_would_claim_live_tracking_is_replaced() -> None:
    assert "do not watch competitors" in cc._guard("I am tracking Titan in real time")


def test_adding_a_competitor_says_there_is_no_price_until_a_screenshot() -> None:
    step = cc.Step("ci.competitor_add", {"url": "https://www.amazon.in/dp/B09ABC1234"})
    text = cc.compose(cc.Plan("ADD_COMPETITORS", steps=(step,)), [(step, leg({"status": "OK"}))])
    assert "Tracking amazon.in/dp/B09ABC1234" in text and "no price for a competitor until you send me a screenshot" in text
    bad = cc.compose(cc.Plan("ADD_COMPETITORS", steps=(step,)), [(step, leg({"status": "NOT_ALLOWLISTED"}))])
    assert "only track amazon.in" in bad


# ---- alert preferences ---------------------------------------------------------------
def test_quiet_hours_are_read_from_plain_words_and_default_to_india_time(monkeypatch) -> None:
    World(monkeypatch)
    p = plan("set quiet hours 10pm to 7am")
    assert p.kind == "ALERT_SETTINGS" and p.steps[0].slots == {"quiet_start": "22:00", "quiet_end": "07:00", "quiet_tz": "Asia/Kolkata"}
    p2 = plan("quiet hours from 9:30 pm until 6:15 am UTC")
    assert p2.steps[0].slots == {"quiet_start": "21:30", "quiet_end": "06:15", "quiet_tz": "UTC"}


def test_quiet_hours_use_the_sellers_configured_timezone_when_there_is_one(monkeypatch) -> None:
    World(monkeypatch, tz="Asia/Dubai")
    assert plan("set quiet hours 10pm to 7am").steps[0].slots["quiet_tz"] == "Asia/Dubai"
    World(monkeypatch, tz="Not/AZone")  # an unusable setting falls back to India time, it never blocks the seller
    assert plan("set quiet hours 10pm to 7am").steps[0].slots["quiet_tz"] == "Asia/Kolkata"


def test_what_product_ideas_did_you_find_is_not_the_competitor_candidate_list(monkeypatch) -> None:
    World(monkeypatch, queue=[cand(1)])
    assert plan("What product ideas did you find?") is None
    assert plan("what competitors did you find?").kind == "CANDIDATES"


def test_quiet_hours_can_be_turned_off_and_a_threshold_set(monkeypatch) -> None:
    World(monkeypatch)
    assert plan("turn off quiet hours").steps[0].slots == {"clear_quiet": True}
    assert plan("alert me when a competitor's price changes by more than 8%").steps[0].slots == {"price_threshold_pct": "8"}
    assert plan("tell me if the price drops 12.5%").steps[0].slots == {"price_threshold_pct": "12.5"}


def test_unreadable_quiet_hours_are_asked_about_and_nothing_is_saved(monkeypatch) -> None:
    World(monkeypatch)
    p = plan("quiet hours 25 to 7")
    assert p.kind == "ALERT_SETTINGS_ASK" and not p.steps and "Nothing was changed" in p.text


def test_the_settings_reply_echoes_what_is_now_in_force_and_names_the_timezone() -> None:
    plan_ = cc.Plan("ALERT_SETTINGS", steps=(cc.Step("ci.alert_settings_set", {}),), context={"asked": ["price_threshold_pct", "quiet_end", "quiet_start", "quiet_tz"]})
    text = cc.compose(plan_, [(None, leg({"quietHours": {"start": "22:00", "end": "07:00", "timezone": "Asia/Kolkata"}, "priceThresholdPct": "8.00", "cleared": False}))])
    assert "22:00 to 07:00 India time (IST)" in text and "held and shown when it ends" in text and "8.00%" in text
    off = cc.compose(cc.Plan("ALERT_SETTINGS", steps=(cc.Step("x", {}),), context={"asked": ["clear_quiet"]}), [(None, leg({"quietHours": None, "priceThresholdPct": "5.00", "cleared": True}))])
    assert "Quiet hours are off" in off
    bad = cc.compose(plan_, [(None, leg({"status": "REFUSED", "code": "INVALID_THRESHOLD"}))])
    assert "between 1% and 50%" in bad


# ---- delivery and offers (C44) -------------------------------------------------------
def _asked_with_delivery(monkeypatch):
    snap = uuid4()
    reqs = [req("listed_price_paise", 269900, snap, 1), req("delivery_charge_paise", 4900, snap, 2), req("offers", [{"kind": "COUPON", "amount_paise": 10000, "condition_text": None}], snap, 3)]
    World(monkeypatch, open_requests=reqs)
    return reqs


def test_delivery_is_corrected_separately_from_the_price(monkeypatch) -> None:
    reqs = _asked_with_delivery(monkeypatch)
    p = plan("price is 2699 and delivery is 49", last_ceo_text=cc.CONFIRM_MARKER)
    vals = {a["info_request_id"]: a["value"] for a in p.steps[0].slots["answers"]}
    assert vals == {str(reqs[0]["id"]): 269900, str(reqs[1]["id"]): 4900}  # the delivery amount is not read as a second price (which would make the price ambiguous)


def test_free_delivery_is_an_observed_zero(monkeypatch) -> None:
    reqs = _asked_with_delivery(monkeypatch)
    p = plan("the price is 2699, free delivery", last_ceo_text=cc.CONFIRM_MARKER)
    vals = {a["info_request_id"]: a["value"] for a in p.steps[0].slots["answers"]}
    assert vals[str(reqs[1]["id"])] == 0 and vals[str(reqs[0]["id"])] == 269900


def test_yes_accepts_the_offers_as_read_and_skip_declines_them(monkeypatch) -> None:
    reqs = _asked_with_delivery(monkeypatch)
    yes = plan("yes", last_ceo_text=cc.CONFIRM_MARKER).steps[0].slots["answers"]
    assert {a["info_request_id"]: a["value"] for a in yes}[str(reqs[2]["id"])] == [{"kind": "COUPON", "amount_paise": 10000, "condition_text": None}]
    skip = plan("skip", last_ceo_text=cc.CONFIRM_MARKER).steps[0].slots
    assert str(reqs[2]["id"]) in skip["declined"] and skip["answers"] == []


def test_the_question_shows_delivery_and_offers_and_says_conditional_offers_are_not_counted() -> None:
    payload = {"status": "NEEDS_CONFIRMATION", "summary": {}, "questions": [
        {"field": "delivery_charge_paise", "proposedValue": 4900}, {"field": "offers", "proposedValue": [
            {"kind": "COUPON", "amount_paise": 10000, "condition_text": None}, {"kind": "BANK_OFFER", "amount_paise": 25000, "condition_text": "HDFC cards"}]}]}
    text = cc.compose(_intake_plan(), [(None, leg(payload))])
    assert "delivery charge ₹49.00" in text and "coupon ₹100.00 off" in text and "bank offer ₹250.00 off (HDFC cards, which I will not count in the price)" in text
    assert "free delivery" in text  # the correction examples
    free = cc.compose(_intake_plan(), [(None, leg({"status": "NEEDS_CONFIRMATION", "summary": {}, "questions": [{"field": "delivery_charge_paise", "proposedValue": 0}]}))])
    assert "free delivery" in free


def test_no_discount_or_discount_zero_is_an_explicit_correction_to_zero() -> None:
    fields = ["listed_price_paise", "visible_discount_paise"]
    for words in ("no discount", "discount 0", "discount is zero", "price is 2299, discount 0"):
        corrections, _, _ = cc.parse_confirmation(words, fields)
        assert corrections.get("visible_discount_paise") == 0, words
    assert cc.parse_confirmation("price is 2299, discount 0", fields)[0]["listed_price_paise"] == 229900
    assert cc.parse_confirmation("discount 150", fields)[0]["visible_discount_paise"] == 15000
    assert "visible_discount_paise" not in cc.parse_confirmation("discount 150", ["listed_price_paise"])[0]


def test_a_question_about_competitors_does_not_pick_up_an_old_unread_image(monkeypatch) -> None:
    World(monkeypatch)
    assert plan("what do customers complain about at my competitors", latest_attachments=[IMG]) is None
    assert plan("how are my competitors doing?", latest_attachments=[IMG]) is None
    assert plan("this is Titan Octane", latest_attachments=[IMG]).kind == "INTAKE"  # naming it still picks the waiting image up
