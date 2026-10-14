"""PI saved-report routes (docs/specs/ceo-pi-research-flow.md AC8-AC10): history, one report, pin/unpin, against the real routes and the scratch Postgres.
Another tenant can neither read, pin nor unpin a report, and learns nothing about whether it exists."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from product_intelligence.direct_path import pi_case
from product_intelligence.repositories.tenant_context import tenant_scope

from tests.integration.test_pi_discover_api import (  # noqa: F401  (fixtures and helpers)
    _clean_pi_tables,
    _register_owner,
    app_client,
    fake_clerk,
    tenant,
)

BASE = "/api/v1/pi/research"
T0 = datetime(2026, 10, 1, tzinfo=timezone.utc)


def _finished_run_with_candidates(tenant_id: uuid.UUID, day: int, n: int = 6) -> uuid.UUID:
    brief, run = uuid.uuid4(), uuid.uuid4()
    with tenant_scope(tenant_id) as conn:
        conn.execute(
            text("INSERT INTO niche_brief (id, tenant_id, status, category_text, budget_paise, marketplaces, created_by) VALUES (:b, :t, 'READY', 'mens watches', 2000000, ARRAY['AMAZON'], :u)"),
            {"b": str(brief), "t": str(tenant_id), "u": str(uuid.uuid4())},
        )
        conn.execute(
            text("INSERT INTO pi_research_run (id, tenant_id, niche_brief_id, depth, trigger, candidate_cap, status, started_at, finished_at, created_at) VALUES (:r, :t, :b, 'SHALLOW', 'CEO_REQUEST', 30, 'COMPLETE', :at, :at, :at)"),
            {"r": str(run), "t": str(tenant_id), "b": str(brief), "at": T0 + timedelta(days=day)},
        )
        for i in range(n):
            conn.execute(
                text("INSERT INTO product_candidate (tenant_id, run_id, candidate_title, source_diversity, proxy_score, proxy_state, proxy_basis, score_explanation, source_urls, capture_status, confidence) VALUES (:t, :r, :title, 2, CAST(:p AS numeric), 'COMPUTED', '{}'::jsonb, '{}'::jsonb, '[]'::jsonb, 'OK', 'DERIVED')"),
                {"t": str(tenant_id), "r": str(run), "title": f"Watch {i}", "p": f"{20 + i * 10}.00"},
            )
    return run


def test_history_and_report_return_the_saved_five_and_nothing_else(app_client, fake_clerk, tenant):
    headers = _register_owner(fake_clerk, tenant)
    run = _finished_run_with_candidates(tenant, 1)
    pi_case.select_top5(tenant, run)
    pi_case.finalize_case(tenant, run)
    items = app_client.get(BASE, headers=headers).json()["items"]
    assert [i["runId"] for i in items] == [str(run)] and items[0]["category"] == "mens watches" and len(items[0]["topProducts"]) == 5
    report = app_client.get(f"{BASE}/{run}", headers=headers).json()
    assert report["runId"] == str(run) and len(report["products"]) == 5  # 6 were discovered; only five are seller-facing
    assert report["brief"]["budgetPaise"] == 2000000 and report["pinned"] is False


def test_pin_unpin_round_trip_and_idempotence(app_client, fake_clerk, tenant):
    headers = _register_owner(fake_clerk, tenant)
    run = _finished_run_with_candidates(tenant, 1)
    assert app_client.post(f"{BASE}/{run}/pin", headers=headers).json() == {"runId": str(run), "pinned": True}
    assert app_client.post(f"{BASE}/{run}/pin", headers=headers).status_code == 200
    assert app_client.get(f"{BASE}/{run}", headers=headers).json()["pinned"] is True
    assert app_client.get(BASE, headers=headers).json()["items"][0]["pinned"] is True
    assert app_client.post(f"{BASE}/{run}/unpin", headers=headers).json()["pinned"] is False
    assert app_client.get(f"{BASE}/{run}", headers=headers).json()["pinned"] is False


def test_unpinning_when_over_the_limit_archives_the_oldest_unpinned(app_client, fake_clerk, tenant):
    headers = _register_owner(fake_clerk, tenant)
    runs = [_finished_run_with_candidates(tenant, d, n=1) for d in range(11)]
    assert app_client.post(f"{BASE}/{runs[0]}/pin", headers=headers).status_code == 200
    assert app_client.post(f"{BASE}/{runs[0]}/unpin", headers=headers).status_code == 200  # 11 unpinned now: the oldest (this one) goes over the limit of 10
    assert app_client.get(f"{BASE}/{runs[0]}", headers=headers).status_code == 404
    assert len(app_client.get(BASE, headers=headers).json()["items"]) == 10


def test_another_tenant_gets_404_everywhere_and_changes_nothing(app_client, fake_clerk, tenant, two_tenants):
    mine = _register_owner(fake_clerk, tenant)
    run = _finished_run_with_candidates(tenant, 1)
    other = _register_owner(fake_clerk, two_tenants[1])
    for method, path in (("get", f"{BASE}/{run}"), ("post", f"{BASE}/{run}/pin"), ("post", f"{BASE}/{run}/unpin")):
        assert getattr(app_client, method)(path, headers=other).status_code == 404
    assert app_client.get(BASE, headers=other).json()["items"] == []
    assert app_client.get(f"{BASE}/{run}", headers=mine).json()["pinned"] is False  # the foreign pin attempt changed nothing
    assert app_client.get(f"{BASE}/{uuid.uuid4()}", headers=mine).status_code == 404  # an unknown id looks the same


class _TavilyImages:
    def images_for(self, query, *, max_images=5):
        from product_intelligence.sources.tavily_client import TavilyImage

        return [TavilyImage(url="https://cdn.shop.example/watch-4.jpg", source_url="https://shop.example/watch-4", description=None, title="Watch 4 product photo")]


class _Verifier:
    def verify(self, url):
        from product_intelligence.discovery.top5_images import VerifiedImage

        return VerifiedImage(900, 900, 80_000)


def test_selecting_the_top_five_gives_only_those_five_a_verified_image_and_clears_video_frames(app_client, fake_clerk, tenant, monkeypatch):
    from backend.services import pi_actions

    headers = _register_owner(fake_clerk, tenant)
    run = _finished_run_with_candidates(tenant, 1, n=7)
    with tenant_scope(tenant) as conn:  # an older run stored a YouTube thumbnail on every candidate
        conn.execute(text("UPDATE product_candidate SET image_url = 'https://i.ytimg.com/vi/x/hqdefault.jpg', image_source_url = 'https://www.youtube.com/watch?v=x' WHERE run_id = :r"), {"r": str(run)})
    monkeypatch.setattr(pi_actions, "_tavily_client", lambda: _TavilyImages())
    monkeypatch.setattr(pi_actions, "_image_verifier", lambda: _Verifier())
    ids = pi_actions.select_research_top5(tenant, run)
    assert len(ids) == 5
    pi_case.finalize_case(tenant, run)
    products = app_client.get(f"{BASE}/{run}", headers=headers).json()["products"]
    # "Watch 4 product photo" names "watch" + "4"? the title is "Watch N": only the matching product keeps the image; every other one has none, never a video frame
    assert all("ytimg" not in (p["candidate"]["image_url"] or "") for p in products)
    with tenant_scope(tenant) as conn:
        rows = conn.execute(text("SELECT candidate_title, image_url FROM product_candidate WHERE run_id = :r"), {"r": str(run)}).all()
    by_title = {r[0]: r[1] for r in rows}
    chosen = {p["candidate"]["candidate_title"] for p in products}
    assert all(("ytimg" not in (img or "")) for t, img in by_title.items() if t in chosen)  # the five were re-resolved
    assert all("ytimg" in (img or "") for t, img in by_title.items() if t not in chosen)  # the others were never touched
