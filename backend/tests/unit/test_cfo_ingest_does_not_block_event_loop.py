"""`POST /cfo/ingest` is an `async def` handler, but everything after reading the upload (hashing,
file write, three DB calls, CSV parse, `ingest_and_persist`) is synchronous. Run directly on the
event loop that blocks EVERY other request on the worker for the whole ingestion (large
settlement files take seconds even after the bulk-insert fix). The handler must hand that work to
the threadpool so the loop stays responsive.

Calls the real handler as a plain coroutine (same convention as test_cfo_route_entitlement_
enforcement.py), with a deliberately slow synchronous `ingest_and_persist` stand-in, and measures
the longest stall of a concurrent event-loop heartbeat."""

from __future__ import annotations

import asyncio
import io
import time
import uuid
from types import SimpleNamespace

from fastapi import UploadFile

from backend.api.v1 import cfo as cfo_routes
from backend.auth.context import AuthContext

_SLOW_SECONDS = 0.5


def _ctx() -> AuthContext:
    return AuthContext(
        app_user_id=uuid.uuid4(), clerk_user_id="user_test", email_verified=True, tenant_id=uuid.uuid4(),
        membership_status="ACTIVE", role="OWNER", permissions={}, onboarding_state="COMPLETE",
    )


async def test_slow_ingestion_does_not_stall_the_event_loop(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(cfo_routes, "_require_cfo_entitlement", lambda *a, **k: None)
    monkeypatch.setattr(cfo_routes, "cfo_report_storage_dir", lambda: str(tmp_path))
    monkeypatch.setattr(cfo_routes.report_file_repo, "find_by_content_hash", lambda *a, **k: None)
    monkeypatch.setattr(cfo_routes.report_file_repo, "insert_report_file", lambda *a, **k: uuid.uuid4())
    monkeypatch.setattr(cfo_routes, "read_csv_file", lambda contents: (None, None))

    def slow_ingest(*args, **kwargs):
        time.sleep(_SLOW_SECONDS)  # stands in for parsing + persisting a large file
        return SimpleNamespace(
            ingestion_run_id=uuid.uuid4(), row_count_read=1, row_count_accepted=1, row_count_rejected=0,
            row_count_duplicate=0, persisted_sales_line_ids=(),
        )

    monkeypatch.setattr(cfo_routes, "ingest_and_persist", slow_ingest)
    adapter_id = next(iter(cfo_routes.ADAPTER_REGISTRY))

    max_gap = 0.0
    done = asyncio.Event()

    async def heartbeat() -> None:
        nonlocal max_gap
        last = time.perf_counter()
        while not done.is_set():
            await asyncio.sleep(0.01)
            now = time.perf_counter()
            max_gap = max(max_gap, now - last)
            last = now

    beat = asyncio.create_task(heartbeat())
    await asyncio.sleep(0.05)  # let the heartbeat establish its rhythm
    upload = UploadFile(file=io.BytesIO(b"a,b\n1,2\n"), filename="settlement.csv")
    result = await cfo_routes.post_ingest(upload, marketplace="MEESHO", adapter_id=adapter_id, ctx=_ctx())
    done.set()
    await beat

    assert result["duplicate"] is False and result["rowCountAccepted"] == 1
    # Blocking on the loop makes this gap ~_SLOW_SECONDS; offloaded work leaves it near the 10 ms tick.
    assert max_gap < _SLOW_SECONDS / 2, f"event loop stalled for {max_gap:.2f}s during ingestion"
