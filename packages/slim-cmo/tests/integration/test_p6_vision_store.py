"""P6 persistence and the trust gate against a real Postgres (skipped without DATABASE_URL / DATABASE_URL_APP)."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, ProgrammingError

from slim_cmo.catalog.attributes import CatalogAttribute as C
from slim_cmo.claims import EligibilityReason
from slim_cmo.evaluation.db import PostgresEvalWriter
from slim_cmo.evaluation.runner import run_evaluation
from slim_cmo.generation.facts import build_fact_context, image_attributes
from slim_cmo.repositories.postgres_image_store import PostgresImageStore
from slim_cmo.repositories.postgres_store import PostgresGenerationStore
from slim_cmo.repositories.tenant_context import tenant_scope
from slim_cmo.service.catalog import CatalogRequest, CatalogService
from slim_cmo.service.generate import Intake
from slim_cmo.service.models import Actor, AnalysisRecord, DuplicateAnalysis
from slim_cmo.service.vision import ImageService
from slim_cmo.storage.local_disk import LocalDiskImageStore
from slim_cmo.types import ImageAnalysisState as S
from slim_cmo.vision.provider import ScriptedVisionProvider, VisionUnavailable
from slim_cmo.vision.schema import ATTRIBUTE_NAMES, SCHEMA_VERSION

from ..unit.imagehelpers import LIMITS, SECRET, jpeg_with_exif, png_bytes
from . import _seed

MODEL = "it-vision"
GOOD = json.dumps({"color": "matte blue", "material": "steel", "size": "large", "brand": "AquaKeep", "product_type": "bottle", "visible_text": "Stay hydrated"})


def svc(tmp_path, replies=(GOOD,), model=MODEL):
    store = PostgresImageStore()
    provider = ScriptedVisionProvider(replies)
    return ImageService(store, LocalDiskImageStore(str(tmp_path)), limits=LIMITS, provider=provider, provider_name="ollama", model=model,
                        clock=lambda: datetime.now(UTC)), store, provider


def eval_run(engine, passed, model=MODEL, run_at=None):
    rid = _seed.insert_vision_eval_run(engine, provider="ollama", model=model, schema_version=SCHEMA_VERSION, passed=passed)
    if run_at is not None:
        with engine.begin() as conn:
            conn.execute(text("UPDATE vision_eval_run SET run_at = :t WHERE id = :i"), {"t": run_at, "i": str(rid)})
    return rid


def raw_attributes(tenant, analysis_id):
    with tenant_scope(tenant) as conn:
        return conn.execute(text("SELECT attributes, eval_gate_ref, analysis_state, degraded_reason FROM product_image_analysis WHERE tenant_id=:t AND id=:i"),
                            {"t": tenant, "i": analysis_id}).one()


def asset_of(service, actor, data=None):
    return service.upload(actor, data or jpeg_with_exif(), "image/jpeg").asset_id


class TestUploadPersistence:
    def test_assets_are_content_addressed_per_tenant(self, tmp_path):
        a, b = Actor(uuid.uuid4(), uuid.uuid4()), Actor(uuid.uuid4(), uuid.uuid4())
        s, _store, _p = svc(tmp_path)
        first, again = s.upload(a, jpeg_with_exif(comment=True), "image/jpeg"), s.upload(a, jpeg_with_exif(comment=False), "image/jpeg")
        other_tenant = s.upload(b, jpeg_with_exif(), "image/jpeg")
        assert first.created and not again.created and first.asset_id == again.asset_id
        assert other_tenant.asset_id != first.asset_id and other_tenant.created
        with tenant_scope(a.tenant_id) as conn:
            row = conn.execute(text("SELECT content_type, byte_size, status, storage_uri FROM seller_image_asset WHERE tenant_id=:t"), {"t": a.tenant_id}).all()
        assert len(row) == 1 and row[0][0] == "image/png" and row[0][2] == "ACTIVE" and row[0][3].startswith(f"local://{a.tenant_id}/")
        for p in tmp_path.rglob("*"):
            if p.is_file():
                assert SECRET not in p.read_bytes()

    def test_an_asset_is_invisible_to_another_tenant(self, tmp_path):
        a, b = Actor(uuid.uuid4(), uuid.uuid4()), Actor(uuid.uuid4(), uuid.uuid4())
        s, store, _p = svc(tmp_path)
        asset = asset_of(s, a)
        assert store.load_asset(a.tenant_id, asset) is not None and store.load_asset(b.tenant_id, asset) is None


class TestAnalysisPersistenceAndGate:
    def test_a_closed_gate_persists_unverified_hints_with_no_gate_ref(self, tmp_path):
        a = Actor(uuid.uuid4(), uuid.uuid4())
        s, _store, _p = svc(tmp_path)
        res = s.analyze(a, asset_of(s, a))
        row = raw_attributes(a.tenant_id, res.analysis_id)
        assert row.eval_gate_ref is None and row.analysis_state == "COMPLETE"
        assert {x["trust_state"] for x in row.attributes} == {"UNVERIFIED_HINT"} and len(row.attributes) == len(ATTRIBUTE_NAMES)

    def test_a_passing_evaluation_opens_the_gate_and_the_database_accepts_the_citation(self, tmp_path, migrate_engine):
        a = Actor(uuid.uuid4(), uuid.uuid4())
        run = eval_run(migrate_engine, True)
        s, _store, _p = svc(tmp_path)
        res = s.analyze(a, asset_of(s, a))
        row = raw_attributes(a.tenant_id, res.analysis_id)
        assert row.eval_gate_ref == run and "EVAL_PASSED" in {x["trust_state"] for x in row.attributes} and res.trust_gate_open

    def test_a_passing_run_for_another_model_never_opens_it(self, tmp_path, migrate_engine):
        a = Actor(uuid.uuid4(), uuid.uuid4())
        eval_run(migrate_engine, True, model="some-other-model")
        s, _store, _p = svc(tmp_path)
        assert not s.analyze(a, asset_of(s, a)).trust_gate_open

    def test_the_database_still_refuses_forged_trust(self, tmp_path, migrate_engine):
        a = Actor(uuid.uuid4(), uuid.uuid4())
        s, store, _p = svc(tmp_path)
        asset = asset_of(s, a)
        passing = eval_run(migrate_engine, True, model="forge-pass")
        failing = eval_run(migrate_engine, False, model="forge-fail")
        passed_attrs = [{"name": "color", "value": "blue", "basis": "IMAGE_OBSERVED", "trust_state": "EVAL_PASSED"}]

        def rec(**kw):
            base = dict(image_asset_id=asset, provider="ollama", model=MODEL, schema_version=SCHEMA_VERSION, eval_gate_ref=None, attributes=passed_attrs,
                        analysis_state=S.COMPLETE, degraded_reason=None)
            base.update(kw)
            return AnalysisRecord(**base)

        for forged in (rec(), rec(eval_gate_ref=passing), rec(model="forge-fail", eval_gate_ref=failing), rec(model="forge-pass", eval_gate_ref=failing)):
            with pytest.raises(IntegrityError):
                store.save_analysis(a.tenant_id, forged)
        with pytest.raises(IntegrityError):
            store.save_analysis(a.tenant_id, rec(attributes=[{"name": "weight", "value": "350 g", "basis": "SELLER_PROVIDED", "trust_state": "UNVERIFIED_HINT"}]))
        store.save_analysis(a.tenant_id, rec(model="forge-pass", eval_gate_ref=passing))  # the legitimate form is accepted

    def test_complete_analyses_are_unique_per_asset_and_triple_but_failed_ones_are_not(self, tmp_path):
        a = Actor(uuid.uuid4(), uuid.uuid4())
        s, store, provider = svc(tmp_path, [VisionUnavailable("down"), VisionUnavailable("down"), GOOD])
        asset = asset_of(s, a)
        assert s.analyze(a, asset).state is S.FAILED and s.analyze(a, asset).state is S.FAILED
        ok = s.analyze(a, asset)
        assert ok.state is S.COMPLETE and not ok.reused
        again = s.analyze(a, asset)
        assert again.reused and again.analysis_id == ok.analysis_id and provider.calls == 3
        with pytest.raises(DuplicateAnalysis):
            store.save_analysis(a.tenant_id, AnalysisRecord(asset, "ollama", MODEL, SCHEMA_VERSION, None, [], S.COMPLETE, None))
        with tenant_scope(a.tenant_id) as conn:
            n = conn.execute(text("SELECT count(*) FROM product_image_analysis WHERE tenant_id=:t"), {"t": a.tenant_id}).scalar_one()
        assert n == 3

    def test_failed_and_degraded_analyses_persist_with_a_reason(self, tmp_path):
        a = Actor(uuid.uuid4(), uuid.uuid4())
        s, _store, _p = svc(tmp_path, ["garbage", '{"color": "blue"}'])
        asset = asset_of(s, a)
        failed, degraded = s.analyze(a, asset), s.analyze(a, asset)
        f, d = raw_attributes(a.tenant_id, failed.analysis_id), raw_attributes(a.tenant_id, degraded.analysis_id)
        assert (f.analysis_state, f.attributes, f.degraded_reason is not None) == ("FAILED", [], True)
        assert d.analysis_state == "DEGRADED" and d.degraded_reason and any(x["value"] == "blue" for x in d.attributes)

    def test_the_raw_reply_is_not_in_the_database(self, tmp_path):
        a = Actor(uuid.uuid4(), uuid.uuid4())
        reply = json.dumps({n: None for n in ATTRIBUTE_NAMES} | {"color": "blue", "visible_text": "RAW-MARKER 12345", "weight": "350 g", "notes": "RAW-NOTES"})
        s, _store, _p = svc(tmp_path, [reply])
        res = s.analyze(a, asset_of(s, a))
        with tenant_scope(a.tenant_id) as conn:
            blob = json.dumps([list(map(str, r)) for r in conn.execute(text("SELECT * FROM product_image_analysis WHERE tenant_id=:t"), {"t": a.tenant_id}).all()])
        for banned in ("RAW-MARKER", "RAW-NOTES", "350 g", "weight"):  # (no bare digit strings: they can occur inside random UUIDs)
            assert banned not in blob, banned
        assert res.state is S.COMPLETE

    def test_analyses_are_append_only_for_the_application_role(self, tmp_path):
        a = Actor(uuid.uuid4(), uuid.uuid4())
        s, _store, _p = svc(tmp_path)
        res = s.analyze(a, asset_of(s, a))
        for sql in ("UPDATE product_image_analysis SET analysis_state = 'FAILED'", "DELETE FROM product_image_analysis"):
            with pytest.raises(ProgrammingError):
                with tenant_scope(a.tenant_id) as conn:
                    conn.execute(text(sql))
        assert raw_attributes(a.tenant_id, res.analysis_id).analysis_state == "COMPLETE"

    def test_tenant_isolation_for_analysis(self, tmp_path):
        a, b = Actor(uuid.uuid4(), uuid.uuid4()), Actor(uuid.uuid4(), uuid.uuid4())
        s, store, provider = svc(tmp_path, [GOOD, GOOD])
        asset = asset_of(s, a)
        res = s.analyze(a, asset)
        from slim_cmo.service.errors import NotFound

        with pytest.raises(NotFound):
            s.analyze(b, asset)
        assert store.load_effective_analysis(b.tenant_id, res.analysis_id) is None and provider.calls == 1
        with pytest.raises(IntegrityError):  # the composite FK refuses another tenant's asset even for a hand-written row
            store.save_analysis(b.tenant_id, AnalysisRecord(asset, "ollama", MODEL, SCHEMA_VERSION, None, [], S.FAILED, "x"))

    def test_recent_analyses_are_counted_per_tenant(self, tmp_path):
        a, b = Actor(uuid.uuid4(), uuid.uuid4()), Actor(uuid.uuid4(), uuid.uuid4())
        s, store, _p = svc(tmp_path, [GOOD, VisionUnavailable("x")])
        s.analyze(a, asset_of(s, a))
        s.analyze(a, asset_of(s, a, jpeg_with_exif((50, 30))))
        since = datetime.now(UTC) - timedelta(minutes=5)
        assert store.count_recent_analyses(a.tenant_id, since) == 2 and store.count_recent_analyses(b.tenant_id, since) == 0
        assert store.count_recent_analyses(a.tenant_id, datetime.now(UTC) + timedelta(minutes=5)) == 0


class TestReadTimeRevocation:
    def test_a_later_failing_evaluation_revokes_trust_without_touching_the_stored_row(self, tmp_path, migrate_engine):
        a = Actor(uuid.uuid4(), uuid.uuid4())
        t0 = datetime.now(UTC) - timedelta(hours=3)
        eval_run(migrate_engine, True, run_at=t0)
        s, store, _p = svc(tmp_path)
        res = s.analyze(a, asset_of(s, a))
        assert res.trust_gate_open
        stored_before = raw_attributes(a.tenant_id, res.analysis_id)
        eval_run(migrate_engine, False, run_at=t0 + timedelta(hours=1))
        view = store.load_effective_analysis(a.tenant_id, res.analysis_id)
        assert view is not None and {x["trust_state"] for x in view.attributes} == {"UNVERIFIED_HINT"}
        assert tuple(raw_attributes(a.tenant_id, res.analysis_id)) == tuple(stored_before)  # immutable at rest
        assert "EVAL_PASSED" in json.dumps(stored_before.attributes)
        eval_run(migrate_engine, True, run_at=t0 + timedelta(hours=2))  # a newer pass restores it
        again = store.load_effective_analysis(a.tenant_id, res.analysis_id)
        assert again is not None and "EVAL_PASSED" in {x["trust_state"] for x in again.attributes}

    def test_p3_and_p4_consume_effective_trust_so_a_revoked_observation_is_never_a_claim(self, tmp_path, migrate_engine):
        a = Actor(uuid.uuid4(), uuid.uuid4())
        t0 = datetime.now(UTC) - timedelta(hours=3)
        eval_run(migrate_engine, True, run_at=t0)
        s, _store, _p = svc(tmp_path)
        res = s.analyze(a, asset_of(s, a))
        gstore, catalog = PostgresGenerationStore(), CatalogService(PostgresGenerationStore())

        def color_answer(key):
            run = catalog.answer(a, CatalogRequest(Intake(request_key=key, sku="S", image_analysis_id=res.analysis_id), (C.COLOR, C.WEIGHT)))
            with tenant_scope(a.tenant_id) as conn:
                structured = conn.execute(text("SELECT output_structured FROM cmo_generation WHERE tenant_id=:t AND id=:i"), {"t": a.tenant_id, "i": run.artefacts[0].generation_id}).scalar_one()
            return {x["attribute"]: x for x in structured["attributes"]}

        def eligible_names():
            analysis = gstore.load_image_analysis(a.tenant_id, res.analysis_id)
            ctx = build_fact_context([], image_attributes(analysis.attributes))  # exactly what P3 generation does
            return {x.name for x in ctx.eligible}, {r for _x, r in ctx.ineligible}

        trusted = color_answer("c1")
        assert (trusted["COLOR"]["basis"], trusted["COLOR"]["value"], trusted["COLOR"]["claim_eligible"]) == ("IMAGE_OBSERVED", "matte blue", True)
        assert trusted["WEIGHT"]["basis"] == "UNKNOWN" and trusted["WEIGHT"]["value"] is None
        names, _r = eligible_names()
        assert {"color", "material", "size", "brand", "product_type", "visible_text"} == names

        eval_run(migrate_engine, False, run_at=t0 + timedelta(hours=1))  # regression
        revoked = color_answer("c2")
        assert (revoked["COLOR"]["basis"], revoked["COLOR"]["value"]) == ("UNKNOWN", None) and revoked["COLOR"]["suggestion"]["value"] == "matte blue"
        names, reasons = eligible_names()
        assert names == set() and reasons == {EligibilityReason.UNVERIFIED_IMAGE_HINT}  # all six fields were observed, so every one is now a hint

    def test_confirming_a_hint_never_changes_the_analysis_even_after_revocation(self, tmp_path, migrate_engine):
        a = Actor(uuid.uuid4(), uuid.uuid4())
        s, _store, _p = svc(tmp_path)
        res = s.analyze(a, asset_of(s, a))
        before = tuple(raw_attributes(a.tenant_id, res.analysis_id))
        result = CatalogService(PostgresGenerationStore()).confirm_image_hint(a, analysis_id=res.analysis_id, attribute_name="color", sku="S1")
        assert result.created
        assert tuple(raw_attributes(a.tenant_id, res.analysis_id)) == before
        with tenant_scope(a.tenant_id) as conn:
            fact = conn.execute(text("SELECT fact_type, fact_value, image_analysis_id FROM seller_fact WHERE tenant_id=:t"), {"t": a.tenant_id}).one()
        assert tuple(fact) == ("ATTRIBUTE", "matte blue", res.analysis_id)


class TestEvaluationRecording:
    def test_the_operator_runner_writes_an_immutable_run_the_gate_then_reads(self, tmp_path, migrate_engine, app_engine):
        import os

        from PIL import Image

        ds = tmp_path / "ds"
        ds.mkdir()
        labels = {n: f"v {n}".replace("_", " ") for n in ATTRIBUTE_NAMES}
        entries = []
        for i in range(3):
            Image.new("RGB", (12 + i, 12)).save(ds / f"i{i}.png")
            entries.append({"id": f"i{i}", "image": f"i{i}.png", "labels": labels})
        Image.new("RGB", (9, 9)).save(ds / "none.png")
        entries.append({"id": "none", "image": "none.png", "labels": {n: None for n in ATTRIBUTE_NAMES}})
        (ds / "manifest.json").write_text(json.dumps({"name": "synthetic", "version": "7", "items": entries}))
        bar = {"name": "it-bar", "min_items": 2, "max_hallucination_bp": 1000, "max_numeral_reliance_bp": 1000, "per_class": {n: {"min_precision_bp": 9000, "min_recall_bp": 9000} for n in ATTRIBUTE_NAMES}}
        (tmp_path / "bar.json").write_text(json.dumps(bar))
        good = json.dumps({n: f"v {n}".replace("_", " ") for n in ATTRIBUTE_NAMES})
        report = run_evaluation(provider=ScriptedVisionProvider([good] * 3 + [json.dumps({n: None for n in ATTRIBUTE_NAMES})]), provider_name="ollama", model="it-op",
                                schema_version=SCHEMA_VERSION, run_by="pytest", dataset_dir=ds, bar_path=tmp_path / "bar.json", limits=LIMITS,
                                writer=PostgresEvalWriter(os.environ["DATABASE_URL"]))
        assert report.passed
        with tenant_scope(uuid.uuid4()) as conn:  # the application role reads platform runs, with no tenant data in them
            row = conn.execute(text("SELECT provider, model, schema_version, dataset_ref, bar_ref, passed, run_by, metrics FROM vision_eval_run WHERE id=:i"), {"i": report.run_id}).one()
        assert (row.provider, row.model, row.dataset_ref, row.passed, row.run_by) == ("ollama", "it-op", "synthetic@7", True, "pytest") and row.bar_ref.startswith("it-bar@")
        assert row.metrics["hallucination_bp"] == 0 and row.metrics["items"] == 4
        latest = PostgresImageStore().latest_eval_run(uuid.uuid4(), "ollama", "it-op", SCHEMA_VERSION)
        assert latest is not None and latest.id == report.run_id and latest.passed
        for sql in ("INSERT INTO vision_eval_run (provider, model, schema_version, dataset_ref, metrics, bar_ref, passed, run_by) VALUES ('p','m','v','d','{}'::jsonb,'b',true,'x')",
                    "UPDATE vision_eval_run SET passed = true", "DELETE FROM vision_eval_run"):
            with pytest.raises(ProgrammingError):
                with tenant_scope(uuid.uuid4()) as conn:
                    conn.execute(text(sql))  # an evaluation is operator-only: the application role cannot write or alter it

    def test_the_latest_run_for_the_exact_triple_wins(self, migrate_engine):
        t0 = datetime.now(UTC) - timedelta(hours=5)
        eval_run(migrate_engine, True, model="triple", run_at=t0)
        failing = eval_run(migrate_engine, False, model="triple", run_at=t0 + timedelta(hours=1))
        eval_run(migrate_engine, True, model="other-triple", run_at=t0 + timedelta(hours=2))
        latest = PostgresImageStore().latest_eval_run(uuid.uuid4(), "ollama", "triple", SCHEMA_VERSION)
        assert latest is not None and latest.id == failing and latest.passed is False
