"""Evaluation maths and the bar (spec §6.2.1; P6 decision 13): integers only, no default bar, no evidence = fail."""

from __future__ import annotations

import copy

import pytest

from slim_cmo.vision.eval import BP, Bar, BarInvalid, DatasetInvalid, judge, parse_bar, score, validate_item
from slim_cmo.vision.parse import parse_analysis
from slim_cmo.vision.schema import ATTRIBUTE_NAMES, SCHEMA_VERSION

CLASS_BAR = {"min_precision_bp": 8000, "min_recall_bp": 5000}
BAR_DOC = {"name": "test-bar-v1", "min_items": 2, "max_hallucination_bp": 2000, "max_numeral_reliance_bp": 5000, "per_class": {n: dict(CLASS_BAR) for n in ATTRIBUTE_NAMES}}


def bar(**over) -> Bar:
    doc = copy.deepcopy(BAR_DOC)
    doc.update(over)
    return parse_bar(doc)


def item(item_id, **labels):
    return validate_item(item_id, {n: labels.get(n) for n in ATTRIBUTE_NAMES})


def reply(**values):
    import json

    return parse_analysis(json.dumps({n: values.get(n) for n in ATTRIBUTE_NAMES}), SCHEMA_VERSION)


def perfect_pairs():
    return [(item("a", color="blue", brand="AquaKeep"), reply(color="blue", brand="AquaKeep")),
            (item("b", color="red", brand="Zed"), reply(color="Red", brand="zed"))]


class TestBarIsRequiredAndComplete:
    def test_a_complete_bar_parses(self):
        b = bar()
        assert b.name == "test-bar-v1" and b.min_items == 2 and set(b.per_class) == set(ATTRIBUTE_NAMES)

    @pytest.mark.parametrize("obj", [None, [], "bar", 5])
    def test_a_non_object_is_refused(self, obj):
        with pytest.raises(BarInvalid):
            parse_bar(obj)

    @pytest.mark.parametrize("key", ["name", "min_items", "max_hallucination_bp", "max_numeral_reliance_bp", "per_class"])
    def test_every_top_level_threshold_is_required(self, key):
        doc = copy.deepcopy(BAR_DOC)
        del doc[key]
        with pytest.raises(BarInvalid) as caught:
            parse_bar(doc)
        assert key in " ".join(caught.value.problems)

    @pytest.mark.parametrize("cls", ATTRIBUTE_NAMES)
    @pytest.mark.parametrize("key", ["min_precision_bp", "min_recall_bp"])
    def test_every_class_threshold_is_required(self, cls, key):
        doc = copy.deepcopy(BAR_DOC)
        del doc["per_class"][cls][key]
        with pytest.raises(BarInvalid):
            parse_bar(doc)

    def test_a_missing_class_or_an_unknown_class_is_refused(self):
        doc = copy.deepcopy(BAR_DOC)
        del doc["per_class"]["color"]
        with pytest.raises(BarInvalid):
            parse_bar(doc)
        doc = copy.deepcopy(BAR_DOC)
        doc["per_class"]["weight"] = dict(CLASS_BAR)
        with pytest.raises(BarInvalid):
            parse_bar(doc)

    @pytest.mark.parametrize("bad", [True, 10001, -1, 0.5, "8000", None])
    def test_thresholds_are_integer_basis_points_in_range(self, bad):
        doc = copy.deepcopy(BAR_DOC)
        doc["max_hallucination_bp"] = bad
        with pytest.raises(BarInvalid):
            parse_bar(doc)

    def test_all_problems_are_reported_at_once(self):
        with pytest.raises(BarInvalid) as caught:
            parse_bar({"name": "x"})
        assert len(caught.value.problems) >= 4


class TestDatasetLabels:
    def test_every_field_must_be_labelled_even_if_null(self):
        with pytest.raises(DatasetInvalid):
            validate_item("x", {"color": "blue"})
        with pytest.raises(DatasetInvalid):
            validate_item("x", {**{n: None for n in ATTRIBUTE_NAMES}, "extra": None})
        with pytest.raises(DatasetInvalid):
            validate_item("x", {**{n: None for n in ATTRIBUTE_NAMES}, "color": "  "})
        with pytest.raises(DatasetInvalid):
            validate_item("x", "labels")


