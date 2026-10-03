"""Per-report search budgets (spec §6.8.5, §6.8.6, E25). Every number comes from `TrendConfig`;
nothing is defaulted here.

`QueryBudget` is a plain accountant for ONE report build (single-threaded by contract - a
report is assembled by one task). It answers "may this section run another provider query?"
and records the answer, so budget exhaustion is a recorded, explainable state
(`SECTION_BUDGET_EXHAUSTED` / `REPORT_BUDGET_EXHAUSTED`) rather than a silent truncation.

Sections are served in the configured `section_priority` order. That order matters: when the
report-wide cap is smaller than the sum of section budgets (config validation guarantees it is
at least the sum, but a cap lowered later or a shared pool is still possible), the
highest-priority sections spend first and the lowest-priority ones are the ones left
UNAVAILABLE with a stated reason.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import TypeVar

from slim_cmo.config import TrendConfig
from slim_cmo.types import TrendSection

T = TypeVar("T")


class BudgetDenial(str, Enum):
    SECTION_BUDGET_EXHAUSTED = "SECTION_BUDGET_EXHAUSTED"
    REPORT_BUDGET_EXHAUSTED = "REPORT_BUDGET_EXHAUSTED"
    SECTION_NOT_REQUESTED = "SECTION_NOT_REQUESTED"


@dataclass(frozen=True, slots=True)
class BudgetDecision:
    allowed: bool
    denial: BudgetDenial | None = None


class QueryBudget:
    def __init__(self, config: TrendConfig, requested: Iterable[TrendSection]) -> None:
        self._config = config
        self._requested = frozenset(requested)
        self._spent: dict[str, int] = {s.value: 0 for s in TrendSection}
        self._total = 0

    def ordered_sections(self) -> tuple[TrendSection, ...]:
        """The requested sections, highest configured priority first."""
        return tuple(TrendSection(v) for v in self._config.section_priority if TrendSection(v) in self._requested)

    def try_spend(self, section: TrendSection) -> BudgetDecision:
        if section not in self._requested:
            return BudgetDecision(False, BudgetDenial.SECTION_NOT_REQUESTED)
        if self._spent[section.value] >= self._config.section_query_budgets[section.value]:
            return BudgetDecision(False, BudgetDenial.SECTION_BUDGET_EXHAUSTED)
        if self._total >= self._config.max_queries_per_report:
            return BudgetDecision(False, BudgetDenial.REPORT_BUDGET_EXHAUSTED)
        self._spent[section.value] += 1
        self._total += 1
        return BudgetDecision(True)

    def spent(self, section: TrendSection) -> int:
        return self._spent[section.value]

    @property
    def spent_total(self) -> int:
        return self._total

    @property
    def remaining_total(self) -> int:
        return self._config.max_queries_per_report - self._total

    def usage(self) -> dict[str, object]:
        """For the evidence section: budget used versus allowed."""
        return {
            "queries_used": self._total,
            "queries_allowed": self._config.max_queries_per_report,
            "by_section": {s: {"used": self._spent[s], "allowed": self._config.section_query_budgets[s]} for s in self._spent},
        }


def limit_sources(
    per_section: Mapping[TrendSection, Sequence[T]], config: TrendConfig
) -> tuple[dict[TrendSection, tuple[T, ...]], int]:
    """Enforce `max_sources_per_report` across sections: walk sections in priority order, keep
    each section's items in their given order, stop at the cap. Returns (kept, dropped_count)."""
    kept: dict[TrendSection, tuple[T, ...]] = {}
    remaining = config.max_sources_per_report
    dropped = 0
    for value in config.section_priority:
        section = TrendSection(value)
        items = per_section.get(section, ())
        take = items[: max(remaining, 0)]
        kept[section] = tuple(take)
        dropped += len(items) - len(take)
        remaining -= len(take)
    return kept, dropped


def cap_findings(findings: Sequence[T], config: TrendConfig) -> tuple[tuple[T, ...], int]:
    """Enforce `max_findings_per_section`; returns (kept, dropped_count). Order is preserved:
    the caller sorts first (by corroboration, then recency) so the cap keeps the best-evidenced."""
    kept = tuple(findings[: config.max_findings_per_section])
    return kept, len(findings) - len(kept)
