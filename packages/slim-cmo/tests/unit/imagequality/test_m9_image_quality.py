"""M9 image quality: deterministic measurements, score, findings and the marketplace-rule boundary, on synthetic pictures only."""

from __future__ import annotations

import copy
import io
import json
import random
from datetime import date

import pytest
from PIL import Image, ImageDraw, ImageFilter

from slim_cmo.imagequality.measure import measure
from slim_cmo.imagequality.review import DIMENSIONS, TEXT, compliance, review
from slim_cmo.service import marketplace_rules as mr


def png(im: Image.Image) -> bytes:
    b = io.BytesIO()
    im.save(b, "PNG")
    return b.getvalue()


def product(size: int = 1200, blur: int = 0, bg: tuple[int, int, int] = (255, 255, 255), dim: int = 1) -> Image.Image:
    im = Image.new("RGB", (size, size), bg)
    d = ImageDraw.Draw(im)
    s = size
    d.rounded_rectangle((s * 3 // 10, s // 10, s * 7 // 10, s * 9 // 10), radius=s // 20, fill=(40, 90, 160))
    for i in range(0, s * 8 // 10, 12):
        d.line((s * 3 // 10, s // 10 + i, s * 7 // 10, s // 10 + i), fill=(60, 120, 200), width=2)
    d.rectangle((s * 4 // 10, s * 45 // 100, s * 6 // 10, s * 55 // 100), fill=(240, 240, 240))
    if blur:
        im = im.filter(ImageFilter.GaussianBlur(blur))
    if dim > 1:
        im = im.point(lambda v: v // dim)
    return im


def item(i: int, im: Image.Image, role: str = "SECONDARY", shot: str = "FRONT") -> dict:
    return {"id": f"img{i}", "role": role, "shotType": shot, "measures": measure(png(im))}


def codes(report: dict, number: int | None = None) -> set[str]:
    return {f["code"] for f in report["findings"] if number is None or f["imageNumber"] == number}


def good_set() -> list[dict]:
    return [item(1, product(), "PRIMARY", "FRONT"), item(2, product(), "SECONDARY", "ANGLE"), item(3, product(), "SECONDARY", "DETAIL"),
            item(4, product(), "SECONDARY", "SIZE"), item(5, product(), "SECONDARY", "USAGE")]


def test_weights_add_up_to_one_hundred_and_every_finding_has_text():
    assert sum(w for _, _, w in DIMENSIONS) == 100
    assert all(len(v) == 3 and all(v) for v in TEXT.values())


def test_a_sharp_well_lit_centred_set_scores_and_every_figure_is_an_integer():
    r = review(good_set())
    assert r["scoreState"] == "COMPLETE" and isinstance(r["score"], int) and 80 <= r["score"] <= 100
    assert sum(d["earned"] for d in r["dimensions"]) == r["score"] and r["pointsAssessable"] == 100
    assert not [f for f in r["findings"] if f["severity"] == "HIGH"]

    def walk(x):
        if isinstance(x, dict):
            yield from (y for v in x.values() for y in walk(v))
        elif isinstance(x, list):
            yield from (y for v in x for y in walk(v))
        else:
            yield x

    assert not [v for v in walk(r) if isinstance(v, float)]


def test_the_same_images_always_give_the_same_report():
    assert json.dumps(review(good_set()), sort_keys=True) == json.dumps(review(good_set()), sort_keys=True)


def test_blur_lowers_sharpness_and_is_a_high_finding_on_the_main_image():
    sharp, soft = measure(png(product())), measure(png(product(blur=4)))
    assert sharp["sharpness"] > soft["sharpness"] * 2
    r = review([item(1, product(blur=4), "PRIMARY")])
    assert "BLURRY" in codes(r) and next(f for f in r["findings"] if f["code"] == "BLURRY")["severity"] == "HIGH"


def test_a_small_image_is_a_low_resolution_finding():
    r = review([item(1, product(300), "PRIMARY")])
    assert "LOW_RESOLUTION" in codes(r)
    assert next(f for f in r["findings"] if f["code"] == "LOW_RESOLUTION")["recommendation"]


def test_a_dark_image_is_flagged_too_dark():
    r = review([item(1, product(dim=4), "PRIMARY")])
    assert "TOO_DARK" in codes(r)


def test_a_busy_background_stops_the_product_being_separated_and_the_score_is_withheld():
    random.seed(1)
    busy = Image.effect_noise((1000, 1000), 90).convert("RGB")
    busy.paste(product(1000).crop((300, 100, 700, 900)), (300, 100))
    r = review([item(1, busy, "PRIMARY")])
    assert "BUSY_BACKGROUND" in codes(r)
    dims = {d["key"]: d for d in r["dimensions"]}
    assert dims["visibility"]["state"] == "NOT_ASSESSED" and dims["visibility"]["reason"]
    assert r["scoreState"] == "PARTIAL" and r["score"] is None and r["pointsEarned"] is not None


def test_a_tiny_product_on_a_plain_backdrop_is_reported_not_skipped():
    im = Image.new("RGB", (1000, 1000), (255, 255, 255))
    ImageDraw.Draw(im).rectangle((450, 450, 550, 550), fill=(40, 90, 160))
    r = review([item(1, im, "PRIMARY")])
    assert "PRODUCT_TOO_SMALL_OR_ABSENT" in codes(r)
    assert next(d for d in r["dimensions"] if d["key"] == "lighting")["state"] == "NOT_ASSESSED"


def test_a_product_cut_off_at_the_frame_is_flagged():
    im = Image.new("RGB", (1000, 1000), (255, 255, 255))
    ImageDraw.Draw(im).rectangle((300, 0, 700, 1000), fill=(40, 90, 160))
    assert "SUBJECT_CUT_OFF" in codes(review([item(1, im, "PRIMARY")]))


def test_overlay_text_away_from_the_product_is_only_a_possible_low_confidence_finding():
    im = product()
    ImageDraw.Draw(im).rectangle((100, 20, 1100, 70), fill=(200, 0, 0))
    r = review([item(1, im, "PRIMARY")])
    assert r["images"][0]["overlayCheck"] == "POSSIBLE_OVERLAY" and r["images"][0]["overlayCheckConfidence"] == "LOW"
    assert "POSSIBLE_OVERLAY" in codes(r) and "cannot read text" in " ".join(r["notes"])
    assert measure(png(product()))["overlay"] == "NOT_DETECTED"


def test_a_single_image_is_assessed_but_the_score_is_withheld_until_consistency_can_be_checked():
    r = review([item(1, product(), "PRIMARY")])
    assert r["scoreState"] == "PARTIAL" and r["score"] is None and "ONLY_ONE_IMAGE" in codes(r)
    s = next(d for d in r["dimensions"] if d["key"] == "set")
    assert s["state"] == "PARTIAL" and s["assessableMax"] == 8 and r["pointsAssessable"] < 100


def test_no_main_image_means_no_score_and_a_high_finding_but_secondary_images_are_still_reviewed():
    r = review([item(1, product(300), "SECONDARY")])
    assert r["scoreState"] == "NOT_CALCULABLE" and r["score"] is None
    assert "NO_PRIMARY" in codes(r) and "LOW_RESOLUTION" in codes(r, 1)
    empty = review([])
    assert empty["scoreState"] == "NOT_CALCULABLE" and empty["findings"][0]["code"] == "NO_PRIMARY" and empty["pointsEarned"] is None


def test_missing_shots_are_recommendations_never_marketplace_requirements():
    r = review([item(1, product(), "PRIMARY"), item(2, product(), "SECONDARY", "ANGLE")])
    assert {m["shotType"] for m in r["missingShots"]} == {"DETAIL", "SIZE", "USAGE"}
    assert all(m["isMarketplaceRequirement"] is False for m in r["missingShots"]) and all(f["isMarketplaceRequirement"] is False for f in r["findings"])


def test_an_inconsistent_set_is_called_out():
    wide = Image.new("RGB", (1600, 800), (255, 255, 255))
    ImageDraw.Draw(wide).rectangle((600, 150, 1000, 650), fill=(40, 90, 160))
    r = review([item(1, product(), "PRIMARY"), item(2, wide, "SECONDARY", "ANGLE")])
    assert "INCONSISTENT_ASPECT" in codes(r)
    assert next(d for d in r["dimensions"] if d["key"] == "set")["earned"] < 15


def test_findings_are_ordered_most_important_first():
    r = review([item(1, product(300, blur=3), "PRIMARY"), item(2, product(), "SECONDARY", "ANGLE")])
    sev = [f["severity"] for f in r["findings"]]
    assert sev == sorted(sev, key={"HIGH": 0, "MEDIUM": 1, "LOW": 2}.__getitem__)
    assert sev[0] == "HIGH"


def test_usage_and_detail_shots_are_not_marked_down_for_a_busy_frame():
    random.seed(2)
    scene = Image.effect_noise((1000, 1000), 80).convert("RGB")
    r = review([item(1, product(), "PRIMARY"), item(2, scene, "SECONDARY", "USAGE")])
    row = r["images"][1]
    assert row["dimensions"]["background"] is None and "Not applicable" in row["notAssessed"]["background"]
    assert "BUSY_BACKGROUND" not in codes(r, 2)


# ---- marketplace rules --------------------------------------------------------------------------------------------------------------------------------------
def test_with_the_shipped_register_every_marketplace_image_check_is_not_assessed():
    reg = mr.load()
    for m in ("AMAZON", "FLIPKART", "MEESHO"):
        c = compliance(reg, m, good_set(), today=date(2026, 11, 1), max_age_days=90)
        assert c["status"] == "NOT_ASSESSED" and c["checks"] == [] and "NOT_ASSESSED" in c["notAssessed"]


def _rule(field: str, value: int, **kw) -> dict:
    base = {"marketplace": "AMAZON", "scope": "amazon.in ALL_CATEGORIES", "field": field, "value": value, "status": "OFFICIAL_VERIFIED",
            "source": {"url": "https://sellercentral.amazon.in/help/example"}, "checked_on": "2026-10-31"}
    base.update(kw)
    return base


def test_only_a_verified_fresh_official_rule_is_checked_and_it_is_never_called_compliance():
    reg = copy.deepcopy(mr.load())
    imgs = [item(1, product(600), "PRIMARY"), item(2, product(1200), "SECONDARY", "ANGLE")]
    reg["rules"] += [_rule("image.min_long_side_px", 1000), _rule("image.min_count", 3)]
    c = compliance(reg, "AMAZON", imgs, today=date(2026, 11, 1), max_age_days=90)
    assert c["status"] == "CHECKED_FAILED"
    results = {(x["rule"], x.get("imageNumber")): x["result"] for x in c["checks"]}
    assert results[("image.min_long_side_px", 1)] == "FAIL" and results[("image.min_long_side_px", 2)] == "PASS" and results[("image.min_count", None)] == "FAIL"
    assert all(x["source"]["url"].startswith("https://") and x["source"]["checkedOn"] == "2026-10-31" for x in c["checks"])
    assert "compliant" not in json.dumps(c).lower() or "not a statement" in c["message"]
    assert compliance(reg, "FLIPKART", imgs, today=date(2026, 11, 1), max_age_days=90)["status"] == "NOT_ASSESSED"


@pytest.mark.parametrize("bad", [
    _rule("image.min_long_side_px", 1000, status="OFFICIAL_PARTIAL"),
    _rule("image.min_long_side_px", 1000, status="THIRD_PARTY_ONLY"),
    _rule("image.min_long_side_px", 1000, scope="amazon.in Kitchen"),
    _rule("image.min_long_side_px", 1000, source={"url": "http://example.com/blog"}),
    _rule("image.min_long_side_px", 1000, checked_on="2025-01-01"),
    {**_rule("image.min_long_side_px", 1000), "value": None},
    _rule("image.aspect_ratio", 1),
])
def test_partial_third_party_category_stale_or_non_official_rules_are_ignored(bad):
    reg = copy.deepcopy(mr.load())
    reg["rules"].append(bad)
    assert compliance(reg, "AMAZON", good_set(), today=date(2026, 11, 1), max_age_days=90)["status"] == "NOT_ASSESSED"


# ---- near-duplicate detection ----------------------------------------------------------------------------------------------------------------------------
def bottle(lying: bool = False, detail: bool = False, label=(240, 240, 240), body=(40, 90, 160), size: int = 1200) -> Image.Image:
    im = Image.new("RGB", (size, size), (255, 255, 255))
    d = ImageDraw.Draw(im)
    s = size
    if detail:
        d.ellipse((s // 10, s // 10, s * 9 // 10, s * 9 // 10), fill=(200, 60, 40))
        for i in range(8):
            d.line((s // 10, s // 5 + i * s // 12, s * 9 // 10, s // 5 + i * s // 12), fill=(120, 20, 10), width=6)
    elif lying:
        d.rounded_rectangle((s // 10, s * 38 // 100, s * 9 // 10, s * 62 // 100), radius=s // 20, fill=body)
        d.rectangle((s * 4 // 10, s * 42 // 100, s * 6 // 10, s * 58 // 100), fill=label)
    else:
        d.rounded_rectangle((s * 3 // 10, s // 10, s * 7 // 10, s * 9 // 10), radius=s // 20, fill=body)
        d.rectangle((s * 4 // 10, s * 45 // 100, s * 6 // 10, s * 55 // 100), fill=label)
    return im


def pair(a: Image.Image, b: Image.Image, shot_a: str = "FRONT", shot_b: str = "FRONT") -> dict:
    return review([item(1, a, "PRIMARY", shot_a), item(2, b, "SECONDARY", shot_b)])["duplicateCheck"]


def reencoded(im: Image.Image) -> Image.Image:
    out = io.BytesIO()
    im.resize((800, 800), Image.Resampling.LANCZOS).save(out, "JPEG", quality=70)
    return Image.open(io.BytesIO(out.getvalue())).convert("RGB")


def test_an_identical_resized_or_reencoded_picture_is_a_repeat_with_the_reason_and_numbers():
    for other in (bottle(), bottle(size=600), reencoded(bottle())):
        d = pair(bottle(), other)
        assert d["state"] == "CHECKED" and [p["verdict"] for p in d["pairs"]] == ["REPEAT"] and d["pairs"][0]["images"] == [1, 2]
        assert d["pairs"][0]["hashDistanceOf64"] == 0 and "almost the same shapes and colours" in d["pairs"][0]["reason"]
    r = review([item(1, bottle(), "PRIMARY", "FRONT"), item(2, bottle(size=600), "SECONDARY", "FRONT")])
    rep = next(f for f in r["findings"] if f["code"] == "REPEATED_IMAGE")
    assert rep["problem"] == "Image 1 and image 2 look almost the same" and rep["severity"] == "LOW" and rep["isMarketplaceRequirement"] is False and rep["recommendation"]


def test_a_slightly_changed_picture_of_the_same_kind_of_shot_is_still_a_repeat():
    sticker = bottle()
    ImageDraw.Draw(sticker).rectangle((820, 160, 880, 220), fill=(200, 0, 0))
    for other in (sticker, bottle(label=(250, 220, 90))):
        assert [p["verdict"] for p in pair(bottle(), other)["pairs"]] == ["REPEAT"]


def test_a_slightly_changed_picture_labelled_as_a_different_view_is_not_flagged_only_not_assessed():
    d = pair(bottle(), bottle(label=(250, 220, 90)), "FRONT", "BACK")
    assert [p["verdict"] for p in d["pairs"]] == ["NOT_ASSESSED"] and "Not assessed" in d["pairs"][0]["reason"]
    r = review([item(1, bottle(), "PRIMARY", "FRONT"), item(2, bottle(label=(250, 220, 90)), "SECONDARY", "BACK")])
    assert "REPEATED_IMAGE" not in codes(r)


def test_genuinely_different_angles_and_details_are_never_called_repeats():
    for other, shot in ((bottle(lying=True), "SIDE"), (bottle(detail=True), "DETAIL")):
        assert pair(bottle(), other, "FRONT", shot)["pairs"] == []
        assert pair(bottle(), other, "FRONT", "FRONT")["pairs"] == []  # even if the seller labelled both as front views
    assert "REPEATED_IMAGE" not in codes(review(good_set()[:1] + [item(2, bottle(lying=True), "SECONDARY", "SIDE")]))


def test_alike_but_not_alike_enough_is_not_assessed_not_a_false_positive():
    d = pair(bottle(), bottle(body=(160, 40, 40)))
    assert [p["verdict"] for p in d["pairs"]] == ["NOT_ASSESSED"]
    assert "REPEATED_IMAGE" not in codes(review([item(1, bottle(), "PRIMARY"), item(2, bottle(body=(160, 40, 40)), "SECONDARY")]))


def test_one_image_cannot_be_checked_and_the_check_never_changes_the_score_or_compliance():
    assert review([item(1, bottle(), "PRIMARY")])["duplicateCheck"]["state"] == "NOT_ASSESSED"
    a, b = review([item(1, bottle(), "PRIMARY"), item(2, bottle(size=600), "SECONDARY")]), review([item(1, bottle(), "PRIMARY"), item(2, bottle(lying=True), "SECONDARY")])
    assert "REPEATED_IMAGE" in codes(a) and "REPEATED_IMAGE" not in codes(b)
    assert compliance(mr.load(), "AMAZON", [{"role": "PRIMARY", "measures": {"long_side": 1200}}], today=date(2026, 11, 1), max_age_days=90)["status"] == "NOT_ASSESSED"
