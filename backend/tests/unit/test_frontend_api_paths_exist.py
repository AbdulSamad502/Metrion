"""Every `/api/v1/...` path the frontend calls must be a route the backend really serves.

Static and cheap: it reads the frontend's non-test sources, resolves the small `const X = "/api/v1/..."` prefixes they use, and checks each resulting path
against the paths in the FastAPI app's OpenAPI document. It cannot prove a request body is right (the integration tests do that); it catches the drift where
a screen calls a path that was renamed or never existed, which the frontend's own mocked tests cannot see.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

# `backend.main` reads these when it is imported; harmless placeholders, as in the other app-level unit tests.
os.environ.setdefault("CLERK_SECRET_KEY", "sk_test_dummy")
os.environ.setdefault("CLERK_WEBHOOK_SECRET", "whsec_MfKQ9r8GKYqrTwjUPD8ILPZIo2LaLaSw")
os.environ.setdefault("CLERK_JWT_KEY", "-----BEGIN PUBLIC KEY-----\nX\n-----END PUBLIC KEY-----")
os.environ.setdefault("FRONTEND_ORIGIN", "http://localhost:3000")

FRONTEND = Path(__file__).resolve().parents[3] / "frontend"
SOURCE_DIRS = ("app", "components", "lib")

_PREFIX_CONST = re.compile(r"""\bconst\s+([A-Za-z_][A-Za-z0-9_]*)\s*(?::\s*string\s*)?=\s*["'`](/api/v1[^"'`]*)["'`]""")
_LITERAL = re.compile(r"""(["'`])((?:\\.|(?!\1).)*?)\1""", re.DOTALL)
# A typed client whose helpers take a path relative to its `const BASE = "/api/v1/..."`, e.g. call<T>("/investigations") or post<T>(getToken, "/title-sets", ...).
_RELATIVE_CALL = re.compile(r"""\b(?:call|post|get|put|patch|del)(?:<[^>()]*(?:\([^)]*\))?[^>()]*>)?\(\s*(?:getToken,\s*)?(["'`])(/[^"'`]*)\1""")
_RUNTIME_VALUE = re.compile(r"\$\{[^}]*\}")


def _frontend_files() -> list[Path]:
    out: list[Path] = []
    for d in SOURCE_DIRS:
        for p in (FRONTEND / d).rglob("*"):
            if p.suffix in {".ts", ".tsx"} and ".test." not in p.name and "node_modules" not in p.parts:
                out.append(p)
    return out


def _template(raw: str) -> str:
    """`/api/v1/x/${id}/y?z=1` -> `/api/v1/x/{}/y`."""
    # an unterminated `${` is a nested template the literal scan cut short (an optional query string): the path ends there
    return _RUNTIME_VALUE.sub("{}", raw).split("${")[0].split("?")[0].rstrip("/")


def _called_paths() -> dict[str, str]:
    """path template (runtime values as `{}`) -> one file that calls it."""
    found: dict[str, str] = {}
    for f in _frontend_files():
        text = f.read_text(encoding="utf-8")
        where = f.relative_to(FRONTEND).as_posix()
        consts = dict(_PREFIX_CONST.findall(text))
        for m in _LITERAL.finditer(text):
            raw = m.group(2)
            for name, value in consts.items():
                raw = raw.replace("${" + name + "}", value)
            if not raw.startswith("/api/v1/"):
                continue
            path = _template(raw)
            if path in consts.values() or re.search(r"/api/v1/[a-z-]+\{\}", path):
                continue  # a bare prefix constant, or a prefix followed straight by a runtime value: the call sites resolve those
            found.setdefault(path, where)
        base = consts.get("BASE")
        if base:
            for m in _RELATIVE_CALL.finditer(text):
                found.setdefault(_template(base + m.group(2)), where)
    return found


def _served() -> list[re.Pattern[str]]:
    from backend.main import app

    # the OpenAPI document lists every served path, however the routers were included
    return [re.compile("^" + re.sub(r"\\\{[^}/]+\\\}", "[^/]+", re.escape(path.rstrip("/"))) + "$") for path in app.openapi()["paths"] if path.startswith("/api/v1")]


def test_the_scan_finds_the_frontend_calls_and_the_backend_routes() -> None:
    # a guard against either side silently coming back empty (a moved directory, a changed constant style, a router no longer included)
    assert len(_called_paths()) >= 50
    assert len(_served()) >= 90


@pytest.mark.parametrize("path,caller", sorted(_called_paths().items()))
def test_every_path_the_frontend_calls_is_served(path: str, caller: str) -> None:
    probe = path.replace("{}", "x")
    assert any(p.match(probe) for p in _served()), f"{caller} calls {path}, which no backend route serves"
