"""Local-disk store for NORMALISED seller images (spec §5 `seller_image_asset.storage_uri`; P6 decision 6).

Content-addressed and tenant-partitioned: `<base>/<tenant_id>/<sha256[:2]>/<sha256>.png`. A path is ALWAYS built
from a validated tenant UUID and a validated 64-hex digest - never from a client-supplied name or an arbitrary
stored string - so there is no path traversal. The URI stored in the database is `local://<tenant_id>/<sha256>.png`
(no filesystem path, so the base directory can move). Writes are atomic (temp file then rename); a read verifies
the bytes still hash to their name. The base directory is REQUIRED configuration with no default.
"""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from pathlib import Path
from uuid import UUID

_SHA = re.compile(r"^[0-9a-f]{64}$")
_URI = re.compile(r"^local://([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/([0-9a-f]{64})\.png$")


class ImageStoreError(Exception):
    pass


class LocalDiskImageStore:
    def __init__(self, base_dir: str) -> None:
        if not isinstance(base_dir, str) or not base_dir.strip():
            raise ValueError("base_dir is required (no default)")
        self._base = Path(base_dir).resolve()

    def _path(self, tenant_id: UUID, sha256: str) -> Path:
        if not _SHA.match(sha256):
            raise ImageStoreError("invalid content hash")
        path = (self._base / str(tenant_id) / sha256[:2] / f"{sha256}.png").resolve()
        if self._base not in path.parents:
            raise ImageStoreError("path escapes the storage directory")
        return path

    @staticmethod
    def uri(tenant_id: UUID, sha256: str) -> str:
        return f"local://{tenant_id}/{sha256}.png"

    def put(self, tenant_id: UUID, sha256: str, data: bytes) -> str:
        if hashlib.sha256(data).hexdigest() != sha256:
            raise ImageStoreError("content does not match its hash")
        path = self._path(tenant_id, sha256)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".part-")
            try:
                with os.fdopen(fd, "wb") as fh:
                    fh.write(data)
                os.replace(tmp, path)
            except BaseException:
                Path(tmp).unlink(missing_ok=True)
                raise
        return self.uri(tenant_id, sha256)

    def get(self, storage_uri: str) -> bytes:
        m = _URI.match(storage_uri or "")
        if m is None:
            raise ImageStoreError("unrecognised storage uri")
        path = self._path(UUID(m.group(1)), m.group(2))
        try:
            data = path.read_bytes()
        except OSError:
            raise ImageStoreError("stored image is not readable") from None
        if hashlib.sha256(data).hexdigest() != m.group(2):
            raise ImageStoreError("stored image failed its integrity check")
        return data
