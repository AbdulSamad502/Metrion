"""Turns Business State entries, specialist legs and stored findings into the composer's evidence table — spec §6.5, §6.13, §6.15.

A figure reaches the table only through its REF: it is resolved against the owning table for THIS tenant (`provenance`), formatted by
`figure_format` from the stored value, and dropped with a named gap if it cannot be verified or is unavailable. Specialist payload
text is never copied across except closed enums (band names, severity labels, action types) — free text from a payload could carry
numbers or instructions, so it is not evidence (R9). Nothing here computes anything.
"""

from __future__ import annotations

import logging
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
from backend.ceo import plain_reasons
from backend.ceo.contract import (
    BusinessStateEntry, Conflict, Denial, EntryStatus, Fact, Figure, Gap, LegResult, LegStatus, Ref, RefKind, Register,
)
from backend.ceo.figure_format import format_paise, format_percent_number, format_ratio_as_percent, format_ratio_x, format_units, register_for

logger = logging.getLogger(__name__)

BATCH_PARTIAL_TEXT = "The most units your budget allows could not be worked out: for a product with no sales history it needs the supplier's minimum order quantity or delivery time, and the saved quote has neither"
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
    "EXPENSE_TOTAL": "Expenses in your ledger",
    "EXPENSE_INCLUDING_UNRESOLVED": "Expenses including entries awaiting review",
    "EXPENSE_REVIEW_QUEUE_AMOUNT": "Expenses awaiting your review",
    "EXPENSE_RECURRING_TOTAL": "Recurring expenses",
}
# Stored results whose value is a unit COUNT carried in the money slot (shown as units, never as rupees).
_UNIT_COUNT_METRICS = frozenset({"BATCH_CONSTRAINED_QUANTITY"})
# Results whose unit this formatter does not render: named as a gap pointing at the dashboard, never shown as rupees.
_NOT_IN_CHAT = frozenset({"SETTLEMENT_LAG_DAYS", "CASH_SHORTFALL_STATUS"})
_CANDIDATE_PRICE_RE = re.compile(r"candidate_price_paise=(-?\d+)")
_SUPPLIER_RE = re.compile(r"supplier=(?:'([^']*)'|\"([^\"]*)\")")


def _label_for_row(code: str, row: Mapping[str, Any]) -> str:
    """The engine writes WHICH candidate price / supplier a row is for into its `calculation_basis`; the label says so, so several rows of one metric are never
    indistinguishable. Display text only: the stored value is untouched."""
    base = _METRIC_LABELS.get(code, code.replace("_", " ").capitalize())
    if code == "EXPENSE_BY_CATEGORY" and "|expense|" in str(row.get("target_ref") or ""):  # the ledger mints one result per category and class, and one for the whole period
        tail = str(row["target_ref"]).split("|expense|", 1)[1].split("|")
        base = "Expenses in your ledger (all categories)" if tail[0] == "ALL" else f"Expenses: {tail[0]}" + ("" if len(tail) < 2 or tail[1] == "OTHER_UNCLASSIFIED" else f" ({tail[1].replace('_', ' ').lower()})")
    basis = str(row.get("calculation_basis") or "")
    if code == "MARGIN_AT_PRICE" and (m := _CANDIDATE_PRICE_RE.search(basis)):
        return f"Margin if you sell at {format_paise(int(m.group(1)))}"
    if code == "PRICE_POSITIONING" and (m := re.search(r"vs (\w+) \(reference_price_paise=\d+, gap_pct=(-?[\d.]+)%(?:, gap_pct_of_seller_price=(-?[\d.]+)%)?", basis)):
        word = {"AVERAGE": "average", "MIN": "lowest", "MAX": "highest"}.get(m.group(1), m.group(1).lower())
        mine = f"{m.group(3)}% of your price, " if m.group(3) else ""
        return f"Your price compared with the competitor's {word} price ({mine}{m.group(2)}% of the competitor's price; a plus means you are higher)"
    if code == "LANDED_COST_PER_UNIT" and (m := _SUPPLIER_RE.search(basis)):
        return f"{base} ({m.group(1) or m.group(2)})"
    return base

_PI_LIMITS: Mapping[str, str] = {
    "marketplace_price_and_competition": "These ideas have not been checked against live marketplace listings, so their prices and competition are unknown.",
    "demand_signal": "Real sales and demand numbers are not available for these ideas.",
}
MAX_TREND_ITEMS = 4
_CMO_KINDS: Mapping[str, str] = {
    "TITLE_SET": "Title options", "DESCRIPTION": "Description", "KEYWORDS": "Search keywords", "HASHTAGS": "Hashtags", "BULLETS": "Bullet points",
    "LISTING_COPY": "Listing copy", "BACKEND_TERMS": "Backend search terms", "CATALOG_ANSWER": "Product details",
}
_BASIS_WORDS: Mapping[str, str] = {
    "SELLER_PROVIDED": "you told me", "IMAGE_OBSERVED": "seen in your photo", "SOURCE_DERIVED": "from a cited source",
    "ESTIMATED": "an estimate, confirm it before you list", "UNKNOWN": "not known yet",
}


def _catalog_item(x: Mapping[str, Any]) -> str:
    """One catalog answer line: the value only if there is one, and always how sure it is. An unknown stays unknown; it is never filled in."""
    name = str(x.get("attribute") or "detail").replace("_", " ").title()
    basis = _BASIS_WORDS.get(str(x.get("basis")), "not known yet")
    value = x.get("value")
    if value in (None, ""):
        est = x.get("estimate") or {}
        sug = (x.get("suggestion") or {}).get("text")
        guess = f" Suggestion: {sug}." if sug else ""
        return f"{name}: not known yet ({basis}).{guess}" + (" Tell me this and I will use it." if x.get("requiresSellerInput") else "") + (f" Estimate: {est}." if est and not sug else "")
    return f"{name}: {value} ({basis})"

