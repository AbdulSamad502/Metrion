"""Validation severities — data-foundation.md §4.1.

| Severity | Effect |
|---|---|
| ERROR   | Row is quarantined. Excluded from all financial aggregates. Surfaced to the seller. |
| WARNING | Row is ingested and included, flagged, and counted in the data-quality report. |
| INFO    | Recorded for diagnostics only. |
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Severity(str, Enum):
    ERROR = "ERROR"
    WARNING = "WARNING"
    INFO = "INFO"


@dataclass(frozen=True, slots=True)
class Finding:
    rule_id: str
    severity: Severity
    message: str
    source_row_number: int | None = None
