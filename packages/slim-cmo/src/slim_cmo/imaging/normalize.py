"""Upload validation and normalisation (spec §5 `seller_image_asset`, §6.2; P6 decisions 5, 8, 9).

Pipeline step "validate -> normalise / strip EXIF -> hash": the ORIGINAL upload is never stored and never
sent to a provider. What is stored and analysed is a freshly re-encoded PNG built from the decoded pixels
only, so EXIF (including GPS and capture time), ICC profiles, XMP, comments, thumbnails, trailing bytes and any
polyglot payload are gone. The EXIF orientation is applied to the pixels BEFORE the metadata is dropped, so
the picture is not rotated wrong.

Refused (stable `code`, never the file's contents): empty, over the byte limit, a type outside the configured
allow-list, bytes that are not that type (a mislabelled upload), a corrupt or truncated file, an animated file,
and a decoded size over the pixel limit - checked from the header BEFORE any pixel is decoded, so a tiny file
that expands to billions of pixels cannot exhaust memory.

All three limits are REQUIRED configuration passed in (`ImageLimits`); nothing here has a default. The hash is of
the NORMALISED bytes: the same picture uploaded with different metadata is one asset.
"""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass

from PIL import Image, ImageOps

NORMALISED_CONTENT_TYPE = "image/png"

_SIGNATURES: tuple[tuple[bytes, str], ...] = ((b"\xff\xd8\xff", "image/jpeg"), (b"\x89PNG\r\n\x1a\n", "image/png"))
_FORMAT_TO_TYPE = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}


class ImageRejected(Exception):
    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


@dataclass(frozen=True, slots=True)
class ImageLimits:
    max_bytes: int
    max_pixels: int
    allowed_types: frozenset[str]

    def __post_init__(self) -> None:
        for name in ("max_bytes", "max_pixels"):
            v = getattr(self, name)
            if type(v) is not int or v < 1:
                raise ValueError(f"{name} must be a positive integer")
        if not self.allowed_types:
            raise ValueError("allowed_types must not be empty")


@dataclass(frozen=True, slots=True)
class NormalizedImage:
    data: bytes
    content_type: str
    sha256: str
    width: int
    height: int
    source_type: str


def sniff_type(data: bytes) -> str | None:
    """The type the BYTES actually are (magic numbers), regardless of what the client claimed."""
    for sig, kind in _SIGNATURES:
        if data.startswith(sig):
            return kind
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def normalize_image(data: bytes, declared_type: str, limits: ImageLimits) -> NormalizedImage:
    if not data:
        raise ImageRejected("EMPTY", "the file is empty")
    if len(data) > limits.max_bytes:
        raise ImageRejected("TOO_LARGE", "the file is larger than the configured upload limit")
    declared = (declared_type or "").split(";")[0].strip().lower()
    if declared not in limits.allowed_types:
        raise ImageRejected("TYPE_NOT_ALLOWED", "this image type is not accepted")
    sniffed = sniff_type(data)
    if sniffed is None:
        raise ImageRejected("NOT_AN_IMAGE", "the file is not a supported image")
    if sniffed != declared:
        raise ImageRejected("TYPE_MISMATCH", "the file content does not match its declared type")
    if sniffed not in limits.allowed_types:
        raise ImageRejected("TYPE_NOT_ALLOWED", "this image type is not accepted")

    try:
        img = Image.open(io.BytesIO(data))  # lazy: reads the header only
        width, height = img.size
        fmt_type = _FORMAT_TO_TYPE.get(str(img.format))
        if fmt_type != sniffed:
            raise ImageRejected("TYPE_MISMATCH", "the file content does not match its declared type")
        if width < 1 or height < 1 or width * height > limits.max_pixels:
            raise ImageRejected("TOO_MANY_PIXELS", "the image dimensions exceed the configured limit")
        if getattr(img, "n_frames", 1) > 1:
            raise ImageRejected("ANIMATED_NOT_SUPPORTED", "animated images are not supported")
        img.load()  # full decode - raises on truncated or corrupt data
    except ImageRejected:
        raise
    except Image.DecompressionBombError:
        raise ImageRejected("TOO_MANY_PIXELS", "the image dimensions exceed the configured limit") from None
    except (OSError, SyntaxError, ValueError, EOFError, MemoryError):
        raise ImageRejected("CORRUPT", "the image could not be decoded") from None

    oriented = ImageOps.exif_transpose(img) or img  # apply orientation to the pixels, THEN drop all metadata
    if oriented.mode not in ("RGB", "RGBA", "L"):
        has_alpha = "A" in oriented.mode or "transparency" in oriented.info
        oriented = oriented.convert("RGBA" if has_alpha else "RGB")
    clean = Image.frombytes(oriented.mode, oriented.size, oriented.tobytes())  # pixels only: no `info`, EXIF, ICC, XMP
    out = io.BytesIO()
    clean.save(out, format="PNG")
    normalized = out.getvalue()
    return NormalizedImage(
        data=normalized,
        content_type=NORMALISED_CONTENT_TYPE,
        sha256=hashlib.sha256(normalized).hexdigest(),
        width=clean.size[0],
        height=clean.size[1],
        source_type=sniffed,
    )
