"""Where a submitted screenshot's bytes actually live, keyed by the opaque `image_ref` an
evidence-upload endpoint hands back (see `backend/api/v1/ci.py`'s `/evidence` route). This
package never assumes a storage backend — `ImageStore` is a `Protocol`, the same seam
pattern as `Fetcher`/`Parser`/`VisionExtractor`, so the real backend (local disk today,
object storage later) is wired at the composition root, never imported by orchestration
code or tests directly.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol


class ImageNotFound(Exception):
    pass


class ImageStore(Protocol):
    def read(self, image_ref: str) -> bytes: ...


class LocalDiskImageStore:
    """Reads from the same directory `backend/api/v1/ci.py`'s upload endpoint writes to
    (`ci_evidence_storage_dir()`) — this package takes that directory as a plain string at
    construction time rather than importing `backend.config`, keeping the dependency
    direction backend -> competitor-intelligence, never the reverse."""

    def __init__(self, base_dir: str) -> None:
        self._base_dir = Path(base_dir)

    def read(self, image_ref: str) -> bytes:
        path = self._base_dir / image_ref
        # `image_ref` is always a bare filename minted by the upload endpoint (uuid4 + a
        # suffix taken from the original filename's extension only) — never a path a client
        # supplies directly, so this is not a client-controlled path-traversal surface. The
        # resolved-path check is still here as defence in depth against a future caller that
        # forwards a less-trusted string.
        resolved = path.resolve()
        if resolved.parent != self._base_dir.resolve():
            raise ImageNotFound(f"'{image_ref}' does not resolve inside the evidence store")
        if not resolved.is_file():
            raise ImageNotFound(f"no evidence image found for ref '{image_ref}'")
        return resolved.read_bytes()
