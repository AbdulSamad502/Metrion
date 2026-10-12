"""Machine-readable error classification, added BESIDE the existing `detail` (issue 24).

The API's error bodies were `{"detail": <string | object | list>}`. 79 sites still return a bare string, which a program cannot classify (validation? missing data? configuration?
a dependency down?). Rewriting those bodies would break every consumer that reads `detail`, so nothing in `detail` changes. Every error response now ALSO carries the classification in RESPONSE HEADERS (the body stays exactly what it was: several consumers and tests pin whole bodies, so an extra
body key is not backward compatible):

    X-Error-Kind: conflict          X-Error-Code: CLIENT_REQUEST_ID_REUSED (only when `detail` is an object with a `code`)       X-Request-ID: ...

`kind` is one of: validation, authentication, permission, entitlement, not_found, conflict, too_large, rate_limited, configuration, unavailable, server.
  * derived from the HTTP status, and, when `detail` is an object with a `code`, `code` is echoed and a code naming missing configuration (`..._NOT_CONFIGURED`, `CONFIG_MISSING`,
    `..._MISSING_CONFIG`) turns a 503 into `configuration` instead of `unavailable`;
  * `requestId` is the `X-Request-ID` of the same response, so a support report can be matched to the log line.
Nothing here ever includes exception text."""

from __future__ import annotations

import re
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.observability import REQUEST_ID

_BY_STATUS = {
    400: "validation", 401: "authentication", 402: "entitlement", 403: "permission", 404: "not_found", 405: "not_found", 409: "conflict", 413: "too_large",
    415: "validation", 422: "validation", 429: "rate_limited", 501: "unavailable", 502: "unavailable", 503: "unavailable", 504: "unavailable",
}
_CONFIG_CODE = re.compile(r"(NOT_CONFIGURED|CONFIG_MISSING|MISSING_CONFIG)", re.IGNORECASE)


def error_info(status: int, detail: Any, request_id: str | None = None) -> dict[str, Any]:
    code = detail.get("code") if isinstance(detail, dict) and isinstance(detail.get("code"), str) else None
    kind = _BY_STATUS.get(status, "server" if status >= 500 else "validation")
    if status >= 500 and code and _CONFIG_CODE.search(code):
        kind = "configuration"
    info: dict[str, Any] = {"kind": kind, "status": status}
    if code:
        info["code"] = code
    rid = request_id or REQUEST_ID.get()
    if rid:
        info["requestId"] = rid
    return info


def error_headers(status: int, detail: Any, extra: dict[str, str] | None = None, request_id: str | None = None) -> dict[str, str]:
    info = error_info(status, detail, request_id)
    headers = dict(extra or {})
    headers["X-Error-Kind"] = info["kind"]
    if "code" in info:
        headers["X-Error-Code"] = info["code"]
    return headers


def install(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def http_exception(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=error_headers(exc.status_code, exc.detail, getattr(exc, "headers", None)))

    @app.exception_handler(RequestValidationError)
    async def validation_exception(_request: Request, exc: RequestValidationError) -> JSONResponse:
        from fastapi.encoders import jsonable_encoder

        detail = jsonable_encoder(exc.errors())  # FastAPI's own 422 body, unchanged
        return JSONResponse({"detail": detail}, status_code=422, headers=error_headers(422, detail))

    @app.exception_handler(Exception)
    async def unexpected(request: Request, exc: Exception) -> JSONResponse:
        import logging

        rid = request.scope.get("request_id")
        logging.getLogger("backend.errors").error("unhandled %s", type(exc).__name__, exc_info=exc)  # server side only; the client gets no exception text
        return JSONResponse({"detail": "Internal Server Error"}, status_code=500, headers=error_headers(500, None, {"X-Request-ID": rid} if rid else None, rid))
