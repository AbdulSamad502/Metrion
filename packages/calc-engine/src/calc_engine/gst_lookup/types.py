"""GstLookupQuery / GstLookupResult / GstLookupNoMatch — deterministic-engine.md §8.4's
`gst_lookup_result` schema, plus the query input and a distinguished non-result outcome.

**L3 enforced structurally, not just at runtime.** `source_url` and `retrieved_at` are
declared with no default, ahead of every other field that does carry one. `dataclass` refuses
to compile a class where a no-default field follows a defaulted one, and refuses to
*construct* an instance missing a no-default field (`TypeError: missing N required
positional/keyword arguments`) — so `GstLookupResult(...)` without both is not a validation
error caught later, it is impossible to call. `tests/unit/test_gst_lookup_types.py` proves
this directly (attempts construction without each field, asserts `TypeError`).

**L5 (the standing disclaimer) lives on the dataclass itself, as a field with a fixed
default**, not attached later by a narration layer. Reasoning: the disclaimer's text is not
something a caller ever legitimately customises per query — every `GstLookupResult` the
composition function in `lookup.py` returns carries exactly the same L5 text, so binding it as
this dataclass's own default keeps "you cannot construct a result without the disclaimer"
true by the same structural mechanism as L3, rather than trusting every future call site
(CFO's G3 route, the frontend) to remember to attach it.

**Tier is deliberately NOT a field here** (§8.4.1: "`gst_lookup_result` does not currently
carry an explicit tier column... the tier is inferable from `source_url`'s host"). Adding one
here would silently reintroduce the schema column the spec explicitly declined to add in this
pass — `calc_engine.gst_lookup.allowlist.tier_for_host(result.source_url)` is the sanctioned
way for a consuming surface to recover it at read/narration time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from fractions import Fraction
from typing import Any
from uuid import UUID

# §8.4 L5 — the exact standing disclaimer text, verbatim.
GST_LOOKUP_DISCLAIMER = (
    "Likely classification based on web research. Final GST classification must be verified "
    "through official GST guidance or a qualified tax professional."
)

STATUS_PROVISIONAL = "PROVISIONAL"
STATUS_SELLER_VERIFIED = "SELLER_VERIFIED"
STATUS_REJECTED = "REJECTED"


@dataclass(frozen=True, slots=True)
class GstLookupQuery:
    """§8.4 input: "product title, and where available HSN/SAC or category." `sku` is
    optional — a lookup may be run ad hoc against a product title with no SKU tied to it yet
    (e.g. a pre-listing check)."""

    product_title: str
    sku: str | None = None
    hsn: str | None = None
    category: str | None = None


@dataclass(frozen=True, slots=True)
class GstLookupResult:
    """§8.4's `gst_lookup_result` schema. `likely_rate_pct` is a `Fraction`, never a `float`
    (CLAUDE.md's no-float rule, applied here even though this result is research output, not
    an engine calculation — nothing under `calc_engine` ever represents a rate as a float).

    `alternatives` holds competing classifications found in the same fetched content (L4) as
    plain dicts (`{"rate_pct": Fraction, "hsn": str | None, "category": str | None}`) — kept
    unstructured rather than a nested dataclass because L4's contract only requires
    *surfacing* them, never comparing or ranking them (that would be exactly the kind of
    "picking one confidently" L4 forbids).
    """

    id: UUID
    tenant_id: UUID
    query_text: str
    source_url: str  # L3: mandatory, no default.
    retrieved_at: datetime  # L3: mandatory, no default.

    sku: str | None = None
    query_hsn: str | None = None
    likely_rate_pct: Fraction | None = None
    likely_hsn: str | None = None
    likely_category: str | None = None
    ambiguity_note: str | None = None  # L4: populated when classification is uncertain.
    alternatives: tuple[dict[str, Any], ...] = field(default_factory=tuple)  # L4.
    source_title: str | None = None
    status: str = STATUS_PROVISIONAL  # PROVISIONAL | SELLER_VERIFIED | REJECTED
    verified_by: str | None = None
    verified_at: datetime | None = None
    disclaimer: str = GST_LOOKUP_DISCLAIMER  # L5, fixed — see module docstring.

    def __post_init__(self) -> None:
        if not self.source_url:
            raise ValueError("GstLookupResult.source_url must be non-empty (L3)")
        if self.status not in (STATUS_PROVISIONAL, STATUS_SELLER_VERIFIED, STATUS_REJECTED):
            raise ValueError(f"GstLookupResult.status must be one of PROVISIONAL/SELLER_VERIFIED/REJECTED, got {self.status!r}")


@dataclass(frozen=True, slots=True)
class GstLookupNoMatch:
    """§8.4.1's "no reliable source found" outcome — every known page attempted (fetch failed
    or yielded no genuine match) without producing a `GstLookupResult`. A real, named
    non-result type, never a placeholder `GstLookupResult` with a guessed/absent source
    (mirrors `calc_engine.anomaly.types.AnomalyInsufficientHistory`'s pattern: a distinguished
    outcome a caller pattern-matches, not an exception and not a coerced "empty" result)."""

    query_text: str
    attempted_urls: tuple[str, ...] = ()
    reason: str = "NO_RELIABLE_SOURCE_FOUND"
