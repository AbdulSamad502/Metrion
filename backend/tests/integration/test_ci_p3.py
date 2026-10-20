"""P3: CI -> CEO -> CMO listing intelligence (slim-cmo-agent.md section 6.7, CEO-brokered mode).

Over a real Postgres with the REAL registry, CEO and CMO handlers (only the CMO's language model is a deterministic fake): the CEO reads the seller's saved competitor listing insights,
freezes their ids into the plan card, and Slim CMO writes from the seller's own facts with derived market themes as context only. Competitor text and prices never reach a prompt, a
copy or a close rewrite is set aside, an id that is not the seller's is a 404, and no usable insight / no agent.ci means an independent task with a note."""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from backend.auth.permissions import PARTNER_ROLE
from competitor_intelligence.listing_insight.derive import ListingInsightDraft
from competitor_intelligence.repositories import competitor_listing_insight_repo
from competitor_intelligence.types import Confidence, DerivationMethod, InsightState
from tests.integration.test_ceo_cmo_delegation import approve, ask_for_titles, chat, cmo_counts  # noqa: F401
from tests.integration.test_cmo_api import TITLES, _erase_cmo_rows, _login, ctx_engine, env, fake_clerk  # noqa: F401

pytestmark = pytest.mark.skipif(not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL"), reason="needs a live Postgres")

CASPIAN_TITLE = "CASPIAN Stainless Steel Insulated Water Bottle 1 Litre Leakproof Cap Keeps Drinks Cold"
COMP_TITLE = "AquaKeep Steel Bottle AquaKeep Steel Bottle"  # words the seller's own facts support, so only the originality guard (not the fact check) can stop a copy
COMP_BULLETS = ["Double wall vacuum insulation keeps your drink cold for hours outdoors", "Leakproof cap with a carry loop"]
THEMES = ["insulated", "leakproof", "caspian", "vacuum"]


def seed_competitor(e, *, tenant=None, themes=THEMES, title=CASPIAN_TITLE, bullets=COMP_BULLETS, price_paise=32900, age_days=0) -> uuid.UUID:
    """One tracked competitor with a saved listing capture (title, bullets, a price) and its derived listing insight. Returns the insight id."""
    tenant = tenant or e.tenant
    url_id, cap, snap = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    with e.cengine.begin() as conn:
        conn.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": str(tenant)})
        conn.execute(text("INSERT INTO competitor_url (id, tenant_id, marketplace, url, label, status, added_by, created_at) VALUES (:id, :t, 'AMAZON', :u, 'CASPIAN bottle', 'ACTIVE', :by, now())"),
                     {"id": str(url_id), "t": str(tenant), "u": f"https://www.amazon.in/dp/{url_id.hex[:10].upper()}", "by": str(e.user_id)})
        conn.execute(text("INSERT INTO ci_capture_run (id, tenant_id, trigger, requested_by, url_ids, status) VALUES (:id, :t, 'MANUAL', :by, :urls, 'COMPLETE')"),
                     {"id": str(cap), "t": str(tenant), "by": str(e.user_id), "urls": [str(url_id)]})
        conn.execute(text("INSERT INTO competitor_snapshot (id, tenant_id, competitor_url_id, ci_capture_run_id, captured_at, capture_status, listed_price_paise, source_url, confidence, research_session_id, "
                          "title, bullets) VALUES (:id, :t, :u, :cap, now(), 'COMPLETE', :p, 'https://x.example', 'VISION_EXTRACTED', :rs, :title, CAST(:bullets AS jsonb))"),
                     {"id": str(snap), "t": str(tenant), "u": str(url_id), "cap": str(cap), "p": price_paise, "rs": str(uuid.uuid4()), "title": title, "bullets": json.dumps(bullets)})
    draft = ListingInsightDraft(
        keyword_themes={w: 1 for w in themes}, title_length=len(title), title_structure={}, feature_categories={}, benefit_term_patterns={}, differentiation_opportunities=["bpa"],
        bullet_count=len(bullets), image_count=None, confidence=Confidence.DERIVED, derivation_method=DerivationMethod.LOCAL_HEURISTIC, insight_state=InsightState.COMPLETE, degraded_reason=None,
    )
    insight = competitor_listing_insight_repo.insert_insight(tenant, snapshot_id=snap, source_url="https://www.amazon.in/dp/x", fetched_at=datetime.now(timezone.utc), draft=draft)
    if age_days:
        with e.cengine.begin() as conn:
            conn.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": str(tenant)})
            conn.execute(text("UPDATE competitor_listing_insight SET derived_at = :d WHERE id = :i"), {"d": datetime.now(timezone.utc) - timedelta(days=age_days), "i": str(insight)})
    return insight


def _generation(e):
    rows = e.q("SELECT input_mode, ci_inputs_snapshot, output_structured FROM cmo_generation ORDER BY created_at DESC LIMIT 1")
    return rows[0]


def test_brokered_themes_inform_the_writing_and_are_recorded_without_competitor_text_or_prices(chat):
    c, e = chat, chat.env
    insight = seed_competitor(e)
    inv, planned = ask_for_titles(c)
    plan = planned["plan"]
    leg = plan["plan"]["legs"][0]
    assert leg["slots"]["ci_insight_ids"] == [str(insight)]  # frozen into the plan: the seller approves exactly this
    assert "Informed by themes from 1 of your tracked competitors' saved listings" in plan["plan"]["summary_text"]
    assert any("Uses themes from 1 tracked competitor listing" in l for l in plan["plan"]["compact_lines"])
    assert cmo_counts(c)["generations"] == 0  # nothing ran yet
    r = approve(c, inv, plan)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "DELIVERED"
    mode, snapshot, structured = _generation(e)
    assert mode == "CEO_BROKERED_CI" and snapshot["insights"][0]["id"] == str(insight)
    prompt = e.provider.prompts[-1]
    assert "MARKET CONTEXT" in prompt and "insulated" in prompt and "leakproof" in prompt
    assert "caspian" not in prompt.lower().replace("caspian bottle", "") and "CASPIAN Stainless" not in prompt and "vacuum insulation keeps" not in prompt  # no brand, no competitor text
    assert "329" not in prompt and "32900" not in prompt  # competitor prices are never consumed by CMO
    assert "CASPIAN Stainless" not in json.dumps(snapshot) and "329" not in json.dumps(snapshot)
    assert "ci_note" not in structured["provenance"]
    assert [i for i in TITLES if i in r.json()["answer"]] == TITLES  # the seller's own facts decide the text


def test_no_saved_competitor_listing_runs_independently_and_says_so(chat):
    c, e = chat, chat.env
    inv, planned = ask_for_titles(c)
    plan = planned["plan"]
    assert "ci_insight_ids" not in plan["plan"]["legs"][0]["slots"]
    assert "Competitor listing themes were not used: none of your tracked competitors has a saved listing capture yet" in plan["plan"]["summary_text"]
    assert approve(c, inv, plan).status_code == 200
    assert _generation(e)[0] == "INDEPENDENT" and _generation(e)[1] is None
    assert "MARKET CONTEXT" not in e.provider.prompts[-1]


def test_a_stale_capture_is_not_offered(chat):
    c, e = chat, chat.env
    seed_competitor(e, age_days=60)
    inv, planned = ask_for_titles(c)
    assert "ci_insight_ids" not in planned["plan"]["plan"]["legs"][0]["slots"]
    assert "older than 30 days" in planned["plan"]["plan"]["summary_text"]


def test_a_draft_that_copies_a_competitor_is_set_aside_and_rewritten_from_the_sellers_facts(chat):
    c, e = chat, chat.env
    seed_competitor(e, title=COMP_TITLE, bullets=[])
    real = e.provider.complete

    def copycat(*, model: str, prompt: str) -> str:
        if "MARKET CONTEXT" in prompt:  # the informed draft lifts the competitor's title
            return json.dumps({"titles": [COMP_TITLE, COMP_TITLE + " Steel", COMP_TITLE + " Bottle"]})
        return real(model=model, prompt=prompt)

    e.provider.complete = copycat
    inv, planned = ask_for_titles(c)
    r = approve(c, inv, planned["plan"])
    assert r.status_code == 200, r.text
    mode, snapshot, structured = _generation(e)
    assert mode == "INDEPENDENT" and snapshot is None  # CEO_BROKERED_CI is recorded only when the themes were actually used
    assert "COPIES_COMPETITOR_TEXT" in structured["provenance"]["ci_note"]
    assert COMP_TITLE not in r.json()["answer"] and all(t in r.json()["answer"] for t in TITLES)


def test_a_market_claim_in_an_informed_draft_is_set_aside(chat):
    c, e = chat, chat.env
    seed_competitor(e)
    real = e.provider.complete
    e.provider.complete = lambda *, model, prompt: json.dumps({"titles": ["AquaKeep Best Selling Steel Bottle", "AquaKeep #1 Flask", "AquaKeep Top Ranked Bottle"]}) if "MARKET CONTEXT" in prompt else real(model=model, prompt=prompt)
    inv, planned = ask_for_titles(c)
    assert approve(c, inv, planned["plan"]).status_code == 200
    mode, _, structured = _generation(e)
    assert mode == "INDEPENDENT" and "set aside" in structured["provenance"]["ci_note"]  # (the claim rule itself is pinned in the unit tests; here the fact check may stop it first)


def test_an_insight_id_that_is_not_the_sellers_is_a_404_and_nothing_runs(env):
    other, other_headers = env.other_tenant()
    foreign = seed_competitor(env, tenant=other)
    before = env.n("cmo_generation")
    r = env.post("title-sets", {"request_key": "ci-foreign", "sku": "S1", "brand": "AquaKeep", "marketplaces": ["AMAZON"], "ci_insight_ids": [str(foreign)]})
    assert r.status_code == 404 and r.json() == {"detail": "Not found"}
    assert env.provider.calls == 0 and env.n("cmo_generation") == before


def test_a_member_without_agent_ci_runs_independently_even_with_a_valid_id(env):
    mine = seed_competitor(env)
    headers, _ = _login(env.fake_clerk, env.tenant, role=PARTNER_ROLE, permissions={"agent.cmo": True})
    r = env.post("title-sets", {"request_key": "ci-noperm", "sku": "S1", "brand": "AquaKeep", "marketplaces": ["AMAZON"], "ci_insight_ids": [str(mine)]}, headers=headers)
    assert r.status_code == 200, r.text
    assert _generation(env)[0] == "INDEPENDENT" and "MARKET CONTEXT" not in env.provider.prompts[-1]


def test_the_direct_route_with_the_owner_uses_the_themes(env):
    mine = seed_competitor(env)
    r = env.post("title-sets", {"request_key": "ci-owner", "sku": "S1", "brand": "AquaKeep", "marketplaces": ["AMAZON"], "ci_insight_ids": [str(mine)]})
    assert r.status_code == 200, r.text
    assert _generation(env)[0] == "CEO_BROKERED_CI"
