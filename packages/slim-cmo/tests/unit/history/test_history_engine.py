"""CMO 3.0 M7 pure engine: text/list diff, comparison, keyword movement, claim and audit changes, lineage, recommendations, performance integrity, chat parsing. Acceptance IDs: see
docs/CMO-3.0/CMO_ACCEPTANCE_TESTS.md section G."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from slim_cmo.history import ask, compare as cmp, diff, lineage, performance, recommend

T0 = datetime(2026, 10, 1, tzinfo=timezone.utc)
FACTS = [{"name": "Material", "value": "stainless steel"}, {"name": "Capacity", "value": "1 litre"}, {"name": "Colour", "value": "silver"}]
CANDS = [{"id": "c1", "keyword": "steel water bottle", "recommended": True, "confidence": "STRONG", "placement": ["TITLE"], "intent": "PRODUCT"},
         {"id": "c2", "keyword": "reusable", "recommended": True, "confidence": "MODERATE", "placement": ["BULLETS"], "intent": "FEATURE"},
         {"id": "c3", "keyword": "travel bottle", "recommended": True, "confidence": "WEAK", "placement": ["KEYWORDS"], "intent": "USE"}]


def audit(*findings, verdict="NEEDS_ATTENTION"):
    return {"verdict": verdict, "rulesBasis": "UNVERIFIED", "createdAt": "2026-10-01", "checks": [{"id": "A04", "name": "Claims", "status": "FAIL" if findings else "PASS"}], "findings": list(findings)}


def f(code, section, text, check="A04", sev="BLOCKER"):
    return {"check": check, "severity": sev, "section": section, "code": code, "explanation": text, "correction": "Remove it."}


def ver(n, *, title="AquaNest Steel Water Bottle 1 Litre Silver", bullets=("Holds 1 litre", "Reusable stainless steel body", "Silver finish"), desc="A bottle. It is reusable.", kw=("steel water bottle", "reusable"),
        be=("bottle",), ht=None, aud=None, src="ORIGINAL"):
    return {"id": f"v{n}", "number": n, "sku": "aquanest", "marketplace": "AMAZON", "source": src, "sourceText": src, "approved": False,
            "sections": {"title": title, "bullets": list(bullets), "description": desc, "keywords": list(kw), "backend_terms": None if be is None else list(be), "hashtags": ht}, "audit": aud}


# ---- diff -------------------------------------------------------------------------------------------------------------------------------------------------------
def test_text_diff_shows_added_removed_and_keeps_original_text():
    d = diff.text_diff("AquaNest Steel Bottle 1 Litre", "AquaNest Insulated Steel Bottle 1 Litre Silver")
    assert d["addedWords"] == ["Insulated", "Silver"] and d["removedWords"] == [] and d["characterDelta"] == len(d["new"]) - len(d["old"])
    assert d["old"] == "AquaNest Steel Bottle 1 Litre" and d["changed"]


def test_text_diff_identical_ignores_case_and_punctuation_but_reports_exact_change():
    d = diff.text_diff("Steel Bottle, 1 Litre", "steel bottle 1 litre")
    assert not d["changed"] and d["exactTextChanged"] and d["ops"][0]["op"] == "equal"


def test_text_diff_modified_wording_is_a_replace():
    d = diff.text_diff("Keeps drinks cold", "Keeps water cool")
    assert any(o["op"] == "replace" for o in d["ops"]) and "cold" in d["removedWords"] and "cool" in d["addedWords"]


def test_list_diff_classifies_unchanged_reordered_modified_added_removed():
    old = ["Holds 1 litre", "Reusable stainless steel body", "Silver finish", "Comes with a cap"]
    new = ["Reusable stainless steel body", "Holds 1 litre", "Silver finish colour", "Wide mouth opening"]
    d = diff.list_diff(old, new)
    st = {i["new"] or i["old"]: i["status"] for i in d["items"]}
    assert st["Reusable stainless steel body"] == "reordered" and st["Holds 1 litre"] == "reordered"
    assert st["Silver finish colour"] == "modified" and st["Wide mouth opening"] == "added" and st["Comes with a cap"] == "removed"
    assert d["counts"] == {"unchanged": 0, "reordered": 2, "modified": 1, "added": 1, "removed": 1}


def test_list_diff_identical_and_empty_and_duplicates():
    assert not diff.list_diff(["a b", "c d"], ["a b", "c d"])["changed"]
    assert diff.list_diff([], [])["counts"]["added"] == 0
    d = diff.list_diff(["same one", "same one"], ["same one"])
    assert d["counts"]["removed"] == 1 and d["counts"]["unchanged"] == 1


def test_sentence_diff_and_length_change():
    d = diff.sentence_diff("A bottle. It is reusable.", "A bottle. It is reusable. It fits a bag.")
    assert d["counts"]["added"] == 1 and d["counts"]["unchanged"] == 2 and d["characterDelta"] > 0


def test_term_diff_added_removed_retained_and_missing_side():
    d = diff.term_diff(["Steel Bottle", "reusable"], ["steel bottle", "travel flask"])
    assert d["added"] == ["travel flask"] and d["removed"] == ["reusable"] and d["retained"] == ["steel bottle"]
    m = diff.term_diff(None, ["x"])
    assert m["available"] and m["missingIn"] == "older" and m["added"] == ["x"] and m["changed"]
    assert diff.term_diff(None, None)["available"] is False


# ---- compare ------------------------------------------------------------------------------------------------------------------------------------------------------
def test_compare_two_versions_covers_every_section():
    a = ver(1)
    b = ver(2, title="AquaNest Insulated Steel Water Bottle 1 Litre Silver", bullets=("Reusable stainless steel body", "Holds 1 litre", "Keeps drinks cold 24 hours"), desc="A bottle. It is reusable. Great gift.",
            kw=("steel water bottle", "travel bottle"), be=("flask",), ht=["#bottle"])
    r = cmp.compare(a, b, facts=FACTS, candidates=CANDS)
    assert r["sectionsChanged"] == {"title": True, "bullets": True, "description": True, "keywords": True, "backendTerms": True, "hashtags": True} and not r["identical"]
    assert r["title"]["addedWords"] == ["Insulated"] and r["backendTerms"]["added"] == ["flask"] and r["backendTerms"]["removed"] == ["bottle"]
    assert r["hashtags"]["added"] == ["#bottle"] and r["hashtags"]["missingIn"] == "older" and r["keywords"]["added"] == ["travel bottle"] and r["keywords"]["removed"] == ["reusable"]
    assert {i["status"] for i in r["bullets"]["items"]} >= {"reordered", "added", "removed"}


def test_compare_orders_older_and_newer_whichever_way_it_is_asked():
    r = cmp.compare(ver(3, title="Other title here"), ver(1))
    assert r["swapped"] and r["older"]["number"] == 1 and r["newer"]["number"] == 3


def test_identical_versions_report_no_change():
    r = cmp.compare(ver(1), ver(2))
    assert r["identical"] and not any(r["sectionsChanged"].values()) and r["keywordMovement"]["counts"]["ADDED"] == 0


def test_missing_sections_are_unavailable_not_changed():
    r = cmp.compare(ver(1, be=None), ver(2, be=None))
    assert r["backendTerms"]["available"] is False and r["backendTerms"]["reason"] == "NOT_USED_BY_THIS_MARKETPLACE" and not r["backendTerms"]["changed"]
    r2 = cmp.compare(ver(1, bullets=()), ver(2))
    assert r2["bullets"]["counts"]["added"] == 3 and r2["bullets"]["oldCount"] == 0


def test_keyword_movement_distinguishes_added_removed_retained_moved():
    a = ver(1, title="AquaNest Steel Water Bottle", bullets=("Reusable body",), desc="Holds a lot.", kw=("steel water bottle",), be=("insulated flask",))
    b = ver(2, title="AquaNest Steel Water Bottle", bullets=("Holds a lot",), desc="Reusable and light. Travel bottle friendly.", kw=("steel water bottle",), be=())
    rows = {r["keyword"]: r for r in cmp.compare(a, b, candidates=CANDS)["keywordMovement"]["rows"]}
    assert rows["steel water bottle"]["result"] == "RETAINED"
    assert rows["reusable"]["result"] == "MOVED" and rows["reusable"]["before"] == ["BULLET 1"] and rows["reusable"]["after"] == ["DESCRIPTION"] and rows["reusable"]["crossSection"]
    assert rows["insulated flask"]["result"] == "REMOVED" and rows["travel bottle"]["result"] == "ADDED"


def test_keyword_trace_links_candidates_and_flags_missing_ones():
    a = ver(1, kw=("steel water bottle", "old term"), be=())
    b = ver(2, kw=("steel water bottle", "reusable"), be=())
    rows = {r["keyword"]: r for r in cmp.compare(a, b, candidates=CANDS)["keywordMovement"]["rows"]}
    assert rows["steel water bottle"]["trace"]["candidateId"] == "c1" and rows["steel water bottle"]["trace"]["evidence"] == "AVAILABLE"
    assert rows["old term"]["trace"]["state"] == "NOT_A_RESEARCHED_CANDIDATE" and rows["old term"]["trace"]["evidence"] == "UNAVAILABLE" and rows["old term"]["trace"]["candidateId"] is None
    a["keywordMap"] = {"candidates": [{"keyword": "old term", "intent": "USE"}]}
    again = {r["keyword"]: r for r in cmp.compare(a, b, candidates=CANDS)["keywordMovement"]["rows"]}
    assert again["old term"]["trace"]["state"] == "NOT_IN_CURRENT_CANDIDATES"
    assert "volume" in cmp.compare(a, b)["keywordMovement"]["limits"].lower() and all("volume" not in k for k in rows["reusable"]["trace"])


def test_new_unsupported_claim_is_located_explained_and_tied_to_the_audit():
    fl = f("UNSUPPORTED_CLAIM", "BULLET 3", "It says or implies “keeps drinks cold 24 hours”, which you have not confirmed for this product.")
    r = cmp.compare(ver(1, aud=audit()), ver(2, aud=audit(fl, verdict="BLOCKED")))
    c = r["claims"]["new"]
    assert len(c) == 1 and c[0]["section"] == "BULLET 3" and c[0]["claim"] == "keeps drinks cold 24 hours" and c[0]["auditCode"] == "UNSUPPORTED_CLAIM" and "confirmed" in c[0]["reference"] and c[0]["introducedHere"] is True
    assert r["audit"]["new"][0]["code"] == "UNSUPPORTED_CLAIM" and r["audit"]["newerVerdict"] == "BLOCKED"


def test_audit_changes_new_resolved_unresolved_and_check_status_change():
    keep = f("W2_REPEATED_ACROSS_BULLETS", "BULLETS", "“steel” is in 3 different bullets.", "A08", "WARNING")
    gone = f("UNCONFIRMED_TOPIC", "BULLET 2", "It touches “insulation”, which is not confirmed.")
    new = f("UNSUPPORTED_NUMBER", "DESCRIPTION", "Contains number(s) 24.", "A05")
    r = cmp.compare(ver(1, aud=audit(keep, gone, verdict="BLOCKED")), ver(2, aud=audit(keep, new, verdict="BLOCKED")))["audit"]
    assert [x["code"] for x in r["new"]] == ["UNSUPPORTED_NUMBER"] and [x["code"] for x in r["resolved"]] == ["UNCONFIRMED_TOPIC"] and [x["code"] for x in r["unresolved"]] == ["W2_REPEATED_ACROSS_BULLETS"]


def test_missing_audit_is_unavailable_never_clean():
    r = cmp.compare(ver(1), ver(2, aud=audit()))
    assert r["audit"]["available"] is False and r["audit"]["reason"] == "AUDIT_MISSING_FOR_OLDER"
    assert cmp.compare(ver(1), ver(2))["claims"]["available"] is False


def test_removed_and_introduced_confirmed_attributes():
    a = ver(1)
    b = ver(2, title="AquaNest Water Bottle 1 Litre", bullets=("Holds 1 litre", "Silver finish"), desc="A bottle.", kw=("steel water bottle",))
    r = cmp.compare(a, b, facts=FACTS)["attributes"]
    assert [x["value"] for x in r["removed"]] == ["stainless steel"] and r["introduced"] == [] and {x["value"] for x in r["kept"]} == {"1 litre", "silver"}
    assert cmp.compare(a, b, facts=None)["attributes"]["available"] is False


def test_repeated_content_is_reported_per_version():
    v = ver(2, bullets=("Holds 1 litre", "Holds 1 litre", "Silver finish"), desc="It is reusable. It is reusable. Holds 1 litre.")
    rep = cmp.compare(ver(1), v)["repetition"]["newer"]
    assert rep["duplicateBullets"] == [{"bullet": 2, "sameAs": 1}] and rep["repeatedSentences"] and rep["descriptionSentencesCopiedFromBullets"] == ["Holds 1 litre."]


def test_compare_is_reproducible():
    a, b = ver(1), ver(2, title="Different Title For Aqua", desc="Other text.")
    assert cmp.compare(a, b, facts=FACTS, candidates=CANDS) == cmp.compare(a, b, facts=FACTS, candidates=CANDS)


# ---- lineage ------------------------------------------------------------------------------------------------------------------------------------------------------
def row(i, parent=None, sku="aquanest", mp="AMAZON", src="ORIGINAL", sec=None, at=0):
    return {"id": f"p{i}", "createdAt": T0 + timedelta(hours=at or i), "parentId": parent, "sku": sku, "marketplace": mp, "source": src, "section": sec}


def test_lineage_example_four_versions():
    out = lineage.resolve([row(1), row(2, "p1", src="SELLER_EDIT", sec="BULLET 2"), row(3, "p2", src="AI_REWRITE", sec="DESCRIPTION"), row(4, "p3", src="SELLER_EDIT", sec="KEYWORDS")])
    assert [o["number"] for o in out] == [1, 2, 3, 4] and [o["parentNumber"] for o in out] == [None, 1, 2, 3] and all(o["originalNumber"] == 1 for o in out)
    assert out[1]["sourceText"] == "Your own edit: bullet 2" and "model" in out[2]["sourceText"] and out[3]["sourceText"].endswith("the keywords") and out[0]["sourceText"].startswith("Original")


def test_lineage_rejects_missing_cross_product_cross_marketplace_and_cycles():
    out = {o["id"]: o for o in lineage.resolve([row(1), row(2, "ghost"), row(3, "p1", sku="other"), row(4, "p1", mp="FLIPKART"), row(5, "p6"), row(6, "p5")])}
    assert out["p2"]["lineageIssue"] == "MISSING_PARENT" and out["p2"]["parentId"] is None and out["p2"]["originalNumber"] == 2
    assert out["p3"]["lineageIssue"] == "CROSS_PRODUCT" and out["p4"]["lineageIssue"] == "CROSS_MARKETPLACE"
    assert out["p5"]["lineageIssue"] in ("NOT_EARLIER", "CYCLE") and out["p6"]["parentId"] == "p5"  # a later child of an earlier row is fine; the backwards link is the one refused
    self_loop = lineage.resolve([row(1, "p1")])[0]
    assert self_loop["lineageIssue"] == "CYCLE" and self_loop["parentId"] is None


def test_lineage_numbers_are_stable_when_a_version_is_added():
    first = lineage.resolve([row(1), row(2, "p1")])
    later = lineage.resolve([row(1), row(2, "p1"), row(3, "p2")])
    assert [o["number"] for o in first] == [1, 2] and [o["id"] for o in later[:2]] == ["p1", "p2"]


def test_source_of_reads_what_was_stored():
    assert lineage.source_of({}, has_parent=False) == "ORIGINAL"
    assert lineage.source_of({"revision": {"by": "SELLER_TEXT"}, "revision_of": "x"}, has_parent=True) == "SELLER_EDIT"
    assert lineage.source_of({"revision": {"by": "MODEL_REWRITE"}}, has_parent=True) == "AI_REWRITE"
    assert lineage.source_of({"revision_of": "x"}, has_parent=True) == "REVISION_UNKNOWN"


def test_validate_pair_refuses_other_products_and_markets():
    a, b = ver(1), ver(2)
    assert lineage.validate_pair(a, b) is None and lineage.validate_pair(a, None) == "VERSION_NOT_FOUND"
    assert lineage.validate_pair(a, {**b, "sku": "x"}) == "DIFFERENT_PRODUCT" and lineage.validate_pair(a, {**b, "marketplace": "FLIPKART"}) == "DIFFERENT_MARKETPLACE"


# ---- recommendations ----------------------------------------------------------------------------------------------------------------------------------------------
def test_recommendations_cover_the_evidence_rules_and_each_has_every_field():
    fl = f("UNSUPPORTED_CLAIM", "BULLET 3", "It says “keeps drinks cold”, which you have not confirmed.")
    prev = ver(1, aud=audit(f("W2_REPEATED_ACROSS_BULLETS", "BULLETS", "“steel” repeats.", "A08", "WARNING")))
    late = ver(2, title="AquaNest Water Bottle", bullets=("Keeps drinks cold",), desc="A bottle.", kw=(), be=(), aud=audit(fl, f("W2_REPEATED_ACROSS_BULLETS", "BULLETS", "“steel” repeats.", "A08", "WARNING"), verdict="BLOCKED"))
    comp = cmp.compare(prev, late, facts=FACTS, candidates=CANDS)
    out = recommend.recommend(late, previous=prev, comparison=comp, facts=FACTS, candidates=CANDS, unanswered_questions=[{"question": "Is it dishwasher safe?"}], limit=50)
    codes = {r["code"] for r in out["recommendations"]}
    assert {"UNSUPPORTED_CLAIM", "MISSING_SUPPORTED_KEYWORD", "MISSING_CONFIRMED_ATTRIBUTE", "UNANSWERED_BUYER_QUESTION", "REVISION_REMOVED_CONFIRMED_INFO", "ISSUE_NOT_RESOLVED",
                     "REVISION_INTRODUCED_UNSUPPORTED_WORDING"} <= codes
    for r in out["recommendations"]:
        assert all(r[k] for k in ("recommendation", "section", "evidence", "reason", "nextAction", "limitations")) and r["versionNumber"] == 2 and "ranking" in r["limitations"]


def test_recommendations_never_use_weak_candidates_or_promise_results():
    late = ver(2, kw=(), be=(), aud=audit())
    out = recommend.recommend(late, candidates=CANDS)
    kws = [r["refs"]["keyword"] for r in out["recommendations"] if r["code"] == "MISSING_SUPPORTED_KEYWORD"]
    assert "travel bottle" not in kws  # WEAK evidence is never recommended
    blob = str(out).lower()
    assert "increase sales" not in blob and "rank higher" not in blob and "improve conversion" not in blob


def test_no_evidence_is_said_plainly():
    out = recommend.recommend(ver(1))
    assert out["state"] == recommend.NO_EVIDENCE and out["recommendations"] == [] and "not enough" in out["message"]
    clean = recommend.recommend(ver(1, aud=audit(verdict="CHECKED_NOT_VERIFIED")))
    assert clean["state"] == "NOTHING_TO_RECOMMEND"


def test_moved_to_a_lower_place_and_removed_researched_keyword():
    a = ver(1, title="AquaNest Steel Water Bottle", bullets=("Reusable body",), kw=("steel water bottle",), be=())
    b = ver(2, title="AquaNest Bottle", bullets=("Holds a lot",), desc="Reusable and light.", kw=(), be=(), aud=audit())
    out = recommend.recommend(b, previous=a, comparison=cmp.compare(a, b, candidates=CANDS), candidates=CANDS)
    codes = {r["code"] for r in out["recommendations"]}
    assert "KEYWORD_MOVED_LOWER" in codes and "REVISION_REMOVED_KEYWORD" in codes


# ---- performance integrity ---------------------------------------------------------------------------------------------------------------------------------------
def obs(s, e, v, src="UPLOAD:amazon-business-report", metric="units"):
    return {"source": src, "metric": metric, "periodStart": s, "periodEnd": e, "value": v}


def test_performance_unavailable_is_not_assessed_and_says_what_is_missing():
    for none in (None, [], [obs("2026-09-01", "2026-09-30", 10)]):
        r = performance.assess(none)
        assert r["state"] == "NOT_ASSESSED" and "uploaded sales or traffic reports" in r["missing"] and r["periods"] == []
    assert "conversion" in r["never"] and "ranking" in r["never"]


def test_comparable_periods_are_observed_but_never_attributed():
    r = performance.assess([obs("2026-10-01", "2026-10-30", 20), obs("2026-09-01", "2026-09-30", 10)])
    assert r["state"] == "OBSERVED_COMPARABLE" and r["attribution"] == "NOT_ATTRIBUTED" and [p["value"] for p in r["periods"]] == [10, 20] and "does not show that the listing change caused" in r["note"]


def test_incomparable_periods_are_refused_with_reasons():
    r = performance.assess([obs("2026-09-01", "2026-09-30", 10), obs("2026-10-01", "2026-10-07", 5, src="OTHER", metric="revenue")])
    assert r["state"] == "INCOMPARABLE" and {"DIFFERENT_SOURCE", "DIFFERENT_MEASURE", "DIFFERENT_PERIOD_LENGTH"} <= set(r["reasons"])
    assert "OVERLAPPING_PERIODS" in performance.assess([obs("2026-09-01", "2026-09-30", 1), obs("2026-09-15", "2026-10-14", 2)])["reasons"]
    assert performance.assess([obs("garbage", "2026-09-30", 1), obs("2026-10-01", "2026-10-30", 2)])["state"] == "NOT_ASSESSED"


# ---- chat requests ------------------------------------------------------------------------------------------------------------------------------------------------
def test_the_fourteen_requests_are_recognised():
    cases = {
        "Show my listing history.": ask.HISTORY, "Show my latest AquaNest listing.": ask.VERSION, "Show my previous listing.": ask.VERSION, "Compare my old and new listings.": ask.COMPARE,
        "Compare version 1 and version 3.": ask.COMPARE, "What changed in my latest listing?": ask.CHANGES, "Why was this listing revised?": ask.WHY_REVISED,
        "What claims were introduced in the latest revision?": ask.CLAIMS, "Which listing version is approved for use?": ask.APPROVED, "Show my Amazon listing changes.": ask.CHANGES,
    }
    for text, kind in cases.items():
        assert ask.parse(text) is not None and ask.parse(text).kind == kind, text
    for text, kind in {"Which keywords were removed?": ask.KEYWORDS_REMOVED, "Which keywords did I add?": ask.KEYWORDS_ADDED, "Show me the audit changes.": ask.AUDIT_CHANGES, "What should I improve next?": ask.IMPROVE}.items():
        assert ask.parse(text) is None and ask.parse(text, in_context=True).kind == kind, text


def test_request_details_product_marketplace_versions_and_position():
    a = ask.parse("Compare version 2 and version 4 of my AquaNest bottle on Flipkart")
    assert (a.kind, a.versions, a.marketplace, a.product_hint) == (ask.COMPARE, (2, 4), "FLIPKART", "aquanest bottle")
    b = ask.parse("Compare my previous AquaNest listing with the latest one")
    assert b.relative == "PREVIOUS_LATEST" and b.product_hint == "aquanest" and ask.parse("Compare my old and new listings").relative == "OLD_NEW"
    assert ask.parse("show my previous listing").relative == "PREVIOUS" and ask.parse("show my original listing").relative == "ORIGINAL" and ask.parse("compare version 1 to 3").versions == (1, 3)


def test_unrelated_messages_are_left_alone():
    for text in ("what is my margin", "write titles for my bottle", "compare my profit this month and last", "hello", "show me my orders", "", "x" * 500):
        assert ask.parse(text) is None, text
