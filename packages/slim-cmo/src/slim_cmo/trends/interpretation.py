"""Checker for the 'What this could mean for your business' section (spec §6.8.2 s6, AC27, T40).

The interpretation is the one part of a trend report where the model speaks for itself, so it
is the most tightly fenced. An item is accepted only if:

* it cites at least one finding, and every cited finding id exists in this report;
* its action type is one of the defined set;
* it adds no number that is absent from the findings it cites (no new facts, no new figures);
* it makes no attention-as-demand or profit/outcome claim (`narration.check_trend_prose`);
* if it cites a reported tactic, it cannot recommend more than the tactic's risk permits:
  a tactic that is not `NONE_IDENTIFIED` (risky, or unassessed) allows `NO_ACTION` only, and a
  clean tactic allows at most WATCHLIST / CONTENT_ANGLE.

Rejected items are reported with every problem found; they are never edited into compliance.
The seller-facing label is a constant so it cannot be reworded.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum

from slim_cmo.claims import find_unsupported_numbers
from slim_cmo.narration import check_trend_prose
from slim_cmo.textnorm import clean_generated_text
from slim_cmo.trends.risk import SAFE_TACTIC_ACTIONS, PolicyRisk
from slim_cmo.types import TrendSection

INTERPRETATION_LABEL = "CMO's interpretation — not a verified market fact."

ACTION_TYPES: frozenset[str] = frozenset(
    {"LISTING_KEYWORD_IDEA", "CONTENT_ANGLE", "WATCHLIST", "INVESTIGATE_WITH_PI", "NO_ACTION"}
)


@dataclass(frozen=True, slots=True)
class FindingRef:
    finding_id: str
    section: TrendSection
    text: str  # the finding's theme + summary as shown to the seller
    policy_risk: PolicyRisk | None = None  # set for REPORTED_TACTICS findings


@dataclass(frozen=True, slots=True)
class InterpretationItem:
    statement: str
    derived_from_finding_ids: tuple[str, ...]
    action_type: str


class Problem(str, Enum):
    EMPTY_STATEMENT = "EMPTY_STATEMENT"
    NO_CITATION = "NO_CITATION"
    UNKNOWN_FINDING = "UNKNOWN_FINDING"
    BAD_ACTION = "BAD_ACTION"
    UNSUPPORTED_NUMBER = "UNSUPPORTED_NUMBER"
    BANNED_CLAIM = "BANNED_CLAIM"
    TACTIC_ACTION_NOT_ALLOWED = "TACTIC_ACTION_NOT_ALLOWED"


@dataclass(frozen=True, slots=True)
class RejectedItem:
    index: int
    problems: tuple[Problem, ...]


@dataclass(frozen=True, slots=True)
class InterpretationCheck:
    accepted: tuple[InterpretationItem, ...]
    rejected: tuple[RejectedItem, ...]


def check_interpretation(
    items: Sequence[InterpretationItem], findings: Mapping[str, FindingRef]
) -> InterpretationCheck:
    accepted: list[InterpretationItem] = []
    rejected: list[RejectedItem] = []
    for index, item in enumerate(items):
        problems: list[Problem] = []
        statement = clean_generated_text(item.statement) if isinstance(item.statement, str) else ""
        if not statement:
            problems.append(Problem.EMPTY_STATEMENT)
        ids = tuple(item.derived_from_finding_ids or ())
        cited: list[FindingRef] = []
        if not ids:
            problems.append(Problem.NO_CITATION)
        for fid in ids:
            ref = findings.get(fid)
            if ref is None:
                problems.append(Problem.UNKNOWN_FINDING)
            else:
                cited.append(ref)
        if item.action_type not in ACTION_TYPES:
            problems.append(Problem.BAD_ACTION)
        if statement and cited:
            if find_unsupported_numbers(statement, [c.text for c in cited]):
                problems.append(Problem.UNSUPPORTED_NUMBER)
        if statement and check_trend_prose(statement):
            problems.append(Problem.BANNED_CLAIM)
        if item.action_type in ACTION_TYPES and item.action_type != "NO_ACTION":
            for c in cited:
                if c.section is TrendSection.REPORTED_TACTICS:
                    allowed = SAFE_TACTIC_ACTIONS if c.policy_risk is PolicyRisk.NONE_IDENTIFIED else frozenset()
                    if item.action_type not in allowed:
                        problems.append(Problem.TACTIC_ACTION_NOT_ALLOWED)
                        break
        if problems:
            rejected.append(RejectedItem(index, tuple(dict.fromkeys(problems))))
        else:
            accepted.append(InterpretationItem(statement, ids, item.action_type))
    return InterpretationCheck(tuple(accepted), tuple(rejected))
