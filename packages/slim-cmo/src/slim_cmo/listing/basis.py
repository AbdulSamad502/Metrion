"""The rules-unavailable basis (docs/specs/slim-cmo-agent.md section 6.18.11; owner decision 2026-10-30, amends C13 for the M6 full-listing workflow only).

A VERIFIED, non-stale row always wins. Only when none is usable AND the operator flag is on AND the step belongs to a full-listing workflow, this module supplies a synthetic constraint with NO
marketplace limit stated (so the existing rule "a limit the row does not state is not enforced and not guessed" applies to every limit) and the generation settings the owner approved. The
workflow marker is decided by the server (the CEO's own plan), never by anything the client sends. Pure: no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from slim_cmo.constraints import ConstraintUnavailable, FormatConstraint, ResolvedConstraint, UnavailableReason
from slim_cmo.types import ConstraintRowKind, CountRule, Marketplace

VERIFIED, UNVERIFIED = "VERIFIED", "UNVERIFIED"
FLAG_KEY = "listing_unverified_rules_enabled"
BULLET_TARGET_KEY = "rules_unavailable_bullet_target"
FULL_LISTING = "FULL_LISTING"
BANNER = "Marketplace rules are not verified for {marketplace}. Lengths and field limits were measured, not checked. Check them on the marketplace before you use this listing."
# Only these outcomes mean "no marketplace data". A configuration fault (CONFIG_MISSING, INVALID_ROW, ...) never opens this basis.
ELIGIBLE_REASONS = frozenset({UnavailableReason.NO_ROW, UnavailableReason.NO_VERIFIED_ROW, UnavailableReason.STALE, UnavailableReason.COUNTING_RULE_UNVERIFIED})
_NIL = UUID(int=0)
DRAFT_TITLE_OPTION_COUNT = 5  # CMO 3.0 plan: five titles per marketplace. A product setting for the draft title set, not a marketplace rule.


@dataclass(frozen=True, slots=True)
class UnverifiedConstraint(FormatConstraint):
    """A synthetic row with every marketplace limit unstated. It is never persisted as a rule and never cites a source."""

    def cite(self) -> dict[str, Any]:
        return {"rules_basis": UNVERIFIED, "format_constraint_ref": None, "source_url": None, "verified_at": None, "version": None, "row_kind": "NONE",
                "note": "No verified marketplace rule was used. Lengths were measured, not checked."}


@dataclass(frozen=True, slots=True)
class BasisSettings:
    enabled: bool  # listing_unverified_rules_enabled is exactly True
    bullet_target: int | None  # rules_unavailable_bullet_target (a positive int) or None when missing/invalid
    workflow: str | None  # FULL_LISTING when the server runs this step inside a full-listing request


def parse_flag(raw: object) -> bool:
    """Default false: only the boolean True or the exact strings 'true'/'TRUE' enable it. Anything else (absent, '1', 'yes', 2, None) is off."""
    return raw is True or (isinstance(raw, str) and raw.strip().lower() == "true")


def parse_target(raw: object) -> int | None:
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw if raw >= 1 else None
    if isinstance(raw, str) and raw.strip().isdigit() and int(raw.strip()) >= 1:
        return int(raw.strip())
    return None


BASIS_OUTPUT_TYPES = frozenset({"TITLE_SET", "LISTING_COPY", "BACKEND_TERMS"})  # the only artefacts a full-listing workflow may produce on this basis


def applies(unavailable: ConstraintUnavailable, settings: BasisSettings) -> bool:
    return settings.workflow == FULL_LISTING and settings.enabled and unavailable.reason in ELIGIBLE_REASONS


def disabled_reason(settings: BasisSettings) -> str | None:
    """Why the basis cannot be used even though the rows are unavailable, in the seller's words; None when it can."""
    if settings.workflow != FULL_LISTING:
        return None
    if not settings.enabled:
        return "unverified drafts are not enabled"
    return None


def synthetic(marketplace: Marketplace, *, settings: BasisSettings, title_option_count: int | None, now: datetime, needs_bullets: bool) -> ResolvedConstraint | ConstraintUnavailable:
    """The constraint to generate against. A missing/invalid bullet target (when bullets are written) or a missing option count (title sets) is a configuration fault: blocked, no hidden default."""
    if needs_bullets and settings.bullet_target is None:
        return ConstraintUnavailable(UnavailableReason.CONFIG_MISSING, marketplace, f"{BULLET_TARGET_KEY} is not configured as a positive integer", missing=(BULLET_TARGET_KEY,))
    row = UnverifiedConstraint(
        id=_NIL, marketplace=marketplace, category=None, version=0, row_kind=ConstraintRowKind.TEST_FIXTURE, source_url="", verified_at=now,
        title_option_count=title_option_count, bullet_count=settings.bullet_target if needs_bullets else None, count_rule=CountRule.CODE_POINTS,
    )
    return ResolvedConstraint(row=row, unverified_limits=("title_max_chars", "bullet_max_chars", "description_max_chars", "keywords_max_count", "keywords_max_chars", "backend_terms_max_bytes"))


def rules_basis_of(row: FormatConstraint) -> str:
    return UNVERIFIED if isinstance(row, UnverifiedConstraint) else VERIFIED
