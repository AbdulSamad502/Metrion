"""CMO 3.0 M7 against a real Postgres, through the real API: listing history, revision lineage, deterministic version comparison, keyword movement, claim and audit changes, evidence-based
suggestions, performance integrity, tenant isolation, permissions and idempotency. Everything is read-only and free: no unit, no metered event, no model call and no new version is created by
looking at the history. Acceptance IDs M7-nn: docs/CMO-3.0/CMO_ACCEPTANCE_TESTS.md section G."""

from __future__ import annotations

import json
import os
import uuid

import pytest
from sqlalchemy import text
from tests.integration.test_cmo_api import AMAZON, FLIPKART, _erase_cmo_rows, _login, ctx_engine, env, fake_clerk  # noqa: F401
from tests.integration.test_cmo_m6_integration import ListingProvider, body, gens, ru_env

pytestmark = pytest.mark.skipif(not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL"), reason="needs a live Postgres")

BASE = "/api/v1/cmo/listing-history"
EDIT2 = "Change bullet 2 to: Holds 1 litre of water"
EDIT3 = "Change description to: A reusable stainless steel bottle that holds 1 litre. Easy to carry and easy to clean."


def get(env, path="", headers=None, **params):
    return env.client().get(BASE + path, params=params or None, headers=headers or env.headers)


def edit(env, gid, message):
    r = env.client().post(f"/api/v1/cmo/listing/{gid}/edit", json={"message": message}, headers=env.headers)
    assert r.status_code == 200, r.text
    return r.json()["generationId"]


def three(env):
    """v1 (Metrion's original) -> v2 (seller edit, bullet 2) -> v3 (seller edit, description)."""
    ru_env(env, ListingProvider())
    v1 = env.post("full-listing", body()).json()["card"]["generationId"]
    v2 = edit(env, v1, EDIT2)
    v3 = edit(env, v2, EDIT3)
    return v1, v2, v3


def footprint(env):
    return {"gens": env.n("cmo_generation"), "events": len(env.events()), "usage": env.n("cmo_result_usage_event"), "calls": env.provider.calls}


# ---------------------------------------------------------------- A. listing history (M7-01..M7-10)
def test_m7_01_to_05_the_history_lists_every_version_newest_first_with_source_parent_and_states(env):
    v1, v2, v3 = three(env)
    before = footprint(env)
    r = get(env)
    assert r.status_code == 200, r.text
    h = r.json()
    assert h["kind"] == "LISTING_HISTORY" and h["view"] == "HISTORY" and h["total"] == 3 and h["empty"] is False
    assert [v["id"] for v in h["versions"]] == [v3, v2, v1] and [v["number"] for v in h["versions"]] == [3, 2, 1]  # all versions; the latest first
    latest, mid, first = h["versions"]
    assert latest["isLatest"] is True and mid["isLatest"] is False
    assert (first["source"], first["parentId"], first["parentNumber"]) == ("ORIGINAL", None, None) and "Original" in first["sourceText"]  # the original is retrievable
    assert (mid["source"], mid["parentNumber"], mid["changedSection"]) == ("SELLER_EDIT", 1, "BULLET 2") and mid["sourceText"] == "Your own edit: bullet 2"
    assert (latest["source"], latest["parentNumber"], latest["changedSection"], latest["originalNumber"]) == ("SELLER_EDIT", 2, "DESCRIPTION", 1)
    assert h["groups"] == [{"sku": first["sku"], "product": h["groups"][0]["product"], "marketplace": "AMAZON", "versionCount": 3, "latestNumber": 3, "latestId": v3}]
    for v in h["versions"]:  # the states are separate recorded facts; nothing is published and the latest is not assumed approved
        assert v["states"]["approvedForUse"]["done"] is False and v["states"]["published"] == {"known": False}
    assert "not know which version, if any, is live" in h["published"]
    assert footprint(env) == before  # reading history creates nothing, bills nothing, calls no model


def test_m7_approval_state_belongs_to_one_version_only(env):
    v1, v2, v3 = three(env)
    assert env.client().post(f"/api/v1/cmo/listing/{v2}/approve", headers=env.headers).status_code == 200
    by = {v["number"]: v for v in get(env).json()["versions"]}
    assert by[2]["states"]["approvedForUse"]["done"] is True and by[1]["states"]["approvedForUse"]["done"] is False and by[3]["states"]["approvedForUse"]["done"] is False
    assert by[3]["isLatest"] and not by[3]["states"]["approvedForUse"]["done"]  # the latest version is not assumed approved


def test_m7_06_07_filter_by_marketplace_and_product_and_the_two_markets_do_not_mix(env):
    v1, v2, v3 = three(env)
    f = env.post("full-listing", {**body("fk"), "marketplace": FLIPKART})
    assert f.status_code == 200 and f.json()["status"] in ("COMPLETE", "PARTIAL"), f.text
    fid = f.json()["card"]["generationId"]
    amazon = get(env, marketplace="AMAZON").json()
    flip = get(env, marketplace="FLIPKART").json()
    assert [v["id"] for v in amazon["versions"]] == [v3, v2, v1] and [v["id"] for v in flip["versions"]] == [fid] and flip["versions"][0]["number"] == 1  # numbering is per product + marketplace
    assert get(env).json()["total"] == 4 and len(get(env).json()["groups"]) == 2
    sku = amazon["versions"][0]["sku"]
    assert get(env, sku=sku).json()["total"] == 4 and get(env, sku="no-such-product").json()["empty"] is True
    assert get(env, marketplace="EBAY").status_code == 422


def test_m7_08_an_empty_history_is_empty_not_an_error(env):
    r = get(env)
    assert r.status_code == 200 and r.json()["empty"] is True and r.json()["versions"] == [] and r.json()["total"] == 0 and r.json()["groups"] == []


def test_m7_09_a_missing_or_foreign_version_is_not_found_and_looks_the_same(env):
    v1, v2, v3 = three(env)
    assert get(env, f"/{uuid.uuid4()}").status_code == 404
    assert get(env, f"/{uuid.uuid4()}/recommendations").status_code == 404
    assert get(env, "/compare", older=v1, newer=str(uuid.uuid4())).status_code == 404
    assert get(env, "/not-a-uuid").status_code == 422


def test_m7_10_history_is_paged(env):
    v1, v2, v3 = three(env)
    first = get(env, limit=2, offset=0).json()
    second = get(env, limit=2, offset=2).json()
    assert [v["number"] for v in first["versions"]] == [3, 2] and first["hasMore"] is True and first["total"] == 3
    assert [v["number"] for v in second["versions"]] == [1] and second["hasMore"] is False
    assert get(env, limit=1000).json()["limit"] == 100 and get(env, limit=0).json()["limit"] == 1


# ---------------------------------------------------------------- B. lineage (M7-11..M7-18)
def test_m7_11_13_17_seller_edits_keep_every_earlier_version_unchanged(env):
    v1, v2, v3 = three(env)
    d1, d2, d3 = (get(env, f"/{x}").json() for x in (v1, v2, v3))
    assert d1["sections"]["bullets"][1] != d2["sections"]["bullets"][1] and d2["sections"]["bullets"][1].startswith("Holds 1 litre of water")  # v1 still has its own bullet 2
    assert d2["sections"]["description"] == d1["sections"]["description"] and d3["sections"]["bullets"] == d2["sections"]["bullets"]
    assert (d3["parent"]["id"], d3["parent"]["number"], d2["parent"]["number"], d1["parent"], d3["original"]["number"], d3["versionCount"]) == (v2, 2, 1, None, 1, 3)
    assert d2["whyRevised"]["reasonRecorded"] is False and "not your reason" in d2["whyRevised"]["note"] and d2["whyRevised"]["section"] == "BULLET 2"
    stored = env.q("SELECT id::text, output_structured -> 'revision_of' FROM cmo_generation WHERE output_type = 'LISTING_COPY' ORDER BY created_at")
    assert [r[0] for r in stored] == [v1, v2, v3] and [r[1] for r in stored] == [None, v1, v2]  # the stored lineage is exactly what the history shows


def test_m7_16_a_duplicate_edit_is_served_once_and_the_history_does_not_grow(env):
    v1, v2, v3 = three(env)
    again = env.client().post(f"/api/v1/cmo/listing/{v1}/edit", json={"message": EDIT2}, headers=env.headers).json()
    assert again["reused"] is True and again["generationId"] == v2
    assert get(env).json()["total"] == 3


def test_m7_12_a_model_rewrite_is_recorded_as_ai_assisted_and_billed_once_while_viewing_it_is_free(env):
    from tests.integration.test_cmo_m6_rewrite_integration import GOOD, RewriteProvider, listing as rw_listing, rw_body

    card = rw_listing(env, rewrites=[GOOD])
    v1 = card["generationId"]
    r = env.post("listing-rewrite", rw_body(v1))
    assert r.status_code == 200 and r.json()["status"] == "COMPLETE" and r.json()["unitsBilled"] == 1, r.text
    v2 = r.json()["card"]["generationId"]
    billed = len(env.events())
    h = get(env).json()
    top = h["versions"][0]
    assert (top["id"], top["source"], top["parentNumber"], top["changedSection"]) == (v2, "AI_REWRITE", 1, "BULLET 3") and "model" in top["sourceText"].lower() and isinstance(env.provider, RewriteProvider)
    c = get(env, "/compare", older=v1, newer=v2).json()
    assert c["newer"]["sourceText"].startswith("Rewritten by the model") and c["bullets"]["counts"]["modified"] + c["bullets"]["counts"]["added"] >= 1
    assert len(env.events()) == billed  # looking at it, comparing it and asking for advice cost nothing


# ---------------------------------------------------------------- C. comparison (M7-19..M7-29)
def test_m7_19_to_27_comparing_two_non_consecutive_versions_shows_the_exact_differences(env):
    v1, v2, v3 = three(env)
    before = footprint(env)
    r = get(env, "/compare", older=v1, newer=v3)
    assert r.status_code == 200, r.text
    c = r.json()
    assert (c["view"], c["older"]["number"], c["newer"]["number"], c["swapped"], c["identical"]) == ("COMPARE", 1, 3, False, False)
    assert c["sectionsChanged"]["bullets"] and c["sectionsChanged"]["description"] and not c["sectionsChanged"]["title"]
    assert c["title"]["changed"] is False and c["title"]["characterDelta"] == 0
    mod = [i for i in c["bullets"]["items"] if i["status"] == "modified"]
    assert len(mod) == 1 and mod[0]["old"] != mod[0]["new"] and mod[0]["new"].startswith("Holds 1 litre of water") and mod[0]["diff"]["addedWords"]  # the real text, not a summary
    assert c["bullets"]["counts"]["unchanged"] == 2 and c["description"]["changed"] is True and c["description"]["characterDelta"] != 0
    assert c["description"]["counts"]["added"] + c["description"]["counts"]["modified"] >= 1
    assert footprint(env) == before  # comparing regenerates nothing and bills nothing
    assert get(env, f"/{v1}").json()["sections"]["description"] != get(env, f"/{v3}").json()["sections"]["description"]  # the older text is preserved, not overwritten


def test_m7_28_identical_versions_and_the_order_asked_for(env):
    v1, v2, v3 = three(env)
    same = get(env, "/compare", older=v1, newer=v1).json()
    assert same["identical"] is True and not any(same["sectionsChanged"].values()) and same["keywordMovement"]["counts"]["ADDED"] == 0
    swapped = get(env, "/compare", older=v3, newer=v1).json()
    assert swapped["swapped"] is True and swapped["older"]["number"] == 1 and swapped["newer"]["number"] == 3  # the earlier version is always the older
    assert get(env, "/compare", older=v1, newer=v3).json()["bullets"] == swapped["bullets"]  # reproducible


def test_m7_29_sections_a_marketplace_does_not_have_are_unavailable_not_changed(env):
    v1, v2, v3 = three(env)
    c = get(env, "/compare", older=v1, newer=v2).json()
    assert c["hashtags"]["available"] is False and c["hashtags"]["reason"] == "NOT_PART_OF_THESE_VERSIONS" and c["hashtags"]["changed"] is False
    f = env.post("full-listing", {**body("fk"), "marketplace": FLIPKART}).json()["card"]["generationId"]
    f2 = edit(env, f, EDIT2)
    fc = get(env, "/compare", older=f, newer=f2).json()
    assert fc["backendTerms"]["available"] is False and fc["backendTerms"]["reason"] == "NOT_USED_BY_THIS_MARKETPLACE"


def test_m7_18_versions_of_different_marketplaces_are_never_compared(env):
    v1, v2, v3 = three(env)
    f = env.post("full-listing", {**body("fk"), "marketplace": FLIPKART}).json()["card"]["generationId"]
    r = get(env, "/compare", older=v1, newer=f)
    assert r.status_code == 422 and r.json()["detail"]["code"] in ("DIFFERENT_MARKETPLACE", "DIFFERENT_PRODUCT")


# ---------------------------------------------------------------- D. keyword intelligence (M7-30..M7-36)
def test_m7_30_to_36_keyword_movement_is_computed_from_the_saved_text_and_traced_or_marked_unavailable(env):
    v1, v2, v3 = three(env)
    c = get(env, "/compare", older=v1, newer=v3).json()
    km = c["keywordMovement"]
    assert km["counts"].keys() >= {"ADDED", "REMOVED", "RETAINED", "MOVED"} and "not assessed" in km["limits"].lower()
    for row in km["rows"]:
        assert row["result"] in ("ADDED", "REMOVED", "RETAINED", "MOVED") and row["trace"]["state"] in ("TRACEABLE", "NOT_IN_CURRENT_CANDIDATES", "NOT_A_RESEARCHED_CANDIDATE")
        if row["trace"]["state"] != "TRACEABLE":
            assert row["trace"]["evidence"] == "UNAVAILABLE" and row["trace"]["candidateId"] is None  # never invented
        assert "searchVolume" not in row["trace"] and "volume" not in json.dumps(row).lower().replace("search volume, ranking and demand are not assessed", "")
        if row["result"] == "REMOVED":
            assert row["after"] == []  # removed means in no section at all; a keyword that merely moved is MOVED
        if row["result"] == "MOVED":
            assert row["before"] and row["after"] and row["before"] != row["after"]
    assert c["evidence"]["candidates"]["kind"] in ("SAVED_M2_ANALYSIS", "COMPUTED_FROM_CONFIRMED_FACTS")
    assert c["keywords"]["available"] is True


def test_m7_34_a_saved_m2_analysis_gives_each_researched_keyword_its_saved_candidate_id(env):
    v1, v2, v3 = three(env)
    r = env.post("keyword-intelligence", {"request_key": "kw1", "sku": get(env).json()["versions"][0]["sku"], "marketplace": AMAZON})
    if r.status_code != 200:
        pytest.skip(f"keyword analysis not available in this fixture ({r.status_code})")
    c = get(env, "/compare", older=v1, newer=v3).json()
    traced = [x for x in c["keywordMovement"]["rows"] if x["trace"]["state"] == "TRACEABLE"]
    assert c["evidence"]["candidates"]["kind"] == "SAVED_M2_ANALYSIS" and traced
    assert all(x["trace"]["candidateId"] and x["trace"]["candidateId"].startswith(c["evidence"]["candidates"]["analysisId"]) for x in traced)


# ---------------------------------------------------------------- E. content, claims and audits (M7-37..M7-43)
def corrupt(env, gid, bullets):
    with env.cengine.begin() as conn:  # the owner role, to force a version the application would have refused (the app role cannot rewrite a version)
        conn.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": str(env.tenant)})
        conn.execute(text("UPDATE cmo_generation SET output_structured = jsonb_set(output_structured, '{bullets}', CAST(:b AS jsonb)) WHERE id = :g"), {"g": gid, "b": json.dumps(bullets)})


def test_m7_37_40_a_newly_introduced_unsupported_claim_is_located_explained_and_tied_to_its_audit(env):
    v1, v2, v3 = three(env)
    get(env, f"/{v1}")  # v1 is audited as it stood (clean of this claim) before the later version is looked at
    base = get(env, f"/{v1}").json()["sections"]["bullets"]
    corrupt(env, v3, [base[0], "Insulated and leakproof, keeps drinks cold for 24 hours", base[2]])
    c = get(env, "/compare", older=v1, newer=v3).json()
    assert c["claims"]["available"] is True and c["claims"]["new"], c["claims"]
    claim = c["claims"]["new"][0]
    assert claim["section"] == "BULLET 2" and claim["auditCheck"] in ("A04", "A05") and claim["reference"] == "your confirmed product facts" and claim["why"] and claim["nextStep"]
    assert any(f["section"] == "BULLET 2" and f["severity"] == "BLOCKER" for f in c["audit"]["new"]) and c["audit"]["newerVerdict"] == "BLOCKED"
    assert c["audit"]["olderVerdict"] != "BLOCKED"


def test_m7_41_42_43_audits_are_per_version_resolved_and_unresolved_issues_are_told_apart_and_history_is_kept(env):
    v1, v2, v3 = three(env)
    for x in (v1, v2, v3):
        assert get(env, f"/{x}").json()["audit"]["verdict"]
    audits = env.q("SELECT generation_id::text, id::text FROM cmo_listing_audit ORDER BY created_at")
    assert {a[0] for a in audits} >= {v1, v2, v3}
    again = [get(env, f"/{x}").json() for x in (v1, v2, v3)] + [get(env, "/compare", older=v1, newer=v3).json()]
    assert env.q("SELECT generation_id::text, id::text FROM cmo_listing_audit ORDER BY created_at") == audits  # no audit was replaced or duplicated by looking again
    base = get(env, f"/{v1}").json()["sections"]["bullets"]
    corrupt(env, v1, [base[0], "Insulated body", base[2]])
    fresh = get(env, "/compare", older=v1, newer=v2).json()["audit"]  # v1's audit was saved before the change and stays as it was
    assert fresh["available"] is True and fresh["olderVerdict"] != "BLOCKED"
    assert {"new", "resolved", "unresolved"} <= fresh.keys()
    assert again[3]["audit"]["available"] is True


def test_m7_38_39_removed_confirmed_attributes_and_repeated_content_are_reported(env):
    v1, v2, v3 = three(env)
    edit4 = edit(env, v3, "Change bullet 3 to: Holds 1 litre of water")
    c = get(env, "/compare", older=v1, newer=edit4).json()
    assert c["attributes"]["available"] is True and {"removed", "introduced", "kept"} <= c["attributes"].keys()
    assert c["repetition"]["newer"]["duplicateBullets"] == [{"bullet": 3, "sameAs": 2}]  # bullet 3 now repeats bullet 2


# ---------------------------------------------------------------- F. recommendations (M7-44..M7-49)
def test_m7_44_to_49_recommendations_are_evidence_based_complete_and_free(env):
    v1, v2, v3 = three(env)
    before = footprint(env)
    base = get(env, f"/{v1}").json()["sections"]["bullets"]
    corrupt(env, v3, [base[0], "Insulated and leakproof", base[2]])
    r = get(env, f"/{v3}/recommendations")
    assert r.status_code == 200, r.text
    out = r.json()
    assert (out["view"], out["versionNumber"], out["comparedWith"]) == ("RECOMMEND", 3, 2) and out["state"] in ("RECOMMENDATIONS", "NOTHING_TO_RECOMMEND", "NO_EVIDENCE")
    assert out["recommendations"], out
    for rec in out["recommendations"]:
        assert all(rec[k] for k in ("recommendation", "section", "evidence", "reason", "nextAction", "limitations")) and rec["versionNumber"] == 3
        assert "ranking" in rec["limitations"] and "sales" in rec["limitations"]
    assert any(rec["code"] == "UNSUPPORTED_CLAIM" and rec["section"] == "BULLET 2" for rec in out["recommendations"])
    blob = json.dumps(out).lower()
    assert "will increase" not in blob and "boost sales" not in blob and "rank higher" not in blob
    assert footprint(env) == before


def test_m7_49_no_evidence_is_said_plainly(env):
    ru_env(env, ListingProvider())
    v1 = env.post("full-listing", body()).json()["card"]["generationId"]
    out = get(env, f"/{v1}/recommendations").json()
    assert out["state"] in ("RECOMMENDATIONS", "NOTHING_TO_RECOMMEND", "NO_EVIDENCE") and out["limitations"]
    if out["state"] == "NO_EVIDENCE":
        assert "not enough" in out["message"]


# ---------------------------------------------------------------- G. performance integrity (M7-50..M7-53)
def test_m7_50_53_performance_is_not_assessed_and_no_sales_or_ranking_claim_is_made(env):
    v1, v2, v3 = three(env)
    c = get(env, "/compare", older=v1, newer=v3).json()
    p = c["performance"]
    assert p["state"] == "NOT_ASSESSED" and p["periods"] == [] and p["attribution"] == "NOT_ATTRIBUTED" and "performance data" in p["missing"]
    assert "ranking" in p["never"] and "conversion" in p["never"]
    blob = json.dumps(c).lower()
    for phrase in ("improved sales", "increased sales", "more sales", "better ranking", "higher ranking", "conversion improved", "revenue grew"):
        assert phrase not in blob
    assert get(env, f"/{v3}/recommendations").json()["performance"]["state"] == "NOT_ASSESSED"


# ---------------------------------------------------------------- I. security (M7-66..M7-68)
def test_m7_66_another_tenant_sees_nothing_and_cannot_compare_or_read(env):
    v1, v2, v3 = three(env)
    other, headers = env.other_tenant()
    assert get(env, headers=headers).json()["empty"] is True
    assert get(env, f"/{v1}", headers=headers).status_code == 404
    assert get(env, f"/{v1}/recommendations", headers=headers).status_code == 404
    assert get(env, "/compare", headers=headers, older=v1, newer=v3).status_code == 404
    assert env.n("cmo_listing_audit", tenant=other) == 0  # a foreign read saved nothing


def test_m7_67_without_the_cmo_permission_nothing_is_readable(env):
    from backend.auth.permissions import PARTNER_ROLE

    v1, v2, v3 = three(env)
    denied, _ = _login(env.fake_clerk, env.tenant, role=PARTNER_ROLE, permissions={})
    for path, params in ((BASE, {}), (f"{BASE}/{v1}", {}), (f"{BASE}/{v1}/recommendations", {}), (f"{BASE}/compare", {"older": v1, "newer": v3})):
        r = env.client().get(path, params=params or None, headers=denied)
        assert r.status_code == 403 and "agent.cmo" in json.dumps(r.json()), path
    assert env.client().get(BASE).status_code in (401, 403)


def test_m7_68_the_history_routes_cannot_write_anything(env):
    v1, v2, v3 = three(env)
    for method in ("post", "put", "patch", "delete"):
        assert getattr(env.client(), method)(BASE, headers=env.headers).status_code in (404, 405)
        assert getattr(env.client(), method)(f"{BASE}/{v1}", headers=env.headers).status_code in (404, 405)
    assert [v["number"] for v in get(env).json()["versions"]] == [3, 2, 1]
    assert gens(env, "output_type = 'LISTING_COPY'")[0][4]  # the original is still there
