"""ImageService (P6): upload -> normalise -> store; analyse -> parse -> trust-gate -> immutable analysis.

In-memory ports mimic what the database guarantees the service relies on (tenant isolation, content-addressed
assets, the partial unique index over COMPLETE analyses, append-only analyses, read-time trust revocation)."""

from __future__ import annotations

import json
import uuid
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest

from slim_cmo.imaging.normalize import ImageRejected
from slim_cmo.service.errors import NotFound
from slim_cmo.service.models import Actor, AnalysisRecord, DuplicateAnalysis, ExistingAnalysis, StoredAnalysis, StoredAsset
from slim_cmo.service.vision import ImageService, StoredImageUnreadable
from slim_cmo.storage.local_disk import LocalDiskImageStore
from slim_cmo.types import ImageAnalysisState as S
from slim_cmo.vision.provider import ScriptedVisionProvider, VisionUnavailable
from slim_cmo.vision.schema import SCHEMA_VERSION
from slim_cmo.vision.trust import EvalRunRef, effective_attributes

from ..imagehelpers import LIMITS, SECRET, jpeg_with_exif, png_bytes

NOW = datetime(2026, 10, 5, 12, tzinfo=UTC)
TENANT_A, TENANT_B, USER = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
A, B = Actor(TENANT_A, USER), Actor(TENANT_B, USER)
GOOD = json.dumps({"color": "blue", "material": "stainless steel", "size": "large", "brand": "AquaKeep", "product_type": "bottle", "visible_text": "Stay hydrated"})


class MemImageStore:
    def __init__(self) -> None:
        self.assets: dict[tuple[uuid.UUID, uuid.UUID], StoredAsset] = {}
        self.by_sha: dict[tuple[uuid.UUID, str], uuid.UUID] = {}
        self.analyses: list[tuple[uuid.UUID, uuid.UUID, AnalysisRecord, datetime]] = []  # tenant, id, record, created
        self.runs: list[EvalRunRef] = []
        self.before_save = None

    def save_asset(self, tenant_id, *, uploaded_by, storage_uri, sha256, content_type, byte_size):
        if (tenant_id, sha256) in self.by_sha:
            return self.by_sha[(tenant_id, sha256)], False
        aid = uuid.uuid4()
        self.assets[(tenant_id, aid)] = StoredAsset(aid, storage_uri, sha256, content_type, byte_size, "ACTIVE")
        self.by_sha[(tenant_id, sha256)] = aid
        return aid, True

    def load_asset(self, tenant_id, asset_id):
        return self.assets.get((tenant_id, asset_id))

    def find_complete_analysis(self, tenant_id, asset_id, provider, model, schema_version):
        for t, aid, r, _c in self.analyses:
            if (t, r.image_asset_id, r.provider, r.model, r.schema_version, r.analysis_state) == (tenant_id, asset_id, provider, model, schema_version, S.COMPLETE):
                return ExistingAnalysis(aid, r.analysis_state, r.degraded_reason)
        return None

    def save_analysis(self, tenant_id, record):
        if self.before_save:
            hook, self.before_save = self.before_save, None
            hook(record)
        if record.analysis_state is S.COMPLETE and self.find_complete_analysis(tenant_id, record.image_asset_id, record.provider, record.model, record.schema_version):
            raise DuplicateAnalysis()
        aid = uuid.uuid4()
        self.analyses.append((tenant_id, aid, record, NOW))
        return aid

    def latest_eval_run(self, tenant_id, provider, model, schema_version):
        runs = [r for r in self.runs if (r.provider, r.model, r.schema_version) == (provider, model, schema_version)]
        return max(runs, key=lambda r: (r.run_at, str(r.id))) if runs else None

    def load_effective_analysis(self, tenant_id, analysis_id):
        for t, aid, r, _c in self.analyses:
            if t == tenant_id and aid == analysis_id:
                latest = self.latest_eval_run(t, r.provider, r.model, r.schema_version)
                return StoredAnalysis(aid, r.analysis_state, tuple(effective_attributes(r.attributes, bool(latest and latest.passed))))
        return None

    def count_recent_analyses(self, tenant_id, since):
        return sum(1 for t, _a, _r, c in self.analyses if t == tenant_id and c >= since)

    def stored_row(self, analysis_id) -> AnalysisRecord:
        return next(r for _t, aid, r, _c in self.analyses if aid == analysis_id)


def make(tmp_path, replies=(GOOD,), store=None):
    store = store or MemImageStore()
    provider = ScriptedVisionProvider(replies)
    files = LocalDiskImageStore(str(tmp_path))
    svc = ImageService(store, files, limits=LIMITS, provider=provider, provider_name="ollama", model="vision-m1", clock=lambda: NOW)
    return svc, store, provider, files


