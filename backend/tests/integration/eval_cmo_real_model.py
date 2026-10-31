"""CMO real-model quality evaluation (B2). NOT part of the suite (the file name does not match `test_*.py`; run it by path with METRION_REAL_MODEL_EVAL=1 and a local Ollama).

Several controlled, non-production products x several runs, on a scratch database, a real local model through the same `OllamaLlmProvider` the product uses. Only DETERMINISTIC checks judge
what comes back (no second model grades the first). Each case appends one JSON line (outcome, failure categories from the product's own validator, the checks below, timings) to the file named
by METRION_EVAL_OUT; `summarise()` turns the lines into a pass rate and a failure-category table. It records; it asserts nothing about quality.

    METRION_REAL_MODEL_EVAL=1 METRION_EVAL_RUNS=2 METRION_EVAL_RETRIES=1 METRION_EVAL_OUT=eval.jsonl pytest backend/tests/integration/eval_cmo_real_model.py -s
"""

from __future__ import annotations

import json
import os
import re
import time
from collections import Counter

import pytest

import slim_cmo.generation.copy as gcopy
from backend.services import cmo_runtime
from backend.services.cmo_runtime import CmoRuntime
from slim_cmo.providers.ollama import OllamaLlmProvider
from slim_cmo.repositories.postgres_store import PostgresGenerationStore
from slim_cmo.service.approve import ApprovalService
from slim_cmo.service.catalog import CatalogService
from slim_cmo.service.generate import GenerationService
from slim_cmo.service.models import NewFact
from slim_cmo.types import ConstraintRowKind as K
from slim_cmo.types import SellerFactType as F
from tests.integration.test_cmo_api import _erase_cmo_rows, ctx_engine, env, fake_clerk  # noqa: F401
from tests.integration.test_cmo_m6_integration import AMAZON, FLAG_ON, ru_env

pytestmark = pytest.mark.skipif(os.environ.get("METRION_REAL_MODEL_EVAL") != "1", reason="real-model evaluation is run on request")

# name, sku slug, brand, facts (name -> value), the seller's own title, one extra confirmed detail used for the rewrite step
PRODUCTS = [
    ("AquaNest 1 Litre Stainless Steel Water Bottle", "aquanest-1-litre", "AquaNest", {"Size": "1 litre", "Material": "stainless steel", "Color": "silver"}, "AquaNest 1 Litre Stainless Steel Water Bottle", ("Opening", "wide")),
    ("BrightBeam LED Desk Lamp", "brightbeam-led-desk-lamp", "BrightBeam", {"Size": "40 cm", "Material": "plastic", "Color": "white"}, "BrightBeam LED Desk Lamp", ("Light mode", "three brightness levels")),
    ("CottonCo Men's Round Neck T-Shirt", "cottonco-mens-round-neck-t-shirt", "CottonCo", {"Size": "L", "Material": "cotton", "Color": "navy blue"}, "CottonCo Men's Round Neck T-Shirt", ("Neck", "round")),
]
RUNS = int(os.environ.get("METRION_EVAL_RUNS", "1"))
CASES = [(p, r) for p in range(len(PRODUCTS)) for r in range(RUNS)]

# Words that name an activity, place, occasion or kind of user; and claim words the seller never gave. Any hit in generated text is an unsupported-claim finding (a RECORD, not a verdict on the product).
USE_CASE = ("gym", "commut", "office", "travel", "school", "college", "hik", "trek", "camp", "outdoor", "picnic", "sport", "athlet", "workout", "yoga", "kids", "children", "student", "baby", "party", "wedding", "festive", "gift")
CLAIMS = ("insulated", "vacuum", "leakproof", "leak-proof", "bpa", "dishwasher", "warranty", "24 hours", "12 hours", "waterproof", "energy", "eye-care", "flicker", "100%", "best", "premium quality", "high-quality", "high quality", "guarantee", "certified", "eco-friendly")
SOFT = ("sturdy", "easy to clean", "easy to carry", "comfortable", "breathable", "soft", "durable", "long-lasting", "stylish", "sleek", "elegant", "sophisticated", "modern", "versatile", "perfect", "ideal", "reliable")
NUM = re.compile(r"\b\d+(?:\.\d+)?\b")


def runtime(model: str, timeout: int = 420):
    store = PostgresGenerationStore()
    inner = OllamaLlmProvider(host=os.environ.get("CMO_OLLAMA_HOST", "http://localhost:11434"), timeout_seconds=timeout, think=False)

    class Recording:
        calls = 0
        answers: list[str] = []

        def complete(self, *, model: str, prompt: str) -> str:
            Recording.calls += 1
            answer = inner.complete(model=model, prompt=prompt)
            Recording.answers.append(answer[:1800])
            return answer

    clock = cmo_runtime.utc_now
    kinds = frozenset({K.TEST_FIXTURE})
    return CmoRuntime(store=store, generation=GenerationService(store, Recording(), model=model, clock=clock, accepted_row_kinds=kinds),
                      approvals=ApprovalService(store, clock=clock, accepted_row_kinds=kinds), catalog=CatalogService(store), clock=clock), Recording


def hits(words: tuple[str, ...], blob: str) -> list[str]:
    return [w for w in words if w in blob]


def scan(texts: list[str], fact_blob: str) -> dict:
    blob = " ".join(texts).casefold()
    fb = fact_blob.casefold()
    return {"use_case_words": [w for w in hits(USE_CASE, blob) if w not in fb], "claim_words": [w for w in hits(CLAIMS, blob) if w not in fb], "soft_filler_words": hits(SOFT, blob),
            "numbers_not_in_facts": sorted({n for n in NUM.findall(blob) if n not in fb})}


