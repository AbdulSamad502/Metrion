"""TOP-5 IMAGES — resolves a clear, accurate product image for the five seller-facing products only (docs/specs/ceo-pi-research-flow.md C11).

The ~30 discovered candidates persist with NO image. Only after the top five are chosen does this module search for images by each product's own name and accept
one only when ALL of these hold:

* attribution: the image's own title/description names every identity token of the product, with at least two tokens (`match_image_for_candidate`, the same
  honest rule discovery always used: no image is better than a misattributed one);
* not a video frame: anything hosted on YouTube/Vimeo (thumbnails, channel art) is refused outright;
* it really is a usable image: the URL loads over http(s), is an image type (JPEG/PNG/WEBP), and is large enough to look sharp (shorter side >= 300 px, with
  the byte-size floor as the fallback when pixel size cannot be read), and is not an extreme banner/strip shape.

Among the verified matches the largest is chosen. A product with no verified image keeps NO image (the dashboard shows a plain placeholder), never a guess.
The image is a hotlink with visible source attribution (PI §0b/C8); nothing is rehosted. Network access is behind `ImageVerifier`, so tests need no network.
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from typing import Protocol, Sequence
from urllib.parse import urlparse
from uuid import UUID

import httpx

from product_intelligence.discovery.candidate_synthesis import match_image_for_candidate_all
from product_intelligence.discovery.prerank import clean_display_title
from product_intelligence.repositories import product_candidate_repo
from product_intelligence.sources.tavily_client import TavilyClient, TavilyImage, TavilyUnavailable

logger = logging.getLogger(__name__)

MIN_SHORT_SIDE_PX = 300
MIN_BYTES_WITHOUT_DIMENSIONS = 15_000
MAX_BYTES = 3_000_000
MAX_ASPECT = 1.4  # long side / short side; product photos are near-square, lifestyle banners and hero shots are wide (live run 2026-10-14: a wide lifestyle photo was picked for AirPods)
_ALLOWED_TYPES = ("image/jpeg", "image/png", "image/webp")
_VIDEO_HOSTS = ("youtube.com", "youtu.be", "ytimg.com", "ggpht.com", "vimeo.com")
_QUERY_SUFFIXES = ("", " product photo")
_MAX_CANDIDATES_TO_VERIFY = 6


@dataclass(frozen=True, slots=True)
class VerifiedImage:
    width: int | None
    height: int | None
    byte_size: int

    @property
    def area(self) -> int:
        return (self.width or 0) * (self.height or 0)


class ImageVerifier(Protocol):
    def verify(self, url: str) -> VerifiedImage | None:
        """None when the URL does not load as a clear, usable product image."""


def is_video_host(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(host == h or host.endswith("." + h) for h in _VIDEO_HOSTS)


class HttpImageVerifier:
    """Fetches the image (bounded) and checks type, size and shape. Pillow is used for pixel size when installed; otherwise the byte-size floor applies."""

    def __init__(self, *, timeout_seconds: float = 6.0) -> None:
        self._timeout = timeout_seconds

    def verify(self, url: str) -> VerifiedImage | None:
        if urlparse(url).scheme not in ("http", "https"):
            return None
        try:
            with httpx.stream("GET", url, timeout=self._timeout, follow_redirects=True, headers={"Accept": "image/jpeg,image/png,image/webp"}) as response:
                if response.status_code != 200:
                    return None
                if response.headers.get("content-type", "").split(";")[0].strip().lower() not in _ALLOWED_TYPES:
                    return None
                data = bytearray()
                for chunk in response.iter_bytes():
                    data.extend(chunk)
                    if len(data) > MAX_BYTES:
                        return None
        except (httpx.HTTPError, ValueError):
            return None
        return _inspect(bytes(data))


def _inspect(data: bytes) -> VerifiedImage | None:
    try:
        from PIL import Image  # optional: pixel size

        with Image.open(io.BytesIO(data)) as img:
            width, height = img.size
    except ImportError:
        return VerifiedImage(None, None, len(data)) if len(data) >= MIN_BYTES_WITHOUT_DIMENSIONS else None
    except Exception:  # noqa: BLE001 - not a decodable image
        return None
    short, long_ = min(width, height), max(width, height)
    if short < MIN_SHORT_SIDE_PX or long_ / short > MAX_ASPECT:
        return None
    return VerifiedImage(width, height, len(data))


_STAGED_WORDS = ("lifestyle", "banner", "hero", "model-shot", "campaign", "wearing")


def _not_staged(url: str) -> int:
    """1 for a file that does not say it is a staged / lifestyle shot (a plain product photo is preferred); a hint from the file name only, never decisive on its own."""
    low = url.lower()
    return 0 if any(w in low for w in _STAGED_WORDS) else 1


def _quality(v: VerifiedImage) -> tuple[int, int, int]:
    """Higher is better: nearest to square first (in coarse steps, so a slightly larger image still wins within the same shape class), then size."""
    if not v.width or not v.height:
        return (0, 0, v.byte_size)
    ratio_x100 = max(v.width, v.height) * 100 // min(v.width, v.height)  # 100 = square
    shape_class = 3 if ratio_x100 <= 110 else 2 if ratio_x100 <= 125 else 1
    return (shape_class, v.area, v.byte_size)


def resolve_best_image(candidate_title: str, *, tavily: TavilyClient, verifier: ImageVerifier) -> tuple[TavilyImage, VerifiedImage] | None:
    """The best verified, correctly attributed, non-video image for one product, or None."""
    seen: set[str] = set()
    matched: list[TavilyImage] = []
    for suffix in _QUERY_SUFFIXES:
        try:
            images = tavily.images_for(candidate_title + suffix, max_images=8)
        except TavilyUnavailable:
            continue
        for image in match_image_for_candidate_all(candidate_title, images):
            if image.url in seen or is_video_host(image.url) or is_video_host(image.source_url):
                continue
            seen.add(image.url)
            matched.append(image)
        if matched:
            break
    best: tuple[TavilyImage, VerifiedImage] | None = None
    for image in matched[:_MAX_CANDIDATES_TO_VERIFY]:
        verified = verifier.verify(image.url)
        if verified is None:
            continue
        if best is None or (_not_staged(image.url), _quality(verified)) > (_not_staged(best[0].url), _quality(best[1])):
            best = (image, verified)
    return best


def resolve_top5_images(
    tenant_id: UUID, candidate_ids: Sequence[UUID], *, tavily: TavilyClient, verifier: ImageVerifier | None = None,
) -> dict[UUID, bool]:
    """Resolves and persists the image of each given product (the final five). A product with no verified image has any earlier image CLEARED (so a stale video
    frame can never remain). Returns candidate_id -> whether a verified image was stored. Never raises for a provider failure: the image is not a reason to fail
    the case."""
    verifier = verifier or HttpImageVerifier()
    out: dict[UUID, bool] = {}
    for row in product_candidate_repo.list_candidates_by_ids(tenant_id, list(candidate_ids)):
        cid = UUID(str(row["id"]))
        try:
            found = resolve_best_image(clean_display_title(str(row["candidate_title"])), tavily=tavily, verifier=verifier)
        except Exception:  # noqa: BLE001
            logger.exception("top-5 image resolution failed for one product")
            found = None
        if found is None:
            product_candidate_repo.update_image(tenant_id, cid, image_url=None, image_source_url=None)
            out[cid] = False
        else:
            product_candidate_repo.update_image(tenant_id, cid, image_url=found[0].url, image_source_url=found[0].source_url)
            out[cid] = True
    return out
