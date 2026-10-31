"""CMO 3.0 M6, second traceability pass (Section F rows N-05g, N-05j, N-05l, N-14g): end-to-end checks through the real API on a real Postgres that the earlier unit-level evidence did not give. Where a row's
remaining gap is an unimplemented feature (NEEDS_SELLER_INPUT, the side-by-side M3/M5 card), that is stated in CMO_M6_TRACEABILITY.md and these tests do not pretend otherwise."""

from __future__ import annotations

import json
import os

import pytest

from tests.integration.test_cmo_api import FLIPKART, _erase_cmo_rows, ctx_engine, env, fake_clerk  # noqa: F401
from tests.integration.test_cmo_m6_integration import DATA_MARK, SKU, ListingProvider, body, ru_env

pytestmark = pytest.mark.skipif(not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL"), reason="needs a live Postgres")

UNCONFIRMED = ("insulated", "leakproof", "dishwasher", "bpa", "warranty")


def card_for(env, key="k1", **extra):
    ru_env(env, ListingProvider())
    out = env.post("full-listing", {**body(key), **extra}).json()
    assert out["status"] == "COMPLETE", out
    return out["card"]


def test_n05j_unanswered_buyer_questions_are_listed_as_not_claimed_and_never_reach_the_generated_text(env):
    c = card_for(env)
    a10 = next(x for x in c["audit"]["checks"] if x["id"] == "A10")
    for topic in ("Dishwasher safe", "Insulated", "Leakproof", "Warranty"):
        assert topic in a10["detail"], a10  # the card lists the unanswered topics
    assert any(f["code"] == "ANSWER_NOT_SHOWN" for f in c["audit"]["findings"])
    s = c["sections"]
    text_ = " ".join([s["title"], *s["bullets"], s["description"], *s["keywords"], *(s["backend_terms"] or [])]).casefold()
    assert not [w for w in UNCONFIRMED if w in text_], text_  # none of the unconfirmed claims was written
    assert c["audit"]["verdict"] != "BLOCKED"


def test_n05g_only_researched_candidates_are_offered_to_the_writer_and_placed(env):
    c = card_for(env)
    prompt = [p for p in env.provider.prompts if '"keywords"' in p.split("Reply shape:")[1].split("\n")[0] and "bullets" in p.split("Reply shape:")[1].split("\n")[0]][0]
    allowed = {k.casefold() for k in json.loads(prompt.split(DATA_MARK)[1].split("\n")[0])["keywords_allowed"]}
    placeable = {r["keyword"].casefold() for r in c["keywordMap"]["candidates"]}
    assert allowed and allowed <= placeable  # the writer was offered researched candidates only
    assert {k.casefold() for k in c["sections"]["keywords"]} <= allowed  # and nothing else is in the keyword section
    assert all(k["keyword"].casefold() not in {x.casefold() for x in c["sections"]["keywords"]} for k in c["keywordMap"]["notUsed"])  # a "not used" keyword is never in the section


def test_n05l_a_flipkart_listing_is_its_own_row_and_is_independent_of_the_amazon_pack(env):
    amazon = card_for(env)
    flip = env.post("full-listing", {**body("fk"), "marketplace": FLIPKART}).json()["card"]
    assert flip["marketplace"] == "FLIPKART" and flip["generationId"] != amazon["generationId"] and flip["sections"]["backend_terms"] is None and amazon["sections"]["backend_terms"]
    rows = {r[0]: r for r in env.q("SELECT id::text, marketplace, request_key, output_structured FROM cmo_generation WHERE output_type = 'LISTING_COPY'")}
    assert {rows[amazon["generationId"]][1], rows[flip["generationId"]][1]} == {"AMAZON", "FLIPKART"} and rows[amazon["generationId"]][2] != rows[flip["generationId"]][2]
    before = rows[flip["generationId"]][3]
    r = env.client().post(f"/api/v1/cmo/listing/{amazon['generationId']}/edit", json={"message": "Change bullet 2 to: Holds 1 litre of water"}, headers=env.headers)
    assert r.status_code == 200
    after = env.q("SELECT output_structured FROM cmo_generation WHERE id = :g", g=flip["generationId"])[0][0]
    assert after == before  # editing the Amazon listing did not touch the Flipkart one
    assert env.client().get(f"/api/v1/cmo/listing/{flip['generationId']}", headers=env.headers).json()["sections"]["bullets"] == flip["sections"]["bullets"]


def test_n14g_the_audit_never_changes_the_m3_or_m5_rows(env):
    c = card_for(env)
    tables = ("cmo_title_analysis", "cmo_buyer_question_set", "cmo_readiness_assessment")
    before = {t: env.n(t) for t in tables}
    for _ in range(2):  # opening the card again re-runs the audit (read-only on those tables)
        assert env.client().get(f"/api/v1/cmo/listing/{c['generationId']}", headers=env.headers).status_code == 200
    assert {t: env.n(t) for t in tables} == before
    assert env.n("cmo_listing_audit") == 1  # and the audit itself is saved once per version


# ---------------------------------------------------------------- third pass: N-05g (WEAK fixture), N-05l (NEEDS_SELLER_INPUT), N-14g (three measures side by side)
def test_n05g_a_weak_candidate_is_listed_as_not_used_with_the_reason_and_never_reaches_the_text(env, monkeypatch):
    from backend.services import cmo_listing  # noqa: PLC0415

    real = cmo_listing.keyword_analysis

    def with_weak(*a, **k):
        kw, ctx = real(*a, **k)
        weak = {"keyword": "travel mug", "intent": "DESCRIBE", "placement": ["KEYWORDS"], "relevance": "MEDIUM", "relevanceBasis": "1 of 2 words are backed by your confirmed facts or product name",
                "confidence": "WEAK", "evidence": [{"kind": "NICHE_TERM", "ref": "x", "text": "travel mug"}], "competitorOccurrence": {"status": "NOT_ASSESSED"}, "searchVolume": "NOT_ASSESSED",
                "buyerDemand": "NOT_ASSESSED", "marketplaceRank": "NOT_ASSESSED", "recommended": True}
        return {**kw, "candidates": [*kw["candidates"], weak]}, ctx

    monkeypatch.setattr(cmo_listing, "keyword_analysis", with_weak)
    c = card_for(env)
    assert {"keyword": "travel mug", "reason": "Not used: evidence is weak."} in c["keywordMap"]["notUsed"]
    s = c["sections"]
    assert "travel mug" not in " ".join([s["title"], *s["bullets"], s["description"], *s["keywords"], *(s["backend_terms"] or [])]).casefold()  # absent from every section and the backend terms
    assert all(r["keyword"] != "travel mug" for r in c["keywordMap"]["candidates"] if r.get("placed"))
    assert "travel mug" not in "".join(p for p in env.provider.prompts if "keywords_allowed" in p).casefold()  # the writer was never offered it


def test_n05l_a_flipkart_card_says_its_structured_fields_need_seller_input_and_fills_none_and_amazon_has_none(env):
    amazon = card_for(env)
    flip = env.post("full-listing", {**body("fk"), "marketplace": FLIPKART}).json()["card"]
    sf = flip["structuredFields"]
    assert sf["state"] == "NEEDS_SELLER_INPUT" and sf["fields"] == [] and "not verified" in sf["reason"]  # nothing is shown as filled or enforced
    assert amazon["structuredFields"] is None


def test_n14g_the_card_shows_three_separate_measures_each_from_its_own_source_and_not_assessed_is_never_zero(env):
    from slim_cmo.service import readiness  # noqa: PLC0415
    from slim_cmo.service.models import Actor  # noqa: PLC0415

    c = card_for(env)
    m = {x["id"]: x for x in c["measures"]}
    assert [x["id"] for x in c["measures"]] == ["TITLE_CHECK", "LISTING_AUDIT", "READINESS"]
    assert m["LISTING_AUDIT"]["status"] == "ASSESSED" and m["LISTING_AUDIT"]["value"]
    assert m["READINESS"]["status"] == "NOT_ASSESSED" and m["READINESS"]["value"] is None  # no saved readiness check: never shown as a number
    assert m["TITLE_CHECK"]["status"] in ("ASSESSED", "NOT_ASSESSED") and (m["TITLE_CHECK"]["value"] is None) == (m["TITLE_CHECK"]["status"] == "NOT_ASSESSED")
    sku = SKU
    saved = {"method": "m5", "marketplace": "AMAZON", "verdict": "NEEDS_WORK", "verdictText": "Needs work before you list", "score": 61}
    readiness.save_result(Actor(env.tenant, env.user_id), "readiness", sku, "m5", saved, "ready-1")
    before = env.n("cmo_readiness_assessment")
    again = env.client().get(f"/api/v1/cmo/listing/{c['generationId']}", headers=env.headers).json()
    r = {x["id"]: x for x in again["measures"]}["READINESS"]
    assert r["status"] == "ASSESSED" and "61" in r["value"] and "Needs work" in r["value"] and r["asOf"]  # the saved M5 result, exactly as saved
    assert env.n("cmo_readiness_assessment") == before  # reading it did not write or rescore


def test_n16c_a_title_over_a_verified_limit_is_refused_naming_the_limit_and_its_length_and_nothing_is_cut_or_charged(env):
    from sqlalchemy import text  # noqa: PLC0415

    from backend.services import cmo_listing  # noqa: PLC0415
    from tests.integration.test_cmo_m6_integration import TITLE  # noqa: PLC0415

    ru_env(env, ListingProvider())
    first = env.post("full-listing", body("before")).json()
    assert first["status"] == "COMPLETE"  # while no verified row exists the unverified draft basis runs
    packs, events = env.n("cmo_generation"), env.n("metered_event", "agent_code = 'CMO'")
    with env.engine.begin() as conn:
        conn.execute(text("INSERT INTO format_constraint (marketplace, title_max_chars, title_option_count, bullet_count, bullet_max_chars, description_type, description_max_chars, keywords_max_count, "
                          "keywords_max_chars, backend_terms_max_bytes, count_rule, source_url, verified_at, version, row_kind) VALUES ('AMAZON', 20, 3, 3, 200, 'plain', 900, 10, 40, 249, "
                          "'UTF16_CODE_UNITS', 'https://example.invalid/test-fixture', now(), 1, 'TEST_FIXTURE')"))
    r = env.post("full-listing", body("after"))
    assert r.status_code == 409, r.text
    detail = json.dumps(r.json())
    assert "TITLE_OVER_LIMIT" in detail and "at most 20 characters" in detail and f"is {len(TITLE)} characters" in detail and "shorter title" in detail and "not changed or cut" in detail
    assert (env.n("cmo_generation"), env.n("metered_event", "agent_code = 'CMO'")) == (packs, events)  # the earlier pack stays; nothing new was generated or charged
    said = cmo_listing.chat_refusal(env.tenant, {"sku": SKU, "marketplace": "AMAZON", "seller_title": TITLE})  # the CEO says the same, before any plan card
    assert said and "at most 20 characters" in said and f"is {len(TITLE)} characters" in said
    with env.engine.begin() as conn:
        conn.execute(text("UPDATE format_constraint SET title_max_chars = 200 WHERE row_kind = 'TEST_FIXTURE'"))
    assert cmo_listing.chat_refusal(env.tenant, {"sku": SKU, "marketplace": "AMAZON", "seller_title": TITLE}) is None  # a title within the verified limit is planned normally
