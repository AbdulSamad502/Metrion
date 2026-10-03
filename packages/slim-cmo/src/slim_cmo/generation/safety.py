"""Deterministic safety glue between provider output and the P2 validators.

`prose_findings` runs the narration check (forbidden content, numbers that appear in no input,
the VALUE of an ineligible attribute) over every generated string. The structural validators
(lengths, counts, duplicates, bytes) are the P2 `check_*` functions; this module adds only what
they do not already run on their own. It invents no rule.

Known validation limitation (P3 decision 12): contradiction between generated copy and the
approved title in MEANING cannot be established deterministically and is NOT detected. What is
enforced: unsupported / ineligible attributes, unsupported numbers, forbidden content, structure.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from slim_cmo.forbidden import scan_forbidden
from slim_cmo.generation.facts import FactContext, is_price_name
from slim_cmo.generation.safety_limits import MAX_DECLARED_MISSING_FACTS, MAX_FACT_NAME_CHARS, MAX_FEEDBACK_LINES
from slim_cmo.narration import check_copy_prose
from slim_cmo.textnorm import clean_generated_text, collapse_whitespace, dedupe_key
from slim_cmo.validators import Violation


@dataclass(frozen=True, slots=True)
class ProseFinding:
    field: str
    kind: str  # FORBIDDEN | UNSUPPORTED_NUMBER | INELIGIBLE_ATTRIBUTE
    rule: str  # rule id / number token / attribute NAME - never the model's text


def prose_findings(
    items: Sequence[tuple[str, str]], ctx: FactContext, *, extra_allowed: Sequence[str] = ()
) -> tuple[ProseFinding, ...]:
    """`items` are `(field, text)`. `extra_allowed` is further text the output is entitled to
    repeat: the approved title (its numbers and words are grounded by the seller's approval)."""
    out: list[ProseFinding] = []
    for field, text in items:
        if not text:
            continue
        for f in check_copy_prose(text, eligible=ctx.eligible, ineligible=ctx.ineligible, extra_allowed_text=extra_allowed):
            out.append(ProseFinding(field, f.kind, f.rule))
    return tuple(out)


def ineligible_names(findings: Iterable[ProseFinding]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(f.rule for f in findings if f.kind == "INELIGIBLE_ATTRIBUTE"))


def feedback_lines(violations: Iterable[Violation], findings: Iterable[ProseFinding]) -> tuple[str, ...]:
    """Lines sent back to the model on a retry. They carry field names, rule ids and counts ONLY.
    They deliberately never echo a number token or an attribute name from the findings: an
    ineligible attribute's value (an ESTIMATED weight, an unverified image hint) must not reach a
    prompt, even indirectly."""
    lines: list[str] = [str(v) for v in violations]
    for f in findings:
        if f.kind == "FORBIDDEN":
            lines.append(f"{f.field}: FORBIDDEN_CONTENT ({f.rule})")
        elif f.kind == "UNSUPPORTED_NUMBER":
            lines.append(f"{f.field}: contains a number that is not in the confirmed facts")
        elif f.kind == "INELIGIBLE_ATTRIBUTE":
            lines.append(f"{f.field}: states a detail that is not a confirmed fact")
    return tuple(dict.fromkeys(lines))[:MAX_FEEDBACK_LINES]


def rule_ids(violations: Iterable[Violation], findings: Iterable[ProseFinding]) -> tuple[str, ...]:
    ids = [v.code.value for v in violations]
    ids += [f"{f.kind}:{f.rule}" if f.kind == "FORBIDDEN" else f.kind for f in findings]
    return tuple(ids)


_ALLOWED_PUNCT = " -_/&'"


def screen_fact_names(names: Iterable[str]) -> tuple[str, ...]:
    """A "fact to supply" shown to the seller must be a SHORT NAME of a fact - never a sentence,
    never a number, never forbidden content. Names that fail are dropped (and if none survive, the
    caller does not claim NEEDS_FACTS)."""
    kept: list[str] = []
    seen: set[str] = set()
    for raw in names:
        if not isinstance(raw, str):
            continue
        name = collapse_whitespace(clean_generated_text(raw))
        if not name or len(name) > MAX_FACT_NAME_CHARS:
            continue
        if not all(ch.isalpha() or unicodedata.category(ch)[0] == "M" or ch in _ALLOWED_PUNCT for ch in name):
            continue  # digits, symbols, control characters, newlines
        if scan_forbidden(name) or is_price_name(name):
            continue  # CMO never asks the seller for, or states, a price (C7)
        key = dedupe_key(name)
        if not key or key in seen:
            continue
        seen.add(key)
        kept.append(name)
        if len(kept) >= MAX_DECLARED_MISSING_FACTS:
            break
    return tuple(kept)
