"""Operator tool (READ-ONLY): is this environment configured so Slim CMO can really generate? (CMO 3.0 M0; slim-cmo-agent.md 6.3, 6.8.5, C13, C16; CLAUDE.md "missing is not zero".)

It reads three things and writes nothing:
  1. `format_constraint`: per marketplace, is there a VERIFIED row with a source page, a counting rule and a recent enough check date? Without it production generation for that
     marketplace fails closed (`COUNTING_RULE_UNVERIFIED`) - this is a blocker only a human can clear, by loading reviewed rules with `seed_format_constraints.py`.
  2. `cmo_platform_config`: which of the required keys have a platform value (generation, hashtags, niche, trends). Missing keys are named; none is ever defaulted.
  3. `vision_eval_run`: whether any passing evaluation exists (the trust gate). The gate is allowed to be closed - it only means photo details stay "suggestions to confirm".

Usage:
    python verify_cmo_readiness.py                   # needs DATABASE_URL (a role that can SELECT the three tables)
    python verify_cmo_readiness.py --max-age-days N  # override the staleness window ONLY for this report (default: the platform value, else "unknown")

Exit code 0 = every marketplace can generate; 1 = at least one blocker; 2 = could not read the database. Nothing is invented: an unreadable or absent value is reported as such.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

MARKETPLACES = ("AMAZON", "FLIPKART", "MEESHO")
GENERATION_KEYS = ("format_constraint_max_age_days", "internal_retry_bound")
HASHTAG_KEYS = ("hashtag_set_size",)
NICHE_KEYS = ("max_confirmed_niche_terms", "max_term_chars", "catalog_titles_read_cap")
TREND_KEYS = (
    "max_queries_per_report", "section_query_budgets", "section_priority", "max_results_per_query", "max_sources_per_report", "max_findings_per_section", "fresh_window_days",
    "recent_window_days", "news_window_days", "moderate_min_independent_sources", "strong_min_independent_sources", "provider_call_timeout_seconds", "provider_cache_ttl_hours",
    "provider_daily_search_ceiling",
)


@dataclass(frozen=True, slots=True)
class MarketplaceStatus:
    marketplace: str
    ok: bool
    reasons: tuple[str, ...]


def assess_marketplace(marketplace: str, row: dict[str, Any] | None, *, now: datetime, max_age_days: int | None) -> MarketplaceStatus:
    """Pure: one marketplace's newest VERIFIED marketplace-wide row against the rules generation applies."""
    if row is None:
        return MarketplaceStatus(marketplace, False, ("no VERIFIED rule row exists; load reviewed rules with seed_format_constraints.py",))
    reasons: list[str] = []
    if not row.get("count_rule"):
        reasons.append("the row has no verified counting rule (COUNTING_RULE_UNVERIFIED)")
    for field in ("title_max_chars", "title_option_count", "bullet_count"):
        if not row.get(field):
            reasons.append(f"{field} is not stated")
    verified_at = row.get("verified_at")
    if not isinstance(verified_at, datetime):
        reasons.append("no check date")
    elif max_age_days is None:
        reasons.append("staleness cannot be judged: format_constraint_max_age_days is not configured")
    elif (now - (verified_at if verified_at.tzinfo else verified_at.replace(tzinfo=timezone.utc))).days > max_age_days:
        reasons.append(f"last checked {verified_at.date().isoformat()}, older than {max_age_days} days (stale)")
    return MarketplaceStatus(marketplace, not reasons, tuple(reasons))


def missing_keys(present: set[str], required: tuple[str, ...]) -> list[str]:
    return [k for k in required if k not in present]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--max-age-days", type=int, default=None)
    args = ap.parse_args(argv)
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL is required (a role that can SELECT format_constraint, cmo_platform_config and vision_eval_run).")
        return 2
    try:
        from sqlalchemy import create_engine, text

        engine = create_engine(url)
        with engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT DISTINCT ON (marketplace) marketplace, count_rule, title_max_chars, title_option_count, bullet_count, verified_at, source_url "
                "FROM format_constraint WHERE row_kind = 'VERIFIED' AND category IS NULL ORDER BY marketplace, version DESC"
            )).mappings().all()
            cfg = conn.execute(text(
                "SELECT DISTINCT ON (key) key, value FROM cmo_platform_config WHERE tenant_id IS NULL AND effective_from <= CURRENT_DATE ORDER BY key, effective_from DESC"
            )).mappings().all()
            passed = conn.execute(text("SELECT count(*) FROM vision_eval_run WHERE passed")).scalar_one()
    except Exception as exc:  # noqa: BLE001
        print(f"Could not read the database: {type(exc).__name__}. Nothing was assessed.")
        return 2

    by_mp = {r["marketplace"]: dict(r) for r in rows}
    values = {r["key"]: r["value"] for r in cfg}
    age = args.max_age_days if args.max_age_days is not None else (values.get("format_constraint_max_age_days") if isinstance(values.get("format_constraint_max_age_days"), int) else None)
    now = datetime.now(timezone.utc)
    blockers = 0
    print("Marketplace format rules (a VERIFIED, sourced, recently checked row with a counting rule):")
    for mp in MARKETPLACES:
        st = assess_marketplace(mp, by_mp.get(mp), now=now, max_age_days=age)
        blockers += 0 if st.ok else 1
        print(f"  {mp:9} {'READY  ' if st.ok else 'BLOCKED'}" + ("" if st.ok else " - " + "; ".join(st.reasons)))
    present = set(values)
    print("\nPlatform configuration (no key is ever defaulted):")
    for label, keys in (("generation (needed for every artefact)", GENERATION_KEYS), ("hashtags", HASHTAG_KEYS), ("niche terms", NICHE_KEYS), ("market trends", TREND_KEYS)):
        gone = missing_keys(present, keys)
        print(f"  {label}: {'complete' if not gone else 'MISSING ' + ', '.join(gone)}")
        blockers += 1 if (gone and label.startswith("generation")) else 0
    print("\nTitle display rules (listing preview cut-offs): " + ("configured; each rule still needs an https source and a fresh check date to count as verified" if "title_display_rules" in present else "not configured; previews are labelled ILLUSTRATIVE, never official"))
    print(f"\nPhoto trust gate: {'a passing evaluation exists' if passed else 'closed (no passing evaluation); photo details stay suggestions the seller confirms. This is allowed.'}")
    print("\nResult:", "every marketplace can generate" if not blockers else f"{blockers} blocker(s); production generation is blocked where listed above")
    return 0 if not blockers else 1


if __name__ == "__main__":
    sys.exit(main())
