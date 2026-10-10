"""Turns Business State entries, specialist legs and stored findings into the composer's evidence table — spec §6.5, §6.13, §6.15.

A figure reaches the table only through its REF: it is resolved against the owning table for THIS tenant (`provenance`), formatted by
`figure_format` from the stored value, and dropped with a named gap if it cannot be verified or is unavailable. Specialist payload
text is never copied across except closed enums (band names, severity labels, action types) — free text from a payload could carry
numbers or instructions, so it is not evidence (R9). Nothing here computes anything.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from fractions import Fraction
from typing import Any
from uuid import UUID

from backend.ceo import conflicts as conflict_rules
from backend.ceo import provenance
from backend.ceo.composer import WEB_ARTEFACT_TITLE, EvidenceTable, figures_with_tokens
from backend.ceo.contract import (
    BusinessStateEntry, Conflict, Denial, EntryStatus, Fact, Figure, Gap, LegResult, LegStatus, Ref, RefKind, Register,
)
from backend.ceo.figure_format import format_paise, format_percent_number, format_units, register_for

MAX_CANDIDATES_SHOWN = 10  # how many product ideas one answer lists (a display bound; the rest stay on the Product Intelligence page, said so)
MAX_FIGURES = 12  # how many verified figures one answer carries; the rest stay on the findings (stated as a gap, never dropped silently)

_METRIC_LABELS: Mapping[str, str] = {
    "NET_REALIZED_REVENUE": "Net realized revenue",
    "CONTRIBUTION_PROFIT": "Contribution profit",
    "MARKETPLACE_FEES": "Marketplace fees",
    "CONTRIBUTION_MARGIN_PCT": "Contribution margin",
    "FEE_RATIO_PCT": "Fee ratio",
    "RETURN_RATE_PCT": "Return rate",
    "CASH_RECEIVED": "Cash received",
    "MARGIN_AT_PRICE": "Margin at a candidate price",
    "LANDED_COST_PER_UNIT": "Landed cost per unit",
    "BATCH_CONSTRAINED_QUANTITY": "Most units your budget allows",
}
# Stored results whose value is a unit COUNT carried in the money slot (shown as units, never as rupees).
_UNIT_COUNT_METRICS = frozenset({"BATCH_CONSTRAINED_QUANTITY"})
_CANDIDATE_PRICE_RE = re.compile(r"candidate_price_paise=(-?\d+)")
_SUPPLIER_RE = re.compile(r"supplier=(?:'([^']*)'|\"([^\"]*)\")")


def _label_for_row(code: str, row: Mapping[str, Any]) -> str:
    """The engine writes WHICH candidate price / supplier a row is for into its `calculation_basis`; the label says so, so several rows of one metric are never
    indistinguishable. Display text only: the stored value is untouched."""
    base = _METRIC_LABELS.get(code, code.replace("_", " ").capitalize())
    basis = str(row.get("calculation_basis") or "")
    if code == "MARGIN_AT_PRICE" and (m := _CANDIDATE_PRICE_RE.search(basis)):
        return f"Margin if you sell at {format_paise(int(m.group(1)))}"
    if code == "LANDED_COST_PER_UNIT" and (m := _SUPPLIER_RE.search(basis)):
        return f"{base} ({m.group(1) or m.group(2)})"
    return base

_PI_LIMITS: Mapping[str, str] = {
    "marketplace_price_and_competition": "These ideas have not been checked against live marketplace listings, so their prices and competition are unknown.",
    "demand_signal": "Real sales and demand numbers are not available for these ideas.",
}
_CMO_KINDS: Mapping[str, str] = {
    "TITLE_SET": "Title options", "DESCRIPTION": "Description", "KEYWORDS": "Search keywords", "HASHTAGS": "Hashtags", "BULLETS": "Bullet points",
    "LISTING_COPY": "Listing copy", "BACKEND_TERMS": "Backend search terms",
}
_CMO_ITEMS: Mapping[str, Any] = {
    "TITLE_SET": lambda a: [str(o.get("text")) for o in a.get("options") or [] if o.get("text")],
    "DESCRIPTION": lambda a: [str(a["description"])] if a.get("description") else [],
    "KEYWORDS": lambda a: [str(k) for k in a.get("keywords") or []],
    "HASHTAGS": lambda a: [str(h) for h in a.get("hashtags") or []],
    "BULLETS": lambda a: [str(b) for b in a.get("bullets") or []],
}
LEG_LABELS: Mapping[str, str] = {
    "cmo.generate_title_sets": "The title options",
    "cmo.generate_hashtags": "The hashtags",
    "cmo.generate_description": "The description",
    "cmo.generate_keywords": "The search keywords",
    "cfo.financial_health": "The financial health check",
    "cfo.anomaly_check": "The anomaly check",
    "cfo.strategic_briefing": "The CFO briefing",
    "cfo.reconcile": "The marketplace reconciliation",
    "cfo.cash_reconciliation": "The cash reconciliation",
    "cfo.gst_lookup": "The GST rate lookup",
    "service.gst_lookup": "The GST rate lookup",
    "ci.request_price_scenario": "The competitor price comparison",
    "cfo.pricing": "The margin at each candidate price",
    "cfo.landed_cost": "The landed cost",
    "cfo.supplier_ranking": "The supplier ranking",
    "cfo.batch_size": "The batch size estimate",
    "pi.report": "The product research report",
    "pi.discover": "The product research",
    "BS_COMPETITOR_SNAPSHOT": "The competitor prices",
    "BS_PI_REPORT_LATEST": "The product research status",
    "BS_CMO_WORKFLOW": "The listing content status",
    "BS_PNL_LATEST": "The latest profit and loss",
    "BS_LEAK_OPEN": "The open leak summary",
    "BS_DATA_GAPS": "The list of inputs still needed",
    "BS_HEALTH_BANDS": "The health bands",
    "BS_SELLER_CONTEXT": "Your saved goal and notes",
    "BS_INGEST_STATUS": "The upload status",
}
_AGENT_NAME = {"CFO": "CFO", "CI": "Competitor Intelligence", "PI": "Product Intelligence", "CMO": "CMO", "SERVICE": "The GST lookup"}

_ENTRY_STATUS_FINDING: Mapping[EntryStatus, str] = {
    EntryStatus.AVAILABLE: "COMPLETE", EntryStatus.STALE: "PARTIAL", EntryStatus.PARTIAL: "PARTIAL", EntryStatus.UNAVAILABLE: "UNAVAILABLE",
    EntryStatus.NOT_ENTITLED: "NOT_ENTITLED", EntryStatus.NOT_PERMITTED: "DENIED", EntryStatus.NOT_ATTACHED: "DENIED",
}


def finding_status_for_entry(status: EntryStatus) -> str:
    return _ENTRY_STATUS_FINDING[status]


def figure_from_metric_row(row: Mapping[str, Any]) -> Figure | Gap:
    """A stored `metric_result` row -> a displayable Figure, or a Gap when its result is unavailable (never a value from nothing)."""
    code = str(row["metric_code"])
    label = _label_for_row(code, row)
    period = row.get("period")
    if period:
        label = f"{label} ({period})"
    available = bool(row["is_available"])
    ref = Ref(RefKind.ENGINE_RESULT, UUID(str(row["id"])), as_of=row["computed_at"])
    if not available:
        return Gap("UNAVAILABLE_RESULT", f"{label} is unavailable: {row.get('unavailable_reason') or 'a required input is missing'}.", ref.id)
    if code.endswith("_PCT"):
        value = format_percent_number(row.get("value_fraction_numerator"), row.get("value_fraction_denominator"))
    elif code in _UNIT_COUNT_METRICS:
        value = format_units(row.get("value_paise"))
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
    conflicts: list[Conflict] = field(default_factory=list)
    artefacts: list[tuple[str, tuple[str, ...], str | None]] = field(default_factory=list)
    _seen: set[UUID] = field(default_factory=set)

    # ---- sources
    def add_gap(self, message: str) -> None:
        if message not in self.gaps:
            self.gaps.append(message)

    def add_fact(self, label: str, text: str, basis: str = "SOURCE_DERIVED") -> None:
        self.facts.append((label, text, basis))

    def add_conflict(self, conflict: Conflict) -> None:
        """A stored disagreement (spec §6.32). Both sides are shown only inside the conflict block, so neither is ever listed as a plain figure."""
        if any({c.a.ref.id, c.b.ref.id} == {conflict.a.ref.id, conflict.b.ref.id} for c in self.conflicts):
            return
        self.conflicts.append(conflict)
        self._seen.update((conflict.a.ref.id, conflict.b.ref.id))

    def add_entry(self, entry: BusinessStateEntry) -> None:
        for c in entry.conflicts:
            self.add_conflict(c)
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
        for stored in (finding.get("presentation") or {}).get("conflicts") or []:  # a stored disagreement is carried forward as a named gap, never as two plain figures
            try:
                self._seen.update(UUID(str(i)) for i in stored["refIds"])
                self.add_gap(f"{stored['what']} had two different stored values that disagree; neither was chosen. Open that earlier answer to see both.")
            except (KeyError, TypeError, ValueError):
                self.add_gap(f"A stored disagreement from {label} was malformed and was left out.")
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
        elif leg.action_key in ("cfo.gst_lookup", "service.gst_lookup"):
            self._gst_result(payload)
        elif leg.action_key == "pi.report":
            self._pi_candidates(payload)
        elif leg.action_key.startswith("cmo."):
            self._cmo_artefacts(payload)
        elif leg.action_key == "cfo.strategic_briefing":
            for signal in payload.get("signals") or []:
                self.add_fact(f"Briefing signal: {str(signal.get('category', 'signal')).replace('_', ' ').lower()}",
                              f"{str(signal.get('severityLabel', 'unrated')).lower()} severity; suggested action type "
                              f"{str(signal.get('recommendedActionType', 'none')).replace('_', ' ').lower()}")

    def _pi_candidates(self, payload: Mapping[str, Any]) -> None:
        """Product ideas Product Intelligence found on the public web: their names, quoted and labelled. They are not figures, carry no sales data and are never
        verified here; the scores, sources and supplier leads stay on the Product Intelligence page."""
        rows = payload.get("candidates") or []
        names: list[str] = []
        for row in rows[:MAX_CANDIDATES_SHOWN]:
            c = row.get("candidate") or {}
            title = " ".join(str(c.get("candidate_title") or "").split())
            if not title:
                continue
            names.append(title[:140])  # the name only: the label PI stores is internal ("candidate opportunity") and says nothing to a seller
        if not names:
            self.add_gap("The research run finished but found no product ideas to show for that niche. Try a broader niche.")
        else:
            more = len(rows) - len(names)
            self.artefacts.append((
                WEB_ARTEFACT_TITLE, tuple(names),
                "From public web sources and not verified: this is not your sales data, and Product Intelligence has not measured demand or margin for these."
                + (f" {more} more are on the Product Intelligence page." if more > 0 else ""),
            ))
        for u in payload.get("unavailable") or []:  # PI's own notes are for developers; the seller is told the plain consequence, by field
            field = str(u.get("field") or "")
            self.add_gap(_PI_LIMITS.get(field, "The research run was only partly complete, so some ideas may be missing." if field == "run_completeness" else "Some information was not available for these ideas."))

    def _cmo_artefacts(self, payload: Mapping[str, Any]) -> None:
        """What CMO wrote. The text is the specialist's own content, shown quoted and labelled; it is never a figure and is not run through the money provenance path.
        A failed artefact is a named gap, not a result."""
        arts = payload.get("artefacts") or []
        if not arts:
            self.add_gap("The writing run returned nothing.")
        for a in arts:
            kind = _CMO_KINDS.get(str(a.get("outputType")), "Content")
            where = f" for {str(a['marketplace']).title()}" if a.get("marketplace") else ""
            if a.get("status") != "COMPLETE":
                failure = a.get("failure") or {}
                missing = ", ".join(str(m) for m in (failure.get("missingFacts") or []))
                self.add_gap(f"{kind}{where} could not be written" + (f": more detail is needed about {missing}." if missing else "."))
                continue
            items = _CMO_ITEMS.get(str(a.get("outputType")), lambda x: [])(a)
            if not items:
                self.add_gap(f"{kind}{where} came back empty.")
                continue
            cite = a.get("constraint") or {}
            note = f"Fitted to the marketplace rule from {cite['sourceUrl']}, checked {cite['verifiedAt']}" if cite.get("sourceUrl") and cite.get("verifiedAt") else None
            self.artefacts.append((f"{kind}{where}", tuple(items), note))

    @staticmethod
    def _rate_text(raw: Any) -> str | None:
        """A stored rate (an exact `Fraction` rendered as text, e.g. "18" or "1/4") shown as a percentage. Never a float: whole rates stay whole."""
        try:
            f = Fraction(str(raw))
        except (ValueError, ZeroDivisionError):
            return None
        return f"{f.numerator}%" if f.denominator == 1 else format_percent_number(f.numerator, f.denominator)

    def _gst_result(self, payload: Mapping[str, Any]) -> None:
        """The stored, PROVISIONAL lookup (spec G3): the rate is copied from the stored row and cited by its ref; it is never labelled verified."""
        result = payload.get("result")
        if not result:
            self.add_gap("No GST rate could be found for that product from the public sources I am allowed to use. Please ask your accountant.")
            return
        rate = result.get("likelyRatePct")
        try:
            ref_id = UUID(str(result["id"]))
            retrieved = datetime.fromisoformat(str(result["retrievedAt"]))
        except (KeyError, ValueError):
            self.add_gap("A GST lookup result could not be verified and was left out.")
            return
        shown = self._rate_text(rate)
        if rate is None or shown is None:
            self.add_gap("The lookup found no single GST rate for that product. Please ask your accountant.")
        else:
            self._add_figure(Figure(
                label="Likely GST rate (provisional)", formatted_value=shown, register=Register.DERIVED,
                ref=Ref(RefKind.AGENT_REPORT_FIELD, ref_id, source="gst_lookup_result", as_of=retrieved), as_of=retrieved,
                note="Looked up from a cited public source. It is not confirmed for your product and is never applied to your numbers.",
            ))
        others = [s for a in result.get("alternatives") or [] if a.get("ratePct") is not None and (s := self._rate_text(a["ratePct"])) is not None]
        if others:
            self.add_fact("Other GST rates that may apply", ", ".join(others))

    def shown_figures(self) -> list[Figure]:
        """The plain figures: those not already shown as a side of a conflict block."""
        sides = {i for c in self.conflicts for i in (c.a.ref.id, c.b.ref.id)}
        return [f for f in self.figures if f.ref.id not in sides]

    def verified_conflicts(self) -> list[Conflict]:
        """Each conflict whose BOTH sides still resolve for this tenant; otherwise it is not shown and is named as a gap (never one side alone)."""
        kept: list[Conflict] = []
        for c in self.conflicts:
            gated = provenance.gate_figures(self.tenant_id, (c.a, c.b))
            if len(gated.kept) == 2:
                kept.append(Conflict(c.kind, c.what, gated.kept[0], gated.kept[1]))
            else:
                self.add_gap(f"{c.what} has two stored values that disagree, but one could not be verified, so neither is shown.")
        return kept

    def _truncate(self) -> tuple[Figure, ...]:
        plain = self.shown_figures()
        if len(plain) > MAX_FIGURES:
            self.add_gap(f"{len(plain) - MAX_FIGURES} more verified results exist and are listed in this investigation's findings.")
        return tuple(plain[:MAX_FIGURES])

    # ---- output
    def table(
        self, *, untrusted: Sequence[tuple[str, str]] = (), disclaimers: Sequence[tuple[str, str]] = (), attach: Sequence[str] = (),
    ) -> EvidenceTable:
        """The final table. Figures are re-gated through the provenance gate here as a last defence: a figure whose ref does not resolve
        for this tenant at this instant never reaches the composer (R3)."""
        gated = provenance.gate_figures(self.tenant_id, self._truncate())
        for g in gated.gaps:
            self.add_gap(g.message)
        verified = self.verified_conflicts()
        return EvidenceTable(
            figures=figures_with_tokens(gated.kept),
            facts=tuple(self.facts),
            gaps=tuple((f"G{i}", m) for i, m in enumerate(self.gaps, start=1)),
            disclaimers=tuple((f"D{i}", k, t) for i, (k, t) in enumerate([*self.disclaimers, *disclaimers], start=1)),
            attach=tuple((f"A{i}", a) for i, a in enumerate([*self.attach, *attach], start=1)),
            offers=tuple((f"O{i}", k, lbl) for i, (k, lbl) in enumerate(self.offers, start=1)),
            untrusted=tuple((f"U{i}", s, t) for i, (s, t) in enumerate(untrusted, start=1)),
            conflicts=tuple((f"C{i}", c.what, conflict_rules.render(c)) for i, c in enumerate(verified, start=1)),
            artefacts=tuple(self.artefacts),
        )
