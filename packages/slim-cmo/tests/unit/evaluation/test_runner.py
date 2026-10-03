"""The vision evaluation runner (P6 decision 13): refuses without operator, labelled dataset and a complete bar; an
outage never records a failing run; images and replies go through the SAME normaliser and parser as production."""

from __future__ import annotations

import json
import uuid

import pytest
from PIL import Image

from slim_cmo.evaluation.runner import EvalRefused, load_bar, load_dataset, run_evaluation
from slim_cmo.vision.provider import ScriptedVisionProvider, VisionUnavailable
from slim_cmo.vision.schema import ATTRIBUTE_NAMES, SCHEMA_VERSION

from ..imagehelpers import LIMITS, SECRET, jpeg_with_exif

CLASS_BAR = {"min_precision_bp": 8000, "min_recall_bp": 5000}
BAR = {"name": "test-bar", "min_items": 2, "max_hallucination_bp": 2000, "max_numeral_reliance_bp": 5000, "per_class": {n: dict(CLASS_BAR) for n in ATTRIBUTE_NAMES}}
LABELS = {n: f"v {n}".replace("_", " ") for n in ATTRIBUTE_NAMES}
GOOD_REPLY = json.dumps({n: f"v {n}".replace("_", " ") for n in ATTRIBUTE_NAMES})


class Writer:
    def __init__(self):
        self.rows = []

    def write(self, **kw):
        self.rows.append(kw)
        return uuid.uuid4()


def build(tmp_path, items=3, absent_item=True, bar=None, labels=None):
    ds = tmp_path / "ds"
    ds.mkdir()
    entries = []
    for i in range(items):
        name = f"img{i}.jpg"
        (ds / name).write_bytes(jpeg_with_exif())
        entries.append({"id": f"i{i}", "image": name, "labels": dict(labels or LABELS)})
    if absent_item:
        (ds / "empty.png").write_bytes(b"")
        Image.new("RGB", (10, 10)).save(ds / "empty.png")
        entries.append({"id": "absent", "image": "empty.png", "labels": {n: None for n in ATTRIBUTE_NAMES}})
    (ds / "manifest.json").write_text(json.dumps({"name": "synthetic", "version": "1", "items": entries}))
    bar_path = tmp_path / "bar.json"
    bar_path.write_text(json.dumps(bar or BAR))
    return ds, bar_path


def go(tmp_path, replies, **kw):
    ds, bar = build(tmp_path, **{k: kw.pop(k) for k in ("items", "absent_item", "labels") if k in kw}, bar=kw.pop("bar", None))
    provider = ScriptedVisionProvider(replies)
    writer = Writer()
    args = dict(provider=provider, provider_name="ollama", model="m", schema_version=SCHEMA_VERSION, run_by="Asha Rao",
                dataset_dir=ds, bar_path=bar, limits=LIMITS, writer=writer)
    args.update(kw)
    return run_evaluation(**args), provider, writer


def empties(n):
    return [json.dumps({k: None for k in ATTRIBUTE_NAMES})] * n


class TestRefusals:
    @pytest.mark.parametrize("run_by", ["", " ", "x", None])
    def test_a_named_human_operator_is_required(self, tmp_path, run_by):
        ds, bar = build(tmp_path)
        w = Writer()
        with pytest.raises(EvalRefused):
            run_evaluation(provider=ScriptedVisionProvider([]), provider_name="ollama", model="m", schema_version=SCHEMA_VERSION, run_by=run_by,  # type: ignore[arg-type]
                           dataset_dir=ds, bar_path=bar, limits=LIMITS, writer=w)
        assert w.rows == []

    def test_no_bar_means_no_run(self, tmp_path):
        ds, _ = build(tmp_path)
        provider = ScriptedVisionProvider([GOOD_REPLY])
        w = Writer()
        with pytest.raises(EvalRefused, match="no bar"):
            run_evaluation(provider=provider, provider_name="ollama", model="m", schema_version=SCHEMA_VERSION, run_by="Asha Rao", dataset_dir=ds, bar_path=None, limits=LIMITS, writer=w)
        assert provider.calls == 0 and w.rows == []

    def test_a_missing_or_unreadable_bar_file_or_an_incomplete_bar(self, tmp_path):
        with pytest.raises(EvalRefused):
            load_bar(tmp_path / "nope.json")
        bad = tmp_path / "bad.json"
        bad.write_text("{not json")
        with pytest.raises(EvalRefused):
            load_bar(bad)
        bad.write_text(json.dumps({"name": "x"}))
        with pytest.raises(EvalRefused, match="invalid"):
            load_bar(bad)

    def test_no_dataset_means_no_run(self, tmp_path):
        _, bar = build(tmp_path)
        w = Writer()
        with pytest.raises(EvalRefused, match="no labelled dataset"):
            run_evaluation(provider=ScriptedVisionProvider([]), provider_name="ollama", model="m", schema_version=SCHEMA_VERSION, run_by="Asha Rao", dataset_dir=None, bar_path=bar, limits=LIMITS, writer=w)

    @pytest.mark.parametrize("manifest", [None, "{not json", json.dumps({"items": []}), json.dumps({"name": "n", "items": [{"id": "a", "image": "x.png", "labels": {}}]}),
                                          json.dumps({"name": "n", "version": "1", "items": [{"id": "a", "image": "x.png", "labels": {"color": "blue"}}]}),
                                          json.dumps({"name": "n", "version": "1", "items": [{"id": "a", "image": "../outside.png", "labels": {k: None for k in ATTRIBUTE_NAMES}}]}),
                                          json.dumps({"name": "n", "version": "1", "items": [{"id": "a", "image": "x.png", "labels": {k: None for k in ATTRIBUTE_NAMES}}] * 2})])
    def test_an_unusable_dataset_is_refused(self, tmp_path, manifest):
        d = tmp_path / "d"
        d.mkdir()
        if manifest is not None:
            (d / "manifest.json").write_text(manifest)
        with pytest.raises(EvalRefused):
            load_dataset(d)

    def test_an_unsupported_schema_version_and_empty_identity_are_refused(self, tmp_path):
        ds, bar = build(tmp_path)
        for kw in (dict(schema_version="cmo-vision-v0"), dict(model=" "), dict(provider_name="")):
            args = dict(provider=ScriptedVisionProvider([]), provider_name="ollama", model="m", schema_version=SCHEMA_VERSION, run_by="Asha Rao", dataset_dir=ds, bar_path=bar, limits=LIMITS, writer=Writer())
            args.update(kw)
            with pytest.raises(EvalRefused):
                run_evaluation(**args)  # type: ignore[arg-type]

    def test_an_unreadable_image_or_a_rejected_one_refuses_the_whole_run(self, tmp_path):
        ds, bar = build(tmp_path)
        (ds / "img0.jpg").write_bytes(b"not an image")
        w = Writer()
        with pytest.raises(EvalRefused, match="rejected"):
            run_evaluation(provider=ScriptedVisionProvider([GOOD_REPLY] * 4), provider_name="ollama", model="m", schema_version=SCHEMA_VERSION, run_by="Asha Rao", dataset_dir=ds, bar_path=bar, limits=LIMITS, writer=w)
        assert w.rows == []


