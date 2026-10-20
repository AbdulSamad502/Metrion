"""The composition gate — spec §6.5 / R4 / AC21 (production since B3; moved unchanged from the evaluation harness, whose gate module re-exports it).

Counts and rejects numerals and illegal markers in a model draft. Deliberately conservative and deterministic; the same code is
the evaluation harness's measuring instrument, so the measured behaviour and the shipped behaviour cannot drift.

A composer draft is free text plus markers `{{TOKEN}}`:

    F# figure value   K# (not a marker; facts are text)   G# named gap   V# verbatim block   D# required disclaimer
    O# offered registered action   A# "Add <agent>" control   U# untrusted evidence (never a marker)

Everything OUTSIDE the markers is the model's own prose, and must contain no numeral.

Strictness is a measured question (spec §6.5 closing note, Q13), so numeral findings are classified:
`NUMERAL_DIGIT_DATE` (a year/day-month — the likeliest false positive of a strict rule) is reported separately from
`NUMERAL_DIGIT`, `NUMERAL_CURRENCY`, `NUMERAL_PERCENT` and `NUMERAL_WORD`.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from backend.services.ci_conv_data import currency_claims as _ci_currency_claims  # the one list of "claims CI does not have" (CI spec C40, AC47)

MARKER_RE = re.compile(r"\{\{\s*([A-Za-z0-9_:\-]+)\s*\}\}")

_MONTHS = r"(jan(uary)?|feb(ruary)?|mar(ch)?|apr(il)?|may|jun(e)?|jul(y)?|aug(ust)?|sep(t(ember)?)?|oct(ober)?|nov(ember)?|dec(ember)?)"
_DATE_LIKE_RE = re.compile(rf"(\b(19|20)\d{{2}}\b|\b\d{{1,2}}(st|nd|rd|th)?\s+{_MONTHS}\b|\b{_MONTHS}\s+\d{{1,2}}(st|nd|rd|th)?\b)", re.IGNORECASE)
_DIGIT_RE = re.compile(r"\d")
_CURRENCY_RE = re.compile(r"(₹|\$|€|£|\bRs\.?|\bINR\b|\bUSD\b)", re.IGNORECASE)
_PERCENT_RE = re.compile(r"(%|\bper\s?cent(age)?s?\b|\bpercent(age)?s?\b)", re.IGNORECASE)
_MAGNITUDE_RE = re.compile(r"\b(hundreds?|thousands?|lakhs?|lacs?|crores?|millions?|billions?)\b", re.IGNORECASE)
_NUMBER_WORDS = (
    "zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|"
    "eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety"
)
# A number word restating a QUANTITY (money / units / rates). Counts of enumerated items ("three options") and time spans are
# deliberately not flagged: the spec allows counts in words and the gate must not be unusable.
_UNIT_WORDS = r"(rupees?|paise|rs|units?|orders?|sales|items?|pieces?|pcs|times|x)"
_NUMBER_WORD_QUANTITY_RE = re.compile(rf"\b({_NUMBER_WORDS})([\s\-]+({_NUMBER_WORDS}))?\s+{_UNIT_WORDS}\b", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class Violation:
    code: str
    detail: str = ""


NUMERAL_CODES = frozenset({"NUMERAL_DIGIT", "NUMERAL_DIGIT_DATE", "NUMERAL_CURRENCY", "NUMERAL_PERCENT", "NUMERAL_WORD"})


def markers_in(text: str) -> list[str]:
    return [m.group(1) for m in MARKER_RE.finditer(text)]


def strip_markers(text: str) -> str:
    return MARKER_RE.sub(" ", text)


def numeral_violations(prose: str) -> list[Violation]:
    """Numerals in the model's own prose (markers already removed)."""
    out: list[Violation] = []
    for m in _CURRENCY_RE.finditer(prose):
        out.append(Violation("NUMERAL_CURRENCY", m.group(0)))
    for m in _PERCENT_RE.finditer(prose):
        out.append(Violation("NUMERAL_PERCENT", m.group(0)))
    for m in _MAGNITUDE_RE.finditer(prose):
        out.append(Violation("NUMERAL_WORD", m.group(0)))
    for m in _NUMBER_WORD_QUANTITY_RE.finditer(prose):
        out.append(Violation("NUMERAL_WORD", m.group(0)))
    date_spans = [m.span() for m in _DATE_LIKE_RE.finditer(prose)]
    for m in _DIGIT_RE.finditer(prose):
        inside_date = any(s <= m.start() < e for s, e in date_spans)
        out.append(Violation("NUMERAL_DIGIT_DATE" if inside_date else "NUMERAL_DIGIT", m.group(0)))
    # one finding per distinct span is plenty for a rate; collapse digit runs ("1,00,000" is one finding, not seven)
    return _collapse(out)