def passing_run(store, passed=True, minutes=0, model="vision-m1"):
    run = EvalRunRef(uuid.uuid4(), "ollama", model, SCHEMA_VERSION, passed, NOW.replace(minute=minutes))
    store.runs.append(run)
    return run


def upload(svc, actor=A, data=None, declared="image/jpeg"):
    return svc.upload(actor, data or jpeg_with_exif(), declared)


class TestUpload:
    def test_the_original_bytes_are_never_stored_only_the_normalised_png(self, tmp_path):
        svc, store, _p, files = make(tmp_path)
        original = jpeg_with_exif()
        res = upload(svc, data=original)
        asset = store.assets[(TENANT_A, res.asset_id)]
        stored = files.get(asset.storage_uri)
        assert stored.startswith(b"\x89PNG") and SECRET not in stored and b"Exif" not in stored and original != stored
        assert asset.content_type == "image/png" and asset.byte_size == len(stored) and asset.sha256 == res.sha256
        for path in tmp_path.rglob("*"):
            if path.is_file():
                assert SECRET not in path.read_bytes()  # nothing else on disk carries the metadata either

    def test_duplicate_uploads_are_one_asset_even_with_different_metadata(self, tmp_path):
        svc, store, _p, _f = make(tmp_path)
        first = upload(svc, data=jpeg_with_exif(comment=True))
        again = upload(svc, data=jpeg_with_exif(comment=False))
        assert first.created and not again.created and first.asset_id == again.asset_id and len(store.assets) == 1

    def test_the_same_picture_in_two_tenants_is_two_assets_in_two_directories(self, tmp_path):
        svc, store, _p, _f = make(tmp_path)
        a, b = upload(svc, A), upload(svc, B)
        assert a.asset_id != b.asset_id and a.sha256 == b.sha256
        assert (tmp_path / str(TENANT_A)).is_dir() and (tmp_path / str(TENANT_B)).is_dir()

    @pytest.mark.parametrize("data,declared,code", [(b"", "image/png", "EMPTY"), (b"<svg/>", "image/png", "NOT_AN_IMAGE"), (png_bytes(), "image/jpeg", "TYPE_MISMATCH"), (png_bytes(), "image/svg+xml", "TYPE_NOT_ALLOWED")])
    def test_rejected_uploads_write_nothing(self, tmp_path, data, declared, code):
        svc, store, _p, _f = make(tmp_path)
        with pytest.raises(ImageRejected) as caught:
            svc.upload(A, data, declared)
        assert caught.value.code == code and store.assets == {} and not [p for p in tmp_path.rglob("*") if p.is_file()]


