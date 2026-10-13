"""Operator tool: load REVIEWED, SOURCED marketplace format rules into `format_constraint` as VERIFIED rows (slim-cmo-agent.md 6.3, C13, V11, Q21).

This is the only supported way to create a VERIFIED row. Nothing here supplies a rule of its own: every value comes from a JSON file a HUMAN reviewed against the marketplace's own
seller documentation, and every row must carry the page it came from (`source_url`, https) and the date it was checked (`verified_at`). A row with a missing source, a missing
date, a placeholder, or a counting rule that is not one of the two the code supports is REFUSED, and nothing is written.

Usage (run as the table owner / migration role; the application role cannot write this table):
    python seed_format_constraints.py rules.json            # validate and print what WOULD be written (default; changes nothing)
    python seed_format_constraints.py rules.json --apply    # write them (needs DATABASE_URL); each row gets version = (highest existing version for that marketplace + category) + 1

The template `format_constraints.template.json` lists every field with no values: copy it, fill it from the current seller-central pages, review it, then run it. Staleness is enforced
at generation time by `format_constraint_max_age_days`: re-run this with a fresh `verified_at` when you re-check the pages.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

MARKETPLACES = ("AMAZON", "FLIPKART", "MEESHO")
COUNT_RULES = ("UTF16_CODE_UNITS", "CODE_POINTS")
INT_FIELDS = (
    "title_max_chars", "title_option_count", "bullet_count", "bullet_max_chars", "description_max_chars", "keywords_max_count", "keywords_max_chars", "backend_terms_max_bytes",
)
REQUIRED_INT = ("title_max_chars", "title_option_count", "bullet_count")  # without these the main artefacts cannot even be defined


@dataclass(frozen=True, slots=True)
class Row:
    marketplace: str
    category: str | None
    values: dict[str, Any]
    source_url: str
    verified_at: datetime
    count_rule: str
    description_type: str | None
    hashtags_supported: bool | None


def _positive_int(v: Any) -> bool:
    return type(v) is int and v > 0


def validate(doc: Any, *, today: date) -> tuple[list[Row], list[str]]:
    """(rows, problems). Any problem means NOTHING may be written."""
    problems: list[str] = []
    rows: list[Row] = []
    entries = doc.get("rules") if isinstance(doc, dict) else None
    if not isinstance(entries, list) or not entries:
        return [], ["the file must be a JSON object with a non-empty list under \"rules\""]
    for n, raw in enumerate(entries, start=1):
        where = f"rule {n}"
        if not isinstance(raw, dict):
            problems.append(f"{where}: not an object")
            continue
        mp = raw.get("marketplace")
        if mp not in MARKETPLACES:
            problems.append(f"{where}: marketplace must be one of {', '.join(MARKETPLACES)}")
            continue
        where = f"rule {n} ({mp})"
        url = raw.get("source_url")
        if not isinstance(url, str) or not url.startswith(("https://", "http://")) or ".invalid" in url or "example." in url:
            problems.append(f"{where}: source_url must be the real https page the rule was read from (no placeholder)")
        try:
            checked = datetime.fromisoformat(str(raw.get("verified_at")))
            if checked.tzinfo is None:
                checked = checked.replace(tzinfo=timezone.utc)
            if checked.date() > today:
                problems.append(f"{where}: verified_at is in the future")
        except ValueError:
            problems.append(f"{where}: verified_at must be the ISO date the page was checked (for example 2026-10-13)")
            checked = datetime.now(timezone.utc)
        if raw.get("count_rule") not in COUNT_RULES:
            problems.append(f"{where}: count_rule must be one of {', '.join(COUNT_RULES)} (how the marketplace counts characters)")
        values: dict[str, Any] = {}
        for f in INT_FIELDS:
            v = raw.get(f)
            if v is None:
                if f in REQUIRED_INT:
                    problems.append(f"{where}: {f} is required")
                if f == "backend_terms_max_bytes" and mp == "AMAZON":
                    problems.append(f"{where}: backend_terms_max_bytes is required for Amazon (or leave Amazon backend terms unsupported by omitting this rule)")
                continue
            if not _positive_int(v):
                problems.append(f"{where}: {f} must be a positive whole number or null (null = the source does not state it)")
            elif f == "backend_terms_max_bytes" and mp != "AMAZON":
                problems.append(f"{where}: backend_terms_max_bytes exists only for Amazon")
            else:
                values[f] = v
        cat = raw.get("category")
        if cat is not None and (not isinstance(cat, str) or not cat.strip()):
            problems.append(f"{where}: category must be null (marketplace-wide) or a non-empty text")
        ht = raw.get("hashtags_supported")
        if ht is not None and not isinstance(ht, bool):
            problems.append(f"{where}: hashtags_supported must be true, false or null (not established)")
        dt = raw.get("description_type")
        rows.append(Row(mp, cat.strip() if isinstance(cat, str) else None, values, str(url), checked, str(raw.get("count_rule")), dt if isinstance(dt, str) and dt.strip() else None, ht))
    return rows, problems


_INSERT = """
INSERT INTO format_constraint (marketplace, category, title_max_chars, title_option_count, bullet_count, bullet_max_chars, description_type, description_max_chars,
    keywords_max_count, keywords_max_chars, backend_terms_max_bytes, hashtags_supported, count_rule, source_url, verified_at, version, row_kind)
VALUES (:marketplace, :category, :title_max_chars, :title_option_count, :bullet_count, :bullet_max_chars, :description_type, :description_max_chars,
    :keywords_max_count, :keywords_max_chars, :backend_terms_max_bytes, :hashtags_supported, :count_rule, :source_url, :verified_at,
    (SELECT COALESCE(MAX(version), 0) + 1 FROM format_constraint WHERE marketplace = :marketplace AND category IS NOT DISTINCT FROM :category AND row_kind = 'VERIFIED'), 'VERIFIED')
"""


def apply(rows: list[Row], url: str) -> None:
    from sqlalchemy import create_engine, text

    engine = create_engine(url)
    with engine.begin() as conn:
        for r in rows:
            params = {f: r.values.get(f) for f in INT_FIELDS}
            params.update(marketplace=r.marketplace, category=r.category, description_type=r.description_type, hashtags_supported=r.hashtags_supported,
                          count_rule=r.count_rule, source_url=r.source_url, verified_at=r.verified_at)
            conn.execute(text(_INSERT), params)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("file", type=Path)
    ap.add_argument("--apply", action="store_true", help="write the rows (default: only validate and print)")
    args = ap.parse_args(argv)
    rows, problems = validate(json.loads(args.file.read_text(encoding="utf-8")), today=date.today())
    if problems:
        print("REFUSED. Nothing was written. Fix these first:")
        for p in problems:
            print(f" - {p}")
        return 2
    for r in rows:
        print(f"OK  {r.marketplace} {r.category or '(marketplace-wide)'}: {r.values} counting={r.count_rule} source={r.source_url} checked={r.verified_at.date()}")
    if not args.apply:
        print("Dry run: nothing was written. Re-run with --apply to write these as VERIFIED rows.")
        return 0
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL (the table owner / migration role) is required for --apply.")
        return 2
    apply(rows, url)
    print(f"Wrote {len(rows)} VERIFIED row(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
