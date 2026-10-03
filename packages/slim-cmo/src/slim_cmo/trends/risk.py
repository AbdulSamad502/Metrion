"""Reported-tactic policy-risk assessment (spec §6.8.2 s3, §6.8.7 rule 3, AC29).

A "tactic" is something a web article or video CLAIMS works. Metrion does not know whether it
works and does not know whether it breaks a marketplace's rules. This module decides how
cautious the report must be:

* `PolicyRisk.NONE_IDENTIFIED` - a curated pattern set was applied and matched nothing. Even
  then the tactic is only ever "reported", and at most WATCHLIST / CONTENT_ANGLE may be
  suggested, alongside the standing policy-check line.
* `POSSIBLE` / `LIKELY` - a curated pattern matched, or the model raised a flag. NO action is
  ever suggested.
* `UNASSESSED` - there is no usable pattern set. This is the FAIL-SAFE (spec §6.8.7 rule 3c):
  nothing is declared safe, nothing is recommended. An EMPTY pattern set counts as no pattern
  set - a configured list that can match nothing must not read as "assessed and clean".

Asymmetry by construction: a model flag can RAISE the risk, never lower it; pattern matches
cannot be overridden by the model.

The pattern CONTENT is human-curated data (open question Q17); this module defines how it is
applied, not what is in it. Patterns are matched against `skeleton()` text (case/width/
zero-width/lookalike folded), so they should be authored in lower-case plain letters.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum

from slim_cmo.textnorm import skeleton


class PolicyRisk(str, Enum):
    NONE_IDENTIFIED = "NONE_IDENTIFIED"
    POSSIBLE = "POSSIBLE"
    LIKELY = "LIKELY"
    UNASSESSED = "UNASSESSED"


class RiskBasis(str, Enum):
    PATTERN_MATCH = "PATTERN_MATCH"
    MODEL_FLAG = "MODEL_FLAG"
    BOTH = "BOTH"
    NONE = "NONE"


_ORDER = {PolicyRisk.NONE_IDENTIFIED: 0, PolicyRisk.POSSIBLE: 1, PolicyRisk.LIKELY: 2}

# What a tactic with no identified risk may be turned into. Anything else is not offered.
SAFE_TACTIC_ACTIONS: frozenset[str] = frozenset({"WATCHLIST", "CONTENT_ANGLE"})
POLICY_CHECK_LINE = "Check the marketplace's current seller policy before trying this."


class PatternSetInvalid(ValueError):
    """A curated pattern set is malformed. Raised at construction so a bad set can never be
    loaded and silently treated as 'no risk'."""


@dataclass(frozen=True, slots=True)
class RiskPattern:
    id: str
    regex: str
    level: PolicyRisk


@dataclass(frozen=True)
class RiskPatternSet:
    version: str
    patterns: tuple[RiskPattern, ...]
    _compiled: tuple[tuple[str, re.Pattern[str], PolicyRisk], ...] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not isinstance(self.version, str) or not self.version.strip():
            raise PatternSetInvalid("a pattern set needs a version")
        compiled: list[tuple[str, re.Pattern[str], PolicyRisk]] = []
        seen: set[str] = set()
        for p in self.patterns:
            if p.level not in (PolicyRisk.POSSIBLE, PolicyRisk.LIKELY):
                raise PatternSetInvalid(f"pattern {p.id!r}: level must be POSSIBLE or LIKELY")
            if not p.id.strip() or p.id in seen:
                raise PatternSetInvalid(f"pattern id {p.id!r} is empty or duplicated")
            seen.add(p.id)
            try:
                compiled.append((p.id, re.compile(p.regex), p.level))
            except re.error as exc:
                raise PatternSetInvalid(f"pattern {p.id!r}: invalid regex ({exc})") from exc
        object.__setattr__(self, "_compiled", tuple(compiled))

    @property
    def usable(self) -> bool:
        return bool(self._compiled)


@dataclass(frozen=True, slots=True)
class RiskAssessment:
    risk: PolicyRisk
    basis: RiskBasis
    matched_pattern_ids: tuple[str, ...]

    @property
    def suggested_actions_allowed(self) -> frozenset[str]:
        return SAFE_TACTIC_ACTIONS if self.risk is PolicyRisk.NONE_IDENTIFIED else frozenset()


def assess_tactic_risk(
    text: str, pattern_set: RiskPatternSet | None, *, model_flagged: bool = False
) -> RiskAssessment:
    folded = skeleton(text)
    matched: list[tuple[str, PolicyRisk]] = []
    if pattern_set is not None and pattern_set.usable:
        matched = [(pid, level) for pid, rx, level in pattern_set._compiled if rx.search(folded)]
        assessed = True
    else:
        assessed = False

    if assessed:
        risk = PolicyRisk.NONE_IDENTIFIED
        for _, level in matched:
            if _ORDER[level] > _ORDER[risk]:
                risk = level
    else:
        risk = PolicyRisk.UNASSESSED

    pattern_hit = bool(matched)
    if model_flagged:
        if risk in (PolicyRisk.NONE_IDENTIFIED, PolicyRisk.UNASSESSED):
            risk = PolicyRisk.POSSIBLE  # raised; a model flag is never ignored, never lowers
        basis = RiskBasis.BOTH if pattern_hit else RiskBasis.MODEL_FLAG
    else:
        basis = RiskBasis.PATTERN_MATCH if pattern_hit else RiskBasis.NONE
    return RiskAssessment(risk, basis, tuple(sorted(pid for pid, _ in matched)))


def suggested_action_permitted(action: str, assessment: RiskAssessment) -> bool:
    """May `action` be offered for a tactic with this assessment? 'NO_ACTION' is always fine."""
    return action == "NO_ACTION" or action in assessment.suggested_actions_allowed


def pattern_set_from_entries(version: str, entries: Sequence[dict[str, str]]) -> RiskPatternSet:
    """Build a set from config-shaped dicts `{id, regex, level}`. Raises PatternSetInvalid."""
    patterns = []
    for e in entries:
        try:
            level = PolicyRisk(e["level"])
            patterns.append(RiskPattern(e["id"], e["regex"], level))
        except (KeyError, ValueError) as exc:
            raise PatternSetInvalid(f"malformed pattern entry: {e!r}") from exc
    return RiskPatternSet(version, tuple(patterns))
