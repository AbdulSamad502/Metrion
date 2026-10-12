"""Score recorded raw model replies against the v2 manifest, offline and reproducibly.

Scoring rules (fixed, stated here so a number can be reproduced by anyone):
  For every (image, field) the manifest says what is VISIBLE (a value) or NOT visible (None). The pipeline reports a value or nothing. The outcome is exactly one of
    CORRECT           visible and reported value equals the truth (exact; strings compared case-insensitively with whitespace collapsed; prices are integer paise, exact)
    WRONG             visible, reported, different
    MISSED            visible, nothing reported
    CORRECT_ABSENT    not visible, nothing reported
    FALSE_EXTRACTION  not visible, a value reported (an unsupported value)
  A plausible guess is WRONG or FALSE_EXTRACTION, never correct. The model's own confidence is never used. An image whose reply is unusable counts as `extraction_failed` and reports
  nothing (what production does: the screenshot contributes no fields).

Pipelines:  `baseline`  = the extractor exactly as it was when this campaign began (legacy_vision_extractor_snapshot.py)
            `current`   = the production extractor as it is in the working tree now (competitor_intelligence.evidence.vision_extractor)

    python score_v2.py --images <dir> --raw baseline --pipeline baseline
    python score_v2.py --images <dir> --raw candidate --pipeline current
"""

from __future__ import annotations

import argparse
import collections
import importlib.util
import json
import re
import sys
from pathlib import Path

FIELDS = ("title", "listed_price_paise", "mrp_paise", "visible_discount_paise", "rating", "rating_count", "availability", "seller_name", "description", "observed_category", "bullets")
HERE = Path(__file__).resolve().parent


