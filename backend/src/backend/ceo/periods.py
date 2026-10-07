"""Deterministic period resolution (spec §6.3 rule 3: "Dates/periods likewise" parsed by code, echoed back for confirmation, AC17).

The classifier extracts a period as TEXT ("September", "last month"). It never produces a date. This module turns that text into a
concrete range or refuses (`PeriodUnresolvable` -> the turn asks the seller, spec E22) — it never guesses. What it resolved is always
echoed to the seller (`ResolvedPeriod.echo`).

Supported, and only these: `last month` / `previous month`, `this month`, `<month name> [<year>]`, `YYYY-MM`, and an explicit
`YYYY-MM-DD to YYYY-MM-DD`. A bare month name means its most recent occurrence not in the future. Quarters ("last quarter") are
deliberately NOT supported: calendar and Indian fiscal quarters differ, so the seller is asked.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date

_MONTHS = {name.lower(): i for i, name in enumerate(calendar.month_name) if name}
_MONTHS.update({name.lower(): i for i, name in enumerate(calendar.month_abbr) if name})
_MONTHS["sept"] = 9

_ISO_RANGE = re.compile(r"^(\d{4}-\d{2}-\d{2})\s*(?:to|-|–|/)\s*(\d{4}-\d{2}-\d{2})$")
_ISO_MONTH = re.compile(r"^(\d{4})-(\d{2})$")
_MONTH_YEAR = re.compile(r"^(?:for\s+|in\s+|of\s+)?([a-z]+)\.?(?:\s+(\d{4}))?$")


class PeriodUnresolvable(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ResolvedPeriod:
    start: date
    end: date
    as_of: date  # the day the request was made — never a seller-chosen or model-chosen date
    echo: str  # shown back to the seller so a wrong interpretation is visible


def _month_range(year: int, month: int) -> tuple[date, date]:
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def _previous_month(today: date) -> tuple[int, int]:
    return (today.year - 1, 12) if today.month == 1 else (today.year, today.month - 1)


def _echo(raw: str, start: date, end: date) -> str:
    return f"I read the period '{raw.strip()}' as {start.isoformat()} to {end.isoformat()}."


def resolve_period(raw: str | None, *, today: date) -> ResolvedPeriod:
    text = (raw or "").strip().lower()
    if not text:
        raise PeriodUnresolvable("no period given")

    if text in ("last month", "previous month", "the last month", "the previous month"):
        start, end = _month_range(*_previous_month(today))
        return ResolvedPeriod(start, end, today, _echo(raw or "", start, end))
    if text in ("this month", "the current month", "current month", "month to date", "so far this month"):
        start = today.replace(day=1)
        return ResolvedPeriod(start, today, today, _echo(raw or "", start, today))

    m = _ISO_RANGE.match(text)
    if m:
        try:
            start, end = date.fromisoformat(m.group(1)), date.fromisoformat(m.group(2))
        except ValueError as exc:
            raise PeriodUnresolvable("not a valid date range") from exc
        if end < start:
            raise PeriodUnresolvable("the range ends before it starts")
        if start > today:
            raise PeriodUnresolvable("that period has not started yet")
        end = min(end, today)
        return ResolvedPeriod(start, end, today, _echo(raw or "", start, end))

    m = _ISO_MONTH.match(text)
    if m and 1 <= int(m.group(2)) <= 12:
        start, end = _month_range(int(m.group(1)), int(m.group(2)))
        if start > today:
            raise PeriodUnresolvable("that period has not started yet")
        end = min(end, today)
        return ResolvedPeriod(start, end, today, _echo(raw or "", start, end))

    m = _MONTH_YEAR.match(text)
    if m and m.group(1) in _MONTHS:
        month = _MONTHS[m.group(1)]
        if m.group(2):
            year = int(m.group(2))
        else:  # the most recent occurrence of that month that is not in the future
            year = today.year if month <= today.month else today.year - 1
        start, end = _month_range(year, month)
        if start > today:
            raise PeriodUnresolvable("that period has not started yet")
        end = min(end, today)
        return ResolvedPeriod(start, end, today, _echo(raw or "", start, end))

    raise PeriodUnresolvable("period not recognised")
