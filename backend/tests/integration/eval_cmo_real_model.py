"""CMO real-model quality evaluation (B2). NOT part of the suite (the file name does not match `test_*.py`; run it by path with METRION_REAL_MODEL_EVAL=1 and a local Ollama).

A controlled, non-production product (the AquaNest fixture) on a scratch database, a real local model through the same `OllamaLlmProvider` the product uses, and ONLY deterministic checks on
what comes back (no second model judges the first). It writes the raw outputs and the check results to the JSON file named by METRION_EVAL_OUT. It asserts nothing about quality: it records."""

from __future__ import annotations

import json
import os
import re
import time

import pytest
from sqlalchemy import text

from backend.services import cmo_runtime
from backend.services.cmo_runtime import CmoRuntime
from slim_cmo.providers.ollama import OllamaLlmProvider
from slim_cmo.repositories.postgres_store import PostgresGenerationStore
from slim_cmo.service.approve import ApprovalService
from slim_cmo.service.catalog import CatalogService
from slim_cmo.service.generate import GenerationService
from slim_cmo.types import ConstraintRowKind as K
from tests.integration.test_cmo_api import _erase_cmo_rows, ctx_engine, env, fake_clerk  # noqa: F401
from tests.integration.test_cmo_m6_integration import AMAZON, NAME, SKU, TITLE, body, ru_env

pytestmark = pytest.mark.skipif(os.environ.get("METRION_REAL_MODEL_EVAL") != "1", reason="real-model evaluation is run on request")

# What the seller confirmed (the fixture's facts) and what they did NOT: any of these words appearing in generated text is an unsupported claim.
CONFIRMED = {"aquanest", "stainless", "steel", "silver", "1 litre", "1 l", "1l", "1000 ml", "water", "bottle"}
UNSUPPORTED = ("insulated", "insulation", "vacuum", "leakproof", "leak-proof", "leak proof", "bpa", "dishwasher", "warranty", "hot for", "cold for", "24 hours", "12 hours", "bpa-free", "double wall",
               "double-wall", "thermos", "100%", "best", "#1", "guarantee", "certified", "fda", "eco-friendly", "sports", "gym", "kids")
CAPACITY = re.compile(r"\b(\d+(?:\.\d+)?)\s*(?:l|litre|litres|liter|liters|ml)\b", re.IGNORECASE)


RAW: list[dict] = []


class Recording:
    """Records what the model was asked and answered (controlled, non-production data only)."""

    def __init__(self, inner) -> None:
        self.inner = inner

    def complete(self, *, model: str, prompt: str) -> str:
        answer = self.inner.complete(model=model, prompt=prompt)
        RAW.append({"prompt_tail": prompt[-1100:], "answer": answer[:2500]})
        return answer


def runtime(model: str, timeout: int = 420):
    store = PostgresGenerationStore()
    kinds = frozenset({K.TEST_FIXTURE})
    provider = OllamaLlmProvider(host=os.environ.get("CMO_OLLAMA_HOST", "http://localhost:11434"), timeout_seconds=timeout, think=False)
    provider = Recording(provider)
    clock = cmo_runtime.utc_now
    rt = CmoRuntime(store=store, generation=GenerationService(store, provider, model=model, clock=clock, accepted_row_kinds=kinds),
                    approvals=ApprovalService(store, clock=clock, accepted_row_kinds=kinds), catalog=CatalogService(store), clock=clock)
    return rt


def scan(label: str, texts: list[str]) -> dict:
    blob = " ".join(texts).casefold()
    bad = [w for w in UNSUPPORTED if w in blob]
    caps = {m.group(0).casefold() for m in CAPACITY.finditer(" ".join(texts))}
    wrong_caps = sorted(c for c in caps if not re.match(r"^(1\s*(l|litre|liter)|1000\s*ml)$", c))
    return {"label": label, "unsupported_claims_found": bad, "capacity_mentions": sorted(caps), "capacity_not_matching_fact": wrong_caps}