@pytest.mark.parametrize("pi,run", CASES)
def test_real_model_case(env, monkeypatch, pi, run):
    name, sku, brand, facts, title, (extra_name, extra_value) = PRODUCTS[pi]
    model = os.environ.get("METRION_EVAL_MODEL", "qwen3:8b")
    retries = int(os.environ.get("METRION_EVAL_RETRIES", "1"))
    rt, rec = runtime(model)
    monkeypatch.setattr(cmo_runtime, "build_runtime", lambda **_kw: rt)
    spy: list[list[str]] = []
    orig = gcopy.run_attempts

    def run_spy(**kw):
        log = orig(**kw)
        spy.append(sorted(log.violations))
        return log

    monkeypatch.setattr(gcopy, "run_attempts", run_spy)
    ru_env(env, config={**FLAG_ON, "internal_retry_bound": retries})
    rows = [NewFact(F.ATTRIBUTE, sku, "product_name", name), NewFact(F.BRAND, sku, None, brand), *[NewFact(F.ATTRIBUTE, sku, k, v) for k, v in facts.items()]]
    env.runtime.store.save_facts(env.tenant, env.user_id, rows)
    fact_blob = " ".join([name, brand, title, *facts.values(), *facts.keys(), extra_name, extra_value])
    out: dict = {"product": name, "run": run, "model": model, "retries": retries}
    t0 = time.time()
    r = env.post("full-listing", {"request_key": f"ev-{pi}-{run}", "sku": sku, "product_name": name, "brand": brand, "marketplace": AMAZON, "seller_title": title})
    j = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    card = j.get("card") or {}
    secs = card.get("sections") or {}
    out.update({"http": r.status_code, "status": j.get("status"), "seconds": round(time.time() - t0), "model_calls": rec.calls, "validator_violations_by_call": spy,
                "units_billed": j.get("unitsBilled"), "listing_rows_saved": env.n("cmo_generation", "output_type = 'LISTING_COPY' AND status = 'COMPLETE'"),
                "failed_rows_with_text": env.n("cmo_generation", "status = 'FAILED' AND output_text IS NOT NULL")})
    if not secs:
        out["raw_answers"] = list(rec.answers)
    if secs:
        texts = [secs.get("title", ""), *(secs.get("bullets") or []), secs.get("description", ""), *(secs.get("keywords") or []), *(secs.get("backend_terms") or [])]
        out.update({"passed": True, "audit_verdict": (card.get("audit") or {}).get("verdict"), "audit_finding_codes": sorted({f["code"] for f in (card.get("audit") or {}).get("findings", [])}),
                    "checks": scan(texts, fact_blob), "sections": secs,
                    "keywords_all_placed": all(c.get("placed") for c in (card.get("keywordMap") or {}).get("candidates", []))})
        env.runtime.store.save_facts(env.tenant, env.user_id, [NewFact(F.ATTRIBUTE, sku, extra_name, extra_value)])
        t1 = time.time()
        rw = env.post("listing-rewrite", {"request_key": f"evrw-{pi}-{run}", "generation_id": card["generationId"], "target": "bullet", "bullet_number": 2, "topic": extra_value, "sku": sku})
        new = ((rw.json() if rw.status_code == 200 else {}).get("card") or {}).get("sections") or {}
        out["rewrite"] = {"http": rw.status_code, "seconds": round(time.time() - t1), "after": (new.get("bullets") or [None, None])[1],
                          "others_unchanged": bool(new) and [b for i, b in enumerate(new.get("bullets", [])) if i != 1] == [b for i, b in enumerate(secs.get("bullets", [])) if i != 1],
                          "checks": scan([(new.get("bullets") or ["", ""])[1] or ""], fact_blob), "error": None if new else rw.text[:300]}
        bad = env.post("listing-rewrite", {"request_key": f"evrw2-{pi}-{run}", "generation_id": card["generationId"], "target": "bullet", "bullet_number": 2, "topic": "keeps drinks cold for 24 hours", "sku": sku})
        out["rewrite_unconfirmed_topic_refused"] = bad.status_code == 422 and "TOPIC_NOT_CONFIRMED" in bad.text
    else:
        out["passed"] = False
        out["failure_reason"] = (j.get("copy") or {}).get("artefacts", [{}])[0].get("failure", {}).get("reason") if j else r.text[:300]
    path = os.environ.get("METRION_EVAL_OUT")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(out, default=str) + "\n")


def summarise(path: str) -> dict:
    rows = [json.loads(x) for x in open(path, encoding="utf-8") if x.strip()]
    passed = [r for r in rows if r.get("passed")]
    cats = Counter(v for r in rows if not r.get("passed") for call in r.get("validator_violations_by_call", []) for v in call)
    return {"cases": len(rows), "passed": len(passed), "pass_rate": f"{len(passed)}/{len(rows)}", "failure_categories": dict(cats),
            "unsupported_use_case_words": Counter(w for r in passed for w in r["checks"]["use_case_words"]), "claim_words": Counter(w for r in passed for w in r["checks"]["claim_words"]),
            "soft_filler": Counter(w for r in passed for w in r["checks"]["soft_filler_words"]), "numbers_not_in_facts": [r["checks"]["numbers_not_in_facts"] for r in passed],
            "rewrite_ok": sum(1 for r in passed if r.get("rewrite", {}).get("http") == 200 and r["rewrite"]["others_unchanged"]), "unconfirmed_topic_refused": sum(1 for r in passed if r.get("rewrite_unconfirmed_topic_refused")),
            "saved_failed_text_rows": sum(r.get("failed_rows_with_text", 0) for r in rows), "billed_on_failure": sum(int(r.get("units_billed") or 0) for r in rows if not r.get("passed"))}
