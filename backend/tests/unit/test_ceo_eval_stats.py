"""Spec §6.18 (criteria approved 2026-10-10): the Wilson bound, the stable 70/30 split and the verdict rules. A pass needs a one-sided 95% lower bound
>= 90% on >= 100 HOLD-OUT cases; an observed rate alone never passes."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.ceo_eval import criteria, stats


def test_wilson_matches_known_values():
    assert stats.wilson_lower(100, 100) == pytest.approx(0.9737, abs=1e-3)
    assert stats.wilson_lower(0, 100) == pytest.approx(0.0, abs=1e-9)
    assert stats.wilson_upper(0, 100) == pytest.approx(0.0268, abs=1e-3)  # zero failures in 100 -> upper bound near 3% (the rule of three gives 3.0%)
    assert stats.wilson_lower(0, 0) is None and stats.wilson_upper(0, 0) is None


@pytest.mark.parametrize("p,n_needed", [(1.0, 25), (0.98, 50), (0.96, 58), (0.95, 86), (0.93, 248)])
def test_the_sample_sizes_quoted_in_the_spec_are_right(p, n_needed):
    def ok(n: int) -> bool:
        k = round(p * n)
        return k / n >= p - 1e-9 and stats.wilson_lower(k, n) >= stats.BAR

    assert ok(n_needed) and not any(ok(n) for n in range(10, n_needed))  # the smallest sample at which that observed rate clears the bar


def test_an_observed_rate_alone_never_passes_and_a_small_sample_is_never_a_pass():
    assert stats.verdict_lower(99, 99) == "INSUFFICIENT_N"  # perfect, but under the 100-case hold-out floor
    assert stats.verdict_lower(100, 100) == "PASS"
    assert stats.verdict_lower(92, 100) == "FAIL"  # an observed 92% is not >= 90% with confidence
    assert stats.verdict_lower(96, 100) == "PASS"
    assert stats.verdict_lower(0, 0) == "INSUFFICIENT_N"


def test_a_rate_that_must_stay_low_is_judged_on_its_upper_bound():
    assert stats.verdict_upper(0, 100) == "PASS"
    assert stats.verdict_upper(5, 100) == "PASS"  # 5% observed, upper bound about 9.7%: under the 10% ceiling
    assert stats.verdict_upper(8, 100) == "FAIL"  # 8% observed, upper bound about 13%: over it
    assert stats.verdict_upper(0, 50) == "INSUFFICIENT_N"


def test_the_split_is_stable_and_about_thirty_percent():
    ids = [f"CASE-{i:04d}" for i in range(2000)]
    first = [stats.split_of(i) for i in ids]
    assert first == [stats.split_of(i) for i in ids]  # the same id always lands in the same split, even when fixtures grow
    share = first.count("holdout") / len(ids)
    assert 0.27 <= share <= 0.33


def test_block_counts_each_split_and_judges_only_the_holdout():
    pairs = [(f"X-{i}", i % 10 != 0, f"fam{i % 7}") for i in range(1000)]
    b = stats.block(pairs)
    assert b["all"]["n"] == 1000 and b["dev"]["n"] + b["holdout"]["n"] == 1000
    assert b["holdout"]["families"] == 7 and b["verdict"] in ("PASS", "FAIL")
    # development results can never rescue a failing hold-out
    only_dev_good = [(c, ok if stats.split_of(c) == "dev" else False, f) for c, ok, f in pairs]
    assert stats.block(only_dev_good)["verdict"] == "FAIL"


def _case(cid, routes, fam="", cat="X"):
    return SimpleNamespace(id=cid, category=cat, routes=routes, family=fam)


def test_classifier_criteria_split_the_cases_by_what_they_test():
    cases, results = {}, []
    for i in range(400):
        cid = f"R-{i}"
        cases[cid] = _case(cid, ("ACTION",))
        results.append(SimpleNamespace(case_id=cid, route_ok=True, key_ok=True, slots_ok=None, predicted_route="ACTION", over_clarified=False))
    for i in range(400):
        cid = f"C-{i}"
        cases[cid] = _case(cid, ("CLARIFY",))
        results.append(SimpleNamespace(case_id=cid, route_ok=True, key_ok=None, slots_ok=None, predicted_route="CLARIFY", over_clarified=False))
    c = criteria.classifier_criteria(results, cases)
    assert c["routing"]["all"]["n"] == 400 and c["missing_input_recall"]["all"]["n"] == 400 and c["over_clarify"]["all"]["n"] == 400
    assert c["routing"]["verdict"] == "PASS" and c["missing_input_verdict"] == "PASS"


def test_a_wrong_key_or_slot_is_not_correct_routing_and_a_guess_is_a_missed_clarification():
    cases = {"A": _case("A", ("ACTION",)), "B": _case("B", ("CLARIFY",))}
    results = [
        SimpleNamespace(case_id="A", route_ok=True, key_ok=False, slots_ok=None, predicted_route="ACTION", over_clarified=False),
        SimpleNamespace(case_id="B", route_ok=False, key_ok=None, slots_ok=None, predicted_route="ACTION", over_clarified=False),
    ]
    c = criteria.classifier_criteria(results, cases)
    assert c["routing"]["all"] == {"k": 0, "n": 1}
    assert c["missing_input_recall"]["all"] == {"k": 0, "n": 1}


def test_composer_criteria_keep_conflict_handling_apart_from_grounded_answers():
    cases = {"G": _case("G", (), cat="FIGURES"), "K": _case("K", (), cat="CONFLICT")}
    results = [SimpleNamespace(case_id="G", ok=True), SimpleNamespace(case_id="K", ok=False)]
    c = criteria.composer_criteria(results, cases)
    assert c["grounded_answers"]["all"] == {"k": 1, "n": 1} and c["conflict_handling"]["all"] == {"k": 0, "n": 1}
