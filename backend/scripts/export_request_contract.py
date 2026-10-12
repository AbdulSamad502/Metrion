"""Export the backend's request contract (what each `/api/v1` route accepts) for the frontend's contract tests.

    python backend/scripts/export_request_contract.py            # rewrite frontend/test-support/requestContract.json
    python backend/scripts/export_request_contract.py --check    # exit 1 if the committed file is stale

Only the request side is exported: JSON body schemas, query parameters and the schemas they reference. Response bodies are not described by the API
(handlers return plain dicts), so they are covered by the per-endpoint response contracts instead (see `contracts/`).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

os.environ.setdefault("CLERK_SECRET_KEY", "sk_test_dummy")
os.environ.setdefault("CLERK_WEBHOOK_SECRET", "whsec_MfKQ9r8GKYqrTwjUPD8ILPZIo2LaLaSw")
os.environ.setdefault("CLERK_JWT_KEY", "-----BEGIN PUBLIC KEY-----\nX\n-----END PUBLIC KEY-----")
os.environ.setdefault("FRONTEND_ORIGIN", "http://localhost:3000")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend" / "src"))
TARGET = ROOT / "frontend" / "test-support" / "requestContract.json"


def _refs(node: Any, out: set[str]) -> None:
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str):
            out.add(ref.rsplit("/", 1)[-1])
        for v in node.values():
            _refs(v, out)
    elif isinstance(node, list):
        for v in node:
            _refs(v, out)


def build() -> dict[str, Any]:
    from backend.main import app

    spec = app.openapi()
    schemas = spec.get("components", {}).get("schemas", {})
    routes: dict[str, Any] = {}
    needed: set[str] = set()
    for path, methods in sorted(spec["paths"].items()):
        if not path.startswith("/api/v1"):
            continue
        for method, op in sorted(methods.items()):
            content = (op.get("requestBody") or {}).get("content", {})
            body = content.get("application/json", {}).get("schema")
            multipart = "multipart/form-data" in content
            query = sorted(p["name"] for p in op.get("parameters", []) if p.get("in") == "query")
            required_query = sorted(p["name"] for p in op.get("parameters", []) if p.get("in") == "query" and p.get("required"))
            entry: dict[str, Any] = {"query": query, "requiredQuery": required_query}
            if body is not None:
                entry["body"] = body
                _refs(body, needed)
            if multipart:
                entry["multipart"] = True
            routes[f"{method.upper()} {path}"] = entry
    # transitive closure of referenced component schemas
    resolved: dict[str, Any] = {}
    queue = sorted(needed)
    while queue:
        name = queue.pop()
        if name in resolved or name not in schemas:
            continue
        resolved[name] = schemas[name]
        more: set[str] = set()
        _refs(schemas[name], more)
        queue.extend(sorted(more - set(resolved)))
    return {"routes": routes, "schemas": dict(sorted(resolved.items()))}


def render() -> str:
    return json.dumps(build(), indent=1, sort_keys=True) + "\n"


if __name__ == "__main__":
    text = render()
    if "--check" in sys.argv:
        sys.exit(0 if TARGET.exists() and TARGET.read_text(encoding="utf-8") == text else 1)
    TARGET.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {TARGET} ({len(text)} bytes)")
