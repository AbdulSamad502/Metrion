"""CMO 3.0 M3 against a real Postgres and through the real CEO chat (N-03 a-d, R-04, R-05, R-06): the title analyzer is free, saved once per request key, tenant-isolated, never
changes the title options or their order, marks unconfirmed claims as hard failures, and says NOT_ASSESSED when no verified marketplace rule exists."""

from __future__ import annotations

import os
import re

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.pool import NullPool

from slim_cmo.service.models import Actor
from slim_cmo.service.title_analysis import TitleAnalysisService
from slim_cmo.types import ConstraintRowKind

from tests.integration.test_ceo_cmo_delegation import approve, ask_for_titles, chat, cmo_counts, say  # noqa: F401
from tests.integration.test_cmo_api import AMAZON, TITLES, _erase_cmo_rows, ctx_engine, env, fake_clerk  # noqa: F401

pytestmark = pytest.mark.skipif(not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL"), reason="needs a live Postgres")


def title_set(env, key="m3t"):
    r = env.post("title-sets", {"request_key": key, "sku": "aquakeep", "product_name": "AquaKeep Steel Bottle", "brand": "AquaKeep", "marketplaces": [AMAZON],
                                "attributes": [{"name": "Material", "value": "steel"}]})
    assert r.status_code == 200, r.text
    return r.json()["artefacts"][0]


def analyse(env, generation_id, key="a1", headers=None):
    return env.post("title-analysis", {"request_key": key, "generation_id": generation_id}, headers=headers)


def by_rank(body):
    return {o["rank"]: o for o in body["options"]}


def test_each_option_is_compared_on_every_dimension_with_reasons_and_no_score(env):
    ts = title_set(env)
    r = analyse(env, ts["id"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["unitsBilled"] == 0 and body["reused"] is False and len(body["options"]) == 3
    for o in body["options"]:
        assert set(o["dimensions"]) == {"marketplaceRules", "factAccuracy", "keywordRelevance", "buyerIntent", "positioning", "readability"}
        assert all(d["detail"] for d in o["dimensions"].values())
        assert set(o["scores"]["criteria"]) == {"keywordRelevance", "factAccuracy", "readability", "buyerIntent", "structure"}
        assert o["scores"]["overall"]["status"] in ("ASSESSED", "NOT_ASSESSED")
    assert any("not an Amazon SEO ranking" in line for line in body["limits"]) and body["scoring"]["criteria"] == {"keywordRelevance": 25, "factAccuracy": 25, "readability": 20, "buyerIntent": 15, "structure": 15}


def test_an_option_that_claims_something_the_seller_never_confirmed_is_a_hard_failure_and_not_recommended(env):
    ts = title_set(env)
    body = analyse(env, ts["id"]).json()
    insulated = next(o for o in body["options"] if "Insulated" in o["text"])
    assert insulated["hardFailures"] and "insulated" in insulated["hardFailures"][0].lower() and insulated["eligible"] is False
    assert insulated["scores"]["criteria"]["factAccuracy"]["earned"] == 0 and insulated["scores"]["overall"].get("band") == "NOT_USABLE"
    assert body["recommendation"].get("optionId") != insulated["optionId"]


def test_the_test_rule_is_labelled_a_placeholder_and_a_missing_verified_rule_is_not_assessed(env):
    ts = title_set(env)
    body = analyse(env, ts["id"]).json()
    rules = by_rank(body)[1]["dimensions"]["marketplaceRules"]
    assert rules["ruleKind"] == "TEST_FIXTURE" and "NOT a verified marketplace rule" in rules["detail"]
    svc = TitleAnalysisService(env.runtime.store, clock=env.runtime.clock, accepted_row_kinds=frozenset({ConstraintRowKind.VERIFIED}))  # production reads VERIFIED rows only
    prod = svc.run(Actor(env.tenant, env.user_id), __import__("uuid").UUID(ts["id"]), "prod-1")
    for o in prod["options"]:
        r = o["dimensions"]["marketplaceRules"]
        assert r["status"] == "NOT_ASSESSED" and "no verified, current rule" in r["detail"] and not any("rule" in h for h in o["hardFailures"])
    assert any("marketplace rules" in n for n in prod["notes"])


def test_the_score_is_saved_exactly_as_shown_and_compliance_never_changes_it(env):
    ts = title_set(env)
    body = analyse(env, ts["id"]).json()
    stored = env.q("SELECT result FROM cmo_title_analysis")[0][0]
    assert [o["scores"] for o in stored["options"]] == [o["scores"] for o in body["options"]]
    for o in body["options"]:
        ov = o["scores"]["overall"]
        if ov["status"] == "ASSESSED":
            assert ov["score"] == sum(c["earned"] for c in o["scores"]["criteria"].values() if c["status"] == "ASSESSED") * 100 // max(ov["assessablePoints"], 1) or ov["assessablePoints"] != 100
            assert 0 <= ov["score"] <= 100


def test_the_same_key_returns_the_saved_analysis_and_nothing_is_billed_or_reserved(env):
    ts = title_set(env)
    events = len(env.events())
    first = analyse(env, ts["id"]).json()
    again = analyse(env, ts["id"]).json()
    assert again["reused"] is True and again["analysisId"] == first["analysisId"]
    assert env.n("cmo_title_analysis") == 1 and env.n("agent_run", "trigger_ref = 'cmo.analyze_titles'") == 1
    assert len(env.events()) == events and env.reservations() == []


def test_the_title_options_and_their_order_are_unchanged_and_choosing_still_works(env):
    ts = title_set(env)
    before = env.q("SELECT rank, title_text FROM cmo_title_option ORDER BY rank")
    analyse(env, ts["id"])
    assert env.q("SELECT rank, title_text FROM cmo_title_option ORDER BY rank") == before
    ok = env.post("title-approvals", {"generation_id": ts["id"], "option_id": ts["options"][0]["id"]})
    assert ok.status_code == 200 and ok.json()["unitsBilled"] == 0


def test_another_tenants_title_set_is_a_404_and_nothing_is_saved_for_anyone(env):
    ts = title_set(env)
    other, headers = env.other_tenant()
    r = analyse(env, ts["id"], headers=headers)
    assert r.status_code == 404 and env.n("cmo_title_analysis", tenant=other) == 0 and env.n("cmo_title_analysis") == 0


def test_the_application_role_cannot_change_or_delete_a_saved_analysis(env):
    ts = title_set(env)
    analyse(env, ts["id"])
    app = create_engine(os.environ["DATABASE_URL_APP"], poolclass=NullPool)
    try:
        for sql in ("UPDATE cmo_title_analysis SET method = 'x'", "DELETE FROM cmo_title_analysis"):
            with pytest.raises(ProgrammingError):
                with app.begin() as conn:
                    conn.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": str(env.tenant)})
                    conn.execute(text(sql))
    finally:
        app.dispose()


def test_a_client_supplied_tenant_is_refused(env):
    ts = title_set(env)
    r = env.post("title-analysis", {"request_key": "x", "generation_id": ts["id"], "tenant_id": "00000000-0000-0000-0000-000000000001"})
    assert r.status_code == 422 and env.n("cmo_title_analysis") == 0


# ---------------------------------------------------------------- through the real CEO chat
def test_the_seller_compares_the_titles_in_chat_for_free_and_can_still_choose_one(chat):
    c, e = chat, chat.env
    inv, planned = ask_for_titles(c)
    body = approve(c, inv, planned["plan"]).json()
    assert "compare these titles" in body["answer"]
    before = cmo_counts(c)
    r = say(c, inv, "compare these titles")
    assert r["status"] == "DELIVERED", r
    a = r["answer"]
    assert "Title quality scores" in a and "Comparison of all options" in a and "marketplace compliance (separate):" in a and "Recommendation" in a
    assert re.search(r"quality score \d{1,3}/100 \([a-z ]+\) \[\d{1,3} of 100 points assessable\]", a) and "keywords " in a and "confirmed facts " in a and "readability " in a and "buyer intent " in a and "structure " in a
    assert "internal listing-quality assessment" in a and "not an Amazon SEO ranking" in a
    assert "HARD FAIL, never recommended whatever its score" in a and "insulated" in a.lower()  # the fake model wrote an insulated option the seller never confirmed
    assert not re.search(r"ranked #?\d|sales will|will convert|search volume of \d", a, re.IGNORECASE)  # no ranking, conversion or sales claim is ever made
    after = cmo_counts(c)
    assert after["cmo_events"] == before["cmo_events"] and after["model_calls"] == before["model_calls"] and e.n("cmo_title_analysis") == 1
    pick = say(c, inv, "use option 1")
    assert pick["status"] == "CLARIFIED" and pick["choices"]["slot"] == "title_pick"
    assert say(c, inv, "1")["status"] == "DELIVERED" and e.n("cmo_title_approval") == 1


def test_asking_to_compare_with_no_titles_says_so_and_saves_nothing(chat):
    c = chat
    inv = c.client.post("/api/v1/ceo/investigations", json={"title": "x"}, headers=c.env.headers).json()["investigationId"]
    r = say(c, inv, "compare my titles")
    assert "no title options" in r["answer"].lower() and c.env.n("cmo_title_analysis") == 0
