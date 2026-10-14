"""Research case, history, pinning and archiving against a real Postgres (docs/specs/ceo-pi-research-flow.md C4, C6; AC3, AC9, AC10)."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from product_intelligence.direct_path import pi_case
from product_intelligence.repositories import pi_research_case_repo, pi_research_history_repo
from product_intelligence.repositories.tenant_context import tenant_scope

pytestmark = pytest.mark.usefixtures("_clean_pi_tables")

BASE = datetime(2026, 10, 1, tzinfo=timezone.utc)


def _brief(tenant: uuid.UUID) -> uuid.UUID:
    bid = uuid.uuid4()
    with tenant_scope(tenant) as conn:
        conn.execute(
            text(
                "INSERT INTO niche_brief (id, tenant_id, status, category_text, budget_paise, marketplaces, created_by) "
                "VALUES (:id, :t, 'READY', 'mens watches', 2000000, ARRAY['AMAZON'], :u)"
            ),
            {"id": str(bid), "t": str(tenant), "u": str(uuid.uuid4())},
        )
    return bid


def _run(tenant: uuid.UUID, day: int, status: str = "COMPLETE") -> uuid.UUID:
    rid = uuid.uuid4()
    with tenant_scope(tenant) as conn:
        conn.execute(
            text(
                "INSERT INTO pi_research_run (id, tenant_id, niche_brief_id, depth, trigger, candidate_cap, status, started_at, finished_at, created_at) "
                "VALUES (:id, :t, :b, 'SHALLOW', 'CEO_REQUEST', 30, :s, :at, :at, :at)"
            ),
            {"id": str(rid), "t": str(tenant), "b": str(_brief(tenant)), "s": status, "at": BASE + timedelta(days=day)},
        )
    return rid


def _candidate(tenant: uuid.UUID, run: uuid.UUID, title: str, proxy: str, positive: dict | None = None) -> uuid.UUID:
    cid = uuid.uuid4()
    with tenant_scope(tenant) as conn:
        conn.execute(
            text(
                "INSERT INTO product_candidate (id, tenant_id, run_id, candidate_title, source_diversity, proxy_score, proxy_state, proxy_basis, "
                "score_explanation, source_urls, capture_status, confidence) VALUES (:id, :t, :r, :title, 2, CAST(:p AS numeric), 'COMPUTED', '{}'::jsonb, "
                "'{}'::jsonb, '[]'::jsonb, 'OK', 'DERIVED')"
            ),
            {"id": str(cid), "t": str(tenant), "r": str(run), "title": title, "p": proxy},
        )
        if positive is not None:
            conn.execute(
                text(
                    "INSERT INTO product_review_insight (tenant_id, candidate_id, insight_source_type, positive_themes, complaint_themes, reviews_considered, "
                    "confidence, derivation_method, insight_state, source_url, fetched_at, derived_at) VALUES (:t, :c, 'WEB_EDITORIAL', CAST(:pos AS jsonb), "
                    "'{}'::jsonb, 3, 'DERIVED', 'LOCAL_MODEL', 'COMPLETE', 'https://example.test/a', now(), now())"
                ),
                {"t": str(tenant), "c": str(cid), "pos": json.dumps(positive)},
            )
    return cid


def _visible_ids(tenant: uuid.UUID) -> list[str]:
    return [r["runId"] for r in pi_case.list_history(tenant)]


def test_history_keeps_ten_unpinned_archives_the_oldest_and_never_touches_pinned(two_tenants) -> None:
    t, other = two_tenants
    runs = [_run(t, d) for d in range(12)]  # day 0 oldest .. day 11 newest
    other_runs = [_run(other, d) for d in range(12)]
    assert pi_research_history_repo.set_pinned(t, runs[0], pinned=True, now=BASE)  # the oldest is pinned: it must survive
    archived = pi_research_history_repo.archive_over_limit(t, limit=10, now=BASE + timedelta(days=30))
    assert archived == 1  # 11 unpinned (days 1..11): only day 1 is beyond the newest 10
    visible = set(_visible_ids(t))
    assert str(runs[0]) in visible and str(runs[1]) not in visible
    assert len([r for r in runs if str(r) in visible]) == 11  # 10 unpinned + 1 pinned
    assert pi_research_history_repo.archive_over_limit(t, limit=10, now=BASE) == 0  # idempotent
    assert len(_visible_ids(other)) == 12  # another tenant is untouched
    assert pi_research_history_repo.get_visible_run(other, other_runs[0]) is not None


def test_unpin_reapplies_the_limit_and_pinned_are_unlimited(two_tenants) -> None:
    t, _ = two_tenants
    runs = [_run(t, d) for d in range(11)]
    for r in runs[:3]:
        assert pi_research_history_repo.set_pinned(t, r, pinned=True, now=BASE)
    assert pi_research_history_repo.archive_over_limit(t, limit=5, now=BASE) == 3  # 8 unpinned -> 5 kept
    assert len(_visible_ids(t)) == 8
    assert pi_research_history_repo.set_pinned(t, runs[0], pinned=False, now=BASE)
    assert pi_research_history_repo.archive_over_limit(t, limit=5, now=BASE) == 1  # the just-unpinned, oldest one is now over the limit
    assert str(runs[0]) not in _visible_ids(t)


def test_pin_is_idempotent_and_refused_for_other_tenants_archived_and_unfinished_runs(two_tenants) -> None:
    t, other = two_tenants
    mine, running = _run(t, 1), _run(t, 2, status="RUNNING")
    assert pi_research_history_repo.set_pinned(t, mine, pinned=True, now=BASE)
    assert pi_research_history_repo.set_pinned(t, mine, pinned=True, now=BASE + timedelta(days=1))
    assert pi_research_history_repo.get_visible_run(t, mine)["pinned_at"] == BASE  # first pin time kept
    assert not pi_research_history_repo.set_pinned(other, mine, pinned=True, now=BASE)  # another tenant: no effect, no leak
    assert not pi_research_history_repo.set_pinned(t, running, pinned=True, now=BASE)
    assert pi_research_history_repo.get_visible_run(other, mine) is None


def test_a_pinned_report_cannot_be_archived_even_by_a_direct_update(app_engine, two_tenants) -> None:
    t, _ = two_tenants
    r = _run(t, 1)
    pi_research_history_repo.set_pinned(t, r, pinned=True, now=BASE)
    with pytest.raises(Exception, match="pinned_never_archived"):
        with tenant_scope(t) as conn:
            conn.execute(text("UPDATE pi_research_run SET archived_at = now() WHERE id = :id"), {"id": str(r)})


def test_case_selects_top_five_then_final_order_and_exposes_only_five(two_tenants) -> None:
    t, other = two_tenants
    run = _run(t, 1)
    titles = []
    for i in range(8):
        titles.append(_candidate(t, run, f"Watch {i}", f"{10 + i * 10}.00", positive={"strap": 4} if i == 2 else None))
    ids = pi_case.select_top5(t, run)
    assert len(ids) == 5 and ids == pi_case.select_top5(t, run)  # deterministic and repeatable
    out = pi_case.finalize_case(t, run, now=BASE + timedelta(days=2))
    assert len(out["top5"]) == 5
    case = pi_case.render_case(t, run)
    assert case["caseSaved"] is True and len(case["products"]) == 5  # never the 8 discovered
    assert [p["rank"] for p in case["products"]] == [1, 2, 3, 4, 5]
    assert case["overall"]["candidate_id"] == case["products"][0]["recommendation"]["candidate_id"]
    fields = {u["field"] for u in case["unavailable"]}
    assert {"verified_buyer_reviews", "demand_signal"} <= fields
    assert all("no supplier lead" in " ".join(p["recommendation"]["gaps"]) for p in case["products"])  # no leads were inserted: named, not invented
    assert pi_case.list_history(t)[0]["topProducts"]  # the history rail names the top products
    with pytest.raises(pi_case.CaseNotAvailable):
        pi_case.render_case(other, run)  # another tenant: indistinguishable from "does not exist"


def test_cfo_references_are_attached_by_reference_only_and_tenant_scoped(two_tenants) -> None:
    t, other = two_tenants
    run = _run(t, 1)
    _candidate(t, run, "Watch A", "50.00")
    pi_case.select_top5(t, run)
    ref = {"candidate_id": str(uuid.uuid4()), "kind": "ENGINE", "ref": str(uuid.uuid4()), "leg_key": "cfo.landed_cost", "status": "COMPLETE"}
    assert pi_research_case_repo.attach_cfo_results(t, run, [ref])
    assert not pi_research_case_repo.attach_cfo_results(other, run, [ref])
    assert pi_case.render_case(t, run)["cfoRefs"] == [ref]


def test_an_older_run_with_no_case_is_assembled_on_the_fly_and_flagged(two_tenants) -> None:
    t, _ = two_tenants
    run = _run(t, 1)
    _candidate(t, run, "Watch A", "50.00")
    case = pi_case.render_case(t, run)
    assert case["caseSaved"] is False and len(case["products"]) == 1
