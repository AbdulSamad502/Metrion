"""CHECKPOINT 3 + 6: a product photo attached in the CEO chat reaches the CMO BY REFERENCE and nothing is guessed from it
(ceo-cmo-delegation.md CD2, CD5, CD10, CD11, 6.4, 6.5; AC-D*).

One HTTP end-to-end flow over the REAL app, registry, CMO handlers, generator, image normaliser and Postgres. Only the CMO's text model and the vision model are deterministic fakes:

  attach photo -> "titles for this on Amazon" -> small 0-unit image-analysis plan card (nothing read yet) -> typed "yes" ignored -> Approve -> labelled observations + the CEO asks
  the seller to confirm / correct -> seller answers -> the generation plan card holds ONLY the confirmed facts -> Approve -> titles with code-counted lengths ->
  the read-only showcase shows them for tenant A and not for tenant B.

Plus: a failed vision run and a failed generation charge nothing; an endpoint that is not attested in LLM_OPERATOR_CONTROLLED_HOSTS stops the hand-off before a byte is read."""

from __future__ import annotations

import dataclasses
import os
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import text

from slim_cmo.vision.provider import VisionUnavailable

from backend import config
from backend.repositories import investigation_plan_repo as plan_repo
from backend.services import cmo_attachment, cmo_runtime
from backend.services.cmo_actions import Principal

from .test_ceo_cmo_delegation import approve, chat, cmo_counts, messages, new_investigation, say  # noqa: F401
from .test_cmo_api import TITLES, _erase_cmo_rows, ctx_engine, env, fake_clerk  # noqa: F401
from .test_cmo_images_api import GOOD, MODEL, SECRET, FakeVision, _runtime, jpeg

