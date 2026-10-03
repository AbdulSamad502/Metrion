"""`format_constraint` reads (spec §6.3, C13, AC5, AC24). Platform table, no tenant data.

Production reads `VERIFIED` rows only: the default `kinds` is VERIFIED, and `TEST_FIXTURE` rows
exist for automated tests, which must pass them explicitly (the service never exposes this to a
client). The resolver then applies category specificity, version, staleness and the counting rule.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from sqlalchemy import Connection, bindparam, text

from slim_cmo.constraints import FormatConstraint
from slim_cmo.types import ConstraintRowKind, CountRule, Marketplace

_SQL = text(
    """
    SELECT id, marketplace, category, version, row_kind, source_url, verified_at,
           title_max_chars, title_option_count, bullet_count, bullet_max_chars,
           description_type, description_max_chars, keywords_max_count, keywords_max_chars,
           backend_terms_max_bytes, hashtags_supported, count_rule
    FROM format_constraint
    WHERE marketplace = :marketplace AND row_kind IN :kinds
    """
).bindparams(bindparam("kinds", expanding=True))


def _row(r: Any) -> FormatConstraint:
    return FormatConstraint(
        id=r.id, marketplace=Marketplace(r.marketplace), category=r.category, version=r.version,
        row_kind=ConstraintRowKind(r.row_kind), source_url=r.source_url, verified_at=r.verified_at,
        title_max_chars=r.title_max_chars, title_option_count=r.title_option_count,
        bullet_count=r.bullet_count, bullet_max_chars=r.bullet_max_chars,
        description_type=r.description_type, description_max_chars=r.description_max_chars,
        keywords_max_count=r.keywords_max_count, keywords_max_chars=r.keywords_max_chars,
        backend_terms_max_bytes=r.backend_terms_max_bytes, hashtags_supported=r.hashtags_supported,
        count_rule=CountRule(r.count_rule) if r.count_rule else None,
    )


def list_constraints(
    conn: Connection,
    marketplace: Marketplace,
    kinds: Iterable[ConstraintRowKind] = (ConstraintRowKind.VERIFIED,),
) -> list[FormatConstraint]:
    result = conn.execute(_SQL, {"marketplace": marketplace.value, "kinds": [k.value for k in kinds]})
    return [_row(r) for r in result]
