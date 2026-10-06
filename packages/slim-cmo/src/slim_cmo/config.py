"""Typed, fail-closed configuration (spec C16, §6.3, §6.8.5, §8.3).

Every tunable lives in `cmo_platform_config` as data. **No value here has a code default.**
`load_*` takes the raw key->value mapping (read from that table in a later phase) and returns
either a fully-validated config object or `ConfigMissing` naming EVERY problem at once - the
operator fixes them in one pass instead of discovering them one failed request at a time.

Missing, `None`, wrongly typed (including bools and floats where an int is required - the
project has no floats in any calculation path), non-positive where positivity is required, and
internally inconsistent values (e.g. `fresh_window_days > recent_window_days`) are all
rejected. A `ConfigMissing` result means: the affected action must not run, must not call a
provider, and must not consume a unit (AC31).

Two keys are deliberately OPTIONAL, each with an explicit, safe, documented absence behaviour
rather than a default value (spec deviation recorded in the P2 report):

* `tactic_risk_pattern_set_ref` - absent => no pattern set => every tactic is `UNASSESSED`
  and receives no suggested action (spec §6.8.7 rule 3c: the stated fail-safe).
* `official_marketplace_domains` - absent => nothing is ever labelled `OFFICIAL_MARKETPLACE`
  (a third-party page can never be mislabelled official by omission).

Two more are optional because they adjust built-in linguistic data rather than supply a policy
value: `niche_stopwords_extra` / `niche_stopwords_exclude` (absent => the documented built-in
English/Hindi/Hinglish stop-word sets apply unchanged).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from slim_cmo.stopwords import build_stopwords, normalise_stopword
from slim_cmo.types import TrendSection

# --- key names (the contract with cmo_platform_config.key) ---------------------------------

FORMAT_CONSTRAINT_MAX_AGE_DAYS = "format_constraint_max_age_days"
INTERNAL_RETRY_BOUND = "internal_retry_bound"

MAX_QUERIES_PER_REPORT = "max_queries_per_report"
SECTION_QUERY_BUDGETS = "section_query_budgets"
SECTION_PRIORITY = "section_priority"
MAX_RESULTS_PER_QUERY = "max_results_per_query"
MAX_SOURCES_PER_REPORT = "max_sources_per_report"
MAX_FINDINGS_PER_SECTION = "max_findings_per_section"
FRESH_WINDOW_DAYS = "fresh_window_days"
RECENT_WINDOW_DAYS = "recent_window_days"
NEWS_WINDOW_DAYS = "news_window_days"
MODERATE_MIN_INDEPENDENT_SOURCES = "moderate_min_independent_sources"
STRONG_MIN_INDEPENDENT_SOURCES = "strong_min_independent_sources"
MAX_CONFIRMED_NICHE_TERMS = "max_confirmed_niche_terms"
MAX_TERM_CHARS = "max_term_chars"
CATALOG_TITLES_READ_CAP = "catalog_titles_read_cap"
PROVIDER_CALL_TIMEOUT_SECONDS = "provider_call_timeout_seconds"
PROVIDER_CACHE_TTL_HOURS = "provider_cache_ttl_hours"
PROVIDER_DAILY_SEARCH_CEILING = "provider_daily_search_ceiling"
TACTIC_RISK_PATTERN_SET_REF = "tactic_risk_pattern_set_ref"
OFFICIAL_MARKETPLACE_DOMAINS = "official_marketplace_domains"
NICHE_STOPWORDS_EXTRA = "niche_stopwords_extra"
NICHE_STOPWORDS_EXCLUDE = "niche_stopwords_exclude"

HASHTAG_SET_SIZE = "hashtag_set_size"

# Required ONLY for the niche flow (`cmo.suggest_niche_terms` / `cmo.confirm_niche_terms`, P7d): the three
# niche keys of the trend set. A missing value blocks the niche actions and never blocks anything else.
NICHE_REQUIRED_KEYS: tuple[str, ...] = ("max_confirmed_niche_terms", "max_term_chars", "catalog_titles_read_cap")

GENERATION_REQUIRED_KEYS: tuple[str, ...] = (FORMAT_CONSTRAINT_MAX_AGE_DAYS, INTERNAL_RETRY_BOUND)
# Required ONLY for `cmo.generate_hashtags` (P3 decision 8): a missing value blocks hashtags with
# CONFIG_MISSING and never blocks titles or listing copy.
HASHTAG_REQUIRED_KEYS: tuple[str, ...] = (HASHTAG_SET_SIZE,)

TREND_REQUIRED_KEYS: tuple[str, ...] = (
    MAX_QUERIES_PER_REPORT, SECTION_QUERY_BUDGETS, SECTION_PRIORITY, MAX_RESULTS_PER_QUERY,
    MAX_SOURCES_PER_REPORT, MAX_FINDINGS_PER_SECTION, FRESH_WINDOW_DAYS, RECENT_WINDOW_DAYS,
    NEWS_WINDOW_DAYS, MODERATE_MIN_INDEPENDENT_SOURCES, STRONG_MIN_INDEPENDENT_SOURCES,
    MAX_CONFIRMED_NICHE_TERMS, MAX_TERM_CHARS, CATALOG_TITLES_READ_CAP, PROVIDER_CALL_TIMEOUT_SECONDS,
    PROVIDER_CACHE_TTL_HOURS, PROVIDER_DAILY_SEARCH_CEILING,
)
TREND_OPTIONAL_KEYS: tuple[str, ...] = (
    TACTIC_RISK_PATTERN_SET_REF, OFFICIAL_MARKETPLACE_DOMAINS, NICHE_STOPWORDS_EXTRA, NICHE_STOPWORDS_EXCLUDE,
)

_ALL_SECTIONS: tuple[str, ...] = tuple(s.value for s in TrendSection)


@dataclass(frozen=True, slots=True)
class ConfigMissing:
    """A required configuration problem. `code` is the stable machine-readable string callers
    surface to the operator (spec AC31). Nothing downstream may proceed on this result."""

    missing: tuple[str, ...]
    invalid: tuple[tuple[str, str], ...]  # (key, human-readable reason)
    code: str = "CONFIG_MISSING"

    def describe(self) -> str:
        parts = [f"missing: {', '.join(self.missing)}"] if self.missing else []
        parts += [f"invalid {k}: {why}" for k, why in self.invalid]
        return "; ".join(parts)


@dataclass(frozen=True, slots=True)
class GenerationConfig:
    format_constraint_max_age_days: int
    internal_retry_bound: int  # 0 is a legitimate, explicit choice: no internal retries


@dataclass(frozen=True, slots=True)
class HashtagConfig:
    hashtag_set_size: int  # the MAXIMUM number of hashtags in one suggestion set


@dataclass(frozen=True, slots=True)
class TrendConfig:
    max_queries_per_report: int
    section_query_budgets: Mapping[str, int]
    section_priority: tuple[str, ...]
    max_results_per_query: int
    max_sources_per_report: int
    max_findings_per_section: int
    fresh_window_days: int
    recent_window_days: int
    news_window_days: int
    moderate_min_independent_sources: int
    strong_min_independent_sources: int
    max_confirmed_niche_terms: int
    max_term_chars: int
    catalog_titles_read_cap: int
    provider_call_timeout_seconds: int
    provider_cache_ttl_hours: int
    provider_daily_search_ceiling: int  # COMBINED CMO provider searches per Asia/Kolkata day, all tenants (does not see PI's use of the shared keys)
    tactic_risk_pattern_set_ref: str | None
    official_marketplace_domains: frozenset[str]
    niche_stopwords_extra: tuple[str, ...]
    niche_stopwords_exclude: tuple[str, ...]
    niche_stopwords: frozenset[str]  # (built-in defaults - exclude) | extra: what suggest_terms actually uses

    def snapshot(self) -> dict[str, Any]:
        """JSON-able copy for `cmo_trend_report.config_snapshot` (reproducibility, spec §5)."""
        return {
            MAX_QUERIES_PER_REPORT: self.max_queries_per_report,
            SECTION_QUERY_BUDGETS: dict(self.section_query_budgets),
            SECTION_PRIORITY: list(self.section_priority),
            MAX_RESULTS_PER_QUERY: self.max_results_per_query,
            MAX_SOURCES_PER_REPORT: self.max_sources_per_report,
            MAX_FINDINGS_PER_SECTION: self.max_findings_per_section,
            FRESH_WINDOW_DAYS: self.fresh_window_days,
            RECENT_WINDOW_DAYS: self.recent_window_days,
            NEWS_WINDOW_DAYS: self.news_window_days,
            MODERATE_MIN_INDEPENDENT_SOURCES: self.moderate_min_independent_sources,
            STRONG_MIN_INDEPENDENT_SOURCES: self.strong_min_independent_sources,
            MAX_CONFIRMED_NICHE_TERMS: self.max_confirmed_niche_terms,
            MAX_TERM_CHARS: self.max_term_chars,
            CATALOG_TITLES_READ_CAP: self.catalog_titles_read_cap,
            PROVIDER_CALL_TIMEOUT_SECONDS: self.provider_call_timeout_seconds,
            PROVIDER_CACHE_TTL_HOURS: self.provider_cache_ttl_hours,
            PROVIDER_DAILY_SEARCH_CEILING: self.provider_daily_search_ceiling,
            TACTIC_RISK_PATTERN_SET_REF: self.tactic_risk_pattern_set_ref,
            OFFICIAL_MARKETPLACE_DOMAINS: sorted(self.official_marketplace_domains),
            NICHE_STOPWORDS_EXTRA: list(self.niche_stopwords_extra),
            NICHE_STOPWORDS_EXCLUDE: list(self.niche_stopwords_exclude),
        }


# --- validation helpers ---------------------------------------------------------------------


class _Problems:
    def __init__(self) -> None:
        self.missing: list[str] = []
        self.invalid: list[tuple[str, str]] = []

    def missing_key(self, key: str) -> None:
        self.missing.append(key)

    def bad(self, key: str, why: str) -> None:
        self.invalid.append((key, why))

    def result(self) -> ConfigMissing | None:
        if not self.missing and not self.invalid:
            return None
        return ConfigMissing(missing=tuple(self.missing), invalid=tuple(self.invalid))


def _present(values: Mapping[str, object], key: str, problems: _Problems) -> object | None:
    value = values.get(key)
    if value is None:
        problems.missing_key(key)
        return None
    return value


def _int(values: Mapping[str, object], key: str, problems: _Problems, *, minimum: int) -> int | None:
    raw = _present(values, key, problems)
    if raw is None:
        return None
    if type(raw) is not int:  # bool is an int subclass; floats are never accepted (no floats anywhere)
        problems.bad(key, f"must be an integer, got {type(raw).__name__}")
        return None
    if raw < minimum:
        problems.bad(key, f"must be >= {minimum}, got {raw}")
        return None
    return raw


def _budgets(values: Mapping[str, object], problems: _Problems) -> dict[str, int] | None:
    raw = _present(values, SECTION_QUERY_BUDGETS, problems)
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        problems.bad(SECTION_QUERY_BUDGETS, "must be an object mapping each section to an integer")
        return None
    unknown = sorted(str(k) for k in raw if k not in _ALL_SECTIONS)
    absent = [s for s in _ALL_SECTIONS if s not in raw]
    if unknown:
        problems.bad(SECTION_QUERY_BUDGETS, f"unknown section(s): {', '.join(unknown)}")
        return None
    if absent:
        problems.bad(SECTION_QUERY_BUDGETS, f"every section needs an explicit budget; missing: {', '.join(absent)}")
        return None
    out: dict[str, int] = {}
    for section in _ALL_SECTIONS:
        v = raw[section]
        if type(v) is not int or v < 0:
            problems.bad(SECTION_QUERY_BUDGETS, f"{section} must be an integer >= 0, got {v!r}")
            return None
        out[section] = v
    return out


def _priority(values: Mapping[str, object], problems: _Problems) -> tuple[str, ...] | None:
    raw = _present(values, SECTION_PRIORITY, problems)
    if raw is None:
        return None
    if not isinstance(raw, (list, tuple)) or not all(isinstance(x, str) for x in raw):
        problems.bad(SECTION_PRIORITY, "must be an ordered list of section names")
        return None
    if sorted(raw) != sorted(_ALL_SECTIONS):
        problems.bad(SECTION_PRIORITY, f"must list each of {', '.join(_ALL_SECTIONS)} exactly once")
        return None
    return tuple(raw)


def _domains(values: Mapping[str, object], problems: _Problems) -> frozenset[str]:
    raw = values.get(OFFICIAL_MARKETPLACE_DOMAINS)
    if raw is None:
        return frozenset()  # explicit fail-safe: nothing is ever labelled OFFICIAL_MARKETPLACE
    if not isinstance(raw, (list, tuple)) or not all(isinstance(x, str) and x.strip() for x in raw):
        problems.bad(OFFICIAL_MARKETPLACE_DOMAINS, "must be a list of domain names")
        return frozenset()
    cleaned = {x.strip().lower().rstrip(".") for x in raw}
    for d in cleaned:
        if "/" in d or " " in d or ":" in d or "." not in d:
            problems.bad(OFFICIAL_MARKETPLACE_DOMAINS, f"{d!r} is not a bare registrable domain (e.g. 'example.in')")
    return frozenset(cleaned)


def _stopword_list(values: Mapping[str, object], key: str, problems: _Problems) -> tuple[str, ...]:
    raw = values.get(key)
    if raw is None:
        return ()  # optional: the built-in defaults apply (linguistic data, not a policy value)
    if not isinstance(raw, (list, tuple)):
        problems.bad(key, "must be a list of single words")
        return ()
    cleaned: list[str] = []
    for word in raw:
        try:
            cleaned.append(normalise_stopword(word))
        except ValueError as exc:
            problems.bad(key, str(exc))
            return ()
    return tuple(dict.fromkeys(cleaned))


# --- public loaders -------------------------------------------------------------------------


def load_generation_config(values: Mapping[str, object]) -> GenerationConfig | ConfigMissing:
    problems = _Problems()
    max_age = _int(values, FORMAT_CONSTRAINT_MAX_AGE_DAYS, problems, minimum=1)
    retries = _int(values, INTERNAL_RETRY_BOUND, problems, minimum=0)
    failed = problems.result()
    if failed is not None:
        return failed
    assert max_age is not None and retries is not None
    return GenerationConfig(format_constraint_max_age_days=max_age, internal_retry_bound=retries)


def load_retry_bound(values: Mapping[str, object]) -> int | ConfigMissing:
    """`internal_retry_bound` alone: the trend pipeline's model calls need only this one generation key (0 = no retries)."""
    problems = _Problems()
    retries = _int(values, INTERNAL_RETRY_BOUND, problems, minimum=0)
    failed = problems.result()
    if failed is not None:
        return failed
    assert retries is not None
    return retries


