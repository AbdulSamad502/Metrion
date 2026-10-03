"""P6 unit tests (no database): required image/vision configuration, runtime wiring, error mapping, response allow-list
and the structural zero-unit boundary of the image actions."""

from __future__ import annotations

import ast
import asyncio
import inspect
import json
import textwrap
import uuid

import pytest
from fastapi import HTTPException

from slim_cmo.imaging.normalize import ImageRejected
from slim_cmo.service.models import Actor
from slim_cmo.service.vision import AnalysisResult, UploadResult, VisionNotConfigured
from slim_cmo.types import ImageAnalysisState

from backend import config
from backend.api.v1 import cmo
from backend.auth.context import AuthContext
from backend.services import cmo_images, cmo_runtime
from backend.services.cmo_runtime import CmoNotConfigured

IMAGE_FNS = (config.cmo_image_storage_dir, config.cmo_image_max_bytes, config.cmo_image_max_pixels, config.cmo_image_allowed_types,
             config.cmo_vision_model, config.cmo_vision_ollama_host, config.cmo_vision_timeout_seconds, config.cmo_vision_rate_max,
             config.cmo_vision_rate_window_seconds)
ENV = {"CMO_IMAGE_DIR": "/tmp/imgs", "CMO_IMAGE_MAX_BYTES": "5000000", "CMO_IMAGE_MAX_PIXELS": "4000000", "CMO_IMAGE_ALLOWED_TYPES": "image/jpeg,image/png",
       "CMO_VISION_MODEL": "vision-x", "CMO_VISION_OLLAMA_HOST": "http://ollama.test:11434", "CMO_VISION_TIMEOUT_SECONDS": "90",
       "CMO_VISION_ANALYSES_PER_WINDOW": "5", "CMO_VISION_RATE_WINDOW_SECONDS": "3600"}


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    for name in ENV:
        monkeypatch.delenv(name, raising=False)
    for fn in IMAGE_FNS:
        fn.cache_clear()
    yield
    for fn in IMAGE_FNS:
        fn.cache_clear()


def set_env(monkeypatch, **override):
    for k, v in {**ENV, **override}.items():
        if v is None:
            monkeypatch.delenv(k, raising=False)
        else:
            monkeypatch.setenv(k, v)
    for fn in IMAGE_FNS:
        fn.cache_clear()


def identifiers(obj) -> set[str]:
    tree = ast.parse(textwrap.dedent(inspect.getsource(obj)))
    out = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    out |= {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str) and len(n.value) < 60}
    return out


class TestRequiredConfiguration:
    @pytest.mark.parametrize("fn", [config.cmo_image_storage_dir, config.cmo_vision_model, config.cmo_vision_ollama_host,
                                    config.cmo_vision_timeout_seconds, config.cmo_vision_rate_max, config.cmo_vision_rate_window_seconds])
    def test_these_have_no_default_and_raise_when_unset(self, fn):
        with pytest.raises(config.MissingConfig):
            fn()

    def test_the_image_limits_are_none_when_unset_and_the_routes_then_refuse(self):
        assert config.cmo_image_max_bytes() is None and config.cmo_image_max_pixels() is None and config.cmo_image_allowed_types() == frozenset()

    def test_no_hidden_directory_model_or_host_remains(self):
        for fn in (config.cmo_image_storage_dir, config.cmo_vision_model, config.cmo_vision_ollama_host):
            ids = identifiers(fn)
            assert "get" not in ids and not [i for i in ids if "./data" in i or "localhost" in i or "qwen" in i or "llava" in i], fn.__name__

    @pytest.mark.parametrize("bad", ["abc", "0", "-3", "2.5", " ", "1e3"])
    def test_integers_are_strict_and_positive(self, monkeypatch, bad):
        for name in ("CMO_VISION_TIMEOUT_SECONDS", "CMO_VISION_ANALYSES_PER_WINDOW", "CMO_VISION_RATE_WINDOW_SECONDS"):
            monkeypatch.setenv(name, bad)
        for fn in (config.cmo_vision_timeout_seconds, config.cmo_vision_rate_max, config.cmo_vision_rate_window_seconds):
            with pytest.raises((ValueError, config.MissingConfig)):
                fn()
        monkeypatch.setenv("CMO_IMAGE_MAX_PIXELS", bad)
        if bad.strip() and bad not in ("abc", "2.5", "1e3"):
            with pytest.raises(ValueError):
                config.cmo_image_max_pixels()


