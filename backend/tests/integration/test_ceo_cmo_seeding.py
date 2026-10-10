"""Spec 6.39 (C4): the CMO titles conversation OFFERS the themes the seller's other agents already hold as the category hint: Product Intelligence's keyword themes for
the idea being written about, and the keywords of a tracked competitor's captured listing. Each is labelled "not verified", comes from a stored row (tenant-scoped), is
never filled in by itself, and choosing it passes exactly that text as the hint. No model is called (the classifier is EMPTY)."""

from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest
from sqlalchemy import text

from competitor_intelligence.listing_insight.derive import ListingInsightDraft
from competitor_intelligence.repositories import competitor_listing_insight_repo
from competitor_intelligence.types import Confidence, DerivationMethod, InsightState
from product_intelligence.repositories import product_candidate_repo

from backend.ceo import orchestrator
from tests.integration.ceo_support import ctx_for
from tests.integration.test_ceo_cmo_chat import registry
from tests.integration.test_ceo_state_specialists import NOW, _scope, seed  # noqa: F401  (fixture + constant)
from tests.integration.test_ceo_turn import Grounded, Scripted, runtime, start

pytestmark = [pytest.mark.usefixtures("two_tenants"), pytest.mark.skipif(not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL"), reason="needs a live Postgres")]


def add_candidate(tenant, run_id, title, themes):
    return product_candidate_repo.insert_candidate(
        tenant, run_id=run_id, candidate_title=title, title_length=len(title), title_structure=None, keyword_themes=themes, observed_category=None, category_confidence=None,
        image_url=None, image_source_url=None, demand_signal=None, engagement_signal=None, web_price_signal=None, source_diversity=1, proxy_score=None, proxy_state="UNAVAILABLE",
        proxy_basis={}, score_explanation={}, candidate_marketplaces=["AMAZON"], source_urls=[], capture_status="COMPLETE", confidence="DERIVED",
    )


def add_insight(tenant, snapshot_id, words):
    draft = ListingInsightDraft(
        keyword_themes={w: 1 for w in words}, title_length=20, title_structure={}, feature_categories={}, benefit_term_patterns={}, differentiation_opportunities=[],
        bullet_count=3, image_count=None, confidence=Confidence.DERIVED, derivation_method=DerivationMethod.LOCAL_HEURISTIC, insight_state=InsightState.COMPLETE, degraded_reason=None,
    )
    return competitor_listing_insight_repo.insert_insight(tenant, snapshot_id=snapshot_id, source_url="https://amazon.in/dp/x", fetched_at=datetime.now(timezone.utc), draft=draft)


def to_hint_question(ctx, rt, product, inv=None):
    first = orchestrator.run_turn(ctx, rt, inv or start(ctx, rt), f"write titles for {product}")
    assert first.choices["pending"]["key"] == "cmo.generate_title_sets" and first.choices["pending"]["collected"] == {"product_name": product}
    return first


def test_themes_are_offered_with_their_source_and_a_not_verified_label_never_filled_in(two_tenants, app_user, seed, migrate_engine):  # noqa: F811
    a, _ = two_tenants
    calls: dict = {}
    ctx = ctx_for(a, user_id=app_user)
    rt = runtime(Scripted({}), Grounded(), registry=registry(calls))
    run_id = seed.run(a, "COMPLETE")
    rival = seed.url(a, "Acme Steel")
    snap = seed.snapshot(a, rival, 52000)
    cand = add_candidate(a, run_id, "Steel Water Bottle", {"top_keywords": ["insulated", "leakproof", "bpa free"]})
    ins = add_insight(a, snap, ["vacuum", "double wall"])
    try:
        inv = start(ctx, rt)
        q = to_hint_question(ctx, rt, "Steel Water Bottle", inv)
        labels = {o["label"]: o for o in q.choices["options"] if o["kind"] in ("RECOMMENDED", "ALTERNATIVE")}
        assert set(labels) == {"Use Product Intelligence's themes", "Use Acme Steel's listing keywords", "Skip"}
        pi, ci = labels["Use Product Intelligence's themes"], labels["Use Acme Steel's listing keywords"]
        assert pi["value"] == "insulated, leakproof, bpa free" and "Not verified" in pi["reason"] and "Not verified" in ci["reason"]
        assert "category_hint" not in q.choices["pending"]["collected"] and calls == {}  # offered, never filled in
        nxt = orchestrator.run_turn(ctx, rt, inv, "(chose an option)", clarification=orchestrator.ClarificationReply(q.message_id, pi["key"]))
        assert nxt.choices["pending"]["collected"]["category_hint"] == "insulated, leakproof, bpa free"  # exactly the offered text
    finally:
        with _scope(migrate_engine, a) as c:
            c.execute(text("DELETE FROM competitor_listing_insight WHERE id = :i"), {"i": str(ins)})
            c.execute(text("DELETE FROM product_candidate WHERE id = :i"), {"i": str(cand)})


def test_an_idea_pi_does_not_know_and_no_competitor_insight_means_only_skip_is_offered(two_tenants, app_user, seed):  # noqa: F811
    a, _ = two_tenants
    ctx = ctx_for(a, user_id=app_user)
    rt = runtime(Scripted({}), Grounded(), registry=registry({}))
    q = to_hint_question(ctx, rt, "Unknown Gadget")
    assert [o["label"] for o in q.choices["options"] if o["kind"] in ("RECOMMENDED", "ALTERNATIVE")] == ["Skip"]  # no theme is invented


def test_another_tenants_themes_are_never_offered(two_tenants, app_user, seed, migrate_engine):  # noqa: F811
    a, b = two_tenants
    run_b = seed.run(b, "COMPLETE")
    cand = add_candidate(b, run_b, "Steel Water Bottle", {"top_keywords": ["secret"]})
    try:
        ctx = ctx_for(a, user_id=app_user)
        rt = runtime(Scripted({}), Grounded(), registry=registry({}))
        q = to_hint_question(ctx, rt, "Steel Water Bottle")
        assert all("secret" not in str(o["value"]) for o in q.choices["options"])
    finally:
        with _scope(migrate_engine, b) as c:
            c.execute(text("DELETE FROM product_candidate WHERE id = :i"), {"i": str(cand)})
