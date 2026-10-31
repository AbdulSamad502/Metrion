"""M9: what can be MEASURED from a seller's product image with Pillow and integer arithmetic. No model, no I/O, no floats, no clock.

Everything is derived from the decoded pixels of the already-normalised PNG (EXIF is gone). Ratios are in per-mille (0..1000) or hundredths, every value is an `int`. The picture is worked on at a fixed
size (long side `WORK_SIDE`) so the same picture always yields the same numbers. The "subject" is whatever differs from the colour of the image border; on a busy border the subject cannot be separated
and the subject-based values are `None` (NOT_ASSESSED), never guessed. The text/watermark check is a rough heuristic and is always labelled low-confidence."""

from __future__ import annotations

import io
from typing import Any

from PIL import Image, ImageChops, ImageFilter

WORK_SIDE = 512
BG_TOLERANCE = 24  # a border pixel within this distance of the border colour counts as "plain background"
FG_THRESHOLD = 40  # a pixel further than this from the border colour is "subject"
_LAP = ImageFilter.Kernel((3, 3), [0, 1, 0, 1, -4, 1, 0, 1, 0], scale=1, offset=128)
_FG_TABLE = [0] * (FG_THRESHOLD + 1) + [255] * (255 - FG_THRESHOLD)
_EDGE_TABLE = [255 if abs(v - 128) > 24 else 0 for v in range(256)]


def _pct(hist: list[int], n: int, permille: int) -> int:
    """The value below which `permille`/1000 of the pixels lie."""
    need, run = n * permille // 1000, 0
    for v, c in enumerate(hist):
        run += c
        if run > need:
            return v
    return 255


