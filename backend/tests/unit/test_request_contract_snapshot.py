"""The request contract the frontend's tests validate against (`frontend/test-support/requestContract.json`) must be what the backend accepts today.

If this fails, a route's request schema changed: regenerate the file with `python backend/scripts/export_request_contract.py`, then run the frontend tests; any
screen that now sends a request the backend would refuse fails there (see `frontend/test-support/setup.ts`)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "backend" / "scripts" / "export_request_contract.py"
SNAPSHOT = ROOT / "frontend" / "test-support" / "requestContract.json"


def _exporter():
    spec = importlib.util.spec_from_file_location("export_request_contract", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_committed_contract_is_what_the_backend_exports_now() -> None:
    assert SNAPSHOT.read_text(encoding="utf-8") == _exporter().render(), "stale: run `python backend/scripts/export_request_contract.py`"


def test_the_contract_carries_the_routes_the_frontend_depends_on() -> None:
    routes = json.loads(SNAPSHOT.read_text(encoding="utf-8"))["routes"]
    assert len(routes) >= 90
    cash = routes["POST /api/v1/cfo/cash-reconciliation"]["body"]
    assert cash["$ref"].endswith("CashReconciliationHttpRequest")
    assert "requiredQuery" in routes["GET /api/v1/ci/alerts"]