# CI narration (CI spec C26, C40, C45). Competitor Intelligence states observations from the seller's own evidence; it neither watches competitors nor advises on price or margin
# (that is the finance side's, from Brain 1 figures). An answer built from CI results is therefore checked for three things on top of the numeral rule:
#   LIVE_CLAIM                 - it must not claim live / real-time / continuous / "currently priced" knowledge;
#   UNSUPPORTED_RECOMMENDATION - it must not tell the seller to change their price unless a finance result is part of the evidence;
#   MARGIN_CLAIM               - it must not say what a competitor move does to margin / profit unless a finance result is part of the evidence.
_REPRICE_ADVICE = re.compile(
    r"\b(?:you (?:should|could|might want to|ought to|need to|must|can)|i (?:recommend|suggest|advise)(?: that)? you|consider|try to|best to)\b[^.?!]{0,50}"
    r"\b(?:lower|raise|reduce|increase|cut|drop|match|beat|undercut|change|adjust|reprice|discount)\w*\b[^.?!]{0,30}\b(?:price|prices|pricing)\b"
    r"|\b(?:match|beat|undercut) (?:their|the|its) (?:price|pricing)\b|\breprice\b|\b(?:lower|raise|reduce|cut|increase) your price\b",
    re.IGNORECASE,
)
_MARGIN_CLAIM = re.compile(
    r"\b(?:your|their|the)\b[^.?!]{0,20}\b(?:margin|contribution|break-?even|profit)\b[^.?!]{0,40}\b(?:would|will|could|may|might|is|are|drops?|falls?|improves?|shrinks?|suffers?|stays?|goes?)\b"
    r"|\b(?:would|will|could|may|might)\b[^.?!]{0,30}\b(?:change|hurt|reduce|improve|affect|erode|squeeze|cut|lift|raise|lower|boost)\b[^.?!]{0,15}\b(?:your |the |their )?(?:margin|profit|contribution)\b",
    re.IGNORECASE,
)


def ci_narration_violations(prose: str, *, finance_present: bool) -> list[Violation]:
    out = [Violation("LIVE_CLAIM", name) for name in _ci_currency_claims(prose)]
    if not finance_present:
        out += [Violation("UNSUPPORTED_RECOMMENDATION", m.group(0)[:60]) for m in _REPRICE_ADVICE.finditer(prose)]
        out += [Violation("MARGIN_CLAIM", m.group(0)[:60]) for m in _MARGIN_CLAIM.finditer(prose)]
    return out


def _collapse(items: list[Violation]) -> list[Violation]:
    kept: list[Violation] = []
    for v in items:
        if v.code in ("NUMERAL_DIGIT", "NUMERAL_DIGIT_DATE") and kept and kept[-1].code == v.code:
            continue
        kept.append(v)
    return kept


@dataclass(frozen=True, slots=True)
class GateReport:
    violations: tuple[Violation, ...]

    @property
    def passed(self) -> bool:
        return not self.violations

    def codes(self) -> frozenset[str]:
        return frozenset(v.code for v in self.violations)

    @property
    def has_numeral(self) -> bool:
        return bool(self.codes() & NUMERAL_CODES)


def check_composition(
    text: str,
    *,
    figure_tokens: Mapping[str, bool],
    other_tokens: Iterable[str] = (),
    required_markers: Iterable[str] = (),
    forbidden_markers: Iterable[str] = (),
    ci_narration: bool = False,
    finance_present: bool = False,
) -> GateReport:
    """`figure_tokens` maps each figure token to `is_available` (an UNAVAILABLE figure may never be presented as a value).
    `other_tokens` are the remaining legal marker names (G#/V#/D#/O#/A#). Required/forbidden markers are case-level."""
    violations: list[Violation] = []
    legal = set(figure_tokens) | set(other_tokens)
    used = markers_in(text)
    for tok in used:
        if tok not in legal:
            violations.append(Violation("UNKNOWN_TOKEN", tok))
        elif tok in figure_tokens and not figure_tokens[tok]:
            violations.append(Violation("UNAVAILABLE_AS_VALUE", tok))
    for tok in required_markers:
        if tok not in used:
            violations.append(Violation("MISSING_REQUIRED", tok))
    for tok in forbidden_markers:
        if tok in used:
            violations.append(Violation("FORBIDDEN_MARKER", tok))
    violations.extend(numeral_violations(strip_markers(text)))
    if ci_narration:
        violations.extend(ci_narration_violations(strip_markers(text), finance_present=finance_present))
    return GateReport(tuple(violations))
