"""Deterministic marketplace-constraint resolution (spec §6.3, C13, AC5, AC24, E5, E16, E17).

Given the `format_constraint` rows a repository loaded, decide which ONE row governs a
generation - or say, explicitly, why none may. Never reads the illustrative §6.3 table, never
supplies a value of its own, never falls back silently.

Rules, in order:

1. `max_age_days` is configuration. If it is absent the answer is `CONFIG_MISSING` - not a
   guess, not "no staleness check".
2. Only rows of an accepted `row_kind` are visible. Production passes nothing and therefore sees
   `VERIFIED` rows only; `TEST_FIXTURE` rows (tests) are invisible to it (C13, E17).
3. Category specificity: a row for the requested category beats the marketplace-wide default
   (`category is None`). If a category-specific row exists but is unusable (stale, future-dated,
   missing a needed limit) the request is BLOCKED - it does not quietly fall back to the
   default, because the more specific rule is the one that applies to that product.
4. Within the winning group the highest `version` wins.
5. The winner must be time-valid: tz-aware, not dated in the future, and not older than
   `max_age_days` (an age of exactly `max_age_days` is still valid; one second more is stale).
6. The winner must state how the marketplace counts characters (`count_rule`); without it
   production generation is blocked (the code's UTF-16 count is only a conservative fallback,
   never a verified rule). Backend search terms are exempt: their cap is in UTF-8 bytes.
7. The winner must state every limit needed to even DEFINE the artefact (the option count for a
   title set, the bullet count for bullets, the byte cap for Amazon backend terms). A limit that
   merely helps validate but is not stated (e.g. `title_max_chars is None`) is "unverified": the
   artefact may proceed with that limit un-enforced, and the gap is reported to the caller
   (spec §6.4: "not enforced and not guessed").
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Any
from uuid import UUID

from slim_cmo.textnorm import collapse_whitespace
from slim_cmo.types import CONSTRAINT_BOUND_OUTPUT_TYPES, ConstraintRowKind, CountRule, Marketplace, OutputType


@dataclass(frozen=True, slots=True)
class FormatConstraint:
    """One `format_constraint` row. Every limit may be None = 'not stated by the source'."""

    id: UUID
    marketplace: Marketplace
    category: str | None
    version: int
    row_kind: ConstraintRowKind
    source_url: str
    verified_at: datetime
    title_max_chars: int | None = None
    title_option_count: int | None = None
    bullet_count: int | None = None
    bullet_max_chars: int | None = None
    description_type: str | None = None
    description_max_chars: int | None = None
    keywords_max_count: int | None = None
    keywords_max_chars: int | None = None
    backend_terms_max_bytes: int | None = None
    hashtags_supported: bool | None = None
    count_rule: CountRule | None = None  # None = counting rule NOT verified for this marketplace

    def cite(self) -> dict[str, Any]:
        """What an output cites so a seller can see how current the rule is (spec §6.3)."""
        return {
            "format_constraint_ref": str(self.id),
            "source_url": self.source_url,
            "verified_at": self.verified_at.isoformat(),
            "version": self.version,
        }

    @property
    def hashtags_in_listing_allowed(self) -> bool:
        """Only an explicit, verified True permits hashtags inside a listing field (AC13).
        NULL means 'not established' and is treated as NOT supported."""
        return self.hashtags_supported is True


class UnavailableReason(str, Enum):
    CONFIG_MISSING = "CONFIG_MISSING"
    NO_ROW = "NO_ROW"
    NO_VERIFIED_ROW = "NO_VERIFIED_ROW"
    STALE = "STALE"
    FUTURE_VERIFIED_AT = "FUTURE_VERIFIED_AT"
    INVALID_ROW = "INVALID_ROW"
    MISSING_REQUIRED_LIMIT = "MISSING_REQUIRED_LIMIT"
    COUNTING_RULE_UNVERIFIED = "COUNTING_RULE_UNVERIFIED"
    UNSUPPORTED_COMBINATION = "UNSUPPORTED_COMBINATION"


@dataclass(frozen=True, slots=True)
class ConstraintUnavailable:
    """Generation for this marketplace is blocked (E5). `detail` is safe to show the seller."""

    reason: UnavailableReason
    marketplace: Marketplace
    detail: str
    missing: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ResolvedConstraint:
    row: FormatConstraint
    unverified_limits: tuple[str, ...]  # limits relevant to this artefact that the row does not state


# Limits needed to DEFINE the artefact: without them it cannot be produced at all.
_REQUIRED_LIMITS: dict[OutputType, tuple[str, ...]] = {
    OutputType.TITLE_SET: ("title_option_count",),
    OutputType.LISTING_COPY: ("bullet_count",),
    OutputType.BULLETS: ("bullet_count",),
    OutputType.BACKEND_TERMS: ("backend_terms_max_bytes",),
    OutputType.DESCRIPTION: (),
    OutputType.KEYWORDS: (),
}
# Limits that help VALIDATE; None means "not enforced, reported as unverified".
_VALIDATING_LIMITS: dict[OutputType, tuple[str, ...]] = {
    OutputType.TITLE_SET: ("title_max_chars",),
    OutputType.LISTING_COPY: (
        "bullet_max_chars", "description_max_chars", "keywords_max_count", "keywords_max_chars",
    ),
    OutputType.BULLETS: ("bullet_max_chars",),
    OutputType.DESCRIPTION: ("description_max_chars",),
    OutputType.KEYWORDS: ("keywords_max_count", "keywords_max_chars"),
    OutputType.BACKEND_TERMS: (),
}


def _norm_category(category: str | None) -> str | None:
    if category is None:
        return None
    cleaned = collapse_whitespace(category).casefold()
    return cleaned or None


def _is_aware(dt: datetime) -> bool:
    return dt.tzinfo is not None and dt.tzinfo.utcoffset(dt) is not None


def resolve_constraint(
    rows: Iterable[FormatConstraint],
    *,
    marketplace: Marketplace,
    category: str | None,
    output_type: OutputType,
    now: datetime,
    max_age_days: int | None,
    accepted_row_kinds: frozenset[ConstraintRowKind] = frozenset({ConstraintRowKind.VERIFIED}),
) -> ResolvedConstraint | ConstraintUnavailable:
    """See the module docstring for the rules. `now` must be timezone-aware (a naive clock is a
    programming error, not a data condition)."""
    if output_type not in CONSTRAINT_BOUND_OUTPUT_TYPES:
        raise ValueError(f"{output_type.value} is not bound to a marketplace format constraint")
    if not _is_aware(now):
        raise ValueError("`now` must be timezone-aware")

    # 1. configuration first: without a staleness policy nothing may be called 'current'.
    if max_age_days is None or type(max_age_days) is not int or max_age_days < 1:
        return ConstraintUnavailable(
            UnavailableReason.CONFIG_MISSING, marketplace,
            "format_constraint_max_age_days is not configured as a positive integer",
            missing=("format_constraint_max_age_days",),
        )

    if output_type is OutputType.BACKEND_TERMS and marketplace is not Marketplace.AMAZON:
        return ConstraintUnavailable(
            UnavailableReason.UNSUPPORTED_COMBINATION, marketplace,
            "backend search terms exist only for Amazon",
        )

    # 2. visibility by row kind
    all_rows = [r for r in rows if r.marketplace is marketplace]
    if not all_rows:
        return ConstraintUnavailable(UnavailableReason.NO_ROW, marketplace, "no format constraint exists for this marketplace")
    visible = [r for r in all_rows if r.row_kind in accepted_row_kinds]
    if not visible:
        return ConstraintUnavailable(
            UnavailableReason.NO_VERIFIED_ROW, marketplace,
            "no verified format constraint exists for this marketplace",
        )

    # 3. category specificity (a more specific rule never silently falls back to the default)
    wanted = _norm_category(category)
    pool: Sequence[FormatConstraint]
    if wanted is not None:
        specific = [r for r in visible if _norm_category(r.category) == wanted]
        pool = specific if specific else [r for r in visible if _norm_category(r.category) is None]
    else:
        pool = [r for r in visible if _norm_category(r.category) is None]
    if not pool:
        return ConstraintUnavailable(
            UnavailableReason.NO_ROW, marketplace,
            "no marketplace-wide constraint exists and none matches the requested category",
        )

    # 4. highest version wins. The schema makes (marketplace, category, version, row_kind) unique,
    # so a tie can only be a VERIFIED and a TEST_FIXTURE row (when tests accept both): VERIFIED
    # wins, then id, which keeps the choice a deterministic total order even on bad data.
    row = max(pool, key=lambda r: (r.version, r.row_kind is ConstraintRowKind.VERIFIED, str(r.id)))

    # 5. time validity
    if not _is_aware(row.verified_at):
        return ConstraintUnavailable(UnavailableReason.INVALID_ROW, marketplace, "constraint verified_at has no timezone")
    if row.verified_at > now:
        return ConstraintUnavailable(UnavailableReason.FUTURE_VERIFIED_AT, marketplace, "constraint is dated in the future")
    if now - row.verified_at > timedelta(days=max_age_days):
        return ConstraintUnavailable(
            UnavailableReason.STALE, marketplace,
            f"the newest verified constraint is older than the allowed {max_age_days} days",
        )

    # 6. the counting rule must be VERIFIED. The UTF-16 count in `textnorm` is only a conservative
    # implementation fallback, never a verified marketplace rule; production generation stays
    # blocked for a marketplace until its row states how that marketplace counts characters.
    # (Backend search terms are capped in UTF-8 bytes, which is not a character rule.)
    if output_type is not OutputType.BACKEND_TERMS and row.count_rule is None:
        return ConstraintUnavailable(
            UnavailableReason.COUNTING_RULE_UNVERIFIED, marketplace,
            "the constraint does not state how this marketplace counts characters", missing=("count_rule",),
        )

    # 7. limits
    missing = tuple(f for f in _REQUIRED_LIMITS[output_type] if getattr(row, f) is None)
    if missing:
        return ConstraintUnavailable(
            UnavailableReason.MISSING_REQUIRED_LIMIT, marketplace,
            f"the constraint does not state: {', '.join(missing)}", missing=missing,
        )
    unverified = tuple(f for f in _VALIDATING_LIMITS[output_type] if getattr(row, f) is None)
    return ResolvedConstraint(row=row, unverified_limits=unverified)
