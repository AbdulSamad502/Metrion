"""Image quality gate and duplicate hashes — competitor-intelligence-agent.md §6.22.1–§6.22.2 (C36).

Deterministic and local: Pillow only, no model, no network. It runs on the raw bytes *before*
any vision model sees them, so a clearly unusable image costs nothing and stores no snapshot.

* **Type is established by content**, not by file extension or the client's MIME type (§7
  rule 16). Only PNG, JPEG and WebP decode; anything else is rejected with a named reason.
* **Size** is capped by the caller's configured maximum.
* **Legibility** — a minimum short side, and a sharpness measure (variance of an edge filter on
  the greyscale image). The thresholds are configuration, deliberately conservative defaults
  (A13): they reject the obviously unreadable and let borderline images through, because the
  seller-confirmation step (C37) is the backstop for what the gate misses.
* **Duplicates** — SHA-256 for exact duplicates and a 64-bit average hash for near-duplicates.

"Is this actually a marketplace listing?" cannot be answered from pixels without a model; that
check lives in the intake pipeline after extraction (an image that yields none of price, title or
rating is `REJECTED_NOT_A_LISTING`).
"""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass
from enum import Enum

from PIL import Image, ImageFilter, ImageStat, UnidentifiedImageError

ALLOWED_FORMATS = frozenset({"PNG", "JPEG", "WEBP"})
DEFAULT_MIN_SHORT_SIDE_PX = 320
DEFAULT_MIN_SHARPNESS = 25.0
NEAR_DUPLICATE_MAX_HAMMING = 5


class QualityStatus(str, Enum):
    ACCEPTED = "ACCEPTED"
    REJECTED_LOW_QUALITY = "REJECTED_LOW_QUALITY"
    REJECTED_NOT_A_LISTING = "REJECTED_NOT_A_LISTING"


class QualityReason(str, Enum):
    EMPTY = "EMPTY"
    TOO_LARGE = "TOO_LARGE"
    NOT_AN_IMAGE = "NOT_AN_IMAGE"
    UNSUPPORTED_TYPE = "UNSUPPORTED_TYPE"
    TOO_SMALL = "TOO_SMALL"
    TOO_BLURRY = "TOO_BLURRY"


_SELLER_MESSAGES: dict[QualityReason, str] = {
    QualityReason.EMPTY: "the file is empty",
    QualityReason.TOO_LARGE: "the file is larger than the allowed size",
    QualityReason.NOT_AN_IMAGE: "it is not an image I can read",
    QualityReason.UNSUPPORTED_TYPE: "only PNG, JPEG or WebP screenshots are supported",
    QualityReason.TOO_SMALL: "the image is too small to read the details",
    QualityReason.TOO_BLURRY: "the image is too blurry to read the price and details",
}


@dataclass(frozen=True, slots=True)
class QualityVerdict:
    status: QualityStatus
    reason: QualityReason | None
    sha256: str
    perceptual_hash: str | None
    width: int | None = None
    height: int | None = None

    @property
    def accepted(self) -> bool:
        return self.status is QualityStatus.ACCEPTED

    @property
    def seller_message(self) -> str | None:
        return _SELLER_MESSAGES[self.reason] if self.reason is not None else None


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def average_hash(image: Image.Image) -> str:
    """64-bit average hash as 16 hex chars: 8x8 greyscale, each pixel above the mean is a 1."""
    small = image.convert("L").resize((8, 8), Image.Resampling.LANCZOS)
    pixels = list(small.getdata())
    mean = sum(pixels) / len(pixels)
    bits = 0
    for value in pixels:
        bits = (bits << 1) | (1 if value > mean else 0)
    return f"{bits:016x}"


def hamming_distance(a: str, b: str) -> int:
    return bin(int(a, 16) ^ int(b, 16)).count("1")


def is_near_duplicate(a: str, b: str) -> bool:
    return hamming_distance(a, b) <= NEAR_DUPLICATE_MAX_HAMMING


def assess_image(
    data: bytes,
    *,
    max_bytes: int,
    min_short_side_px: int = DEFAULT_MIN_SHORT_SIDE_PX,
    min_sharpness: float = DEFAULT_MIN_SHARPNESS,
) -> QualityVerdict:
    digest = sha256_hex(data)

    def reject(reason: QualityReason, *, size: tuple[int, int] | None = None, phash: str | None = None) -> QualityVerdict:
        return QualityVerdict(
            QualityStatus.REJECTED_LOW_QUALITY,
            reason,
            digest,
            phash,
            width=size[0] if size else None,
            height=size[1] if size else None,
        )

    if not data:
        return reject(QualityReason.EMPTY)
    if len(data) > max_bytes:
        return reject(QualityReason.TOO_LARGE)

    try:
        with Image.open(io.BytesIO(data)) as probe:
            fmt = probe.format
            probe.load()
            image = probe.copy()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        return reject(QualityReason.NOT_AN_IMAGE)

    if fmt not in ALLOWED_FORMATS:
        return reject(QualityReason.UNSUPPORTED_TYPE)

    size = image.size
    phash = average_hash(image)
    if min(size) < min_short_side_px:
        return reject(QualityReason.TOO_SMALL, size=size, phash=phash)

    edges = image.convert("L").filter(ImageFilter.FIND_EDGES)
    # The filter writes artefacts on the outermost pixels; measure the interior only.
    interior = edges.crop((2, 2, edges.width - 2, edges.height - 2))
    sharpness = ImageStat.Stat(interior).var[0]
    if sharpness < min_sharpness:
        return reject(QualityReason.TOO_BLURRY, size=size, phash=phash)

    return QualityVerdict(QualityStatus.ACCEPTED, None, digest, phash, width=size[0], height=size[1])
