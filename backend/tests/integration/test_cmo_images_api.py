"""P6 end-to-end: image upload and analysis over the real HTTP API on a real Postgres.

Real: FastAPI app, auth chain (only Clerk is faked), P3/P4/P6 services, Postgres, local-disk image store, the Pillow
normaliser, the trust gate. Faked: the vision model (a scripted provider) and the text model (the P5 router)."""

from __future__ import annotations

import base64
import io
import json
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from PIL import Image
from sqlalchemy import text

from slim_cmo.imaging.normalize import ImageLimits
from slim_cmo.providers.ollama_vision import OllamaVisionProvider
from slim_cmo.repositories.postgres_image_store import PostgresImageStore
from slim_cmo.service.vision import ImageService
from slim_cmo.storage.local_disk import LocalDiskImageStore
from slim_cmo.vision.prompts import vision_prompt
from slim_cmo.vision.provider import VisionUnavailable
from slim_cmo.vision.schema import SCHEMA_VERSION

from backend import config
from backend.auth.permissions import PARTNER_ROLE
from backend.services import cmo_runtime
from backend.services.cmo_runtime import CmoImageRuntime

from .test_cmo_api import (  # noqa: F401
    AMAZON, TITLES, RoutingProvider, _erase_cmo_rows, _login, ctx_engine, env, fake_clerk, title_body,
)

pytestmark = pytest.mark.skipif(not os.environ.get("DATABASE_URL_APP") or not os.environ.get("DATABASE_URL"), reason="needs a live Postgres")

MODEL = "vision-it"
SECRET = b"SECRET-GPS-AND-OWNER-NAME"
GOOD = {"color": "matte blue", "material": "steel", "size": "large", "brand": "AquaKeep", "product_type": "bottle", "visible_text": "Stay hydrated"}
LIMITS = ImageLimits(max_bytes=3_000_000, max_pixels=4_000_000, allowed_types=frozenset({"image/jpeg", "image/png", "image/webp"}))


# ---- image builders -----------------------------------------------------------------------------------------


def _gradient(size=(40, 20), seed=0) -> Image.Image:
    img = Image.new("RGB", size)
    img.putdata([((x * 6 + seed) % 256, (y * 12 + seed * 7) % 256, (x + y + seed) * 4 % 256) for y in range(size[1]) for x in range(size[0])])
    return img


def jpeg(size=(40, 20), seed=0, exif=True) -> bytes:
    out = io.BytesIO()
    kw = {}
    if exif:
        e = Image.Exif()
        e[0x010F] = "TestCameraMake"
        gps = e.get_ifd(0x8825)
        gps[1], gps[3] = "N", "E"
        kw = {"exif": e, "comment": SECRET}
    _gradient(size, seed).save(out, format="JPEG", **kw)
    return out.getvalue()


def png(size=(30, 30)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size).save(out, format="PNG")
    return out.getvalue()


class FakeVision:
    def __init__(self, reply=None, delay=0.0, error=None):
        self.reply = json.dumps(GOOD) if reply is None else reply
        self.delay, self.error = delay, error
        self.calls, self.images = 0, []
        self._lock = threading.Lock()

    def describe(self, *, model, schema_version, image):
        with self._lock:
            self.calls += 1
            self.images.append(image)
        if self.delay:
            time.sleep(self.delay)
        if self.error:
            raise self.error
        return self.reply


class Img:
    def __init__(self, env, rt, vision, tmp_path):
        self.env, self.rt, self.vision, self.dir = env, rt, vision, tmp_path

    def upload(self, data, ctype="image/jpeg", name="photo.jpg", headers=None, client=None):
        c = client or self.env.client()
        return c.post("/api/v1/cmo/images", files={"file": (name, data, ctype)}, headers=self.env.headers if headers is None else headers)

    def analyze(self, asset_id, headers=None, client=None):
        return self.env.post("image-analyses", {"asset_id": str(asset_id)}, headers=headers, client=client)

    def stored_files(self):
        return [p for p in self.dir.rglob("*") if p.is_file()]


def _runtime(vision, tmp_path, *, rate_max=50, window=3600, limits=LIMITS, clock=None, provider=None):
    clock = clock or cmo_runtime.utc_now
    images = ImageService(PostgresImageStore(), LocalDiskImageStore(str(tmp_path)), limits=limits, provider=provider or vision,
                          provider_name="ollama", model=MODEL, clock=clock)
    return CmoImageRuntime(images=images, clock=clock, rate_max=rate_max, rate_window_seconds=window)


