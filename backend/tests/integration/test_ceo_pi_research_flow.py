"""CEO -> PI -> CEO research flow, end to end over the real app and a real Postgres (docs/specs/ceo-pi-research-flow.md AC1-AC7).

Real: authentication chain (Clerk faked), RLS, the orchestrator, the input session, the stored plan and its hash, the approve endpoint, the choke point, PI's own case
assembly (pre-rank, top-five images, final scores, recommendation) and `pi.report`. Faked, as in the other approval tests: the model handles (the classifier is never
asked: explicit rules route the request) and the two PI handlers that would reach the internet (`pi.discover` writes a saved run with seven candidates;
`pi.supplier_lookup` writes leads), plus the image search and image host. Nothing here proves live Tavily/YouTube behaviour: that needs real keys (spec section 10)."""

from __future__ import annotations

import dataclasses
import os
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import text

from backend.api.v1 import ceo as ceo_api
from backend.ceo.registry import ActionRegistry, get_registry
from backend.repositories import investigation_repo as repo
from backend.services import pi_actions
from backend.tenant_context import tenant_scope
from product_intelligence.repositories import niche_brief_repo, supplier_lead_repo
from tests.integration.test_ceo_api import clerk  # noqa: F401  (fixture)
from tests.integration.test_ceo_approval_workflow import Env, approve, env, rows, start, turn  # noqa: F401  (fixture + helpers)

