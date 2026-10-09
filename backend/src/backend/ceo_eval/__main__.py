"""CLI: `python -m backend.ceo_eval run|report ...` (see docs/evaluation/ceo-eval-baseline.md for how a run is made)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from backend.ceo_eval import report, runner
from backend.ceo_eval.model import OllamaEvalModel

DEFAULT_OUT = Path(__file__).resolve().parents[4] / "docs" / "evaluation" / "ceo-runs"


def _run(args: argparse.Namespace) -> int:
    run_id = args.run_id or runner.new_run_id()
    out_dir = Path(args.out)
    record: dict = {"run_id": run_id, "started": run_id, "args": vars(args), "environment": runner.environment(), **runner.provenance_block(), "models": {}}
    path = out_dir / f"{run_id}.json"
    suites = tuple(args.suites)

    def log(msg: str) -> None:
        print(msg, flush=True)

    if args.merge_into:  # add to an existing record (e.g. a DB-latency-only run after the model runs)
        record = json.loads(Path(args.merge_into).read_text(encoding="utf-8"))
        path = Path(args.merge_into)
        out_dir, run_id = path.parent, record["run_id"]
    for name in args.models:
        runner.unload_all()
        model = OllamaEvalModel(name, think=False if args.think == "off" else (True if args.think == "on" else None), num_ctx=args.num_ctx)
        log(f"== {name}")
        entry: dict = {}
        if "probe" in suites:
            entry["cold_and_cache_probe"] = runner.probe_cold_and_cache(model)
            log("  probe done")
        entry.update(runner.run_model(
            model, suites=[s for s in suites if s in ("classifier", "composer")], constrained=not args.unconstrained,
            classifier_limit=args.classifier_limit, composer_limit=args.composer_limit, holdout_only=args.holdout_only, per_metric=args.per_metric, progress=log,
        ))
        record["models"][name] = entry
        runner.write_record(record, out_dir)  # incremental: a crash or pause keeps every finished model
        log(f"  wrote {path}")
    if "latency" in suites:
        if not args.db_ok:
            print("refusing the DB latency suite without --db-ok (it creates and purges a synthetic tenant)", file=sys.stderr)
            return 2
        from backend.ceo_eval import latency_db

        log(f"== DB latency against {latency_db.describe_target()}")
        record["db_latency"] = latency_db.run(repeat=args.repeat)
        runner.write_record(record, out_dir)
    runner.unload_all()
    log(f"run {run_id} complete: {path}")
    return 0


def _report(args: argparse.Namespace) -> int:
    record = json.loads(Path(args.record).read_text(encoding="utf-8"))
    Path(args.output).write_text(report.render(record), encoding="utf-8")
    print(f"wrote {args.output}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m backend.ceo_eval")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--models", nargs="*", default=[])
    r.add_argument("--suites", nargs="+", default=["probe", "classifier", "composer"], choices=["probe", "classifier", "composer", "latency"])
    r.add_argument("--out", default=str(DEFAULT_OUT))
    r.add_argument("--run-id")
    r.add_argument("--think", choices=["off", "on", "default"], default="off")
    r.add_argument("--num-ctx", type=int, default=4096)
    r.add_argument("--unconstrained", action="store_true", help="classifier without schema-constrained decoding")
    r.add_argument("--holdout-only", action="store_true", help="run only the hold-out split (the approved criteria are measured there)")
    r.add_argument("--per-metric", type=int, help="with --holdout-only: this many hold-out cases for each metric (the minimum is 100)")
    r.add_argument("--classifier-limit", type=int)
    r.add_argument("--composer-limit", type=int)
    r.add_argument("--repeat", type=int, default=20)
    r.add_argument("--db-ok", action="store_true")
    r.add_argument("--merge-into", help="path of an existing run record to extend")
    r.set_defaults(fn=_run)
    g = sub.add_parser("report")
    g.add_argument("record")
    g.add_argument("--output", required=True)
    g.set_defaults(fn=_report)
    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