class TestScoring:
    def test_counts_and_basis_points_are_exact_integers(self):
        pairs = [(item("a", color="blue"), reply(color="blue")), (item("b", color="red"), reply(color="green")), (item("c"), reply(color="blue")),
                 (item("d", color="pink"), reply())]
        m = score(pairs)
        c = m.per_class["color"]
        assert (c.expected_present, c.expected_absent, c.reported, c.correct, c.hallucinated) == (3, 1, 3, 1, 1)
        j = m.to_json()
        assert j["per_class"]["color"]["precision_bp"] == 3333 and j["per_class"]["color"]["recall_bp"] == 3333 and j["hallucination_bp"] is not None
        assert all(isinstance(v, int) or v is None for v in (j["numeral_reliance_bp"], j["hallucination_bp"]))
        assert "." not in str(j["per_class"]["color"]["precision_bp"])

    def test_hallucination_is_a_value_for_a_field_labelled_not_present(self):
        pairs = [(item("a"), reply(color="blue", material="steel")), (item("b"), reply())]
        m = score(pairs)
        assert m.hallucinated_total == 2 and m.absent_total == 12 and m.to_json()["hallucination_bp"] == 2 * BP // 12

    def test_a_failed_parse_counts_as_misses_not_reports(self):
        pairs = [(item("a", color="blue"), parse_analysis("garbage", SCHEMA_VERSION))]
        m = score(pairs)
        assert m.failed_items == 1 and m.per_class["color"].reported == 0 and m.per_class["color"].expected_present == 1

    def test_digit_reliance_is_measured_before_the_policy_discards_the_value(self):
        import json

        digits = parse_analysis(json.dumps({**{n: None for n in ATTRIBUTE_NAMES}, "size": "500 ml"}), SCHEMA_VERSION)
        m = score([(item("a", size="large"), digits), (item("b", size="small"), reply(size="small"))])
        assert m.numeral_items == 1 and m.to_json()["numeral_reliance_bp"] == 5000

    def test_matching_ignores_case_spacing_and_punctuation_only(self):
        m = score([(item("a", brand="Aqua Keep"), reply(brand="aqua  keep!"))])
        assert m.per_class["brand"].correct == 1
        assert score([(item("a", brand="Aqua Keep"), reply(brand="AquaKeep"))]).per_class["brand"].correct == 0


class TestJudge:
    def dataset(self):
        pairs = []
        for i in range(4):
            labels = {n: f"v{n}" if n in ("color", "material", "size", "brand", "product_type", "visible_text") else None for n in ATTRIBUTE_NAMES}
            pairs.append((validate_item(f"p{i}", labels), reply(**{n: f"v{n}".replace("_", " ") for n in ATTRIBUTE_NAMES})))
        pairs.append((item("absent"), reply()))
        return pairs

    def test_a_clean_run_passes(self):
        pairs = self.dataset()
        # every class has positives; the absent item gives hallucination evidence
        verdict = judge(score(pairs), bar(min_items=5))
        assert verdict.passed, verdict.failures

    def test_min_items_is_enforced(self):
        assert "at least" in " ".join(judge(score(self.dataset()), bar(min_items=99)).failures)

    def test_no_not_present_labels_means_hallucination_is_unmeasurable_and_fails(self):
        pairs = [(validate_item("a", {n: f"x{n}".replace("_", " ") for n in ATTRIBUTE_NAMES}), reply(**{n: f"x{n}".replace("_", " ") for n in ATTRIBUTE_NAMES}))]
        assert "cannot be measured" in " ".join(judge(score(pairs), bar(min_items=1)).failures)

    def test_a_class_with_no_positive_examples_fails(self):
        pairs = [(item("a", color="blue"), reply(color="blue"))]
        assert any("no positive examples" in f for f in judge(score(pairs), bar(min_items=1)).failures)

    def test_hallucination_boundary_is_exact_integer_arithmetic(self):
        # 12 absent slots across 2 items; 2 hallucinated = 1666 bp (floor), but the check is cross-multiplied: 2*10000 > 1666*12
        pairs = [(item("a"), reply(color="blue", material="steel")), (item("b"), reply())]
        assert any("hallucination" in f for f in judge(score(pairs), bar(min_items=1, max_hallucination_bp=1666)).failures)
        assert not any("hallucination" in f for f in judge(score(pairs), bar(min_items=1, max_hallucination_bp=1667)).failures)

    def test_precision_and_recall_floors_are_enforced_per_class(self):
        pairs = [(item("a", color="blue"), reply(color="green")), (item("b"), reply())]
        failures = " ".join(judge(score(pairs), bar(min_items=1)).failures)
        assert "color: precision below" in failures and "color: recall below" in failures

    def test_a_model_that_reports_nothing_cannot_pass_by_having_no_false_positives(self):
        pairs = [(validate_item("a", {n: "x" for n in ATTRIBUTE_NAMES}), reply()), (item("b"), reply())]
        verdict = judge(score(pairs), bar(min_items=1))
        assert not verdict.passed and any("precision below" in f for f in verdict.failures)

    def test_numeral_reliance_is_capped_by_the_bar(self):
        import json

        digits = parse_analysis(json.dumps({**{n: None for n in ATTRIBUTE_NAMES}, "size": "500 ml"}), SCHEMA_VERSION)
        pairs = [(item("a"), digits), (item("b"), digits)]
        assert any("numeral" in f for f in judge(score(pairs), bar(min_items=1, max_numeral_reliance_bp=0)).failures)

    def test_no_default_bar_exists_in_code(self):
        with pytest.raises(TypeError):
            Bar()  # type: ignore[call-arg]
