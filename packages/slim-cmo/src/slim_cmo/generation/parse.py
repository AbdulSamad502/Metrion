"""Strict parsing of a provider reply. Provider output is UNTRUSTED.

A reply must be ONE JSON object (optionally wrapped in a Markdown code fence - the only tolerance
granted). Anything else is a parse failure: an attempt is spent, nothing is "repaired", and no
text is salvaged from prose. Unknown extra keys are ignored (never used). The technical
parse-safety ceilings (`safety_limits`) are applied here; a reply beyond them is unusable, not
truncated.

`needs_facts`: a model may answer `{"needs_facts": ["material", ...]}` instead of content. The
names are returned RAW here and screened by `safety.screen_fact_names` before anyone sees them.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from slim_cmo.generation.safety_limits import (
    MAX_DECLARED_MISSING_FACTS,
    PARSE_SAFETY_MAX_DESCRIPTION_CHARS,
    PARSE_SAFETY_MAX_ITEM_CHARS,
    PARSE_SAFETY_MAX_LIST_ITEMS,
    PARSE_SAFETY_MAX_RESPONSE_CHARS,
)

_FENCE = re.compile(r"^```[A-Za-z0-9_-]*[ \t]*\n(.*?)\n?[ \t]*```$", re.DOTALL)


@dataclass(frozen=True, slots=True)
class Parsed:
    payload: dict[str, Any] | None  # None only when the model declared needs_facts instead of content
    needs_facts: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ParseFailure:
    reason: str
    too_large: bool = False


def _reject_constant(name: str) -> Any:
    raise ValueError(f"non-finite JSON constant {name}")


def _load_object(raw: object) -> dict[str, Any] | ParseFailure:
    if not isinstance(raw, str):
        return ParseFailure("reply was not text")
    if len(raw) > PARSE_SAFETY_MAX_RESPONSE_CHARS:
        return ParseFailure("reply exceeds the technical parse-safety ceiling", too_large=True)
    text = raw.strip().lstrip("﻿").strip()
    fenced = _FENCE.match(text)
    if fenced:
        text = fenced.group(1).strip()
    try:
        value = json.loads(text, parse_constant=_reject_constant)
    except (ValueError, RecursionError):
        return ParseFailure("reply was not a single valid JSON object")
    if not isinstance(value, dict):
        return ParseFailure("reply JSON was not an object")
    return value


def _ceiling_problem(key: str, value: Any) -> str | None:
    if isinstance(value, str):
        limit = PARSE_SAFETY_MAX_DESCRIPTION_CHARS if key == "description" else PARSE_SAFETY_MAX_ITEM_CHARS
        return f"{key} exceeds the technical parse-safety ceiling" if len(value) > limit else None
    if isinstance(value, list):
        if len(value) > PARSE_SAFETY_MAX_LIST_ITEMS:
            return f"{key} has more entries than the technical parse-safety ceiling"
        for item in value:
            if isinstance(item, str) and len(item) > PARSE_SAFETY_MAX_ITEM_CHARS:
                return f"an entry of {key} exceeds the technical parse-safety ceiling"
    return None


def _declared_missing(obj: Mapping[str, Any]) -> tuple[str, ...]:
    raw = obj.get("needs_facts")
    if not isinstance(raw, list):
        return ()
    names = [x for x in raw if isinstance(x, str)]
    return tuple(names[:MAX_DECLARED_MISSING_FACTS])


def parse_reply(raw: object, content_types: Mapping[str, type]) -> Parsed | ParseFailure:
    """`content_types` maps each required content key to its required JSON type (`str` or `list`).
    Item-level types and values are judged later by the deterministic validators."""
    obj = _load_object(raw)
    if isinstance(obj, ParseFailure):
        return obj
    declared = _declared_missing(obj)
    missing = [k for k in content_types if k not in obj]
    if missing:
        if declared:
            return Parsed(None, declared)
        return ParseFailure(f"reply is missing: {', '.join(missing)}")
    payload: dict[str, Any] = {}
    for key, expected in content_types.items():
        value = obj[key]
        if not isinstance(value, expected) or isinstance(value, bool):
            return ParseFailure(f"{key} has the wrong JSON type")
        problem = _ceiling_problem(key, value)
        if problem is not None:
            return ParseFailure(problem, too_large=True)
        payload[key] = value
    return Parsed(payload, declared)