class TestImageRuntime:
    def test_nothing_configured_is_cmo_not_configured_for_both_modes(self):
        for need_vision in (False, True):
            with pytest.raises(CmoNotConfigured):
                cmo_runtime.build_image_runtime(need_vision=need_vision)

    @pytest.mark.parametrize("missing", ["CMO_IMAGE_DIR", "CMO_IMAGE_MAX_BYTES", "CMO_IMAGE_MAX_PIXELS", "CMO_IMAGE_ALLOWED_TYPES"])
    def test_every_upload_setting_is_required_even_for_upload_only(self, monkeypatch, missing):
        set_env(monkeypatch, **{missing: None})
        with pytest.raises(CmoNotConfigured):
            cmo_runtime.build_image_runtime(need_vision=False)

    @pytest.mark.parametrize("missing", ["CMO_VISION_MODEL", "CMO_VISION_OLLAMA_HOST", "CMO_VISION_TIMEOUT_SECONDS", "CMO_VISION_ANALYSES_PER_WINDOW", "CMO_VISION_RATE_WINDOW_SECONDS"])
    def test_every_vision_setting_is_required_for_analysis_but_not_for_upload(self, monkeypatch, missing):
        set_env(monkeypatch, **{missing: None})
        with pytest.raises(CmoNotConfigured):
            cmo_runtime.build_image_runtime(need_vision=True)
        assert cmo_runtime.build_image_runtime(need_vision=False).rate_max is None  # upload-only does not need them

    def test_a_complete_configuration_builds_both_runtimes_with_local_ollama(self, monkeypatch):
        set_env(monkeypatch)
        up = cmo_runtime.build_image_runtime(need_vision=False)
        full = cmo_runtime.build_image_runtime(need_vision=True)
        assert up.images.max_upload_bytes == 5_000_000 and (full.rate_max, full.rate_window_seconds) == (5, 3600)
        with pytest.raises(VisionNotConfigured):
            up.images.analyze(Actor(uuid.uuid4(), uuid.uuid4()), uuid.uuid4())  # an upload-only service cannot analyse

    def test_the_provider_identity_is_a_constant_not_a_setting(self):
        assert cmo_runtime.VISION_PROVIDER_NAME == "ollama"


class TestErrorMapping:
    @pytest.mark.parametrize("code,status", [("EMPTY", 422), ("TOO_LARGE", 413), ("TYPE_NOT_ALLOWED", 415), ("NOT_AN_IMAGE", 415), ("TYPE_MISMATCH", 415),
                                             ("CORRUPT", 422), ("TOO_MANY_PIXELS", 422), ("ANIMATED_NOT_SUPPORTED", 415)])
    def test_every_rejection_has_a_status_and_a_generic_body(self, code, status):
        def boom():
            raise ImageRejected(code, "plain reason")
        with pytest.raises(HTTPException) as caught:
            cmo._guarded(boom)
        assert caught.value.status_code == status and caught.value.detail == {"code": code, "detail": "plain reason"}

    def test_rate_limited_is_429_with_retry_after(self):
        with pytest.raises(HTTPException) as caught:
            cmo._guarded(lambda: (_ for _ in ()).throw(cmo_images.RateLimited(3600)))
        assert caught.value.status_code == 429 and caught.value.headers == {"Retry-After": "3600"} and caught.value.detail == {"code": "RATE_LIMITED"}

    def test_a_vision_runtime_that_is_not_configured_is_503(self):
        with pytest.raises(HTTPException) as caught:
            cmo._guarded(lambda: (_ for _ in ()).throw(VisionNotConfigured()))
        assert (caught.value.status_code, caught.value.detail) == (503, {"code": "CMO_NOT_CONFIGURED"})

    def test_an_unreadable_stored_image_is_a_generic_500(self):
        from slim_cmo.service.vision import StoredImageUnreadable

        with pytest.raises(HTTPException) as caught:
            cmo._guarded(lambda: (_ for _ in ()).throw(StoredImageUnreadable()))
        assert caught.value.status_code == 500 and caught.value.detail == {"code": "INTERNAL_ERROR"}


