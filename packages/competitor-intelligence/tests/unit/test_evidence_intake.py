"""§6.22–§6.23 — the CEO Hub intake pipeline, against in-memory fakes (no database, no model)."""

from __future__ import annotations

import io
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from PIL import Image, ImageDraw

from competitor_intelligence.direct_path import evidence_intake as ei
from competitor_intelligence.direct_path.evidence_intake import IntakeStatus, intake_screenshot, settle_confirmation
from competitor_intelligence.intake.events import CiEvent

TENANT, USER, URL_ID = uuid4(), uuid4(), uuid4()
NOW = datetime(2026, 10, 18, tzinfo=timezone.utc)


def _png(seed: int = 0) -> bytes:
    img = Image.new("RGB", (800, 600), "white")
    d = ImageDraw.Draw(img)
    for i in range(0, 800, 12 + seed):
        d.rectangle([i, 0, i + 5, 600], fill="black")
    d.text((20, 20), f"Rs {2000 + seed}", fill="red")
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


class _Writer:
    def __init__(self) -> None:
        self.written: list[bytes] = []

    def write(self, data: bytes) -> str:
        self.written.append(data)
        return f"img-{len(self.written)}.png"


class World:
    """One shared in-memory state behind every repository the intake touches."""

    def __init__(self, monkeypatch, *, snapshot_fields: list[dict], url_exists: bool = True) -> None:
        self.events: list[tuple] = []
        self.evidence: dict = {}
        self.metadata: dict = {}
        self.requests: dict = {}
        self.confirmation: dict = {}
        self.snapshot_fields = snapshot_fields
        self.session_calls: list[dict] = []
        self.corrections: list[dict] = []
        snapshot_id, self.snapshot_id = uuid4(), None
        self.snapshot_id = snapshot_id
        self.evidence_id = uuid4()
        w = self

        monkeypatch.setattr(ei, "competitor_url_repo", SimpleNamespace(get_by_ids=lambda t, ids: [{"id": URL_ID}] if url_exists else []))
        monkeypatch.setattr(ei, "ci_event_repo", SimpleNamespace(record=lambda t, ev, **kw: w.events.append((ev, kw.get("detail", {}), kw.get("object_id")))))
        monkeypatch.setattr(
            ei,
            "competitor_evidence_repo",
            SimpleNamespace(
                find_by_sha=lambda t, sha: w.evidence.get(sha),
                list_perceptual_hashes=lambda t, competitor_url_id=None: [{"id": k, "perceptual_hash": v} for k, v in w.metadata.items() if v],
                get_by_research_session=lambda t, rs: [{"id": w.evidence_id, "extraction_status": "EXTRACTED"}],
                set_intake_metadata=lambda t, eid, **kw: w.metadata.__setitem__(eid, kw.get("perceptual_hash")) or w.evidence.__setitem__(kw["content_sha256"], {"id": eid}),
            ),
        )
        monkeypatch.setattr(ei, "competitor_snapshot_field_repo", SimpleNamespace(get_fields=lambda t, sid: w.snapshot_fields))

        def create_request(t, **kw):
            rid = uuid4()
            w.requests[rid] = {"id": rid, "status": "OPEN", "answered_value": None, "snapshot_id": kw["snapshot_id"], **kw}
            return rid

        def answer(t, rid, *, value, answered_by, now=None):
            r = w.requests.get(rid)
            if r is None:
                return None
            if r["status"] == "OPEN":
                r.update(status="ANSWERED", answered_value=value)
            return r

        def decline(t, rid, *, answered_by, now=None):
            r = w.requests.get(rid)
            if r is not None and r["status"] == "OPEN":
                r.update(status="DECLINED")
            return r

        monkeypatch.setattr(
            ei,
            "ci_info_request_repo",
            SimpleNamespace(
                create=create_request,
                get=lambda t, rid: w.requests.get(rid),
                answer=answer,
                decline=decline,
                list_open=lambda t, snapshot_id=None, competitor_url_id=None: [r for r in w.requests.values() if r["status"] == "OPEN"],
                list_for_snapshot=lambda t, sid: list(w.requests.values()),
            ),
        )
        monkeypatch.setattr(ei, "competitor_snapshot_repo", SimpleNamespace(set_price_confirmation=lambda t, sid, state: w.confirmation.__setitem__(sid, state)))

        def session(t, **kw):
            w.session_calls.append(kw)
            return SimpleNamespace(snapshot_id=w.snapshot_id, research_session_id=uuid4())

        monkeypatch.setattr(ei, "submit_research_session", session)
        import competitor_intelligence.direct_path.research_run as rr

        monkeypatch.setattr(rr, "submit_manual_correction", lambda t, sid, manual_fields, now=None: w.corrections.append(dict(manual_fields)) or SimpleNamespace())
        monkeypatch.setattr(rr, "competitor_snapshot_repo", SimpleNamespace(set_price_confirmation=lambda t, sid, state: w.confirmation.__setitem__(sid, state)))

    def names(self) -> list:
        return [e[0] for e in self.events]


