"""CMO 3.0 M6, second traceability pass (Section F rows N-05g, N-05j, N-05l, N-14g): end-to-end checks through the real API on a real Postgres that the earlier unit-level evidence did not give. Where a row's
remaining gap is an unimplemented feature (NEEDS_SELLER_INPUT, the side-by-side M3/M5 card), that is stated in CMO_M6_TRACEABILITY.md and these tests do not pretend otherwise."""

from __future__ import annotations

import json
import os

import pytest

from tests.integration.test_cmo_api import FLIPKART, _erase_cmo_rows, ctx_engine, env, fake_clerk  # noqa: F401
from tests.integration.test_cmo_m6_integration import DATA_MARK, ListingProvider, body, ru_env

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