pytestmark = pytest.mark.skipif(not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL"), reason="needs a live Postgres")

ASK = "Find me trending products under ₹20,000 on Amazon"
NOW = datetime(2026, 10, 12, 9, 0, tzinfo=timezone.utc)
TITLES = [f"Brand{i} Smart Watch Model{i}" for i in range(7)]


class _Tavily:
    def images_for(self, query, *, max_images=5):
        from product_intelligence.sources.tavily_client import TavilyImage

        title = query.replace(" product photo", "")
        return [TavilyImage(url=f"https://cdn.shop.example/{title.split()[0]}.jpg", source_url="https://shop.example/p", description=None, title=f"{title} official photo")]


class _Verifier:
    def verify(self, url):
        from product_intelligence.discovery.top5_images import VerifiedImage

        return VerifiedImage(900, 900, 90_000)


@dataclasses.dataclass
class Pi:
    calls: dict
    run_id: uuid.UUID | None = None


def _pi_registry(e: Env, pi: Pi, *, lookup_fails: bool = False) -> ActionRegistry:
    real = get_registry()

    def discover(slots, ctx, leg):
        pi.calls.setdefault("pi.discover", []).append(slots.model_dump(mode="json"))
        run = uuid.uuid4()
        pi.run_id = run
        with tenant_scope(ctx.tenant_id) as conn:
            conn.execute(
                text("INSERT INTO pi_research_run (id, tenant_id, niche_brief_id, depth, trigger, candidate_cap, status, started_at, finished_at, created_at) "
                     "VALUES (:r, :t, :b, 'SHALLOW', 'CEO_REQUEST', 30, 'COMPLETE', :n, :n, :n)"),
                {"r": str(run), "t": str(ctx.tenant_id), "b": str(slots.niche_brief_id), "n": NOW},
            )
            for i, title in enumerate(TITLES):
                conn.execute(
                    text("INSERT INTO product_candidate (tenant_id, run_id, candidate_title, source_diversity, proxy_score, proxy_state, proxy_basis, score_explanation, source_urls, "
                         "capture_status, confidence, image_url, image_source_url) VALUES (:t, :r, :title, 2, CAST(:p AS numeric), 'COMPUTED', '{}'::jsonb, '{}'::jsonb, '[]'::jsonb, "
                         "'OK', 'DERIVED', 'https://i.ytimg.com/vi/x/hq.jpg', 'https://www.youtube.com/watch?v=x')"),
                    {"t": str(ctx.tenant_id), "r": str(run), "title": title, "p": f"{20 + i * 10}.00"},
                )
        return {"runId": str(run), "agentRunId": str(uuid.uuid4()), "status": "COMPLETE", "candidateIds": [], "shortlistedCandidateIds": [], "partialReason": None, "failedReason": None}

    def lookup(slots, ctx, leg):
        pi.calls.setdefault("pi.supplier_lookup", []).append(slots.model_dump(mode="json"))
        if lookup_fails:
            raise RuntimeError("the provider is down")
        for cid in slots.candidate_ids:
            supplier_lead_repo.insert_lead(ctx.tenant_id, run_id=slots.run_id, candidate_id=cid, supplier_name="Siddhi Instruments", source="GOOGLE_PLACES",
                                           contact={"phone": "+91 98251 00000", "website": "https://example.com", "moq": None}, locality="Morbi, Gujarat", distance_km=None,
                                           category_match=None, source_url="https://example.com", fetched_at=NOW)
        return {"agentRunId": str(uuid.uuid4()), "results": [{"candidateId": str(c), "leadIds": [], "degradedReason": None} for c in slots.candidate_ids]}

    specs = [
        dataclasses.replace(real.get("pi.discover"), invoke=discover, entitlement=None, writes_own_run=False),
        dataclasses.replace(real.get("pi.supplier_lookup"), invoke=lookup, entitlement=None, writes_own_run=False),
        real.get("pi.report"),
    ]
    return ActionRegistry(specs)


@pytest.fixture
def pienv(env, monkeypatch):  # noqa: F811
    from backend.main import app

    pi = Pi(calls={})
    e = env
    rt = dataclasses.replace(e.rt, registry=_pi_registry(e, pi))
    app.dependency_overrides[ceo_api.get_runtime] = lambda: rt
    monkeypatch.setenv("GOOGLE_PLACES_API_KEY", "test-key")
    from backend import config

    config.google_places_api_key.cache_clear()
    monkeypatch.setattr(pi_actions, "_tavily_client", lambda: _Tavily())
    monkeypatch.setattr(pi_actions, "_image_verifier", lambda: _Verifier())
    yield e, pi, rt
    app.dependency_overrides[ceo_api.get_runtime] = lambda: e.rt
    config.google_places_api_key.cache_clear()


def _answer_to_plan(e: Env, inv: str, first: dict) -> dict:
    """Answers whatever the CEO still asks (category, depth...) until a plan is produced."""
    r, answers = first, {"category": "smart watches", "price_range": "skip", "confirm": "yes", "marketplaces": "Amazon", "budget": "20000"}
    for _ in range(8):
        if r["status"] == "PLANNED":
            return r
        assert r["status"] == "CLARIFIED", r
        r = turn(e, e.owner, inv, answers[r["clarifyFor"]])
    raise AssertionError(r)


def test_values_in_the_first_message_are_reused_and_only_the_missing_ones_are_asked(pienv):
    e, pi, _ = pienv
    inv = start(e, e.owner)
    first = turn(e, e.owner, inv, ASK)
    assert first["status"] == "CLARIFIED" and first["clarifyFor"] == "category"  # niche is missing: asked
    asked = [first["clarifyFor"]]
    r = turn(e, e.owner, inv, "smart watches")
    while r["status"] == "CLARIFIED":
        asked.append(r["clarifyFor"])
        r = turn(e, e.owner, inv, {"price_range": "skip", "confirm": "yes"}[r["clarifyFor"]])
    assert "budget" not in asked and "marketplaces" not in asked, asked  # both were already in the message
    assert r["status"] == "PLANNED" and pi.calls == {}  # nothing ran before approval


def test_the_plan_lists_the_supplier_lookup_and_one_approval_runs_the_whole_chain(pienv):
    e, pi, _ = pienv
    inv = start(e, e.owner)
    planned = _answer_to_plan(e, inv, turn(e, e.owner, inv, ASK))
    plan = planned["plan"]
    assert [l["action_key"] for l in plan["plan"]["legs"]] == ["pi.discover"]
    assert [l["action_key"] for l in plan["plan"]["then"]] == ["pi.supplier_lookup"]
    assert "without asking again" in plan["plan"]["summary_text"] and "pi.supplier_lookup" in plan["plan"]["summary_text"]
    assert pi.calls == {}
    before_units = rows(e.a, "SELECT count(*) FROM metered_event")[0][0]
    r = e.client.post(f"/api/v1/ceo/investigations/{inv}/plans/{plan['id']}/approve", json={"plan_hash": plan["planHash"]}, headers=e.owner)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "DELIVERED"
    assert list(pi.calls) == ["pi.discover", "pi.supplier_lookup"]
    lookup = pi.calls["pi.supplier_lookup"][0]
    assert str(lookup["run_id"]) == str(pi.run_id) and len(lookup["candidate_ids"]) == 5  # exactly the five, chosen by code
    case = pi_actions.load_research_case(e.a, pi.run_id)
    assert [p["rank"] for p in case["products"]] == [1, 2, 3, 4, 5] and case["caseSaved"] is True
    chosen = {str(p["candidate"]["id"]) for p in case["products"]}
    assert chosen == {str(c) for c in lookup["candidate_ids"]}
    assert all((p["candidate"]["image_url"] or "").startswith("https://cdn.shop.example/") for p in case["products"])  # the five: verified product images, no video frames
    with tenant_scope(e.a) as conn:
        others = conn.execute(text("SELECT image_url FROM product_candidate WHERE run_id = :r AND id <> ALL(CAST(:ids AS uuid[]))"), {"r": str(pi.run_id), "ids": list(chosen)}).all()
    assert len(others) == 2 and all("ytimg" in (o[0] or "") for o in others)  # the two others were never touched (internal candidates)
    assert all(p["recommendation"]["supplier_option"]["supplier_name"] == "Siddhi Instruments" for p in case["products"])
    # the CEO's answer: the five only, with the honest labels, and never the other discovered candidates
    answer = body["answer"]
    open(os.environ.get("PI_DEBUG_OUT", os.devnull), "w", encoding="utf8").write(answer + "\n---\n" + plan["plan"]["summary_text"] + "\n" + str(plan["plan"]["compact_lines"]))
    for p in case["products"]:
        assert p["candidate"]["candidate_title"] in answer
    assert sum(t in answer for t in TITLES) == 5
    assert "Strongest opportunity:" in answer and "## Recommendation" in answer and "needs your supplier quote" in answer and "how many units should I buy of #1?" in answer
    assert "PI recommendation" not in answer  # one recommendation for the investigation, not one per product
    assert "Verified marketplace buyer reviews are not available" in answer and "### 1." in answer and "## Top 5 products" in answer
    assert "trending" not in answer.lower() and "bestseller" not in answer.lower()
    # the saved report is what the link opens: a pi.report finding carries the run id
    report = [f for f in body.get("findings", []) if f.get("action_key") == "pi.report"]
    assert report and report[0]["report_ref"]["runId"] == str(pi.run_id)
    # one approval: the lookup was a covered step, not a second approval; the plan is consumed once
    assert rows(e.a, "SELECT count(*) FROM investigation_plan")[0][0] == 1
    assert before_units == rows(e.a, "SELECT count(*) FROM metered_event")[0][0] - 1  # the one CEO conversation unit (the fake handlers record no PI usage)


def test_a_failed_supplier_lookup_is_named_and_the_five_are_still_delivered(pienv):
    e, pi, rt = pienv
    from backend.main import app

    rt2 = dataclasses.replace(rt, registry=_pi_registry(e, pi, lookup_fails=True))
    app.dependency_overrides[ceo_api.get_runtime] = lambda: rt2
    inv = start(e, e.owner)
    planned = _answer_to_plan(e, inv, turn(e, e.owner, inv, ASK))
    r = e.client.post(f"/api/v1/ceo/investigations/{inv}/plans/{planned['plan']['id']}/approve", json={"plan_hash": planned["plan"]["planHash"]}, headers=e.owner)
    assert r.status_code == 200, r.text
    answer = r.json()["answer"]
    assert sum(t in answer for t in TITLES) == 5
    assert "supplier lookup did not complete" in answer and "No supplier lead was found" in answer


def test_another_tenant_cannot_open_the_saved_report(pienv):
    e, pi, _ = pienv
    inv = start(e, e.owner)
    planned = _answer_to_plan(e, inv, turn(e, e.owner, inv, ASK))
    assert e.client.post(f"/api/v1/ceo/investigations/{inv}/plans/{planned['plan']['id']}/approve", json={"plan_hash": planned["plan"]["planHash"]}, headers=e.owner).status_code == 200
    assert e.client.get(f"/api/v1/pi/research/{pi.run_id}", headers=e.owner).status_code == 200
    assert e.client.get(f"/api/v1/pi/research/{pi.run_id}", headers=e.foreign).status_code == 404
    assert e.client.get("/api/v1/pi/research", headers=e.foreign).json()["items"] == []


# ------------------------------------------------------------------------------------------------ CP4: CFO results reach the saved case only through the CEO
def _case_with_five(tenant: uuid.UUID) -> uuid.UUID:
    from product_intelligence.direct_path import pi_case
    from tests.integration.test_pi_research_api import _finished_run_with_candidates

    run = _finished_run_with_candidates(tenant, 1, n=6)
    pi_case.select_top5(tenant, run)
    pi_case.finalize_case(tenant, run)
    return run


def _cfo_legs(tenant: uuid.UUID):
    from backend.ceo.contract import LegResult, LegStatus, Ref, RefKind
    from tests.integration.ceo_support import save_metric

    landed = save_metric(tenant, "LANDED_COST_PER_UNIT", period=None, value_paise=25500)
    units = save_metric(tenant, "BATCH_CONSTRAINED_QUANTITY", period=None, value_paise=380)
    return [
        LegResult("cfo.landed_cost", LegStatus.COMPLETE, payload={"engineResultRef": str(landed)}, figure_refs=(Ref(RefKind.ENGINE_RESULT, landed),)),
        LegResult("cfo.batch_size", LegStatus.COMPLETE, payload={"engineResultRef": str(units)}, figure_refs=(Ref(RefKind.ENGINE_RESULT, units),)),
    ]


def test_the_ceo_attaches_cfo_figures_to_the_named_product_and_the_report_shows_them(two_tenants, app_user):
    from backend.ceo import pi_research

    a, b = two_tenants
    run = _case_with_five(a)
    case = pi_actions.load_research_case(a, run)
    name = case["products"][2]["candidate"]["candidate_title"]
    pi_research.attach_results_to_case(a, name.upper(), _cfo_legs(a))  # matched case-insensitively against the five
    after = pi_actions.load_research_case(a, run)
    got = {p["candidate"]["candidate_title"]: p["financials"] for p in after["products"]}
    assert [f["label"] for f in got[name]] == ["Landed cost per unit", "Most units your budget allows"]
    assert got[name][0]["display"] and "255" in got[name][0]["display"] and got[name][0]["authoritative"] is True and got[name][0]["ref"]["id"]
    assert all(v == [] for t, v in got.items() if t != name)  # the other four are untouched
    pi_research.attach_results_to_case(a, name, _cfo_legs(a))  # asked again after changing a quote: the earlier entries are replaced, not duplicated
    assert len(pi_actions.load_research_case(a, run)["cfoRefs"]) == 2


def test_a_name_that_is_not_one_of_the_five_attaches_nothing_and_another_tenant_is_untouched(two_tenants, app_user):
    from backend.ceo import pi_research

    a, b = two_tenants
    run = _case_with_five(a)
    pi_research.attach_results_to_case(a, "Some Other Product", _cfo_legs(a))
    pi_research.attach_results_to_case(b, "Watch 0", _cfo_legs(b))  # tenant B has no case: nothing is written anywhere
    assert pi_actions.load_research_case(a, run)["cfoRefs"] == []


def test_the_report_read_numbers_the_five_in_rank_order_so_follow_ups_mean_the_same_product(two_tenants, app_user):
    from backend.services import pi_actions as pa

    a, _ = two_tenants
    run = _case_with_five(a)
    five = pa.top_five_for_report(a, run)
    assert [t["rank"] for t in five] == [1, 2, 3, 4, 5] and five[0]["title"] == pa.load_research_case(a, run)["products"][0]["candidate"]["candidate_title"]
    assert pa.top_five_for_report(uuid.uuid4(), run) == []  # another tenant: nothing


def test_numbered_follow_ups_resolve_to_the_five_in_rank_order_not_to_the_discovered_list(two_tenants):
    """The CEO's "#1".."#5" come from the newest PI finding's artefact; with a finished case that artefact is exactly the five, in rank order."""
    from backend.ceo import references
    from backend.ceo.contract import LegResult, LegStatus
    from backend.ceo.presentation import present_leg

    a, _ = two_tenants
    payload = {
        "runId": str(uuid.uuid4()), "status": "COMPLETE", "unavailable": [],
        "candidates": [{"candidate": {"candidate_title": f"Discovered {i}"}} for i in range(12)],  # the internal list: never what "#3" means
        "topFive": [{"rank": r, "candidateId": str(uuid.uuid4()), "title": f"Final {r}"} for r in range(1, 6)],
    }
    snap = present_leg(a, LegResult("pi.report", LegStatus.COMPLETE, payload=payload))
    finding = {"source": "PI", "created_at": datetime(2026, 10, 12, tzinfo=timezone.utc), "presentation": snap}
    assert references.latest_ideas([finding]) == [f"Final {r}" for r in range(1, 6)]
    text, notes = references.expand([finding], "is #3 worth stocking?")
    assert text == "is Final 3 worth stocking?" and notes


def test_the_whole_conversation_research_then_is_1_worth_stocking_runs_the_real_cfo_engine_and_puts_its_figures_on_the_saved_case(pienv, app_user):
    """The full chain through the real app: research (one approval) -> the seller names #1 -> quantity, window, supplier quote (price, shipping, MOQ, lead time) and budget are
    asked in chat and saved only after "yes" -> the REAL deterministic CFO legs run (no recorder) -> the CEO attaches what they returned to the saved case, which the report
    endpoint then serves. Only PI's two internet-facing steps are recorders."""
    from backend.main import app

    e, pi, rt = pienv
    real = get_registry()
    registry = ActionRegistry([*rt.registry.specs(), *(dataclasses.replace(real.get(k), entitlement=None) for k in ("cfo.landed_cost", "cfo.supplier_ranking", "cfo.batch_size"))])
    rt2 = dataclasses.replace(rt, registry=registry, max_candidate_prices=5)
    app.dependency_overrides[ceo_api.get_runtime] = lambda: rt2
    inv = start(e, e.owner)
    planned = _answer_to_plan(e, inv, turn(e, e.owner, inv, ASK))
    r = e.client.post(f"/api/v1/ceo/investigations/{inv}/plans/{planned['plan']['id']}/approve", json={"plan_hash": planned["plan"]["planHash"]}, headers=e.owner)
    assert r.status_code == 200, r.text
    assert "Next step (optional)" in r.json()["answer"] and "not a recommendation" in r.json()["answer"]  # the quote step is offered, skippable, with the ceiling caveat
    first = pi_actions.load_research_case(e.a, pi.run_id)["products"][0]["candidate"]["candidate_title"]
    q = turn(e, e.owner, inv, "ok how much units or batch size should we buy? the top #1 product ?")
    replies = {"sku": first, "quantity": "100", "supplier_name": "Siddhi Traders", "unit_cost": "250", "order_shipping": "skip", "moq": "50", "lead_time_days": "21", "budget": "100000", "confirm": "yes"}
    done = None
    for _ in range(12):
        if q["status"] != "CLARIFIED":
            done = q
            break
        slot = q["clarifyFor"]
        if slot == "window":
            window = next(o for o in q["choices"]["options"] if o["kind"] in ("RECOMMENDED", "ALTERNATIVE"))
            q = turn(e, e.owner, inv, "(chose an option)", clarification={"id": q["clarificationId"], "option": window["key"]})
        else:
            q = turn(e, e.owner, inv, replies[slot])
    assert done is not None and done["status"] == "DELIVERED", done
    after = e.client.get(f"/api/v1/pi/research/{pi.run_id}", headers=e.owner).json()
    fin = {f["label"]: f for f in after["products"][0]["financials"]}
    landed = next(f for l, f in fin.items() if l.startswith("Landed cost per unit"))
    assert landed["status"] == "COMPLETE" and landed["authoritative"] is True and landed["ref"]["kind"] == "ENGINE_RESULT" and "250" in landed["display"]  # the seller's confirmed price, from the real engine
    units = next(f for l, f in fin.items() if "units" in l.lower())
    assert units["status"] == "COMPLETE" and units["display"], fin  # a budget ceiling, computed once the MOQ made the estimate possible
    assert "ceiling, not a recommendation" in done["answer"] or "budget ceiling" in done["answer"]  # said beside the number in the chat answer
    assert all(p["financials"] == [] for p in after["products"][1:])  # only the product the seller asked about
