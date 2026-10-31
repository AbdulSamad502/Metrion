"""Search-result preview simulation (CMO 3.0 M4; docs/specs/slim-cmo-agent.md section 6.16).

What this module IS: pure, deterministic code that works out, for one title and one screen (mobile or desktop), how much of the title a search-results card would show before cutting it
off, which of the title-worthy keywords and the seller's important confirmed details stay visible, and what to change. Both screens are computed together so the seller can switch between
them instantly with no further request.

What it is NOT: a copy of what any marketplace shows. Real cut-offs depend on the device width, the font, the marketplace layout and the page, and Metrion has no verified source for them.
So every cut-off here is labelled:

* VERIFIED - only when a platform configuration row `title_display_rules` states the visible length for that marketplace and screen WITH an https source page and a check date no older than
  the format-rule staleness window (the same discipline as `format_constraint`);
* ILLUSTRATIVE - otherwise: a fixed demonstration cut-off, said to be exactly that. It is never presented as an official limit.

It calls no model, reads no database, produces no price, rating, review count, sales figure or ranking (a preview card has none of those to show), and shows no product picture it was not
given. Characters are counted as Unicode characters.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any
from urllib.parse import urlparse

METHOD = "listing-preview-v1"
MODES = ("mobile", "desktop")
MARKETPLACES = ("AMAZON", "FLIPKART", "MEESHO")
TITLE_DISPLAY_RULES_KEY = "title_display_rules"
ILLUSTRATIVE_VISIBLE_CHARS = {"mobile": 60, "desktop": 110}  # a demonstration cut-off, not a marketplace fact; the same for every marketplace on purpose (no invented differences)
ILLUSTRATIVE_NOTE = "Illustrative cut-off for demonstration. It is not an official limit; the real display depends on the device, the page and the marketplace."
SIMULATION_NOTICE = ("This is an illustrative simulation of a search result, not the real marketplace page. Price, rating and reviews are not simulated. "
                     "The real display may cut the title at a different point.")
_WORDS = re.compile(r"[^\W_]+", re.UNICODE)
_STOP = frozenset({"a", "an", "the", "for", "of", "and", "with", "in", "to", "by", "on"})
_TRIM = " ,;:-|/–—"
_BACKTRACK = 20  # when the cut falls inside a word, step back to the previous space only if one is this close


@dataclass(frozen=True, slots=True)
class DisplayRule:
    chars: int
    basis: str  # VERIFIED | ILLUSTRATIVE
    note: str
    source_url: str | None = None
    verified_at: str | None = None


def _words(text: str) -> list[str]:
    return [w.casefold() for w in _WORDS.findall(text or "")]


@dataclass(frozen=True, slots=True)
class SourcePolicy:
    """What a display rule's source must satisfy to be called VERIFIED when the caller supplies a policy: the page's host must be an official marketplace host, and the rule must declare it
    applies to ALL_CATEGORIES (a preview has no category, so a rule limited to some categories cannot apply)."""

    official_hosts: frozenset[str]


def display_rules(raw: Any, marketplace: str, *, today: date, max_age_days: int | None, policy: SourcePolicy | None = None) -> dict[str, DisplayRule]:
    """The cut-off for each screen. A configured value is used only when it is complete and fresh; anything else falls back to the labelled illustrative cut-off, with the reason."""
    out: dict[str, DisplayRule] = {}
    entry = raw.get(marketplace) if isinstance(raw, Mapping) else None
    for mode in MODES:
        rule = entry.get(mode) if isinstance(entry, Mapping) else None
        why = "no verified display rule is configured for this marketplace and screen"
        if isinstance(rule, Mapping):
            n, url, stamp = rule.get("visible_chars"), rule.get("source_url"), rule.get("verified_at")
            try:
                checked = date.fromisoformat(str(stamp)[:10])
            except ValueError:
                checked = None
            if type(n) is not int or n < 1:
                why = "the configured display rule has no usable character count"
            elif not (isinstance(url, str) and url.startswith("https://")):
                why = "the configured display rule has no source page"
            elif policy is not None and urlparse(url).hostname not in policy.official_hosts:
                why = "the configured display rule's source page is not on an official marketplace host"
            elif policy is not None and rule.get("scope") != "ALL_CATEGORIES":
                why = "the configured display rule is not stated for all categories"
            elif checked is None or checked > today:
                why = "the configured display rule has no valid check date"
            elif max_age_days is None or (today - checked).days > max_age_days:
                why = "the configured display rule is stale or its staleness window is not configured"
            else:
                out[mode] = DisplayRule(n, "VERIFIED", f"From the display rule checked {checked.isoformat()} ({url}).", url, checked.isoformat())
                continue
        out[mode] = DisplayRule(ILLUSTRATIVE_VISIBLE_CHARS[mode], "ILLUSTRATIVE", ILLUSTRATIVE_NOTE + f" ({why}.)")
    return out


def split_visible(text: str, limit: int) -> tuple[str, str, bool]:
    """(shown, cut off, truncated). The cut falls on a word boundary when one is close; the shown part never ends in a separator."""
    t = " ".join(text.split())
    if len(t) <= limit:
        return t, "", False
    cut = limit
    if t[limit] != " " and t[limit - 1] != " ":
        back = t.rfind(" ", max(0, limit - _BACKTRACK), limit)
        cut = back if back > 0 else limit
    shown = t[:cut].rstrip(_TRIM)
    return shown, t[cut:].strip(), True


def _covered(phrase_words: Sequence[str], haystack: set[str]) -> bool:
    content = [w for w in phrase_words if w not in _STOP]
    return bool(content) and all(w in haystack for w in content)


def keyword_visibility(shown: str, full: str, keywords: Sequence[str]) -> list[dict[str, str]]:
    sw, fw = set(_words(shown)), set(_words(full))
    out = []
    for k in keywords:
        kw = _words(k)
        out.append({"keyword": k, "status": "VISIBLE" if _covered(kw, sw) else "CUT_OFF" if _covered(kw, fw) else "NOT_IN_TITLE"})
    return out


def detail_visibility(shown: str, full: str, details: Mapping[str, str]) -> list[dict[str, str]]:
    sw, fw = set(_words(shown)), set(_words(full))
    out = []
    for label, value in details.items():
        vw = _words(value)
        out.append({"label": label, "value": value, "status": "VISIBLE" if _covered(vw, sw) else "CUT_OFF" if _covered(vw, fw) else "NOT_IN_TITLE"})
    return out


def _suggestions(mode: str, truncated: bool, kws: Sequence[Mapping[str, str]], dets: Sequence[Mapping[str, str]], hard_fail: bool) -> list[str]:
    screen = "mobile" if mode == "mobile" else "desktop"
    out: list[str] = []
    if hard_fail:
        out.append("This option has a hard failure (see its score). Fix that before you use it; the preview shows how it would look, not that it is usable.")
    cut_details = [d["label"].lower() for d in dets if d["status"] == "CUT_OFF"]
    cut_kws = [k["keyword"] for k in kws if k["status"] == "CUT_OFF"]
    if truncated and cut_details:
        out.append(f"Your {', '.join(cut_details)} would be hidden on {screen}. Move it earlier or shorten the title.")
    if truncated and cut_kws:
        out.append(f"The keyword{'s' if len(cut_kws) > 1 else ''} “{'”, “'.join(cut_kws[:3])}” would be hidden on {screen}. Put {'them' if len(cut_kws) > 1 else 'it'} nearer the start.")
    missing = [d["label"].lower() for d in dets if d["status"] == "NOT_IN_TITLE"]
    if missing:
        out.append(f"Your confirmed {', '.join(missing)} {'is' if len(missing) == 1 else 'are'} not in this title. Add {'it' if len(missing) == 1 else 'them'} if buyers search by {'it' if len(missing) == 1 else 'them'}.")
    if truncated and not cut_details and not cut_kws:
        out.append(f"Only the end of the title is cut off on {screen}; your important details and keywords stay visible.")
    if not truncated and not out:
        out.append(f"The whole title fits in this illustrative {screen} view.")
    return out[:4]


def option_preview(text: str, rules: Mapping[str, DisplayRule], keywords: Sequence[str], details: Mapping[str, str], hard_fail: bool) -> dict[str, Any]:
    modes: dict[str, Any] = {}
    for mode in MODES:
        rule = rules[mode]
        shown, hidden, cut = split_visible(text, rule.chars)
        kws, dets = keyword_visibility(shown, text, keywords), detail_visibility(shown, text, details)
        modes[mode] = {"visible": shown, "hidden": hidden, "truncated": cut, "visibleChars": len(shown), "totalChars": len(" ".join(text.split())), "limit": rule.chars,
                       "limitBasis": rule.basis, "limitNote": rule.note, "limitSourceUrl": rule.source_url, "limitVerifiedAt": rule.verified_at,
                       "keywords": kws, "details": dets, "suggestions": _suggestions(mode, cut, kws, dets, hard_fail)}
    return modes


def set_preview(analysis: Mapping[str, Any], keyword_result: Mapping[str, Any] | None, details: Mapping[str, str], rules: Mapping[str, DisplayRule]) -> list[dict[str, Any]]:
    """Every option of one analysed title set, with both screens, its M3 score, its evidence coverage and its marketplace compliance status (all copied from the analysis, never recomputed)."""
    cands = [c["keyword"] for c in (keyword_result or {}).get("candidates", []) if c.get("recommended") and "TITLE" in c.get("placement", [])]
    out = []
    for o in analysis.get("options", []):
        ov = (o.get("scores") or {}).get("overall") or {}
        comp = (o.get("dimensions") or {}).get("marketplaceRules") or {}
        out.append({
            "optionId": o["optionId"], "rank": o["rank"], "text": o["text"], "strategy": o.get("strategy"), "hardFailures": list(o.get("hardFailures") or []),
            "score": {"status": ov.get("status"), "score": ov.get("score"), "band": ov.get("band"), "assessablePoints": ov.get("assessablePoints"), "note": ov.get("note"),
                      "criteria": {k: {"status": c.get("status"), "earned": c.get("earned"), "max": c.get("max")} for k, c in ((o.get("scores") or {}).get("criteria") or {}).items()}},
            "compliance": {"status": comp.get("status", "NOT_ASSESSED"), "detail": comp.get("detail"), "length": comp.get("length"), "limit": comp.get("limit"), "ruleKind": comp.get("ruleKind")},
            "modes": option_preview(o["text"], rules, cands, details, bool(o.get("hardFailures"))),
        })
    return out
