"""CMO 3.0 M7, second coverage pass (acceptance M7-06, 14, 15, 18, 35, 38, 41, 42, 46, 57 at integration level): real stored lineage corruption written through the owner role, real audit transitions between
saved versions, a second real product, the confirmed-fact attribute check against saved text, the live buyer-question source and a historical keyword that is no longer a saved candidate. Controlled
fixtures only; the fake provider writes the text."""

from __future__ import annotations

import json
import os
import uuid

import pytest
from sqlalchemy import text

from slim_cmo.service.models import NewFact
from slim_cmo.types import SellerFactType as F
from tests.integration.test_cmo_api import AMAZON, FLIPKART, _erase_cmo_rows, _install, ctx_engine, env, fake_clerk  # noqa: F401
from tests.integration.test_cmo_m6_integration import NAME, SKU, ListingProvider, body, ru_env

pytestmark = pytest.mark.skipif(not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL"), reason="needs a live Postgres")

BASE = "/api/v1/cmo/listing-history"
SKU2, NAME2, TITLE2 = "novaflask-500-ml", "NovaFlask 500 ml Glass Water Bottle", "NovaFlask 500 ml Glass Water Bottle"


def get(env, path="", headers=None, **params):
    return env.client().get(BASE + path, params=params or None, headers=headers or env.headers)


def edit(env, gid, message):
    r = env.client().post(f"/api/v1/cmo/listing/{gid}/edit", json={"message": message}, headers=env.headers)
    assert r.status_code == 200, r.text
    return r.json()["generationId"]


def owner(env, sql, **params):
    with env.cengine.begin() as conn:
        conn.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": str(env.tenant)})
        conn.execute(text(sql), params)


def set_bullets(env, gid, bullets):
    owner(env, "UPDATE cmo_generation SET output_structured = jsonb_set(output_structured, '{bullets}', CAST(:b AS jsonb)) WHERE id = :g", g=gid, b=json.dumps(bullets))


def set_parent(env, gid, parent):
    owner(env, "UPDATE cmo_generation SET output_structured = jsonb_set(output_structured, '{revision_of}', to_jsonb(CAST(:p AS text))) WHERE id = :g", g=gid, p=str(parent))


class NovaProvider(ListingProvider):
    """The same fake writer, saying what is true of the NovaFlask glass bottle instead of the AquaNest steel one."""

    def complete(self, *, model: str, prompt: str) -> str:
        out = super().complete(model=model, prompt=prompt)
        return out.replace(NAME, NAME2).replace("Stainless steel", "Glass").replace("stainless steel", "glass").replace("1 litre", "500 ml")


def second_product(env, key="n1", marketplace=AMAZON, colour=True):
    env.provider = NovaProvider()
    _install(env.monkeypatch, env.provider)
    env.runtime.store.save_facts(env.tenant, env.user_id, [NewFact(F.ATTRIBUTE, SKU2, "product_name", NAME2), NewFact(F.BRAND, SKU2, None, "NovaFlask"), NewFact(F.ATTRIBUTE, SKU2, "Size", "500 ml"),
                                                           NewFact(F.ATTRIBUTE, SKU2, "Material", "glass"), *([NewFact(F.ATTRIBUTE, SKU2, "Color", "blue")] if colour else [])])
    r = env.post("full-listing", {"request_key": key, "sku": SKU2, "product_name": NAME2, "brand": "NovaFlask", "marketplace": marketplace, "seller_title": TITLE2})
    assert r.status_code == 200 and r.json()["status"] in ("COMPLETE", "PARTIAL"), r.text
    return r.json()["card"]["generationId"]


def three(env):
    ru_env(env, ListingProvider())
    v1 = env.post("full-listing", body()).json()["card"]["generationId"]
    v2 = edit(env, v1, "Change bullet 2 to: Holds 1 litre of water")
    v3 = edit(env, v2, "Change description to: A reusable stainless steel bottle that holds 1 litre. Easy to carry and easy to clean.")
    return v1, v2, v3


# ---------------------------------------------------------------- M7-14 / 15 / 18: a corrupted stored lineage is reported and never followed
def test_m7_14_15_18_a_stored_parent_that_cannot_be_trusted_is_named_and_the_version_becomes_a_starting_point(env):
    v1, v2, v3 = three(env)
    flip = env.post("full-listing", {**body("fk"), "marketplace": FLIPKART}).json()["card"]["generationId"]
    nova = second_product(env)
    set_parent(env, v2, uuid.uuid4())  # a parent that does not exist
    set_parent(env, nova, v1)  # a parent of another product
    set_parent(env, flip, v1)  # a parent of another marketplace
    set_parent(env, v1, v3)  # a loop: v1 claims to come from its own descendant
    h = {v["id"]: v for v in get(env).json()["versions"]}
    assert h[v2]["lineageIssue"] == "MISSING_PARENT" and h[v2]["parentId"] is None and h[v2]["parentNumber"] is None and h[v2]["originalNumber"] == 2
    assert h[nova]["lineageIssue"] == "CROSS_PRODUCT" and h[nova]["parentId"] is None
    assert h[flip]["lineageIssue"] == "CROSS_MARKETPLACE" and h[flip]["parentId"] is None
    assert h[v1]["lineageIssue"] in ("CYCLE", "NOT_EARLIER") and h[v1]["parentId"] is None  # a version can never be its own ancestor
    assert h[v3]["parentId"] == v2 and h[v3]["lineageIssue"] is None  # the honest links are still followed
    detail = get(env, f"/{v2}").json()
    assert detail["parent"] is None and detail["version"]["lineageIssue"] == "MISSING_PARENT"
    assert get(env, "/compare", older=v1, newer=v3).status_code == 200  # a damaged link never breaks reading or comparing
    assert [v["id"] for v in get(env, marketplace="AMAZON", sku=SKU).json()["versions"]] == [v3, v2, v1]  # nothing was removed or rewritten


# ---------------------------------------------------------------- M7-06 / 18 / 57: two real products
def test_m7_06_18_two_products_have_separate_histories_numbers_and_are_never_compared(env):
    v1, v2, _ = three(env)
    nova = second_product(env)
    allh = get(env).json()
    assert allh["total"] == 4 and {g["sku"] for g in allh["groups"]} == {SKU, SKU2}
    mine, theirs = get(env, sku=SKU).json(), get(env, sku=SKU2).json()
    assert mine["total"] == 3 and [v["id"] for v in theirs["versions"]] == [nova] and theirs["versions"][0]["number"] == 1  # numbering is per product + marketplace
    assert all(v["sku"] == SKU for v in mine["versions"]) and "NovaFlask" in (theirs["versions"][0]["product"] or "")
    r = get(env, "/compare", older=v1, newer=nova)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "DIFFERENT_PRODUCT"
    other, headers = env.other_tenant()
    assert get(env, headers=headers).json()["empty"] is True and get(env, f"/{nova}", headers=headers).status_code == 404


# ---------------------------------------------------------------- M7-41 / 42: audit transitions between two saved versions
def test_m7_41_42_issues_that_were_fixed_are_resolved_and_issues_that_remain_are_unresolved(env):
    v1, v2, _ = three(env)
    v4 = edit(env, v2, "Change bullet 1 to: Stainless steel body")  # a fresh version that has not been opened (so not yet audited)
    base = get(env, f"/{v2}").json()["sections"]["bullets"]
    set_bullets(env, v4, [base[0], "Insulated and leakproof body", "Keeps drinks cold for 24 hours"])  # two unsupported claims, in bullets 2 and 3
    v5 = edit(env, v4, "Change bullet 2 to: Holds 1 litre of water")  # fixes bullet 2 only; bullet 3 still carries its claim
    a = get(env, "/compare", older=v4, newer=v5).json()["audit"]
    assert a["available"] is True and a["olderVerdict"] == "BLOCKED", a
    assert any(f["section"] == "BULLET 2" for f in a["resolved"]), a  # fixed
    assert any(f["section"] == "BULLET 3" for f in a["unresolved"]), a  # still there
    assert not any(f["section"] == "BULLET 2" for f in a["new"])
    assert "FACT_NOT_GIVEN" in {f["code"] for f in a["unresolved"]}  # an ordinary note present in both versions is unresolved, not new
    claims = get(env, "/compare", older=v4, newer=v5).json()["claims"]
    assert not any(c["section"] == "BULLET 3" for c in claims["new"])  # an old claim is not reported as introduced by the newer version
    rec = get(env, f"/{v5}/recommendations").json()
    assert any(r["code"] == "ISSUE_NOT_RESOLVED" and r["section"] == "BULLET 3" for r in rec["recommendations"]), rec["recommendations"]


# ---------------------------------------------------------------- M7-38: a confirmed attribute the revision dropped
def test_m7_38_a_confirmed_attribute_removed_by_a_revision_is_reported_and_suggested_back(env):
    ru_env(env, ListingProvider())
    env.runtime.store.save_facts(env.tenant, env.user_id, [NewFact(F.ATTRIBUTE, SKU, "Opening", "wide")])
    v1 = env.post("full-listing", body()).json()["card"]["generationId"]
    v2 = edit(env, v1, "Change bullet 3 to: Wide opening makes filling easy.")
    v3 = edit(env, v2, "Change bullet 3 to: Easy to carry")
    c = get(env, "/compare", older=v2, newer=v3).json()
    assert any(a["value"] == "wide" for a in c["attributes"]["removed"]), c["attributes"]
    assert any(a["value"] == "wide" for a in get(env, "/compare", older=v1, newer=v2).json()["attributes"]["introduced"])
    rec = get(env, f"/{v3}/recommendations").json()
    assert any(r["code"] == "REVISION_REMOVED_CONFIRMED_INFO" and "wide" in r["recommendation"] for r in rec["recommendations"]), rec["recommendations"]


# ---------------------------------------------------------------- M7-46: the live buyer-question source
def test_m7_46_an_unanswered_essential_buyer_question_comes_from_the_real_m5_source(env):
    ru_env(env, ListingProvider())
    nova = second_product(env, colour=False)  # the colour (an essential topic) was never confirmed for this product
    qs = [r for r in get(env, f"/{nova}/recommendations").json()["recommendations"] if r["code"] == "UNANSWERED_BUYER_QUESTION"]
    assert [q["refs"]["question"] for q in qs] == ["What colour is it?"], qs  # the M5 question bank, essential and not confirmed
    q = qs[0]
    assert q["section"] == "WHOLE_LISTING" and "question bank" in " ".join(q["evidence"]).lower() and q["nextAction"] and q["limitations"]
    env.runtime.store.save_facts(env.tenant, env.user_id, [NewFact(F.ATTRIBUTE, SKU2, "Color", "blue")])  # the seller answers it
    again = [r for r in get(env, f"/{nova}/recommendations").json()["recommendations"] if r["code"] == "UNANSWERED_BUYER_QUESTION"]
    assert again == []  # an answered question is no longer open
    one, headers = three(env)[0], env.headers
    assert not [r for r in get(env, f"/{one}/recommendations").json()["recommendations"] if r["code"] == "UNANSWERED_BUYER_QUESTION"]  # F6 confirmed every essential topic: nothing is invented


# ---------------------------------------------------------------- M7-35: a keyword that is no longer a saved candidate
def test_m7_35_a_historical_keyword_missing_from_the_current_saved_analysis_is_marked_not_in_current_candidates(env):
    v1, v2, v3 = three(env)
    r = env.post("keyword-intelligence", {"request_key": "kw35", "sku": SKU, "marketplace": AMAZON})
    assert r.status_code == 200, r.text
    victim = get(env, f"/{v1}").json()["keywordMap"]["candidates"][0]["keyword"]
    owner(env, "UPDATE cmo_keyword_analysis SET result = jsonb_set(result, '{candidates}', (SELECT COALESCE(jsonb_agg(c), '[]'::jsonb) FROM jsonb_array_elements(result -> 'candidates') c WHERE c ->> 'keyword' <> :k)) WHERE sku = :s",
          k=victim, s=SKU)
    c = get(env, "/compare", older=v1, newer=v3).json()
    rows = {x["keyword"]: x for x in c["keywordMovement"]["rows"]}
    assert victim in rows and rows[victim]["trace"]["state"] == "NOT_IN_CURRENT_CANDIDATES" and rows[victim]["trace"]["candidateId"] is None and rows[victim]["trace"]["evidence"] == "UNAVAILABLE"
    traced = [x for x in rows.values() if x["trace"]["state"] == "TRACEABLE"]
    assert all(x["trace"]["candidateId"].startswith(c["evidence"]["candidates"]["analysisId"] + ":") for x in traced)
