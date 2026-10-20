"""C36/C37/C47 — the quality gate, the confirmation policy and the event-detail safety rule."""

from __future__ import annotations

import io
from enum import Enum
from uuid import uuid4

import pytest
from PIL import Image, ImageDraw

from competitor_intelligence.intake.events import UnsafeEventDetail, safe_detail
from competitor_intelligence.intake.policy import AskReason, FieldAction, decide_field, is_consequential
from competitor_intelligence.intake.quality import (
    QualityReason,
    QualityStatus,
    assess_image,
    average_hash,
    hamming_distance,
    is_near_duplicate,
)
from competitor_intelligence.landscape.price_band import _is_band_eligible
from competitor_intelligence.types import Confidence

MAX = 5_000_000


def _png(img: Image.Image, fmt: str = "PNG") -> bytes:
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return buf.getvalue()


def _sharp(size=(800, 600)) -> Image.Image:
    img = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(img)
    for i in range(0, size[0], 12):
        draw.rectangle([i, 0, i + 5, size[1]], fill="black")
    draw.text((20, 20), "Rs 2,899", fill="red")
    return img


# ---- quality gate -------------------------------------------------------------------
def test_a_sharp_screenshot_is_accepted_with_hashes() -> None:
    v = assess_image(_png(_sharp()), max_bytes=MAX)
    assert v.status is QualityStatus.ACCEPTED and v.reason is None and v.accepted
    assert len(v.sha256) == 64 and v.perceptual_hash and len(v.perceptual_hash) == 16
    assert (v.width, v.height) == (800, 600)


def test_a_flat_blurry_image_is_rejected_with_a_seller_readable_reason() -> None:
    v = assess_image(_png(Image.new("RGB", (800, 600), "#cccccc")), max_bytes=MAX)
    assert v.status is QualityStatus.REJECTED_LOW_QUALITY and v.reason is QualityReason.TOO_BLURRY
    assert "blurry" in v.seller_message


def test_a_tiny_image_is_rejected() -> None:
    v = assess_image(_png(_sharp((200, 150))), max_bytes=MAX)
    assert v.reason is QualityReason.TOO_SMALL


@pytest.mark.parametrize(
    "data,reason",
    [
        (b"", QualityReason.EMPTY),
        (b"this is not an image", QualityReason.NOT_AN_IMAGE),
        (b"<svg xmlns='http://www.w3.org/2000/svg'/>", QualityReason.NOT_AN_IMAGE),
    ],
)
def test_non_images_are_rejected(data, reason) -> None:
    assert assess_image(data, max_bytes=MAX).reason is reason


def test_type_is_decided_by_content_not_by_name_gif_is_unsupported() -> None:
    assert assess_image(_png(_sharp(), "GIF"), max_bytes=MAX).reason is QualityReason.UNSUPPORTED_TYPE


def test_oversize_is_rejected_before_decoding() -> None:
    assert assess_image(_png(_sharp()), max_bytes=100).reason is QualityReason.TOO_LARGE


def test_jpeg_and_webp_are_supported() -> None:
    assert assess_image(_png(_sharp(), "JPEG"), max_bytes=MAX).accepted
    assert assess_image(_png(_sharp(), "WEBP"), max_bytes=MAX).accepted


def test_exact_duplicate_has_the_same_sha_and_a_near_duplicate_a_close_hash() -> None:
    a = _png(_sharp())
    assert assess_image(a, max_bytes=MAX).sha256 == assess_image(a, max_bytes=MAX).sha256
    slightly_edited = _sharp()
    ImageDraw.Draw(slightly_edited).point((5, 5), fill="blue")
    h1, h2 = average_hash(_sharp()), average_hash(slightly_edited)
    assert is_near_duplicate(h1, h2) and hamming_distance(h1, h1) == 0
    different = Image.new("RGB", (800, 600), "white")
    ImageDraw.Draw(different).rectangle([0, 0, 400, 600], fill="black")
    assert not is_near_duplicate(h1, average_hash(different))


