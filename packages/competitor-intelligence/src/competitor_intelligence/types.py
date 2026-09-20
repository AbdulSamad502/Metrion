"""Shared vocabulary — competitor-intelligence-agent.md §5, §5.1.

`Paise` is a plain `int` alias, not a wrapped class: this package never does the kind of
compounding arithmetic on money that would justify a distinct numeric type (that's
calc-engine's job). It only ever stores an observed integer and, in `delta/`, subtracts two
of them — see delta/compute.py for why even that one subtraction avoids float.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

Paise = int


class Marketplace(str, Enum):
    AMAZON = "AMAZON"
    FLIPKART = "FLIPKART"
    MEESHO = "MEESHO"


class UrlStatus(str, Enum):
    ACTIVE = "ACTIVE"
    UNREACHABLE = "UNREACHABLE"
    ARCHIVED = "ARCHIVED"


class CaptureStatus(str, Enum):
    """§5.3 rule 5 — REVISED for the evidence model. Replaces the retired
    OK|BLOCKED|NOT_FOUND|PARSE_FAILED (a fetch-outcome vocabulary — nothing is fetched anymore).
    Reflects the merge outcome of a research session instead."""

    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    PENDING_MANUAL_ENTRY = "PENDING_MANUAL_ENTRY"


class ExtractionStatus(str, Enum):
    """§5 `competitor_evidence.extraction_status` — one row per submitted screenshot."""

    PENDING = "PENDING"
    EXTRACTED = "EXTRACTED"
    EXTRACTION_FAILED = "EXTRACTION_FAILED"


class Confidence(str, Enum):
    """§5.1 — CI's own scoped vocabulary, distinct from data-foundation.md §7.1. REVISED for
    the evidence model: `OBSERVED` is retired (it meant "read directly from the listing page,"
    which nothing does anymore) and replaced by two tiers reflecting who/what produced a
    value.

    Deliberately has no VERIFIED/PROVISIONAL/MANUAL members: CI never claims either, and a
    CI-sourced figure can never present as one downstream — a value always enters Brain 1 as
    DERIVED regardless of which of these four tiers it carried inside CI (§5.1).
    """

    VISION_EXTRACTED = "VISION_EXTRACTED"
    SELLER_ENTERED = "SELLER_ENTERED"
    DERIVED = "DERIVED"
    UNAVAILABLE = "UNAVAILABLE"


class Availability(str, Enum):
    IN_STOCK = "IN_STOCK"
    OUT_OF_STOCK = "OUT_OF_STOCK"
    UNKNOWN = "UNKNOWN"


class Trigger(str, Enum):
    """§5, `ci_capture_run.trigger`. REVISED for the evidence model: `EVIDENCE_UPLOAD` is the
    only wired value in this pass — it fires when the seller submits a screenshot from the
    dashboard, superseding `DIRECT_UI`'s former role as "the dashboard trigger" (DIRECT_UI
    used to mean a fetch-triggering button, which no longer exists). `DIRECT_UI` stays in the
    enum for a possible future non-evidence direct action but is not wired to anything here.
    `CEO_REQUEST`/`WHATSAPP_CONFIRM` remain deferred per spec §1a, unchanged."""

    EVIDENCE_UPLOAD = "EVIDENCE_UPLOAD"
    DIRECT_UI = "DIRECT_UI"
    CEO_REQUEST = "CEO_REQUEST"
    WHATSAPP_CONFIRM = "WHATSAPP_CONFIRM"


class RunStatus(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    PARTIAL = "PARTIAL"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"


class Direction(str, Enum):
    INCREASE = "INCREASE"
    DECREASE = "DECREASE"


class AvailabilityChange(str, Enum):
    IN_TO_OUT = "IN_TO_OUT"
    OUT_TO_IN = "OUT_TO_IN"


class InsightState(str, Enum):
    COMPLETE = "COMPLETE"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"


class DerivationMethod(str, Enum):
    LOCAL_MODEL = "LOCAL_MODEL"
    LOCAL_HEURISTIC = "LOCAL_HEURISTIC"
    STRUCTURED_ONLY = "STRUCTURED_ONLY"


@dataclass(frozen=True, slots=True)
class Unavailable:
    """A step's result when a required input is missing or a computation cannot be
    performed safely — never a silent zero or a fabricated value (CLAUDE.md hard rule)."""

    reason: str