def load_hashtag_config(values: Mapping[str, object]) -> HashtagConfig | ConfigMissing:
    problems = _Problems()
    size = _int(values, HASHTAG_SET_SIZE, problems, minimum=1)
    failed = problems.result()
    if failed is not None:
        return failed
    assert size is not None
    return HashtagConfig(hashtag_set_size=size)


@dataclass(frozen=True, slots=True)
class NicheConfig:
    max_confirmed_niche_terms: int
    max_term_chars: int
    catalog_titles_read_cap: int
    niche_stopwords: frozenset[str]


def load_niche_config(values: Mapping[str, object]) -> NicheConfig | ConfigMissing:
    problems = _Problems()
    max_terms = _int(values, MAX_CONFIRMED_NICHE_TERMS, problems, minimum=1)
    max_chars = _int(values, MAX_TERM_CHARS, problems, minimum=1)
    cap = _int(values, CATALOG_TITLES_READ_CAP, problems, minimum=1)
    extra = _stopword_list(values, NICHE_STOPWORDS_EXTRA, problems)
    exclude = _stopword_list(values, NICHE_STOPWORDS_EXCLUDE, problems)
    failed = problems.result()
    if failed is not None:
        return failed
    assert max_terms is not None and max_chars is not None and cap is not None
    return NicheConfig(
        max_confirmed_niche_terms=max_terms, max_term_chars=max_chars, catalog_titles_read_cap=cap,
        niche_stopwords=build_stopwords(extra, exclude),
    )


