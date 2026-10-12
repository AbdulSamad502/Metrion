"""accounting_cutover repository — read-only (migration 20261011_0017).

The table is a platform-level, application-read-only record of when each accounting rule took effect. A record created
before its rule's `effective_at` is LEGACY and must never be re-evaluated, charged, refunded, repaired or backfilled.
A missing cut-over row means the rule is NOT in effect on this database (fail closed: nothing is treated as post-cut-over).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import text

from backend.db import engine

CEO_UNIT_RULE_2 = "CEO_UNIT_RULE_2"
PI_USAGE_1 = "PI_USAGE_1"
NICHE_RUN_USAGE_1 = "NICHE_RUN_USAGE_1"


def effective_at(code: str) -> datetime | None:
    with engine().connect() as conn:
        value = conn.execute(text("SELECT effective_at FROM accounting_cutover WHERE code = :code"), {"code": code}).scalar()
    return value  # type: ignore[no-any-return]


def is_post_cutover(code: str, created_at: datetime | None) -> bool:
    """True only when the rule is in effect AND the record is known to have been created at/after it. A record with no
    timestamp (legacy rows) or a rule with no cut-over row is never post-cut-over."""
    if created_at is None:
        return False
    cutover = effective_at(code)
    return cutover is not None and created_at >= cutover
