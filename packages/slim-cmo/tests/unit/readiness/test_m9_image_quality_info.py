"""M9: product image quality shown BESIDE readiness. It is information only: it never changes the readiness score, the verdict or any checklist item, and missing images are never a pass."""

from __future__ import annotations

import dataclasses

from slim_cmo.readiness.checklist import assess

from .test_checklist import inputs, items, market


def with_images(photo: bool, summary):
    return dataclasses.replace(inputs(photo=photo), images=summary)


REVIEWED = {"images": 4, "hasPrimary": True, "review": {"score": 82, "scoreState": "COMPLETE", "isCurrent": True, "highFindings": 1}}


def test_without_any_uploaded_image_the_quality_is_not_assessed_and_never_a_pass():
    r = assess(inputs(), market())
    q = r["imageQuality"]
    assert q["state"] == "NOT_ASSESSED" and "not a pass" in q["message"] and q["separateFromReadiness"] is True and "score" not in q


def test_a_reviewed_current_set_shows_its_score_and_high_findings_but_changes_nothing_else():
    base = assess(inputs(), market())
    r = assess(with_images(True, {"AMAZON": REVIEWED}), market())
    assert r["imageQuality"]["state"] == "REVIEWED" and r["imageQuality"]["score"] == 82 and r["imageQuality"]["highFindings"] == 1
    assert (r["score"], r["verdict"], r["categories"], r["nextActions"]) == (base["score"], base["verdict"], base["categories"], base["nextActions"])


def test_a_stale_partial_or_unreviewed_set_is_labelled_as_such_and_shows_no_score():
    for review, state in ((None, "NOT_REVIEWED"), ({**REVIEWED["review"], "isCurrent": False}, "STALE"), ({**REVIEWED["review"], "scoreState": "PARTIAL", "score": None}, "PARTIAL")):
        q = assess(with_images(True, {"AMAZON": {**REVIEWED, "review": review}}), market())["imageQuality"]
        assert q["state"] == state and "score" not in q


def test_a_main_image_on_the_images_page_counts_as_the_photo_being_present_but_a_good_review_cannot_hide_other_gaps():
    none = assess(inputs(photo=False), market())
    assert items(none)["photo_present"]["status"] == "MISSING"
    uploaded = assess(with_images(False, {"AMAZON": REVIEWED}), market())
    assert items(uploaded)["photo_present"]["status"] == "DONE" and items(uploaded)["photo_present"]["earned"] == 10 and "images page" in items(uploaded)["photo_present"]["detail"]
    gaps = assess(with_images(False, {"AMAZON": REVIEWED}), market(copy=False))
    assert gaps["verdict"] == "NOT_READY" and items(gaps)["content_copy"]["status"] == "MISSING"  # a good image score does not override another blocker
    secondary_only = assess(with_images(False, {"AMAZON": {**REVIEWED, "hasPrimary": False}}), market())
    assert items(secondary_only)["photo_present"]["status"] == "MISSING"


def test_images_of_another_marketplace_are_not_counted():
    r = assess(with_images(False, {"FLIPKART": REVIEWED}), market("AMAZON"))
    assert items(r)["photo_present"]["status"] == "MISSING" and r["imageQuality"]["state"] == "NOT_ASSESSED"
