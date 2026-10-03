"""Upload validation + normalisation (spec §6.2, P6 decisions 5, 8, 9): EXIF/GPS stripped, bombs refused, nothing stored raw."""

from __future__ import annotations

import io
import json

import pytest
from PIL import Image

from slim_cmo.imaging.normalize import ImageLimits, ImageRejected, normalize_image, sniff_type

from ..imagehelpers import (
    LIMITS, SECRET, animated_gif, animated_webp, bomb_png, gradient, jpeg_with_exif, png_bytes, png_with_text, webp_bytes,
)


def reject(data, declared, limits=LIMITS) -> str:
    with pytest.raises(ImageRejected) as caught:
        normalize_image(data, declared, limits)
    return caught.value.code


class TestMetadataIsStripped:
    def test_exif_gps_make_date_and_comment_are_gone_from_the_stored_bytes(self):
        original = jpeg_with_exif()
        assert b"Exif" in original and SECRET in original and b"TestCameraMake" in original  # the fixture really carries them
        out = normalize_image(original, "image/jpeg", LIMITS)
        for needle in (b"Exif", SECRET, b"TestCameraMake", b"2026:10:05", b"GPS", b"\xff\xd8", b"JFIF"):
            assert needle not in out.data, needle
        with Image.open(io.BytesIO(out.data)) as im:
            assert im.format == "PNG" and not im.getexif() and not any(k in im.info for k in ("exif", "icc_profile", "comment", "xmp"))
        assert out.content_type == "image/png" and out.source_type == "image/jpeg"

    def test_png_text_chunks_and_every_ancillary_chunk_are_dropped(self):
        original = png_with_text()
        assert SECRET in original
        out = normalize_image(original, "image/png", LIMITS)
        assert SECRET not in out.data and b"tEXt" not in out.data and b"iTXt" not in out.data

    def test_webp_is_re_encoded_as_png(self):
        out = normalize_image(webp_bytes(), "image/webp", LIMITS)
        assert out.data.startswith(b"\x89PNG") and out.source_type == "image/webp"

    def test_pixels_are_preserved_for_a_lossless_source(self):
        src = png_bytes((8, 8))
        with Image.open(io.BytesIO(normalize_image(src, "image/png", LIMITS).data)) as a, Image.open(io.BytesIO(src)) as b:
            assert a.convert("RGB").tobytes() == b.convert("RGB").tobytes()

    def test_exif_orientation_is_applied_to_the_pixels_before_the_metadata_is_dropped(self):
        out = normalize_image(jpeg_with_exif((40, 20), orientation=6), "image/jpeg", LIMITS)
        assert (out.width, out.height) == (20, 40)  # a 40x20 photo marked "rotate 90" is stored upright
        plain = normalize_image(jpeg_with_exif((40, 20), orientation=1), "image/jpeg", LIMITS)
        assert (plain.width, plain.height) == (40, 20)

    def test_trailing_bytes_and_embedded_payloads_cannot_survive(self):
        payload = b"<?php system($_GET['c']); ?>"
        polyglot = png_bytes() + payload
        out = normalize_image(polyglot, "image/png", LIMITS)
        assert payload not in out.data
        jpg = jpeg_with_exif() + payload
        assert payload not in normalize_image(jpg, "image/jpeg", LIMITS).data

    def test_the_hash_is_of_the_normalised_bytes_so_metadata_variants_are_one_asset(self):
        a = normalize_image(jpeg_with_exif(comment=True), "image/jpeg", LIMITS)
        b = normalize_image(jpeg_with_exif(comment=False), "image/jpeg", LIMITS)
        assert a.sha256 == b.sha256 and len(a.sha256) == 64

    def test_normalisation_is_deterministic(self):
        d = jpeg_with_exif()
        assert normalize_image(d, "image/jpeg", LIMITS).data == normalize_image(d, "image/jpeg", LIMITS).data

    @pytest.mark.parametrize("mode", ["P", "CMYK", "LA", "I;16", "1"])
    def test_unusual_colour_modes_are_converted(self, mode):
        out = io.BytesIO()
        Image.new(mode, (10, 10)).save(out, format="PNG") if mode in ("P", "LA", "I;16", "1") else Image.new("CMYK", (10, 10)).save(out, format="JPEG")
        declared = "image/png" if mode != "CMYK" else "image/jpeg"
        assert normalize_image(out.getvalue(), declared, LIMITS).data.startswith(b"\x89PNG")


