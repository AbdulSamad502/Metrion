"""Request-body size limit, enforced BEFORE the body is parsed or spooled.

`uploads.read_upload_capped` protects memory at `await file.read()`, but by then Starlette's
multipart parser has already received the whole request and spooled it to a temp file on disk —
an unbounded request still costs bandwidth and disk. This ASGI middleware closes that gap for the
upload routes:

- **Content-Length present and too large** -> `413` immediately; the app (auth, form parsing,
  temp-file spooling) never runs.
- **No Content-Length (chunked / unknown size)** -> bytes are counted as they stream in; the
  moment the running total passes the limit the middleware answers `413` itself and tells the app
  the client disconnected, so no more of the body is parsed or spooled. (It answers itself rather
  than raising from `receive` because FastAPI's body-parsing handler converts arbitrary
  exceptions raised there into a generic 400.)

It is a defence in depth and NOT a substitute for a reverse proxy: the ASGI server has already
read what the socket delivered by the time this runs. The deployment layer should also cap the
request body (see backend/README.md, "Request-body limits"). The per-route limit in
`uploads.read_upload_capped` (exact file size, clear message) stays as the authoritative check.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

# A multipart upload adds a boundary and part headers around the file's bytes (a few hundred
# bytes for one file part). The route's own check enforces the exact file-size limit; this slack
# only keeps legitimate at-limit files from being cut off by envelope overhead.
MULTIPART_OVERHEAD_BYTES = 64 * 1024

_BODY_METHODS = frozenset({"POST", "PUT", "PATCH"})


class RequestBodyLimitMiddleware:
    def __init__(self, app: Any, *, limits: Mapping[str, int], overhead_bytes: int = MULTIPART_OVERHEAD_BYTES) -> None:
        self.app = app
        self._max_body = {path: limit + overhead_bytes for path, limit in limits.items()}

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        max_body = self._max_body.get(scope.get("path", "")) if scope["type"] == "http" else None
        if max_body is None or scope["method"] not in _BODY_METHODS:
            await self.app(scope, receive, send)
            return

        declared = dict(scope["headers"]).get(b"content-length")
        if declared is not None:
            try:
                declared_bytes = int(declared)
            except ValueError:
                await _respond(send, 400, "Invalid Content-Length header.")
                return
            if declared_bytes > max_body:
                await _respond(send, 413, _message(max_body))
                return

        received = 0
        answered = False

        async def limited_receive() -> dict[str, Any]:
            nonlocal received, answered
            if answered:
                return {"type": "http.disconnect"}
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > max_body:
                    answered = True
                    await _respond(send, 413, _message(max_body))
                    return {"type": "http.disconnect"}  # stop the app reading/spooling any more
            return message

        async def guarded_send(message: dict[str, Any]) -> None:
            if answered:  # we already replied 413; drop whatever the aborted app tries to send
                return
            await send(message)

        try:
            await self.app(scope, limited_receive, guarded_send)
        except Exception:
            if not answered:
                raise
            # the app was told the client disconnected and may raise (e.g. ClientDisconnect) — expected


def _message(max_body: int) -> str:
    return f"Request body is larger than the {max_body / (1024 * 1024):g} MB limit for this endpoint."


async def _respond(send: Any, status: int, detail: str) -> None:
    body = ('{"detail":"%s"}' % detail).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
        }
    )
    await send({"type": "http.response.body", "body": body})
