"""Bounded reads of uploaded files.

Starlette spools a multipart file part to a temp file once it passes 1 MB, so an upload does not
sit in memory while it is received — the memory is spent at `await file.read()`. These endpoints
then need the WHOLE file in memory (the ingestion pipeline's `RawFile.rows` is a full list of
dicts; measured peak ~31x the CSV's size), so a hard cap, enforced before the read, is the
control that fits — not streaming. Oversized files fail fast with a clear 413.
"""

from __future__ import annotations

from fastapi import HTTPException, UploadFile


def _mb(n: int) -> str:
    return f"{n / (1024 * 1024):g} MB"


async def read_upload_capped(file: UploadFile, *, max_bytes: int, env_var: str) -> bytes:
    """Reads the whole upload, or raises `413` if it exceeds `max_bytes` — without loading more
    than `max_bytes + 1` bytes into memory when the size isn't known up front."""
    detail = f"File is larger than the {_mb(max_bytes)} upload limit (configurable via {env_var})."
    if file.size is not None and file.size > max_bytes:
        raise HTTPException(status_code=413, detail=detail)
    data = await file.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise HTTPException(status_code=413, detail=detail)
    return data
