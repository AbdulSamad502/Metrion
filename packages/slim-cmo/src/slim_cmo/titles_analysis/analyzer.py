"""Five-title quality analyzer (CMO 3.0 M3; docs/specs/slim-cmo-agent.md section 6.15).

What this module IS: pure, deterministic code that compares title options against the seller's own CONFIRMED facts and a verified marketplace rule, and explains the result with named
rules. Same input, same output. For every option it reports, separately and never blended into one number:

* marketplace rules - hard pass / fail against the VERIFIED rule for the marketplace, or NOT_ASSESSED when no verified, current rule exists (a missing rule is never a pass);
* fact accuracy - hard fail for an invented number, an unconfirmed claim, a forbidden statement or a value the seller never confirmed (the existing claim / forbidden gates);
* keyword relevance - how many of the title-worthy keywords from the keyword analysis (M2) the title carries, or NOT_ASSESSED;
* buyer-intent coverage - which kinds of buyer search the wording speaks to (brand, product type, specification, use case);
* positioning - the strategy the wording follows (descriptive, never a score) and, when competitor themes were supplied, which of them it mentions;
* readability - concrete wording flags (a word repeated, shouting, symbols, too short), and length against the verified rule when there is one.

On top of those it computes a TITLE QUALITY SCORE, 0-100, by fixed integer rules (section 6.15 of the spec): keyword relevance 25, confirmed-fact accuracy 25, readability 20, buyer intent 15,
structure 15. Every criterion lists the points it kept and the deductions with their reasons. A criterion whose essential evidence is missing is NOT_ASSESSED: it earns nothing, is taken out of
BOTH the points earned and the points assessable (never treated as zero), and the overall score is shown with how many of the 100 points could be assessed; below MIN_ASSESSED_POINTS there
is no overall score at all. MARKETPLACE COMPLIANCE IS NOT PART OF THE SCORE: it stays a separate PASS / FAIL / NOT_ASSESSED.

What it is NOT: it calls no model and reads no database. The score is an INTERNAL listing-quality assessment of wording and fit with the seller's own facts. It is not an Amazon SEO ranking,
search volume, conversion rate or sales prediction. Unsupported claims and verified marketplace-rule violations are HARD FAILURES: such an option is never recommended, whatever its score.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from slim_cmo.generation.facts import FactContext
from slim_cmo.generation.safety import prose_findings
from slim_cmo.keywords.intelligence import CLAIM_TERMS, _claim_confirmed, _claim_in, _words
from slim_cmo.types import Marketplace

METHOD = "title-analysis-v2"
MAX_POINTS = {"keywordRelevance": 25, "factAccuracy": 25, "readability": 20, "buyerIntent": 15, "structure": 15}  # sums to 100
MIN_ASSESSED_POINTS = 50  # below this many assessable points there is no overall score (an internal rule of thumb, stated to the seller)
BANDS = ((80, "STRONG"), (65, "GOOD"), (50, "FAIR"), (0, "WEAK"))  # internal quality bands for the overall score; not marketplace terms
READ_COSTS = {"REPEATS": 8, "CAPS": 5, "SYMBOLS": 4, "SHORT": 8, "LONG": 4}  # readability points lost per flag (out of 20)
INTENT_WEIGHTS = {"brand": 3, "product type": 6, "specification": 4, "use case": 2}  # buyer-intent points per kind the seller confirmed (rescaled to 15)
STRUCT_WEIGHTS = {"type_early": 6, "no_repeated_pair": 3, "few_separators": 3, "brand_early": 3}  # structure points per rule (rescaled to 15)
_TYPE_WITHIN = 8  # the product type should appear in the first this-many words
_BRAND_WITHIN = 3
_MAX_SEPARATORS = 3
_LONG_WORDS = 20
NOT_ASSESSED = "NOT_ASSESSED"
STRONG, OK, WEAK = "STRONG", "OK", "WEAK"
_STOP = frozenset({"a", "an", "the", "for", "of", "and", "with", "in", "to", "by", "on"})
_USE_CASES = frozenset({"gym", "school", "office", "travel", "kids", "daily", "home", "camping", "running", "hiking", "sports", "yoga", "college", "outdoor", "everyday", "work"})
_SIZE_ATTRS = frozenset({"size", "capacity", "volume", "weight", "dimensions"})
_SPEC_ATTRS = _SIZE_ATTRS | {"material", "color", "colour"}
_REPEAT_AT = 3  # a content word used this many times or more reads as stuffing
_SYMBOLS = re.compile(r"[^\w\s,\-'&/().]", re.UNICODE)
_MAX_SYMBOLS = 2
_MIN_WORDS = 3


@dataclass(frozen=True, slots=True)
class TitleOption:
    id: str
    rank: int  # presentation order only; never a quality claim
    text: str


@dataclass(frozen=True, slots=True)
class RuleContext:
    """The marketplace rule as the analyzer needs it. `check` is None when no verified, current rule exists; `reason` then says why (shown to the seller)."""

    check: Callable[[str], tuple[bool, tuple[str, ...], int]] | None = None  # text -> (valid, violation codes, counted length)
    limit: int | None = None
    source_url: str | None = None
    verified_at: str | None = None
    reason: str = "no verified marketplace rule is available"
    kind: str = "VERIFIED"  # TEST_FIXTURE only in tests: said plainly, never presented as the marketplace's real rule


@dataclass(frozen=True, slots=True)
class AnalysisInputs:
    options: Sequence[TitleOption]
    facts: FactContext
    product_name: str | None
    brand: str | None
    keyword_result: Mapping[str, Any] | None  # the M2 analysis (candidates with placement), or None
    rule: RuleContext
    ci_theme_words: tuple[str, ...] = ()
    marketplace: Marketplace | None = None


def _tokens(text: str) -> list[str]:
    return _words(text)


def _contains(title_words: set[str], phrase_words: Sequence[str]) -> bool:
    content = [w for w in phrase_words if w not in _STOP]
    return bool(content) and all(w in title_words for w in content)


def _eligible_by_name(facts: FactContext) -> dict[str, str]:
    return {a.name.casefold(): str(a.value) for a in facts.eligible if a.value}


# ------------------------------------------------------------------------------------------------ dimensions
def _rules(text: str, rule: RuleContext) -> dict[str, Any]:
    if rule.check is None:
        return {"status": NOT_ASSESSED, "detail": f"Not assessed: {rule.reason}. Check the limit in your seller account before you use a title."}
    valid, codes, n = rule.check(text)
    return {"status": "PASS" if valid else "FAIL", "violations": list(codes), "length": n, "limit": rule.limit, "sourceUrl": rule.source_url, "verifiedAt": rule.verified_at, "ruleKind": rule.kind,
            "detail": ("" if rule.kind == "VERIFIED" else "Placeholder test limit, NOT a verified marketplace rule. ") + ((f"Within the verified marketplace rule ({n} of {rule.limit} characters)." if valid and rule.limit else "Passes the verified marketplace rule.") if valid
            else "Breaks the verified marketplace rule: " + ", ".join(codes).lower().replace("_", " ") + ".")}


def _fact_accuracy(text: str, inp: AnalysisInputs) -> dict[str, Any]:
    elig = [a for a in inp.facts.eligible if a.value]
    if not elig and not inp.product_name:
        return {"status": NOT_ASSESSED, "detail": "Not assessed: there are no confirmed facts to check the title against.", "findings": []}
    findings = [{"kind": f.kind, "rule": f.rule} for f in prose_findings([("title", text)], inp.facts)]
    words = _tokens(text)
    product_words = set(_tokens(inp.product_name or ""))
    for claim in CLAIM_TERMS:
        if _claim_in(words) == claim and not _claim_confirmed(claim, elig, product_words):
            findings.append({"kind": "UNSUPPORTED_CLAIM", "rule": claim})
    seen: set[tuple[str, str]] = set()
    unique = [f for f in findings if not ((f["kind"], f["rule"]) in seen or seen.add((f["kind"], f["rule"])))]
    if unique:
        return {"status": "HARD_FAIL", "findings": unique, "detail": "Says something you have not confirmed: " + "; ".join(_finding_text(f) for f in unique) + "."}
    used = [a.name for a in elig if a.name.casefold() != "product_name" and _tokens(str(a.value)) and set(_tokens(str(a.value))) <= set(words)]
    return {"status": "PASS", "findings": [], "confirmedDetailsUsed": used, "detail": "Every claim in it is backed by your confirmed facts."}


def _finding_text(f: Mapping[str, str]) -> str:
    return {"UNSUPPORTED_NUMBER": f"the number {f['rule']} is not in your facts", "INELIGIBLE_ATTRIBUTE": f"it states {f['rule']}, which you have not confirmed",
            "UNSUPPORTED_CLAIM": f"it claims “{f['rule']}”, which you have not confirmed", "FORBIDDEN": "it contains wording that is not allowed (price, tax, ranking or similar)"}.get(f["kind"], f["kind"].lower())


def _keyword_relevance(text: str, inp: AnalysisInputs) -> dict[str, Any]:
    res = inp.keyword_result
    cands = [c for c in (res or {}).get("candidates", []) if c.get("recommended") and "TITLE" in c.get("placement", [])]
    if not res or res.get("status") != "COMPLETE" or not cands:
        return {"status": NOT_ASSESSED, "detail": "Not assessed: there are no title-worthy keywords yet (they come from your confirmed facts).", "covered": [], "missing": []}
    tw = set(_tokens(text))
    covered = [c["keyword"] for c in cands if _contains(tw, c["keyword"].split())]
    missing = [c["keyword"] for c in cands if c["keyword"] not in covered]
    share = len(covered) * 2
    band = STRONG if len(covered) == len(cands) else OK if share >= len(cands) else WEAK
    return {"status": band, "covered": covered, "missing": missing, "detail": f"Carries {len(covered)} of {len(cands)} title-worthy keywords for your product."}


def _intent(text: str, inp: AnalysisInputs) -> dict[str, Any]:
    by = _eligible_by_name(inp.facts)
    if not by and not inp.product_name:
        return {"status": NOT_ASSESSED, "detail": "Not assessed: there are no confirmed facts.", "present": [], "missing": []}
    tw = set(_tokens(text))
    brand = set(_tokens(inp.brand or by.get("brand", "")))
    core = [w for w in _tokens(inp.product_name or "") if w not in brand and w not in _STOP and not w.isdigit()]
    spec_vals = [v for n, v in by.items() if n in _SPEC_ATTRS]
    present: list[str] = []
    missing: list[str] = []
    if brand:
        (present if brand <= tw else missing).append("brand")
    if core:
        (present if sum(w in tw for w in core) * 2 >= len(core) else missing).append("product type")
    if spec_vals:
        (present if any(set(_tokens(v)) <= tw for v in spec_vals) else missing).append("specification (size, material or colour)")
    uses = [w for n, v in by.items() if n in {"main use", "use", "key features"} for w in _tokens(v) if w in _USE_CASES]
    if uses:
        (present if any(u in tw for u in uses) else missing).append("use case")
    needs_type = "product type" in present
    band = STRONG if not missing and needs_type else OK if needs_type and len(present) >= 2 else WEAK
    return {"status": band, "present": present, "missing": missing,
            "detail": "Speaks to: " + (", ".join(present) or "nothing you confirmed") + (". Leaves out: " + ", ".join(missing) if missing else "") + "."}


def _strategy(text: str, inp: AnalysisInputs) -> tuple[str, str]:
    by = _eligible_by_name(inp.facts)
    ws = _tokens(text)
    brand = set(_tokens(inp.brand or by.get("brand", "")))
    if brand and ws and ws[0] in brand:
        return "Brand-first", "Leads with your brand name, then describes the product."
    first = [w for w in ws[:4]]
    if any(w in _USE_CASES for w in first):
        return "Use-case-first", "Leads with who or what it is for."
    spec_words = {w for n, v in by.items() if n in _SPEC_ATTRS for w in _tokens(v)}
    if ws and (ws[0].isdigit() or ws[0] in spec_words):
        return "Specification-first", "Leads with a specification such as size, material or colour."
    return "Search-coverage", "Leads with what the product is, the way a buyer would search for it."


def _positioning(text: str, inp: AnalysisInputs) -> dict[str, Any]:
    label, why = _strategy(text, inp)
    out: dict[str, Any] = {"status": "DESCRIPTIVE", "strategy": label, "detail": why}
    if inp.ci_theme_words:
        tw = set(_tokens(text))
        used = [w for w in inp.ci_theme_words if w in tw]
        out["competitorThemesMentioned"] = used
        out["competitorDetail"] = ("Mentions competitor themes: " + ", ".join(used) + ".") if used else "Mentions none of the themes your tracked competitors use."
    else:
        out["competitorThemesMentioned"] = NOT_ASSESSED
        out["competitorDetail"] = "Competitor positioning: not assessed (no competitor evidence was supplied)."
    return out


def _readability(text: str, rule: RuleContext) -> dict[str, Any]:
    ws = _tokens(text)
    flags: list[str] = []
    codes: list[str] = []
    content = [w for w in ws if w not in _STOP and not w.isdigit()]
    repeated = [w for w, n in Counter(content).items() if n >= _REPEAT_AT]
    if repeated:
        flags.append("repeats " + ", ".join(repeated) + " (reads as keyword stuffing)")
        codes.append("REPEATS")
    shouting = [w for w in re.findall(r"[^\W\d_]{4,}", text) if w.isupper()]
    if shouting:
        flags.append("uses ALL CAPS words")
        codes.append("CAPS")
    if len(_SYMBOLS.findall(text)) > _MAX_SYMBOLS:
        flags.append("has many symbols")
        codes.append("SYMBOLS")
    if len(ws) < _MIN_WORDS:
        flags.append("is very short")
        codes.append("SHORT")
    if len(ws) > _LONG_WORDS:
        flags.append(f"is very long ({len(ws)} words, hard to scan)")
        codes.append("LONG")
    band = STRONG if not flags else OK if len(flags) == 1 else WEAK
    d: dict[str, Any] = {"status": band, "flags": flags, "flagCodes": codes, "words": len(ws), "detail": "Reads cleanly." if not flags else "Reading flags: " + "; ".join(flags) + "."}
    if rule.check is None:
        d["lengthCheck"] = NOT_ASSESSED
    return d



# ------------------------------------------------------------------------------------------------ the 0-100 score (integer arithmetic only)
def _share(max_points: int, num: int, den: int) -> int:
    """max_points * num / den, rounded half up, in integers."""
    return (max_points * num * 2 + den) // (2 * den) if den else 0


def _na(name: str, detail: str) -> dict[str, Any]:
    return {"status": NOT_ASSESSED, "earned": None, "max": MAX_POINTS[name], "detail": detail, "deductions": []}


def _crit(name: str, earned: int, detail: str, deductions: list[dict[str, Any]]) -> dict[str, Any]:
    return {"status": "ASSESSED", "earned": earned, "max": MAX_POINTS[name], "detail": detail, "deductions": deductions}


def _structure(text: str, inp: AnalysisInputs) -> dict[str, Any]:
    ws = _tokens(text)
    by = _eligible_by_name(inp.facts)
    brand = set(_tokens(inp.brand or by.get("brand", "")))
    core = {w for w in _tokens(inp.product_name or "") if w not in brand and w not in _STOP and not w.isdigit() and w not in _UNIT_WORDS}
    rules: list[tuple[str, bool, str]] = []
    if core:
        rules.append(("type_early", any(w in core for w in ws[:_TYPE_WITHIN]), f"the product type appears within the first {_TYPE_WITHIN} words"))
    pairs = Counter(zip(ws, ws[1:], strict=False))
    rules.append(("no_repeated_pair", not any(n >= 2 and not (a in _STOP or b in _STOP) for (a, b), n in pairs.items()), "no two-word phrase is repeated"))
    rules.append(("few_separators", len(re.findall(r"[,|;:\u2013\u2014]|\s-\s", text)) <= _MAX_SEPARATORS, f"at most {_MAX_SEPARATORS} separators (commas, dashes, bars)"))
    if brand:
        rules.append(("brand_early", bool(brand & set(ws[:_BRAND_WITHIN])), f"your brand appears within the first {_BRAND_WITHIN} words"))
    total = sum(STRUCT_WEIGHTS[k] for k, _, _ in rules)
    kept = sum(STRUCT_WEIGHTS[k] for k, ok, _ in rules if ok)
    earned = _share(MAX_POINTS["structure"], kept, total)
    failed = [label for _, ok, label in rules if not ok]
    ded = [{"reason": "Does not meet: " + "; ".join(failed), "points": MAX_POINTS["structure"] - earned}] if failed else []
    return _crit("structure", earned, "Structure rules met: " + ", ".join(label for _, ok, label in rules if ok) + "." if not failed else "Structure rules not met: " + "; ".join(failed) + ".", ded)


_UNIT_WORDS = frozenset({"litre", "litres", "liter", "liters", "l", "ml", "kg", "g", "gm", "gram", "grams", "cm", "mm", "inch", "inches", "oz", "pcs", "piece", "pieces", "pack", "set"})


def _scores(d: Mapping[str, Any], text: str, inp: AnalysisInputs) -> dict[str, Any]:
    crit: dict[str, dict[str, Any]] = {}
    kr = d["keywordRelevance"]
    if kr["status"] == NOT_ASSESSED:
        crit["keywordRelevance"] = _na("keywordRelevance", "Not assessed: there are no title-worthy keywords yet, so no points were awarded or taken away.")
    else:
        total = len(kr["covered"]) + len(kr["missing"])
        earned = _share(25, len(kr["covered"]), total)
        ded = [{"reason": "Leaves out " + ", ".join(f"“{k}”" for k in kr["missing"]), "points": 25 - earned}] if kr["missing"] else []
        crit["keywordRelevance"] = _crit("keywordRelevance", earned, f"Carries {len(kr['covered'])} of {total} title-worthy keywords: 25 x {len(kr['covered'])}/{total} = {earned}.", ded)
    fa = d["factAccuracy"]
    if fa["status"] == NOT_ASSESSED:
        crit["factAccuracy"] = _na("factAccuracy", "Not assessed: there are no confirmed facts to check the title against, so no points were awarded or taken away.")
    elif fa["status"] == "HARD_FAIL":
        crit["factAccuracy"] = _crit("factAccuracy", 0, "Hard failure: " + fa["detail"], [{"reason": fa["detail"], "points": 25}])
    else:
        crit["factAccuracy"] = _crit("factAccuracy", 25, "Every claim is backed by your confirmed facts: 25 of 25.", [])
    rd = d["readability"]
    lost = sum(READ_COSTS[c] for c in rd["flagCodes"])
    r_earned = max(0, 20 - lost)
    crit["readability"] = _crit("readability", r_earned, "Reads cleanly: 20 of 20." if not rd["flagCodes"] else f"Reading flags cost {min(lost, 20)} points: " + "; ".join(rd["flags"]) + ".",
                                [{"reason": f, "points": READ_COSTS[c]} for f, c in zip(rd["flags"], rd["flagCodes"], strict=False)])
    bi = d["buyerIntent"]
    if bi["status"] == NOT_ASSESSED:
        crit["buyerIntent"] = _na("buyerIntent", "Not assessed: there are no confirmed facts, so no points were awarded or taken away.")
    else:
        key = lambda label: next(k for k in INTENT_WEIGHTS if label.startswith(k))  # noqa: E731
        present, missing = [key(x) for x in bi["present"]], [key(x) for x in bi["missing"]]
        kept, total = sum(INTENT_WEIGHTS[k] for k in present), sum(INTENT_WEIGHTS[k] for k in present + missing)
        earned = _share(15, kept, total)
        ded = [{"reason": "Leaves out " + ", ".join(missing), "points": 15 - earned}] if missing else []
        crit["buyerIntent"] = _crit("buyerIntent", earned, "Speaks to: " + (", ".join(present) or "nothing you confirmed") + (f". Leaves out: {', '.join(missing)}" if missing else "") + f". {earned} of 15.", ded)
    crit["structure"] = _structure(text, inp)
    assessed = [c for c in crit.values() if c["status"] == "ASSESSED"]
    earned_sum, assessable = sum(c["earned"] for c in assessed), sum(c["max"] for c in assessed)
    if assessable < MIN_ASSESSED_POINTS:
        overall: dict[str, Any] = {"status": NOT_ASSESSED, "assessablePoints": assessable, "note": f"Not enough evidence for an overall score: only {assessable} of 100 points could be assessed (at least {MIN_ASSESSED_POINTS} are needed)."}
    else:
        score = _share(100, earned_sum, assessable)
        overall = {"status": "ASSESSED", "score": score, "band": next(b for floor, b in BANDS if score >= floor), "earnedPoints": earned_sum, "assessablePoints": assessable,
                   "note": ("Based on all five criteria: 100 of 100 points assessable." if assessable == 100 else f"Based on {assessable} of 100 points assessable; the criteria that could not be assessed are left out, not counted as zero.")}
    return {"criteria": crit, "overall": overall}

# ------------------------------------------------------------------------------------------------ the comparison
_COMPARED = ("keywordRelevance", "buyerIntent", "readability")


def _strengths_weaknesses(d: Mapping[str, Any]) -> tuple[list[str], list[str]]:
    good, bad = [], []
    fa = d["factAccuracy"]
    if fa["status"] == "PASS" and fa.get("confirmedDetailsUsed"):
        good.append("Uses your confirmed " + ", ".join(x.lower() for x in fa["confirmedDetailsUsed"]))
    kr = d["keywordRelevance"]
    if kr["status"] in (STRONG, OK):
        good.append(kr["detail"].rstrip("."))
    elif kr["status"] == WEAK and kr["missing"]:
        bad.append("Leaves out keywords such as " + ", ".join(f"“{k}”" for k in kr["missing"][:3]))
    bi = d["buyerIntent"]
    if bi["status"] == STRONG:
        good.append("Speaks to " + ", ".join(bi["present"]))
    elif bi["missing"]:
        bad.append("Leaves out " + ", ".join(bi["missing"]))
    rd = d["readability"]
    if rd["flags"]:
        bad.append("Wording " + "; ".join(rd["flags"]))
    elif rd["status"] == STRONG:
        good.append("Reads cleanly")
    return good, bad


def _counts(d: Mapping[str, Any]) -> tuple[int, int]:
    bands = [d[k]["status"] for k in _COMPARED]
    return bands.count(WEAK), bands.count(STRONG)


def _recommendation(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """The recommendation, by score, never across unequal evidence. Only options with no hard failure and an overall score compete, and only options assessed on the SAME points compete:
    if coverage differs (one title could be checked on more of the 100 points than another), the comparison is limited to the group with the most assessable points and the answer says
    so, because 85/100 on 60 assessable points is not the same evidence as 85/100 on 100."""
    eligible = [r for r in rows if r["eligible"]]
    scored = [r for r in eligible if r["scores"]["overall"]["status"] == "ASSESSED"]
    if not eligible:
        return {"optionId": None, "status": "NONE_ELIGIBLE", "text": "None of these options passes the hard checks, so none is recommended, whatever its score. Ask for new titles after confirming more details."}
    if not scored:
        return {"optionId": None, "status": "NOT_ASSESSED", "text": "There is not enough confirmed evidence to score these titles, so none is recommended. Tell me more about your product and ask again."}
    widest = max(r["scores"]["overall"]["assessablePoints"] for r in scored)
    pool = [r for r in scored if r["scores"]["overall"]["assessablePoints"] == widest]
    left_out = [r for r in scored if r not in pool]
    fairness = ""
    if left_out:
        names = ", ".join(str(r["rank"]) for r in sorted(left_out, key=lambda x: x["rank"]))
        fairness = f" Option(s) {names} could be checked on fewer points than the others, so they were not compared with them."
    best = max(r["scores"]["overall"]["score"] for r in pool)
    top = [r for r in pool if r["scores"]["overall"]["score"] == best]
    basis = f"{widest} of 100 points assessable"
    if len(top) == 1:
        r = top[0]
        others = sorted((x["scores"]["overall"]["score"] for x in pool if x is not r), reverse=True)
        vs = f", ahead of the next best at {others[0]}" if others else ""
        reasons = list(r["strengths"]) or ["It has no weak point on the checks that could be run"]
        return {"optionId": r["optionId"], "status": "RECOMMENDED", "score": best, "assessablePoints": widest, "comparedOptionIds": [x["optionId"] for x in pool],
                "text": f"Option {r['rank']} has the highest internal quality score ({best}/100, {basis}{vs}): " + "; ".join(reasons) + "." + fairness, "reasons": reasons}
    ranks = ", ".join(str(r["rank"]) for r in sorted(top, key=lambda x: x["rank"]))
    return {"optionId": None, "status": "TIE", "tiedOptionIds": [r["optionId"] for r in top], "score": best, "assessablePoints": widest, "comparedOptionIds": [x["optionId"] for x in pool],
            "text": f"Options {ranks} are tied at {best}/100 ({basis}), so there is no single best. Choose by your own preference." + fairness}


def analyse_titles(inp: AnalysisInputs) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for o in inp.options:
        text = " ".join(o.text.split())
        dims = {"marketplaceRules": _rules(text, inp.rule), "factAccuracy": _fact_accuracy(text, inp), "keywordRelevance": _keyword_relevance(text, inp),
                "buyerIntent": _intent(text, inp), "positioning": _positioning(text, inp), "readability": _readability(text, inp.rule)}
        hard = []
        if dims["factAccuracy"]["status"] == "HARD_FAIL":
            hard.append(dims["factAccuracy"]["detail"])
        if dims["marketplaceRules"]["status"] == "FAIL":
            hard.append(dims["marketplaceRules"]["detail"])
        good, bad = _strengths_weaknesses(dims)
        scores = _scores(dims, text, inp)
        if hard and scores["overall"]["status"] == "ASSESSED":
            scores["overall"]["band"] = "NOT_USABLE"
            scores["overall"]["note"] = "Hard failure: this option is never recommended, whatever its score. " + scores["overall"]["note"]
        rows.append({"optionId": o.id, "rank": o.rank, "text": text, "strategy": dims["positioning"]["strategy"], "dimensions": dims, "scores": scores, "hardFailures": hard,
                     "strengths": good, "weaknesses": bad, "eligible": not hard})
    rec = _recommendation(rows)
    notes = []
    skipped = sorted({k for r in rows for k, v in r["dimensions"].items() if v["status"] == NOT_ASSESSED})
    if skipped:
        notes.append("Not assessed (left out of the comparison, never counted as good or bad): " + ", ".join(_DIM_NAMES[k] for k in skipped) + ".")
    return {"method": METHOD, "status": "COMPLETE", "marketplace": inp.marketplace.value if inp.marketplace else None, "options": rows, "recommendation": rec, "notes": notes,
            "scoring": {"criteria": {k: v for k, v in MAX_POINTS.items()}, "minimumAssessedPoints": MIN_ASSESSED_POINTS, "bands": [{"from": f, "band": b} for f, b in BANDS]},
            "limits": ["The 0-100 score is an internal listing-quality assessment of wording and fit with your own confirmed facts. It is not an Amazon SEO ranking, a search position, search volume, a conversion rate or a sales prediction.",
                       "Marketplace compliance is not part of the score: it is shown separately as PASS, FAIL or NOT_ASSESSED.",
                       "A criterion that could not be assessed is left out of the score; it is never counted as zero or as full marks.",
                       "Unsupported claims and verified marketplace-rule violations are hard failures: an option with one is never recommended.",
                       "The order the options were written in is not a ranking."]}


_DIM_NAMES = {"marketplaceRules": "marketplace rules", "factAccuracy": "fact accuracy", "keywordRelevance": "keyword relevance", "buyerIntent": "buyer-intent coverage", "positioning": "positioning",
              "readability": "readability"}