def test_real_model_evaluation(env, monkeypatch):
    model = os.environ.get("METRION_EVAL_MODEL", "qwen3:8b")
    out: dict = {"model": model, "product": NAME, "steps": {}}
    rt = runtime(model)
    out["raw_calls"] = RAW
    monkeypatch.setattr(cmo_runtime, "build_runtime", lambda **_kw: rt)
    env.provider = rt.generation.provider
    from tests.integration.test_cmo_m6_integration import FLAG_ON  # noqa: PLC0415

    retries = int(os.environ.get("METRION_EVAL_RETRIES", "0"))
    out["internal_retry_bound"] = retries
    ru_env(env, config={**FLAG_ON, "internal_retry_bound": retries})  # flag on, facts saved (brand, size, material, colour), no marketplace rule rows
    with env.engine.begin() as conn:  # a TEST_FIXTURE rule row so the standalone title action can run; the listing below runs without it (the unverified basis)
        conn.execute(text("INSERT INTO format_constraint (marketplace, title_max_chars, title_option_count, bullet_count, bullet_max_chars, description_type, description_max_chars, keywords_max_count, "
                          "keywords_max_chars, backend_terms_max_bytes, count_rule, source_url, verified_at, version, row_kind) VALUES ('AMAZON', 200, 3, 3, 200, 'plain', 900, 10, 40, 249, "
                          "'UTF16_CODE_UNITS', 'https://example.invalid/test-fixture', now(), 1, 'TEST_FIXTURE')"))
    t0 = time.time()
    r = env.post("title-sets", {"request_key": "ev-t", "sku": SKU, "product_name": NAME, "brand": "AquaNest", "marketplaces": [AMAZON]})
    titles = []
    if r.status_code == 200:
        for a in r.json().get("artefacts", []):
            titles = [o.get("text") or o.get("title") for o in (a.get("options") or [])] or titles
    out["steps"]["titles"] = {"http": r.status_code, "seconds": round(time.time() - t0), "options": titles, "raw": None if r.status_code == 200 else r.text[:400], "checks": scan("titles", [t for t in titles if t])}
    with env.engine.begin() as conn:
        conn.execute(text("UPDATE format_constraint SET verified_at = now() - interval '90 days' WHERE row_kind = 'TEST_FIXTURE'"))  # stale: the listing below runs on the unverified basis

    t0 = time.time()
    r = env.post("full-listing", body("ev-l"))
    j = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    card = j.get("card") or {}
    secs = card.get("sections") or {}
    out["steps"]["listing"] = {"http": r.status_code, "status": j.get("status"), "seconds": round(time.time() - t0), "sections": secs,
                               "audit_verdict": (card.get("audit") or {}).get("verdict"), "findings": [(f["code"], f["section"]) for f in (card.get("audit") or {}).get("findings", [])],
                               "keyword_map": {"placed": [(c["keyword"], c.get("where")) for c in (card.get("keywordMap") or {}).get("candidates", []) if c.get("placed")],
                                               "not_used": (card.get("keywordMap") or {}).get("notUsed")},
                               "checks": scan("listing", [secs.get("title", ""), *(secs.get("bullets") or []), secs.get("description", ""), *(secs.get("keywords") or []), *(secs.get("backend_terms") or [])]) if secs else None,
                               "error": None if secs else r.text[:3000]}
    if secs:
        from slim_cmo.service.models import NewFact  # noqa: PLC0415
        from slim_cmo.types import SellerFactType as F  # noqa: PLC0415

        env.runtime.store.save_facts(env.tenant, env.user_id, [NewFact(F.ATTRIBUTE, SKU, "Opening", "wide")])  # the seller confirms one more detail, then asks for a rewrite about it
        t0 = time.time()
        rw = env.post("listing-rewrite", {"request_key": "ev-rw", "generation_id": card["generationId"], "target": "bullet", "bullet_number": 2, "topic": "wide opening", "sku": SKU})
        rj = rw.json() if rw.headers.get("content-type", "").startswith("application/json") else {}
        new = (rj.get("card") or {}).get("sections") or {}
        out["steps"]["rewrite"] = {"http": rw.status_code, "seconds": round(time.time() - t0), "before": (secs.get("bullets") or [None, None])[1], "after": (new.get("bullets") or [None, None])[1],
                                   "other_bullets_unchanged": new.get("bullets", [None])[0:1] == secs.get("bullets", [None])[0:1] and new.get("bullets", [None, None, None])[2:] == secs.get("bullets", [None, None, None])[2:],
                                   "checks": scan("rewrite", [(new.get("bullets") or ["", ""])[1] or ""]), "error": None if new else rw.text[:400]}
        # a topic the seller has NOT confirmed must be refused before any model call
        rw2 = env.post("listing-rewrite", {"request_key": "ev-rw2", "generation_id": card["generationId"], "target": "bullet", "bullet_number": 2, "topic": "keeps drinks cold for 24 hours", "sku": SKU})
        out["steps"]["rewrite_unconfirmed_topic"] = {"http": rw2.status_code, "detail": rw2.text[:300]}
    path = os.environ.get("METRION_EVAL_OUT")
    if path:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(out, fh, indent=2, default=str)
    print(json.dumps(out, indent=2, default=str)[:6000])
