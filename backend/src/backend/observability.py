"""Request correlation ids and log redaction (Stage 4).

* Every HTTP request gets an id: the caller's `X-Request-ID` when it is a plain token (letters, digits, `-`, `_`, 8-64 chars: anything else is ignored, never echoed, so a header
  cannot inject log lines), otherwise a fresh uuid4. It is returned in the `X-Request-ID` response header and appended to every log line written while the request is handled
  (` [req=<id>]`), so a seller-reported failure can be matched to the backend log without exposing internals in the response.
* Every log message passes through `redact` before it is written: bearer tokens, JWTs, `key=`/`token=`/`secret=`/`password=` pairs, and the well-known key shapes (Clerk
  `sk_`/`whsec_`, Google `AIza...`) are replaced by `[redacted]`. Defence in depth: the code does not log secrets on purpose; this keeps a library's own message (an httpx URL, a
  driver DSN) from doing it by accident.

Pure ASGI (no BaseHTTPMiddleware task switch), and a log-record factory rather than handler filters, so it applies to every handler and format, uvicorn's included. The id
follows the request into the threadpool (context is copied); it does NOT follow work submitted to a plain `ThreadPoolExecutor`, which logs without a request id."""

from __future__ import annotations

import contextvars
import logging
import re
import uuid
from typing import Any

REQUEST_ID: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)
_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")

_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+"), "Bearer [redacted]"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]*"), "[redacted]"),
    (re.compile(r"(?i)\b(api[_-]?key|key|token|secret|password|passwd|authorization)(=|:\s*)(?!\[redacted\])[^&\s'\",;)]+"), r"\1\2[redacted]"),
    (re.compile(r"\b(?:sk|pk|rk)_(?:live|test)_[A-Za-z0-9]{6,}"), "[redacted]"),
    (re.compile(r"\bwhsec_[A-Za-z0-9+/=]{6,}"), "[redacted]"),
    (re.compile(r"\bAIza[0-9A-Za-z_-]{20,}"), "[redacted]"),
)


def redact(text: str) -> str:
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def new_request_id(candidate: str | None) -> str:
    return candidate if candidate and _SAFE_ID.match(candidate) else uuid.uuid4().hex


_installed = False


def install_logging() -> None:
    """Idempotent: wraps the log-record factory once so every record is redacted and carries the request id."""
    global _installed
    if _installed:
        return
    previous = logging.getLogRecordFactory()

    class _SafeRecord(logging.LogRecord):
        """Redacts and tags the formatted message; `msg` and `args` stay untouched, so formatters that read `args` themselves (uvicorn's access log) keep working."""

        def getMessage(self) -> str:  # noqa: N802 — the stdlib name
            message = redact(super().getMessage())
            rid = getattr(self, "request_id", None)  # captured when the record was created, not when it is formatted
            return f"{message} [req={rid}]" if rid else message

    def factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
        record = previous(*args, **kwargs)
        if type(record) is logging.LogRecord:
            record.__class__ = _SafeRecord
            record.request_id = REQUEST_ID.get()
        return record

    logging.setLogRecordFactory(factory)
    _installed = True


class RequestIdMiddleware:
    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        incoming = next((v.decode("latin-1") for k, v in scope["headers"] if k == b"x-request-id"), None)
        rid = new_request_id(incoming)
        scope["request_id"] = rid  # outer handlers (the 500 handler runs outside this middleware, after the context variable is reset) read it from the shared scope
        token = REQUEST_ID.set(rid)

        async def send_with_id(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                message = {**message, "headers": [*message.get("headers", []), (b"x-request-id", rid.encode())]}
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            REQUEST_ID.reset(token)