@pytest.fixture
def img(env, tmp_path, monkeypatch, migrate_engine, ctx_engine):
    vision = FakeVision()
    rt = _runtime(vision, tmp_path)
    monkeypatch.setattr(cmo_runtime, "build_image_runtime", lambda *, need_vision, clock=cmo_runtime.utc_now: rt)
    yield Img(env, rt, vision, tmp_path)
    # analyses cite evaluation runs (composite FK): erase the analyses of every tenant this test touched BEFORE the runs
    from testkit.tenant_cleanup import TRACKER

    from .test_cmo_api import _CMO_TENANT_TABLES

    for tenant in sorted(set(TRACKER.tenants), key=str):
        with ctx_engine.begin() as conn:
            conn.execute(text("SET CONSTRAINTS ALL DEFERRED"))
            conn.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": str(tenant)})
            for table in _CMO_TENANT_TABLES:
                conn.execute(text(f"DELETE FROM {table} WHERE tenant_id = :t"), {"t": str(tenant)})
    with migrate_engine.begin() as conn:
        conn.execute(text("DELETE FROM vision_eval_run WHERE run_by = 'pytest'"))


def passing_eval(engine, passed=True, model=MODEL):
    with engine.begin() as conn:
        return conn.execute(text("INSERT INTO vision_eval_run (provider, model, schema_version, dataset_ref, metrics, bar_ref, passed, run_by) "
                                 "VALUES ('ollama', :m, :s, 'synthetic@1', '{}'::jsonb, 'bar@1', :p, 'pytest') RETURNING id"), {"m": model, "s": SCHEMA_VERSION, "p": passed}).scalar_one()


def count(env, table, where="true", **p):
    return env.n(table, where, **p)


# ---- upload: auth, permissions, storage ------------------------------------------------------------------------------


def test_unauthenticated_upload_and_analysis_are_401_and_do_nothing(img):
    assert img.upload(jpeg(), headers={}).status_code == 401
    assert img.env.post("image-analyses", {"asset_id": str(uuid.uuid4())}, headers={}).status_code == 401
    assert count(img.env, "seller_image_asset") == 0 and img.stored_files() == [] and img.vision.calls == 0


def test_upload_needs_files_upload_as_well_as_agent_cmo(img):
    only_cmo, _ = _login(img.env.fake_clerk, img.env.tenant, role=PARTNER_ROLE, permissions={"agent.cmo": True})
    only_files, _ = _login(img.env.fake_clerk, img.env.tenant, role=PARTNER_ROLE, permissions={"files.upload": True})
    both, _ = _login(img.env.fake_clerk, img.env.tenant, role=PARTNER_ROLE, permissions={"agent.cmo": True, "files.upload": True})
    r = img.upload(jpeg(), headers=only_cmo)
    assert r.status_code == 403 and "files.upload" in r.text
    assert img.upload(jpeg(), headers=only_files).status_code == 403
    assert count(img.env, "seller_image_asset") == 0
    assert img.upload(jpeg(), headers=both).status_code == 200
    only_cmo_analysis = img.env.post("image-analyses", {"asset_id": str(uuid.uuid4())}, headers=only_cmo)
    assert only_cmo_analysis.status_code == 404  # analysis needs agent.cmo only (the asset just does not exist)


def test_upload_stores_a_normalised_image_with_no_metadata_and_never_the_original(img):
    original = jpeg(exif=True)
    assert SECRET in original and b"Exif" in original
    r = img.upload(original)
    body = r.json()
    assert r.status_code == 200 and body["created"] is True and body["contentType"] == "image/png" and body["unitsBilled"] == 0
    assert set(body) == {"assetId", "created", "sha256", "width", "height", "contentType", "unitsBilled", "agentRunId"}
    files = img.stored_files()
    assert len(files) == 1 and str(img.env.tenant) in str(files[0])
    data = files[0].read_bytes()
    assert data.startswith(b"\x89PNG") and SECRET not in data and b"Exif" not in data and b"TestCameraMake" not in data and data != original
    with Image.open(io.BytesIO(data)) as im:
        assert not im.getexif() and "exif" not in im.info
    row = img.env.q("SELECT content_type, byte_size, status, sha256, storage_uri FROM seller_image_asset")[0]
    assert (row[0], row[1], row[2], row[3]) == ("image/png", len(data), "ACTIVE", body["sha256"]) and row[4].startswith(f"local://{img.env.tenant}/")
    assert str(img.dir) not in r.text and "local://" not in r.text and "photo.jpg" not in r.text  # no path, uri or client filename returned
    assert img.env.n("agent_run", "trigger_ref = 'cmo.upload_image'") == 1 and img.env.events() == [] and img.env.reservations() == []


def test_a_duplicate_upload_is_one_asset_one_file_and_no_new_run(img):
    a = img.upload(jpeg(exif=True)).json()
    b = img.upload(jpeg(exif=False)).json()  # same pixels, different metadata
    assert a["assetId"] == b["assetId"] and a["created"] is True and b["created"] is False and b["agentRunId"] is None
    assert count(img.env, "seller_image_asset") == 1 and len(img.stored_files()) == 1 and img.env.n("agent_run", "trigger_ref = 'cmo.upload_image'") == 1


