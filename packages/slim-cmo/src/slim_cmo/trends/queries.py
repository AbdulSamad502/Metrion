"""Fixed query templates, the outbound-query plan, the exact preview, and the egress guard (spec §6.8.3 rule 5, C15, AC30).

Pure: no network, no database, no clock. A provider request may carry ONLY:

* fixed template text (the literals in `TEMPLATES`, versioned by id),
* marketplace names (rendered from the `Marketplace` enum, never free text), and
* seller-CONFIRMED niche terms (re-screened here, in addition to when they were confirmed).

Nothing else can reach a provider: not a catalog title, not an unconfirmed / suggested / rejected term, not a seller
note, SKU, price or any report or customer datum. This is enforced structurally (a query is built only from a template
id + at most one confirmed term + enum marketplace names) and then independently re-checked by `validate_egress`,
which re-renders every query from its parts and requires an exact match, so a query altered after planning - or built by
hand - is refused. The retrieval service calls `validate_egress` immediately before ANY provider call.

Allocation of the budget to providers is a product decision (7e, 2026-10-04), fixed in `SECTION_SLOTS`:
niche = 1 Tavily news + 1 YouTube; marketplace news = 2 Tavily news; tactics = 2 Tavily news; new product buzz =
2 YouTube; adjacent = 2 Tavily news. Sections 1 (niche) and 5 (adjacent) need confirmed terms; 2-4 never use them.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any

from slim_cmo.config import TrendConfig
from slim_cmo.trends.budget import BudgetDenial, QueryBudget
from slim_cmo.trends.screening import normalise_term, screen_term
from slim_cmo.types import Marketplace, TrendSection

TEMPLATE_VERSION = "1"
NO_NICHE_REASON = "Confirm a niche to research your products."

# Region / country values sent to the providers for India-focused research (the probe of 2026-10-04 showed the Tavily
# `country` filter is accepted in news mode; relevance is partial, which the evidence section states).
TAVILY_COUNTRY = "india"
YOUTUBE_REGION = "IN"


class Provider(str, Enum):
    TAVILY = "TAVILY"
    YOUTUBE = "YOUTUBE"


MARKETPLACE_NAMES: Mapping[Marketplace, str] = {
    Marketplace.AMAZON: "Amazon India",
    Marketplace.FLIPKART: "Flipkart",
    Marketplace.MEESHO: "Meesho",
}


@dataclass(frozen=True, slots=True)
class Template:
    id: str
    provider: Provider
    text: str  # literal with {term} and/or {marketplaces} placeholders only
    needs_term: bool
    needs_marketplaces: bool


def _t(id_: str, provider: Provider, text: str) -> Template:
    return Template(id_, provider, text, "{term}" in text, "{marketplaces}" in text)


TEMPLATES: Mapping[str, Template] = {
    t.id: t
    for t in (
        _t("NICHE_NEWS_V1", Provider.TAVILY, "{term} India e-commerce news"),
        _t("NICHE_VIDEO_V1", Provider.YOUTUBE, "{term} India"),
        _t("MARKET_NEWS_POLICY_V1", Provider.TAVILY, "{marketplaces} seller policy and fee changes"),
        _t("MARKET_NEWS_PROGRAM_V1", Provider.TAVILY, "{marketplaces} seller programs and seasonal sales"),
        _t("TACTICS_SALES_V1", Provider.TAVILY, "{marketplaces} sellers tips to increase sales"),
        _t("TACTICS_RANKING_V1", Provider.TAVILY, "{marketplaces} listing ranking tactics for sellers"),
        _t("BUZZ_VIRAL_V1", Provider.YOUTUBE, "viral products India online sellers"),
        _t("BUZZ_LAUNCH_V1", Provider.YOUTUBE, "new product launches India online shopping"),
        _t("ADJACENT_CATEGORIES_V1", Provider.TAVILY, "{term} related product categories India"),
        _t("ADJACENT_IDEAS_V1", Provider.TAVILY, "{term} new product ideas India"),
    )
}

# Per section, the ordered provider slots. A section's configured budget truncates this list (never extends it).
SECTION_SLOTS: Mapping[TrendSection, tuple[str, ...]] = {
    TrendSection.NICHE: ("NICHE_NEWS_V1", "NICHE_VIDEO_V1"),
    TrendSection.MARKET_NEWS: ("MARKET_NEWS_POLICY_V1", "MARKET_NEWS_PROGRAM_V1"),
    TrendSection.REPORTED_TACTICS: ("TACTICS_SALES_V1", "TACTICS_RANKING_V1"),
    TrendSection.NEW_PRODUCTS_BUZZ: ("BUZZ_VIRAL_V1", "BUZZ_LAUNCH_V1"),
    TrendSection.ADJACENT: ("ADJACENT_CATEGORIES_V1", "ADJACENT_IDEAS_V1"),
}


@dataclass(frozen=True, slots=True)
class OutboundQuery:
    query_id: str  # "<SECTION>:<n>" - stable within a plan
    section: TrendSection
    provider: Provider
    template_id: str
    text: str  # EXACTLY what is sent to the provider
    term: str | None  # the one confirmed niche term, or None
    marketplaces: tuple[Marketplace, ...]  # the marketplace names used, or ()
    params: Mapping[str, str | int]  # EXACTLY the provider options sent (besides the query text)

    def preview(self) -> dict[str, Any]:
        """The exact outbound request, as shown to the seller before the first send and persisted in
        `cmo_trend_report.outbound_queries`."""
        return {
            "queryId": self.query_id, "section": self.section.value, "provider": self.provider.value,
            "templateId": self.template_id, "query": self.text, "params": dict(self.params),
        }


@dataclass(frozen=True, slots=True)
class SkippedQuery:
    section: TrendSection
    template_id: str
    reason: str  # a BudgetDenial value


@dataclass(frozen=True, slots=True)
class QueryPlan:
    queries: tuple[OutboundQuery, ...]  # in execution order (section priority, then slot order)
    unavailable: Mapping[TrendSection, str]  # section -> reason (no query is planned for it)
    skipped: tuple[SkippedQuery, ...]  # slots dropped by the budget
    unresearched_terms: tuple[str, ...]  # confirmed terms no query used - disclosed to the seller
    budget_usage: Mapping[str, object]

    def preview(self) -> list[dict[str, Any]]:
        return [q.preview() for q in self.queries]

    def by_provider(self) -> dict[str, int]:
        out = {p.value: 0 for p in Provider}
        for q in self.queries:
            out[q.provider.value] += 1
        return out


class EgressViolation(ValueError):
    def __init__(self, reasons: Sequence[str]) -> None:
        super().__init__("; ".join(reasons))
        self.reasons = tuple(reasons)


# ---------------------------------------------------------------------------------------- building
def _canonical_marketplaces(marketplaces: Iterable[Marketplace]) -> tuple[Marketplace, ...]:
    wanted = set(marketplaces)
    return tuple(m for m in Marketplace if m in wanted)  # enum order: deterministic, enum members only


def render(template: Template, term: str | None, marketplaces: Sequence[Marketplace]) -> str:
    names = " ".join(MARKETPLACE_NAMES[m] for m in marketplaces)
    return template.text.format(term=term or "", marketplaces=names)


def params_for(provider: Provider, config: TrendConfig) -> dict[str, str | int]:
    """The ONLY provider options CMO ever sends. Every value comes from configuration or a fixed constant."""
    if provider is Provider.TAVILY:
        return {"topic": "news", "days": config.news_window_days, "country": TAVILY_COUNTRY, "max_results": config.max_results_per_query}
    return {"region_code": YOUTUBE_REGION, "published_within_days": config.news_window_days, "max_results": config.max_results_per_query}


def build_plan(
    *,
    config: TrendConfig,
    sections: Iterable[TrendSection],
    confirmed_terms: Sequence[str],
    marketplaces: Sequence[Marketplace],
) -> QueryPlan:
    """Plan the report's provider queries. `confirmed_terms` must come from `NicheService.confirmed_terms` (CONFIRMED rows
    only); every term is re-screened here and an unsafe one is dropped, never sent. Terms are used one per query in
    sorted order across the term-needing sections in priority order; unused terms are disclosed."""
    mps = _canonical_marketplaces(marketplaces) or tuple(Marketplace)  # no selection = all three marketplaces
    terms = tuple(dict.fromkeys(t for t in sorted(normalise_term(x) for x in confirmed_terms) if t and screen_term(t, max_chars=config.max_term_chars).ok))
    requested = tuple(sections)
    budget = QueryBudget(config, requested)

    queries: list[OutboundQuery] = []
    unavailable: dict[TrendSection, str] = {}
    skipped: list[SkippedQuery] = []
    used_terms: set[str] = set()
    cursor = 0

    for section in budget.ordered_sections():
        template_ids = SECTION_SLOTS[section]
        needs_term = any(TEMPLATES[t].needs_term for t in template_ids)
        if needs_term and not terms:
            unavailable[section] = NO_NICHE_REASON
            continue
        for n, template_id in enumerate(template_ids):
            decision = budget.try_spend(section)
            if not decision.allowed:
                assert decision.denial is not None
                skipped.append(SkippedQuery(section, template_id, decision.denial.value))
                continue
            template = TEMPLATES[template_id]
            term: str | None = None
            if template.needs_term:
                term = terms[cursor % len(terms)]
                cursor += 1
                used_terms.add(term)
            used_marketplaces = mps if template.needs_marketplaces else ()
            queries.append(
                OutboundQuery(
                    query_id=f"{section.value}:{n}", section=section, provider=template.provider, template_id=template_id,
                    text=render(template, term, used_marketplaces), term=term, marketplaces=used_marketplaces,
                    params=params_for(template.provider, config),
                )
            )
    return QueryPlan(tuple(queries), unavailable, tuple(skipped), tuple(t for t in terms if t not in used_terms), budget.usage())


# ---------------------------------------------------------------------------------------- the egress guard
def validate_egress(
    queries: Iterable[OutboundQuery],
    *,
    confirmed_terms: Collection[str],
    config: TrendConfig,
) -> None:
    """Raise `EgressViolation` unless EVERY query is exactly what its template, at most one CONFIRMED term and enum
    marketplace names would produce, with exactly the permitted provider options, within the configured budgets."""
    confirmed = {normalise_term(t) for t in confirmed_terms}
    problems: list[str] = []
    per_section: dict[str, int] = {}
    seen: set[tuple[str, str]] = set()
    total = 0
    for q in queries:
        total += 1
        label = q.query_id
        template = TEMPLATES.get(q.template_id) if isinstance(q.template_id, str) else None
        if template is None:
            problems.append(f"{label}: unknown template")
            continue
        if q.template_id not in SECTION_SLOTS.get(q.section, ()):
            problems.append(f"{label}: template {q.template_id} is not allowed for section {q.section.value}")
        if q.provider is not template.provider:
            problems.append(f"{label}: provider does not match the template")
        if template.needs_term:
            if q.term is None or normalise_term(q.term) not in confirmed:
                problems.append(f"{label}: the term is not a confirmed niche term")
            elif not screen_term(q.term, max_chars=config.max_term_chars).ok:
                problems.append(f"{label}: the term fails the outbound screen")
        elif q.term is not None:
            problems.append(f"{label}: this template takes no term")
        if template.needs_marketplaces:
            if not q.marketplaces or any(not isinstance(m, Marketplace) for m in q.marketplaces) or q.marketplaces != _canonical_marketplaces(q.marketplaces):
                problems.append(f"{label}: marketplaces must be a non-empty, canonical set of known marketplaces")
        elif q.marketplaces:
            problems.append(f"{label}: this template takes no marketplace names")
        try:
            rendered: str | None = render(template, q.term, q.marketplaces)
        except Exception:  # noqa: BLE001 - a malformed query (e.g. a non-enum marketplace) is a violation, not a crash
            rendered = None
        if rendered != q.text:
            problems.append(f"{label}: the query text is not exactly the rendered template")
        if dict(q.params) != params_for(template.provider, config):
            problems.append(f"{label}: provider options differ from the permitted set")
        key = (q.provider.value, q.text)
        if key in seen:
            problems.append(f"{label}: duplicate query")
        seen.add(key)
        per_section[q.section.value] = per_section.get(q.section.value, 0) + 1
    for section, count in per_section.items():
        if count > config.section_query_budgets.get(section, 0):
            problems.append(f"section {section}: {count} queries exceed its budget")
    if total > config.max_queries_per_report:
        problems.append(f"{total} queries exceed the report budget")
    if problems:
        raise EgressViolation(problems)


__all__ = [
    "BudgetDenial", "EgressViolation", "NO_NICHE_REASON", "OutboundQuery", "Provider", "QueryPlan", "SECTION_SLOTS",
    "SkippedQuery", "TEMPLATES", "TEMPLATE_VERSION", "Template", "build_plan", "params_for", "render", "validate_egress",
]
