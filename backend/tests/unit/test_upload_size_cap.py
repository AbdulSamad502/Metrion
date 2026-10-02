"""Upload size cap. Before: both upload endpoints did `await file.read()` with no limit, and the
ingestion pipeline then holds the whole file in memory at ~31x its size (measured), so one large
upload could take the worker down. Oversized files must now fail fast with a 413 — before the
file is loaded, ingested, or written to disk."""

from __future__ import annotations

import io
import uuid

import pytest
from fastapi import HTTPException, UploadFile

from backend import config
from backend.api.v1 import ci as ci_routes
from backend.api.v1 import cfo as cfo_routes
from backend.auth.context import AuthContext
from backend.uploads import read_upload_capped


def _upload(data: bytes, filename: str = "f.csv") -> UploadFile:
    return UploadFile(file=io.BytesIO(data), filename=filename, size=len(data))


def _ctx() -> AuthContext:
    return AuthContext(
        app_user_id=uuid.uuid4(), clerk_user_id="user_test", email_verified=True, tenant_id=uuid.uuid4(),
        membership_status="ACTIVE", role="OWNER", permissions={}, onboarding_state="COMPLETE",
    )


async def test_file_at_the_limit_is_accepted_and_returned_intact() -> None:
    data = b"x" * 100
    assert await read_upload_capped(_upload(data), max_bytes=100, env_var="E") == data


async def test_file_over_the_limit_is_rejected_with_413_and_names_the_env_var() -> None:
    with pytest.raises(HTTPException) as exc:
        await read_upload_capped(_upload(b"x" * 101), max_bytes=100, env_var="MY_LIMIT")
    assert exc.value.status_code == 413
    assert "MY_LIMIT" in exc.value.detail


async def test_unknown_size_upload_is_still_capped_without_reading_it_all() -> None:
    class _Counting(io.BytesIO):
        bytes_read = 0

        def read(self, n=-1):  # type: ignore[no-untyped-def]
            chunk = super().read(n)
            _Counting.bytes_read += len(chunk)
            return chunk

    big = _Counting(b"x" * 10_000)
    upload = UploadFile(file=big, filename="f.csv")  # no size -> cannot be pre-checked
    assert upload.size is None
    with pytest.raises(HTTPException) as exc:
        await read_upload_capped(upload, max_bytes=100, env_var="E")
    assert exc.value.status_code == 413
    assert _Counting.bytes_read <= 101  # never pulled the whole 10 kB (let alone a huge file) into memory


async def test_cfo_ingest_rejects_oversized_file_before_ingesting(monkeypatch) -> None:
    monkeypatch.setattr(cfo_routes, "_require_cfo_entitlement", lambda *a, **k: None)
    monkeypatch.setattr(cfo_routes, "cfo_max_upload_bytes", lambda: 50)

    def _never(*a, **k):
        raise AssertionError("an oversized upload must be rejected before any parsing/persisting")

    monkeypatch.setattr(cfo_routes, "ingest_and_persist", _never)
    monkeypatch.setattr(cfo_routes.report_file_repo, "find_by_content_hash", _never)
    monkeypatch.setattr(cfo_routes.report_file_repo, "insert_report_file", _never)
    adapter_id = next(iter(cfo_routes.ADAPTER_REGISTRY))
    with pytest.raises(HTTPException) as exc:
        await cfo_routes.post_ingest(_upload(b"a,b\n" + b"1,2\n" * 100), marketplace="MEESHO", adapter_id=adapter_id, ctx=_ctx())
    assert exc.value.status_code == 413


async def test_ci_evidence_rejects_oversized_image_and_writes_nothing(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(ci_routes, "ci_evidence_storage_dir", lambda: str(tmp_path / "evidence"))
    monkeypatch.setattr(ci_routes, "ci_max_evidence_bytes", lambda: 50)
    with pytest.raises(HTTPException) as exc:
        await ci_routes.upload_evidence(_upload(b"\x89PNG" + b"0" * 500, "shot.png"), ctx=_ctx())
    assert exc.value.status_code == 413
    assert not (tmp_path / "evidence").exists()  # rejected before the storage dir was even created


async def test_ci_evidence_within_limit_is_stored(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(ci_routes, "ci_evidence_storage_dir", lambda: str(tmp_path / "evidence"))
    monkeypatch.setattr(ci_routes, "ci_max_evidence_bytes", lambda: 1000)
    result = await ci_routes.upload_evidence(_upload(b"\x89PNG" + b"0" * 100, "shot.png"), ctx=_ctx())
    assert (tmp_path / "evidence" / result["imageRef"]).read_bytes().startswith(b"\x89PNG")


def test_limits_are_env_configurable_and_reject_nonsense(monkeypatch) -> None:
    config.cfo_max_upload_bytes.cache_clear()
    monkeypatch.setenv("CFO_MAX_UPLOAD_BYTES", "12345")
    assert config.cfo_max_upload_bytes() == 12345
    config.cfo_max_upload_bytes.cache_clear()
    monkeypatch.setenv("CFO_MAX_UPLOAD_BYTES", "0")
    with pytest.raises(ValueError):
        config.cfo_max_upload_bytes()
    config.cfo_max_upload_bytes.cache_clear()
    monkeypatch.delenv("CFO_MAX_UPLOAD_BYTES")
    assert config.cfo_max_upload_bytes() == 20 * 1024 * 1024
    config.cfo_max_upload_bytes.cache_clear()