def test_the_same_picture_in_two_tenants_is_two_assets_in_separate_directories(img):
    other, other_headers = img.env.other_tenant()
    mine, theirs = img.upload(jpeg()).json(), img.upload(jpeg(), headers=other_headers).json()
    assert mine["assetId"] != theirs["assetId"] and mine["sha256"] == theirs["sha256"]
    assert {p.parent.parent.name for p in img.stored_files()} == {str(img.env.tenant), str(other)}


@pytest.mark.parametrize("data,ctype,status,code", [
    (b"", "image/jpeg", 422, "EMPTY"),
    (b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>", "image/svg+xml", 415, "TYPE_NOT_ALLOWED"),
    (b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>", "image/png", 415, "NOT_AN_IMAGE"),
    (b"%PDF-1.7 not an image", "image/jpeg", 415, "NOT_AN_IMAGE"),
    (png(), "image/jpeg", 415, "TYPE_MISMATCH"),
    (jpeg()[:60], "image/jpeg", 422, "CORRUPT"),
    (png() + b"<?php system($_GET['c']); ?>", "image/jpeg", 415, "TYPE_MISMATCH"),
    (jpeg(), "application/octet-stream", 415, "TYPE_NOT_ALLOWED"),
    (jpeg(), "", 415, "TYPE_NOT_ALLOWED"),
])
def test_rejected_uploads_have_a_status_a_generic_body_and_store_nothing(img, data, ctype, status, code):
    r = img.upload(data, ctype=ctype)
    assert r.status_code == status and r.json()["detail"]["code"] == code
    assert "script" not in r.text and "PDF" not in r.text and "system(" not in r.text
    assert count(img.env, "seller_image_asset") == 0 and img.stored_files() == [] and img.env.n("agent_run") == 0


def test_a_decompression_bomb_and_an_animated_image_are_refused(img):
    bomb = io.BytesIO()
    Image.new("1", (20000, 20000)).save(bomb, format="PNG")
    assert len(bomb.getvalue()) < 100_000
    assert img.upload(bomb.getvalue(), ctype="image/png").json()["detail"]["code"] == "TOO_MANY_PIXELS"
    frames = [_gradient((16, 16)), Image.new("RGB", (16, 16), (200, 10, 10))]
    anim = io.BytesIO()
    frames[0].save(anim, format="WEBP", save_all=True, append_images=frames[1:], duration=50)
    r = img.upload(anim.getvalue(), ctype="image/webp")
    assert r.status_code == 415 and r.json()["detail"]["code"] == "ANIMATED_NOT_SUPPORTED"
    assert count(img.env, "seller_image_asset") == 0 and img.stored_files() == []


def test_the_pixel_limit_comes_from_configuration_not_code(env, tmp_path, monkeypatch):
    small = ImageLimits(max_bytes=3_000_000, max_pixels=1000, allowed_types=LIMITS.allowed_types)  # 1000 pixels
    rt = _runtime(FakeVision(), tmp_path, limits=small)
    monkeypatch.setattr(cmo_runtime, "build_image_runtime", lambda *, need_vision, clock=cmo_runtime.utc_now: rt)
    c = env.client()
    ok = c.post("/api/v1/cmo/images", files={"file": ("a.jpg", jpeg((40, 20)), "image/jpeg")}, headers=env.headers)  # 800 pixels
    assert ok.status_code == 200
    r = c.post("/api/v1/cmo/images", files={"file": ("b.jpg", jpeg((60, 60), seed=3), "image/jpeg")}, headers=env.headers)  # 3600 pixels
    assert r.status_code == 422 and r.json()["detail"]["code"] == "TOO_MANY_PIXELS" and env.n("seller_image_asset") == 1


def test_the_exact_byte_limit_is_enforced_by_the_route(env, tmp_path, monkeypatch):
    data = jpeg((200, 200))
    limits = ImageLimits(max_bytes=len(data) - 1, max_pixels=4_000_000, allowed_types=LIMITS.allowed_types)
    rt = _runtime(FakeVision(), tmp_path, limits=limits)
    monkeypatch.setattr(cmo_runtime, "build_image_runtime", lambda *, need_vision, clock=cmo_runtime.utc_now: rt)
    r = env.client().post("/api/v1/cmo/images", files={"file": ("a.jpg", data, "image/jpeg")}, headers=env.headers)
    assert r.status_code == 413 and env.n("seller_image_asset") == 0 and list(tmp_path.rglob("*.png")) == []


def test_the_body_size_middleware_rejects_an_oversized_upload_before_auth_or_parsing(env, monkeypatch):
    from fastapi.testclient import TestClient

    from backend.main import create_app

    monkeypatch.setenv("CMO_IMAGE_MAX_BYTES", "1000")
    config.cmo_image_max_bytes.cache_clear()
    try:
        client = TestClient(create_app())
        r = client.post("/api/v1/cmo/images", files={"file": ("big.jpg", b"\xff\xd8\xff" + b"0" * 400_000, "image/jpeg")})  # no auth header at all
        assert r.status_code == 413 and "limit" in r.text.lower()
        small = client.post("/api/v1/cmo/images", files={"file": ("s.jpg", jpeg(), "image/jpeg")})  # under the limit: reaches auth
        assert small.status_code == 401
    finally:
        config.cmo_image_max_bytes.cache_clear()


def test_missing_image_configuration_is_503_before_the_body_is_read_and_nothing_is_written(env, monkeypatch, tmp_path):
    for name in ("CMO_IMAGE_DIR", "CMO_IMAGE_MAX_BYTES", "CMO_IMAGE_MAX_PIXELS", "CMO_IMAGE_ALLOWED_TYPES", "CMO_VISION_MODEL", "CMO_VISION_OLLAMA_HOST",
                 "CMO_VISION_TIMEOUT_SECONDS", "CMO_VISION_ANALYSES_PER_WINDOW", "CMO_VISION_RATE_WINDOW_SECONDS"):
        monkeypatch.delenv(name, raising=False)
    for fn in (config.cmo_image_storage_dir, config.cmo_image_max_bytes, config.cmo_image_max_pixels, config.cmo_image_allowed_types, config.cmo_vision_model,
               config.cmo_vision_ollama_host, config.cmo_vision_timeout_seconds, config.cmo_vision_rate_max, config.cmo_vision_rate_window_seconds):
        fn.cache_clear()
    c = env.client()
    r = c.post("/api/v1/cmo/images", files={"file": ("a.jpg", jpeg(), "image/jpeg")}, headers=env.headers)
    assert r.status_code == 503 and r.json()["detail"] == {"code": "CMO_NOT_CONFIGURED"} and "CMO_IMAGE" not in r.text
    r2 = env.post("image-analyses", {"asset_id": str(uuid.uuid4())})
    assert r2.status_code == 503 and r2.json()["detail"] == {"code": "CMO_NOT_CONFIGURED"}
    assert env.n("seller_image_asset") == 0 and env.n("agent_run") == 0 and not list(tmp_path.rglob("*"))


# ---- analysis ------------------------------------------------------------------------------------------------------


def test_analysis_is_zero_units_untrusted_and_immutable_and_records_one_run(img):
    asset = img.upload(jpeg()).json()["assetId"]
    r = img.analyze(asset)
    body = r.json()
    assert r.status_code == 200 and body["state"] == "COMPLETE" and body["reused"] is False and body["trustGate"] == {"open": False}
    assert body["unitsBilled"] == 0 and body["agentRunId"] is not None
    by = {a["name"]: a for a in body["attributes"]}
    assert set(by) == {"color", "material", "size", "brand", "product_type", "visible_text"}
    assert all(a["trustState"] == "UNVERIFIED_HINT" and a["basis"] == "IMAGE_OBSERVED" and a["note"] for a in by.values())
    assert img.env.events() == [] and img.env.reservations() == [] and count(img.env, "cmo_generation") == 0
    assert img.env.n("agent_run", "trigger_ref = 'cmo.analyze_image'") == 1
    row = img.env.q("SELECT eval_gate_ref, analysis_state, provider, model, schema_version FROM product_image_analysis")[0]
    assert (row[0], row[1], row[2], row[3], row[4]) == (None, "COMPLETE", "ollama", MODEL, SCHEMA_VERSION)


def test_the_provider_is_given_only_the_normalised_stored_image(img):
    asset = img.upload(jpeg()).json()["assetId"]
    img.analyze(asset)
    image = img.vision.images[0]
    assert image.content_type == "image/png" and image.data.startswith(b"\x89PNG") and SECRET not in image.data and b"Exif" not in image.data
    assert image.data == img.stored_files()[0].read_bytes()


def test_a_replayed_analysis_is_reused_with_no_model_call_and_no_new_run(img):
    asset = img.upload(jpeg()).json()["assetId"]
    first = img.analyze(asset).json()
    runs = img.env.n("agent_run")
    again = img.analyze(asset).json()
    assert again["reused"] is True and again["analysisId"] == first["analysisId"] and again["agentRunId"] is None
    assert img.vision.calls == 1 and img.env.n("agent_run") == runs and count(img.env, "product_image_analysis") == 1


def test_unknown_and_cross_tenant_assets_are_404_and_the_model_is_never_called(img):
    other, other_headers = img.env.other_tenant()
    asset = img.upload(jpeg()).json()["assetId"]
    for headers, asset_id in ((other_headers, asset), (None, str(uuid.uuid4()))):
        r = img.analyze(asset_id, headers=headers)
        assert r.status_code == 404 and r.json() == {"detail": "Not found"}
    assert img.vision.calls == 0 and count(img.env, "product_image_analysis", tenant=other) == 0 and count(img.env, "product_image_analysis") == 0


def test_analysis_bodies_reject_unknown_and_tenant_fields(img):
    other, _ = img.env.other_tenant()
    asset = img.upload(jpeg()).json()["assetId"]
    for extra in ({"tenant_id": str(other)}, {"provider": "hosted"}, {"model": "gpt"}, {"schema_version": "x"}, {"image": "base64..."}):
        assert img.env.post("image-analyses", {"asset_id": asset, **extra}).status_code == 422
    for bad in ({}, {"asset_id": "nope"}, {"asset_id": None}):
        assert img.env.post("image-analyses", bad).status_code == 422
    assert img.vision.calls == 0


def test_a_provider_failure_is_a_persisted_failed_analysis_not_an_error_and_leaks_nothing(img):
    img.vision.error = VisionUnavailable("boom-secret-token http://internal-ollama:11434")
    asset = img.upload(jpeg()).json()["assetId"]
    r = img.analyze(asset)
    assert r.status_code == 200 and r.json()["state"] == "FAILED" and r.json()["attributes"] == [] and r.json()["unitsBilled"] == 0
    assert "boom-secret-token" not in r.text and "internal-ollama" not in r.text
    assert img.env.q("SELECT analysis_state, attributes FROM product_image_analysis")[0][0] == "FAILED"
    assert img.env.n("agent_run", "trigger_ref = 'cmo.analyze_image' AND status = 'FAILED'") == 1
    img.vision.error = None
    retry = img.analyze(asset).json()  # a failed attempt never blocks a retry
    assert retry["state"] == "COMPLETE" and retry["reused"] is False


@pytest.mark.parametrize("reply", ["not json at all RAW-MARKER", "", "{}", '{"weight": "350 g", "price": "Rs 499"}', "[]"])
def test_an_unusable_reply_is_a_failed_analysis_and_the_raw_text_never_reaches_the_seller_or_the_database(img, reply):
    img.vision.reply = reply
    asset = img.upload(jpeg()).json()["assetId"]
    r = img.analyze(asset)
    assert r.json()["state"] == "FAILED" and "RAW-MARKER" not in r.text and "350 g" not in r.text and "Rs 499" not in r.text
    assert "RAW-MARKER" not in json.dumps([list(map(str, row)) for row in img.env.q("SELECT * FROM product_image_analysis")])


def test_policy_filtering_discards_weight_price_dimensions_and_digits_without_degrading(img):
    img.vision.reply = json.dumps({**GOOD, "material": "steel 304", "size": "500 ml", "visible_text": "Call 9876543210 RAW-VISIBLE-MARKER",
                                   "weight": "350 g", "price": "Rs 499", "dimensions": "10 x 5 cm", "notes": "RAW-NOTES", "rating": "4.5 stars"})
    asset = img.upload(jpeg()).json()["assetId"]
    r = img.analyze(asset)
    body = r.json()
    assert body["state"] == "COMPLETE" and body["reason"] is None
    by = {a["name"]: a["value"] for a in body["attributes"]}
    assert by == {"color": "matte blue", "material": None, "size": None, "brand": "AquaKeep", "product_type": "bottle", "visible_text": None}
    stored = json.dumps([list(map(str, row)) for row in img.env.q("SELECT * FROM product_image_analysis")])
    # distinctive tokens only: bare digit strings can occur by chance inside the random UUIDs in a dumped row
    for banned in ("350 g", "Rs 499", "steel 304", "500 ml", "9876543210", "RAW-NOTES", "RAW-VISIBLE-MARKER", "weight", "price", "dimensions", "rating", "4.5 stars"):
        assert banned not in r.text and banned not in stored, banned


def test_a_partially_usable_reply_is_degraded_and_a_hostile_basis_claim_changes_nothing(img):
    img.vision.reply = json.dumps({"color": "blue", "brand": "AquaKeep", "basis": "SELLER_PROVIDED", "trust_state": "EVAL_PASSED"})
    body = img.analyze(img.upload(jpeg()).json()["assetId"]).json()
    assert body["state"] == "DEGRADED" and body["reason"] and body["trustGate"] == {"open": False}
    assert {a["trustState"] for a in body["attributes"]} == {"UNVERIFIED_HINT"} and {a["basis"] for a in body["attributes"]} <= {"IMAGE_OBSERVED", "UNKNOWN"}


def test_the_responses_never_expose_the_provider_model_prompt_evaluation_or_storage(img):
    passing_eval(img.env.engine)
    asset_resp = img.upload(jpeg())
    analysis = img.analyze(asset_resp.json()["assetId"])
    for resp in (asset_resp, analysis):
        for banned in ("ollama", MODEL, "prompt", "eval", "storage", "local://", "gate_ref", "Reply with a single", str(img.dir)):
            assert banned not in resp.text, banned
    assert resp.headers["Cache-Control"] == "no-store"


def test_nothing_in_a_vision_request_comes_from_seller_data_or_the_target_price(env, tmp_path, monkeypatch):
    """The REAL Ollama vision client over a mock transport: the only things it sends are the fixed prompt and the normalised PNG."""
    sent = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"response": json.dumps(GOOD)})

    provider = OllamaVisionProvider(host="http://ollama.test", timeout_seconds=5, transport=httpx.MockTransport(handler))
    rt = _runtime(None, tmp_path, provider=provider)
    monkeypatch.setattr(cmo_runtime, "build_image_runtime", lambda *, need_vision, clock=cmo_runtime.utc_now: rt)
    # the seller has supplied facts and a target price elsewhere in the same tenant (stored as seller facts)
    assert env.post("title-sets", title_body("pre", target_price_paise=49900)).status_code == 200
    assert env.n("seller_fact", "fact_type = 'TARGET_PRICE'") == 1
    asset = env.client().post("/api/v1/cmo/images", files={"file": ("p.jpg", jpeg(), "image/jpeg")}, headers=env.headers).json()["assetId"]
    assert env.post("image-analyses", {"asset_id": asset}).status_code == 200
    assert len(sent) == 1
    payload = sent[0]
    assert set(payload) == {"model", "prompt", "images", "stream"} and payload["model"] == MODEL and payload["prompt"] == vision_prompt(SCHEMA_VERSION) and payload["stream"] is False
    assert len(payload["images"]) == 1
    sent_image = base64.b64decode(payload["images"][0])
    assert sent_image.startswith(b"\x89PNG") and SECRET not in sent_image and b"Exif" not in sent_image
    for banned in ("49900", "AquaKeep", "SKU1", "target", str(env.tenant)):
        assert banned not in payload["prompt"]


