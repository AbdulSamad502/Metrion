"""L7 mechanism — the LLM extraction step's prompt construction and deterministic response
parsing (§8.4.1, "LLM extraction step (mechanism for L7)").

**The hard constraint this module exists to enforce.** Per §8.4.1: the prompt gives the model
(1) the query and (2) the actual fetched page text from the current attempt only, and
constrains it to extract a rate/HSN/category *only* when the fetched text itself states one —
"never answered from the model's own training knowledge... rather than the LLM inferring or
guessing from adjacent context." `build_extraction_prompt` is the only place that constraint
is stated; `parse_extraction_response` is the only place a model's text response is ever
turned back into structured data, and it is a plain, deterministic parser (no second LLM call,
no eval) — CLAUDE.md's "LLMs explain/extract, they never compute" boundary, extended by §8.4.1
to cited-text extraction: the model may locate what a page says, never supply a figure the
page doesn't contain, and this module never "fills in" what a malformed response left out.

**Response format — a small, fixed-key line format**, chosen over asking for JSON because a
local/open model (Ollama in dev, per CLAUDE.md's stack) is more reliably coerced into a short,
repeated `KEY: value` shape than well-formed JSON, and the parser below needs no JSON library
error-handling path to reach the same "malformed -> no match" outcome — a missing/garbled line
is just a missing/garbled line, matched by regex, never partially trusted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from fractions import Fraction

from calc_engine.gst_lookup.types import GstLookupQuery

_EXTRACTION_INSTRUCTIONS = """\
You are extracting GST (Goods and Services Tax) rate information for an Indian e-commerce \
product, from ONE fetched web page's text.

STRICT RULE: only report a rate, HSN code or category if the fetched page text below \
EXPLICITLY states it for this product or a clearly matching product category. Do NOT use \
your own general knowledge of GST rates. Do NOT infer a rate from a related but different \
item. If the fetched text does not state a rate/HSN/category that genuinely matches the \
query, you MUST answer "MATCH: NO" and leave every other field NONE.

Respond in EXACTLY this format — one field per line, nothing else, no extra commentary:
MATCH: YES or NO
RATE_PCT: <number, e.g. 18 or 18.0, or NONE>
HSN: <HSN/SAC code stated on the page, or NONE>
CATEGORY: <short category label stated on the page, or NONE>
AMBIGUOUS: YES or NO
AMBIGUITY_NOTE: <one sentence explaining the ambiguity, or NONE>
ALTERNATIVE: rate_pct=<number or NONE>; hsn=<code or NONE>; category=<text or NONE>

(Repeat the ALTERNATIVE line once per additional competing classification actually found on \
the page; omit it entirely if there is only one candidate.)
"""


def build_extraction_prompt(query: GstLookupQuery, *, page_text: str, source_url: str) -> str:
    """(1) the query, (2) the fetched page text from THIS attempt only — never the query
    alone, never a previous attempt's text (§8.4.1)."""
    query_line = f"product_title={query.product_title!r}, hsn={query.hsn!r}, category={query.category!r}"
    return (
        f"{_EXTRACTION_INSTRUCTIONS}\n"
        f"Query: {query_line}\n\n"
        f"Fetched page text (source: {source_url}):\n"
        f"{page_text}\n"
    )


@dataclass(frozen=True, slots=True)
class ExtractionResult:
    """Internal to this module and `lookup.py` — never persisted directly; `lookup.py` maps a
    genuine match into a real `GstLookupResult`."""

    rate_pct: Fraction | None
    hsn: str | None
    category: str | None
    ambiguous: bool
    ambiguity_note: str | None
    alternatives: tuple[dict[str, object], ...]


_LINE_RE = re.compile(r"^\s*([A-Za-z_]+)\s*:\s*(.*?)\s*$")
_ALT_FIELD_RE = re.compile(r"(\w+)\s*=\s*([^;]*)")


def _none_or(value: str) -> str | None:
    v = value.strip()
    return None if v == "" or v.upper() == "NONE" else v


def _parse_fraction(value: str | None) -> Fraction | None:
    v = _none_or(value or "")
    if v is None:
        return None
    v = v.rstrip("%").strip()
    try:
        return Fraction(v)
    except (ValueError, ZeroDivisionError):
        return None


def _parse_alternative_line(value: str) -> dict[str, object]:
    fields: dict[str, object] = {"rate_pct": None, "hsn": None, "category": None}
    for match in _ALT_FIELD_RE.finditer(value):
        key, raw = match.group(1).strip().lower(), match.group(2)
        if key == "rate_pct":
            fields["rate_pct"] = _parse_fraction(raw)
        elif key == "hsn":
            fields["hsn"] = _none_or(raw)
        elif key == "category":
            fields["category"] = _none_or(raw)
    return fields


def parse_extraction_response(raw: str) -> ExtractionResult | None:
    """Returns `None` for: no genuine match (`MATCH: NO`), or a malformed/unparseable
    response — both are treated identically by `lookup.py` (fall through to the next known
    page, or `GstLookupNoMatch` if none remain). Never raises; never returns a result built
    from a partial/garbled parse (L4/L7: "confident-sounding single answers are not produced
    from ambiguous evidence" extends here to *malformed* evidence too — a half-parsed response
    is not trustworthy evidence either)."""
    try:
        fields: dict[str, str] = {}
        alternatives: list[dict[str, object]] = []
        for line in raw.splitlines():
            m = _LINE_RE.match(line)
            if not m:
                continue
            key, value = m.group(1).upper(), m.group(2)
            if key == "ALTERNATIVE":
                alternatives.append(_parse_alternative_line(value))
            elif key not in fields:  # first occurrence wins for singular keys
                fields[key] = value

        match_raw = fields.get("MATCH", "").strip().upper()
        if match_raw not in ("YES", "NO"):
            return None  # malformed — no recognisable MATCH verdict.
        if match_raw == "NO":
            return None  # genuine no-match.

        rate_pct = _parse_fraction(fields.get("RATE_PCT"))
        hsn = _none_or(fields.get("HSN", ""))
        category = _none_or(fields.get("CATEGORY", ""))
        if rate_pct is None and hsn is None and category is None:
            # "YES" with nothing actually extracted is not a genuine match — malformed.
            return None

        ambiguous = fields.get("AMBIGUOUS", "").strip().upper() == "YES"
        ambiguity_note = _none_or(fields.get("AMBIGUITY_NOTE", ""))

        return ExtractionResult(
            rate_pct=rate_pct,
            hsn=hsn,
            category=category,
            ambiguous=ambiguous,
            ambiguity_note=ambiguity_note,
            alternatives=tuple(alternatives),
        )
    except Exception:
        # Never crash on a malformed model response — treated identically to "no match".
        return None
