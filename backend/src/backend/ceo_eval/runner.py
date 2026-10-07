"""Evaluation run orchestration: classifier + composer suites over one or more models, per-stage LLM latency, JSON record.

A run records its own provenance (run id, prompt versions, fixture hashes, model digests, host) so a result is attributable
and a later model swap re-measures rather than assumes (spec §6.18). It sets NO pass/fail threshold anywhere.
"""

from __future__ import annotations

import hashlib
import json
import platform
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from backend.ceo_eval import classifier, composer, fixtures
from backend.ceo_eval.catalog import build_catalog
from backend.ceo_eval.model import EvalModel, OllamaEvalModel


def percentile(values: Sequence[int | float], p: float) -> float | None:
    """Nearest-rank percentile (no interpolation: with small n the honest statement is an observed value)."""
    xs = sorted(values)
    if not xs:
        return None
    rank = max(1, -(-int(p * len(xs)) // 100)) if p < 100 else len(xs)
    return float(xs[min(rank, len(xs)) - 1])


def stats(values: Sequence[int | float | None]) -> dict[str, Any]:
    xs = [v for v in values if v is not None]
    if not xs:
        return {"n": 0}
    return {"n": len(xs), "min": min(xs), "p50": percentile(xs, 50), "p95": percentile(xs, 95), "max": max(xs), "mean": round(sum(xs) / len(xs), 1)}


def llm_latency(results: Sequence[Any]) -> dict[str, Any]:
    """Per-call LLM metrics from already-scored results. `prompt_tokens` is the TOTAL prompt size (a cached prefix still counts);
    the cache effect shows in time to first token and in the cold/warm probe's prompt-eval time (spec §6.26 L4)."""
    return {
        "wall_ms": stats([r.wall_ms for r in results]),
        "ttft_ms": stats([r.ttft_ms for r in results]),
        "prompt_tokens_total": stats([r.prompt_tokens for r in results]),
        "output_tokens": stats([r.output_tokens for r in results]),
        "model_load_ms_when_nonzero": stats([r.load_ms for r in results if r.load_ms and r.load_ms > 100]),
        "calls_with_error": sum(1 for r in results if r.error),
    }


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def environment(host: str = "http://localhost:11434") -> dict[str, Any]:
    env: dict[str, Any] = {"python": platform.python_version(), "os": platform.platform(), "machine": platform.machine(), "processor": platform.processor()}
    try:
        env["ollama_version"] = httpx.get(f"{host}/api/version", timeout=5).json().get("version")
        env["models_installed"] = {
            m["name"]: {"digest": m["digest"][:12], "params": m["details"].get("parameter_size"), "quant": m["details"].get("quantization_level")}
            for m in httpx.get(f"{host}/api/tags", timeout=5).json().get("models", [])
        }
    except (httpx.HTTPError, KeyError, ValueError):
        env["ollama_version"] = None
    try:
        import os

        env["logical_cpus"] = os.cpu_count()
    except Exception:
        pass
    return env


def unload_all(host: str = "http://localhost:11434") -> list[str]:
    """Unloads every resident model so each model is measured alone (a CPU/RAM-bound host would otherwise skew latency)."""
    gone: list[str] = []
    try:
        for m in httpx.get(f"{host}/api/ps", timeout=5).json().get("models", []):
            httpx.post(f"{host}/api/generate", json={"model": m["name"], "keep_alive": 0}, timeout=60)
            gone.append(m["name"])
    except httpx.HTTPError:
        pass
    time.sleep(2)
    return gone


def new_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def run_model(
    model: EvalModel,
    *,
    suites: Sequence[str] = ("classifier", "composer"),
    constrained: bool = True,
    classifier_limit: int | None = None,
    composer_limit: int | None = None,
    progress: Callable[[str], None] = lambda s: None,
) -> dict[str, Any]:
    out: dict[str, Any] = {"model": model.name, "constrained_classifier": constrained}
    if "classifier" in suites:
        cases = fixtures.load_classifier_cases()
        by_id = {c.id: c for c in cases}
        scorable = [c for c in cases if c.pending is None]
        if classifier_limit:
            scorable = _spread(scorable, classifier_limit)
        t0 = time.perf_counter()
        results = classifier.run_cases(model, scorable, constrained=constrained, on_result=lambda r: progress(f"  classifier {r.case_id} {'ok' if r.ok else 'MISS'} {r.wall_ms}ms"))
        out["classifier"] = {
            "summary": classifier.summarize(results, by_id), "latency": llm_latency(results), "results": [asdict(r) for r in results],
            "pending_excluded": [{"id": c.id, "reason": c.pending} for c in cases if c.pending],
            "run_seconds": round(time.perf_counter() - t0, 1),
        }
    if "composer" in suites:
        ccases = fixtures.load_composer_cases()
        cby = {c.id: c for c in ccases}
        if composer_limit:
            ccases = _spread(ccases, composer_limit)
        t0 = time.perf_counter()
        cres = composer.run_cases(model, ccases, on_result=lambda r: progress(f"  composer {r.case_id} {'ok' if r.ok else 'MISS'} {r.wall_ms}ms"))
        out["composer"] = {
            "summary": composer.summarize(cres, cby), "latency": llm_latency(cres), "results": [asdict(r) for r in cres],
            "run_seconds": round(time.perf_counter() - t0, 1),
        }
    return out


def _spread(items: Sequence[Any], limit: int) -> list[Any]:
    """An evenly spread subset (keeps every category represented) for smoke runs."""
    if limit >= len(items):
        return list(items)
    step = len(items) / limit
    return [items[int(i * step)] for i in range(limit)]


def probe_cold_and_cache(model: OllamaEvalModel) -> dict[str, Any]:
    """Cold start and prefix-cache behaviour for the classifier prefix, measured directly:
    unload -> call (cold: load + full prefix prefill) -> same prefix + different message (prefix should be cached) -> a call on a
    different scenario's prefix (prefix not cached). Wall and server-reported figures."""
    cat_full, cat_nocfo = build_catalog("FULL"), build_catalog("NO_CFO")
    schema_full, schema_nocfo = classifier.output_schema(cat_full), classifier.output_schema(cat_nocfo)
    model.unload()
    time.sleep(2)
    probes = [
        ("cold: first call after unload", cat_full, "How did last month go?", schema_full),
        ("warm: same prefix, new message", cat_full, "Show me my open leaks", schema_full),
        ("warm: same prefix, new message (2)", cat_full, "Run a P&L for October", schema_full),
        ("different scenario prefix", cat_nocfo, "How did last month go?", schema_nocfo),
        ("back to first prefix", cat_full, "What's my goal again?", schema_full),
    ]
    rows = []
    for label, cat, msg, schema in probes:
        c = model.complete(classifier.build_prompt(cat, msg), schema=schema, max_output_tokens=160)
        rows.append({"probe": label, "wall_ms": c.wall_ms, "ttft_ms": c.ttft_ms, "load_ms": c.load_ms, "prompt_tokens_total": c.prompt_tokens,
                     "prompt_eval_ms": c.prompt_eval_ms, "output_tokens": c.output_tokens, "eval_ms": c.eval_ms})
    return {"model": model.name, "static_prefix_chars": len(classifier.static_prefix(cat_full)), "probes": rows}


def write_record(record: Mapping[str, Any], out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{record['run_id']}.json"
    path.write_text(json.dumps(record, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    return path


def provenance_block() -> dict[str, Any]:
    fx = fixtures.FIXTURE_DIR
    cl, co = fixtures.load_classifier_cases(), fixtures.load_composer_cases()
    return {
        "classifier_prompt_version": classifier.PROMPT_VERSION, "composer_prompt_version": composer.PROMPT_VERSION,
        "fixtures": {
            "classifier.jsonl": {"sha256_16": _sha(fx / "classifier.jsonl"), "cases": len(cl), "scored": sum(1 for c in cl if c.pending is None), "pending": sum(1 for c in cl if c.pending)},
            "composer.jsonl": {"sha256_16": _sha(fx / "composer.jsonl"), "cases": len(co)},
        },
    }
