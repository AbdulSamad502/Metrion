"""Operator CLI: evaluate a vision provider/model/schema_version and record the result (spec §6.2.1).

    python scripts/vision_eval.py --provider ollama --model <model> --run-by "<your name>" \\
        --dataset <dir with manifest.json> --bar <bar.json>

This is the ONLY way a `vision_eval_run` is created. It REFUSES (exit 2, nothing written) without a named operator,
a labelled dataset and a complete bar file; there is no default for any of them. Required environment (no
defaults): DATABASE_URL (the admin role), CMO_VISION_OLLAMA_HOST, CMO_VISION_TIMEOUT_SECONDS, CMO_IMAGE_MAX_BYTES,
CMO_IMAGE_MAX_PIXELS, CMO_IMAGE_ALLOWED_TYPES. Local Ollama only. Evaluation images must be synthetic or
consented - never seller data.

The `--provider` and `--model` strings are the trust identity: production analyses cite a run only if they use the
EXACT same provider name, model and schema version.

Exit codes: 0 run recorded (see output for PASS/FAIL), 2 refused / not recorded.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from slim_cmo.evaluation.db import PostgresEvalWriter
from slim_cmo.evaluation.runner import EvalRefused, run_evaluation
from slim_cmo.imaging.normalize import ImageLimits
from slim_cmo.providers.ollama_vision import OllamaVisionProvider
from slim_cmo.vision.schema import SCHEMA_VERSION


def _need(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise EvalRefused(f"{name} is required (no default)")
    return value


def _need_int(name: str) -> int:
    raw = _need(name)
    if not raw.isdigit() or int(raw) < 1:
        raise EvalRefused(f"{name} must be a positive integer")
    return int(raw)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--provider", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--schema-version", default=SCHEMA_VERSION)
    ap.add_argument("--run-by", required=True, help="the named human operator running this evaluation")
    ap.add_argument("--dataset", type=Path, required=True)
    ap.add_argument("--bar", type=Path, required=True)
    args = ap.parse_args(argv)
    try:
        types = frozenset(t.strip().lower() for t in _need("CMO_IMAGE_ALLOWED_TYPES").split(",") if t.strip())
        limits = ImageLimits(_need_int("CMO_IMAGE_MAX_BYTES"), _need_int("CMO_IMAGE_MAX_PIXELS"), types)
        provider = OllamaVisionProvider(_need("CMO_VISION_OLLAMA_HOST"), _need_int("CMO_VISION_TIMEOUT_SECONDS"))
        report = run_evaluation(
            provider=provider, provider_name=args.provider, model=args.model, schema_version=args.schema_version,
            run_by=args.run_by, dataset_dir=args.dataset, bar_path=args.bar, limits=limits,
            writer=PostgresEvalWriter(_need("DATABASE_URL")), on_item=lambda i: print(f"  evaluating {i} ...", flush=True),
        )
    except EvalRefused as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    print(f"{'PASS' if report.passed else 'FAIL'}  run={report.run_id}  dataset={report.dataset_ref}  bar={report.bar_ref}")
    for failure in report.failures:
        print(f"  - {failure}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