class TestAnalyse:
    def test_the_provider_receives_only_the_normalised_stored_image(self, tmp_path):
        svc, store, provider, files = make(tmp_path)
        asset = upload(svc, data=jpeg_with_exif())
        svc.analyze(A, asset.asset_id)
        image = provider.images[0]
        assert image.data == files.get(store.assets[(TENANT_A, asset.asset_id)].storage_uri) and image.content_type == "image/png"
        assert SECRET not in image.data and b"Exif" not in image.data and provider.models == ["vision-m1"] and provider.schema_versions == [SCHEMA_VERSION]

    def test_a_closed_gate_stores_hints_and_nothing_trusted(self, tmp_path):
        svc, store, _p, _f = make(tmp_path)
        res = svc.analyze(A, upload(svc).asset_id)
        assert res.state is S.COMPLETE and not res.reused and res.trust_gate_open is False
        assert {a["trust_state"] for a in res.attributes} == {"UNVERIFIED_HINT"} and {a["basis"] for a in res.attributes} == {"IMAGE_OBSERVED"}
        row = store.stored_row(res.analysis_id)
        assert row.eval_gate_ref is None and row.provider == "ollama" and row.model == "vision-m1" and row.schema_version == SCHEMA_VERSION

    def test_a_passing_evaluation_for_the_exact_triple_opens_the_gate_and_is_cited(self, tmp_path):
        svc, store, _p, _f = make(tmp_path)
        run = passing_run(store)
        res = svc.analyze(A, upload(svc).asset_id)
        assert res.trust_gate_open and {a["trust_state"] for a in res.attributes} == {"EVAL_PASSED"}
        assert store.stored_row(res.analysis_id).eval_gate_ref == run.id

    @pytest.mark.parametrize("other_model", ["vision-m2"])
    def test_a_passing_evaluation_for_another_model_does_not_open_it(self, tmp_path, other_model):
        svc, store, _p, _f = make(tmp_path)
        passing_run(store, model=other_model)
        res = svc.analyze(A, upload(svc).asset_id)
        assert not res.trust_gate_open and store.stored_row(res.analysis_id).eval_gate_ref is None

    def test_a_failing_latest_evaluation_keeps_the_gate_closed(self, tmp_path):
        svc, store, _p, _f = make(tmp_path)
        passing_run(store, True, minutes=1)
        passing_run(store, False, minutes=2)
        assert not svc.analyze(A, upload(svc).asset_id).trust_gate_open

    def test_a_later_failing_evaluation_revokes_trust_at_read_time_and_the_stored_row_never_changes(self, tmp_path):
        svc, store, _p, _f = make(tmp_path)
        passing_run(store, True, minutes=1)
        res = svc.analyze(A, upload(svc).asset_id)
        stored_before = json.dumps(store.stored_row(res.analysis_id).attributes)
        assert res.trust_gate_open
        passing_run(store, False, minutes=5)  # regression
        again = svc.analyze(A, upload(svc).asset_id)  # same asset: reused, but shown with CURRENT trust
        assert again.reused and not again.trust_gate_open and {a["trust_state"] for a in again.attributes} == {"UNVERIFIED_HINT"}
        assert json.dumps(store.stored_row(res.analysis_id).attributes) == stored_before  # immutable: still says EVAL_PASSED at rest
        assert "EVAL_PASSED" in stored_before
        passing_run(store, True, minutes=9)
        assert svc.analyze(A, upload(svc).asset_id).trust_gate_open  # a newer pass restores it

    def test_the_raw_reply_is_never_stored_or_returned_and_policy_discarded_values_vanish(self, tmp_path):
        reply = json.dumps({"color": "blue", "material": "steel 304", "size": "500 ml", "brand": "AquaKeep", "product_type": "bottle", "visible_text": "SECRET-RAW-MARKER call 9876543210",
                            "weight": "350 g", "price": "Rs 499", "dimensions": "10x5 cm", "notes": "RAW-NOTES"})
        svc, store, _p, _f = make(tmp_path, [reply])
        res = svc.analyze(A, upload(svc).asset_id)
        blob = json.dumps([store.stored_row(res.analysis_id).attributes, res.attributes, res.reason])
        for banned in ("SECRET-RAW-MARKER", "RAW-NOTES", "350", "499", "10x5", "304", "9876543210", "weight", "price", "dimensions"):
            assert banned not in blob, banned
        assert res.state is S.COMPLETE  # policy filtering is not degradation
        assert {a["name"]: a["value"] for a in res.attributes} == {"color": "blue", "material": None, "size": None, "brand": "AquaKeep", "product_type": "bottle", "visible_text": None}

    def test_a_provider_that_claims_an_unverified_trust_or_a_seller_basis_cannot_change_what_is_stored(self, tmp_path):
        reply = json.dumps({"color": "blue", "basis": "SELLER_PROVIDED", "trust_state": "EVAL_PASSED", "attributes": [{"name": "color", "basis": "SELLER_PROVIDED"}],
                            "material": None, "size": None, "brand": None, "product_type": None, "visible_text": None})
        svc, store, _p, _f = make(tmp_path, [reply])
        res = svc.analyze(A, upload(svc).asset_id)
        assert {a["basis"] for a in res.attributes} <= {"IMAGE_OBSERVED", "UNKNOWN"} and {a["trust_state"] for a in res.attributes} == {"UNVERIFIED_HINT"}

    def test_a_degraded_reply_is_stored_degraded_with_a_reason_and_still_untrusted_hints(self, tmp_path):
        svc, store, _p, _f = make(tmp_path, ['{"color": "blue", "brand": "AquaKeep"}'])
        passing_run(store)
        res = svc.analyze(A, upload(svc).asset_id)
        assert res.state is S.DEGRADED and res.reason and store.stored_row(res.analysis_id).degraded_reason
        assert {a["name"]: a["value"] for a in res.attributes}["color"] == "blue"

    @pytest.mark.parametrize("reply", ["not json", "{}", '{"weight": "350 g"}', "", "[]"])
    def test_an_unusable_reply_is_a_persisted_failed_analysis_with_no_attributes(self, tmp_path, reply):
        svc, store, _p, _f = make(tmp_path, [reply])
        res = svc.analyze(A, upload(svc).asset_id)
        row = store.stored_row(res.analysis_id)
        assert res.state is S.FAILED and res.attributes == () and row.attributes == [] and row.degraded_reason and row.eval_gate_ref is None

    def test_a_provider_timeout_or_error_is_a_persisted_failed_analysis_not_a_crash(self, tmp_path):
        for error in (VisionUnavailable("down"), RuntimeError("boom-secret"), TimeoutError()):
            svc, store, _p, _f = make(tmp_path, [error])
            res = svc.analyze(A, upload(svc).asset_id)
            assert res.state is S.FAILED and "boom-secret" not in json.dumps([res.reason, store.stored_row(res.analysis_id).degraded_reason])

    def test_a_failed_attempt_never_blocks_a_retry_but_a_complete_one_is_reused(self, tmp_path):
        svc, store, provider, _f = make(tmp_path, [VisionUnavailable("down"), GOOD])
        asset = upload(svc)
        assert svc.analyze(A, asset.asset_id).state is S.FAILED
        ok = svc.analyze(A, asset.asset_id)
        assert ok.state is S.COMPLETE and not ok.reused and provider.calls == 2
        again = svc.analyze(A, asset.asset_id)
        assert again.reused and again.analysis_id == ok.analysis_id and provider.calls == 2  # no third model call
        assert sum(1 for *_x, r, _c in store.analyses if r.analysis_state is S.COMPLETE) == 1

    def test_a_new_model_is_a_new_analysis_of_the_same_asset(self, tmp_path):
        svc, store, _p, files = make(tmp_path, [GOOD, GOOD])
        asset = upload(svc)
        first = svc.analyze(A, asset.asset_id)
        other = ImageService(store, files, limits=LIMITS, provider=ScriptedVisionProvider([GOOD]), provider_name="ollama", model="vision-m2", clock=lambda: NOW)
        assert other.analyze(A, asset.asset_id).analysis_id != first.analysis_id

    def test_a_concurrent_duplicate_loses_the_unique_index_race_and_is_served_the_winner(self, tmp_path):
        svc, store, provider, _f = make(tmp_path)
        asset = upload(svc)
        winner_id = uuid.uuid4()

        def race(record: AnalysisRecord) -> None:
            store.analyses.append((TENANT_A, winner_id, replace(record), NOW))

        store.before_save = race
        res = svc.analyze(A, asset.asset_id)
        assert res.reused and res.analysis_id == winner_id and provider.calls == 1  # the duplicate model call happened; one row stands
        assert sum(1 for *_x, r, _c in store.analyses if r.analysis_state is S.COMPLETE) == 1


