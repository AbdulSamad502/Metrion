"""CMO 3.0 M9 (migrations slim-cmo 20261101_0011, backend 20261031_0032): attaching the seller's own images to a product, the deterministic image quality review, tenant isolation, idempotency,
and the rule that marketplace image requirements stay NOT_ASSESSED without a verified official rule. Synthetic pictures only; no model is called and no credit is spent."""

from __future__ import annotations

import io
import json
import os
import uuid

import pytest
from PIL import Image, ImageDraw, ImageFilter

from backend.auth.permissions import PARTNER_ROLE

from .test_cmo_api import _erase_cmo_rows, _login, ctx_engine, env, fake_clerk  # noqa: F401
from .test_cmo_images_api import img  # noqa: F401

pytestmark = pytest.mark.skipif(not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL"), reason="needs a live Postgres")

SKU, NAME, AMAZON, FLIPKART = "AQUA-1", "AquaNest steel bottle", "AMAZON", "FLIPKART"


def picture(size: int = 1000, blur: int = 0, dim: int = 1, bg=(255, 255, 255), crop: bool = False) -> bytes:
    im = Image.new("RGB", (size, size), bg)
    d = ImageDraw.Draw(im)
    s = size
    d.rounded_rectangle((s * 3 // 10, 0 if crop else s // 10, s * 7 // 10, s if crop else s * 9 // 10), radius=s // 20, fill=(40, 90, 160))
    for i in range(0, s * 8 // 10, 12):
        d.line((s * 3 // 10, s // 10 + i, s * 7 // 10, s // 10 + i), fill=(60, 120, 200), width=2)
    d.rectangle((s * 4 // 10, s * 45 // 100, s * 6 // 10, s * 55 // 100), fill=(240, 240, 240))
    if blur:
        im = im.filter(ImageFilter.GaussianBlur(blur))
    if dim > 1:
        im = im.point(lambda v: v // dim)
    out = io.BytesIO()
    im.save(out, "PNG")
    return out.getvalue()


def distinct(seed: int, **kw) -> bytes:
    """A good picture that is a different file each time (a pixel in the border differs), so it is a different stored image."""
    im = Image.open(io.BytesIO(picture(**kw))).convert("RGB")
    im.putpixel((2, 2), (255, 255 - seed, 255))
    out = io.BytesIO()
    im.save(out, "PNG")
    return out.getvalue()


def known_product(env, sku=SKU):
    r = env.post("title-sets", {"request_key": f"m9-{sku}", "sku": sku, "product_name": NAME, "brand": "AquaNest", "marketplaces": [AMAZON]})
    assert r.status_code == 200, r.text


def upload(env, files, sku=SKU, marketplace=AMAZON, headers=None):
    """files: list of (name, bytes, content-type, role, shotType)."""
    labels = [{"role": f[3], "shotType": f[4]} for f in files]
    return env.client().post("/api/v1/cmo/product-images/upload", files=[("files", (f[0], f[1], f[2])) for f in files], data={"sku": sku, "marketplace": marketplace, "labels": json.dumps(labels)},
                             headers=env.headers if headers is None else headers)


def get(env, path, headers=None, **params):
    return env.client().get(f"/api/v1/cmo/product-images{path}", params=params, headers=env.headers if headers is None else headers)


def review(env, sku=SKU, marketplace=AMAZON, headers=None):
    return env.post("product-images/review", {"sku": sku, "marketplace": marketplace}, headers=headers)


def good_set(env, n=3):
    files = [("front.png", distinct(1), "image/png", "PRIMARY", "FRONT")] + [(f"v{i}.png", distinct(10 + i), "image/png", "SECONDARY", s) for i, s in zip(range(2, n + 1), ("ANGLE", "DETAIL", "SIZE", "USAGE"))]
    r = upload(env, files)
    assert r.status_code == 200 and all(x["status"] == "ACCEPTED" for x in r.json()["results"]), r.text
    return r.json()


# ------------------------------------------------------------------------------------------------ upload and assignment
def test_images_attach_to_a_known_product_with_labels_at_zero_cost_and_are_audited(img):
    env = img.env
    known_product(env)
    units_before = len(env.events())
    r = upload(env, [("a.png", distinct(1), "image/png", "PRIMARY", "FRONT"), ("b.png", distinct(2), "image/png", "SECONDARY", "ANGLE")])
    body = r.json()
    assert r.status_code == 200 and body["unitsBilled"] == 0 and body["assignmentsWritten"] == 2 and [x["status"] for x in body["results"]] == ["ACCEPTED", "ACCEPTED"]
    page = get(env, "", sku=SKU, marketplace=AMAZON).json()
    assert [(i["role"], i["shotType"]) for i in page["images"]] == [("PRIMARY", "FRONT"), ("SECONDARY", "ANGLE")]
    assert page["images"][0]["widthPx"] == 1000 and page["compliance"]["status"] == "NOT_ASSESSED" and len(page["assignmentHistory"]) == 2
    assert env.n("cmo_product_image") == 2 and len(env.events()) == units_before and env.reservations() == []
    assert env.n("agent_run", "trigger_ref = 'cmo.assign_images'") == 1 and str(env.q("SELECT DISTINCT assigned_by FROM cmo_product_image")[0][0]) == str(env.user_id)
    assert {p["sku"] for p in get(env, "/products").json()["products"]} >= {SKU}


def test_an_unknown_product_is_refused_and_nothing_is_stored(img):
    env = img.env
    r = upload(env, [("a.png", distinct(1), "image/png", "PRIMARY", "FRONT")], sku="NOT-MINE")
    assert r.status_code == 404 and r.json()["detail"]["code"] == "UNKNOWN_PRODUCT"
    assert env.n("cmo_product_image") == 0 and env.n("seller_image_asset") == 0 and img.stored_files() == []
    assert upload(env, [("a.png", distinct(1), "image/png", "PRIMARY", "FRONT")], marketplace="EBAY").status_code == 422


def test_bad_files_are_reported_one_by_one_and_the_good_ones_still_attach(img):
    env = img.env
    known_product(env)
    svg = b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>"
    r = upload(env, [("ok.png", distinct(1), "image/png", "PRIMARY", "FRONT"), ("x.svg", svg, "image/svg+xml", "SECONDARY", "ANGLE"), ("t.png", b"%PDF-1.7 nope", "image/png", "SECONDARY", "DETAIL"),
                     ("bad.png", distinct(3), "image/png", "SECONDARY", "NOT_A_SHOT")])
    res = r.json()["results"]
    assert r.status_code == 200 and [x["status"] for x in res] == ["ACCEPTED", "REJECTED", "REJECTED", "REJECTED"]
    assert res[1]["code"] == "TYPE_NOT_ALLOWED" and res[2]["code"] == "NOT_AN_IMAGE" and res[3]["code"] == "BAD_LABEL"
    assert env.n("cmo_product_image") == 1 and env.n("seller_image_asset") == 1


def test_the_same_picture_again_is_one_image_and_writes_nothing_new(img):
    env = img.env
    known_product(env)
    f = [("a.png", distinct(1), "image/png", "PRIMARY", "FRONT")]
    assert upload(env, f).json()["assignmentsWritten"] == 1
    again = upload(env, f).json()
    assert again["assignmentsWritten"] == 0 and again["results"][0]["alreadyStored"] is True
    assert env.n("cmo_product_image") == 1 and env.n("seller_image_asset") == 1 and env.n("agent_run", "trigger_ref = 'cmo.assign_images'") == 1


def test_only_one_main_image_and_promoting_another_demotes_the_old_one_with_an_audit_trail(img):
    env = img.env
    known_product(env)
    first = upload(env, [("a.png", distinct(1), "image/png", "PRIMARY", "FRONT")]).json()["results"][0]["assetId"]
    second = upload(env, [("b.png", distinct(2), "image/png", "PRIMARY", "FRONT")]).json()["results"][0]["assetId"]
    imgs = get(env, "", sku=SKU, marketplace=AMAZON).json()["images"]
    assert [(i["assetId"], i["role"]) for i in imgs] == [(second, "PRIMARY"), (first, "SECONDARY")]
    two = upload(env, [("c.png", distinct(3), "image/png", "PRIMARY", "FRONT"), ("d.png", distinct(4), "image/png", "PRIMARY", "FRONT")])
    assert two.status_code == 422 and two.json()["detail"]["code"] == "ONE_PRIMARY"
    assert env.n("cmo_product_image") == 3  # the refused request wrote no assignment
    assert env.n("cmo_product_image", "role = 'PRIMARY'") == 2  # history: both primaries were assigned once; only the newest is current


def test_an_image_can_be_removed_from_the_set_without_deleting_the_stored_picture(img):
    env = img.env
    known_product(env)
    a = upload(env, [("a.png", distinct(1), "image/png", "PRIMARY", "FRONT")]).json()["results"][0]["assetId"]
    r = env.post("product-images/assign", {"sku": SKU, "marketplace": AMAZON, "items": [{"assetId": a, "role": "REMOVED", "shotType": "FRONT"}]})
    assert r.status_code == 200 and r.json()["assignmentsWritten"] == 1
    assert get(env, "", sku=SKU, marketplace=AMAZON).json()["images"] == [] and env.n("seller_image_asset") == 1 and len(img.stored_files()) == 1
    assert env.post("product-images/assign", {"sku": SKU, "marketplace": AMAZON, "items": [{"assetId": str(uuid.uuid4()), "role": "SECONDARY", "shotType": "FRONT"}]}).status_code == 404


def test_the_set_is_limited_and_files_per_request_are_limited(img):
    env = img.env
    known_product(env)
    many = [(f"{i}.png", distinct(i), "image/png", "SECONDARY", "OTHER") for i in range(1, 10)]
    r = upload(env, many)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "TOO_MANY_FILES" and env.n("cmo_product_image") == 0


# ------------------------------------------------------------------------------------------------ the review
def test_a_review_scores_the_set_stores_it_once_and_never_costs_a_credit(img):
    env = img.env
    known_product(env)
    good_set(env, 5)
    units_before = len(env.events())
    r = review(env)
    body = r.json()
    assert r.status_code == 200 and body["created"] is True and body["unitsBilled"] == 0
    rep = body["report"]
    assert rep["scoreState"] == "COMPLETE" and isinstance(rep["score"], int) and sum(d["earned"] for d in rep["dimensions"]) == rep["score"]
    assert [i["role"] for i in rep["images"]] == ["PRIMARY", "SECONDARY", "SECONDARY", "SECONDARY", "SECONDARY"] and rep["product"]["sku"] == SKU
    assert body["compliance"]["status"] == "NOT_ASSESSED" and "no verified official image rule" in body["compliance"]["message"].lower()
    again = review(env).json()
    assert again["created"] is False and again["reviewId"] == body["reviewId"] and env.n("cmo_image_review") == 1
    assert env.n("agent_run", "trigger_ref = 'cmo.review_images'") == 1 and len(env.events()) == units_before and env.reservations() == []
    page = get(env, "", sku=SKU, marketplace=AMAZON).json()
    assert page["review"]["isCurrent"] is True and page["history"][0]["score"] == rep["score"]


def test_changing_the_set_makes_the_old_review_stale_and_a_new_review_is_a_new_row(img):
    env = img.env
    known_product(env)
    good_set(env, 2)
    first = review(env).json()
    upload(env, [("z.png", distinct(30), "image/png", "SECONDARY", "DETAIL")])
    assert get(env, "", sku=SKU, marketplace=AMAZON).json()["review"]["isCurrent"] is False
    second = review(env).json()
    assert second["created"] is True and second["reviewId"] != first["reviewId"] and env.n("cmo_image_review") == 2


def test_poor_pictures_produce_ranked_findings_with_reasons_and_advice(img):
    env = img.env
    known_product(env)
    r = upload(env, [("blur.png", picture(300, blur=3), "image/png", "PRIMARY", "FRONT"), ("dark.png", picture(dim=4), "image/png", "SECONDARY", "ANGLE")])
    assert r.status_code == 200
    rep = review(env).json()["report"]
    found = {(f["code"], f["imageNumber"]) for f in rep["findings"]}
    assert ("BLURRY", 1) in found and ("LOW_RESOLUTION", 1) in found and ("TOO_DARK", 2) in found
    top = rep["findings"][0]
    assert top["severity"] == "HIGH" and top["imageNumber"] == 1 and top["whyItMatters"] and top["recommendation"] and top["isMarketplaceRequirement"] is False
    assert rep["scoreState"] in ("PARTIAL", "COMPLETE")


def test_a_resized_copy_in_the_set_is_reported_as_a_repeat_and_a_different_angle_is_not(img):
    env = img.env
    known_product(env)
    big = picture(1000)
    small = picture(600)
    r = upload(env, [("a.png", big, "image/png", "PRIMARY", "FRONT"), ("b.png", small, "image/png", "SECONDARY", "FRONT")])
    assert r.status_code == 200
    rep = review(env).json()["report"]
    assert rep["duplicateCheck"]["pairs"][0]["verdict"] == "REPEAT" and rep["duplicateCheck"]["pairs"][0]["images"] == [1, 2]
    f = next(x for x in rep["findings"] if x["code"] == "REPEATED_IMAGE")
    assert f["problem"] == "Image 1 and image 2 look almost the same" and f["severity"] == "LOW" and f["isMarketplaceRequirement"] is False


def test_an_empty_set_is_not_scored_saved_or_passed(img):
    env = img.env
    known_product(env)
    r = review(env).json()
    assert r["saved"] is False and r["report"]["scoreState"] == "NOT_CALCULABLE" and r["report"]["score"] is None and r["report"]["findings"][0]["code"] == "NO_PRIMARY"
    assert env.n("cmo_image_review") == 0


def test_a_set_with_no_main_image_cannot_be_scored(img):
    env = img.env
    known_product(env)
    upload(env, [("a.png", distinct(1), "image/png", "SECONDARY", "FRONT")])
    rep = review(env).json()["report"]
    assert rep["scoreState"] == "NOT_CALCULABLE" and rep["score"] is None and "NO_PRIMARY" in {f["code"] for f in rep["findings"]}


def test_images_are_per_marketplace(img):
    env = img.env
    known_product(env)
    upload(env, [("a.png", distinct(1), "image/png", "PRIMARY", "FRONT")])
    assert get(env, "", sku=SKU, marketplace=FLIPKART).json()["images"] == []
    assert review(env, marketplace=FLIPKART).json()["saved"] is False


# ------------------------------------------------------------------------------------------------ tenant isolation and permissions
def test_another_seller_sees_none_of_it_and_cannot_reach_the_files_or_assign_the_images(img):
    env = img.env
    known_product(env)
    a = upload(env, [("a.png", distinct(1), "image/png", "PRIMARY", "FRONT")]).json()["results"][0]["assetId"]
    review(env)
    other, other_headers = env.other_tenant()
    assert get(env, "", headers=other_headers, sku=SKU, marketplace=AMAZON).status_code == 404  # not their product
    assert get(env, f"/{a}/file", headers=other_headers).status_code == 404
    assert env.n("cmo_product_image", tenant=other) == 0 and env.n("cmo_image_review", tenant=other) == 0 and env.n("seller_image_asset", tenant=other) == 0
    # their own product with the same SKU cannot adopt the first seller's image either
    env.post("title-sets", {"request_key": "o1", "sku": SKU, "product_name": "Theirs", "marketplaces": [AMAZON]}, headers=other_headers)
    r = env.post("product-images/assign", {"sku": SKU, "marketplace": AMAZON, "items": [{"assetId": a, "role": "PRIMARY", "shotType": "FRONT"}]}, headers=other_headers)
    assert r.status_code == 404 and env.n("cmo_product_image", tenant=other) == 0
    assert get(env, "", headers=other_headers, sku=SKU, marketplace=AMAZON).json()["images"] == []
    mine = get(env, f"/{a}/file")
    assert mine.status_code == 200 and mine.headers["content-type"] == "image/png" and mine.content[:8] == b"\x89PNG\r\n\x1a\n" and mine.headers["x-content-type-options"] == "nosniff"


def test_an_uploaded_but_unassigned_image_is_not_served_by_the_images_page(img):
    env = img.env
    up = img.upload(distinct(1), "image/png", "p.png").json()
    assert get(env, f"/{up['assetId']}/file").status_code == 404


def test_unauthenticated_and_unpermitted_requests_do_nothing(img):
    env = img.env
    known_product(env)
    f = [("a.png", distinct(1), "image/png", "PRIMARY", "FRONT")]
    assert upload(env, f, headers={}).status_code == 401 and get(env, "", headers={}, sku=SKU, marketplace=AMAZON).status_code == 401
    no_cmo, _ = _login(env.fake_clerk, env.tenant, role=PARTNER_ROLE, permissions={})
    assert upload(env, f, headers=no_cmo).status_code == 403 and review(env, headers=no_cmo).status_code == 403
    no_upload, _ = _login(env.fake_clerk, env.tenant, role=PARTNER_ROLE, permissions={"agent.cmo": True})
    r = upload(env, f, headers=no_upload)
    assert r.status_code == 403 and "files.upload" in json.dumps(r.json()) and env.n("cmo_product_image") == 0
    assert review(env, headers=no_upload).status_code == 200  # reading and reviewing need agent.cmo only


def test_assignments_and_reviews_are_append_only_for_the_application_role(img):
    env = img.env
    for table in ("cmo_product_image", "cmo_image_review"):
        rows = env.q(f"SELECT has_table_privilege('metrion_app', '{table}', 'SELECT'), has_table_privilege('metrion_app', '{table}', 'INSERT'), "
                     f"has_table_privilege('metrion_app', '{table}', 'UPDATE'), has_table_privilege('metrion_app', '{table}', 'DELETE')")
        assert rows[0] == (True, True, False, False)
        assert env.q(f"SELECT relforcerowsecurity FROM pg_class WHERE relname = '{table}'")[0][0] is True


def test_a_chat_photo_is_never_added_without_the_explicit_call_and_an_unknown_one_adds_nothing(img):
    env = img.env
    known_product(env)
    r = env.post("product-images/from-chat", {"sku": SKU, "marketplace": AMAZON, "investigationId": str(uuid.uuid4()), "attachmentId": str(uuid.uuid4())})
    assert r.status_code == 404 and env.n("cmo_product_image") == 0 and env.n("seller_image_asset") == 0


def test_the_existing_vision_analysis_path_is_untouched_by_m9(img):
    env = img.env
    up = img.upload(distinct(1), "image/png", "p.png")
    assert up.status_code == 200 and up.json()["unitsBilled"] == 0
    assert env.n("product_image_analysis") == 0 and img.vision.calls == 0
    known_product(env)
    good_set(env, 2)
    review(env)
    assert img.vision.calls == 0 and env.n("product_image_analysis") == 0  # M9 never calls the vision model
