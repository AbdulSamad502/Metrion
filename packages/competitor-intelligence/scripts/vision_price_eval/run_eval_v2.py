"""Run a REAL local vision model over the v2 evaluation set and record the raw replies (resumable). Scoring is a separate, offline step (`score_v2.py`), so a change to the parsing or
validation code can be re-scored on the SAME raw replies without another model run.

Local only: it talks to the Ollama host you give it (default http://localhost:11434). Nothing here can reach a hosted provider.

    python run_eval_v2.py --images <dir> --label baseline --model llava:latest --prompt-file prompt_baseline.txt
    python run_eval_v2.py --images <dir> --label candidate --model llava:latest --prompt-file <new prompt>

Output: <images>/raw_<label>.jsonl, one record per image: file, raw reply, Ollama's own stage timings, the prompt's sha256, and `error` when the call failed.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sys
import time
from pathlib import Path

import httpx


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--images", required=True, type=Path)
    ap.add_argument("--label", required=True)
    ap.add_argument("--model", default=os.environ.get("CI_VISION_MODEL", "llava:latest"))
    ap.add_argument("--host", default=os.environ.get("OLLAMA_HOST", "http://localhost:11434"))
    ap.add_argument("--prompt-file", type=Path, default=None, help="default: the production prompt as it is in the working tree")
    ap.add_argument("--options", default=None, help='JSON for Ollama "options", e.g. {"temperature": 0}')
    ap.add_argument("--timeout", type=float, default=900.0)
    ap.add_argument("--only", default=None, help="comma-separated manifest indexes to run (default: all)")
    args = ap.parse_args()

    if args.prompt_file is not None:
        prompt = args.prompt_file.read_text(encoding="utf-8")
    else:
        from competitor_intelligence.evidence import vision_extractor as ve

        prompt = ve._PROMPT
    sha = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]
    manifest = json.loads((args.images / "manifest.json").read_text(encoding="utf-8-sig"))
    wanted = {int(i) for i in args.only.split(",")} if args.only else None
    out = args.images / f"raw_{args.label}.jsonl"
    done = {json.loads(line)["file"] for line in out.read_text(encoding="utf-8").splitlines()} if out.exists() else set()
    extra = {"options": json.loads(args.options)} if args.options else {}

    for index, m in enumerate(manifest):
        if (wanted is not None and index not in wanted) or m["file"] in done:
            continue
        b64 = base64.b64encode((args.images / m["file"]).read_bytes()).decode()
        payload = {"model": args.model, "prompt": prompt, "images": [b64], "stream": False, **extra}
        started = time.perf_counter()
        rec: dict = {"file": m["file"], "model": args.model, "prompt_sha": sha, "options": extra.get("options")}
        try:
            r = httpx.post(f"{args.host}/api/generate", json=payload, timeout=args.timeout)
            r.raise_for_status()
            body = r.json()
            rec.update(raw=body.get("response", ""), prompt_tokens=body.get("prompt_eval_count"), output_tokens=body.get("eval_count"),
                       prompt_eval_s=round(body.get("prompt_eval_duration", 0) / 1e9, 1), generate_s=round(body.get("eval_duration", 0) / 1e9, 1))
        except httpx.HTTPError as exc:
            rec.update(raw=None, error=f"{type(exc).__name__}: {exc}"[:200])
        rec["wall_s"] = round(time.perf_counter() - started, 1)
        with out.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        sys.stdout.write(f"{index:02d} {m['file']} wall={rec['wall_s']}s {'ERROR ' + rec['error'] if rec.get('error') else 'ok'}\n")
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
