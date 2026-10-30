"""CMO 3.0 M2 against a real Postgres and through the real CEO chat (N-02, N-02b, R-04, R-05): keyword intelligence is zero units, saved once per request key, tenant-isolated,
built only from the seller's confirmed facts, and never states search volume, demand or rank."""

from __future__ import annotations

import os
import uuid

import pytest

from tests.integration.test_ceo_cmo_delegation import approve, ask_for_titles, chat, cmo_counts, say  # noqa: F401
from tests.integration.test_cmo_api import AMAZON, _erase_cmo_rows, ctx_engine, env, fake_clerk  # noqa: F401

pytestmark = pytest.mark.skipif(not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL"), reason="needs a live Postgres")

NAME = "AquaNest 1 Litre Stainless Steel Water Bottle"
SKU = "aquanest-1-litre-stainless-steel-water-bottle"


def seed_facts(env, key="k1"):
    r = env.post("title-sets", {"request_key": key, "sku": SKU, "product_name": NAME, "brand": "AquaNest", "marketplaces": [AMAZON],
                                "attributes": [{"name": "Size", "value": "1 litre"}, {"name": "Material", "value": "stainless steel"}, {"name": "Color", "value": "silver"}]})
    assert r.status_code == 200, r.text


def analyse(env, key="kw1", headers=None, **extra):
    return env.post("keyword-intelligence", {"request_key": key, "sku": SKU, "marketplace": AMAZON, **extra}, headers=headers)


def test_the_analysis_is_built_from_confirmed_facts_costs_nothing_and_assesses_no_demand(env):
    seed_facts(env)
    events = len(env.events())
    r = analyse(env)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "COMPLETE" and body["unitsBilled"] == 0 and body["reused"] is False
    kws = {c["keyword"]: c for c in body["candidates"]}
    assert {"stainless steel water bottle", "water bottle", "1 litre water bottle", "silver water bottle", "aquanest water bottle"} <= set(kws)
    assert all(c["searchVolume"] == c["buyerDemand"] == c["marketplaceRank"] == "NOT_ASSESSED" for c in kws.values())
    assert body["evidence"]["competitorListingsUsed"] == 0 and any("No competitor evidence" in line for line in body["limits"])
    assert len(env.events()) == events and env.reservations() == []  # no metered event, no reservation
    assert env.n("agent_run", "trigger_ref = 'cmo.keyword_intelligence'") == 1


def test_the_same_request_key_returns_the_saved_analysis_and_a_new_key_is_a_new_one(env):
    seed_facts(env)
    first = analyse(env).json()
    again = analyse(env).json()
    assert again["reused"] is True and again["analysisId"] == first["analysisId"] and again["agentRunId"] is None
    assert env.n("cmo_keyword_analysis") == 1 and env.n("agent_run", "trigger_ref = 'cmo.keyword_intelligence'") == 1
    assert analyse(env, key="kw2").json()["analysisId"] != first["analysisId"] and env.n("cmo_keyword_analysis") == 2


def test_without_confirmed_facts_it_asks_for_them_and_invents_no_keyword(env):
    r = analyse(env).json()
    assert r["status"] == "NO_FACTS" and r["candidates"] == [] and r["needs"]


def test_a_claim_the_seller_never_confirmed_is_not_offered_even_when_a_note_mentions_nothing(env):
    seed_facts(env)
    body = analyse(env).json()
    assert not any(w in c["keyword"] for c in body["candidates"] for w in ("insulated", "leakproof", "dishwasher"))


def test_another_tenant_gets_its_own_analysis_and_never_sees_this_ones(env):
    seed_facts(env)
    mine = analyse(env).json()
    other, headers = env.other_tenant()
    theirs = analyse(env, headers=headers).json()  # same key, same sku, a different tenant
    assert theirs["status"] == "NO_FACTS" and theirs["analysisId"] != mine["analysisId"] and theirs["candidates"] == []
    assert env.n("cmo_keyword_analysis", tenant=other) == 1 and env.n("cmo_keyword_analysis") == 1


def test_a_competitor_insight_that_is_not_the_sellers_is_a_404_and_writes_nothing(env):
    seed_facts(env)
    r = analyse(env, ci_insight_ids=[str(uuid.uuid4())])
    assert r.status_code == 404 and env.n("cmo_keyword_analysis") == 0


def test_the_application_role_cannot_change_or_delete_a_saved_analysis(env):
    from sqlalchemy import create_engine, text
    from sqlalchemy.exc import ProgrammingError
    from sqlalchemy.pool import NullPool

    seed_facts(env)
    analyse(env)
    app = create_engine(os.environ["DATABASE_URL_APP"], poolclass=NullPool)  # the role the application really runs as (the fixture engines are the table owner)
    try:
        for sql in ("UPDATE cmo_keyword_analysis SET status = 'NO_FACTS'", "DELETE FROM cmo_keyword_analysis"):
            with pytest.raises(ProgrammingError):
                with app.begin() as conn:
                    conn.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": str(env.tenant)})
                    conn.execute(text(sql))
    finally:
        app.dispose()


def test_a_client_supplied_tenant_or_meter_is_refused(env):
    r = env.post("keyword-intelligence", {"request_key": "x", "sku": SKU, "tenant_id": str(uuid.uuid4())})
    assert r.status_code == 422 and env.n("cmo_keyword_analysis") == 0


# ---------------------------------------------------------------- through the real CEO chat
def test_the_seller_asks_in_chat_and_gets_evidence_for_each_keyword_with_no_unit_used(chat):
    c, e = chat, chat.env
    inv, planned = ask_for_titles(c)
    assert approve(c, inv, planned["plan"]).json()["status"] == "DELIVERED"
    before = cmo_counts(c)
    r = say(c, inv, "research keywords for my steel bottle")
    while r["status"] == "CLARIFIED" and r.get("choices"):
        r = say(c, inv, "skip")
    assert r["status"] == "DELIVERED", r
    a = r["answer"]
    assert "Keyword candidates" in a and "steel bottle" in a and "search volume and demand: not assessed" in a
    assert "not Amazon SEO rankings" in a or "not search counts" in a
    after = cmo_counts(c)
    assert after["cmo_events"] == before["cmo_events"] and after["model_calls"] == before["model_calls"]  # no unit, no model
    assert e.n("cmo_keyword_analysis") == 1
    assert e.q("SELECT sku FROM cmo_keyword_analysis")[0][0] == "steel-bottle"


def test_asking_to_write_keywords_still_writes_keywords_not_research(chat):
    c = chat
    inv, _ = ask_for_titles(c)
    r = say(c, inv, "write search keywords for my steel bottle on amazon")
    assert r["choices"]["playbook"] == "cmo.generate_keywords"