class TestIsolationAndFaults:
    def test_an_unknown_or_cross_tenant_asset_is_not_found_and_the_provider_is_never_called(self, tmp_path):
        svc, store, provider, _f = make(tmp_path)
        asset = upload(svc, A)
        for actor, asset_id in ((B, asset.asset_id), (A, uuid.uuid4())):
            with pytest.raises(NotFound):
                svc.analyze(actor, asset_id)
        assert provider.calls == 0 and store.analyses == []

    def test_a_purged_asset_looks_like_a_missing_one(self, tmp_path):
        svc, store, provider, _f = make(tmp_path)
        asset = upload(svc)
        store.assets[(TENANT_A, asset.asset_id)] = replace(store.assets[(TENANT_A, asset.asset_id)], status="PURGED")
        with pytest.raises(NotFound):
            svc.analyze(A, asset.asset_id)
        assert provider.calls == 0

    def test_a_row_pointing_at_another_tenants_file_is_never_read(self, tmp_path):
        svc, store, provider, _f = make(tmp_path)
        a_asset, b_asset = upload(svc, A), upload(svc, B)
        victim_uri = store.assets[(TENANT_B, b_asset.asset_id)].storage_uri
        store.assets[(TENANT_A, a_asset.asset_id)] = replace(store.assets[(TENANT_A, a_asset.asset_id)], storage_uri=victim_uri)
        with pytest.raises(StoredImageUnreadable):
            svc.analyze(A, a_asset.asset_id)
        assert provider.calls == 0 and store.analyses == []

    def test_a_missing_or_tampered_stored_file_is_an_operational_error_and_persists_nothing(self, tmp_path):
        svc, store, provider, files = make(tmp_path)
        asset = upload(svc)
        for p in tmp_path.rglob("*.png"):
            p.write_bytes(b"tampered")
        with pytest.raises(StoredImageUnreadable):
            svc.analyze(A, asset.asset_id)
        assert provider.calls == 0 and store.analyses == []

    def test_provider_and_model_identity_are_required(self, tmp_path):
        for name, model in (("", "m"), ("ollama", "  ")):
            with pytest.raises(ValueError):
                ImageService(MemImageStore(), LocalDiskImageStore(str(tmp_path)), limits=LIMITS, provider=ScriptedVisionProvider([]), provider_name=name, model=model, clock=lambda: NOW)

    def test_recent_analysis_count_is_per_tenant(self, tmp_path):
        svc, store, _p, _f = make(tmp_path, [GOOD, GOOD])
        svc.analyze(A, upload(svc, A).asset_id)
        svc.analyze(B, upload(svc, B).asset_id)
        assert svc.recent_analysis_count(A, NOW) == 1 and svc.recent_analysis_count(B, NOW) == 1 and svc.recent_analysis_count(Actor(uuid.uuid4(), USER), NOW) == 0