class TestOutageIsNotAFailingEvaluation:
    def test_a_provider_failure_aborts_without_recording_anything(self, tmp_path):
        replies = [GOOD_REPLY, VisionUnavailable("down"), GOOD_REPLY, GOOD_REPLY]
        ds, bar = build(tmp_path)
        w = Writer()
        with pytest.raises(EvalRefused, match="outage is not a failing evaluation"):
            run_evaluation(provider=ScriptedVisionProvider(replies), provider_name="ollama", model="m", schema_version=SCHEMA_VERSION, run_by="Asha Rao", dataset_dir=ds, bar_path=bar, limits=LIMITS, writer=w)
        assert w.rows == []  # nothing recorded: trust is neither granted nor revoked by an outage


class TestRecordedRuns:
    def test_a_passing_run_is_recorded_with_provenance(self, tmp_path):
        report, provider, w = go(tmp_path, [GOOD_REPLY] * 3 + empties(1))
        assert report.passed and report.failures == ()
        row = w.rows[0]
        assert (row["provider"], row["model"], row["schema_version"], row["run_by"], row["passed"]) == ("ollama", "m", SCHEMA_VERSION, "Asha Rao", True)
        assert row["dataset_ref"] == "synthetic@1" and row["bar_ref"].startswith("test-bar@") and len(row["bar_ref"].split("@")[1]) == 16
        assert row["metrics"]["dataset_items"] == 4 and row["metrics"]["bar_name"] == "test-bar" and row["metrics"]["hallucination_bp"] == 0

    def test_a_failing_run_is_recorded_as_failed_with_its_reasons(self, tmp_path):
        wrong = json.dumps({n: "wrong value" for n in ATTRIBUTE_NAMES})
        report, _p, w = go(tmp_path, [wrong] * 3 + [wrong])
        assert not report.passed and w.rows[0]["passed"] is False
        assert any("precision below" in f for f in w.rows[0]["metrics"]["failures"]) and any("hallucination" in f for f in w.rows[0]["metrics"]["failures"])

    def test_a_hallucinating_model_fails_on_the_not_present_item(self, tmp_path):
        report, _p, _w = go(tmp_path, [GOOD_REPLY] * 3 + [GOOD_REPLY], bar={**BAR, "max_hallucination_bp": 0})
        assert not report.passed and any("hallucination" in f for f in report.failures)

    def test_images_reach_the_provider_normalised_and_the_original_metadata_never_does(self, tmp_path):
        _r, provider, _w = go(tmp_path, [GOOD_REPLY] * 3 + empties(1))
        assert provider.calls == 4
        for image in provider.images:
            assert image.content_type == "image/png" and image.data.startswith(b"\x89PNG") and SECRET not in image.data and b"Exif" not in image.data

    def test_replies_are_judged_after_the_production_policy_filter(self, tmp_path):
        digits = json.dumps({**{n: f"v {n}".replace("_", " ") for n in ATTRIBUTE_NAMES}, "size": "500 ml"})  # digit-bearing size is discarded
        report, _p, w = go(tmp_path, [digits] * 3 + empties(1))
        assert w.rows[0]["metrics"]["numeral_items"] == 3 and w.rows[0]["metrics"]["per_class"]["size"]["reported"] == 0
        assert not report.passed and any("size: precision" in f for f in report.failures)

    def test_the_bar_ref_identifies_the_exact_bar_file(self, tmp_path):
        a, _p, _w = go(tmp_path, [GOOD_REPLY] * 3 + empties(1))
        other = tmp_path.parent / (tmp_path.name + "_2")
        other.mkdir()
        b, _p2, _w2 = go(other, [GOOD_REPLY] * 3 + empties(1), bar={**BAR, "max_numeral_reliance_bp": 4000})
        assert a.bar_ref != b.bar_ref and a.bar_ref.split("@")[0] == b.bar_ref.split("@")[0]

    def test_the_runner_has_no_default_bar_dataset_or_operator(self):
        import inspect

        params = inspect.signature(run_evaluation).parameters
        for name in ("run_by", "dataset_dir", "bar_path", "provider_name", "model", "limits", "writer"):
            assert params[name].default is inspect.Parameter.empty, name
