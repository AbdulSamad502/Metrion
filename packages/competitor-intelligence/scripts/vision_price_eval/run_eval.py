"""Evaluate the production vision extraction against screenshots with KNOWN prices.

Sends each image to the local Ollama model with EXACTLY the production request (the extractor's
own prompt and parser), then records expected vs actual price/MRP, the stage timings Ollama
reports (model load / prompt evaluation / token generation), and a verdict per image.

Why this exists: spec Q7 / Q18 ("is the local vision model good enough?") can only be answered
on real screenshots of the listings a seller actually uploads. Run this on them.

    python run_eval.py --images <dir containing manifest.json + images> --condition default
    python run_eval.py --images <dir> --condition temp0 --start 9 --limit 21

`manifest.json` is a list of {"file", "style", "expected_price_rupees", "expected_mrp_rupees",
"rendered_price"} — `make_images.ps1` generates a synthetic one; for real screenshots write the
same shape by hand (expected_mrp_rupees may be null if none is shown).

Output: <images>/eval_<condition>.jsonl (one record per image, resumable) and a summary on stdout.
Read the numbers as what they are: a small sample on the images you gave it, not a population
accuracy.
"""

from __future__ import annotations

import argparse
import base64
import collections
import json
import os
import statistics
import sys
import time
from pathlib import Path

import httpx

from competitor_intelligence.evidence import vision_extractor as ve

CONDITIONS: dict[str, dict] = {
    "default": {},  # exactly what production sends
    "temp0": {"options": {"temperature": 0, "seed": 7}},
    "json_format": {"format": "json"},
    "num_predict400": {"options": {"num_predict": 400}},
}


def classify(expected: int, expected_mrp: int | None, got: int | None, parsed: object) -> str:
    if parsed is None:
        return "unparseable"
    if got is None:
        return "missing_price"
    if got == expected:
        return "correct"
    if expected_mrp is not None and got == expected_mrp:
        return "took_mrp_as_price"
    if str(expected).startswith(str(got)) or got * 10 == expected or got == expected * 10:
        return "digit_loss_or_gain"
    return "wrong_other"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--images", required=True, type=Path)
    ap.add_argument("--condition", default="default", choices=sorted(CONDITIONS))
    ap.add_argument("--model", default=os.environ.get("CI_VISION_MODEL", "llava"))
    ap.add_argument("--host", default=os.environ.get("OLLAMA_HOST", "http://localhost:11434"))
    ap.add_argument("--timeout", type=float, default=900.0)
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    manifest = json.loads((args.images / "manifest.json").read_text(encoding="utf-8-sig"))
    out = args.images / f"eval_{args.condition}.jsonl"
    done = {json.loads(line)["file"] for line in out.read_text(encoding="utf-8").splitlines()} if out.exists() else set()

    for m in manifest[args.start : args.limit]:
        if m["file"] in done:
            continue
        b64 = base64.b64encode((args.images / m["file"]).read_bytes()).decode()
        payload = {"model": args.model, "prompt": ve._PROMPT, "images": [b64], "stream": False, **CONDITIONS[args.condition]}
        t0 = time.perf_counter()
        r = httpx.post(f"{args.host}/api/generate", json=payload, timeout=args.timeout).json()
        wall = time.perf_counter() - t0
        parsed = ve._extract_json_object(r["response"])
        fields = {f.field_name: f.value for f in ve._fields_from_model_json(parsed)} if parsed else {}
        exp = m["expected_price_rupees"] * 100
        exp_mrp = m["expected_mrp_rupees"] * 100 if m.get("expected_mrp_rupees") is not None else None
        got, got_mrp = fields.get("listed_price_paise"), fields.get("mrp_paise")
        rec = {
            "file": m["file"], "style": m.get("style"), "rendered": m.get("rendered_price"),
            "expected_price": exp, "got_price": got, "verdict": classify(exp, exp_mrp, got, parsed),
            "expected_mrp": exp_mrp, "got_mrp": got_mrp, "wall_s": round(wall, 1),
            "load_s": round(r["load_duration"] / 1e9, 1), "prompt_tokens": r["prompt_eval_count"],
            "prompt_eval_s": round(r["prompt_eval_duration"] / 1e9, 1), "output_tokens": r["eval_count"],
            "generate_s": round(r["eval_duration"] / 1e9, 1), "raw": r["response"][:600],
        }
        with out.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(f"{m['file']:14s} expected={exp:>9} got={str(got):>9} {rec['verdict']:20s} wall={wall:6.1f}s", flush=True)

    rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    if rows:
        verdicts = collections.Counter(r["verdict"] for r in rows)
        print(f"\n[{args.condition}] n={len(rows)} price correct={verdicts['correct']}/{len(rows)} {dict(verdicts)}")
        print(f"latency per image: median {statistics.median(r['wall_s'] for r in rows):.0f}s "
              f"(min {min(r['wall_s'] for r in rows):.0f}, max {max(r['wall_s'] for r in rows):.0f}); "
              f"prompt eval median {statistics.median(r['prompt_eval_s'] for r in rows):.1f}s, "
              f"generation median {statistics.median(r['generate_s'] for r in rows):.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
