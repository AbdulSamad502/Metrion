"""Strict parsing of a vision reply (spec §6.2, P6 decisions 7, 9, 12). The reply is UNTRUSTED text.

Output: ALWAYS one entry per schema field - an observed value, or an explicit UNKNOWN - so the stored analysis
states what could not be determined instead of omitting it.

Outcome (decision 9):
* FAILED   - not text / not a single JSON object / over the size ceiling / none of the schema fields present /
             no field is even well-formed. Nothing from such a reply is used.
* DEGRADED - partially usable but materially incomplete or malformed: some schema fields are missing, or are the
             wrong JSON type, while at least one field is well-formed.
* COMPLETE - every schema field is present and well-formed (a string or null).

POLICY FILTERING IS NOT DEGRADATION: a well-formed value that the policy refuses (any digit; a price, tax,
contact or certification wording; over-long; an "unknown" sentinel) is simply discarded to UNKNOWN. Fields
outside the closed schema (weight, dimensions, price, notable features, ...) are ignored.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any

from slim_cmo.forbidden import scan_forbidden
from slim_cmo.textnorm import clean_generated_text, collapse_whitespace
from slim_cmo.vision.schema import ATTRIBUTE_NAMES, MAX_RESPONSE_CHARS, MAX_VALUE_CHARS, SUPPORTED_SCHEMA_VERSIONS, UNKNOWN_SENTINELS

_FENCE = re.compile(r"^```[A-Za-z0-9_-]*[ \t]*\n(.*?)\n?[ \t]*```$", re.DOTALL)


class AnalysisOutcome(str, Enum):
    COMPLETE = "COMPLETE"
    DEGRADED = "DEGRADED"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class ObservedAttribute:
    name: str
    value: str | None  # None = UNKNOWN


@dataclass(frozen=True, slots=True)
class ParsedAnalysis:
    outcome: AnalysisOutcome
    reason: str | None  # required (non-blank) unless COMPLETE - matches the database CHECK
    attributes: tuple[ObservedAttribute, ...]
    policy_discards: int = 0   # well-formed values the policy refused (informational; never a degradation)
    digit_discards: int = 0    # of those, how many carried a digit (a numeral-reliance signal for evaluation)
    malformed: int = 0
    missing: int = 0

    @property
    def observed(self) -> tuple[ObservedAttribute, ...]:
        return tuple(a for a in self.attributes if a.value is not None)


def _failed(reason: str) -> ParsedAnalysis:
    return ParsedAnalysis(AnalysisOutcome.FAILED, reason, tuple(ObservedAttribute(n, None) for n in ATTRIBUTE_NAMES))


def _load(raw: object) -> dict[str, Any] | str:
    if not isinstance(raw, str):
        return "reply was not text"
    if len(raw) > MAX_RESPONSE_CHARS:
        return "reply exceeded the size ceiling"
    text = raw.strip().lstrip("﻿").strip()
    fenced = _FENCE.match(text)
    if fenced:
        text = fenced.group(1).strip()

    def reject(name: str) -> Any:
        raise ValueError(name)

    try:
        value = json.loads(text, parse_constant=reject)
    except (ValueError, RecursionError):
        return "reply was not a single valid JSON object"
    if not isinstance(value, dict):
        return "reply JSON was not an object"
    return value


def _has_digit(text: str) -> bool:
    return any(ch.isdigit() for ch in text)


def parse_analysis(raw: object, schema_version: str) -> ParsedAnalysis:
    if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        raise ValueError(f"unsupported vision schema version {schema_version!r}")
    obj = _load(raw)
    if isinstance(obj, str):
        return _failed(obj)
    if not any(n in obj for n in ATTRIBUTE_NAMES):
        return _failed("none of the schema fields were present")

    attributes: list[ObservedAttribute] = []
    policy = digits = malformed = missing = well_formed = 0
    for name in ATTRIBUTE_NAMES:
        if name not in obj:
            missing += 1
            attributes.append(ObservedAttribute(name, None))
            continue
        value = obj[name]
        if value is None:
            well_formed += 1
            attributes.append(ObservedAttribute(name, None))
            continue
        if not isinstance(value, str):
            malformed += 1  # numbers, booleans, lists and objects are the wrong shape for a field
            attributes.append(ObservedAttribute(name, None))
            continue
        well_formed += 1
        cleaned = collapse_whitespace(clean_generated_text(value))
        if not cleaned or cleaned.casefold() in UNKNOWN_SENTINELS:
            attributes.append(ObservedAttribute(name, None))
            continue
        if _has_digit(cleaned):
            policy += 1
            digits += 1
            attributes.append(ObservedAttribute(name, None))
            continue
        if len(cleaned) > MAX_VALUE_CHARS or scan_forbidden(cleaned):
            policy += 1
            attributes.append(ObservedAttribute(name, None))
            continue
        attributes.append(ObservedAttribute(name, cleaned))

    if well_formed == 0:
        return _failed("no schema field was well-formed")
    outcome = AnalysisOutcome.COMPLETE
    reason: str | None = None
    if malformed or missing:
        outcome = AnalysisOutcome.DEGRADED
        reason = f"the reply was incomplete: {missing} field(s) missing, {malformed} malformed"
    return ParsedAnalysis(outcome, reason, tuple(attributes), policy, digits, malformed, missing)