# ---- rate limit ------------------------------------------------------------------------------------------------------


def test_the_per_tenant_rate_limit_throttles_only_real_model_calls(env, tmp_path, monkeypatch):
    vision = FakeVision()
    rt = _runtime(vision, tmp_path, rate_max=2, window=3600)
    monkeypatch.setattr(cmo_runtime, "build_image_runtime", lambda *, need_vision, clock=cmo_runtime.utc_now: rt)
    img = Img(env, rt, vision, tmp_path)
    assets = [img.upload(jpeg(seed=i)).json()["assetId"] for i in range(4)]
    assert [img.analyze(a).status_code for a in assets[:2]] == [200, 200]
    limited = img.analyze(assets[2])
    assert limited.status_code == 429 and limited.json()["detail"] == {"code": "RATE_LIMITED"} and limited.headers["Retry-After"] == "3600"
    assert vision.calls == 2 and count(env, "product_image_analysis") == 2
    replay = img.analyze(assets[0])  # an existing analysis is served at the limit: no model call, not throttled
    assert replay.status_code == 200 and replay.json()["reused"] is True and vision.calls == 2
    other, other_headers = env.other_tenant()
    oasset = img.upload(jpeg(seed=9), headers=other_headers).json()["assetId"]
    assert img.analyze(oasset, headers=other_headers).status_code == 200  # the limit is per tenant


