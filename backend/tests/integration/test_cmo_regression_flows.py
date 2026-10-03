"""P1-P5 regression flows that cross phase boundaries (verification only - no product code involved).

Flows 11, 12 and 13 of the regression checklist, exercised through the real HTTP API on a real Postgres:
  11  marketplace constraints stay authoritative after P3/P4/P5 integration (incl. the production path never
      reading TEST_FIXTURE rows)
  12  a target price and unverified / ineligible facts never enter generated copy or a prompt
  13  P1 RLS is still effective for the application role after the API has written rows
The remaining flows (1-10, 14) are covered by test_cmo_api.py and the slim-cmo suites; see the checkpoint report."""

from __future__ import annotations

import json
import os
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from backend import config
from backend.services import cmo_runtime

# Re-use the API suite's fixtures and helpers (pytest resolves fixtures from the importing module's namespace).
from .test_cmo_api import (  # noqa: F401
    AMAZON, TITLES, TS_METER, RoutingProvider, _REAL_BUILD_RUNTIME, _erase_cmo_rows, ctx_engine, env, fake_clerk, seed_analysis, title_body,
)

pytestmark = pytest.mark.skipif(not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL"), reason="needs a live Postgres")


class FixedProvider(RoutingProvider):
    """Returns whatever title list it was given, recording every prompt."""

    def __init__(self, titles: list[str]) -> None:
        super().__init__()
        self.titles = titles

    def complete(self, *, model: str, prompt: str) -> str:
        super().complete(model=model, prompt=prompt)
        return json.dumps({"titles": self.titles})


# ---- 11: constraints are authoritative --------------------------------------------------------------


def test_over_limit_and_duplicate_titles_are_never_delivered_and_counts_come_from_code(env):
    long_title = "AquaKeep " + "Steel " * 30  # > the fixture's 80-character limit
    env.provider.complete = FixedProvider([TITLES[0], long_title, TITLES[0].upper(), TITLES[1], "Bestseller AquaKeep"]).complete  # type: ignore[method-assign]
    r = env.post("title-sets", title_body("c11"))
    art = r.json()["artefacts"][0]
    assert r.status_code == 200 and art["status"] == "COMPLETE"
    texts = [o["text"] for o in art["options"]]
    assert texts == [TITLES[0], TITLES[1]] and art["short"] is True and art["deliveredOptionCount"] == 2   # short and labelled, never padded
    assert all(len(t) <= 80 for t in texts) and [o["charCount"] for o in art["options"]] == [len(t) for t in texts]
    assert art["constraint"]["sourceUrl"] == "https://example.invalid/test-fixture"
    assert len(env.events()) == 1  # a short set is one delivered artefact: one unit


def test_a_stale_constraint_blocks_the_marketplace_through_the_api_with_no_model_call(env):
    with env.engine.begin() as conn:
        conn.execute(text("UPDATE format_constraint SET verified_at = now() - interval '400 days' WHERE row_kind = 'TEST_FIXTURE'"))
    r = env.post("title-sets", title_body("stale"))
    art = r.json()["artefacts"][0]
    assert r.status_code == 200 and art["status"] == "FAILED" and art["failure"]["code"] == "CONSTRAINT_BLOCKED"
    assert env.provider.calls == 0 and env.events() == []


def test_the_production_runtime_never_reads_test_fixture_rows(env):
    """The REAL runtime (VERIFIED rows only) with only fixture rows present: blocked, the model is never called."""
    env.monkeypatch.setattr(cmo_runtime, "build_runtime", _REAL_BUILD_RUNTIME)  # the production composition root
    for name, value in (("CMO_LLM_MODEL", "unused-model"), ("CMO_OLLAMA_HOST", "http://127.0.0.1:9"), ("CMO_LLM_TIMEOUT_SECONDS", "1")):
        env.monkeypatch.setenv(name, value)
    for fn in (config.cmo_llm_model, config.cmo_ollama_host, config.cmo_llm_timeout_seconds):
        fn.cache_clear()
    try:
        r = env.post("title-sets", title_body("prod"))
        art = r.json()["artefacts"][0]
        assert r.status_code == 200 and art["status"] == "FAILED" and art["failure"]["code"] == "CONSTRAINT_BLOCKED"
        assert env.events() == []
    finally:
        for fn in (config.cmo_llm_model, config.cmo_ollama_host, config.cmo_llm_timeout_seconds):
            fn.cache_clear()


# ---- 12: price and unverified facts never reach copy ---------------------------------------------------


def test_target_price_and_unverified_hints_never_reach_a_prompt_or_a_delivered_artefact(env):
    analysis = seed_analysis(env.cengine, env.tenant, [{"name": "color", "value": "matte blue", "basis": "IMAGE_OBSERVED", "trust_state": "UNVERIFIED_HINT"}])
    leaky = FixedProvider(["AquaKeep matte blue Steel Bottle", "AquaKeep Bottle Rs. 499", "AquaKeep Bottle 49900"])
    env.provider.complete = leaky.complete  # type: ignore[method-assign]
    r = env.post("title-sets", title_body("c12", target_price_paise=49900, image_analysis_id=str(analysis), notes=["customers love it"]))
    body = r.json()
    art = body["artefacts"][0]
    assert r.status_code == 200 and art["status"] == "FAILED" and body["unitsBilled"] == 0       # every leaky option was refused
    assert art["failure"]["code"] == "NEEDS_FACTS" and art["failure"]["missingFacts"] == ["color"]  # ask the seller to confirm the colour
    assert env.events() == []
    for prompt in leaky.prompts:
        for forbidden in ("49900", "499", "matte blue", "target_price", "TARGET_PRICE"):
            assert forbidden not in prompt, forbidden
    assert "matte blue" not in r.text and "49900" not in r.text
    # the price is stored as integer paise context only
    assert env.q("SELECT value_paise FROM seller_fact WHERE fact_type = 'TARGET_PRICE'") == [(49900,)]


def test_a_seller_confirmed_hint_is_usable_but_the_original_hint_stays_untrusted(env):
    analysis = seed_analysis(env.cengine, env.tenant, [{"name": "color", "value": "matte blue", "basis": "IMAGE_OBSERVED", "trust_state": "UNVERIFIED_HINT"}])
    assert env.post("image-hints/confirm", {"analysis_id": str(analysis), "attribute_name": "color", "sku": "SKU1"}).status_code == 200
    provider = FixedProvider(["AquaKeep matte blue Steel Bottle", "AquaKeep Blue Flask", "AquaKeep Blue Mug"])
    env.provider.complete = provider.complete  # type: ignore[method-assign]
    r = env.post("title-sets", title_body("c12b", image_analysis_id=str(analysis)))
    assert r.json()["artefacts"][0]["status"] == "COMPLETE"
    assert '"value": "matte blue"' in provider.prompts[0]                                        # the seller's own statement
    assert env.q("SELECT attributes FROM product_image_analysis")[0][0][0]["trust_state"] == "UNVERIFIED_HINT"


# ---- 13: RLS remains effective ---------------------------------------------------------------------------


def test_rls_hides_everything_the_api_wrote_from_the_app_role_without_the_right_tenant_context(env):
    assert env.post("title-sets", title_body("rls")).status_code == 200
    ts = env.q("SELECT id FROM cmo_generation")[0][0]
    other = uuid.uuid4()
    engine = create_engine(os.environ["DATABASE_URL_APP"], poolclass=NullPool)  # metrion_app: non-owner, NOBYPASSRLS
    tables = ("cmo_generation", "cmo_title_option", "seller_fact", "agent_run", "metered_event")
    try:
        with engine.begin() as conn:  # no tenant context at all
            for t in tables:
                assert conn.execute(text(f"SELECT count(*) FROM {t}")).scalar_one() == 0, t
        with engine.begin() as conn:  # someone else's tenant context
            conn.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": str(other)})
            for t in tables:
                assert conn.execute(text(f"SELECT count(*) FROM {t}")).scalar_one() == 0, t
            assert conn.execute(text("SELECT count(*) FROM cmo_generation WHERE id = :i"), {"i": ts}).scalar_one() == 0
        with engine.begin() as conn:  # the owning tenant's context sees its rows
            conn.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": str(env.tenant)})
            assert conn.execute(text("SELECT count(*) FROM cmo_generation")).scalar_one() == 1
            assert conn.execute(text("SELECT count(*) FROM metered_event")).scalar_one() == 1
        with pytest.raises(Exception):  # the app role cannot rewrite or delete a delivered artefact (append-only)
            with engine.begin() as conn:
                conn.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": str(env.tenant)})
                conn.execute(text("UPDATE cmo_generation SET status = 'FAILED'"))
        with pytest.raises(Exception):
            with engine.begin() as conn:
                conn.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": str(env.tenant)})
                conn.execute(text("DELETE FROM cmo_generation"))
    finally:
        engine.dispose()
