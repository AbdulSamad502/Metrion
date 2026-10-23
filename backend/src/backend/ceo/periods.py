"""Deterministic period resolution (spec §6.3 rule 3: "Dates/periods likewise" parsed by code, echoed back for confirmation, AC17).

The classifier extracts a period as TEXT ("September", "last month"). It never produces a date. This module turns that text into a
concrete range or refuses (`PeriodUnresolvable` -> the turn asks the seller, spec E22) — it never guesses. What it resolved is always
echoed to the seller (`ResolvedPeriod.echo`).

Supported, and only these: `last month` / `previous month`, `this month`, `today`, `yesterday`, `last N days`, a single day
(`YYYY-MM-DD`, `5 October [2026]`, `October 5 [2026]`, `5/10/2026` read day-first), a range of two such days (`<day> to <day>`),
`<month name> [<year>]`, `YYYY-MM`, and an explicit `YYYY-MM-DD to YYYY-MM-DD`. A bare month name or a day without a year means its most
recent occurrence not in the future. Quarters ("last quarter") are deliberately NOT supported: calendar and Indian fiscal quarters
differ, so the seller is asked.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date, timedelta

_MONTHS = {name.lower(): i for i, name in enumerate(calendar.month_name) if name}
_MONTHS.update({name.lower(): i for i, name in enumerate(calendar.month_abbr) if name})
_MONTHS["sept"] = 9

_ISO_RANGE = re.compile(r"^(\d{4}-\d{2}-\d{2})\s*(?:to|-|–|/)\s*(\d{4}-\d{2}-\d{2})$")
_ISO_MONTH = re.compile(r"^(\d{4})-(\d{2})$")
_MONTH_YEAR = re.compile(r"^(?:for\s+|in\s+|of\s+)?([a-z]+)\.?(?:\s+(\d{4}))?$")


class PeriodUnresolvable(ValueError):
    pass


_DAY_MONTH = re.compile(r"^(?:on\s+)?(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?([a-z]+)\.?(?:,?\s+(\d{4}))?$")
_MONTH_DAY = re.compile(r"^(?:on\s+)?([a-z]+)\.?\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(\d{4}))?$")
_SLASH_DATE = re.compile(r"^(?:on\s+)?(\d{1,2})[/-](\d{1,2})[/-](\d{4})$")
_LAST_N_DAYS = re.compile(r"^(?:the\s+)?(?:last|past|previous)\s+(\d{1,3})\s+days?$")
_RANGE_OF_DAYS = re.compile(r"^(?:from\s+)?(.+?)\s+(?:to|till|until|through|-|–)\s+(.+)$")


def single_day(raw: str, *, today: date) -> date | None:
    """One calendar day written in a form we read exactly, or None. A day without a year is its most recent occurrence not in the future."""
    text = " ".join((raw or "").strip().lower().split()).strip(" .,")
    if text == "today":
        return today
    if text == "yesterday":
        return today - timedelta(days=1)
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
            return date.fromisoformat(text)
        m = _SLASH_DATE.match(text)
        if m:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))  # day first
        m = _DAY_MONTH.match(text)
        day, month_name, year = (m.group(1), m.group(2), m.group(3)) if m else (None, None, None)
        if not m:
            m = _MONTH_DAY.match(text)
            if m:
                month_name, day, year = m.group(1), m.group(2), m.group(3)
        if m and month_name in _MONTHS:
            month = _MONTHS[month_name]
            if year:
                return date(int(year), month, int(day))
            candidate = date(today.year, month, int(day))
            return candidate if candidate <= today else date(today.year - 1, month, int(day))
    except ValueError:
        return None
    return None


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

    d = single_day(text, today=today)
    if d is not None:
        if d > today:
            raise PeriodUnresolvable("that day has not come yet")
        return ResolvedPeriod(d, d, today, _echo(raw or "", d, d))
    m = _LAST_N_DAYS.match(text)
    if m and 1 <= int(m.group(1)) <= 366:
        start = today - timedelta(days=int(m.group(1)) - 1)
        return ResolvedPeriod(start, today, today, _echo(raw or "", start, today))
    m = _RANGE_OF_DAYS.match(text)
    if m and not _ISO_RANGE.match(text):
        a, b = single_day(m.group(1), today=today), single_day(m.group(2), today=today)
        if a is not None and b is not None:
            if b < a:
                raise PeriodUnresolvable("the range ends before it starts")
            if a > today:
                raise PeriodUnresolvable("that period has not started yet")
            b = min(b, today)
            return ResolvedPeriod(a, b, today, _echo(raw or "", a, b))
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