# ---- confirmation policy ------------------------------------------------------------
def test_price_discount_and_availability_are_the_consequential_fields() -> None:
    assert all(is_consequential(f) for f in ("listed_price_paise", "visible_discount_paise", "availability"))
    assert not any(is_consequential(f) for f in ("rating", "rating_count", "title", "observed_category", "mrp_paise"))


def test_a_vision_read_price_is_always_asked() -> None:
    d = decide_field("listed_price_paise", source=Confidence.VISION_EXTRACTED, present=True)
    assert d.action is FieldAction.ASK_SELLER and d.reason is AskReason.CONSEQUENTIAL_FIELD and d.consequential


def test_a_seller_entered_consequential_field_is_verified_on_entry() -> None:
    assert decide_field("listed_price_paise", source=Confidence.SELLER_ENTERED, present=True).action is FieldAction.STORE


def test_a_non_consequential_vision_field_is_stored_without_a_prompt() -> None:
    d = decide_field("rating", source=Confidence.VISION_EXTRACTED, present=True)
    assert d.action is FieldAction.STORE and not d.consequential


def test_a_missing_field_is_unknown_and_not_asked_unless_consequential_and_needed() -> None:
    assert decide_field("rating", source=None, present=False).action is FieldAction.LEAVE_UNKNOWN
    assert decide_field("listed_price_paise", source=None, present=False).action is FieldAction.LEAVE_UNKNOWN
    asked = decide_field("listed_price_paise", source=None, present=False, needed_for_request=True)
    assert asked.action is FieldAction.ASK_SELLER and asked.reason is AskReason.MISSING
    assert decide_field("rating", source=None, present=False, needed_for_request=True).action is FieldAction.LEAVE_UNKNOWN


def test_a_conflict_is_always_asked() -> None:
    d = decide_field("rating", source=None, present=False, conflict=True)
    assert d.action is FieldAction.ASK_SELLER and d.reason is AskReason.CONFLICT


# ---- event detail safety (AC56) -----------------------------------------------------
class _Kind(str, Enum):
    EXACT = "EXACT"


def test_event_detail_accepts_ids_enums_numbers_and_short_codes() -> None:
    u = uuid4()
    assert safe_detail({"id": u, "kind": _Kind.EXACT, "n": 3, "ok": True, "field": "listed_price_paise", "ids": [u]}) == {
        "id": str(u), "kind": "EXACT", "n": 3, "ok": True, "field": "listed_price_paise", "ids": [str(u)],
    }
    assert safe_detail(None) == {}


@pytest.mark.parametrize(
    "bad",
    [
        {"snippet": "Leather feels like cardboard out of the box, cracked in 2 weeks"},
        {"x": "a" * 65},
        {"x": "line one\nline two"},
        {"x": {"nested": "dict"}},
        {f"k{i}": 1 for i in range(17)},
    ],
)
def test_event_detail_rejects_anything_that_could_be_free_text(bad) -> None:
    with pytest.raises(UnsafeEventDetail):
        safe_detail(bad)


# ---- price-band eligibility (C43) ---------------------------------------------------
@pytest.mark.parametrize(
    "candidate,expected",
    [
        (None, True),  # manually added competitor
        ({"identity_match": "EXACT_MATCH"}, True),
        ({"identity_match": "LIKELY_VARIANT"}, True),
        ({"identity_match": "NOT_A_MATCH", "relationship_class": "DIRECT_COMPETITOR"}, True),
        ({"identity_match": "NOT_A_MATCH", "relationship_class": "FUNCTIONAL_ALTERNATIVE"}, False),
        ({"identity_match": "NOT_A_MATCH", "relationship_class": "UNKNOWN"}, False),
        ({"identity_match": "NOT_A_MATCH"}, False),
        ({"identity_match": "UNCERTAIN", "relationship_class": "UNKNOWN"}, False),
    ],
)
def test_band_eligibility_includes_direct_competitors_but_not_alternatives_or_unknowns(candidate, expected) -> None:
    assert _is_band_eligible(candidate) is expected
