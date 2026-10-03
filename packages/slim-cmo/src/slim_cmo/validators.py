"""Deterministic validation of generated listing artefacts against a resolved marketplace
constraint (spec §6.3, §6.4 rule 4, AC9, AC13, AC25).

The LLM never reports its own lengths and is never trusted to have met a limit: every count and
size below is computed here, from the text, with the conservative counting rules in `textnorm`.

Contract:

* Each `check_*` takes the model's RAW output, applies the tolerant first pass
  (`clean_generated_text`: NFC, strip invisible characters, trim the ends) and judges what the
  model actually produced. It returns the cleaned text alongside the verdict - callers persist
  the cleaned text, never the raw.
* A limit the constraint row does not state (`None`) is NOT enforced and NOT guessed (§6.4);
  the resolver already reported it as unverified.
* Characters are counted by the constraint's VERIFIED `count_rule` (`textnorm.count_by_rule`);
  the code's own UTF-16 count is only the conservative implementation fallback behind it.
* A limit needed to define the artefact itself (title option count, bullet count, backend
  byte cap, counting rule) that is `None` here is a programming error - `constraints.resolve_constraint`
  guarantees it is present - so it raises `ConstraintFieldMissing` rather than silently
  skipping a check.
* Nothing is ever repaired in place. A violation means: regenerate, or return short and
  labelled, or fail (spec §8.3).
"""

from __future__ import annotations

import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any

from slim_cmo.constraints import FormatConstraint
from slim_cmo.forbidden import scan_forbidden
from slim_cmo.textnorm import (
    clean_generated_text,
    count_by_rule,
    dedupe_key,
    has_control_characters,
    utf8_bytes,
)



class ConstraintFieldMissing(RuntimeError):
    """A limit that defines the artefact was None. `resolve_constraint` prevents this; reaching
    it means a caller skipped the resolver."""


class ViolationCode(str, Enum):
    WRONG_TYPE = "WRONG_TYPE"
    EMPTY = "EMPTY"
    CONTROL_CHARACTER = "CONTROL_CHARACTER"
    TOO_LONG = "TOO_LONG"
    TOO_MANY = "TOO_MANY"
    TOO_FEW = "TOO_FEW"
    DUPLICATE = "DUPLICATE"
    BYTES_EXCEEDED = "BYTES_EXCEEDED"
    FORBIDDEN_CONTENT = "FORBIDDEN_CONTENT"
    INVALID_HASHTAG = "INVALID_HASHTAG"


@dataclass(frozen=True, slots=True)
class Violation:
    code: ViolationCode
    field: str
    detail: str = ""  # rule ids and counts only - never seller text

    def __str__(self) -> str:
        return f"{self.field}: {self.code.value}" + (f" ({self.detail})" if self.detail else "")


@dataclass(frozen=True, slots=True)
class TextCheck:
    text: str
    violations: tuple[Violation, ...]

    @property
    def valid(self) -> bool:
        return not self.violations


@dataclass(frozen=True, slots=True)
class ListCheck:
    items: tuple[str, ...]
    violations: tuple[Violation, ...]

    @property
    def valid(self) -> bool:
        return not self.violations


@dataclass(frozen=True, slots=True)
class TitleCheck:
    text: str
    char_count: int
    violations: tuple[Violation, ...]

    @property
    def valid(self) -> bool:
        return not self.violations


def _forbidden(text: str, field: str, allowed_context: str | None) -> list[Violation]:
    return [
        Violation(ViolationCode.FORBIDDEN_CONTENT, field, f"{f.category.value}:{f.rule}")
        for f in scan_forbidden(text, allowed_context=allowed_context)
    ]


def _rule(c: FormatConstraint) -> str:
    """The VERIFIED character-counting rule for this constraint. `resolve_constraint` blocks a
    marketplace whose row does not state one, so reaching here without it is a caller bug."""
    return str(_need(c.count_rule, "count_rule").value)


def _need(value: Any, name: str) -> Any:
    if value is None:
        raise ConstraintFieldMissing(f"constraint field {name} is required to validate this artefact")
    return value