def test_failed_attempts_count_toward_the_rate_limit_and_old_rows_do_not(env, tmp_path, monkeypatch):
    vision = FakeVision(error=VisionUnavailable("down"))
    rt = _runtime(vision, tmp_path, rate_max=1, window=60)
    monkeypatch.setattr(cmo_runtime, "build_image_runtime", lambda *, need_vision, clock=cmo_runtime.utc_now: rt)
    img = Img(env, rt, vision, tmp_path)
    a, b = (img.upload(jpeg(seed=i)).json()["assetId"] for i in (1, 2))
    assert img.analyze(a).json()["state"] == "FAILED"
    assert img.analyze(b).status_code == 429  # the failed attempt cost a model call
    later = _runtime(vision, tmp_path, rate_max=1, window=60, clock=lambda: datetime.now(UTC) + timedelta(hours=1))
    monkeypatch.setattr(cmo_runtime, "build_image_runtime", lambda *, need_vision, clock=cmo_runtime.utc_now: later)
    assert img.analyze(b).status_code == 200  # an hour later the window has moved on


def test_simultaneous_identical_analyses_leave_exactly_one_complete_row(img):
    img.vision.delay = 0.3
    asset = img.upload(jpeg()).json()["assetId"]
    barrier = threading.Barrier(6)

    def go(_):
        client = img.env.client()
        barrier.wait()
        r = img.analyze(asset, client=client)
        return r.status_code, r.json().get("analysisId")

    with ThreadPoolExecutor(max_workers=6) as pool:
        out = list(pool.map(go, range(6)))
    assert all(code == 200 for code, _ in out) and len({aid for _, aid in out}) == 1  # no 500s; everyone is served the one winner
    assert count(img.env, "product_image_analysis", "analysis_state = 'COMPLETE'") == 1 and 1 <= img.vision.calls <= 6  # duplicate model calls are accepted


