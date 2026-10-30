"""CMO 3.0 M6 acceptance rows that the first test files covered only at rule level (docs/CMO-3.0/CMO_M6_TRACEABILITY.md): competitor evidence end to end (N-08), the non-Amazon listings and billing totals
(N-05k, N-05l, N-05s), a verified limit that rejects over-length text (N-05v), a missing draft target (N-05w), hashtags without their configuration (N-05p), a failed pack (N-05o), the separate copied
state (N-05q), a foreign title or insight (N-05r), contradicting and repeating seller edits (N-14c, N-14d), and what the application role may do to a saved listing (N-15f)."""

from __future__ import annotations

import json
import os
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from slim_cmo.service.models import NewFact
from slim_cmo.types import SellerFactType as F
from tests.integration.test_ci_p3 import seed_competitor
from tests.integration.test_cmo_api import AMAZON, FLIPKART, MEESHO, _erase_cmo_rows, _login, ctx_engine, env, fake_clerk  # noqa: F401
from tests.integration.test_cmo_m6_integration import FLAG_ON, NAME, SKU, TITLE, ListingProvider, body, facts, gens, ru_env
from backend.tenant_context import tenant_scope

pytestmark = pytest.mark.skipif(not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL"), reason="needs a live Postgres")


def card_of(env, gid, headers=None):
    return env.client().get(f"/api/v1/cmo/listing/{gid}", headers=headers or env.headers)


def listing(env, key="k1", **extra):
    out = env.post("full-listing", body(key, **extra)).json()
    assert out["status"] in ("COMPLETE", "PARTIAL"), out
    return out


# ---------------------------------------------------------------- N-08: competitor evidence, end to end
def test_n08a_a_supported_theme_informs_the_writing_is_recorded_and_shown_as_supported(env):
    ru_env(env, ListingProvider())
    env.runtime.store.save_facts(env.tenant, env.user_id, [NewFact(F.ATTRIBUTE, SKU, "Feature", "reusable")])
    insight = seed_competitor(env, themes=["reusable", "insulated"])
    out = env.post("full-listing", body("ci1", ci_insight_ids=[str(insight)])).json()
    assert out["status"] == "COMPLETE"
    mode, snapshot = env.q("SELECT input_mode, ci_inputs_snapshot FROM cmo_generation WHERE output_type = 'LISTING_COPY' AND status = 'COMPLETE'")[0]
    assert mode == "CEO_BROKERED_CI" and snapshot["insights"][0]["id"] == str(insight)
    rows = {r["theme"]: r for r in out["card"]["ci"]["rows"]}
    assert rows["reusable"]["support"] == "SUPPORTED" and rows["reusable"]["sharedBy"] == {"count": 1, "of": 1} and out["card"]["ci"]["used"] is True
    prompt = next(p for p in env.provider.prompts if "keywords_allowed" in p)
    assert "reusable" in prompt  # only a theme the confirmed facts carry reaches the model


def test_n08b_an_unsupported_theme_is_only_a_suggestion_never_given_to_the_model_or_written(env):
    ru_env(env, ListingProvider())
    env.runtime.store.save_facts(env.tenant, env.user_id, [NewFact(F.ATTRIBUTE, SKU, "Feature", "reusable")])
    insight = seed_competitor(env, themes=["reusable", "insulated"])
    out = env.post("full-listing", body("ci2", ci_insight_ids=[str(insight)])).json()
    c = out["card"]
    assert "insulated" in c["ci"]["considerIfTrue"] and {r["theme"]: r["support"] for r in c["ci"]["rows"]}["insulated"] == "CONSIDER_IF_TRUE"
    shown = json.dumps(c["sections"]).lower()
    assert "insulated" not in shown
    for p in env.provider.prompts:  # the competitor-context block (the only way a competitor theme reaches the model) carries the supported theme, never the unsupported one
        block = p.split("MARKET CONTEXT")[1] if "MARKET CONTEXT" in p else ""
        assert "insulated" not in block.lower()
    assert any("MARKET CONTEXT" in p and "reusable" in p.split("MARKET CONTEXT")[1] for p in env.provider.prompts)


def test_n08c_no_competitor_text_price_or_image_is_stored_or_shown(env):
    ru_env(env, ListingProvider())
    env.runtime.store.save_facts(env.tenant, env.user_id, [NewFact(F.ATTRIBUTE, SKU, "Feature", "reusable")])
    insight = seed_competitor(env, themes=["reusable"])
    out = env.post("full-listing", body("ci3", ci_insight_ids=[str(insight)])).json()
    stored = json.dumps(env.q("SELECT output_structured, ci_inputs_snapshot FROM cmo_generation"), default=str) + json.dumps(env.q("SELECT findings, checks, keyword_map FROM cmo_listing_audit"), default=str)
    for secret in ("CASPIAN", "Double wall vacuum", "32900", "Leakproof cap with a carry loop"):
        assert secret not in stored and secret not in json.dumps(out), secret  # derived words only
    assert all("CASPIAN" not in p and "Double wall" not in p for p in env.provider.prompts)


def test_n08d_competitor_themes_that_cannot_be_used_never_block_the_listing(env):
    ru_env(env, ListingProvider())
    from backend.auth.permissions import PARTNER_ROLE

    insight = seed_competitor(env, themes=["reusable"])
    only_cmo, _ = _login(env.fake_clerk, env.tenant, role=PARTNER_ROLE, permissions={"agent.cmo": True})  # no agent.ci: the broker is refused
    r = env.post("full-listing", body("ci4", ci_insight_ids=[str(insight)]), headers=only_cmo)
    assert r.status_code == 200 and r.json()["status"] == "COMPLETE" and r.json()["card"]["ci"]["used"] is False  # the broker is refused, the listing is not
    assert env.q("SELECT input_mode, ci_inputs_snapshot FROM cmo_generation WHERE output_type = 'LISTING_COPY' AND status = 'COMPLETE'")[0] == ("INDEPENDENT", None)
    assert all("MARKET CONTEXT" not in p for p in env.provider.prompts)


def test_n08e_without_competitor_evidence_the_listing_is_independent_with_no_ci_section(env):
    ru_env(env, ListingProvider())
    out = listing(env, "ci5")
    assert out["card"]["ci"] == {"rows": [], "considerIfTrue": [], "used": False}
    assert "differentiat" not in json.dumps(out["card"]["sections"]).lower()
    assert env.q("SELECT ci_inputs_snapshot FROM cmo_generation WHERE output_type = 'LISTING_COPY'")[0][0] is None


def test_n08f_a_foreign_insight_id_is_not_found_and_nothing_runs(env):
    ru_env(env, ListingProvider())
    other, _ = env.other_tenant()
    foreign = seed_competitor(env, tenant=other, themes=["reusable"])
    r = env.post("full-listing", body("ci6", ci_insight_ids=[str(foreign)]))
    missing = env.post("full-listing", body("ci7", ci_insight_ids=[str(uuid.uuid4())]))
    assert r.status_code == 404 and missing.status_code == 404 and r.json() == missing.json()  # indistinguishable from an unknown id
    assert env.provider.calls == 0 and gens(env) == [] and env.events() == []


# ---------------------------------------------------------------- N-05r: a foreign title
def test_n05r_a_title_approval_of_another_tenant_is_not_found(env):
    ru_env(env, ListingProvider())
    r = env.post("full-listing", {**body("fa"), "seller_title": None, "approval_id": str(uuid.uuid4())})
    assert r.status_code == 404 and r.json()["detail"]["code"] == "NO_TITLE" and env.provider.calls == 0 and gens(env) == []


# ---------------------------------------------------------------- N-05k, N-05l, N-05s: marketplaces and totals
@pytest.mark.parametrize("mp,units,kinds", [(AMAZON, 2, ["LISTING_COPY", "BACKEND_TERMS"]), (FLIPKART, 1, ["LISTING_COPY"]), (MEESHO, 1, ["LISTING_COPY"])])
def test_n05k_n05l_n05s_backend_terms_are_amazon_only_and_each_marketplace_bills_what_it_delivers(env, mp, units, kinds):
    ru_env(env, ListingProvider())
    out = env.post("full-listing", {**body("mp"), "marketplace": mp}).json()
    assert out["status"] == "COMPLETE" and out["unitsBilled"] == units and len(env.events()) == units
    assert [g[0] for g in gens(env)] == kinds and out["card"]["marketplace"] == mp
    assert (out["card"]["sections"]["backend_terms"] is not None) == (mp == AMAZON)  # Flipkart and Meesho: no backend-terms field at all
    assert out["card"]["rulesBasis"] == "UNVERIFIED" and all(g[3] == "UNVERIFIED" for g in gens(env))


# ---------------------------------------------------------------- N-05v (a): a verified limit is enforced
def test_n05v_a_verified_limit_rejects_text_over_it_the_pack_fails_and_nothing_is_billed(env):
    ru_env(env, ListingProvider())
    with env.engine.begin() as conn:
        conn.execute(text("INSERT INTO format_constraint (marketplace, title_max_chars, title_option_count, bullet_count, bullet_max_chars, description_type, description_max_chars, keywords_max_count, "
                          "keywords_max_chars, backend_terms_max_bytes, count_rule, source_url, verified_at, version, row_kind) VALUES ('AMAZON', 200, 3, 3, 10, 'plain', 900, 10, 40, 249, "
                          "'UTF16_CODE_UNITS', 'https://example.invalid/test-fixture', now(), 1, 'TEST_FIXTURE')"))
    out = env.post("full-listing", body("over")).json()
    assert out["status"] == "FAILED" and out["unitsBilled"] == 0 and out["card"] is None and env.events() == []
    assert all(g[1] == "FAILED" for g in gens(env)) and env.q("SELECT count(*) FROM cmo_generation WHERE status = 'COMPLETE'")[0][0] == 0  # never delivered over the limit


# ---------------------------------------------------------------- N-05w: a missing draft target blocks and names the key
def test_n05w_a_missing_draft_bullet_target_blocks_naming_the_key_with_no_hidden_default(env):
    cfg = {k: v for k, v in FLAG_ON.items() if k != "rules_unavailable_bullet_target"}
    ru_env(env, ListingProvider(), config=cfg)
    out = env.post("full-listing", body("nt")).json()
    assert out["status"] == "FAILED" and out["unitsBilled"] == 0 and "rules_unavailable_bullet_target" in json.dumps(out) and env.provider.calls == 0 and env.events() == []


# ---------------------------------------------------------------- N-05p: hashtags without their configuration
def test_n05p_hashtags_without_their_key_say_config_missing_and_the_rest_proceeds(env):
    ru_env(env, ListingProvider())
    with env.engine.begin() as conn:  # the key the environment seeds for every tenant is removed for this one
        conn.execute(text("DELETE FROM cmo_platform_config WHERE tenant_id = :t AND key = 'hashtag_set_size'"), {"t": str(env.tenant)})
    out = env.post("full-listing", body("hk", include_hashtags=True)).json()
    tags = out["hashtags"]["artefacts"][0]
    assert out["status"] == "PARTIAL" and out["unitsBilled"] == 2 and tags["status"] == "FAILED" and "hashtag_set_size" in json.dumps(tags)
    assert [g[0] for g in gens(env)] == ["LISTING_COPY", "BACKEND_TERMS", "HASHTAGS"] and [g[1] for g in gens(env)] == ["COMPLETE", "COMPLETE", "FAILED"]


# ---------------------------------------------------------------- N-05o: the pack itself fails
class BrokenPack(ListingProvider):
    def complete(self, *, model: str, prompt: str) -> str:
        shape = prompt.split("Reply shape:")[1].split("\n")[0]
        if '"bullets"' in shape and '"keywords"' in shape:
            with self._lock:
                self.calls += 1
            return "this is not json at all SECRET-RAW-MODEL-OUTPUT"
        return super().complete(model=model, prompt=prompt)


def test_n05o_a_failed_pack_saves_no_text_uses_no_unit_runs_no_later_step_and_leaks_nothing(env):
    ru_env(env, BrokenPack())
    r = env.post("full-listing", body("bad"))
    out = r.json()
    assert r.status_code == 200 and out["status"] == "FAILED" and out["unitsBilled"] == 0 and out["card"] is None and "SECRET-RAW-MODEL-OUTPUT" not in r.text
    assert [(g[0], g[1]) for g in gens(env)] == [("LISTING_COPY", "FAILED")]  # the terms step never ran
    assert env.events() == [] and env.n("cmo_listing_audit") == 0 and env.reservations().count("RESERVED") == 0
    assert env.q("SELECT output_text, output_structured ->> 'bullets' FROM cmo_generation")[0] == (None, None)  # no partial text


# ---------------------------------------------------------------- N-05q: copying is its own state and works before approval
def test_n05q_copied_is_its_own_state_recorded_before_any_approval_and_changes_nothing_else(env):
    ru_env(env, ListingProvider())
    gid = listing(env)["card"]["generationId"]
    events = len(env.events())
    r = env.client().post("/api/v1/cmo/showcase/usage-events", json={"generationId": gid, "kind": "COPIED", "surface": "CHAT"}, headers=env.headers)
    assert r.status_code == 204, r.text
    st = card_of(env, gid).json()["states"]
    assert st["copied"]["count"] == 1 and st["approvedForUse"]["done"] is False and st["markedUsed"]["count"] == 0 and st["published"]["known"] is False
    assert st["generated"]["done"] is True and st["audited"]["done"] is True
    used = env.client().post("/api/v1/cmo/showcase/usage-events", json={"generationId": gid, "kind": "MARKED_USED", "surface": "CHAT"}, headers=env.headers)
    assert used.status_code == 204
    st = card_of(env, gid).json()["states"]
    assert st["markedUsed"]["count"] == 1 and st["copied"]["count"] == 1 and st["approvedForUse"]["done"] is False  # marking used approves nothing, and copying marked nothing used
    assert len(env.events()) == events and env.n("cmo_result_usage_event", "event_kind = 'APPROVED'") == 0


# ---------------------------------------------------------------- N-14c, N-14d: seller edits
def test_n14c_an_edit_that_contradicts_the_confirmed_capacity_is_refused_with_section_and_fix(env):
    ru_env(env, ListingProvider())
    gid = listing(env)["card"]["generationId"]
    rows = len(gens(env))
    r = env.client().post(f"/api/v1/cmo/listing/{gid}/edit", json={"message": "Change bullet 2 to: Holds 750 ml"}, headers=env.headers)
    assert r.status_code == 422 and "750" in json.dumps(r.json()) and len(gens(env)) == rows
    d = env.client().post(f"/api/v1/cmo/listing/{gid}/edit", json={"message": "Change description to: A bottle that holds 750 ml of water."}, headers=env.headers)
    assert d.status_code == 422 and len(gens(env)) == rows  # detected in the bullet and in the description


def test_n14d_repetition_is_a_warning_the_edit_is_saved_and_the_finding_names_the_term(env):
    ru_env(env, ListingProvider())
    first = listing(env)["card"]
    gid, term = first["generationId"], first["keywordMap"]["candidates"][0]["keyword"]
    r = env.client().post(f"/api/v1/cmo/listing/{gid}/edit", json={"message": f"Change bullet 2 to: {term} one, {term} two, {term} three"}, headers=env.headers)
    assert r.status_code == 200, r.text
    card = card_of(env, r.json()["generationId"]).json()
    warn = [f for f in card["audit"]["findings"] if f["code"] == "W1_REPEATED_IN_BULLET"]
    assert warn and all(f["severity"] == "WARNING" for f in warn) and term in warn[0]["explanation"] and card["audit"]["verdict"] != "BLOCKED"
    assert "not a marketplace" in warn[0]["explanation"].lower() or "ranking" in warn[0]["explanation"].lower()  # stated as an internal limit


# ---------------------------------------------------------------- N-15f: saved versions are append-only for the application role
def test_n15f_the_application_role_cannot_rewrite_or_delete_a_saved_listing_version(env):
    ru_env(env, ListingProvider())
    gid = listing(env)["card"]["generationId"]
    before = env.q("SELECT output_structured FROM cmo_generation WHERE id = :g", g=gid)[0][0]
    for sql in ("UPDATE cmo_generation SET output_structured = '{}'::jsonb WHERE id = :g", "DELETE FROM cmo_generation WHERE id = :g"):
        with pytest.raises(DBAPIError):
            with tenant_scope(env.tenant) as conn:
                conn.execute(text(sql), {"g": gid})
    assert env.q("SELECT output_structured FROM cmo_generation WHERE id = :g", g=gid)[0][0] == before


# ---------------------------------------------------------------- N-05t: a typed title has no strategy
def test_n05t_a_typed_title_is_used_verbatim_and_its_strategy_is_not_assessed(env):
    ru_env(env, ListingProvider())
    typed = "My Very Own Bottle Title For Steel"
    c = env.post("full-listing", body("ct", seller_title=typed)).json()["card"]
    assert c["strategy"] == "NOT_ASSESSED" and c["sections"]["title"] == typed