# --------------------------------------------------------------------------------------------
# titles
# --------------------------------------------------------------------------------------------


def check_title(raw: object, c: FormatConstraint, *, field: str = "title", allowed_context: str | None = None) -> TitleCheck:
    if not isinstance(raw, str):
        return TitleCheck("", 0, (Violation(ViolationCode.WRONG_TYPE, field, type(raw).__name__),))
    text = clean_generated_text(raw)
    violations: list[Violation] = []
    if not text:
        return TitleCheck("", 0, (Violation(ViolationCode.EMPTY, field),))
    if has_control_characters(text):
        violations.append(Violation(ViolationCode.CONTROL_CHARACTER, field, "titles are single-line"))
    n = count_by_rule(text, _rule(c))
    if c.title_max_chars is not None and n > c.title_max_chars:
        violations.append(Violation(ViolationCode.TOO_LONG, field, f"{n}>{c.title_max_chars}"))
    violations += _forbidden(text, field, allowed_context)
    return TitleCheck(text, n, tuple(violations))


@dataclass(frozen=True, slots=True)
class AcceptedOption:
    rank: int  # presentation order 1..n - NOT a quality claim
    text: str
    char_count: int
    constraint_check: dict[str, Any]  # persisted verbatim in cmo_title_option.constraint_check


@dataclass(frozen=True, slots=True)
class RejectedOption:
    index: int  # position in the model's output
    violations: tuple[Violation, ...]


@dataclass(frozen=True, slots=True)
class TitleSetEvaluation:
    accepted: tuple[AcceptedOption, ...]
    rejected: tuple[RejectedOption, ...]
    expected_count: int
    surplus_dropped: int  # valid options beyond expected_count (dropped, not a violation)

    @property
    def short(self) -> bool:
        """Fewer valid options than the constraint asks for: returned short and LABELLED, never
        padded with invalid text (AC9)."""
        return len(self.accepted) < self.expected_count

    @property
    def complete(self) -> bool:
        return not self.short


def evaluate_title_set(
    raw_options: Sequence[object], c: FormatConstraint, *, allowed_context: str | None = None
) -> TitleSetEvaluation:
    expected = int(_need(c.title_option_count, "title_option_count"))
    accepted: list[AcceptedOption] = []
    rejected: list[RejectedOption] = []
    seen: dict[str, int] = {}
    surplus = 0
    for index, raw in enumerate(raw_options):
        check = check_title(raw, c, field=f"options[{index}]", allowed_context=allowed_context)
        violations = list(check.violations)
        if check.valid:
            key = dedupe_key(check.text)
            if key in seen:
                violations.append(Violation(ViolationCode.DUPLICATE, f"options[{index}]", f"same as options[{seen[key]}]"))
        if violations:
            rejected.append(RejectedOption(index, tuple(violations)))
            continue
        if len(accepted) >= expected:
            surplus += 1
            continue
        seen[dedupe_key(check.text)] = index
        accepted.append(
            AcceptedOption(
                rank=len(accepted) + 1,
                text=check.text,
                char_count=check.char_count,
                constraint_check={
                    "max_chars": c.title_max_chars,
                    "limit_unverified": c.title_max_chars is None,
                    "count_rule": _rule(c),
                    "passed": True,
                },
            )
        )
    return TitleSetEvaluation(tuple(accepted), tuple(rejected), expected, surplus)


# --------------------------------------------------------------------------------------------
# bullets / description / keywords
# --------------------------------------------------------------------------------------------


