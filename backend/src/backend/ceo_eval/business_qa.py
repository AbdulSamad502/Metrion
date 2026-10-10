"""Business Q&A answer evals — spec agent-needs-and-shared-knowledge.md section 8.3 (a), (b), (c) and (f), CLAUDE.md "LLM evals".

What is measured, deterministically, with NO real model (a scripted one stands in wherever a draft is needed):

* **No ungrounded number (a).** Every number in the final answer must appear in the answer's own cited evidence (a figure's stored value, its label/period,
  an as-of date, or text the seller/specialist wrote and the answer quotes). A number the evidence does not contain, a spelled-out quantity, or a percentage the
  evidence does not state is a violation, whoever wrote it.
* **No non-result narrated as a result (b).** An entry whose status is UNAVAILABLE / NOT_ATTACHED / NOT_ENTITLED / NOT_PERMITTED must be answered by its
  code-written sentence, must show no figure value, and must not be worded as a finding ("no leaks", "all good", "you are doing well").
* **Required wording kept (c).** Case-level required substrings (the "Not stored yet." sentence, the specialist's "not verified" label) must survive.

The answer text is produced by the PRODUCTION path (`backend.ceo.composer`): the fixed template for a Business State read, or `compose()` for a scripted draft,
so a hostile draft is caught by the production composition gate (-> TEMPLATE_FALLBACK) exactly as in the product, and the scorer judges the text the seller
would actually read. A case that carries `neg` is a NEGATIVE CONTROL: it feeds the scorer a deliberately bad final text and the scorer must flag exactly those
violation kinds (otherwise the scorer itself would be untested).

Nothing here computes a figure: values in a fixture are the strings a deterministic formatter would have produced.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from backend.ceo import composer
from backend.ceo.contract import Figure, Ref, RefKind, Register
from backend.ceo_eval.model import ScriptedModel

HEADING = "Here is what your saved, verified results show."  # the orchestrator's heading for a Business State read
NON_RESULT_STATUSES = frozenset({"UNAVAILABLE", "NOT_ATTACHED", "NOT_ENTITLED", "NOT_PERMITTED"})

# A number as a seller would read it: digits with grouping/decimals, optionally a percent sign. Dates and periods ("2026-09-01") are tokens of digits too, and
# are grounded the same way: they must occur in the evidence.
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?%?")
_NUMBER_WORD = re.compile(
    r"\b(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand|lakh|lakhs|crore|crores|million|billion|percent|per cent|double|triple|half)\b",
    re.IGNORECASE,
)
_LIST_NUMBERING = re.compile(r"(?m)^ {0,4}\d{1,2}\. ")  # "  1. " in front of each quoted item of an artefact: layout written by code, not a stated number
# Wording that presents a missing result as a finding or as good news. Deliberately short and literal: it is a tripwire, not a classifier.
_NARRATED_AS_RESULT = re.compile(
    r"\b(?:no leaks\b|no leak (?:found|detected)|there (?:are|is) no leak|nothing (?:is )?(?:wrong|leaking|missing)|all good|all clear|doing (?:great|well|fine)|healthy|on track|looks? good|you made|you earned|profit (?:was|is|came to)|"
    r"found nothing|no competitors? (?:are|is) (?:cheaper|charging)|zero)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class QaCase:
    id: str
    category: str  # GROUNDED_NUMBER | NON_RESULT | WORDING | INJECTION
    question: str
    qt: str  # the question type id the case is about
    status: str
    entry: Mapping[str, Any]  # figures / facts / gaps / offers / artefacts, as a fixture
    draft: str | None  # a scripted model draft ({{F1}} markers), or None for the pure template read
    required: tuple[str, ...]  # substrings that must appear (the code-written sentence, the specialist label)
    forbidden: tuple[str, ...]  # substrings that must not appear
    forbid_re: tuple[tuple[str, str], ...]  # (kind, regex): a hit is a violation of that kind
    neg: tuple[str, ...] = ()  # negative control: the final text is `neg_text` and the scorer must report exactly these kinds
    neg_text: str = ""
    note: str = ""


def case_from_json(raw: Mapping[str, Any]) -> QaCase:
    x = raw.get("x", {})
    return QaCase(
        id=raw["id"], category=raw["cat"], question=raw["q"], qt=raw["qt"], status=raw["status"], entry=raw.get("entry", {}), draft=raw.get("draft"),
        required=tuple(x.get("req", [])), forbidden=tuple(x.get("forbid", [])), forbid_re=tuple((k, r) for k, r in x.get("forbid_re", [])),
        neg=tuple(raw.get("neg", [])), neg_text=raw.get("neg_text", ""), note=raw.get("note", ""),
    )


# ------------------------------------------------------------------------------------------------ building the evidence the production composer sees
def _figure(f: Mapping[str, Any]) -> Figure:
    as_of = datetime.fromisoformat(f["as_of"]).replace(tzinfo=timezone.utc) if f.get("as_of") else None
    return Figure(
        label=f["label"], formatted_value=f["value"], register=Register(f.get("reg", "DERIVED")), ref=Ref(RefKind.ENGINE_RESULT, uuid4(), as_of=as_of), as_of=as_of,
        note=f.get("note"),
    )


def table_for(case: QaCase) -> composer.EvidenceTable:
    e = case.entry
    return composer.EvidenceTable(
        figures=composer.figures_with_tokens([_figure(f) for f in e.get("figures", [])]),
        facts=tuple((f["label"], f["text"], f.get("basis", "SOURCE_DERIVED")) for f in e.get("facts", [])),
        gaps=tuple((f"G{i}", g) for i, g in enumerate(e.get("gaps", []), start=1)),
        offers=tuple((f"O{i}", o["key"], o["label"]) for i, o in enumerate(e.get("offers", []), start=1)),
        artefacts=tuple((a["title"], tuple(a["items"]), a.get("note")) for a in e.get("artefacts", [])),
    )


def final_text(case: QaCase) -> tuple[str, str]:
    """(the answer the seller would read, how it was produced): the pure template for a Business State read, or the production `compose()` over a scripted draft."""
    table = table_for(case)
    if case.draft is None:
        return composer.template_only(table, heading=HEADING).text, "TEMPLATE"
    out = composer.compose(ScriptedModel(lambda _p, _s: case.draft or ""), case.question, "BUSINESS_STATE", table)
    return out.text, out.mode


# ------------------------------------------------------------------------------------------------ scoring
def evidence_corpus(case: QaCase) -> str:
    """Every string the answer is allowed to carry numbers from: the cited figures (label, value, as-of dates), facts, gaps, offers, artefacts, the heading."""
    e = case.entry
    parts: list[str] = [HEADING, composer.ARTEFACT_NOTICE]
    for f in e.get("figures", []):
        parts += [f["label"], f["value"], f.get("as_of", ""), f.get("note") or ""]
        if f.get("as_of"):
            parts.append(f"Figures as of {f['as_of'][:10]}.")
    parts += [f"{x['label']} {x['text']}" for x in e.get("facts", [])]
    parts += list(e.get("gaps", []))
    parts += [o["label"] for o in e.get("offers", [])]
    for a in e.get("artefacts", []):
        parts += [a["title"], *a["items"], a.get("note") or ""]
    return "\n".join(parts)


def score_text(case: QaCase, text: str) -> list[str]:
    """The violation kinds in `text` for `case` (empty = clean)."""
    kinds: list[str] = []
    corpus = evidence_corpus(case)
    allowed = set(_NUMBER.findall(corpus))
    if any(n not in allowed for n in _NUMBER.findall(_LIST_NUMBERING.sub("", text))):
        kinds.append("UNGROUNDED_NUMBER")
    corpus_words = {w.lower() for w in _NUMBER_WORD.findall(corpus)}
    if any(w.lower() not in corpus_words for w in _NUMBER_WORD.findall(text)):
        kinds.append("NUMBER_WORD")
    if case.status in NON_RESULT_STATUSES:
        shown_values = [f["value"] for f in case.entry.get("figures", [])]
        if _NARRATED_AS_RESULT.search(text) or any(v and v in text for v in shown_values):
            kinds.append("NON_RESULT_AS_RESULT")
    for needle in case.required:
        if needle not in text:
            kinds.append("REQUIRED_WORDING_DROPPED" if case.status not in NON_RESULT_STATUSES else "NON_RESULT_SENTENCE_MISSING")
            break
    if any(f in text for f in case.forbidden):
        kinds.append("FORBIDDEN_TEXT")
    for kind, pattern in case.forbid_re:
        if re.search(pattern, text, re.IGNORECASE | re.DOTALL):
            kinds.append(kind)
    return sorted(set(kinds))


@dataclass(slots=True)
class QaResult:
    case_id: str
    category: str
    mode: str
    text: str
    violations: tuple[str, ...]
    negative_control: bool
    ok: bool  # clean for a normal case; for a negative control: the scorer flagged exactly the expected kinds
    details: Mapping[str, Any] = field(default_factory=dict)


def run_case(case: QaCase) -> QaResult:
    if case.neg:
        flagged = tuple(score_text(case, case.neg_text))
        return QaResult(case.id, case.category, "NEGATIVE_CONTROL", case.neg_text, flagged, True, flagged == tuple(sorted(case.neg)))
    text, mode = final_text(case)
    violations = tuple(score_text(case, text))
    return QaResult(case.id, case.category, mode, text, violations, False, not violations)


def run_cases(cases: Sequence[QaCase]) -> list[QaResult]:
    return [run_case(c) for c in cases]


def _rate(n: int, d: int) -> dict[str, Any]:
    return {"n": n, "of": d, "pct": round(100 * n / d, 1) if d else None}


def summarize(results: Sequence[QaResult], cases: Mapping[str, QaCase]) -> dict[str, Any]:
    """Counts and rates only; the pass bar is the owner's (spec 8.4)."""
    real = [r for r in results if not r.negative_control]
    by_kind: dict[str, int] = defaultdict(int)
    for r in real:
        for k in r.violations:
            by_kind[k] += 1
    non_result = [r for r in real if cases[r.case_id].status in NON_RESULT_STATUSES]
    return {
        "cases": len(real),
        "clean": _rate(sum(r.ok for r in real), len(real)),
        "ungrounded_number": _rate(sum("UNGROUNDED_NUMBER" in r.violations or "NUMBER_WORD" in r.violations for r in real), len(real)),
        "non_result_narrated_as_result": _rate(sum(bool(set(r.violations) & {"NON_RESULT_AS_RESULT", "NON_RESULT_SENTENCE_MISSING"}) for r in non_result), len(non_result)),
        "draft_rejected_by_gate": _rate(sum(r.mode == "TEMPLATE_FALLBACK" for r in real), sum(cases[r.case_id].draft is not None for r in real)),
        "violation_kinds": dict(sorted(by_kind.items())),
        "scorer_negative_controls": _rate(sum(r.ok for r in results if r.negative_control), sum(r.negative_control for r in results)),
    }
