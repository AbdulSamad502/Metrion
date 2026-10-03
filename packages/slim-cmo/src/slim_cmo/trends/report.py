"""Trend-report completeness (spec §6.8.6, AC32, E25).

A report always accounts for all FIVE researched sections. It is `COMPLETE` iff at least one
section produced at least one finding with a citable source; otherwise it is `FAILED` and bills
nothing. A COMPLETE report may still have degraded sections - each of which must be named, with
its reason, in the evidence block (checked by `undeclared_degraded_sections`). Nothing is
fabricated to fill a degraded section.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from enum import Enum

from slim_cmo.types import TrendSection


class SectionState(str, Enum):
    COMPLETE = "COMPLETE"  # ran fully; findings (possibly zero? no: see below)
    PARTIAL = "PARTIAL"  # ran but some queries/sources failed or were skipped
    UNAVAILABLE = "UNAVAILABLE"  # produced nothing; `reason` says why


class Verdict(str, Enum):
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class SectionOutcome:
    section: TrendSection
    state: SectionState
    cited_findings: int
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class ReportAssessment:
    verdict: Verdict
    degraded: tuple[tuple[TrendSection, str], ...]  # every section the evidence block must name, with its reason
    failure_reason: str | None

    @property
    def units_to_bill(self) -> int:
        """CMO units: 1 for a COMPLETE report (degraded sections included), 0 for FAILED."""
        return 1 if self.verdict is Verdict.COMPLETE else 0


def assess_report(outcomes: Sequence[SectionOutcome]) -> ReportAssessment:
    by_section: dict[TrendSection, SectionOutcome] = {}
    for o in outcomes:
        if o.section in by_section:
            raise ValueError(f"section {o.section.value} reported twice")
        by_section[o.section] = o
    missing = [s.value for s in TrendSection if s not in by_section]
    if missing:
        raise ValueError(f"every researched section must be accounted for; missing: {', '.join(missing)}")

    degraded: list[tuple[TrendSection, str]] = []
    for section in TrendSection:  # fixed order => deterministic output
        o = by_section[section]
        if o.cited_findings < 0:
            raise ValueError("cited_findings cannot be negative")
        if o.state is SectionState.UNAVAILABLE:
            if o.cited_findings != 0:
                raise ValueError(f"{section.value}: an UNAVAILABLE section cannot have findings")
            if not (o.reason or "").strip():
                raise ValueError(f"{section.value}: an UNAVAILABLE section must state why")
            degraded.append((section, o.reason.strip()))  # type: ignore[union-attr]
        elif o.state is SectionState.PARTIAL:
            if not (o.reason or "").strip():
                raise ValueError(f"{section.value}: a PARTIAL section must state what was missing")
            degraded.append((section, o.reason.strip()))  # type: ignore[union-attr]
        elif o.cited_findings == 0:
            raise ValueError(f"{section.value}: a COMPLETE section must have at least one cited finding (else mark it UNAVAILABLE)")

    total = sum(o.cited_findings for o in by_section.values())
    if total == 0:
        return ReportAssessment(Verdict.FAILED, tuple(degraded), "no section produced a finding with a citable source")
    return ReportAssessment(Verdict.COMPLETE, tuple(degraded), None)


def undeclared_degraded_sections(
    assessment: ReportAssessment, named_in_evidence: Collection[TrendSection]
) -> tuple[TrendSection, ...]:
    """Degraded sections the evidence block FAILED to name. Must be empty for a valid report."""
    named = set(named_in_evidence)
    return tuple(s for s, _ in assessment.degraded if s not in named)
