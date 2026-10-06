"""Plan 7c-ii: CMO-only provider options on the shared clients. Each option is OMITTED from the request when unset, so
every pre-existing caller (Product Intelligence) sends the byte-identical request. No network: httpx is replaced."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx
import pytest

from market_signals import tavily_client as tav
from market_signals import youtube_client as yt

KEY = "K-SECRET"


def _resp(body: Any, method: str = "GET") -> httpx.Response:
    return httpx.Response(200, json=body, request=httpx.Request(method, "https://example.invalid/x"))


class Rec:
    def __init__(self, *queued: Any) -> None:
        self.queue, self.calls = list(queued), []

    def __call__(self, url: str, **kw: Any) -> httpx.Response:
        self.calls.append((url, kw))
        return self.queue.pop(0)


def tavily(monkeypatch, *responses):
    rec = Rec(*responses)
    monkeypatch.setattr(tav.httpx, "post", rec)
    return tav.HttpTavilyClient(api_key=KEY), rec


def youtube(monkeypatch, *responses):
    rec = Rec(*responses)
    monkeypatch.setattr(yt.httpx, "get", rec)
    return yt.HttpYoutubeClient(api_key=KEY), rec


# ---------------------------------------------------------------- defaults are byte-identical
def test_tavily_default_body_is_unchanged_by_the_new_options(monkeypatch):
    c, rec = tavily(monkeypatch, _resp({"results": []}, "POST"))
    c.search("q")
    assert rec.calls[0][1]["json"] == {"api_key": KEY, "query": "q", "include_images": False, "max_results": 10, "search_depth": "basic"}


def test_youtube_default_params_are_unchanged_by_the_new_options(monkeypatch):
    c, rec = youtube(monkeypatch, _resp({"items": []}))
    c.search_videos("q")
    assert rec.calls[0][1]["params"] == {"part": "snippet", "q": "q", "type": "video", "maxResults": 10, "key": KEY}


# ---------------------------------------------------------------- Tavily options
def test_tavily_news_options_are_sent_exactly_when_given(monkeypatch):
    c, rec = tavily(monkeypatch, _resp({"results": []}, "POST"))
    c.search("q", max_results=5, topic="news", days=30, country="india")
    assert rec.calls[0][1]["json"] == {
        "api_key": KEY, "query": "q", "include_images": False, "max_results": 5, "search_depth": "basic",
        "topic": "news", "days": 30, "country": "india",
    }


@pytest.mark.parametrize("opt", [{"topic": "news"}, {"days": 7}, {"country": "india"}])
def test_each_tavily_option_is_independent(monkeypatch, opt):
    c, rec = tavily(monkeypatch, _resp({"results": []}, "POST"))
    c.search("q", **opt)
    sent = rec.calls[0][1]["json"]
    assert set(sent) - {"api_key", "query", "include_images", "max_results", "search_depth"} == set(opt)


def test_tavily_dated_news_results_keep_the_raw_date_string(monkeypatch):
    body = {"results": [{"url": "https://a.example/1", "title": "T", "published_date": "Thu, 01 Oct 2026 07:00:00 GMT"}]}
    c, _ = tavily(monkeypatch, _resp(body, "POST"))
    assert c.search("q", topic="news", days=30)[0].published_date == "Thu, 01 Oct 2026 07:00:00 GMT"


# ---------------------------------------------------------------- YouTube options
def test_youtube_region_order_and_published_after_are_sent_when_given(monkeypatch):
    c, rec = youtube(monkeypatch, _resp({"items": []}))
    after = datetime(2026, 9, 4, 5, 30, tzinfo=timezone.utc)
    c.search_videos("q", max_results=5, region_code="IN", order="date", published_after=after)
    assert rec.calls[0][1]["params"] == {
        "part": "snippet", "q": "q", "type": "video", "maxResults": 5, "regionCode": "IN", "order": "date",
        "publishedAfter": "2026-09-04T05:30:00Z", "key": KEY,
    }


def test_published_after_is_normalised_to_utc(monkeypatch):
    from datetime import timedelta

    c, rec = youtube(monkeypatch, _resp({"items": []}))
    ist = timezone(timedelta(hours=5, minutes=30))
    c.search_videos("q", published_after=datetime(2026, 9, 4, 11, 0, tzinfo=ist))
    assert rec.calls[0][1]["params"]["publishedAfter"] == "2026-09-04T05:30:00Z"


def test_youtube_still_makes_exactly_one_batched_statistics_call_with_options(monkeypatch):
    search = {"items": [{"id": {"videoId": f"v{n}"}, "snippet": {"title": "t", "channelId": f"UC{n}"}} for n in range(5)]}
    c, rec = youtube(monkeypatch, _resp(search), _resp({"items": []}))
    c.search_videos("q", max_results=5, region_code="IN")
    assert len(rec.calls) == 2 and rec.calls[1][0].endswith("/videos") and rec.calls[1][1]["params"]["id"] == "v0,v1,v2,v3,v4"


def test_youtube_channel_id_is_returned_when_present_and_none_otherwise(monkeypatch):
    search = {"items": [
        {"id": {"videoId": "a"}, "snippet": {"title": "t", "channelId": "UCabc", "channelTitle": "Ch"}},
        {"id": {"videoId": "b"}, "snippet": {"title": "t"}},
        {"id": {"videoId": "c"}, "snippet": {"title": "t", "channelId": ""}},
        {"id": {"videoId": "d"}, "snippet": {"title": "t", "channelId": 5}},
    ]}
    c, _ = youtube(monkeypatch, _resp(search), _resp({"items": []}))
    assert [v.channel_id for v in c.search_videos("q")] == ["UCabc", None, None, None]


def test_channel_id_is_a_trailing_defaulted_field_so_existing_constructors_still_work():
    now = datetime(2026, 10, 4, tzinfo=timezone.utc)
    v = yt.YoutubeVideo("v", "T", "Ch", 1, 2, "th", now, (), now)  # the PI call-site shape, positional
    assert v.channel_id is None
