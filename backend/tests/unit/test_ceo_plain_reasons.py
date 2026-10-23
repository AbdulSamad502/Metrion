"""Seller-facing wording for figures that cannot be calculated yet: one explanation, what is needed, no engine log lines, nothing invented."""

from __future__ import annotations

from backend.ceo import periods, plain_reasons
from backend.ceo.composer import EvidenceTable, render_template
from datetime import date

TECH = [
    "sales_lines, cogs_per_unit, cancellation_state, return_status, rto_status: input 'sales_lines' is available for 0/1 of lines, below the required 19/20 (0.0% against 95.0%) (blocks CONTRIBUTION_PROFIT)",
    "sales_lines, cancellation_state, return_status, rto_status: input 'sales_lines' is available for 0/1 of lines, below the required 19/20 (0.0% against 95.0%) (blocks NET_REALIZED_REVENUE)",
    "expense_entries: no expense entries are recorded for this period (blocks EXPENSE_BY_CATEGORY)",
    "reconciliation_exceptions: input 'reconciliation_exceptions' coverage was not measured (blocks LEAK_AGGREGATE)",
]


def test_the_engines_coverage_wording_becomes_one_plain_explanation_with_what_is_needed():
    keep, plain = plain_reasons.summarise(["Health bands are unavailable.", *TECH])
    assert keep == ["Health bands are unavailable."]  # a message that is not in the engine's coverage vocabulary is left alone
    assert plain is not None and "0/1" not in plain and "19/20" not in plain and "input '" not in plain
    for word in ("contribution profit", "net realized revenue", "what each product costs you", "which orders were returned", "your business expenses", "a settlement check"):
        assert word in plain
    assert "does not add it" in plain  # reading a file in chat is not importing it, and the seller is told so
    assert "Why this figure?" in plain


def test_nothing_technical_means_nothing_is_changed():
    keep, plain = plain_reasons.summarise(["Not stored yet."])
    assert keep == ["Not stored yet."] and plain is None


def test_the_template_shows_one_plain_line_instead_of_a_log_dump():
    table = EvidenceTable(figures=(), facts=(), gaps=tuple((f"g{i}", m) for i, m in enumerate(TECH)), conflicts=(), disclaimers=(), attach=(), offers=(), artefacts=())
    text = render_template(table)
    assert text.count("Not available yet:") == 1 and "19/20" not in text and "I cannot calculate" in text


def test_a_range_written_with_the_year_once_and_month_spans_are_read_exactly():
    t = date(2026, 10, 23)
    got = lambda s: (lambda r: (r.start.isoformat(), r.end.isoformat()))(periods.resolve_period(s, today=t))
    assert got("1 September to 31 October 2025") == ("2025-09-01", "2025-10-31")
    assert got("August and September 2025") == ("2025-08-01", "2025-09-30")
    assert got("September to October 2025") == ("2025-09-01", "2025-10-31")
    assert got("2025") == ("2025-01-01", "2025-12-31") and got("last year") == ("2025-01-01", "2025-12-31")
