"""Vision evaluation maths (spec §6.2.1; P6 decision 13) - pure, integers only.

An evaluation compares what the parser produced against a HUMAN-LABELLED dataset and judges the result against
a human-approved BAR. No threshold lives in code: `parse_bar` refuses a bar that does not state every threshold,
and there is no default bar. Rates are integer basis points (1/10000) computed by integer cross-multiplication,
never floats.

Metrics (per field class and overall), after the same parse + policy filtering production applies:
* precision  = correct / reported       (reported = a value was produced)
* recall     = correct / expected_present
* hallucination = values reported for a field the label says is NOT in the image / expected_absent
* numeral reliance = items whose raw reply put a digit-bearing value in a field (all such values are discarded
  by policy; CI Q18 showed the failure class is dropped/wrong numerals)

A class or the hallucination measure with no evidence (no positive / no absent examples) FAILS the bar: the
dataset cannot support a trust decision.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from slim_cmo.textnorm import dedupe_key
from slim_cmo.vision.parse import AnalysisOutcome, ParsedAnalysis
from slim_cmo.vision.schema import ATTRIBUTE_NAMES

BP = 10_000


class BarInvalid(ValueError):
    """The bar/threshold file is missing a required threshold or has an invalid one. There is no default bar."""

    def __init__(self, problems: Sequence[str]) -> None:
        self.problems = tuple(problems)
        super().__init__("; ".join(problems))


class DatasetInvalid(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ClassBar:
    min_precision_bp: int
    min_recall_bp: int


@dataclass(frozen=True, slots=True)
class Bar:
    name: str
    min_items: int
    max_hallucination_bp: int
    max_numeral_reliance_bp: int
    per_class: Mapping[str, ClassBar]


def _bp(obj: Mapping[str, Any], key: str, problems: list[str], where: str) -> int:
    v = obj.get(key)
    if type(v) is not int or not (0 <= v <= BP):
        problems.append(f"{where}{key} must be an integer between 0 and {BP} (basis points)")
        return 0
    return v


def parse_bar(obj: object) -> Bar:
    """Validate a bar document. Every threshold is required; an absent one is an error, never a default."""
    problems: list[str] = []
    if not isinstance(obj, dict):
        raise BarInvalid(["the bar must be a JSON object"])
    name = obj.get("name")
    if not isinstance(name, str) or not name.strip():
        problems.append("name is required (it identifies the approved bar in `bar_ref`)")
    min_items = obj.get("min_items")
    if type(min_items) is not int or min_items < 1:
        problems.append("min_items must be an integer >= 1")
        min_items = 1
    max_h = _bp(obj, "max_hallucination_bp", problems, "")
    max_n = _bp(obj, "max_numeral_reliance_bp", problems, "")
    per_class_raw = obj.get("per_class")
    per_class: dict[str, ClassBar] = {}
    if not isinstance(per_class_raw, dict):
        problems.append("per_class must be an object with an entry for every field class")
    else:
        for extra in sorted(set(per_class_raw) - set(ATTRIBUTE_NAMES)):
            problems.append(f"per_class has an unknown class {extra!r}")
        for cls in ATTRIBUTE_NAMES:
            entry = per_class_raw.get(cls)
            if not isinstance(entry, dict):
                problems.append(f"per_class.{cls} is required")
                continue
            per_class[cls] = ClassBar(_bp(entry, "min_precision_bp", problems, f"per_class.{cls}."), _bp(entry, "min_recall_bp", problems, f"per_class.{cls}."))
    if problems:
        raise BarInvalid(problems)
    return Bar(str(name).strip(), min_items, max_h, max_n, per_class)


@dataclass(frozen=True, slots=True)
class LabelledItem:
    item_id: str
    labels: Mapping[str, str | None]  # expected value, or None = not in the image / not determinable


def validate_item(item_id: str, labels: object) -> LabelledItem:
    if not isinstance(labels, dict) or set(labels) != set(ATTRIBUTE_NAMES):
        raise DatasetInvalid(f"item {item_id!r} must label EVERY field ({', '.join(ATTRIBUTE_NAMES)}), using null for 'not present'")
    for k, v in labels.items():
        if v is not None and not (isinstance(v, str) and v.strip()):
            raise DatasetInvalid(f"item {item_id!r} label {k!r} must be a non-empty string or null")
    return LabelledItem(item_id, dict(labels))


@dataclass(frozen=True, slots=True)
class ClassCounts:
    expected_present: int = 0
    expected_absent: int = 0
    reported: int = 0
    correct: int = 0
    hallucinated: int = 0


@dataclass(frozen=True, slots=True)
class Metrics:
    items: int
    failed_items: int
    numeral_items: int
    per_class: Mapping[str, ClassCounts]

    @property
    def absent_total(self) -> int:
        return sum(c.expected_absent for c in self.per_class.values())

    @property
    def hallucinated_total(self) -> int:
        return sum(c.hallucinated for c in self.per_class.values())

    def to_json(self) -> dict[str, Any]:
        def bp(n: int, d: int) -> int | None:
            return None if d == 0 else n * BP // d

        return {
            "schema": "cmo-vision-eval-metrics-v1",
            "items": self.items,
            "failed_items": self.failed_items,
            "numeral_items": self.numeral_items,
            "numeral_reliance_bp": bp(self.numeral_items, self.items),
            "hallucinated": self.hallucinated_total,
            "expected_absent": self.absent_total,
            "hallucination_bp": bp(self.hallucinated_total, self.absent_total),
            "per_class": {
                n: {
                    "expected_present": c.expected_present, "expected_absent": c.expected_absent, "reported": c.reported,
                    "correct": c.correct, "hallucinated": c.hallucinated,
                    "precision_bp": bp(c.correct, c.reported), "recall_bp": bp(c.correct, c.expected_present),
                }
                for n, c in self.per_class.items()
            },
        }


def score(pairs: Sequence[tuple[LabelledItem, ParsedAnalysis]]) -> Metrics:
    counts = {n: [0, 0, 0, 0, 0] for n in ATTRIBUTE_NAMES}  # present, absent, reported, correct, hallucinated
    failed = numeral = 0
    for item, parsed in pairs:
        if parsed.outcome is AnalysisOutcome.FAILED:
            failed += 1
        if parsed.digit_discards:
            numeral += 1
        got = {a.name: a.value for a in parsed.attributes}
        for name in ATTRIBUTE_NAMES:
            c = counts[name]
            expected = item.labels[name]
            value = got.get(name) if parsed.outcome is not AnalysisOutcome.FAILED else None
            if expected is None:
                c[1] += 1
                if value is not None:
                    c[2] += 1
                    c[4] += 1
            else:
                c[0] += 1
                if value is not None:
                    c[2] += 1
                    if dedupe_key(value) == dedupe_key(expected):
                        c[3] += 1
    return Metrics(len(pairs), failed, numeral, {n: ClassCounts(*c) for n, c in counts.items()})


@dataclass(frozen=True, slots=True)
class Verdict:
    passed: bool
    failures: tuple[str, ...]


def judge(metrics: Metrics, bar: Bar) -> Verdict:
    f: list[str] = []
    if metrics.items < bar.min_items:
        f.append(f"only {metrics.items} item(s); the bar requires at least {bar.min_items}")
    if metrics.absent_total == 0:
        f.append("no 'not present' labels: hallucination cannot be measured")
    elif metrics.hallucinated_total * BP > bar.max_hallucination_bp * metrics.absent_total:
        f.append("hallucination rate exceeds the bar")
    if metrics.items and metrics.numeral_items * BP > bar.max_numeral_reliance_bp * metrics.items:
        f.append("numeral reliance exceeds the bar")
    for cls in ATTRIBUTE_NAMES:
        c, cb = metrics.per_class[cls], bar.per_class[cls]
        if c.expected_present == 0:
            f.append(f"{cls}: no positive examples")
            continue
        if c.reported == 0 or c.correct * BP < cb.min_precision_bp * c.reported:
            f.append(f"{cls}: precision below the bar")
        if c.correct * BP < cb.min_recall_bp * c.expected_present:
            f.append(f"{cls}: recall below the bar")
    return Verdict(not f, tuple(f))