# ---- the trust gate, end to end -----------------------------------------------------------------------------------


def catalog_color(env, key, analysis_id):
    r = env.post("catalog-answers", {"request_key": key, "sku": "SKU1", "questions": ["COLOR", "WEIGHT"], "image_analysis_id": str(analysis_id)})
    assert r.status_code == 200, r.text
    return {a["attribute"]: a for a in r.json()["artefacts"][0]["attributes"]}


def test_unverified_then_trusted_then_revoked_through_the_whole_stack(img):
    env = img.env
    # 1. no evaluation: a hint only
    hint = img.analyze(img.upload(jpeg(seed=1)).json()["assetId"]).json()
    c = catalog_color(env, "k1", hint["analysisId"])
    assert (c["COLOR"]["basis"], c["COLOR"]["value"], c["COLOR"]["claimEligible"]) == ("UNKNOWN", None, False) and c["COLOR"]["suggestion"]["value"] == "matte blue"
    # 2. a passing evaluation for the exact provider/model/schema: NEW analyses are trusted
    passing_eval(env.engine)
    asset2 = img.upload(jpeg(seed=2)).json()["assetId"]
    trusted = img.analyze(asset2).json()
    assert trusted["trustGate"] == {"open": True} and {a["trustState"] for a in trusted["attributes"]} == {"EVAL_PASSED"}
    c = catalog_color(env, "k2", trusted["analysisId"])
    assert (c["COLOR"]["basis"], c["COLOR"]["value"], c["COLOR"]["claimEligible"]) == ("IMAGE_OBSERVED", "matte blue", True)
    assert c["WEIGHT"]["basis"] == "UNKNOWN" and c["WEIGHT"]["value"] is None  # weight is never image-observed
    # the earlier analysis is immutable: it stays a hint even though the gate opened later
    assert catalog_color(env, "k3", hint["analysisId"])["COLOR"]["basis"] == "UNKNOWN"
    # 3. a failing evaluation (regression): trust is revoked at read time, the stored row is untouched
    before = env.q("SELECT attributes FROM product_image_analysis WHERE id = :i", i=trusted["analysisId"])[0][0]
    passing_eval(env.engine, passed=False)
    c = catalog_color(env, "k4", trusted["analysisId"])
    assert (c["COLOR"]["basis"], c["COLOR"]["value"], c["COLOR"]["claimEligible"]) == ("UNKNOWN", None, False) and c["COLOR"]["suggestion"]["value"] == "matte blue"
    again = img.analyze(asset2).json()
    assert again["reused"] is True and again["trustGate"] == {"open": False} and {a["trustState"] for a in again["attributes"]} == {"UNVERIFIED_HINT"}
    after = env.q("SELECT attributes FROM product_image_analysis WHERE id = :i", i=trusted["analysisId"])[0][0]
    assert after == before and "EVAL_PASSED" in json.dumps(after)
    # 4. a newer passing evaluation restores it
    passing_eval(env.engine)
    assert catalog_color(env, "k5", trusted["analysisId"])["COLOR"]["basis"] == "IMAGE_OBSERVED"


