"""Turns Business State entries, specialist legs and stored findings into the composer's evidence table — spec §6.5, §6.13, §6.15.

A figure reaches the table only through its REF: it is resolved against the owning table for THIS tenant (`provenance`), formatted by
`figure_format` from the stored value, and dropped with a named gap if it cannot be verified or is unavailable. Specialist payload
text is never copied across except closed enums (band names, severity labels, action types) — free text from a payload could carry
numbers or instructions, so it is not evidence (R9). Nothing here computes anything.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from backend.ceo import provenance
from backend.ceo.composer import EvidenceTable, figures_with_tokens
from backend.ceo.contract import (
    BusinessStateEntry, Denial, EntryStatus, Fact, Figure, Gap, LegResult, LegStatus, Ref, RefKind, Register,
)
from backend.ceo.figure_format import format_paise, format_percent_number, register_for

MAX_FIGURES = 12  # how many verified figures one answer carries; the rest stay on the findings (stated as a gap, never dropped silently)

_METRIC_LABELS: Mapping[str, str] = {
    "NET_REALIZED_REVENUE": "Net realized revenue",
    "CONTRIBUTION_PROFIT": "Contribution profit",
    "MARKETPLACE_FEES": "Marketplace fees",
    "CONTRIBUTION_MARGIN_PCT": "Contribution margin",
    "FEE_RATIO_PCT": "Fee ratio",
    "RETURN_RATE_PCT": "Return rate",
    "CASH_RECEIVED": "Cash received",
}

LEG_LABELS: Mapping[str, str] = {
    "cfo.financial_health": "The financial health check",
    "cfo.anomaly_check": "The anomaly check",
    "cfo.strategic_briefing": "The CFO briefing",
    "cfo.reconcile": "The marketplace reconciliation",
    "cfo.cash_reconciliation": "The cash reconciliation",
    "BS_PNL_LATEST": "The latest profit and loss",
    "BS_LEAK_OPEN": "The open leak summary",
    "BS_DATA_GAPS": "The list of inputs still needed",
    "BS_HEALTH_BANDS": "The health bands",
    "BS_SELLER_CONTEXT": "Your saved goal and notes",
    "BS_INGEST_STATUS": "The upload status",
}
_AGENT_NAME = {"CFO": "CFO", "CI": "Competitor Intelligence", "PI": "Product Intelligence", "CMO": "CMO"}

_ENTRY_STATUS_FINDING: Mapping[EntryStatus, str] = {
    EntryStatus.AVAILABLE: "COMPLETE", EntryStatus.STALE: "PARTIAL", EntryStatus.PARTIAL: "PARTIAL", EntryStatus.UNAVAILABLE: "UNAVAILABLE",
    EntryStatus.NOT_ENTITLED: "NOT_ENTITLED", EntryStatus.NOT_PERMITTED: "DENIED", EntryStatus.NOT_ATTACHED: "DENIED",
}


def finding_status_for_entry(status: EntryStatus) -> str:
    return _ENTRY_STATUS_FINDING[status]


def figure_from_metric_row(row: Mapping[str, Any]) -> Figure | Gap:
    """A stored `metric_result` row -> a displayable Figure, or a Gap when its result is unavailable (never a value from nothing)."""
    code = str(row["metric_code"])
    label = _METRIC_LABELS.get(code, code.replace("_", " ").capitalize())
    period = row.get("period")
    if period:
        label = f"{label} ({period})"
    available = bool(row["is_available"])
    ref = Ref(RefKind.ENGINE_RESULT, UUID(str(row["id"])), as_of=row["computed_at"])
    if not available:
        return Gap("UNAVAILABLE_RESULT", f"{label} is unavailable: {row.get('unavailable_reason') or 'a required input is missing'}.", ref.id)
    if code.endswith("_PCT"):
        value = format_percent_number(row.get("value_fraction_numerator"), row.get("value_fraction_denominator"))
    else:
        value = format_paise(row.get("value_paise"))
    if value == "UNAVAILABLE":
        return Gap("UNAVAILABLE_RESULT", f"{label} has no stored value.", ref.id)
    return Figure(label, value, register_for(is_available=True, confidence=row.get("confidence")), ref, as_of=row["computed_at"])


@dataclass(slots=True)
class EvidenceCollector:
    tenant_id: UUID
    figures: list[Figure] = field(default_factory=list)
    facts: list[tuple[str, str, str]] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    disclaimers: list[tuple[str, str]] = field(default_factory=list)
    attach: list[str] = field(default_factory=list)
    offers: list[tuple[str, str]] = field(default_factory=list)
    _seen: set[UUID] = field(default_factory=set)

    # ---- sources
    def add_gap(self, message: str) -> None:
        if message not in self.gaps:
            self.gaps.append(message)

    def add_fact(self, label: str, text: str, basis: str = "SOURCE_DERIVED") -> None:
        self.facts.append((label, text, basis))

    def add_entry(self, entry: BusinessStateEntry) -> None:
        for f in entry.figures:
            self._add_figure(f)
        for fact in entry.facts:
            self.add_fact(fact.label, fact.text, fact.basis)
        for g in entry.gaps:
            self.add_gap(g.message)
        if entry.preview_hint:
            self._offer(entry.preview_hint, "See the free CFO preview")

    def add_leg(self, leg: LegResult) -> None:
        label = LEG_LABELS.get(leg.action_key, leg.action_key)
        agent = _AGENT_NAME.get(leg.action_key.split(".", 1)[0].upper(), "that specialist")
        if leg.status in (LegStatus.DENIED, LegStatus.NOT_ENTITLED, LegStatus.FAILED, LegStatus.UNAVAILABLE):
            self.add_gap(self._leg_refusal(leg, label, agent))
            if leg.status is LegStatus.NOT_ENTITLED and leg.action_key.startswith("cfo."):
                self._offer("cfo.preview", "See the free CFO preview")
            return
        if leg.status is LegStatus.PARTIAL:
            self.add_gap(f"{label} returned a partial result.")
        self._leg_facts(leg)
        for ref in leg.figure_refs:
            self._add_ref(ref, label)

    def add_finding_row(self, finding: Mapping[str, Any]) -> None:
        """A stored finding (SYNTHESIZE re-resolves findings through their refs — a detached agent's earlier, verified findings stay usable)."""
        label = LEG_LABELS.get(str(finding["action_key"]), str(finding["action_key"]))
        if finding["status"] not in ("COMPLETE", "PARTIAL"):
            self.add_gap(f"{label} did not produce a result ({str(finding['status']).lower().replace('_', ' ')}).")
            return
        for raw in finding.get("figure_refs") or []:
            try:
                self._add_ref(Ref.from_json(raw), label)
            except (KeyError, ValueError):
                self.add_gap(f"A stored reference from {label} was malformed and was left out.")

    # ---- internals
    def _offer(self, key: str, label: str) -> None:
        if (key, label) not in self.offers:
            self.offers.append((key, label))

    def _add_figure(self, figure: Figure) -> None:
        if figure.ref.id in self._seen:
            return
        self._seen.add(figure.ref.id)
        self.figures.append(figure)

    def _add_ref(self, ref: Ref, source_label: str) -> None:
        if ref.id in self._seen:
            return
        row = provenance.load_ref_row(self.tenant_id, ref) if ref.kind is RefKind.ENGINE_RESULT else None
        if row is None:
            if ref.kind is RefKind.ENGINE_RESULT:  # unresolvable or another tenant's: dropped, named (R3)
                self.add_gap(f"A figure from {source_label.lower()} was left out: its source record could not be verified.")
            return
        built = figure_from_metric_row(row)
        if isinstance(built, Gap):
            self.add_gap(built.message)
            self._seen.add(ref.id)
        else:
            self._add_figure(built)

    @staticmethod
    def _leg_refusal(leg: LegResult, label: str, agent: str) -> str:
        if leg.status is LegStatus.NOT_ENTITLED:
            return f"{agent} results are not available on your current plan."
        if leg.status is LegStatus.DENIED:
            if leg.denial is Denial.NOT_ATTACHED:
                return f"{agent} is not attached to this investigation, so {label.lower()} was not run."
            return f"You do not have access to {agent}, so {label.lower()} was not run."
        if leg.status is LegStatus.UNAVAILABLE:
            return f"{label} is not available yet."
        return f"{label} could not be completed."

    def _leg_facts(self, leg: LegResult) -> None:
        payload: Mapping[str, Any] = leg.payload or {}
        if leg.action_key == "cfo.financial_health":
            if payload.get("overallBand"):
                self.add_fact("Overall health band", str(payload["overallBand"]))
            for metric, band in (payload.get("perMetricBands") or {}).items():
                self.add_fact(f"{_METRIC_LABELS.get(str(metric), str(metric))} band", str(band))
            if not payload.get("overallBand"):
                self.add_gap(f"Health bands are unavailable: {payload.get('unavailableReason') or 'the underlying results are missing'}.")
        elif leg.action_key == "cfo.anomaly_check":
            for outcome in payload.get("methods") or []:
                method = str(outcome.get("method", "check")).replace("_", " ").lower()
                flag = outcome.get("flag")
                if flag:
                    self.add_fact(f"Anomaly check ({method})", "an unusual change was flagged" if flag.get("fired") else "no unusual change detected")
                elif outcome.get("insufficientHistory"):
                    self.add_gap(f"The anomaly check ({method}) could not run: there is not enough history yet.")
                elif outcome.get("zeroVariance"):
                    self.add_gap(f"The anomaly check ({method}) could not run: the history does not vary.")
                elif outcome.get("configurationGap"):
                    self.add_gap(f"The anomaly check ({method}) is not configured yet.")
        elif leg.action_key == "cfo.strategic_briefing":
            for signal in payload.get("signals") or []:
                self.add_fact(f"Briefing signal: {str(signal.get('category', 'signal')).replace('_', ' ').lower()}",
                              f"{str(signal.get('severityLabel', 'unrated')).lower()} severity; suggested action type "
                              f"{str(signal.get('recommendedActionType', 'none')).replace('_', ' ').lower()}")

    def _truncate(self) -> tuple[Figure, ...]:
        if len(self.figures) > MAX_FIGURES:
            self.add_gap(f"{len(self.figures) - MAX_FIGURES} more verified results exist and are listed in this investigation's findings.")
        return tuple(self.figures[:MAX_FIGURES])

    # ---- output
    def table(
        self, *, untrusted: Sequence[tuple[str, str]] = (), disclaimers: Sequence[tuple[str, str]] = (), attach: Sequence[str] = (),
    ) -> EvidenceTable:
        """The final table. Figures are re-gated through the provenance gate here as a last defence: a figure whose ref does not resolve
        for this tenant at this instant never reaches the composer (R3)."""
        gated = provenance.gate_figures(self.tenant_id, self._truncate())
        for g in gated.gaps:
            self.add_gap(g.message)
        return EvidenceTable(
            figures=figures_with_tokens(gated.kept),
            facts=tuple(self.facts),
            gaps=tuple((f"G{i}", m) for i, m in enumerate(self.gaps, start=1)),
            disclaimers=tuple((f"D{i}", k, t) for i, (k, t) in enumerate([*self.disclaimers, *disclaimers], start=1)),
            attach=tuple((f"A{i}", a) for i, a in enumerate([*self.attach, *attach], start=1)),
            offers=tuple((f"O{i}", k, lbl) for i, (k, lbl) in enumerate(self.offers, start=1)),
            untrusted=tuple((f"U{i}", s, t) for i, (s, t) in enumerate(untrusted, start=1)),
        )
