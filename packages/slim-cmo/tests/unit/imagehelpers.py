"""Real image bytes for the P6 tests (Pillow builds them; nothing is downloaded and no model is involved)."""

from __future__ import annotations

import io

from PIL import Image
from PIL.PngImagePlugin import PngInfo

from slim_cmo.imaging.normalize import ImageLimits

LIMITS = ImageLimits(max_bytes=5_000_000, max_pixels=4_000_000, allowed_types=frozenset({"image/jpeg", "image/png", "image/webp"}))
SECRET = b"SECRET-GPS-AND-OWNER-NAME"


def gradient(size=(40, 20)) -> Image.Image:
    img = Image.new("RGB", size)
    img.putdata([(x * 6 % 256, y * 12 % 256, (x + y) * 4 % 256) for y in range(size[1]) for x in range(size[0])])
    return img


def jpeg_with_exif(size=(40, 20), orientation: int | None = None, comment: bool = True) -> bytes:
    img = gradient(size)
    exif = Image.Exif()
    exif[0x010F] = "TestCameraMake"          # Make
    exif[0x0132] = "2026:10:05 10:11:12"      # DateTime
    if orientation is not None:
        exif[0x0112] = orientation
    gps = exif.get_ifd(0x8825)                # GPS IFD
    gps[1] = "N"
    gps[3] = "E"
    gps[29] = "2026:10:05"
    out = io.BytesIO()
    kwargs = {"comment": SECRET} if comment else {}
    img.save(out, format="JPEG", exif=exif, **kwargs)
    return out.getvalue()


def png_with_text(size=(30, 30)) -> bytes:
    info = PngInfo()
    info.add_text("Author", SECRET.decode())
    out = io.BytesIO()
    gradient(size).save(out, format="PNG", pnginfo=info)
    return out.getvalue()


def png_bytes(size=(30, 30), mode="RGB") -> bytes:
    out = io.BytesIO()
    Image.new(mode, size).save(out, format="PNG")
    return out.getvalue()


def webp_bytes(size=(30, 30)) -> bytes:
    out = io.BytesIO()
    gradient(size).save(out, format="WEBP")
    return out.getvalue()


def animated_gif() -> bytes:
    frames = [Image.new("P", (10, 10), i) for i in range(3)]
    out = io.BytesIO()
    frames[0].save(out, format="GIF", save_all=True, append_images=frames[1:])
    return out.getvalue()


def animated_webp() -> bytes:
    frames = [gradient((16, 16)), Image.new("RGB", (16, 16), (200, 10, 10))]
    out = io.BytesIO()
    frames[0].save(out, format="WEBP", save_all=True, append_images=frames[1:], duration=50)
    return out.getvalue()


def bomb_png(size=(20000, 20000)) -> bytes:
    """A tiny file whose header declares a huge picture (a 1-bit all-zero image compresses to almost nothing)."""
    out = io.BytesIO()
    Image.new("1", size).save(out, format="PNG")
    return out.getvalue()
