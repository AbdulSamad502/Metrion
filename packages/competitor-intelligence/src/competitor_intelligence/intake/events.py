"""CI event vocabulary and the "ids and enums only" rule — competitor-intelligence-agent.md C47.

`ci_event` is the append-only history the dashboard reads. Its `detail` column carries **ids,
enums, numbers and short codes only** — never review text, snippets, listing copy or image
content (§7 rules 8, 14, 19; AC56). This module is the one gate that enforces it, so a caller
cannot smuggle free text into the audit trail by accident.
"""

from __future__ import annotations

from enum import Enum
from typing import Any
from uuid import UUID


class CiEvent(str, Enum):
    EVIDENCE_RECEIVED = "EVIDENCE_RECEIVED"
    EVIDENCE_REJECTED_QUALITY = "EVIDENCE_REJECTED_QUALITY"
    EVIDENCE_DUPLICATE = "EVIDENCE_DUPLICATE"
    FIELD_CONFIRMATION_REQUESTED = "FIELD_CONFIRMATION_REQUESTED"
    FIELD_CONFIRMED = "FIELD_CONFIRMED"
    FIELD_CONFIRMATION_DECLINED = "FIELD_CONFIRMATION_DECLINED"
    FIELD_CONFIRMATION_EXPIRED = "FIELD_CONFIRMATION_EXPIRED"
    COMPETITOR_APPROVED = "COMPETITOR_APPROVED"
    COMPETITOR_REJECTED = "COMPETITOR_REJECTED"
    COMPETITOR_ADDED = "COMPETITOR_ADDED"
    COMPETITOR_REMOVED = "COMPETITOR_REMOVED"
    DISCOVERY_RUN_STARTED = "DISCOVERY_RUN_STARTED"
    DISCOVERY_RUN_COMPLETED = "DISCOVERY_RUN_COMPLETED"
    DISCOVERY_RUN_FAILED = "DISCOVERY_RUN_FAILED"
    QUERY_DISPATCHED = "QUERY_DISPATCHED"
    PRIVACY_FILTER_DROP = "PRIVACY_FILTER_DROP"
    FINDING_CREATED = "FINDING_CREATED"
    ALERT_RAISED = "ALERT_RAISED"
    ALERT_SUPPRESSED_DEDUP = "ALERT_SUPPRESSED_DEDUP"
    ALERT_HELD_QUIET_HOURS = "ALERT_HELD_QUIET_HOURS"
    ALERT_WITHHELD_STALE = "ALERT_WITHHELD_STALE"
    MONITOR_RUN = "MONITOR_RUN"
    CEO_INVESTIGATION_LINKED = "CEO_INVESTIGATION_LINKED"


MAX_DETAIL_STRING_LENGTH = 64
MAX_DETAIL_KEYS = 16


class UnsafeEventDetail(ValueError):
    """A `detail` value that could carry free text."""


def _check_value(key: str, value: Any) -> None:
    if value is None or isinstance(value, (bool, int, float, UUID)):
        return
    if isinstance(value, Enum):
        return
    if isinstance(value, str):
        if len(value) > MAX_DETAIL_STRING_LENGTH or any(ch.isspace() and ch != " " for ch in value) or "\n" in value:
            raise UnsafeEventDetail(f"detail[{key!r}] is not a short code")
        if value.count(" ") > 2:  # a sentence, not a code
            raise UnsafeEventDetail(f"detail[{key!r}] looks like free text")
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _check_value(key, item)
        return
    raise UnsafeEventDetail(f"detail[{key!r}] has unsupported type {type(value).__name__}")


def safe_detail(detail: dict[str, Any] | None) -> dict[str, Any]:
    """Returns a JSON-safe copy of `detail`, or raises `UnsafeEventDetail`."""
    if not detail:
        return {}
    if len(detail) > MAX_DETAIL_KEYS:
        raise UnsafeEventDetail("too many detail keys")
    out: dict[str, Any] = {}
    for key, value in detail.items():
        _check_value(key, value)
        if isinstance(value, UUID):
            out[key] = str(value)
        elif isinstance(value, Enum):
            out[key] = value.value
        elif isinstance(value, (list, tuple)):
            out[key] = [str(v) if isinstance(v, UUID) else (v.value if isinstance(v, Enum) else v) for v in value]
        else:
            out[key] = value
    return out