class TestUploadRoutePermissions:
    def test_the_upload_route_needs_files_upload_in_addition_to_agent_cmo(self):
        partner = AuthContext(app_user_id=uuid.uuid4(), clerk_user_id="u", email_verified=True, tenant_id=uuid.uuid4(), membership_status="ACTIVE",
                              role="PARTNER", permissions={"agent.cmo": True}, onboarding_state="ACTIVE")
        with pytest.raises(HTTPException) as caught:
            asyncio.run(cmo.post_image(file=None, ctx=partner))  # type: ignore[arg-type]
        assert caught.value.status_code == 403 and "files.upload" in caught.value.detail


class TestResponseShapes:
    def result(self, attrs, state=ImageAnalysisState.COMPLETE, reused=False, open_=False):
        return AnalysisResult(uuid.uuid4(), state, None, tuple(attrs), reused, open_)

    def test_an_analysis_response_is_an_allow_list_with_hints_labelled(self):
        res = self.result([{"name": "color", "value": "blue", "basis": "IMAGE_OBSERVED", "trust_state": "UNVERIFIED_HINT", "provider": "ollama", "model": "SECRET-MODEL", "raw": "RAW"},
                           {"name": "size", "value": None, "basis": "UNKNOWN", "trust_state": "UNVERIFIED_HINT"}])
        out = cmo_images.analysis_json(res, uuid.uuid4())
        assert out["attributes"][0] == {"name": "color", "value": "blue", "basis": "IMAGE_OBSERVED", "trustState": "UNVERIFIED_HINT", "note": "suggested from your photo - please confirm"}
        assert out["attributes"][1]["note"] is None and out["trustGate"] == {"open": False} and out["unitsBilled"] == 0
        blob = json.dumps(out)
        for banned in ("SECRET-MODEL", "RAW", "ollama", "eval", "storage", "prompt"):
            assert banned not in blob, banned

    def test_a_trusted_observation_carries_no_hint_note(self):
        out = cmo_images.analysis_json(self.result([{"name": "color", "value": "blue", "basis": "IMAGE_OBSERVED", "trust_state": "EVAL_PASSED"}], open_=True), None)
        assert out["attributes"][0]["note"] is None and out["trustGate"]["open"] is True and out["agentRunId"] is None

    def test_an_upload_response_has_no_storage_location_or_original_name(self):
        out = cmo_images.upload_json(UploadResult(uuid.uuid4(), True, "a" * 64, 40, 20, "image/png"), None)
        assert set(out) == {"assetId", "created", "sha256", "width", "height", "contentType", "unitsBilled", "agentRunId"} and out["unitsBilled"] == 0


class TestStructuralBoundary:
    def test_the_image_orchestrator_never_touches_admission_reservation_metering_or_entitlement(self):
        ids = identifiers(cmo_images)
        for banned in ("run_billable", "_settle", "_admit", "record_metered_event", "cmo_quota_repo", "resolve_cmo_entitlement", "billable_units"):
            assert banned not in ids, banned

    def test_the_rate_limit_is_checked_only_when_a_model_call_would_happen(self):
        src = inspect.getsource(cmo_images.analyze_image)
        assert src.index("has_reusable_analysis") < src.index("recent_analysis_count") < src.index("images.analyze(")

    def test_no_route_reads_a_client_supplied_path_name_or_tenant(self):
        assert set(cmo.AnalyzeBody.model_fields) == {"asset_id"}
        assert "filename" not in identifiers(cmo.post_image)