def _check_lines(
    raw_items: object, *, field: str, max_chars: int | None, allowed_context: str | None, rule: str | None
) -> tuple[list[str], list[Violation]]:
    """Shared per-item rules for bullets / keywords / terms: strings, non-empty, single-line,
    within the per-item limit, free of forbidden content, no duplicates."""
    if not isinstance(raw_items, (list, tuple)):
        return [], [Violation(ViolationCode.WRONG_TYPE, field, "expected a list")]
    items: list[str] = []
    violations: list[Violation] = []
    seen: dict[str, int] = {}
    for i, raw in enumerate(raw_items):
        name = f"{field}[{i}]"
        if not isinstance(raw, str):
            violations.append(Violation(ViolationCode.WRONG_TYPE, name, type(raw).__name__))
            items.append("")
            continue
        text = clean_generated_text(raw)
        items.append(text)
        if not text:
            violations.append(Violation(ViolationCode.EMPTY, name))
            continue
        if has_control_characters(text):
            violations.append(Violation(ViolationCode.CONTROL_CHARACTER, name, "single-line"))
        if max_chars is not None and rule is not None:
            n = count_by_rule(text, rule)
            if n > max_chars:
                violations.append(Violation(ViolationCode.TOO_LONG, name, f"{n}>{max_chars}"))
        violations += _forbidden(text, name, allowed_context)
        key = dedupe_key(text)
        if key in seen:
            violations.append(Violation(ViolationCode.DUPLICATE, name, f"same as {field}[{seen[key]}]"))
        else:
            seen[key] = i
    return items, violations


def check_bullets(raw: object, c: FormatConstraint, *, allowed_context: str | None = None) -> ListCheck:
    expected = int(_need(c.bullet_count, "bullet_count"))
    items, violations = _check_lines(raw, field="bullets", max_chars=c.bullet_max_chars, allowed_context=allowed_context, rule=_rule(c))
    if isinstance(raw, (list, tuple)):
        if len(items) > expected:
            violations.append(Violation(ViolationCode.TOO_MANY, "bullets", f"{len(items)}>{expected}"))
        elif len(items) < expected:
            violations.append(Violation(ViolationCode.TOO_FEW, "bullets", f"{len(items)}<{expected}"))
    return ListCheck(tuple(items), tuple(violations))


def check_description(raw: object, c: FormatConstraint, *, allowed_context: str | None = None) -> TextCheck:
    if not isinstance(raw, str):
        return TextCheck("", (Violation(ViolationCode.WRONG_TYPE, "description", type(raw).__name__),))
    text = clean_generated_text(raw)
    if not text:
        return TextCheck("", (Violation(ViolationCode.EMPTY, "description"),))
    violations: list[Violation] = []
    if has_control_characters(text, allow_newlines=True):  # paragraphs are allowed in a description
        violations.append(Violation(ViolationCode.CONTROL_CHARACTER, "description"))
    n = count_by_rule(text, _rule(c))
    if c.description_max_chars is not None and n > c.description_max_chars:
        violations.append(Violation(ViolationCode.TOO_LONG, "description", f"{n}>{c.description_max_chars}"))
    violations += _forbidden(text, "description", allowed_context)
    return TextCheck(text, tuple(violations))


def check_keywords(raw: object, c: FormatConstraint, *, allowed_context: str | None = None) -> ListCheck:
    items, violations = _check_lines(raw, field="keywords", max_chars=c.keywords_max_chars, allowed_context=allowed_context, rule=_rule(c))
    if isinstance(raw, (list, tuple)):
        if not items:
            violations.append(Violation(ViolationCode.EMPTY, "keywords"))
        elif c.keywords_max_count is not None and len(items) > c.keywords_max_count:
            violations.append(Violation(ViolationCode.TOO_MANY, "keywords", f"{len(items)}>{c.keywords_max_count}"))
    return ListCheck(tuple(items), tuple(violations))


# --------------------------------------------------------------------------------------------
# Amazon backend terms (byte-capped hidden field)
# --------------------------------------------------------------------------------------------

BACKEND_TERMS_JOINER = " "  # the cap is measured on the terms joined by single spaces


@dataclass(frozen=True, slots=True)
class BackendTermsCheck:
    terms: tuple[str, ...]
    joined: str
    byte_count: int
    violations: tuple[Violation, ...]

    @property
    def valid(self) -> bool:
        return not self.violations


