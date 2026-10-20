"""The "no continuous-monitoring claim" rule, as code — competitor-intelligence-agent.md C40, AC47.

CI re-evaluates stored evidence; it does not watch competitors. Any text that describes the state of
a competitor (a monitoring report, a CEO composition about CI findings, an alert) must not claim
currency it does not have. This is the single list of phrases that make such a claim, and the check
that enforces it — used by the CEO's composition gate and by the eval suite, so the rule lives in a
test, not in a prompt.
"""

from __future__ import annotations

import re

_FORBIDDEN: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (name, re.compile(pattern, re.IGNORECASE))
    for name, pattern in (
        ("live", r"\blive\b(?!\s*(?:listing|link|url))"),
        ("real-time", r"\breal[- ]?time\b"),
        ("continuously", r"\bcontinuous(?:ly)?\b"),
        ("24/7", r"\b24\s*/\s*7\b"),
        ("always up to date", r"\balways (?:up[- ]to[- ]date|current)\b"),
        ("watching", r"\b(?:i am|i'm|we are|we're|am|are) (?:currently )?(?:watching|tracking|monitoring)\b"),
        ("monitoring them", r"\b(?:keep|keeping|kept) (?:an eye|watch|tabs)\b"),
        ("right now", r"\bright now\b"),
        ("currently priced", r"\bcurrently (?:priced|selling|charging|costs?)\b"),
    )
)


def currency_claims(text: str) -> list[str]:
    """Names of the forbidden claims found in `text` (empty means clean)."""
    return [name for name, pattern in _FORBIDDEN if pattern.search(text)]


def assert_no_currency_claim(text: str) -> None:
    found = currency_claims(text)
    if found:
        raise ValueError(f"text claims currency CI does not have: {', '.join(found)}")
