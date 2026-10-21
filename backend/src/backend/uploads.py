"""Bounded reads of uploaded files.

Starlette spools a multipart file part to a temp file once it passes 1 MB, so an upload does not
sit in memory while it is received — the memory is spent at `await file.read()`. These endpoints
then need the WHOLE file in memory (the ingestion pipeline's `RawFile.rows` is a full list of
dicts; measured peak ~31x the CSV's size), so a hard cap, enforced before the read, is the
control that fits — not streaming. Oversized files fail fast with a clear 413.
"""

from __future__ import annotations

from pathlib import Path

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


_BLOCK = 1024 * 1024


async def save_upload_capped(file: UploadFile, dest: "Path", *, max_bytes: int, env_var: str) -> tuple[str, int]:
    """Stream an upload to `dest` in 1 MiB blocks while hashing it, so memory never holds more than one block no matter how
    large the file is. Returns `(sha256 hex, byte size)`. Raises 413 (and removes the partial file) past `max_bytes`."""
    import hashlib

    detail = f"File is larger than the {_mb(max_bytes)} upload limit (configurable via {env_var})."
    if file.size is not None and file.size > max_bytes:
        raise HTTPException(status_code=413, detail=detail)
    digest = hashlib.sha256()
    total = 0
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        with dest.open("wb") as out:
            while True:
                block = await file.read(_BLOCK)
                if not block:
                    break
                total += len(block)
                if total > max_bytes:
                    raise HTTPException(status_code=413, detail=detail)
                digest.update(block)
                out.write(block)
    except BaseException:
        dest.unlink(missing_ok=True)
        raise
    return digest.hexdigest(), total