def _decode(data: bytes) -> tuple[Image.Image, int, int, int]:
    im = Image.open(io.BytesIO(data))
    im.load()
    w, h = im.size
    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
        rgba = im.convert("RGBA")
        base = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        base.alpha_composite(rgba)
        im = base
    im = im.convert("RGB")
    long_side = max(w, h)
    nw, nh = max(1, w * WORK_SIDE // long_side), max(1, h * WORK_SIDE // long_side)
    return im.resize((nw, nh), Image.Resampling.LANCZOS), w, h, len(data)


def _fingerprint(im: Image.Image, gray: Image.Image) -> dict[str, Any]:
    """A small perceptual fingerprint for near-duplicate detection: a 64-bit difference hash (does each pixel of a 9 x 8 greyscale thumbnail get darker to its right?) and an 8 x 8 colour thumbnail.
    Both are integers and depend only on the pixels, so the same picture always gives the same fingerprint, however it was resized or re-encoded."""
    px = list(gray.resize((9, 8), Image.Resampling.LANCZOS).tobytes())
    bits = 0
    for r in range(8):
        for c in range(8):
            bits = (bits << 1) | (1 if px[r * 9 + c] > px[r * 9 + c + 1] else 0)
    return {"dhash": bits, "thumb": list(im.resize((8, 8), Image.Resampling.BOX).tobytes())}


def _strips(im: Image.Image, b: int) -> list[Image.Image]:
    w, h = im.size
    return [im.crop((0, 0, w, b)), im.crop((0, h - b, w, h)), im.crop((0, 0, b, h)), im.crop((w - b, 0, w, h))]


def measure(data: bytes) -> dict[str, Any]:
    """All measurements for one normalised image. Raises on bytes Pillow cannot decode (the upload path already refuses those)."""
    im, w, h, size = _decode(data)
    nw, nh = im.size
    out: dict[str, Any] = {"width": w, "height": h, "bytes": size, "long_side": max(w, h), "aspect_x100": w * 100 // h, "megapixels_x100": w * h // 10_000}
    gray = im.convert("L")
    out["fingerprint"] = _fingerprint(im, gray)
    gh = gray.histogram()
    n = nw * nh
    out["mean_luma"] = sum(i * c for i, c in enumerate(gh)) // n
    # ---- subject separation from the border colour ---------------------------------------------------------------------------------------------------------
    b = max(2, min(nw, nh) * 6 // 100)
    bg = []
    for ch in range(3):
        hist = [0] * 256
        for s in _strips(im, b):
            for i, c in enumerate(s.split()[ch].histogram()):
                hist[i] += c
        bg.append(_pct(hist, sum(hist), 500))
    diff = ImageChops.difference(im, Image.new("RGB", im.size, tuple(bg)))
    r, g, bl = diff.split()
    mx = ImageChops.lighter(ImageChops.lighter(r, g), bl)
    border_hist = [0] * 256
    for s in _strips(mx, b):
        for i, c in enumerate(s.histogram()):
            border_hist[i] += c
    out["border_color"] = bg
    out["border_plain_permille"] = sum(border_hist[: BG_TOLERANCE + 1]) * 1000 // max(1, sum(border_hist))
    mask = mx.point(_FG_TABLE).filter(ImageFilter.MedianFilter(5))
    mh = mask.histogram()
    fg, bgn = mh[255], mh[0]
    out["subject_pixels_permille"] = fg * 1000 // n
    plain = out["border_plain_permille"] >= 750
    out["plain_background"] = plain
    out["subject_isolated"] = bool(plain and fg and out["subject_pixels_permille"] >= 20)
    # ---- the main subject (marks separated from it by a clear gap are reported as a possible overlay, not counted as the product) -----------------------------
    box = _main_box(mask, nw, nh) if out["subject_isolated"] else None
    out["overlay"] = _overlay(mask, nw, nh, box) if box else "NOT_ASSESSED"
    # ---- sharpness: variance of the Laplacian over the subject (or the whole picture when there is no isolated subject); blur removes strong edges --------------
    region = gray.crop(box) if box else gray
    lh = region.filter(_LAP).histogram()
    ln = region.size[0] * region.size[1]
    out["sharpness"] = sum(c * (i - 128) ** 2 for i, c in enumerate(lh)) // ln
    # ---- exposure measured on the subject region (a white backdrop must not read as over-exposed) ------------------------------------------------------------
    rh = region.histogram()
    rn = region.size[0] * region.size[1]
    out["subject_mean_luma"] = sum(i * c for i, c in enumerate(rh)) // rn
    out["dark_clip_permille"] = sum(rh[:11]) * 1000 // rn
    out["bright_clip_permille"] = sum(rh[250:]) * 1000 // rn
    out["contrast_range"] = _pct(rh, rn, 950) - _pct(rh, rn, 50)
    # ---- framing ----------------------------------------------------------------------------------------------------------------------------------------
    if box:
        x0, y0, x1, y1 = box
        out["subject_box_permille"] = (x1 - x0) * (y1 - y0) * 1000 // n
        out["center_offset_permille"] = max(abs((x0 + x1) * 500 // nw - 500), abs((y0 + y1) * 500 // nh - 500))
        edge = 15  # per-mille of the frame
        out["edges_touched"] = sum([x0 * 1000 // nw <= edge, y0 * 1000 // nh <= edge, (nw - x1) * 1000 // nw <= edge, (nh - y1) * 1000 // nh <= edge])
        edges_all = gray.filter(_LAP).point(_EDGE_TABLE)
        busy = ImageChops.darker(edges_all, ImageChops.invert(mask)).histogram()[255]  # strong edges among the pixels that are NOT subject
        out["background_busy_permille"] = busy * 1000 // max(1, bgn)
    else:
        out["subject_box_permille"] = out["center_offset_permille"] = out["edges_touched"] = out["background_busy_permille"] = None
    return out


def _runs(mask: Image.Image, nh: int, nw: int) -> list[tuple[int, int, int]]:
    """Horizontal runs of rows that hold subject pixels, as (first row, last row, subject pixels); runs closer than 1.5% of the height are one run."""
    per_row = list(mask.resize((1, nh), Image.Resampling.BOX).tobytes())
    runs: list[list[int]] = []
    gap_max = max(1, nh * 15 // 1000)
    for y, v in enumerate(per_row):
        if v * nw // 255 < 1:
            continue
        if runs and y - runs[-1][1] <= gap_max + 1:
            runs[-1][1], runs[-1][2] = y, runs[-1][2] + v
        else:
            runs.append([y, y, v])
    return [(a, b, c) for a, b, c in runs]


def _main_box(mask: Image.Image, nw: int, nh: int) -> tuple[int, int, int, int] | None:
    runs = _runs(mask, nh, nw)
    if not runs:
        return None
    y0, y1, _ = max(runs, key=lambda r: r[2])
    box = mask.crop((0, y0, nw, y1 + 1)).getbbox()
    return None if box is None else (box[0], y0, box[2], y1 + 1)


def _overlay(mask: Image.Image, nw: int, nh: int, box: tuple[int, int, int, int]) -> str:
    """Rough check for text, a logo or a watermark on a plain backdrop: a mark in the top or bottom 15% of the frame, separated from the main subject by a clear gap. It cannot read text; it can only
    notice marks away from the product. `POSSIBLE_OVERLAY` asks the seller to look; `NOT_DETECTED` is NOT a statement that the image has no text."""
    for y0, y1, _ in _runs(mask, nh, nw):
        if (y0, y1 + 1) == (box[1], box[3]):
            continue
        if (y1 + 1) * 1000 // nh <= 150 or y0 * 1000 // nh >= 850:
            return "POSSIBLE_OVERLAY"
    return "NOT_DETECTED"