def load_pipeline(name: str):
    if name == "baseline":
        spec = importlib.util.spec_from_file_location("legacy_ve", HERE / "legacy_vision_extractor_snapshot.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules["legacy_ve"] = mod  # a dataclass in the module looks itself up here
        spec.loader.exec_module(mod)
    else:
        from competitor_intelligence.evidence import vision_extractor as mod

    def parse(raw: str | None):
        """(fields dict | None when the screenshot is an extraction failure)."""
        if raw is None:
            return None
        if hasattr(mod, "fields_from_reply"):
            result = mod.fields_from_reply(raw)
            return None if result is None else {f.field_name: f.value for f in result}
        parsed = mod._extract_json_object(raw)
        if parsed is None:
            return None
        fields = mod._fields_from_model_json(parsed)
        return {f.field_name: f.value for f in fields} if fields else None

    return parse


def norm(v):
    return re.sub(r"\s+", " ", v).strip().casefold() if isinstance(v, str) else v


def outcome(expected, got) -> str:
    if expected is None:
        return "CORRECT_ABSENT" if got is None else "FALSE_EXTRACTION"
    if got is None:
        return "MISSED"
    if isinstance(expected, list):
        return "CORRECT" if [norm(x) for x in expected] == [norm(x) for x in got] else "WRONG"
    return "CORRECT" if norm(expected) == norm(got) else "WRONG"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--images", required=True, type=Path)
    ap.add_argument("--raw", required=True, help="label of raw_<label>.jsonl")
    ap.add_argument("--pipeline", choices=("baseline", "current"), default="current")
    ap.add_argument("--json", type=Path, default=None, help="write the full summary here")
    ap.add_argument("--subset", default=None, help="comma-separated manifest indexes: score ONLY these images (a subset evaluation, reported as such)")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    all_items = json.loads((args.images / "manifest.json").read_text(encoding="utf-8-sig"))
    keep = {all_items[int(i)]["file"] for i in args.subset.split(",")} if args.subset else None
    manifest = {m["file"]: m for m in all_items if keep is None or m["file"] in keep}
    raw = {r["file"]: r for r in (json.loads(line) for line in (args.images / f"raw_{args.raw}.jsonl").read_text(encoding="utf-8").splitlines()) if r["file"] in manifest}
    parse = load_pipeline(args.pipeline)
    legacy_parse = load_pipeline("baseline")  # the extractor as it was at the start: used only to see what validation removed
    suppression: list[tuple] = []

    per_image: dict[str, dict[str, str]] = {}
    failed: list[str] = []
    wrong_price_rows: list[tuple] = []
    for file, rec in raw.items():
        m = manifest[file]
        got = parse(rec.get("raw"))
        if got is None:
            failed.append(file)
            got = {}
        per_image[file] = {f: outcome(m["expected"][f], got.get(f)) for f in FIELDS}
        if args.pipeline == "current":
            before = legacy_parse(rec.get("raw")) or {}
            for name, value in before.items():
                if name not in got:
                    truth = m["expected"][name]
                    kind = "SUPPRESSED_CORRECT" if (truth is not None and outcome(truth, value) == "CORRECT") else ("SUPPRESSED_UNSUPPORTED" if truth is None else "SUPPRESSED_WRONG")
                    suppression.append((file, name, value, truth, kind))
        if per_image[file]["listed_price_paise"] in ("WRONG", "FALSE_EXTRACTION"):
            wrong_price_rows.append((file, m["price_text"], m["expected"]["listed_price_paise"], got.get("listed_price_paise"), m["tags"]))

    def count(field, kinds, tag=None):
        rows = [f for f in per_image if tag is None or tag in manifest[f]["tags"]]
        return sum(per_image[f][field] in kinds for f in rows), len(rows)

    summary: dict[str, object] = {"subset": sorted(manifest) if keep else "ALL", "pipeline": args.pipeline, "raw": args.raw, "images": len(per_image), "extraction_failed": [len(failed), len(per_image)]}
    price_visible = [f for f in per_image if manifest[f]["expected"]["listed_price_paise"] is not None]
    price_absent = [f for f in per_image if manifest[f]["expected"]["listed_price_paise"] is None]
    summary["price_exact_visible"] = [sum(per_image[f]["listed_price_paise"] == "CORRECT" for f in price_visible), len(price_visible)]
    summary["price_wrong_visible"] = [sum(per_image[f]["listed_price_paise"] == "WRONG" for f in price_visible), len(price_visible)]
    summary["price_missed_visible"] = [sum(per_image[f]["listed_price_paise"] == "MISSED" for f in price_visible), len(price_visible)]
    summary["price_unreadable_handled_as_unknown"] = [sum(per_image[f]["listed_price_paise"] == "CORRECT_ABSENT" for f in price_absent), len(price_absent)]
    reported = [f for f in per_image if per_image[f]["listed_price_paise"] in ("CORRECT", "WRONG", "FALSE_EXTRACTION")]
    summary["price_precision_of_reported"] = [sum(per_image[f]["listed_price_paise"] == "CORRECT" for f in reported), len(reported)]
    by_tag: dict[str, list[int]] = {}
    for tag in sorted({t for m in manifest.values() for t in m["tags"]}):
        c, n = count("listed_price_paise", ("CORRECT", "CORRECT_ABSENT"), tag)
        by_tag[tag] = [c, n]
    summary["price_correct_by_tag"] = by_tag
    summary["fields"] = {}
    for fld in FIELDS:
        vis = [f for f in per_image if manifest[f]["expected"][fld] is not None]
        absent = [f for f in per_image if manifest[f]["expected"][fld] is None]
        summary["fields"][fld] = {
            "exact_when_visible": [sum(per_image[f][fld] == "CORRECT" for f in vis), len(vis)],
            "wrong_when_visible": [sum(per_image[f][fld] == "WRONG" for f in vis), len(vis)],
            "missed_when_visible": [sum(per_image[f][fld] == "MISSED" for f in vis), len(vis)],
            "false_extraction_when_absent": [sum(per_image[f][fld] == "FALSE_EXTRACTION" for f in absent), len(absent)],
        }
    abs_total = sum(len([f for f in per_image if manifest[f]["expected"][fld] is None]) for fld in FIELDS)
    false_total = sum(per_image[f][fld] == "FALSE_EXTRACTION" for f in per_image for fld in FIELDS)
    summary["false_extraction_rate_all_absent_fields"] = [false_total, abs_total]
    summary["wrong_price_rows"] = wrong_price_rows

    print(json.dumps({k: v for k, v in summary.items() if k not in ("wrong_price_rows", "fields", "price_correct_by_tag")}, indent=1))
    print("\nprice exact by tag (correct incl. correct-unknown / n):", {k: f"{v[0]}/{v[1]}" for k, v in by_tag.items()})
    print("\nper field (exact/visible | wrong/visible | missed/visible | FALSE/absent):")
    for fld, d in summary["fields"].items():
        print(f"  {fld:24s} {d['exact_when_visible'][0]:>2}/{d['exact_when_visible'][1]:<2} | {d['wrong_when_visible'][0]:>2}/{d['wrong_when_visible'][1]:<2} | {d['missed_when_visible'][0]:>2}/{d['missed_when_visible'][1]:<2} | FALSE {d['false_extraction_when_absent'][0]}/{d['false_extraction_when_absent'][1]}")
    print(f"\nfalse extraction over ALL fields that are not visible: {false_total}/{abs_total}")
    print("\nwrong or unsupported prices:")
    for row in wrong_price_rows:
        print("  ", row)
    if args.pipeline == "current":
        kinds = collections.Counter(k for *_, k in suppression)
        print(f"\nvalues removed by validation relative to the original extractor: {len(suppression)} -> {dict(kinds)}")
        for row in suppression:
            if row[4] == "SUPPRESSED_CORRECT":
                print("   REMOVED A CORRECT VALUE:", row)
        summary["suppressed_by_validation"] = {"counts": dict(kinds), "rows": suppression}
    if args.json:
        args.json.write_text(json.dumps({**summary, "per_image": per_image}, indent=1, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