def _field(name, value, source="VISION_EXTRACTED", conflict=False):
    return {"field_name": name, "value": value, "source": source, "confidence": source, "conflict": conflict}


LISTING = [_field("listed_price_paise", 269900), _field("availability", "IN_STOCK"), _field("rating", "4.2"), _field("title", "Titan Octane")]


def _go(world_args=None, **overrides):
    kw = dict(requested_by=USER, image_bytes=_png(), competitor_url_id=URL_ID, extractor=object(), image_store=_Writer(), max_bytes=5_000_000, now=NOW)
    kw.update(overrides)
    return intake_screenshot(TENANT, **kw)


def test_whatsapp_is_a_placeholder_that_stores_nothing(monkeypatch) -> None:
    w = World(monkeypatch, snapshot_fields=LISTING)
    out = _go(channel="WHATSAPP")
    assert out.status is IntakeStatus.CHANNEL_NOT_AVAILABLE and w.session_calls == []


def test_no_competitor_means_nothing_is_stored_and_the_ceo_must_ask(monkeypatch) -> None:
    w = World(monkeypatch, snapshot_fields=LISTING)
    store = _Writer()
    out = _go(competitor_url_id=None, image_store=store)
    assert out.status is IntakeStatus.NEEDS_COMPETITOR and store.written == [] and w.session_calls == []


def test_unknown_competitor_is_not_found(monkeypatch) -> None:
    World(monkeypatch, snapshot_fields=LISTING, url_exists=False)
    assert _go().status is IntakeStatus.COMPETITOR_NOT_FOUND


def test_a_blurry_image_is_rejected_stores_nothing_and_is_logged(monkeypatch) -> None:
    w = World(monkeypatch, snapshot_fields=LISTING)
    flat = io.BytesIO()
    Image.new("RGB", (800, 600), "#dddddd").save(flat, "PNG")
    store = _Writer()
    out = _go(image_bytes=flat.getvalue(), image_store=store)
    assert out.status is IntakeStatus.REJECTED_QUALITY and out.quality_reason.value == "TOO_BLURRY"
    assert store.written == [] and w.session_calls == [] and w.names() == [CiEvent.EVIDENCE_REJECTED_QUALITY]


def test_a_listing_with_a_vision_price_is_held_pending_with_questions(monkeypatch) -> None:
    w = World(monkeypatch, snapshot_fields=LISTING)
    out = _go()
    assert out.status is IntakeStatus.NEEDS_CONFIRMATION
    assert w.session_calls[0]["require_consequential_confirmation"] is True  # price events are deferred
    asked = {q.field_name for q in out.questions}
    assert asked == {"listed_price_paise", "availability"}  # consequential only
    assert "rating" in out.stored_fields and "title" in out.stored_fields  # non-consequential: stored, no prompt
    assert CiEvent.EVIDENCE_RECEIVED in w.names() and w.names().count(CiEvent.FIELD_CONFIRMATION_REQUESTED) == 2


def test_a_listing_with_only_non_consequential_fields_is_stored_without_questions(monkeypatch) -> None:
    World(monkeypatch, snapshot_fields=[_field("listed_price_paise", 259900), _field("rating", "4.2"), _field("title", "Titan Octane")])
    out = _go()
    assert {q.field_name for q in out.questions} == {"listed_price_paise"}  # only the price is consequential here; rating and title are stored


def test_a_listing_with_no_readable_price_always_asks_for_it(monkeypatch) -> None:
    World(monkeypatch, snapshot_fields=[_field("rating", "4.2"), _field("title", "Titan Octane")])
    out = _go()
    assert out.status is IntakeStatus.NEEDS_CONFIRMATION and [q.field_name for q in out.questions] == ["listed_price_paise"] and out.questions[0].proposed_value is None


