"""Column profiling and file fingerprinting (cfo-data-intelligence.md §6.4).

Profiles are computed over a bounded sample the caller supplies — never the whole file held in memory by
this module. Parsing helpers are exact (`Decimal`, never float). Nothing here infers meaning; it measures
what the values look like, and the validator decides what that means for a proposed mapping.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from fractions import Fraction

from data_foundation.mapping.units import parse_percent_points
from data_foundation.mapping.vocab import normalise_header

_CURRENCY_SYMBOLS = re.compile(r"(?i)^\s*(?:₹|rs\.?|inr)\s*")
_FOREIGN_CURRENCY = re.compile(r"(?i)(\$|usd|€|eur|£|gbp|aed)")
_DATE_FORMATS: dict[str, tuple[str, ...]] = {
    "DATE_ISO": ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"),
    "DATE_DMY": ("%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%y", "%d-%m-%y", "%d %b %Y", "%d-%b-%Y", "%d/%m/%Y %H:%M:%S"),
    "DATE_MDY": ("%m/%d/%Y", "%m-%d-%Y", "%m/%d/%y", "%m/%d/%Y %H:%M:%S"),
}
_NUM_BODY = re.compile(r"^-?\d+(?:\.\d+)?$")


def parse_decimal(raw: str) -> Decimal | None:
    """Parse a money/number string: optional ₹/Rs/INR prefix, Indian or western digit grouping, leading '-'
    or accounting parentheses for negatives. Returns None when it is not a plain number."""
    s = raw.strip()
    if not s:
        return None
    negative = False
    if s.startswith("(") and s.endswith(")"):
        negative, s = True, s[1:-1].strip()
    s = _CURRENCY_SYMBOLS.sub("", s).replace(",", "").replace(" ", "")
    if s.startswith("-"):
        negative, s = True, s[1:]
    if not _NUM_BODY.match(s):
        return None
    try:
        d = Decimal(s)
    except InvalidOperation:
        return None
    return -d if negative else d


def parse_date_with(raw: str, transform: str) -> date | None:
    s = raw.strip()
    for fmt in _DATE_FORMATS.get(transform, ()):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


@dataclass(frozen=True, slots=True)
class ColumnProfile:
    index: int
    name: str
    rows_seen: int
    non_null: int
    distinct_count: int
    numeric_parse_rate: Fraction  # share of non-null values that parse as a number
    integer_parse_rate: Fraction  # share that parse as a whole number with no decimal point
    date_parse_rate: dict[str, Fraction]  # transform id -> share of non-null values that parse
    negative_share: Fraction  # share of numeric values below zero
    fractional_share: Fraction  # share of numeric values with a non-zero fractional part
    max_decimal_places: int
    foreign_currency_share: Fraction
    enum_values: tuple[str, ...]  # distinct values when there are at most 20 (for seller confirmation of statuses)
    date_min: date | None
    date_max: date | None
    percent_parse_rate: Fraction  # share of non-null values that are a valid percentage (mapping/units.py)
    date_dmy_certain: bool  # some value has a first component > 12
    date_mdy_certain: bool  # some value has a second component > 12

    @property
    def null_rate(self) -> Fraction:
        return Fraction(self.rows_seen - self.non_null, self.rows_seen) if self.rows_seen else Fraction(1)


def _decimal_places(d: Decimal) -> int:
    exp = d.as_tuple().exponent
    return -exp if isinstance(exp, int) and exp < 0 else 0


def _share(n: int, d: int) -> Fraction:
    return Fraction(n, d) if d else Fraction(0)


def profile_columns(columns: Sequence[str], rows: Sequence[Sequence[str]]) -> tuple[ColumnProfile, ...]:
    out: list[ColumnProfile] = []
    for i, name in enumerate(columns):
        vals = [(r[i] if i < len(r) else "") for r in rows]
        nn = [v for v in vals if v is not None and str(v).strip() != ""]
        n = len(nn)
        nums = [parse_decimal(v) for v in nn]
        numeric = [d for d in nums if d is not None]
        int_ok = sum(1 for v, d in zip(nn, nums) if d is not None and "." not in v)
        frac = sum(1 for d in numeric if d != d.to_integral_value())
        decimals = max((_decimal_places(d) for d in numeric), default=0)
        date_rates: dict[str, Fraction] = {}
        parsed_dates: list[date] = []
        for tr in _DATE_FORMATS:
            ok = [parse_date_with(v, tr) for v in nn]
            date_rates[tr] = _share(sum(1 for d in ok if d is not None), n)
        best = max(date_rates, key=lambda k: date_rates[k]) if date_rates else "DATE_ISO"
        if date_rates and date_rates[best] > 0:
            parsed_dates = [d for d in (parse_date_with(v, best) for v in nn) if d is not None]
        dmy = mdy = False
        for v in nn:
            m = re.match(r"^\s*(\d{1,2})[/\-.](\d{1,2})[/\-.]\d{2,4}", v)
            if m:
                a, b = int(m.group(1)), int(m.group(2))
                dmy = dmy or a > 12
                mdy = mdy or b > 12
        distinct = sorted(set(nn))
        out.append(ColumnProfile(
            index=i, name=name, rows_seen=len(rows), non_null=n, distinct_count=len(distinct),
            numeric_parse_rate=_share(len(numeric), n), integer_parse_rate=_share(int_ok, n), date_parse_rate=date_rates,
            negative_share=_share(sum(1 for d in numeric if d < 0), len(numeric)),
            fractional_share=_share(frac, len(numeric)), max_decimal_places=decimals,
            foreign_currency_share=_share(sum(1 for v in nn if _FOREIGN_CURRENCY.search(v)), n),
            enum_values=tuple(distinct) if len(distinct) <= 20 else (),
            date_min=min(parsed_dates) if parsed_dates else None, date_max=max(parsed_dates) if parsed_dates else None,
            percent_parse_rate=_share(sum(1 for v in nn if parse_percent_points(v) is not None), n),
            date_dmy_certain=dmy, date_mdy_certain=mdy,
        ))
    return tuple(out)


def file_fingerprint(columns: Sequence[str], sheet_name: str | None = None) -> str:
    """Stable id of a file's *shape*: the normalised, order-independent header multiset plus the sheet name.
    The same fingerprint reuses a previously confirmed mapping; any change in headers is a new shape."""
    material = "|".join(sorted(normalise_header(c) for c in columns)) + "##" + normalise_header(sheet_name or "")
    return hashlib.sha256(material.encode()).hexdigest()