def test_an_evaluation_for_a_different_model_never_trusts_this_one(img):
    passing_eval(img.env.engine, model="some-other-vision-model")
    res = img.analyze(img.upload(jpeg()).json()["assetId"]).json()
    assert res["trustGate"] == {"open": False}


def test_generation_prompts_carry_a_trusted_observation_but_never_a_hint_or_the_target_price(img):
    env = img.env
    hint = img.analyze(img.upload(jpeg(seed=1)).json()["assetId"]).json()["analysisId"]
    passing_eval(env.engine)
    trusted = img.analyze(img.upload(jpeg(seed=2)).json()["assetId"]).json()["analysisId"]
    ok = env.post("title-sets", title_body("g1", image_analysis_id=hint, target_price_paise=49900))
    assert ok.status_code == 200 and ok.json()["artefacts"][0]["status"] == "COMPLETE"
    assert "matte blue" not in env.provider.prompts[-1] and "49900" not in env.provider.prompts[-1]  # an unverified hint is never a fact
    env.post("title-sets", title_body("g2", image_analysis_id=trusted, target_price_paise=49900))
    assert '"value": "matte blue"' in env.provider.prompts[-1] and '"name": "color"' in env.provider.prompts[-1] and "49900" not in env.provider.prompts[-1]
    passing_eval(env.engine, passed=False)  # revoke
    env.post("title-sets", title_body("g3", image_analysis_id=trusted))
    assert "matte blue" not in env.provider.prompts[-1]


