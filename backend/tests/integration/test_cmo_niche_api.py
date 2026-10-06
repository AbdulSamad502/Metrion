"""P7d end-to-end: the catalog-seeded niche flow over the real HTTP API on a real Postgres (spec §6.8.3, AC30, AC34,
T34, T38, E19, E20, E26). Real: FastAPI app, auth chain (Clerk faked), the niche service, Postgres + RLS, the
`sales_line` read. No model or provider is involved at all."""

from __future__ import annotations

import json
import os
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import text

from backend.auth.permissions import PARTNER_ROLE

from .test_cmo_api import _login, _make_tenant, ctx_engine, env, fake_clerk, _erase_cmo_rows  # noqa: F401

pytestmark = pytest.mark.skipif(not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL"), reason="needs a live Postgres")

NICHE_CFG = {"max_confirmed_niche_terms": 3, "max_term_chars": 40, "catalog_titles_read_cap": 200}
TITLES = [
    "Steel Water Bottle 1 Litre Leak Proof", "Steel Water Bottle Gym Shaker", "Copper Water Bottle 750ml",
    "Steel Lunch Box 3 Compartment", "Steel Lunch Box Insulated", "Yoga Mat Anti Skid",
]


def seed_config(env, values=None, tenant=None):
    t = tenant or env.tenant
    with env.engine.begin() as conn:
        for k, v in (NICHE_CFG if values is None else values).items():
            conn.execute(text("INSERT INTO cmo_platform_config (tenant_id, key, value, effective_from) VALUES (:t, :k, CAST(:v AS jsonb), '2026-01-01')"),
                         {"t": str(t), "k": k, "v": json.dumps(v)})


def seed_titles(env, titles, tenant=None):
    t = tenant or env.tenant
    run, file_ = uuid.uuid4(), uuid.uuid4()
    with env.cengine.begin() as conn:
        conn.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": str(t)})
        conn.execute(text("INSERT INTO report_file (id, tenant_id, marketplace, report_category, content_sha256, original_filename, byte_size, storage_uri, uploaded_by, uploaded_at) "
                          "VALUES (:id, :t, 'MEESHO', 'TAX', :sha, 'a.csv', 1, 's3://x', :u, now())"),
                     {"id": str(file_), "t": str(t), "sha": uuid.uuid4().hex + uuid.uuid4().hex, "u": str(uuid.uuid4())})
        conn.execute(text("INSERT INTO ingestion_run (id, tenant_id, report_file_id, adapter_id, adapter_version, status) VALUES (:id, :t, :f, 'meesho.orders.v1', 'v1', 'PENDING')"),
                     {"id": str(run), "t": str(t), "f": str(file_)})
        for i, title in enumerate(titles, start=1):
            conn.execute(text("INSERT INTO sales_line (tenant_id, ingestion_run_id, marketplace, item_title, source_row_number, source_row_json, confidence) "
                              "VALUES (:t, :r, 'MEESHO', :title, :n, '{}'::jsonb, 'PROVISIONAL')"),
                         {"t": str(t), "r": str(run), "title": title, "n": i})


def suggest(env, headers=None):
    from fastapi.testclient import TestClient

    from backend.main import app

    return TestClient(app).post("/api/v1/cmo/niche-terms/suggest", headers=env.headers if headers is None else headers)


def listing(env, headers=None):
    from fastapi.testclient import TestClient

    from backend.main import app

    return TestClient(app).get("/api/v1/cmo/niche-terms", headers=env.headers if headers is None else headers)


def terms_by_name(resp_json):
    return {t["term"]: t for t in resp_json["suggestions"]}


# ---- authorisation -----------------------------------------------------------------------------------------


def test_unauthenticated_is_401_for_all_three_routes(env):
    seed_config(env)
    assert suggest(env, {}).status_code == 401
    assert listing(env, {}).status_code == 401
    assert env.post("niche-terms/confirm", {"new_terms": ["x"]}, headers={}).status_code == 401
    assert env.n("cmo_niche_term") == 0


def test_suggest_needs_catalog_view_as_well_as_agent_cmo_T38(env):
    seed_config(env)
    seed_titles(env, TITLES)
    cmo_only, _ = _login(env.fake_clerk, env.tenant, role=PARTNER_ROLE, permissions={"agent.cmo": True})
    r = suggest(env, cmo_only)
    assert r.status_code == 403 and "catalog.view" in json.dumps(r.json())
    view_only, _ = _login(env.fake_clerk, env.tenant, role=PARTNER_ROLE, permissions={"catalog.view": True})
    assert suggest(env, view_only).status_code == 403  # no agent.cmo
    old_key, _ = _login(env.fake_clerk, env.tenant, role=PARTNER_ROLE, permissions={"agent.cmo": True, "files.view": True})
    assert suggest(env, old_key).status_code == 403  # files.view is NOT a substitute
    both, _ = _login(env.fake_clerk, env.tenant, role=PARTNER_ROLE, permissions={"agent.cmo": True, "catalog.view": True})
    assert suggest(env, both).status_code == 200
    assert env.n("cmo_niche_term") > 0


def test_confirm_and_list_need_only_agent_cmo(env):
    seed_config(env)
    cmo_only, _ = _login(env.fake_clerk, env.tenant, role=PARTNER_ROLE, permissions={"agent.cmo": True})
    assert env.post("niche-terms/confirm", {"new_terms": ["steel bottle"]}, headers=cmo_only).status_code == 200
    assert listing(env, cmo_only).status_code == 200
    nobody, _ = _login(env.fake_clerk, env.tenant, role=PARTNER_ROLE, permissions={})
    assert env.post("niche-terms/confirm", {"new_terms": ["x y"]}, headers=nobody).status_code == 403
    assert listing(env, nobody).status_code == 403


def test_a_client_supplied_tenant_or_status_field_is_a_422(env):
    seed_config(env)
    for body in ({"new_terms": ["a b"], "tenant_id": str(uuid.uuid4())}, {"new_terms": ["a b"], "status": "CONFIRMED"},
                 {"decisions": [{"term_id": str(uuid.uuid4()), "decision": "CONFIRM", "tenant_id": str(uuid.uuid4())}]}):
        assert env.post("niche-terms/confirm", body).status_code == 422
    assert env.n("cmo_niche_term") == 0


# ---- configuration fails closed ---------------------------------------------------------------------------


def test_missing_niche_config_is_503_config_missing_and_nothing_is_read_or_written(env):
    seed_titles(env, TITLES)  # config deliberately not seeded
    for r in (suggest(env), env.post("niche-terms/confirm", {"new_terms": ["steel bottle"]})):
        assert r.status_code == 503
        d = r.json()["detail"]
        assert d["code"] == "CONFIG_MISSING" and set(d["missing"]) == set(NICHE_CFG)
    assert env.n("cmo_niche_term") == 0 and env.n("agent_run") == 0


def test_an_invalid_niche_config_value_is_reported_not_defaulted(env):
    seed_config(env, {**NICHE_CFG, "max_term_chars": 0})
    r = suggest(env)
    assert r.status_code == 503 and r.json()["detail"]["invalid"][0]["key"] == "max_term_chars"


# ---- the flow (T34) ----------------------------------------------------------------------------------------


def test_T34_titles_only_screened_terms_two_confirmed_and_only_those_are_egress_eligible(env):
    seed_config(env, {**NICHE_CFG, "max_confirmed_niche_terms": 6})
    seed_titles(env, TITLES + ["Call 9876543210 Steel Bottle", "Order od12345678901 steel bottle", "Buy www.shop.com steel bottle"])
    r = suggest(env)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "OK" and body["unitsBilled"] == 0 and body["confirmed"] == []
    names = terms_by_name(body)
    assert names and len(names) <= 6 and all(t["origin"] == "CATALOG_DERIVED" for t in names.values())
    assert not any(bad in t for t in names for bad in ("9876543210", "od1234", "www", ".com"))
    for row in env.q("SELECT term, origin_note FROM cmo_niche_term"):
        assert "9876543210" not in row[0] and not any(t.lower() in (row[1] or "").lower() for t in TITLES)

    picked = sorted(names)[:2]
    c = env.post("niche-terms/confirm", {"decisions": [{"term_id": names[t]["id"], "decision": "CONFIRM"} for t in picked]})
    assert c.status_code == 200 and {t["term"] for t in c.json()["confirmed"]} == set(picked)
    confirmed = sorted(r[0] for r in env.q("SELECT term FROM cmo_niche_term WHERE status = 'CONFIRMED'"))
    assert confirmed == sorted(picked)  # everything else stays SUGGESTED: never egress-eligible
    assert env.q("SELECT count(*) FROM cmo_niche_term WHERE status = 'CONFIRMED' AND confirmed_by IS NULL")[0][0] == 0


def test_suggest_and_confirm_are_zero_unit_with_one_agent_run_each_and_no_metering(env):
    seed_config(env)
    seed_titles(env, TITLES)
    s = suggest(env).json()
    env.post("niche-terms/confirm", {"decisions": [{"term_id": s["suggestions"][0]["id"], "decision": "CONFIRM"}]})
    assert env.events() == [] and env.reservations() == []
    assert sorted(r[0] for r in env.q("SELECT trigger_ref FROM agent_run")) == ["cmo.confirm_niche_terms", "cmo.suggest_niche_terms"]


def test_no_catalog_titles_is_unavailable_and_the_seller_can_type_a_niche_E19(env):
    seed_config(env)
    r = suggest(env)
    assert r.status_code == 200 and r.json()["status"] == "UNAVAILABLE" and r.json()["suggestions"] == []
    c = env.post("niche-terms/confirm", {"new_terms": ["Eco Friendly Bottle"]})
    assert c.status_code == 200
    assert [(t["term"], t["origin"], t["status"]) for t in c.json()["confirmed"]] == [("eco friendly bottle", "SELLER_STATED", "CONFIRMED")]


def test_edit_reject_and_reconfirm(env):
    seed_config(env)
    seed_titles(env, TITLES)
    names = terms_by_name(suggest(env).json())
    wb, lb = names["water bottle"]["id"], names["steel lunch box"]["id"]
    r = env.post("niche-terms/confirm", {"decisions": [{"term_id": wb, "decision": "EDIT", "new_text": "Insulated Flask"}, {"term_id": lb, "decision": "REJECT"}]})
    assert r.status_code == 200 and [t["term"] for t in r.json()["confirmed"]] == ["insulated flask"] and r.json()["rejectedCount"] == 2
    again = suggest(env).json()
    assert "steel lunch box" not in terms_by_name(again) and "water bottle" not in terms_by_name(again)  # rejected: never re-offered
    assert env.post("niche-terms/confirm", {"decisions": [{"term_id": lb, "decision": "CONFIRM"}]}).status_code == 200


def test_unsafe_terms_are_refused_with_reasons_and_nothing_changes_E20_E26(env):
    seed_config(env)
    for bad in ("me@example.com", "9876543210", "https://x.test/a", "27AAPFU0939F1ZV", "12345"):
        r = env.post("niche-terms/confirm", {"new_terms": ["fine term", bad]})
        assert r.status_code == 422 and r.json()["detail"]["code"] == "NICHE_TERM_REFUSED", bad
        assert r.json()["detail"]["terms"][0]["reasons"]
    assert env.n("cmo_niche_term") == 0


def test_the_confirmed_cap_is_a_422_and_changes_nothing(env):
    seed_config(env)
    assert env.post("niche-terms/confirm", {"new_terms": ["one a", "two b", "three c"]}).status_code == 200
    r = env.post("niche-terms/confirm", {"new_terms": ["four d"]})
    assert r.status_code == 422 and r.json()["detail"] == {"code": "TOO_MANY_CONFIRMED_TERMS", "maximum": 3}
    assert env.n("cmo_niche_term") == 3


def test_concurrent_confirmations_can_never_exceed_the_cap(env):
    seed_config(env)

    def go(i):
        return env.post("niche-terms/confirm", {"new_terms": [f"term number {chr(97 + i)}"]}).status_code

    with ThreadPoolExecutor(8) as pool:
        codes = list(pool.map(go, range(8)))
    assert codes.count(200) == 3 and codes.count(422) == 5
    assert env.n("cmo_niche_term", "status = 'CONFIRMED'") == 3


def test_empty_and_malformed_requests_are_422(env):
    seed_config(env)
    for body in ({}, {"decisions": [], "new_terms": []}, {"new_terms": ["a b", "A  B"]},
                 {"decisions": [{"term_id": str(uuid.uuid4()), "decision": "EDIT"}]}, {"decisions": [{"term_id": "nope", "decision": "CONFIRM"}]}):
        assert env.post("niche-terms/confirm", body).status_code == 422, body


# ---- tenant isolation ------------------------------------------------------------------------------------


def test_another_tenants_titles_terms_and_ids_never_cross(env):
    seed_config(env)
    seed_titles(env, TITLES)
    other = _make_tenant(env.engine)
    other_headers, _ = _login(env.fake_clerk, other, role="OWNER")
    seed_config(env, tenant=other)
    seed_titles(env, ["Wooden Chess Board Set", "Wooden Chess Board Large", "Wooden Chess Pieces"], tenant=other)

    mine = suggest(env).json()
    theirs = suggest(env, other_headers).json()
    assert any("chess" in t for t in terms_by_name(theirs)) and not any("chess" in t for t in terms_by_name(mine))
    assert any("bottle" in t for t in terms_by_name(mine)) and not any("bottle" in t for t in terms_by_name(theirs))

    foreign_id = next(v["id"] for k, v in terms_by_name(theirs).items() if "chess" in k)
    r = env.post("niche-terms/confirm", {"decisions": [{"term_id": foreign_id, "decision": "CONFIRM"}]})
    assert r.status_code == 404 and r.json() == {"detail": "Not found"}
    assert not any("chess" in t["term"] for t in listing(env).json()["terms"])
    assert env.q("SELECT count(*) FROM cmo_niche_term WHERE status = 'CONFIRMED'", other)[0][0] == 0


def test_the_catalog_read_is_bounded_by_the_configured_cap(env):
    seed_config(env, {**NICHE_CFG, "catalog_titles_read_cap": 2})
    seed_titles(env, TITLES)
    assert suggest(env).json()["titlesRead"] == 2


# ---- independent review fixes (P10)
def test_listing_terms_without_catalog_view_shows_only_the_sellers_confirmed_terms(env):
    seed_config(env)
    seed_titles(env, TITLES)
    names = terms_by_name(suggest(env).json())
    env.post("niche-terms/confirm", {"decisions": [{"term_id": names["water bottle"]["id"], "decision": "CONFIRM"}]})
    cmo_only, _ = _login(env.fake_clerk, env.tenant, role=PARTNER_ROLE, permissions={"agent.cmo": True})
    both, _ = _login(env.fake_clerk, env.tenant, role=PARTNER_ROLE, permissions={"agent.cmo": True, "catalog.view": True})
    seen_without = listing(env, cmo_only).json()["terms"]
    seen_with = listing(env, both).json()["terms"]
    assert [t["term"] for t in seen_without] == ["water bottle"] and all(t["status"] == "CONFIRMED" for t in seen_without)
    assert len(seen_with) > len(seen_without) and any(t["status"] == "SUGGESTED" for t in seen_with)  # catalog-derived suggestions need catalog.view


def test_an_absurd_target_price_is_a_422_not_a_500(env):
    for bad in (2**63, 10**30, -1, 4.5, "499"):
        r = env.post("title-sets", {"request_key": "p1", "marketplaces": ["AMAZON"], "brand": "x", "target_price_paise": bad})
        assert r.status_code == 422, bad
    assert env.n("cmo_generation") == 0