def check_backend_terms(raw: object, c: FormatConstraint, *, allowed_context: str | None = None) -> BackendTermsCheck:
    cap = int(_need(c.backend_terms_max_bytes, "backend_terms_max_bytes"))
    items, violations = _check_lines(raw, field="backend_terms", max_chars=None, allowed_context=allowed_context, rule=None)
    if isinstance(raw, (list, tuple)) and not items:
        violations.append(Violation(ViolationCode.EMPTY, "backend_terms"))
    joined = BACKEND_TERMS_JOINER.join(t for t in items if t)
    size = utf8_bytes(joined)
    if size > cap:
        violations.append(Violation(ViolationCode.BYTES_EXCEEDED, "backend_terms", f"{size}>{cap}"))
    return BackendTermsCheck(tuple(items), joined, size, tuple(violations))


# --------------------------------------------------------------------------------------------
# hashtags (separate marketing artefact; never a listing field unless verified, AC13)
# --------------------------------------------------------------------------------------------

def _is_hashtag(tag: str) -> bool:
    """'#' then a letter/digit, then letters, digits, underscores and COMBINING MARKS. Marks
    matter: Indic vowel signs (matras) are Unicode category Mc/Mn, which the regex word class
    does not match, so a regex would wrongly reject a Hindi hashtag."""
    if len(tag) < 2 or tag[0] != "#" or not tag[1].isalnum():
        return False
    return all(ch.isalnum() or ch == "_" or unicodedata.category(ch)[0] == "M" for ch in tag[2:])


def check_hashtags(raw: object, *, allowed_context: str | None = None) -> ListCheck:
    if not isinstance(raw, (list, tuple)):
        return ListCheck((), (Violation(ViolationCode.WRONG_TYPE, "hashtags", "expected a list"),))
    items: list[str] = []
    violations: list[Violation] = []
    seen: dict[str, int] = {}
    for i, item in enumerate(raw):
        name = f"hashtags[{i}]"
        if not isinstance(item, str):
            violations.append(Violation(ViolationCode.WRONG_TYPE, name, type(item).__name__))
            items.append("")
            continue
        tag = clean_generated_text(item)
        items.append(tag)
        if not _is_hashtag(tag):
            violations.append(Violation(ViolationCode.INVALID_HASHTAG, name, "a hashtag is '#' + letters/digits/underscore, no spaces"))
            continue
        violations += _forbidden(tag.lstrip("#"), name, allowed_context)
        key = dedupe_key(tag)
        if key in seen:
            violations.append(Violation(ViolationCode.DUPLICATE, name, f"same as hashtags[{seen[key]}]"))
        else:
            seen[key] = i
    if not items:
        violations.append(Violation(ViolationCode.EMPTY, "hashtags"))
    return ListCheck(tuple(items), tuple(violations))


# --------------------------------------------------------------------------------------------
# the listing copy pack: atomic (AC25)
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ListingCopyCheck:
    description: str
    bullets: tuple[str, ...]
    keywords: tuple[str, ...]
    violations: tuple[Violation, ...]

    @property
    def valid(self) -> bool:
        """COMPLETE only if description, bullets AND keywords all pass (spec §6.4 rule 4, AC25).
        There is no partial pass: a half-valid pack is FAILED, never billed, never shown."""
        return not self.violations

    def structured(self) -> dict[str, Any]:
        """The value persisted in `cmo_generation.output_structured` for a valid pack."""
        if not self.valid:
            raise ValueError("only a valid listing copy pack may be persisted as a deliverable")
        return {"description": self.description, "bullets": list(self.bullets), "keywords": list(self.keywords)}


def check_listing_copy(
    description: object,
    bullets: object,
    keywords: object,
    c: FormatConstraint,
    *,
    allowed_context: str | None = None,
) -> ListingCopyCheck:
    d = check_description(description, c, allowed_context=allowed_context)
    b = check_bullets(bullets, c, allowed_context=allowed_context)
    k = check_keywords(keywords, c, allowed_context=allowed_context)
    return ListingCopyCheck(d.text, b.items, k.items, d.violations + b.violations + k.violations)