def test_an_image_that_yields_nothing_is_not_a_listing(monkeypatch) -> None:
    w = World(monkeypatch, snapshot_fields=[_field("listed_price_paise", None), _field("title", None)])
    out = _go()
    assert out.status is IntakeStatus.REJECTED_NOT_A_LISTING and out.questions == ()
    assert CiEvent.FIELD_CONFIRMATION_REQUESTED not in w.names()


def test_the_same_image_twice_is_an_exact_duplicate_and_creates_no_snapshot(monkeypatch) -> None:
    w = World(monkeypatch, snapshot_fields=LISTING)
    data = _png()
    first = _go(image_bytes=data)
    assert first.status is IntakeStatus.NEEDS_CONFIRMATION and len(w.session_calls) == 1
    second = _go(image_bytes=data)
    assert second.status is IntakeStatus.DUPLICATE and second.duplicate_of == w.evidence_id
    assert len(w.session_calls) == 1  # no second research session, no second snapshot


def test_a_near_duplicate_is_held_until_the_seller_says_it_is_a_fresh_capture(monkeypatch) -> None:
    w = World(monkeypatch, snapshot_fields=LISTING)
    assert _go(image_bytes=_png(0)).status is IntakeStatus.NEEDS_CONFIRMATION
    near = io.BytesIO()
    img = Image.open(io.BytesIO(_png(0)))
    ImageDraw.Draw(img).point((3, 3), fill="blue")  # visually identical, different bytes
    img.save(near, "PNG")
    out = _go(image_bytes=near.getvalue())
    assert out.status is IntakeStatus.NEAR_DUPLICATE and len(w.session_calls) == 1
    fresh = _go(image_bytes=near.getvalue(), allow_near_duplicate=True)
    assert fresh.status is IntakeStatus.NEEDS_CONFIRMATION and len(w.session_calls) == 2


# ---- the confirmation answers -------------------------------------------------------
def test_confirming_every_consequential_field_applies_the_seller_values_and_confirms(monkeypatch) -> None:
    w = World(monkeypatch, snapshot_fields=LISTING)
    out = _go()
    ids = {q.field_name: q.info_request_id for q in out.questions}
    sid = settle_confirmation(TENANT, answered_by=USER, answers={ids["listed_price_paise"]: 289900}, now=NOW)
    assert sid == w.snapshot_id and w.confirmation[sid] == "PENDING" and w.corrections == []  # availability still open
    settle_confirmation(TENANT, answered_by=USER, answers={ids["availability"]: "IN_STOCK"}, now=NOW)
    assert w.corrections == [{"listed_price_paise": 289900, "availability": "IN_STOCK"}]  # BOTH applied, not just the last
    assert w.confirmation[w.snapshot_id] == "CONFIRMED"
    assert w.names().count(CiEvent.FIELD_CONFIRMED) == 2


def test_declining_a_consequential_field_keeps_the_snapshot_out_of_every_consequential_path(monkeypatch) -> None:
    w = World(monkeypatch, snapshot_fields=LISTING)
    out = _go()
    ids = {q.field_name: q.info_request_id for q in out.questions}
    settle_confirmation(TENANT, answered_by=USER, answers={ids["availability"]: "IN_STOCK"}, declined=(ids["listed_price_paise"],), now=NOW)
    assert w.confirmation[w.snapshot_id] == "DECLINED" and w.corrections == []
    assert CiEvent.FIELD_CONFIRMATION_DECLINED in w.names()


def test_answering_the_same_question_twice_changes_nothing(monkeypatch) -> None:
    w = World(monkeypatch, snapshot_fields=[_field("listed_price_paise", 269900), _field("title", "Titan")])
    out = _go()
    (q,) = out.questions
    settle_confirmation(TENANT, answered_by=USER, answers={q.info_request_id: 289900}, now=NOW)
    settle_confirmation(TENANT, answered_by=USER, answers={q.info_request_id: 1}, now=NOW)  # replay with a different value
    assert w.requests[q.info_request_id]["answered_value"] == 289900
    assert w.corrections == [{"listed_price_paise": 289900}]  # replay did not re-apply


def test_an_unknown_request_id_is_ignored(monkeypatch) -> None:
    World(monkeypatch, snapshot_fields=LISTING)
    assert settle_confirmation(TENANT, answered_by=USER, answers={uuid4(): 1}, now=NOW) is None