def load_trend_config(values: Mapping[str, object]) -> TrendConfig | ConfigMissing:
    problems = _Problems()

    max_queries = _int(values, MAX_QUERIES_PER_REPORT, problems, minimum=1)
    budgets = _budgets(values, problems)
    priority = _priority(values, problems)
    max_results = _int(values, MAX_RESULTS_PER_QUERY, problems, minimum=1)
    max_sources = _int(values, MAX_SOURCES_PER_REPORT, problems, minimum=1)
    max_findings = _int(values, MAX_FINDINGS_PER_SECTION, problems, minimum=1)
    fresh = _int(values, FRESH_WINDOW_DAYS, problems, minimum=1)
    recent = _int(values, RECENT_WINDOW_DAYS, problems, minimum=1)
    news = _int(values, NEWS_WINDOW_DAYS, problems, minimum=1)
    # n == 1 is SINGLE_SOURCE by definition, so the moderate threshold must start at 2.
    moderate = _int(values, MODERATE_MIN_INDEPENDENT_SOURCES, problems, minimum=2)
    strong = _int(values, STRONG_MIN_INDEPENDENT_SOURCES, problems, minimum=3)
    max_terms = _int(values, MAX_CONFIRMED_NICHE_TERMS, problems, minimum=1)
    max_term_chars = _int(values, MAX_TERM_CHARS, problems, minimum=1)
    titles_cap = _int(values, CATALOG_TITLES_READ_CAP, problems, minimum=1)
    timeout = _int(values, PROVIDER_CALL_TIMEOUT_SECONDS, problems, minimum=1)
    cache_ttl = _int(values, PROVIDER_CACHE_TTL_HOURS, problems, minimum=1)
    daily_ceiling = _int(values, PROVIDER_DAILY_SEARCH_CEILING, problems, minimum=1)

    domains = _domains(values, problems)
    ref_raw = values.get(TACTIC_RISK_PATTERN_SET_REF)
    ref: str | None = None
    if ref_raw is not None:
        if isinstance(ref_raw, str) and ref_raw.strip():
            ref = ref_raw.strip()
        else:
            problems.bad(TACTIC_RISK_PATTERN_SET_REF, "must be a non-empty string when provided")

    stop_extra = _stopword_list(values, NICHE_STOPWORDS_EXTRA, problems)
    stop_exclude = _stopword_list(values, NICHE_STOPWORDS_EXCLUDE, problems)

    # cross-field consistency (only meaningful when the individual fields were valid)
    if fresh is not None and recent is not None and fresh > recent:
        problems.bad(FRESH_WINDOW_DAYS, f"must be <= {RECENT_WINDOW_DAYS} ({fresh} > {recent})")
    if moderate is not None and strong is not None and strong <= moderate:
        problems.bad(STRONG_MIN_INDEPENDENT_SOURCES, f"must exceed {MODERATE_MIN_INDEPENDENT_SOURCES} ({strong} <= {moderate})")
    if budgets is not None and max_queries is not None and sum(budgets.values()) > max_queries:
        problems.bad(SECTION_QUERY_BUDGETS, f"section budgets sum to {sum(budgets.values())} > {MAX_QUERIES_PER_REPORT} ({max_queries})")

    failed = problems.result()
    if failed is not None:
        return failed
    assert None not in (max_queries, budgets, priority, max_results, max_sources, max_findings, fresh, recent,
                        news, moderate, strong, max_terms, max_term_chars, titles_cap, timeout, cache_ttl, daily_ceiling)
    return TrendConfig(
        max_queries_per_report=max_queries,  # type: ignore[arg-type]
        section_query_budgets=budgets,  # type: ignore[arg-type]
        section_priority=priority,  # type: ignore[arg-type]
        max_results_per_query=max_results,  # type: ignore[arg-type]
        max_sources_per_report=max_sources,  # type: ignore[arg-type]
        max_findings_per_section=max_findings,  # type: ignore[arg-type]
        fresh_window_days=fresh,  # type: ignore[arg-type]
        recent_window_days=recent,  # type: ignore[arg-type]
        news_window_days=news,  # type: ignore[arg-type]
        moderate_min_independent_sources=moderate,  # type: ignore[arg-type]
        strong_min_independent_sources=strong,  # type: ignore[arg-type]
        max_confirmed_niche_terms=max_terms,  # type: ignore[arg-type]
        max_term_chars=max_term_chars,  # type: ignore[arg-type]
        catalog_titles_read_cap=titles_cap,  # type: ignore[arg-type]
        provider_call_timeout_seconds=timeout,  # type: ignore[arg-type]
        provider_cache_ttl_hours=cache_ttl,  # type: ignore[arg-type]
        provider_daily_search_ceiling=daily_ceiling,  # type: ignore[arg-type]
        tactic_risk_pattern_set_ref=ref,
        official_marketplace_domains=domains,
        niche_stopwords_extra=stop_extra,
        niche_stopwords_exclude=stop_exclude,
        niche_stopwords=build_stopwords(stop_extra, stop_exclude),
    )
