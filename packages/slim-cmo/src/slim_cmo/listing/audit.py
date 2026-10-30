"""The post-generation listing audit (docs/specs/slim-cmo-agent.md section 6.18.5). Pure, deterministic, free: no model, no network, no database.

It checks the SAVED text (generated, seller-typed or revised) and reuses, never re-scores, what exists: the M3 hard-failure result for the title, the claim / forbidden / number gates, the M2
candidates and the M5 question states. There is NO numeric score. Check statuses: PASS, FAIL, NOT_ASSESSED (the evidence or a VERIFIED marketplace rule was unavailable - never a pass) and
NOT_APPLICABLE (the check does not exist for this marketplace). Finding severities: BLOCKER, WARNING, NOTE. Verdict: BLOCKED / NEEDS_ATTENTION / CHECKED_NOT_VERIFIED. There is no READY or
"compliant" verdict: style and grammar are never assessed (A15), so the best verdict is CHECKED_NOT_VERIFIED.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from slim_cmo.ci_inputs import CiInputs, check_output
from slim_cmo.claims import Attribute, allowed_context_text, assess, find_ineligible_values_in_text, find_unsupported_numbers
from slim_cmo.constraints import FormatConstraint
from slim_cmo.forbidden import scan_forbidden
from slim_cmo.keywords.intelligence import CLAIM_TERMS
from slim_cmo.listing import keyword_map, limits
from slim_cmo.listing.text import all_texts, count_phrases, norm, sentences, words
from slim_cmo.textnorm import count_by_rule, utf8_bytes

PASS, FAIL, NOT_ASSESSED, NOT_APPLICABLE = "PASS", "FAIL", "NOT_ASSESSED", "NOT_APPLICABLE"
BLOCKER, WARNING, NOTE = "BLOCKER", "WARNING", "NOTE"
BLOCKED, NEEDS_ATTENTION, CHECKED_NOT_VERIFIED = "BLOCKED", "NEEDS_ATTENTION", "CHECKED_NOT_VERIFIED"
UNVERIFIED = "UNVERIFIED"
STYLE_NOT_ASSESSED = "Spelling, grammar and writing style are not checked by Metrion."
NO_MARKETPLACE_CHECK = "Not checked against marketplace rules: no verified rule is available."
CHECK_NAMES = {
    "A01": "Title is the approved title", "A02": "Title hard checks", "A03": "Sections present and shaped", "A04": "Unsupported claims", "A05": "Numbers and units",
    "A06": "Contradictions", "A07": "Keyword traceability", "A08": "Repetition and stuffing", "A09": "Cross-section consistency", "A10": "Buyer-question coverage",
    "A11": "Competitor differentiation", "A12": "Amazon backend terms", "A13": "Marketplace rules", "A14": "Missing information", "A15": "Style and grammar",
}
_MATERIALS = frozenset({"steel", "aluminium", "aluminum", "copper", "plastic", "glass", "silicone", "tritan", "ceramic", "wood", "bamboo", "titanium", "brass", "iron"})
_COLOURS = frozenset({"silver", "black", "blue", "red", "green", "white", "grey", "gray", "pink", "yellow", "orange", "purple", "brown", "gold", "violet", "maroon", "teal"})
_CAPACITY = re.compile(r"(\d+(?:\.\d+)?)\s*(ml|millilit(?:re|er)s?|l|lit(?:re|er)s?)\b", re.IGNORECASE)
_SIZE_ATTRS = frozenset({"size", "capacity", "volume"})


@dataclass(frozen=True, slots=True)
class AuditInputs:
    marketplace: str  # AMAZON | FLIPKART | MEESHO
    rules_basis: str  # VERIFIED | UNVERIFIED
    constraint: FormatConstraint | None  # the VERIFIED row when rules_basis is VERIFIED
    approved_title: str
    title: str
    bullets: Sequence[str]
    description: str
    keywords: Sequence[str]
    backend_terms: Sequence[str] | None  # None = no backend-terms step (every marketplace but Amazon)
    attributes: Sequence[Attribute]
    candidates: Sequence[Mapping[str, Any]]  # M2 candidates
    excluded: Sequence[Mapping[str, Any]] = ()  # M2 exclusions
    questions: Mapping[str, Any] | None = None  # M5 buyer-question analysis
    ci_rows: Sequence[Mapping[str, Any]] = ()  # claim-gated competitor evidence rows
    ci: CiInputs | None = None  # the inputs used (for the originality check); None = no competitor themes used
    title_hard_failures: Sequence[str] = ()  # the M3 hard-failure result for this title
    gaps: Sequence[str] = field(default_factory=tuple)  # confirmed facts the seller has not given (for A14)


class _Collector:
    def __init__(self) -> None:
        self.findings: list[dict[str, Any]] = []
        self.status: dict[str, str] = {}
        self.detail: dict[str, str] = {}

    def add(self, check: str, severity: str, section: str, code: str, explanation: str, correction: str | None = None) -> None:
        self.findings.append({"check": check, "severity": severity, "section": section, "code": code, "explanation": explanation, "correction": correction})

    def finish(self, check: str, *, assessed: bool = True, applicable: bool = True, detail: str = "") -> None:
        if not applicable:
            self.status[check] = NOT_APPLICABLE
        elif not assessed:
            self.status[check] = NOT_ASSESSED
        else:
            bad = any(f["check"] == check and f["severity"] in (BLOCKER, WARNING) for f in self.findings)
            self.status[check] = FAIL if bad else PASS
        if detail:
            self.detail[check] = detail


def _capacities_ml(text: str) -> set[Decimal]:
    out: set[Decimal] = set()
    for m in _CAPACITY.finditer(text or ""):
        val = Decimal(m.group(1))
        out.add((val * 1000 if m.group(2).lower().startswith("l") and not m.group(2).lower().startswith("ml") else val).normalize())
    return out


def _eligible(attrs: Sequence[Attribute]) -> list[Attribute]:
    return [a for a in attrs if a.value and assess(a).eligible]


def _ineligible(attrs: Sequence[Attribute]) -> list[Attribute]:
    return [a for a in attrs if a.value and not assess(a).eligible]


def _measure(text: str, rule: str) -> int:
    return count_by_rule(text, rule)


def run(inp: AuditInputs) -> dict[str, Any]:
    c = _Collector()
    elig = _eligible(inp.attributes)
    ctx = allowed_context_text(elig, inp.approved_title)
    texts = all_texts(inp.title, inp.bullets, inp.description, inp.keywords, inp.backend_terms)
    verified = inp.rules_basis != UNVERIFIED and inp.constraint is not None
    row = inp.constraint if verified else None
    rule = row.count_rule.value if row is not None and row.count_rule is not None else "CODE_POINTS"

    # A01 title is the approved title
    if norm(inp.title) != norm(inp.approved_title):
        c.add("A01", BLOCKER, "TITLE", "TITLE_CHANGED", "The title in this listing is not the title you approved.", "Use the approved title word for word, or approve a different title first.")
    c.finish("A01")

    # A02 title hard checks (the M3 result for this title; not re-scored)
    for f in inp.title_hard_failures:
        c.add("A02", BLOCKER, "TITLE", "TITLE_HARD_FAILURE", f"The title fails a hard check: {f}", "Approve a title that passes the hard checks.")
    c.finish("A02")

    # A03 sections present and shaped
    if not inp.description.strip():
        c.add("A03", BLOCKER, "DESCRIPTION", "SECTION_MISSING", "There is no description.")
    if not [b for b in inp.bullets if b.strip()]:
        c.add("A03", BLOCKER, "BULLETS", "SECTION_MISSING", "There are no bullet points.")
    if not [k for k in inp.keywords if k.strip()]:
        c.add("A03", BLOCKER, "KEYWORDS", "SECTION_MISSING", "There are no keywords.")
    limits_checked = False
    if row is not None:
        stated = [v for v in (row.bullet_count, row.bullet_max_chars, row.description_max_chars, row.keywords_max_count, row.keywords_max_chars) if v is not None]
        limits_checked = bool(stated)
        if row.bullet_count is not None and len(inp.bullets) != row.bullet_count:
            c.add("A03", BLOCKER, "BULLETS", "BULLET_COUNT", f"This marketplace's verified rule asks for {row.bullet_count} bullets; there are {len(inp.bullets)}.")
        if row.bullet_max_chars is not None:
            for i, b in enumerate(inp.bullets):
                if _measure(b, rule) > row.bullet_max_chars:
                    c.add("A03", BLOCKER, f"BULLET {i + 1}", "BULLET_TOO_LONG", f"Longer than the verified limit of {row.bullet_max_chars} characters.")
        if row.description_max_chars is not None and _measure(inp.description, rule) > row.description_max_chars:
            c.add("A03", BLOCKER, "DESCRIPTION", "DESCRIPTION_TOO_LONG", f"Longer than the verified limit of {row.description_max_chars} characters.")
        if row.keywords_max_count is not None and len(inp.keywords) > row.keywords_max_count:
            c.add("A03", BLOCKER, "KEYWORDS", "TOO_MANY_KEYWORDS", f"More than the verified limit of {row.keywords_max_count} keywords.")
        if row.keywords_max_chars is not None:
            for k in inp.keywords:
                if _measure(k, rule) > row.keywords_max_chars:
                    c.add("A03", BLOCKER, "KEYWORDS", "KEYWORD_TOO_LONG", f"“{k}” is longer than the verified limit of {row.keywords_max_chars} characters.")
    any_fail = any(f["check"] == "A03" and f["severity"] == BLOCKER for f in c.findings)
    c.finish("A03", assessed=any_fail or limits_checked, detail="" if (limits_checked or any_fail) else NO_MARKETPLACE_CHECK)

    # A04 unsupported claims (claim list, forbidden content, ineligible values, unconfirmed buyer-question topics)
    elig_words = set()
    for a in elig:
        elig_words.update(words(f"{a.name} {a.value}"))
    elig_words.update(words(inp.approved_title))
    unconfirmed_topics: list[tuple[str, frozenset[str]]] = []
    if inp.questions:
        from slim_cmo.buyer.questions import topic_for_label  # noqa: PLC0415

        for q in inp.questions.get("questions") or []:
            t = topic_for_label(str(q.get("topic", "")))
            if t is not None and t.claim and q.get("status") != "CONFIRMED":
                unconfirmed_topics.append((t.label, frozenset(t.stems | {w for w in words(t.label)})))
    inel = _ineligible(inp.attributes)
    seen: set[tuple[str, str]] = set()
    for section, text in texts:
        toks = set(words(text))
        for claim, stems in CLAIM_TERMS.items():
            if set(stems) & toks and not (set(stems) & elig_words):
                if (section, claim) not in seen:
                    seen.add((section, claim))
                    c.add("A04", BLOCKER, section, "UNSUPPORTED_CLAIM", f"It says or implies “{claim}”, which you have not confirmed for this product.", f"Remove it, or confirm “{claim}” for this product first.")
        for label, stems in unconfirmed_topics:
            if stems & toks and (section, label) not in seen and not (stems & elig_words):
                seen.add((section, label))
                c.add("A04", BLOCKER, section, "UNCONFIRMED_TOPIC", f"It touches “{label}”, which is not confirmed for this product.", f"Remove it, or tell me about its {label.lower()} first.")
        for finding in scan_forbidden(text, allowed_context=ctx):
            c.add("A04", BLOCKER, section, "FORBIDDEN_CONTENT", f"Contains wording that is not allowed in a listing ({finding.category.value.lower().replace('_', ' ')}).", "Remove or reword it.")
        for name in find_ineligible_values_in_text(text, inel, allowed_context=ctx):
            c.add("A04", BLOCKER, section, "UNCONFIRMED_VALUE", f"States a value for “{name}” that you have not confirmed.", "Remove it or confirm the detail.")
    c.finish("A04")

    # A05 numbers and units
    for section, text in texts:
        bad = find_unsupported_numbers(text, [ctx])
        if bad:
            c.add("A05", BLOCKER, section, "UNSUPPORTED_NUMBER", f"Contains number(s) {', '.join(bad)} that none of your confirmed facts support.", "Remove them or confirm the detail they describe.")
    c.finish("A05")

    # A06 contradictions (capacity, material, colour)
    confirmed_cap: set[Decimal] = set()
    for a in elig:
        if a.name.casefold() in _SIZE_ATTRS:
            confirmed_cap |= _capacities_ml(str(a.value))
    mentions: dict[Decimal, list[str]] = {}
    for section, text in texts:
        for ml in _capacities_ml(text):
            mentions.setdefault(ml, []).append(section)
    for ml, sections in mentions.items():
        if confirmed_cap and ml not in confirmed_cap:
            c.add("A06", BLOCKER, sections[0], "CAPACITY_CONTRADICTION", f"States a capacity of {ml} ml, but your confirmed capacity is {', '.join(str(v) for v in sorted(confirmed_cap))} ml.", "Correct the capacity or the confirmed fact.")
    if not confirmed_cap and len(mentions) > 1:
        c.add("A06", BLOCKER, "WHOLE_LISTING", "CAPACITY_DISAGREES", "Different sections state different capacities.", "Use one capacity everywhere.")
    for label, universe, attr_names in (("material", _MATERIALS, {"material"}), ("colour", _COLOURS, {"color", "colour"})):
        confirmed = set()
        for a in elig:
            if a.name.casefold() in attr_names:
                confirmed.update(words(str(a.value)))
        if not confirmed:
            continue
        for section, text in texts:
            other = (set(words(text)) & universe) - confirmed - elig_words
            if other:
                c.add("A06", BLOCKER, section, f"{label.upper()}_CONTRADICTION", f"Mentions {', '.join(sorted(other))}, but your confirmed {label} is {' / '.join(sorted(confirmed))}.", f"Use only your confirmed {label}.")
    c.finish("A06")

    # A07 keyword traceability
    use = keyword_map.placeable(inp.candidates)
    use_keys = {norm(str(x["keyword"])) for x in use}
    excl_keys = {norm(str(e.get("keyword", ""))) for e in inp.excluded}
    for section, terms in (("KEYWORDS", inp.keywords), ("BACKEND_TERMS", inp.backend_terms or [])):
        for t in terms:
            k = norm(t)
            if k in excl_keys:
                c.add("A07", BLOCKER, section, "KEYWORD_EXCLUDED", f"“{t}” was excluded because it needs a claim you have not confirmed.", "Remove it.")
            elif k not in use_keys:
                c.add("A07", BLOCKER, section, "KEYWORD_NOT_TRACEABLE", f"“{t}” is not one of the keywords researched from your confirmed facts.", "Use a researched keyword, or run keyword research again after confirming more details.")
    c.finish("A07")

    # A08 repetition and stuffing (readability warnings W1-W7; not marketplace or ranking rules)
    phrases = [str(x["keyword"]) for x in use]
    note = "This is a readability check, not a marketplace or ranking rule."
    bullet_counts = [count_phrases(b, phrases) for b in inp.bullets]
    for i, bc in enumerate(bullet_counts):
        for p, n in bc.items():
            if n >= limits.W1_SAME_CANDIDATE_IN_ONE_BULLET:
                c.add("A08", WARNING, f"BULLET {i + 1}", "W1_REPEATED_IN_BULLET", f"“{p}” appears {n} times in one bullet. {note}", "Say it once.")
    for p in phrases:
        in_bullets = sum(1 for bc in bullet_counts if bc.get(p))
        if in_bullets >= limits.W2_SAME_CANDIDATE_IN_BULLETS:
            c.add("A08", WARNING, "BULLETS", "W2_REPEATED_ACROSS_BULLETS", f"“{p}” is in {in_bullets} different bullets. {note}", "Keep it to the bullets where it matters.")
    desc_counts = count_phrases(inp.description, phrases)
    title_counts = count_phrases(inp.title, phrases)
    for p, n in desc_counts.items():
        if n >= limits.W3_SAME_CANDIDATE_IN_DESCRIPTION:
            c.add("A08", WARNING, "DESCRIPTION", "W3_REPEATED_IN_DESCRIPTION", f"“{p}” appears {n} times in the description. {note}", "Vary or trim the wording.")
        total = title_counts.get(p, 0) + sum(bc.get(p, 0) for bc in bullet_counts) + n
        if total >= limits.W4_SAME_CANDIDATE_IN_LISTING:
            c.add("A08", WARNING, "WHOLE_LISTING", "W4_REPEATED_IN_LISTING", f"“{p}” appears {total} times across the title, bullets and description. {note}", "Reduce the repetition.")
    seen_b: dict[str, int] = {}
    for i, b in enumerate(inp.bullets):
        k = norm(b)
        if k and k in seen_b:
            c.add("A08", WARNING, f"BULLET {i + 1}", "W5_DUPLICATE_BULLET", f"Identical to bullet {seen_b[k] + 1}. {note}", "Write something different.")
        else:
            seen_b[k] = i
    desc_sentences = {norm(s) for s in sentences(inp.description)}
    for i, b in enumerate(inp.bullets):
        if norm(b) and norm(b) in desc_sentences:
            c.add("A08", WARNING, f"BULLET {i + 1}", "W5_BULLET_IN_DESCRIPTION", f"The bullet is identical to a sentence in the description. {note}", "Say it differently in one of them.")
    use_set = {norm(p) for p in phrases}
    for section, text in [(f"BULLET {i + 1}", b) for i, b in enumerate(inp.bullets)] + [("DESCRIPTION", inp.description)]:
        for s in sentences(text):
            items = [x.strip() for x in re.split(r"[,|]", s.rstrip(".!?")) if x.strip()]
            if len(items) >= limits.W6_BARE_KEYWORD_LIST_ITEMS and all(norm(x) in use_set for x in items):
                c.add("A08", WARNING, section, "W6_BARE_KEYWORD_LIST", f"A sentence that is only a list of {len(items)} keywords. {note}", "Write it as a normal sentence.")
    be_seen: set[str] = set()
    for t in inp.backend_terms or []:
        k = norm(t)
        if k in be_seen:
            c.add("A08", WARNING, "BACKEND_TERMS", "W7_DUPLICATE_TERM", f"“{t}” appears twice. {note}", "Remove the duplicate.")
        be_seen.add(k)
    c.finish("A08")

    # A09 cross-section consistency (title facts missing from bullets and description: a note, not a failure)
    body = set(words(" ".join([*inp.bullets, inp.description])))
    tw = set(words(inp.title))
    for a in elig:
        if a.name.casefold() in ({"brand", "material", "color", "colour"} | _SIZE_ATTRS):
            vw = set(words(str(a.value)))
            if vw and vw <= tw and not (vw & body):
                c.add("A09", NOTE, "WHOLE_LISTING", "TITLE_FACT_NOT_REPEATED", f"The title states {a.name.lower()} “{a.value}”, but the bullets and description never mention it.", "Mention it once in the body if it matters to a buyer.")
    c.finish("A09")

    # A10 buyer-question coverage (M5)
    unanswered: list[str] = []
    if inp.questions:
        for q in inp.questions.get("questions") or []:
            if q.get("status") == "CONFIRMED" and q.get("importance") == "ESSENTIAL" and q.get("answer"):
                aw = {w for w in words(str(q["answer"])) if len(w) > 2}
                if aw and not (aw & body):
                    c.add("A10", NOTE, "WHOLE_LISTING", "ANSWER_NOT_SHOWN", f"You confirmed “{q.get('topic')}: {q['answer']}”, but the bullets and description do not show it.", "Add it if it matters to a buyer.")
            elif q.get("status") != "CONFIRMED":
                unanswered.append(str(q.get("topic")))
    c.finish("A10", assessed=inp.questions is not None, detail=("Not yet answered: " + ", ".join(unanswered)) if unanswered else "")

    # A11 competitor differentiation
    if not inp.ci_rows and inp.ci is None:
        c.finish("A11", detail="No competitor themes were used.")
    else:
        body_words = set(words(" ".join(t for _, t in texts)))
        for r in inp.ci_rows:
            if r.get("support") != "SUPPORTED" and str(r.get("theme")) in body_words and str(r.get("theme")) not in elig_words:
                c.add("A11", BLOCKER, "WHOLE_LISTING", "CI_UNSUPPORTED_THEME_USED", f"Uses the competitor theme “{r['theme']}”, which your confirmed facts do not support.", "Remove it, or confirm it for your product first.")
        if inp.ci is not None:
            for problem in check_output([t for _, t in texts], inp.ci):
                c.add("A11", BLOCKER, "WHOLE_LISTING", "CI_ORIGINALITY", f"Failed the competitor originality check ({problem}).", "Write it from your own product facts.")
        c.finish("A11")

    # A12 Amazon backend terms
    if inp.backend_terms is None:
        c.finish("A12", applicable=False, detail="Backend search terms exist only for Amazon.")
    else:
        blocked = {t.casefold() for t in (inp.ci.exclude_terms if inp.ci else ())}
        for t in inp.backend_terms:
            if blocked & set(words(t)):
                c.add("A12", BLOCKER, "BACKEND_TERMS", "COMPETITOR_BRAND_TERM", f"“{t}” contains a competitor brand word.", "Remove it.")
        cap = row.backend_terms_max_bytes if row is not None else None
        size = utf8_bytes(" ".join(inp.backend_terms))
        if cap is not None and size > cap:
            c.add("A12", BLOCKER, "BACKEND_TERMS", "BACKEND_TERMS_TOO_LONG", f"{size} bytes, over the verified cap of {cap} bytes.")
        c.finish("A12", assessed=cap is not None or any(f["check"] == "A12" for f in c.findings), detail=f"{size} bytes measured. " + ("" if cap is not None else NO_MARKETPLACE_CHECK))

    # A13 marketplace rules (the title and the rest of the verified row)
    if row is not None and row.title_max_chars is not None:
        if _measure(inp.title, rule) > row.title_max_chars:
            c.add("A13", BLOCKER, "TITLE", "TITLE_TOO_LONG", f"Longer than the verified limit of {row.title_max_chars} characters.")
        c.finish("A13")
    else:
        c.finish("A13", assessed=False, detail=NO_MARKETPLACE_CHECK)

    # A14 missing information
    for g in inp.gaps:
        c.add("A14", NOTE, "WHOLE_LISTING", "FACT_NOT_GIVEN", f"{g} has not been confirmed, so the listing does not state it.", f"Tell me the {g.lower()} if you want it in the listing.")
    c.finish("A14")

    # A15 style and grammar: never assessed
    c.finish("A15", assessed=False, detail=STYLE_NOT_ASSESSED)

    blockers = sum(1 for f in c.findings if f["severity"] == BLOCKER)
    warnings = sum(1 for f in c.findings if f["severity"] == WARNING)
    verdict = BLOCKED if blockers else NEEDS_ATTENTION if warnings else CHECKED_NOT_VERIFIED
    measured = {
        "title": {"codePoints": count_by_rule(inp.title, "CODE_POINTS"), "utf16": count_by_rule(inp.title, "UTF16_CODE_UNITS")},
        "bullets": [{"codePoints": count_by_rule(b, "CODE_POINTS"), "utf16": count_by_rule(b, "UTF16_CODE_UNITS")} for b in inp.bullets],
        "description": {"codePoints": count_by_rule(inp.description, "CODE_POINTS"), "utf16": count_by_rule(inp.description, "UTF16_CODE_UNITS")},
        "backendTermsBytes": utf8_bytes(" ".join(inp.backend_terms)) if inp.backend_terms is not None else None,
        "note": "Measured, not checked against any marketplace rule" if not verified else "Measured with the verified counting rule",
    }
    order = {BLOCKER: 0, WARNING: 1, NOTE: 2}
    return {
        "method": limits.METHOD_VERSION, "marketplace": inp.marketplace, "rulesBasis": inp.rules_basis, "verdict": verdict,
        "counts": {"blockers": blockers, "warnings": warnings, "notes": sum(1 for f in c.findings if f["severity"] == NOTE)},
        "checks": [{"id": k, "name": CHECK_NAMES[k], "status": c.status.get(k, NOT_ASSESSED), "detail": c.detail.get(k, "")} for k in CHECK_NAMES],
        "findings": sorted(c.findings, key=lambda f: (order[f["severity"]], f["check"], f["section"])),
        "measured": measured,
        "limits": "A readability and evidence check on your own text. It is not a marketplace review, not a compliance check and not a prediction of ranking, conversion or sales.",
    }