def _counted(text: str, a: Mapping[str, Any], stored: Any = None) -> str:
    """The text with its length, counted by CODE: the CMO's own stored count for a title, else the marketplace's counting rule applied here (UTF-16 code units unless the
    stored rule says otherwise). Never a model's figure."""
    n = stored if isinstance(stored, int) and not isinstance(stored, bool) else (
        len(text.encode("utf-16-le")) // 2 if (a.get("countRule") or "UTF16_CODE_UNITS") == "UTF16_CODE_UNITS" else len(text))
    return text  # the chat shows clean text; the character count is on the Slim CMO dashboard (n is still computed by code for it)


_CMO_ITEMS: Mapping[str, Any] = {
    "TITLE_SET": lambda a: [_counted(str(o.get("text")), a, o.get("charCount")) for o in a.get("options") or [] if o.get("text")],
    "DESCRIPTION": lambda a: [_counted(str(a["description"]), a)] if a.get("description") else [],
    "KEYWORDS": lambda a: [str(k) for k in a.get("keywords") or []],
    "HASHTAGS": lambda a: [str(h) for h in a.get("hashtags") or []],
    "BULLETS": lambda a: [_counted(str(b), a) for b in a.get("bullets") or []],
    "LISTING_COPY": lambda a: ([f"Description: {_counted(str(a['description']), a)}"] if a.get("description") else [])
    + [_counted(str(b), a) for b in a.get("bullets") or []]
    + ([f"Keywords: {', '.join(str(k) for k in a['keywords'])}"] if a.get("keywords") else []),
    "CATALOG_ANSWER": lambda a: [_catalog_item(x) for x in a.get("attributes") or [] if isinstance(x, Mapping)],
    "BACKEND_TERMS": lambda a: ([f"{' '.join(str(t) for t in a['terms'])} ({a['byteCount']} bytes)" if isinstance(a.get("byteCount"), int) and not isinstance(a.get("byteCount"), bool)
                                else ' '.join(str(t) for t in a['terms'])] if a.get("terms") else []),
}
def _trend_sources(finding: Mapping[str, Any]) -> str:
    """The sources behind one trend finding, as the report recorded them: the title, the address and the publication date (or 'date not given'). Copied, never written by a model."""
    out: list[str] = []
    for src in (finding.get("sources") or [])[:2]:
        if not isinstance(src, Mapping) or not src.get("url"):
            continue
        published = str(src.get("published_at") or "")[:10] or "date not given"
        title = " ".join(str(src.get("title") or "").split())[:80]
        out.append(f"{title + ' - ' if title else ''}{src['url']} (published {published})")
    return " [Source: " + "; ".join(out) + "]" if out else ""


_PLANNER_REFUSAL: Mapping[str, str] = {
    "PLANNER_OFF": "open financial questions are not switched on for this workspace yet",
    "PLANNER_ERROR": "I could not work out how to answer it right now",
    "PLAN_MALFORMED": "I could not turn it into a query I can check",
    "PLAN_INVALID": "it needs something I cannot compute from your saved data yet",
    "DATA_CHANGED": "your data changed while I was working, so ask again in a moment",
    "PLAN_CHECK_FAILED": "I could not verify the answer, so I am not giving it",
}
_CMO_FAILURE_WHY: Mapping[str, str] = {
    "VALIDATION_FAILED": "it could not be written from the details you confirmed without adding things you did not tell me, so nothing was invented. Add the brand, size or capacity and 1-3 key features, then ask again",
    "UNPARSEABLE_OUTPUT": "the writing service's reply could not be read, so nothing was used. Ask again in a moment",
    "OUTPUT_TOO_LARGE": "the writing service's reply was unusably large, so nothing was used. Ask again",
    "PROVIDER_ERROR": "the writing service did not answer, so nothing was written. Ask again in a moment",
    "CONSTRAINT_BLOCKED": "there is no verified marketplace rule to write against yet, so I did not guess one",
    "CONFIG_MISSING": "a setting it needs has not been configured by the operator yet",
}


def _cmo_failure_text(kind: str, where: str, failure: Mapping[str, Any]) -> str:
    """Why a CMO artefact was not delivered, in plain words (never internals: no attempt counts, rule ids or model text). Nothing was used up."""
    head = f"{kind}{where} could not be written"
    missing = ", ".join(str(m) for m in (failure.get("missingFacts") or []))
    if missing:
        return f"{head}: more detail is needed about {missing}."
    why = _CMO_FAILURE_WHY.get(str(failure.get("code")))
    return f"{head}: {why}." if why else f"{head}."


def _cmo_rule_note(a: Mapping[str, Any]) -> str | None:
    """The marketplace rule an artefact was fitted to, and how far to trust it. A test-fixture (or otherwise unsourced) rule is said to be exactly that, never presented as the
    marketplace's real rule; a thin set of confirmed details is flagged."""
    cite = a.get("constraint") or {}
    notes: list[str] = []
    if cite:
        unsourced = cite.get("ruleKind") == "TEST_FIXTURE" or ".invalid" in str(cite.get("sourceUrl") or "")
        if unsourced:
            notes.append("Length rule used: placeholder limits for testing, NOT a verified marketplace rule. Check the real limit in your seller account before using this text.")
        elif cite.get("sourceUrl") and cite.get("verifiedAt"):
            notes.append(f"Fitted to the marketplace rule from {cite['sourceUrl']}, checked {cite['verifiedAt']}")
    if a.get("thinInput"):
        notes.append(f"Thin input - add brand/size/features for stronger {'titles' if a.get('outputType') == 'TITLE_SET' else 'results'}.")
    return " ".join(notes) or None


LEG_LABELS: Mapping[str, str] = {
    "ci.discover_competitors": "The competitor search",
    "ci.monitor_competitors": "The competitor check",
    "ci.review_findings": "The review summary",
    "ci.request_price_scenario": "The price comparison",
    "ci.competitor_remove": "Stopping the tracking",
    "cmo.generate_title_sets": "The title options",
    "cmo.generate_hashtags": "The hashtags",
    "cmo.generate_description": "The description",
    "cmo.generate_keywords": "The search keywords",
    "cmo.generate_bullets": "The bullet points",
    "cmo.generate_backend_terms": "The backend search terms",
    "cmo.generate_listing_copy": "The listing copy",
    "cmo.generate_full_listing": "The complete listing",
    "cmo.rewrite_listing_section": "The rewritten section",
    "cmo.analyze_attachment": "The reading of your photo",
    "cmo.approve_title": "Your title choice",
    "cmo.keyword_intelligence": "The keyword research",
    "cmo.analyze_titles": "The title comparison",
    "cmo.catalog_answer": "The product details",
    "cmo.confirm_image_hint": "Your photo confirmation",
    "cmo.market_trends": "The market trend research",
    "cmo.market_trends_preview": "The market research plan",
    "cfo.financial_health": "The financial health check",
    "cfo.anomaly_check": "The anomaly check",
    "cfo.strategic_briefing": "The CFO briefing",
    "cfo.query": "The answer to your financial question",
    "cfo.expense_summary": "Your expenses",
    "cfo.expense_add": "Adding your expense", "cfo.expense_correct": "Changing your expense", "cfo.expense_void": "Removing your expense", "cfo.expense_paid": "Updating your expense",
    "cfo.import_attachments": "Adding your reports to your financial records", "cfo.cash_position": "Your cash position", "cfo.performance": "How your business performed",
    "cfo.reconcile": "The marketplace reconciliation",
    "cfo.cash_reconciliation": "The cash reconciliation",
    "cfo.gst_lookup": "The GST rate lookup",
    "service.gst_lookup": "The GST rate lookup",
    "ci.request_price_scenario": "The competitor price comparison",
    "ci.evidence_intake": "The reading of your competitor screenshot",
    "ci.confirm_field": "The confirmation of the competitor details",
    "ci.competitor_add": "The competitor you asked to track",
    "ci.competitor_remove": "The competitor you asked to stop tracking",
    "ci.competitor_approve": "The competitor you approved",
    "ci.competitor_reject": "The competitor you rejected",
    "ci.monitor_competitors": "The check of your tracked competitors",
    "ci.review_findings": "What competitor reviews say",
    "ci.explain_finding": "The finding you asked about",
    "ci.alert_settings_set": "Your competitor alert settings",
    "ci.review_intake": "The reading of your competitor reviews screenshot",
    "cfo.pricing": "The margin at each candidate price",
    "cfo.landed_cost": "The landed cost",
    "cfo.supplier_ranking": "The supplier ranking",
    "cfo.batch_size": "The batch size estimate",
    "pi.report": "The product research report",
    "pi.discover": "The product research",
    "pi.supplier_lookup": "The supplier lookup for the five shortlisted products",
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
    if code in _NOT_IN_CHAT:
        return Gap("UNAVAILABLE_RESULT", f"{label} is shown on the CFO dashboard rather than in chat.", ref.id)
    if code.endswith("_PCT"):
        value = format_percent_number(row.get("value_fraction_numerator"), row.get("value_fraction_denominator"))
    elif code == "ROAS":
        value = format_ratio_x(row.get("value_fraction_numerator"), row.get("value_fraction_denominator"))
    elif code in ("ACOS", "TACOS"):
        value = format_ratio_as_percent(row.get("value_fraction_numerator"), row.get("value_fraction_denominator"))
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
    ci_legs: bool = False  # a Competitor Intelligence result is in this evidence: the composition gate then applies the CI narration rules
    finance_legs: bool = False  # a finance result is too, so a price / margin implication may be stated from it
    _seen: set[UUID] = field(default_factory=set)
    _pp_values: set = field(default_factory=set)  # price-comparison gaps already shown (one competitor gives the same gap against its average, lowest and highest)

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
        for key, label in entry.offers:
            self._offer(key, label)
        self.artefacts.extend(entry.artefacts)

    def add_leg(self, leg: LegResult) -> None:
        label = LEG_LABELS.get(leg.action_key, leg.action_key)
        agent = _AGENT_NAME.get(leg.action_key.split(".", 1)[0].upper(), "that specialist")
        if leg.status in (LegStatus.DENIED, LegStatus.NOT_ENTITLED, LegStatus.FAILED, LegStatus.UNAVAILABLE):
            self.add_gap(self._leg_refusal(leg, label, agent))
            if leg.status is LegStatus.NOT_ENTITLED and leg.action_key.startswith("cfo."):
                self._offer("cfo.preview", "See the free CFO preview")
            return
        if leg.status is LegStatus.PARTIAL:
            if leg.action_key == "ci.discover_competitors":
                pass  # the search finished; its own result (below) says what it found, so no generic "partial" notice that names an internal action
            elif leg.action_key == "cfo.batch_size":  # the usual cause, in plain words (live run 2026-10-14): a product never sold needs the supplier's minimum order or delivery time
                self.add_gap(BATCH_PARTIAL_TEXT)
            else:
                self.add_gap(f"{label} returned a partial result.")
        if leg.action_key.startswith("ci."):
            self.ci_legs = True
        elif leg.action_key.startswith("cfo."):
            self.finance_legs = True
        snapshot = (len(self.facts), len(self.gaps), len(self.artefacts), len(self.attach), len(self.offers))
        try:
            self._leg_facts(leg)
        except Exception:  # noqa: BLE001 — a result with the wrong inner shape costs only its own leg: nothing half-read is shown, and the other legs still reach the seller
            logger.exception("could not read the result of %s", leg.action_key)
            del self.facts[snapshot[0]:], self.artefacts[snapshot[2]:], self.attach[snapshot[3]:], self.offers[snapshot[4]:]
            self.add_gap(f"{label} returned a result that could not be read, so it is not shown.")
            return
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
        if str(row.get("metric_code")) == "PRICE_POSITIONING" and not isinstance(built, Gap):
            key = (row.get("value_paise"), "PRICE_POSITIONING")
            if key in self._pp_values:  # one competitor gives the same gap as its average, lowest and highest: said once
                self._seen.add(ref.id)
                return
            self._pp_values.add(key)
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
        elif leg.action_key == "cfo.batch_size":
            if leg.status in (LegStatus.COMPLETE, LegStatus.PARTIAL) and not payload.get("dataRequestId"):
                self.add_fact("About \"Most units your budget allows\"", "this is the largest quantity your budget and the supplier's minimum order allow. It is a ceiling, not a recommendation to buy that many and not a sales forecast.", "SOURCE_DERIVED")
        elif leg.action_key == "ci.monitor_competitors":
            self._ci_monitor(payload)
        elif leg.action_key == "ci.review_findings":
            self._ci_reviews(payload)
        elif leg.action_key == "ci.discover_competitors":
            self._ci_discovery(payload)
        elif leg.action_key == "ci.competitor_remove":
            self.add_fact("Competitor removed", "it is no longer tracked; its history is kept" if payload.get("status") == "OK" else "it could not be removed", "SOURCE_DERIVED")
        elif leg.action_key == "pi.report":
            self._pi_candidates(payload)
        elif leg.action_key == "cmo.market_trends_preview":
            self.add_fact("Market research plan", "the exact searches a trend run would send were prepared; nothing was sent", "SOURCE_DERIVED")
        elif leg.action_key == "cmo.market_trends":
            self._trend_report(payload)
        elif leg.action_key == "cmo.analyze_attachment":
            pass  # the reading is shown to the seller by the photo-reading step as labelled suggestions; it is not a deliverable and carries no figure
        elif leg.action_key == "cmo.approve_title":
            self._title_choice(payload)
        elif leg.action_key == "cmo.keyword_intelligence":
            self._keyword_intel(payload)
        elif leg.action_key == "cmo.analyze_titles":
            self._title_analysis(payload)
        elif leg.action_key == "cmo.confirm_image_hint":
            pass  # a zero-unit record of the seller's own confirmation; nothing to present
        elif leg.action_key.startswith("cmo."):
            self._cmo_artefacts(payload)
        elif leg.action_key in ("cfo.query", "cfo.performance"):
            self._planner_result(payload)
        elif leg.action_key == "cfo.expense_summary":
            self._expense_summary(payload)
        elif leg.action_key in ("cfo.expense_add", "cfo.expense_correct", "cfo.expense_void", "cfo.expense_paid"):
            self._expense_write(leg.action_key, payload)
        elif leg.action_key == "cfo.import_attachments":
            self._import_result(payload)
        elif leg.action_key == "cfo.cash_position":
            self._cash_position(payload)
        elif leg.action_key == "cfo.strategic_briefing":
            for signal in payload.get("signals") or []:
                self.add_fact(f"Briefing signal: {str(signal.get('category', 'signal')).replace('_', ' ').lower()}",
                              f"{str(signal.get('severityLabel', 'unrated')).lower()} severity; suggested action type "
                              f"{str(signal.get('recommendedActionType', 'none')).replace('_', ' ').lower()}")

    def _expense_summary(self, payload: Mapping[str, Any]) -> None:
        """Expenses from the seller's expense ledger. Totals arrive through their engine results (the leg's refs); each listed entry is a figure that points at its own entry.
        Sentences written here carry no digit; an empty period is said to be empty, never zero."""
        from backend.ceo import expense_chat  # noqa: PLC0415

        if not payload.get("entryCount"):
            self.add_gap("You have no expenses recorded for that period.")
            return
        for e in payload.get("entries") or []:
            self._add_figure(expense_chat.entry_figure(e))
        if payload.get("truncated"):
            self.add_gap("There are more entries than are shown here; the CFO Expenses tab lists every one.")
        if payload.get("heldCount"):
            self.add_gap("Some entries are on hold as a possible duplicate or a possible marketplace deduction. They are not in any total until you review them on the CFO Expenses tab.")
        if any((f.get("expenseClass") == "OTHER_UNCLASSIFIED") for b in payload.get("buckets") or [] for f in b.get("figures") or []):
            self.add_gap("Some expenses have no confirmed class yet, so they are recorded but not counted in Operating Profit until you confirm their class on the CFO Expenses tab.")
        if payload.get("breakdown") == "DAY":
            self.add_fact("How this is cut", "one total for each day that has entries", "SOURCE_DERIVED")
        elif payload.get("breakdown") == "MONTH":
            self.add_fact("How this is cut", "one total for each calendar month", "SOURCE_DERIVED")
        self.add_fact("Where this comes from", "the expenses in your CFO expense ledger; entries on hold are left out of the totals", "SOURCE_DERIVED")

    def _cash_position(self, payload: Mapping[str, Any]) -> None:
        """Expected settlements and payables. The expected-receipts figures arrive through their estimate references (the leg's refs); here: what could not be projected and why, each payable as
        a figure that points at the seller's own entry, and the plain statement of what this is not."""
        from backend.ceo.contract import Figure, Ref, RefKind, Register  # noqa: PLC0415

        if payload.get("status") == "REFUSED":
            self.add_gap("The cash view could not be produced: " + _PLANNER_REFUSAL.get(str(payload.get("code")), "it is outside what I can read from your saved data") + ".")
        for f in payload.get("figures") or []:
            if not f.get("valueDisplay") and not f.get("estimateRef") and not f.get("engineResultRef"):
                why = f.get("unavailableReason") or "a required input is missing"
                self.add_gap(f"{f.get('label') or 'This figure'} cannot be projected yet: {why}. Settlement reports and your open orders are what it is built from.")
        payables = payload.get("payables") or []
        if not payables:
            self.add_fact("Payables", "you have not recorded any payable (money you owe), so none is counted", "SOURCE_DERIVED")
        for p in payables:
            try:
                ref = Ref(RefKind.SELLER_PROVIDED, UUID(str(p["id"])))
            except (ValueError, KeyError):
                continue
            who = f" to {p['supplierRef']}" if p.get("supplierRef") else ""
            self._add_figure(Figure(f"Payable due {p.get('dueDate') or 'on no stated date'}{who}", p["amount"]["display"], Register.MANUAL, ref))
        self.add_fact("What this is", "expected settlements are an estimate from your own settlement history; neither they nor your payables are your bank balance", "SOURCE_DERIVED")

    def _import_result(self, payload: Mapping[str, Any]) -> None:
        """What the importer reported for each approved file, in words written by code from its own report: rows read and saved, what was held, what needs the seller's column mapping."""
        files = payload.get("files") or []
        added = False
        for f in files:
            name, outcome = f.get("filename", "a file"), f.get("outcome")
            rows = f.get("rows") or {}
            if outcome == "IMPORTED":
                added = True
                extra = f"; {rows['held_total']} held for your review" if rows.get("held_total") else ""
                skipped = f"; {rows['duplicate_overlap_with_earlier_uploads']} already there from an earlier upload" if rows.get("duplicate_overlap_with_earlier_uploads") else ""
                self.add_fact(name, f"added to your financial records: {rows.get('posted')} of {rows.get('read')} rows saved{extra}{skipped}", "SOURCE_DERIVED")
            elif outcome == "ALREADY_IMPORTED":
                self.add_fact(name, "this exact file was imported before, so nothing was added twice", "SOURCE_DERIVED")
            elif outcome == "NEEDS_MAPPING":
                self.add_gap(f"{name} was not added: I do not recognise its columns. Open CFO, Data & imports, choose 'Map the columns yourself', confirm the mapping, and it will be added.")
            elif outcome == "STILL_RUNNING":
                self.add_gap(f"{name} is still being imported. Its progress shows on CFO, Data & imports.")
            else:
                self.add_gap(f"{name} was not added: {f.get('reason') or 'the importer refused it'}. Nothing from it was saved.")
        if added:
            self.add_fact("Next", "your CFO dashboard now reads these records. Profit also needs what each product costs you and which orders were returned.", "SOURCE_DERIVED")

    def _expense_write(self, key: str, payload: Mapping[str, Any]) -> None:
        """What an approved expense change did, in words written by code, with the saved entry as a figure that points at itself."""
        from backend.ceo import expense_chat  # noqa: PLC0415

        if payload.get("status") == "REFUSED":
            self.add_gap("The expense ledger did not save this: " + str(payload.get("message") or "it was not accepted") + ". Nothing was changed.")
            return
        rec = payload.get("record")
        replayed = bool(payload.get("replayed")) or payload.get("changed") is False
        if key == "cfo.expense_add":
            self.add_fact("Expense ledger", "this was already saved earlier, so nothing was added twice" if replayed else "saved to your expense ledger", "SOURCE_DERIVED")
            if payload.get("held"):
                self.add_gap("This entry is on hold as a " + ("possible duplicate of one you already have" if payload.get("heldReason") == "POSSIBLE_DUPLICATE" else "possible marketplace deduction")
                             + ", so it is not in any total until you review it on the CFO Expenses tab.")
            elif not replayed:
                self.add_gap("It has no confirmed class yet, so it does not change Operating Profit until you confirm its class on the CFO Expenses tab.")
        elif key == "cfo.expense_correct":
            self.add_fact("Expense ledger", "the earlier entry was replaced by this corrected one and stays in the history", "SOURCE_DERIVED")
        elif key == "cfo.expense_void":
            self.add_fact("Expense ledger", "this entry was already removed" if replayed else "the entry was removed from your totals; it is kept in the history with your reason", "SOURCE_DERIVED")
        else:
            self.add_fact("Expense ledger", "the payment status is unchanged (it was already set)" if replayed else "the payment status was updated; it does not change any profit figure", "SOURCE_DERIVED")
            if rec and rec.get("paymentStatus"):
                self.add_fact("Payment status", str(rec["paymentStatus"]).replace("_", " ").lower(), "SOURCE_DERIVED")
        if rec:
            self._add_figure(expense_chat.entry_figure(rec, prefix="Removed: " if key == "cfo.expense_void" else ""))

    def _planner_result(self, payload: Mapping[str, Any]) -> None:
        """An answer from the CFO query planner (cfo-query-planner.md). The figures themselves arrive through their `engineResultRef`s (resolved against the stored result
        for THIS tenant); this adds only what the seller must also be told, in sentences written here: a refusal, each figure that is unavailable and why in a closed vocabulary,
        each marketplace left out of a total, and the inputs still needed. Nothing from the planner's free text is copied, and no sentence here carries a digit."""
        if payload.get("status") == "REFUSED":
            self.add_gap("That question could not be answered from your saved data: " + _PLANNER_REFUSAL.get(str(payload.get("code")), "it is outside what I can read from your uploaded reports") + ".")
            return
        for f in payload.get("figures") or []:
            metric = str(f.get("metricId") or "")
            name = _METRIC_LABELS.get(metric, metric.replace("_", " ").lower().capitalize() or "A figure")
            if f.get("status") == "UNAVAILABLE":
                self.add_gap(f"{name} is not available: a required input is missing or incomplete, so no number is shown.")
            elif f.get("status") == "PROVISIONAL" or any(str(x).startswith("PARTIAL") for x in f.get("labels") or []):
                self.add_fact(f"About {name.lower()}", "it is provisional or covers only part of the data, so treat it as an interim figure", "SOURCE_DERIVED")
            if f.get("estimateRef"):
                self.add_fact(f"About {name.lower()}", "it is an estimate from your own history, not a measured actual", "SOURCE_DERIVED")
        for c in payload.get("coverage") or []:
            if not c.get("included"):
                self.add_gap(f"{str(c.get('marketplace', 'A marketplace')).title()} is left out of the {str(c.get('metricId', 'figure')).replace('_', ' ').lower()} because its data is incomplete.")
        for _ in payload.get("dataRequests") or []:
            self.add_gap("More information is needed to answer part of this; it is listed on your CFO dashboard.")
            break

    def _ci_monitor(self, payload: Mapping[str, Any]) -> None:
        """A re-check of SAVED competitor evidence (CI spec C40): freshness and verified changes in words. No price is stated here (a price is a figure and reaches the seller only
        through the dashboard or a finance result); no digit appears, so the composer has nothing to restate; a competitor without current evidence is a named gap, never a guess."""
        products = payload.get("products") or []
        if not any(p.get("competitors") for p in products):
            self.add_gap("No competitors are tracked yet, so there is nothing to re-check.")
            return
        words = {"FRESH": "its newest screenshot is recent", "STALE": "its newest screenshot is getting old"}
        for p in products:
            for c in (p.get("competitors") or [])[:8]:
                label = " ".join(str(c.get("label") or "A competitor").split())[:80]
                if c.get("freshness") in words:
                    change = ""
                    if c.get("verifiedDeltaPct") and c.get("deltaDirection"):
                        change = "; a verified price " + ("drop" if c["deltaDirection"] == "DECREASE" else "rise") + " was recorded between its last two screenshots"
                    self.add_fact(label, words[str(c["freshness"])] + change, "SOURCE_DERIVED")
                if c.get("requestedAction"):
                    self.add_gap(f"{label}: there is no current evidence, so I cannot say what it charges now. The seller can {c['requestedAction']}.")
        self.add_fact("How this was checked", "from the screenshots the seller already sent; nothing was looked up on any marketplace and nothing is watched between screenshots", "SOURCE_DERIVED")

    def _ci_reviews(self, payload: Mapping[str, Any]) -> None:
        rows = payload.get("findings") or []
        if not rows:
            self.add_gap("There is no saved competitor review evidence yet. The seller can send a screenshot of a competitor's reviews.")
            return
        for r in rows[:6]:
            label = " ".join(str(r.get("label") or "A competitor").split())[:80]
            themes = r.get("complaintThemes")
            names = [t["theme"] if isinstance(t, dict) else str(t) for t in themes] if isinstance(themes, list) else list((themes or {}).keys())
            n = r.get("reviewsConsidered")
            if isinstance(n, int) and r.get("reviewInsightId"):  # the number of reviews read is a stored figure with its source, never a number the model types
                when = datetime.fromisoformat(str(r["derivedAt"])) if r.get("derivedAt") else None
                self._add_figure(Figure(f"Reviews read for {label}", str(n), Register.DERIVED, Ref(RefKind.AGENT_REPORT_FIELD, UUID(str(r["reviewInsightId"])), source="competitor_review_insight", as_of=when), as_of=when))
            praise = r.get("positiveThemes")
            pos = [t["theme"] if isinstance(t, dict) else str(t) for t in praise] if isinstance(praise, list) else list((praise or {}).keys())
            text = ("customers mention: " + ", ".join(str(x)[:60] for x in names[:4])) if names else "no recurring complaint was found in the reviews that were read"
            if pos:
                text += "; praised: " + ", ".join(str(x)[:60] for x in pos[:3])
            self.add_fact(label, text, "SOURCE_DERIVED")
        missing = payload.get("competitorsWithoutReviewEvidence")
        if isinstance(missing, int) and missing > 0:
            self.add_gap(f"{missing} tracked competitor{'s have' if missing != 1 else ' has'} no review screenshot yet, so nothing can be said about {'them' if missing != 1 else 'it'}. The seller can send one.")
        self.add_fact("About these themes", "they come from a small sample of reviews in screenshots the seller sent, not from all of a competitor's reviews", "SOURCE_DERIVED")

    def _ci_discovery(self, payload: Mapping[str, Any]) -> None:
        status = str(payload.get("status") or "")
        if status in ("FAILED",):
            self.add_gap("The competitor search did not complete, so finding nothing does not mean there are no competitors.")
        elif status in ("PARTIAL",):
            self.add_gap("The competitor search only partly completed, so more competitors may exist.")
        else:
            self.add_fact("Competitor search", "finished; what it found are search leads, not verified prices. The ones that look like the seller's product are on the Competitors page under \"Found, awaiting your decision\", and the seller can say \"show me what you found\" to see them and decide", "SOURCE_DERIVED")

    def _pi_candidates(self, payload: Mapping[str, Any]) -> None:
        """Product ideas Product Intelligence found on the public web: their names, quoted and labelled. They are not figures, carry no sales data and are never
        verified here; the scores, sources and supplier leads stay on the Product Intelligence page."""
        five = payload.get("topFive") or []
        if five:  # a finished research case: the numbering the seller sees (#1..#5) is the rank, and only these five are described
            names = [" ".join(str(t.get("title") or "").split())[:140] for t in five if t.get("title")]
            self.artefacts.append((
                WEB_ARTEFACT_TITLE, tuple(names),
                "The five shortlisted products in rank order, from public web sources and not verified: this is not your sales data. The full saved report is on the Product Intelligence page.",
            ))
            for u in payload.get("unavailable") or []:
                field = str(u.get("field") or "")
                self.add_gap(_PI_LIMITS.get(field, "The research run was only partly complete, so some ideas may be missing." if field == "run_completeness" else "Some information was not available for these ideas."))
            return
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

    def _trend_report(self, payload: Mapping[str, Any]) -> None:
        """The market-trend report (spec 6.40): what public web sources said, quoted and labelled. Findings are attention in the press and online, never demand or sales,
        and are not verified here; a section that could not be built is a named gap, never filled in."""
        if payload.get("status") != "COMPLETE":
            self.add_gap("The market research did not complete" + (f": {payload['failureReason']}." if payload.get("failureReason") else "."))
            return
        report = payload.get("report") or {}
        labels = {"NICHE": "Your niche", "MARKET_NEWS": "Marketplace news", "REPORTED_TACTICS": "Tactics sellers report", "NEW_PRODUCTS_BUZZ": "New product buzz", "ADJACENT": "Related niches"}
        note = "From public web sources and not verified. This shows attention in the press and online, not demand or your sales."
        for sec, body in (report.get("sections") or {}).items():
            label = labels.get(str(sec), str(sec).replace("_", " ").title())
            items = [" ".join(f"{f.get('theme', '')}. {f.get('summary', '')}".split())[:260] + _trend_sources(f) for f in (body.get("findings") or [])[:MAX_TREND_ITEMS]]
            if body.get("state") == "COMPLETE" and items:
                self.artefacts.append((f"Market trends: {label}", tuple(items), note))
            else:
                self.add_gap(f"{label}: " + (str(body.get("reason")) if body.get("reason") else "nothing supported by the sources was found") + ".")
        interp = report.get("interpretation") or {}
        stmts = [" ".join(str(i.get("statement", "")).split())[:260] for i in (interp.get("items") or [])[:MAX_TREND_ITEMS] if i.get("statement")]
        if stmts:
            self.artefacts.append(("What the CMO makes of it", tuple(stmts), "The CMO's reading of the findings above, not verified. Decide for yourself before acting on it."))

    def _title_analysis(self, payload: Mapping[str, Any]) -> None:
        """The title options with their 0-100 internal quality score, the points of each criterion and why points were lost, quoted as saved. Marketplace compliance is shown beside
        the score, never inside it. A hard failure is stated first and that option is never the recommendation, whatever its score. A criterion that could not be assessed says so; it
        is never shown as zero. No ranking, conversion or sales claim is ever shown."""
        rules = {"PASS": "PASS", "FAIL": "FAIL", "NOT_ASSESSED": "NOT_ASSESSED"}
        names = {"keywordRelevance": "keywords", "factAccuracy": "confirmed facts", "readability": "readability", "buyerIntent": "buyer intent", "structure": "structure"}
        options = payload.get("options") or []
        items: list[str] = []
        compare: list[str] = []
        for o in options:
            sc = o.get("scores") or {}
            ov = sc.get("overall") or {}
            crit = sc.get("criteria") or {}
            comp = rules.get(str(((o.get("dimensions") or {}).get("marketplaceRules") or {}).get("status")), "NOT_ASSESSED")
            parts = []
            for k, label in names.items():
                c = crit.get(k) or {}
                parts.append(f"{label} {c['earned']}/{c['max']}" if c.get("status") == "ASSESSED" else f"{label} not assessed")
            if ov.get("status") == "ASSESSED":
                head = f"{ov['score']}/100 ({str(ov['band']).replace('_', ' ').lower()})"
                cover = f" [{ov['assessablePoints']} of 100 points assessable]"
            else:
                head, cover = "no overall score", f" [{ov.get('note', 'not enough evidence')}]"
            line = f"Option {o['rank']} ({o.get('strategy')}): {o['text']} | quality score {head}{cover} | " + ", ".join(parts) + f" | marketplace compliance (separate): {comp}"
            if o.get("hardFailures"):
                line = f"Option {o['rank']} ({o.get('strategy')}): {o['text']} | HARD FAIL, never recommended whatever its score: " + " ".join(o["hardFailures"]) + f" | score for reference {head}{cover}"
            lost = [f"{names[k]} -{d['points']} ({d['reason']})" for k, c in crit.items() for d in (c.get("deductions") or []) if d.get("points")]
            if lost and not o.get("hardFailures"):
                line += " | points lost: " + "; ".join(lost)
            if o.get("strengths") and not o.get("hardFailures"):
                line += " | good: " + "; ".join(o["strengths"])
            items.append(line)
            compare.append(f"Option {o['rank']}: " + (f"{head}, {ov['assessablePoints']} of 100 points assessable" if ov.get("status") == "ASSESSED" else f"no overall score ({ov.get('assessablePoints', 0)} of 100 points assessable)") + (" - HARD FAIL" if o.get("hardFailures") else ""))
        if items:
            self.artefacts.append(("Title quality scores", tuple(items), "Internal listing-quality assessment of wording and fit with your own confirmed facts. Not a marketplace ranking, search position, conversion or sales prediction."))
            self.artefacts.append(("Comparison of all options", tuple(compare), None))
        else:
            self.add_gap("There were no title options to compare.")
        rec = payload.get("recommendation") or {}
        if rec.get("text"):
            self.add_fact("Recommendation", str(rec["text"]), "SOURCE_DERIVED")
        scoring = payload.get("scoring") or {}
        if scoring.get("criteria"):
            self.add_fact("How the score works", "Out of 100: " + ", ".join(f"{names.get(k, k)} {v}" for k, v in scoring["criteria"].items()) + f". At least {scoring.get('minimumAssessedPoints')} points must be assessable for an overall score.", "SOURCE_DERIVED")
        for n in payload.get("notes") or []:
            self.add_fact("Not assessed", str(n), "SOURCE_DERIVED")
        for line in payload.get("limits") or []:
            self.add_fact("Limit", str(line), "SOURCE_DERIVED")

    def _keyword_intel(self, payload: Mapping[str, Any]) -> None:
        """Keyword candidates with their rule-based labels and evidence, quoted as saved. Volume, demand and rank are never shown as numbers: they are not assessed."""
        if payload.get("status") == "NO_FACTS":
            self.add_gap("There are no confirmed details for this product yet, so there is nothing to base keywords on. Tell me " + " and ".join(payload.get("needs") or ["the product details"]) + ".")
            return
        where = {"TITLE": "title", "BULLETS": "bullet points", "DESCRIPTION": "description", "BACKEND_TERMS": "backend search terms", "KEYWORDS": "keywords field"}
        items: list[str] = []
        for c in payload.get("candidates") or []:
            occ = c.get("competitorOccurrence") or {}
            seen = f"seen in {occ['listings']} of {occ['of']} tracked competitor listings" if occ.get("status") == "OBSERVED" else "competitor use: not assessed"
            evidence = ", ".join(sorted({str(e.get("detail")) for e in c.get("evidence") or []}))
            note = "" if c.get("recommended") else " (weak fit with your product: not recommended)"
            items.append(f"{c['keyword']}: {str(c['intent']).replace('_', ' ').lower()}; use in the {', '.join(where.get(p, str(p).lower()) for p in c['placement'])}; fit with your product {str(c['relevance']).lower()}; "
                         f"evidence strength {str(c['confidence']).replace('_', ' ').lower()} ({evidence}); {seen}; search volume and demand: not assessed{note}")
        if items:
            self.artefacts.append(("Keyword candidates", tuple(items), "Fit and evidence describe how well each keyword matches your own confirmed facts. They are not search counts, rankings or sales predictions."))
        else:
            self.add_gap("No keyword candidates could be built from the confirmed details.")
        for e in payload.get("excluded") or []:
            self.add_gap(f"Excluded: “{e['keyword']}”. {e['reason']}")
        for line in payload.get("limits") or []:
            self.add_fact("Limit", str(line), "SOURCE_DERIVED")

    def _title_choice(self, payload: Mapping[str, Any]) -> None:
        """The seller's own title choice, quoted as saved. It is a record of their choice in Metrion; it is not a publication and not a marketplace approval."""
        text = payload.get("approvedText")
        if not text:
            self.add_gap("Your title choice could not be saved.")
            return
        self.add_fact("The title you chose", f"“{text}”" + (" (worded by you)" if payload.get("editedBySeller") else ""), "SELLER_PROVIDED")
        self.add_fact("What this means", "It is saved in Metrion as your choice. Nothing was published to any marketplace, and copying it later only records that you did.", "SOURCE_DERIVED")
        for old in payload.get("listingsBuiltFromEarlierTitle") or []:  # N-15d: a saved complete listing written from a previous title is called out, never changed
            self.add_fact("Your saved listing", f"{old.get('explanation')} {old.get('nextStep')}", "SOURCE_DERIVED")
        self.add_fact("Next step", "Ask me to write the listing copy (description, bullet points and keywords) and I will base it on this title. That is a separate plan you approve.", "SOURCE_DERIVED")

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
                self.add_gap(_cmo_failure_text(kind, where, a.get("failure") or {}))
                continue
            items = _CMO_ITEMS.get(str(a.get("outputType")), lambda x: [])(a)
            if not items:
                self.add_gap(f"{kind}{where} came back empty.")
                continue
            self.artefacts.append((f"{kind}{where}", tuple(items), _cmo_rule_note(a)))

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
        kept_gaps, plain_gap = plain_reasons.summarise(self.gaps)  # the engine's coverage wording becomes ONE plain explanation, for the model-written answer and the template alike
        final_gaps = [*kept_gaps, *([plain_gap] if plain_gap else [])]
        return EvidenceTable(
            figures=figures_with_tokens(gated.kept),
            facts=tuple(self.facts),
            gaps=tuple((f"G{i}", m) for i, m in enumerate(final_gaps, start=1)),
            disclaimers=tuple((f"D{i}", k, t) for i, (k, t) in enumerate([*self.disclaimers, *disclaimers], start=1)),
            attach=tuple((f"A{i}", a) for i, a in enumerate([*self.attach, *attach], start=1)),
            offers=tuple((f"O{i}", k, lbl) for i, (k, lbl) in enumerate(self.offers, start=1)),
            untrusted=tuple((f"U{i}", s, t) for i, (s, t) in enumerate(untrusted, start=1)),
            conflicts=tuple((f"C{i}", c.what, conflict_rules.render(c)) for i, c in enumerate(verified, start=1)),
            artefacts=tuple(self.artefacts),
            ci_narration=self.ci_legs,
            finance_present=self.finance_legs,
        )