pytestmark = pytest.mark.skipif(not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL"), reason="needs a live Postgres")

HOST = "vision.internal.test:11434"
ASK = "give me titles for this on Amazon"


class Photo:
    def __init__(self, c, vision, tmp_path, monkeypatch):
        self.c, self.vision, self.dir, self.monkeypatch = c, vision, tmp_path, monkeypatch

    def upload(self, inv, data=None, name="shelf-photo.jpg", ctype="image/jpeg", headers=None):
        r = self.c.client.post(f"/api/v1/ceo/investigations/{inv}/attachments", files={"file": (name, data if data is not None else jpeg(exif=True), ctype)},
                               headers=headers or self.c.env.headers)
        assert r.status_code == 201, r.text
        return r.json()["id"]

    def turn(self, inv, message, attachment_ids=()):
        r = self.c.client.post(f"/api/v1/ceo/investigations/{inv}/turns", json={"message": message, "attachment_ids": list(attachment_ids)}, headers=self.c.env.headers)
        assert r.status_code == 200, r.text
        return r.json()

    def assets(self) -> int:
        return self.c.env.n("seller_image_asset")


@pytest.fixture
def photo(chat, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.setenv("CEO_ATTACHMENT_MAX_BYTES", "1000000")
    monkeypatch.setenv("CEO_ATTACHMENT_MAX_FILES", "5")
    monkeypatch.setenv("CEO_ATTACHMENT_MAX_PAGES", "5")
    monkeypatch.setenv("CMO_VISION_MODEL", MODEL)
    monkeypatch.setenv("CMO_VISION_OLLAMA_HOST", f"http://{HOST}")
    monkeypatch.setenv("LLM_OPERATOR_CONTROLLED_HOSTS", HOST)
    for fn in (config.cmo_vision_model, config.cmo_vision_ollama_host):
        fn.cache_clear()
    vision = FakeVision()
    rt = _runtime(vision, tmp_path)
    monkeypatch.setattr(cmo_runtime, "build_image_runtime", lambda *, need_vision, clock=cmo_runtime.utc_now: rt)
    yield Photo(chat, vision, tmp_path, monkeypatch)
    for fn in (config.cmo_vision_model, config.cmo_vision_ollama_host):
        fn.cache_clear()


def counts(p: Photo) -> dict:
    return {**cmo_counts(p.c), "vision_calls": p.vision.calls, "assets": p.assets()}


NOTHING = {"generations": 0, "cmo_events": 0, "ceo_events": 0, "model_calls": 0, "vision_calls": 0, "assets": 0}


def plan_the_reading(p: Photo):
    inv = new_investigation(p.c)
    att = p.upload(inv)
    planned = p.turn(inv, ASK, [att])
    return inv, att, planned


def read_the_photo(p: Photo):
    inv, att, planned = plan_the_reading(p)
    r = approve(p.c, inv, planned["plan"])
    assert r.status_code == 200, r.text
    return inv, att, planned, r.json()


def confirm_facts(p: Photo, inv: str):
    """The seller answers the CEO's questions in order: the product (typed), a CORRECTED colour, the material and brand as read, the size skipped, no category, and the skippable extra details skipped."""
    asked = []
    answers = ["steel water bottle", "silver", "steel", "skip", "AquaKeep", "skip", "skip", "skip"]  # ... then no category, no key features, no main use (the 9th question, search words, is dropped at the limit of 8)
    last = None
    for a in answers:
        last = say(p.c, inv, a)
        asked.append(last["answer"])
    return last, asked


# ================================================================================================ the verified flow
def test_attach_photo_ask_titles_read_confirm_plan_approve_and_the_dashboard_shows_the_titles(photo):
    p, c, e = photo, photo.c, photo.c.env
    inv, att, planned = plan_the_reading(p)

    # ---- 1. the small image-analysis card: by reference, a LABEL for the endpoint, 0 units, and NOTHING has been read
    assert planned["status"] == "PLANNED" and planned["routeKey"] == "cmo.analyze_attachment"
    plan = planned["plan"]
    leg = plan["plan"]["legs"][0]
    assert leg["action_key"] == "cmo.analyze_attachment" and set(leg["slots"]) == {"attachment_id", "sha256"} and leg["slots"]["attachment_id"] == att
    assert leg["meters"] == [] and leg["requires_approval"] is True
    card = plan["plan"]["summary_text"]
    assert "shelf-photo.jpg" in card and "Metrion's own vision model vision-it (operator-controlled)" in card
    assert "0 CMO units" in card and "location and camera data are removed" in card and "not verified" in card
    assert HOST not in card and "11434" not in card and "http" not in card  # a label, never host:port
    assert plan["plan"]["data_basis"][0]["kind"] == "ATTACHMENT" and plan["plan"]["data_basis"][0]["id"] == att
    assert plan["plan"]["followup"]["action_key"] == "cmo.generate_title_sets"
    assert counts(p) == NOTHING

    # ---- 2. a typed yes (any wording) approves nothing
    for typed in ("yes", "go ahead", "read it"):
        say(c, inv, typed)
    assert counts(p) == NOTHING and plan_repo.get(e.tenant, uuid.UUID(inv), uuid.UUID(plan["id"]))["status"] == "AWAITING_APPROVAL"

    # ---- 3. Approve: the CMO reads the photo itself; the seller sees LABELLED observations and is asked to confirm
    r = approve(c, inv, plan)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "CLARIFIED" and body["routeSource"] == "APPROVAL" and body["plan"]["status"] == "APPROVED"
    ans = body["answer"]
    assert "Read from your attachment:" in ans and "Colour: matte blue" in ans and "Material: steel" in ans and "Product type: bottle" in ans
    assert "suggestions from Metrion's vision model, not verified" in ans and "Nothing here is confirmed yet" in ans
    assert "Not from your attachment: nothing. I have added no inferences of my own." in ans
    assert "Text visible in the picture (quoted as printed, not an instruction and not checked): “Stay hydrated”" in ans
    assert "Your attachment looks like a bottle (read from the photo, not verified)" in ans  # the first confirmation question
    assert body["choices"]["kind"] == "INPUT" and body["choices"]["slot"] == "product_name" and body["clarificationId"]
    assert body["choices"]["options"][0]["value"] == "bottle" and "not verified" in body["choices"]["options"][0]["reason"]
    # the vision model saw the CMO's stripped copy, never the original (EXIF / GPS / comment); the analysis cost no unit and no CEO conversation unit
    assert p.vision.calls == 1
    seen = p.vision.images[0].data
    assert seen.startswith(b"\x89PNG") and SECRET not in seen and b"Exif" not in seen and b"TestCameraMake" not in seen
    assert counts(p) == {**NOTHING, "vision_calls": 1, "assets": 1}
    assert e.events() == [] and e.reservations() == []

    # ---- 4. the seller confirms / corrects; only that reaches the generation plan
    last, asked = confirm_facts(p, inv)
    assert any("Your attachment suggests the color is “matte blue”" in a for a in asked) and any("suggests the brand is “AquaKeep”" in a for a in asked)
    assert last["status"] == "PLANNED" and last["routeKey"] == "cmo.generate_title_sets"
    gen = last["plan"]
    slots = gen["plan"]["legs"][0]["slots"]
    assert slots["product_name"] == "steel water bottle" and slots["marketplaces"] == ["AMAZON"] and slots["brand"] == "AquaKeep"
    assert slots["attributes"] == [{"name": "Color", "value": "silver"}, {"name": "Material", "value": "steel"}]  # the CORRECTED colour; the skipped size is absent
    flat = str(slots)
    assert "matte blue" not in flat and "Stay hydrated" not in flat and "image_analysis_id" not in slots and "attachment" not in flat  # no unconfirmed observation, no photo text
    assert "Product facts you confirmed (your own statements, passed as you gave them): Brand: AquaKeep; Color: silver; Material: steel." in gen["plan"]["summary_text"]
    assert "Slim CMO (recommend-only) will write listing title options for steel water bottle on Amazon" in gen["plan"]["summary_text"]
    assert counts(p)["generations"] == 0 and gen["status"] == "AWAITING_APPROVAL"

    # ---- 5. a SECOND, separate approval runs the writing; counted by code; one CMO unit and one CEO conversation unit
    done = approve(c, inv, gen)
    assert done.status_code == 200, done.text
    out = done.json()
    assert out["status"] == "DELIVERED" and out["routeKey"] == "cmo.generate_title_sets"
    for title in TITLES:
        assert title in out["answer"] and "characters)" not in out["answer"]
    assert "Written by Slim CMO (recommend-only)" in out["answer"] and "Used from your plan: 1 CMO unit." in out["answer"]
    assert counts(p) == {"generations": 1, "cmo_events": 1, "ceo_events": 1, "model_calls": 1, "vision_calls": 1, "assets": 1}
    # ---- 6. the read-only dashboard shows it for this tenant and not for another
    shown = c.client.get("/api/v1/cmo/showcase/titles?marketplace=AMAZON", headers=e.headers).json()["items"]
    assert [i["titleText"] for i in shown] == TITLES and all(i["charCount"] == len(i["titleText"]) for i in shown)
    other_id, other_headers = e.other_tenant()
    assert c.client.get("/api/v1/cmo/showcase/titles?marketplace=AMAZON", headers=other_headers).json()["items"] == []


# ================================================================================================ failures charge nothing
def test_a_failed_vision_run_says_so_plainly_and_charges_nothing(photo):
    p, c = photo, photo.c
    p.vision.error = VisionUnavailable("down")
    inv, att, planned = plan_the_reading(p)
    r = approve(c, inv, planned["plan"])
    body = r.json()
    assert r.status_code == 200 and body["status"] == "FAILED" and body["choices"] is None
    assert "I could not read that photo" in body["answer"] and "have not guessed anything from it" in body["answer"] and "Nothing was used up" in body["answer"]
    after = counts(p)
    assert after["cmo_events"] == 0 and after["ceo_events"] == 0 and after["generations"] == 0 and c.env.reservations() == []
    assert c.client.get("/api/v1/cmo/showcase/titles?marketplace=AMAZON", headers=c.env.headers).json()["items"] == []


def test_a_failed_generation_after_confirming_the_photo_facts_charges_nothing(photo):
    p, c, e = photo, photo.c, photo.c.env
    inv, att, planned, read = read_the_photo(p)
    last, _ = confirm_facts(p, inv)
    e.provider.mode = "garbage"  # the CMO's text model returns nonsense: every artefact fails
    r = approve(c, inv, last["plan"])
    body = r.json()
    assert r.status_code == 200 and body["status"] == "FAILED" and "I could not complete this plan" in body["answer"] and "not charged to your plan" in body["answer"]
    after = counts(p)
    assert after["cmo_events"] == 0 and after["ceo_events"] == 0 and e.reservations() in ([], ["RELEASED"])
    assert c.client.get("/api/v1/cmo/showcase/titles?marketplace=AMAZON", headers=e.headers).json()["items"] == []


# ================================================================================================ endpoint trust: refuse BEFORE any byte is read
def test_an_endpoint_not_in_the_operator_controlled_list_builds_no_plan_and_sends_nothing(photo):
    p = photo
    p.monkeypatch.setenv("LLM_OPERATOR_CONTROLLED_HOSTS", "somewhere.else:1")
    inv = new_investigation(p.c)
    att = p.upload(inv)
    res = p.turn(inv, ASK, [att])
    assert res["status"] == "FAILED" and "plan" not in res
    assert "not available" in res["answer"] and "I did not read your photo" in res["answer"] and "11434" not in res["answer"]
    assert plan_repo.list_for_investigation(p.c.env.tenant, uuid.UUID(inv)) == []
    assert counts(p) == NOTHING


def test_an_endpoint_that_stops_being_attested_before_approval_refuses_the_approval_and_sends_nothing(photo):
    p, c = photo, photo.c
    inv, att, planned = plan_the_reading(p)
    p.monkeypatch.setenv("LLM_OPERATOR_CONTROLLED_HOSTS", "somewhere.else:1")
    r = approve(c, inv, planned["plan"])
    assert r.status_code == 409 and r.json()["detail"]["code"] == "INTEGRATION_UNAVAILABLE"
    assert counts(p) == NOTHING
    assert plan_repo.get(c.env.tenant, uuid.UUID(inv), uuid.UUID(planned["plan"]["id"]))["status"] == "AWAITING_APPROVAL"


def test_the_cmo_handler_itself_refuses_an_unattested_endpoint_before_reading_the_stored_bytes(photo, monkeypatch):
    p, e = photo, photo.c.env
    inv = new_investigation(p.c)
    att = p.upload(inv)
    monkeypatch.setenv("LLM_OPERATOR_CONTROLLED_HOSTS", "somewhere.else:1")

    def never(*a, **k):
        raise AssertionError("the photo's bytes were read although the vision endpoint is not operator-controlled")

    monkeypatch.setattr(cmo_attachment.repo, "get_attachment_contents", never)
    with pytest.raises(HTTPException) as exc:
        cmo_attachment.analyze_attachment(Principal(e.tenant, e.user_id), uuid.UUID(inv), uuid.UUID(att), None)
    assert exc.value.status_code == 503 and counts(p) == NOTHING


# ================================================================================================ reference validation and isolation
def test_a_reference_is_validated_against_tenant_and_conversation(photo):
    p, c, e = photo, photo.c, photo.c.env
    inv = new_investigation(c)
    att = p.upload(inv)
    other_inv = new_investigation(c)
    with pytest.raises(HTTPException) as other_conversation:  # the CMO's own read re-validates: another conversation's id is "not found"
        cmo_attachment.analyze_attachment(Principal(e.tenant, e.user_id), uuid.UUID(other_inv), uuid.UUID(att), None)
    assert other_conversation.value.status_code == 404
    other_tenant, _ = e.other_tenant()
    with pytest.raises(HTTPException) as other:  # another tenant cannot name it at all (RLS)
        cmo_attachment.analyze_attachment(Principal(other_tenant, e.user_id), uuid.UUID(inv), uuid.UUID(att), None)
    assert other.value.status_code == 404
    with pytest.raises(HTTPException) as changed:  # a hash the CEO never saw fails closed
        cmo_attachment.analyze_attachment(Principal(e.tenant, e.user_id), uuid.UUID(inv), uuid.UUID(att), "0" * 64)
    assert changed.value.status_code == 409
    assert counts(p) == NOTHING
    r = c.client.post(f"/api/v1/ceo/investigations/{other_inv}/turns", json={"message": ASK, "attachment_ids": [att]}, headers=e.headers)
    assert r.status_code >= 400 and counts(p) == NOTHING  # naming it in the wrong conversation is refused before anything is written


# ================================================================================================ no image / not an image
def test_titles_with_no_photo_and_no_details_ask_to_attach_one_or_type_the_details(photo):
    p, c = photo, photo.c
    inv = new_investigation(c)
    res = say(c, inv, "give me titles")
    assert res["status"] == "CLARIFIED" and res["choices"]["slot"] == "product_name"
    assert "attach a photo" in res["answer"] and "Name it the way a buyer would search for it" in res["answer"]
    assert counts(p) == NOTHING


def test_a_non_image_attachment_is_said_plainly_and_never_sent_to_the_vision_model(photo):
    p, c = photo, photo.c
    inv = new_investigation(c)
    att = p.upload(inv, data=b"sku,price\nA,100\n", name="prices.csv", ctype="text/csv")
    res = p.turn(inv, ASK, [att])
    assert res["status"] == "CLARIFIED" and "not a picture I can read" in res["answer"] and "I did not use it" in res["answer"]
    assert res["routeKey"] != "cmo.analyze_attachment" and plan_repo.list_for_investigation(c.env.tenant, uuid.UUID(inv)) == []
    assert counts(p) == NOTHING


def test_an_unreadable_image_is_said_plainly_and_nothing_is_guessed(photo):
    p, c = photo, photo.c
    p.vision.reply = "this is not json at all"  # the vision model answers nonsense: a FAILED analysis, 0 units
    inv, att, planned = plan_the_reading(p)
    body = approve(c, inv, planned["plan"]).json()
    assert body["status"] == "FAILED" and "have not guessed anything from it" in body["answer"] and body["choices"] is None
    assert counts(p)["cmo_events"] == 0 and counts(p)["ceo_events"] == 0


# ================================================================================================ task C: the rest of the copy, from chat
@pytest.mark.parametrize("ask,key,shown", [
    ("write bullets for my steel bottle on Amazon", "cmo.generate_bullets", "Bullet points for Amazon"),
    ("write backend search terms for my steel bottle on Amazon", "cmo.generate_backend_terms", "Backend search terms for Amazon"),
    ("give me the listing copy for my steel bottle on Amazon", "cmo.generate_listing_copy", "Listing copy for Amazon"),
])
def test_bullets_backend_terms_and_listing_copy_are_asked_planned_approved_and_shown_on_the_dashboard(photo, ask, key, shown):
    p, c, e = photo, photo.c, photo.c.env
    inv = new_investigation(c)
    q = say(c, inv, ask)
    assert q["status"] == "CLARIFIED" and q["choices"]["slot"] == "seller_title"  # the product and marketplace were said; the title it is grounded on is asked, never invented
    planned = say(c, inv, "Steel Bottle 1L Insulated")
    while planned["status"] == "CLARIFIED" and str(planned["choices"]["slot"]).startswith("fact_"):  # the skippable extra details (brand, size, features; Amazon backend terms: brand, features)
        planned = say(c, inv, "skip")
    assert planned["status"] == "PLANNED" and planned["routeKey"] == key and planned["plan"]["plan"]["legs"][0]["meters"][0]["units"] == 1
    assert cmo_counts(c)["generations"] == 0
    done = approve(c, inv, planned["plan"])
    assert done.status_code == 200, done.text
    out = done.json()
    assert out["status"] == "DELIVERED" and shown in out["answer"] and "Used from your plan: 1 CMO unit." in out["answer"], out["answer"]
    assert cmo_counts(c)["generations"] == 1 and cmo_counts(c)["cmo_events"] == 1
    if key == "cmo.generate_listing_copy":  # the dashboard's Copy Pack section fills from the chat-made listing copy
        packs = c.client.get("/api/v1/cmo/showcase/copy-packs?marketplace=AMAZON", headers=e.headers)
        assert packs.status_code == 200 and len(packs.json()["items"]) == 1, packs.text
