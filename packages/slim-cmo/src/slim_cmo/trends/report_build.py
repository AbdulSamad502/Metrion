"""Deterministic assembly pieces of a trend report (spec §6.8.2 section 7, §6.8.6): the plan digest the seller's preview is bound
to, the source cap, and the always-non-empty evidence-and-limitations section. Pure; the LLM contributes nothing here."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

from slim_cmo.trends.findings import Finding, FindingInput
from slim_cmo.trends.queries import TEMPLATE_VERSION, QueryPlan
from slim_cmo.trends.report import ReportAssessment
from slim_cmo.types import TrendSection

# Fixed gaps always listed (spec §6.8.2 section 7).
DATA_GAPS: tuple[str, ...] = (
    "No marketplace sales data is used: attention in the sources is not demand, sales or profitability.",
    "No search-volume or keyword-demand data is used.",
    "Coverage is India-focused and English; the providers' India filter is approximate, and Hinglish or regional-language sources are not covered.",
    "Results are limited to what the configured search providers returned for a small number of queries; absence of a source is not evidence of absence.",
    "Different websites with common ownership cannot be told apart, so independent-source counts can overstate independence.",
    "Reported tactics are reported by third parties and are not verified by Metrion.",
)


def plan_digest(plan: QueryPlan, *, sections: Sequence[TrendSection]) -> str:
    """Binds the preview the seller saw to the run: the exact outbound queries, the unavailable sections and the disclosed
    unresearched terms. Anything that changes any of them (a newly confirmed term, an edited config) changes the digest."""
    canon = {
        "template_version": TEMPLATE_VERSION,
        "sections": sorted(s.value for s in sections),
        "queries": plan.preview(),
        "unavailable": {s.value: r for s, r in sorted(plan.unavailable.items(), key=lambda kv: kv[0].value)},
        "unresearched_terms": list(plan.unresearched_terms),
        "skipped": [[s.section.value, s.template_id, s.reason] for s in plan.skipped],
    }
    return hashlib.sha256(json.dumps(canon, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def cap_items(
    by_section: Mapping[TrendSection, Sequence[FindingInput]], priority: Sequence[str], max_sources: int
) -> tuple[dict[TrendSection, list[FindingInput]], int]:
    """Keep at most `max_sources` retrieved items across the report, highest-priority section first, dated items before
    undated within a section. Returns (kept per section, number dropped)."""
    kept: dict[TrendSection, list[FindingInput]] = {}
    remaining, dropped = max_sources, 0
    for name in priority:
        section = TrendSection(name)
        items = sorted(by_section.get(section, ()), key=lambda i: (i.source.published_at is None, -(i.source.published_at.timestamp() if i.source.published_at else 0), i.source.url))
        take = items[: max(remaining, 0)]
        dropped += len(items) - len(take)
        remaining -= len(take)
        if take:
            kept[section] = list(take)
    return kept, dropped


def evidence_section(
    *,
    findings: Sequence[Finding],
    assessment: ReportAssessment,
    plan: QueryPlan,
    accounting: Mapping[str, Any],
    config_snapshot: Mapping[str, Any],
    withheld_instruction_like: int,
    dropped_by_source_cap: int,
    rejected_findings: Mapping[str, Mapping[str, int]],
    interpretation_counts: Mapping[str, int],
    unresearched_terms: Sequence[str],
) -> dict[str, Any]:
    seen: dict[str, dict[str, Any]] = {}
    for f in findings:
        for s in f.sources:
            row = seen.setdefault(s["url"], {**s, "cited_by": []})
            row["cited_by"].append(f.finding_id)
    modes = sorted({f"{q.provider.value} {'news' if q.provider.value == 'TAVILY' else 'video search'}" for q in plan.queries})
    return {
        "sources": sorted(seen.values(), key=lambda r: r["url"]),
        "per_finding": [
            {"finding_id": f.finding_id, "independent_source_count": f.evidence.independent_source_count, "mention_count": f.evidence.mention_count,
             "recency_class": f.evidence.recency.value, "corroboration": f.evidence.corroboration.value if f.evidence.corroboration else None,
             "is_stale": f.evidence.is_stale}
            for f in findings
        ],
        "degraded_sections": [{"section": s.value, "reason": r} for s, r in assessment.degraded],
        "budget": {"used_vs_allowed": dict(plan.budget_usage), "skipped_by_budget": [[s.section.value, s.reason] for s in plan.skipped]},
        "providers_and_modes_used": modes,
        "provider_accounting": dict(accounting),
        "unresearched_confirmed_terms": list(unresearched_terms),
        "withheld_for_instruction_like_text": withheld_instruction_like,
        "dropped_by_source_cap": dropped_by_source_cap,
        "rejected_findings_by_section": {k: dict(v) for k, v in rejected_findings.items()},
        "interpretation": dict(interpretation_counts),
        "data_gaps": list(DATA_GAPS),
        "config_in_force": dict(config_snapshot),
        "template_version": TEMPLATE_VERSION,
    }