class TestRefusals:
    def test_empty_and_oversize(self):
        assert reject(b"", "image/png") == "EMPTY"
        data = png_bytes((200, 200))
        assert reject(data, "image/png", ImageLimits(max_bytes=len(data) - 1, max_pixels=10**6, allowed_types=LIMITS.allowed_types)) == "TOO_LARGE"
        assert normalize_image(data, "image/png", ImageLimits(max_bytes=len(data), max_pixels=10**6, allowed_types=LIMITS.allowed_types))

    def test_a_type_outside_the_configured_allow_list(self):
        only_jpeg = ImageLimits(10**6, 10**6, frozenset({"image/jpeg"}))
        assert reject(png_bytes(), "image/png", only_jpeg) == "TYPE_NOT_ALLOWED"
        assert reject(png_bytes(), "image/svg+xml") == "TYPE_NOT_ALLOWED"
        assert reject(png_bytes(), "") == "TYPE_NOT_ALLOWED"

    @pytest.mark.parametrize("data", [b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>", b"%PDF-1.7 ...", b"GIF89a....", b"just text", b"MZ\x90\x00 executable"])
    def test_non_images_and_unsupported_formats_are_refused_whatever_they_claim(self, data):
        for claimed in ("image/png", "image/jpeg", "image/webp"):
            assert reject(data, claimed) == "NOT_AN_IMAGE"

    def test_a_mislabelled_upload_is_refused(self):
        assert reject(png_bytes(), "image/jpeg") == "TYPE_MISMATCH"
        assert reject(jpeg_with_exif(), "image/png") == "TYPE_MISMATCH"
        assert reject(webp_bytes(), "image/png") == "TYPE_MISMATCH"

    def test_a_png_header_over_a_jpeg_body_or_vice_versa_is_not_accepted(self):
        franken = png_bytes()[:8] + jpeg_with_exif()[2:]
        assert reject(franken, "image/png") in ("CORRUPT", "TYPE_MISMATCH")

    def test_truncated_and_corrupt_files(self):
        jpg = jpeg_with_exif((200, 200))
        assert reject(jpg[: len(jpg) // 2], "image/jpeg") == "CORRUPT"
        png = png_bytes((200, 200))
        assert reject(png[:40], "image/png") == "CORRUPT"
        assert reject(png[:20] + b"\x00" * 200, "image/png") == "CORRUPT"

    def test_animated_images_are_not_supported(self):
        assert reject(animated_webp(), "image/webp") == "ANIMATED_NOT_SUPPORTED"
        assert reject(animated_gif(), "image/gif", ImageLimits(10**6, 10**6, frozenset({"image/gif"}))) == "NOT_AN_IMAGE"

    def test_pixel_limit_is_checked_from_the_header_before_any_decode(self):
        big = png_bytes((3000, 3000))  # 9M pixels, a small file
        assert len(big) < 100_000
        assert reject(big, "image/png", ImageLimits(10**8, 8_999_999, LIMITS.allowed_types)) == "TOO_MANY_PIXELS"
        assert normalize_image(big, "image/png", ImageLimits(10**8, 9_000_000, LIMITS.allowed_types)).width == 3000

    def test_a_decompression_bomb_is_refused_cheaply(self):
        bomb = bomb_png()
        assert len(bomb) < 5_000_000
        assert reject(bomb, "image/png", ImageLimits(10**8, 10**6, LIMITS.allowed_types)) == "TOO_MANY_PIXELS"
        assert reject(bomb, "image/png", ImageLimits(10**8, 10**12, LIMITS.allowed_types)) == "TOO_MANY_PIXELS"  # Pillow's own bomb guard still trips

    def test_a_rejection_never_echoes_the_file_or_its_name(self):
        with pytest.raises(ImageRejected) as caught:
            normalize_image(b"<script>SECRET-GPS-AND-OWNER-NAME</script>", "image/png", LIMITS)
        assert "SECRET" not in str(caught.value) and "script" not in str(caught.value)


class TestLimitsAreRequiredNeverDefaulted:
    @pytest.mark.parametrize("kw", [dict(max_bytes=0), dict(max_bytes=True), dict(max_pixels=-1), dict(max_pixels=1.5), dict(allowed_types=frozenset())])
    def test_invalid_limits(self, kw):
        base = dict(max_bytes=1, max_pixels=1, allowed_types=frozenset({"image/png"}))
        with pytest.raises(ValueError):
            ImageLimits(**{**base, **kw})

    def test_no_defaults_exist(self):
        with pytest.raises(TypeError):
            ImageLimits()  # type: ignore[call-arg]


def test_sniff_type_reads_magic_numbers_only():
    assert sniff_type(jpeg_with_exif()) == "image/jpeg" and sniff_type(png_bytes()) == "image/png" and sniff_type(webp_bytes()) == "image/webp"
    assert sniff_type(b"RIFF....WAVE") is None and sniff_type(b"") is None
    assert json.dumps(sniff_type(b"\x00\x00")) == "null"
