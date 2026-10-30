"""Seller-facing wording for "this figure cannot be calculated yet" (docs/specs/ceo-expense-tracker-chat.md is not the home of this; the rule is CLAUDE.md "missing input shows as unavailable
or not yet calculable, never as zero").

The engine's own reasons are exact and stay available for diagnostics ("Why this figure?" on the CFO page, the stored result). In the chat they read like a log line ("input 'sales_lines'
is available for 0/1 of lines, below the required 19/20"), which tells a seller nothing about what to do. This module turns a set of such reasons into ONE short explanation that names
what is not calculable and what the seller can do about it. Pure text, no digits written here, no figure created, nothing guessed: it only re-words the missing inputs the engine already named.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

_NEEDS: dict[str, str] = {
    "sales_lines": "your marketplace sales reports added to your financial records (reading a file in chat does not add it)",
    "cogs_per_unit": "what each product costs you per unit",
    "cancellation_state": "which orders were cancelled",
    "return_status": "which orders were returned, with the refund amounts",
    "rto_status": "which orders came back undelivered (RTO)",
    "refunded_amount": "the refund amounts on returned orders",
    "fee_components": "the marketplace fees on your orders",
    "expense_entries": "your business expenses (rent, salaries, software and so on)",
    "reconciliation_exceptions": "a settlement check (Leak Shield) run on your reports",
    "settlement_lines": "your marketplace settlement reports",
    "ad_source": "your advertising spend",
    "rto_outcome": "what happened to undelivered orders",
}
_NAMES: dict[str, str] = {
    "NET_REALIZED_REVENUE": "net realized revenue", "CONTRIBUTION_PROFIT": "contribution profit", "CONTRIBUTION_MARGIN_PCT": "contribution margin",
    "OPERATING_PROFIT": "operating profit", "RETURN_RATE_PCT": "return rate", "FEE_RATIO_PCT": "marketplace fee share", "EXPENSE_BY_CATEGORY": "expenses by category",
    "LEAK_AGGREGATE": "the leak check", "SETTLEMENT_RECEIPTS": "settlement receipts", "AD_SPEND": "advertising spend", "ROAS": "return on ad spend",
}
_ORDER = tuple(_NEEDS)
_FIELD_HEAD = re.compile(r"^(?P<fields>[a-z_]+(?:\s*,\s*[a-z_]+)*)\s*:\s*(?P<rest>.*)$", re.DOTALL)
_BLOCKS = re.compile(r"\(blocks ([A-Z_]+)\)")


def is_technical(message: str) -> bool:
    """A reason in the engine's coverage vocabulary ("input 'x' is available for a/b lines ...", "coverage was not measured", "no ... entries are recorded for this period (blocks X)")."""
    return ("input '" in message and ("is available for" in message or "coverage was not measured" in message or "was not measured" in message)) or bool(_BLOCKS.search(message))


def _fields_of(message: str) -> list[str]:
    m = _FIELD_HEAD.match(message.strip())
    return [f.strip() for f in m.group("fields").split(",")] if m else []


def summarise(messages: Sequence[str]) -> tuple[list[str], str | None]:
    """(messages that are NOT technical, kept as they are; ONE plain explanation of all the technical ones, or None when there were none)."""
    keep: list[str] = []
    needs: list[str] = []
    names: list[str] = []
    for msg in messages:
        if not is_technical(msg):
            keep.append(msg)
            continue
        for f in _fields_of(msg):
            if f in _NEEDS and f not in needs:
                needs.append(f)
        for code in _BLOCKS.findall(msg):
            label = _NAMES.get(code, code.replace("_", " ").lower())
            if label not in names:
                names.append(label)
    if not needs and not names:
        return keep, None
    needs.sort(key=lambda f: _ORDER.index(f))
    what = ", ".join(names) if names else "some of your figures"
    wants = "; ".join(_NEEDS[f] for f in needs) if needs else "more of your financial records"
    text = (f"I cannot calculate {what} yet, because your financial records do not hold what they need. To get them, I need: {wants}. "
            "Technical detail for each figure is on the CFO page under 'Why this figure?'.")
    return keep, text
