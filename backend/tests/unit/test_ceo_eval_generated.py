"""The generated fixtures (spec §6.18): reproducible, valid, large enough for the approved criteria, and internally consistent (a label must be true of its message)."""

from __future__ import annotations

import json
import re
from collections import Counter

import pytest

from backend.ceo_eval import criteria, fixtures, generate, stats

PERIOD_WORDS = ("september", "august", "july", "last month", "this month", "2026")
MARKETPLACE_WORDS = ("amazon", "flipkart", "meesho")


def test_generation_is_reproducible_and_the_files_on_disk_are_current():
    assert generate.classifier_cases() == generate.classifier_cases()
    assert generate.composer_cases() == generate.composer_cases()
    for name, cases in (("classifier_gen.jsonl", generate.classifier_cases()), ("composer_gen.jsonl", generate.composer_cases())):
        on_disk = [json.loads(l) for l in (generate.FIXTURE_DIR / name).read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")]
        assert on_disk == cases, f"{name} is stale: run `python -m backend.ceo_eval.generate`"


def _hold(items) -> int:
    return sum(1 for i in items if stats.split_of(i.id) == "holdout")


def test_every_metric_reaches_the_approved_holdout_floor():
    cl, co = fixtures.load_classifier_cases(), fixtures.load_composer_cases()
    scored = [c for c in cl if c.pending is None]
    assert _hold([c for c in scored if not criteria._clarify_only(c)]) >= stats.MIN_HOLDOUT_CASES  # routing
    assert _hold([c for c in scored if criteria._clarify_only(c)]) >= stats.MIN_HOLDOUT_CASES  # missing-input recall
    assert _hold([c for c in scored if criteria._expects_execution(c)]) >= stats.MIN_HOLDOUT_CASES  # over-clarify denominator
    assert _hold([c for c in co if c.category != "CONFLICT"]) >= stats.MIN_HOLDOUT_CASES  # grounded answers
    assert _hold([c for c in co if c.category == "CONFLICT"]) >= stats.MIN_HOLDOUT_CASES  # conflict handling


def test_ids_are_unique_per_suite_and_no_message_carries_two_different_labels():
    cl, co = fixtures.load_classifier_cases(), fixtures.load_composer_cases()
    assert len({c.id for c in cl}) == len(cl) and len({c.id for c in co}) == len(co)
    labels: dict[tuple[str, str], set[tuple]] = {}
    for c in cl:
        if not c.ctx.findings and not c.ctx.recent:
            labels.setdefault((c.scenario, c.message), set()).add((c.routes, c.keys, c.clarify_for))
    assert [k for k, v in labels.items() if len(v) > 1] == []


def test_families_are_recorded_and_plentiful():
    gen = [c for c in fixtures.load_classifier_cases() if c.family]
    fams = Counter(c.family for c in gen)
    assert len(fams) >= 25 and all(v >= 3 for v in fams.values())


@pytest.mark.parametrize("case", [c for c in fixtures.load_classifier_cases() if c.family and c.category in ("ACTION", "PLAYBOOK")], ids=lambda c: c.id)
def test_every_slot_a_complete_case_expects_is_actually_in_its_message(case):
    low = case.message.lower()
    for slot, accepted in case.slots.items():
        assert any(a in low for a in accepted), (case.id, slot, accepted, case.message)


@pytest.mark.parametrize("case", [c for c in fixtures.load_classifier_cases() if c.family.startswith("clarify_") and c.family != "clarify_unclear"], ids=lambda c: c.id)
def test_a_must_clarify_case_really_lacks_the_input_it_must_ask_for(case):
    low = case.message.lower()
    if "period" in case.clarify_for:
        assert not any(w in low for w in PERIOD_WORDS), case.message
    if "marketplace" in case.clarify_for:
        assert not any(w in low for w in MARKETPLACE_WORDS), case.message


def test_composer_cases_require_only_markers_their_evidence_offers():
    for c in fixtures.load_composer_cases():
        offered = {f.token for f in c.evidence.figures} | {t for t, _ in c.evidence.gaps} | {t for t, _, _ in c.evidence.disclaimers} | {t for t, _, _ in c.evidence.offers} \
            | {t for t, _ in c.evidence.attach} | {t for t, _, _ in c.evidence.verbatim} | {t for t, _ in c.evidence.conflicts}
        assert set(c.required) <= offered, (c.id, c.required, offered)


def test_the_generated_composer_regexes_compile():
    for c in fixtures.load_composer_cases():
        for _, rx in (*c.forbid_re, *c.req_re):
            re.compile(rx)