def test_confirming_a_hint_makes_it_the_sellers_fact_without_touching_the_analysis(img):
    env = img.env
    analysis = img.analyze(img.upload(jpeg()).json()["assetId"]).json()["analysisId"]
    before = env.q("SELECT attributes, eval_gate_ref, analysis_state FROM product_image_analysis")
    r = env.post("image-hints/confirm", {"analysis_id": analysis, "attribute_name": "color", "sku": "SKU1"})
    assert r.status_code == 200 and r.json()["created"] is True and r.json()["unitsBilled"] == 0
    assert env.q("SELECT attributes, eval_gate_ref, analysis_state FROM product_image_analysis") == before
    assert env.events() == [] and env.reservations() == [] and count(env, "cmo_generation") == 0
    c = catalog_color(env, "k9", analysis)
    assert (c["COLOR"]["basis"], c["COLOR"]["value"], c["COLOR"]["claimEligible"]) == ("SELLER_PROVIDED", "matte blue", True)


def test_the_seller_always_wins_over_a_trusted_observation(img):
    env = img.env
    passing_eval(env.engine)
    analysis = img.analyze(img.upload(jpeg()).json()["assetId"]).json()["analysisId"]
    r = env.post("catalog-answers", {"request_key": "w", "sku": "SKU1", "questions": ["COLOR"], "image_analysis_id": analysis, "attributes": [{"name": "colour", "value": "red"}]})
    color = r.json()["artefacts"][0]["attributes"][0]
    assert (color["value"], color["basis"], color["conflictingObservation"]) == ("red", "SELLER_PROVIDED", "matte blue")


# ---- isolation, RLS, zero-unit, no write-back --------------------------------------------------------------------------


def test_cross_tenant_analysis_ids_cannot_be_used_in_generation_catalog_or_confirmation(img):
    other, other_headers = img.env.other_tenant()
    analysis = img.analyze(img.upload(jpeg()).json()["assetId"]).json()["analysisId"]
    for path, body in (("title-sets", title_body("x1", image_analysis_id=analysis)),
                       ("catalog-answers", {"request_key": "x2", "questions": ["COLOR"], "image_analysis_id": analysis}),
                       ("image-hints/confirm", {"analysis_id": analysis, "attribute_name": "color", "sku": "S"})):
        r = img.env.post(path, body, headers=other_headers)
        assert r.status_code == 404 and r.json() == {"detail": "Not found"}, path
    assert count(img.env, "cmo_generation", tenant=other) == 0 and count(img.env, "seller_fact", tenant=other) == 0


def test_rls_hides_assets_and_analyses_from_the_application_role_without_context(img):
    from sqlalchemy import create_engine
    from sqlalchemy.pool import NullPool

    img.analyze(img.upload(jpeg()).json()["assetId"])
    engine = create_engine(os.environ["DATABASE_URL_APP"], poolclass=NullPool)
    try:
        for ctx in (None, uuid.uuid4()):
            with engine.begin() as conn:
                if ctx:
                    conn.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": str(ctx)})
                for table in ("seller_image_asset", "product_image_analysis"):
                    assert conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one() == 0, (table, ctx)
        with engine.begin() as conn:
            conn.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": str(img.env.tenant)})
            assert conn.execute(text("SELECT count(*) FROM product_image_analysis")).scalar_one() == 1
    finally:
        engine.dispose()


def test_the_image_actions_never_bill_reserve_or_meter_even_with_a_zero_cap_everywhere(img):
    from .test_cmo_api import seed_cap

    for meter in ("cmo.upload_image", "cmo.analyze_image", "cmo.generate_title_sets", "cmo.catalog_answer"):
        seed_cap(img.env.engine, meter, 0)
    asset = img.upload(jpeg()).json()["assetId"]
    assert img.analyze(asset).status_code == 200
    assert img.env.events() == [] and img.env.reservations() == [] and count(img.env, "cmo_generation") == 0


def test_there_is_no_get_publish_or_listing_route_for_images(img):
    c = img.env.client()
    for method, path in (("get", "/api/v1/cmo/images"), ("get", "/api/v1/cmo/images/x"), ("delete", "/api/v1/cmo/images"), ("put", "/api/v1/cmo/images"),
                         ("get", "/api/v1/cmo/image-analyses"), ("patch", "/api/v1/cmo/image-analyses"), ("post", "/api/v1/cmo/images/publish"),
                         ("post", "/api/v1/cmo/marketplaces/amazon/images")):
        assert getattr(c, method)(path, headers=img.env.headers).status_code in (404, 405), (method, path)
    assert img.vision.calls == 0
