"""discovery/top5_images.py — a clear, accurate product image for the final five only; never a video frame (docs/specs/ceo-pi-research-flow.md C11)."""

from __future__ import annotations

import io

from product_intelligence.discovery import top5_images
from product_intelligence.discovery.top5_images import VerifiedImage, is_video_host, resolve_best_image
from product_intelligence.sources.tavily_client import TavilyImage, TavilyUnavailable


def _img(url: str, title: str, source: str | None = None) -> TavilyImage:
    return TavilyImage(url=url, source_url=source or url, description=None, title=title)


class _Tavily:
    def __init__(self, by_query: dict[str, list[TavilyImage]] | list[TavilyImage]) -> None:
        self.by_query, self.queries = by_query, []

    def images_for(self, query, *, max_images=5):
        self.queries.append(query)
        if isinstance(self.by_query, TavilyUnavailable):
            raise self.by_query
        return self.by_query if isinstance(self.by_query, list) else self.by_query.get(query, [])


class _Verifier:
    def __init__(self, ok: dict[str, VerifiedImage]) -> None:
        self.ok, self.checked = ok, []

    def verify(self, url):
        self.checked.append(url)
        return self.ok.get(url)


TITLE = "Emerald Sunray Chronograph Watch"


def test_video_hosts_are_recognised() -> None:
    for u in ("https://i.ytimg.com/vi/x/hqdefault.jpg", "https://www.youtube.com/watch?v=x", "https://youtu.be/x", "https://yt3.ggpht.com/a.jpg"):
        assert is_video_host(u)
    assert not is_video_host("https://cdn.shop.example/watch.jpg")


def test_a_youtube_thumbnail_is_refused_even_if_its_text_matches_and_it_would_load() -> None:
    thumb = _img("https://i.ytimg.com/vi/x/hqdefault.jpg", "Emerald Sunray Chronograph Watch review")
    v = _Verifier({thumb.url: VerifiedImage(1280, 720, 90_000)})
    assert resolve_best_image(TITLE, tavily=_Tavily([thumb]), verifier=v) is None
    assert v.checked == []  # never even fetched


def test_an_image_that_does_not_name_the_product_is_refused() -> None:
    other = _img("https://cdn.shop.example/other.jpg", "Black leather wallet")
    assert resolve_best_image(TITLE, tavily=_Tavily([other]), verifier=_Verifier({other.url: VerifiedImage(800, 800, 60_000)})) is None


def test_the_largest_verified_matching_image_wins_and_unloadable_ones_are_skipped() -> None:
    broken = _img("https://cdn.shop.example/broken.jpg", "Emerald Sunray Chronograph Watch front")
    small = _img("https://cdn.shop.example/small.jpg", "Emerald Sunray Chronograph Watch side")
    big = _img("https://cdn.shop.example/big.jpg", "Emerald Sunray Chronograph Watch studio")
    v = _Verifier({small.url: VerifiedImage(400, 400, 30_000), big.url: VerifiedImage(1200, 1200, 200_000)})
    got = resolve_best_image(TITLE, tavily=_Tavily([broken, small, big]), verifier=v)
    assert got is not None and got[0].url == big.url


def test_tavily_failure_gives_no_image_and_does_not_raise() -> None:
    assert resolve_best_image(TITLE, tavily=_Tavily(TavilyUnavailable("down")), verifier=_Verifier({})) is None


def test_single_generic_token_title_never_gets_an_image() -> None:
    i = _img("https://cdn.shop.example/w.jpg", "watch")
    assert resolve_best_image("Watch", tavily=_Tavily([i]), verifier=_Verifier({i.url: VerifiedImage(900, 900, 50_000)})) is None


def _png(w: int, h: int) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (w, h), (200, 30, 30)).save(buf, "PNG")
    return buf.getvalue()


def test_inspection_rejects_small_images_and_banners_and_garbage() -> None:
    assert top5_images._inspect(_png(900, 900)) is not None
    assert top5_images._inspect(_png(200, 200)) is None  # too small to look sharp
    assert top5_images._inspect(_png(1600, 400)) is None  # banner shape
    assert top5_images._inspect(b"not an image at all") is None


def test_a_near_square_product_shot_beats_a_larger_wide_lifestyle_photo() -> None:
    from product_intelligence.discovery.top5_images import _quality

    assert _quality(VerifiedImage(1000, 1000, 80_000)) > _quality(VerifiedImage(2000, 1450, 200_000))  # square beats a bigger wide hero shot
    assert _quality(VerifiedImage(2000, 1900, 90_000)) > _quality(VerifiedImage(1200, 1000, 90_000))  # within square-ish shapes, larger wins
    assert top5_images.MAX_ASPECT < 1.5  # a 3:2 hero or banner is refused outright


def test_a_file_named_as_a_lifestyle_shot_loses_to_a_plain_product_photo() -> None:
    staged = _img("https://cdn.shop.example/AZ100_lifestyle_silver.jpg", "Emerald Sunray Chronograph Watch lifestyle")
    plain = _img("https://cdn.shop.example/az100-front.jpg", "Emerald Sunray Chronograph Watch front")
    v = _Verifier({staged.url: VerifiedImage(1800, 1800, 200_000), plain.url: VerifiedImage(900, 900, 60_000)})
    got = resolve_best_image(TITLE, tavily=_Tavily([staged, plain]), verifier=v)
    assert got is not None and got[0].url == plain.url
