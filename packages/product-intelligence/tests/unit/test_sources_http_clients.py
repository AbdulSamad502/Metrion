"""7b regression pins for the REAL Tavily and YouTube clients (`HttpTavilyClient`,
`HttpYoutubeClient`) against canned, real-shaped HTTP responses. No network: `httpx.post` /
`httpx.get` are replaced in the client modules. These pin CURRENT behaviour so the market-signals
extraction (plan P7a, 7c) can be proven behaviour-preserving without editing any test.

NOT testable here (needs live credentials / provider access - see
docs/planning/market-signal-extraction-plan.md section 5): the providers' real response shape
drifting from these canned shapes, real quota exhaustion, real latency/timeouts, and Tavily's
server-side `search_depth` semantics."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx
import pytest

from product_intelligence.sources import tavily_client as tav
from product_intelligence.sources import youtube_client as yt

KEY = "SECRET-KEY-123"


def _resp(status: int = 200, body: Any = None, *, raw: bytes | None = None, method: str = "GET") -> httpx.Response:
    request = httpx.Request(method, "https://example.invalid/x")
    if raw is not None:
        return httpx.Response(status, content=raw, request=request)
    return httpx.Response(status, json=body, request=request)


class Recorder:
    """Stands in for httpx.post / httpx.get; replays queued responses/exceptions in order."""

    def __init__(self, *queued: Any) -> None:
        self.queue = list(queued)
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, url: str, **kwargs: Any) -> httpx.Response:
        self.calls.append((url, kwargs))
        item = self.queue.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


@pytest.fixture
def tavily(monkeypatch):
    def make(*queued: Any) -> tuple[tav.HttpTavilyClient, Recorder]:
        rec = Recorder(*queued)
        monkeypatch.setattr(tav.httpx, "post", rec)
        return tav.HttpTavilyClient(api_key=KEY), rec

    return make


@pytest.fixture
def youtube(monkeypatch):
    def make(*queued: Any) -> tuple[yt.HttpYoutubeClient, Recorder]:
        rec = Recorder(*queued)
        monkeypatch.setattr(yt.httpx, "get", rec)
        return yt.HttpYoutubeClient(api_key=KEY), rec

    return make


# ---------------------------------------------------------------- Tavily: request pins
def test_tavily_search_default_request_is_exactly_this(tavily):
    client, rec = tavily(_resp(body={"results": []}, method="POST"))
    client.search("steel bottle")
    ((url, kw),) = rec.calls
    assert url == "https://api.tavily.com/search"
    assert kw["json"] == {"api_key": KEY, "query": "steel bottle", "include_images": False, "max_results": 10, "search_depth": "basic"}
    assert kw["timeout"] == 10.0


def test_tavily_search_forwards_include_images_and_max_results(tavily):
    client, rec = tavily(_resp(body={"results": []}, method="POST"))
    client.search("q", include_images=True, max_results=3)
    assert rec.calls[0][1]["json"]["include_images"] is True and rec.calls[0][1]["json"]["max_results"] == 3


def test_tavily_images_for_request_is_exactly_this(tavily):
    client, rec = tavily(_resp(body={"images": []}, method="POST"))
    client.images_for("steel bottle", max_images=4)
    assert rec.calls[0][1]["json"] == {
        "api_key": KEY, "query": "steel bottle", "include_images": True, "include_image_descriptions": True,
        "max_results": 4, "search_depth": "basic",
    }


def test_tavily_images_for_default_max_images_is_five(tavily):
    client, rec = tavily(_resp(body={"images": []}, method="POST"))
    client.images_for("q")
    assert rec.calls[0][1]["json"]["max_results"] == 5


def test_tavily_custom_timeout_is_used(monkeypatch):
    rec = Recorder(_resp(body={"results": []}, method="POST"))
    monkeypatch.setattr(tav.httpx, "post", rec)
    tav.HttpTavilyClient(api_key=KEY, timeout_seconds=2.5).search("q")
    assert rec.calls[0][1]["timeout"] == 2.5


def test_tavily_default_request_has_no_topic_time_range_or_country(tavily):
    """Pins that the PI default path never sends the news/recency/country parameters (added later,
    additively, for CMO - the default request must stay byte-identical)."""
    client, rec = tavily(_resp(body={"results": []}, method="POST"))
    client.search("q")
    assert not ({"topic", "time_range", "days", "country"} & set(rec.calls[0][1]["json"]))


# ---------------------------------------------------------------- Tavily: parsing
def test_tavily_parses_dated_and_undated_results_and_keeps_the_raw_date_string(tavily):
    body = {"results": [
        {"url": "https://a.example/1", "title": "A", "content": "c", "score": 0.5, "published_date": "Thu, 01 Oct 2026 07:00:00 GMT"},
        {"url": "https://b.example/2", "title": "B", "content": "d", "score": 1},
    ], "answer": "MODEL WRITTEN TEXT"}
    client, _ = tavily(_resp(body=body, method="POST"))
    a, b = client.search("q")
    assert a.published_date == "Thu, 01 Oct 2026 07:00:00 GMT"  # raw string; parsing is the caller's job
    assert b.published_date is None
    assert (a.score, b.score) == (0.5, 1.0) and isinstance(b.score, float)


def test_tavily_never_exposes_the_model_written_answer(tavily):
    client, _ = tavily(_resp(body={"results": [{"url": "u", "title": "t"}], "answer": "x"}, method="POST"))
    (r,) = client.search("q")
    assert not hasattr(r, "answer")


@pytest.mark.parametrize("date", [None, 5, ["Thu"], {"a": 1}])
def test_tavily_non_string_published_date_becomes_none(tavily, date):
    client, _ = tavily(_resp(body={"results": [{"url": "u", "title": "t", "published_date": date}]}, method="POST"))
    assert client.search("q")[0].published_date is None


def test_tavily_skips_malformed_entries_and_defaults_missing_fields(tavily):
    body = {"results": ["junk", 7, None, {"title": "no url"}, {"url": "no title"}, {"url": "u", "title": "t", "content": 9, "score": "high"}]}
    client, _ = tavily(_resp(body=body, method="POST"))
    results = client.search("q")
    assert len(results) == 1
    assert results[0].content == "" and results[0].score is None


def test_tavily_retrieved_at_is_utc_aware_and_shared_by_all_results(tavily):
    client, _ = tavily(_resp(body={"results": [{"url": "u1", "title": "t"}, {"url": "u2", "title": "t"}]}, method="POST"))
    a, b = client.search("q")
    assert a.retrieved_at == b.retrieved_at and a.retrieved_at.tzinfo is timezone.utc


def test_tavily_empty_results_list_is_a_real_empty_result_not_an_error(tavily):
    client, _ = tavily(_resp(body={"results": []}, method="POST"))
    assert client.search("q") == []


# ---------------------------------------------------------------- Tavily: images
def test_tavily_images_for_handles_string_and_object_entries(tavily):
    body = {"images": [
        "https://img/1.jpg",
        {"url": "https://img/2.jpg", "description": "a bottle", "title": "Shop"},
        {"url": "https://img/3.jpg", "source_url": "https://page/3"},
        {"nourl": True}, 42,
    ]}
    client, _ = tavily(_resp(body=body, method="POST"))
    imgs = client.images_for("q")
    assert [i.url for i in imgs] == ["https://img/1.jpg", "https://img/2.jpg", "https://img/3.jpg"]
    assert imgs[0].source_url == imgs[0].url and imgs[0].description is None
    assert (imgs[1].description, imgs[1].title, imgs[1].source_url) == ("a bottle", "Shop", "https://img/2.jpg")
    assert imgs[2].source_url == "https://page/3"


def test_tavily_images_for_caps_at_max_images_and_tolerates_missing_images_key(tavily):
    client, _ = tavily(_resp(body={"images": [f"https://i/{n}" for n in range(9)]}, method="POST"))
    assert len(client.images_for("q", max_images=3)) == 3
    client2, _ = tavily(_resp(body={"results": []}, method="POST"))
    assert client2.images_for("q") == []


# ---------------------------------------------------------------- Tavily: errors
@pytest.mark.parametrize("status", [400, 401, 429, 432, 500, 503])
def test_tavily_non_2xx_raises_unavailable_and_never_returns_empty(tavily, status):
    client, _ = tavily(_resp(status, {"detail": "no"}, method="POST"))
    with pytest.raises(tav.TavilyUnavailable):
        client.search("q")


@pytest.mark.parametrize("exc", [httpx.ReadTimeout("t"), httpx.ConnectError("c"), httpx.ConnectTimeout("t")])
def test_tavily_transport_errors_raise_unavailable(tavily, exc):
    client, _ = tavily(exc)
    with pytest.raises(tav.TavilyUnavailable):
        client.search("q")


@pytest.mark.parametrize("raw", [b"not json", b"", b"<html>", b"[1,2]", b'"str"', b"null"])
def test_tavily_malformed_or_non_object_body_raises_unavailable(tavily, raw):
    client, _ = tavily(_resp(raw=raw, method="POST"))
    with pytest.raises(tav.TavilyUnavailable):
        client.search("q")


@pytest.mark.parametrize("body", [{}, {"results": None}, {"results": "x"}, {"results": {"a": 1}}])
def test_tavily_missing_or_non_list_results_raises_unavailable(tavily, body):
    client, _ = tavily(_resp(body=body, method="POST"))
    with pytest.raises(tav.TavilyUnavailable, match="results"):
        client.search("q")


def test_tavily_error_messages_never_contain_the_api_key(tavily):
    for item in (_resp(500, {"x": 1}, method="POST"), httpx.ReadTimeout("slow"), _resp(raw=b"junk", method="POST")):
        client, _ = tavily(item)
        with pytest.raises(tav.TavilyUnavailable) as err:
            client.search("q")
        assert KEY not in str(err.value)


# ---------------------------------------------------------------- YouTube: request / quota shape
SEARCH_OK = {"items": [
    {"id": {"videoId": "v1"}, "snippet": {"title": "T1", "channelTitle": "Ch1", "publishedAt": "2026-09-30T10:00:00Z",
                                           "thumbnails": {"default": {"url": "d1"}, "high": {"url": "h1"}}}},
    {"id": {"videoId": "v2"}, "snippet": {"title": "T2", "channelTitle": "Ch2", "publishedAt": "2026-09-01T00:00:00Z",
                                           "thumbnails": {"medium": {"url": "m2"}, "default": {"url": "d2"}}}},
]}
STATS_OK = {"items": [
    {"id": "v1", "statistics": {"viewCount": "1200", "commentCount": "7"}},
    {"id": "v2", "statistics": {"viewCount": "n/a"}},
]}


def test_youtube_search_default_requests_are_exactly_these(youtube):
    client, rec = youtube(_resp(body=SEARCH_OK), _resp(body=STATS_OK))
    client.search_videos("steel bottle")
    (u1, k1), (u2, k2) = rec.calls
    assert u1 == "https://www.googleapis.com/youtube/v3/search"
    assert k1["params"] == {"part": "snippet", "q": "steel bottle", "type": "video", "maxResults": 10, "key": KEY}
    assert u2 == "https://www.googleapis.com/youtube/v3/videos"
    assert k2["params"] == {"part": "statistics", "id": "v1,v2", "key": KEY}
    assert k1["timeout"] == 10.0


def test_youtube_quota_discipline_one_search_then_one_batched_stats_call(youtube):
    """search.list is the expensive call (100 units): exactly ONE per search, plus ONE batched
    videos.list - never one stats call per video."""
    many = {"items": [{"id": {"videoId": f"v{n}"}, "snippet": {"title": "t"}} for n in range(8)]}
    client, rec = youtube(_resp(body=many), _resp(body={"items": []}))
    client.search_videos("q", max_results=8)
    assert len(rec.calls) == 2


def test_youtube_no_results_makes_no_stats_call_and_returns_empty(youtube):
    client, rec = youtube(_resp(body={"items": []}))
    assert client.search_videos("q") == []
    assert len(rec.calls) == 1


def test_youtube_default_request_has_no_region_order_or_date_filter(youtube):
    """Pins that the PI default path sends none of the optional filters CMO will add later."""
    client, rec = youtube(_resp(body={"items": []}))
    client.search_videos("q")
    assert not ({"regionCode", "order", "publishedAfter", "relevanceLanguage"} & set(rec.calls[0][1]["params"]))


# ---------------------------------------------------------------- YouTube: parsing
def test_youtube_parses_counts_thumbnails_dates_and_titles(youtube):
    client, _ = youtube(_resp(body=SEARCH_OK), _resp(body=STATS_OK))
    v1, v2 = client.search_videos("q")
    assert (v1.video_id, v1.title, v1.channel_title) == ("v1", "T1", "Ch1")
    assert (v1.view_count, v1.comment_count) == (1200, 7)
    assert (v2.view_count, v2.comment_count) == (None, None)  # non-digit / absent -> None, never 0
    assert v1.thumbnail_url == "h1" and v2.thumbnail_url == "m2"  # high > medium > default
    assert v1.published_at == datetime(2026, 9, 30, 10, 0, tzinfo=timezone.utc)
    assert v1.top_comments == () and v1.retrieved_at.tzinfo is timezone.utc


def test_youtube_missing_stats_entry_gives_none_counts_not_zero(youtube):
    client, _ = youtube(_resp(body=SEARCH_OK), _resp(body={"items": [{"id": "v1", "statistics": {"viewCount": "5"}}]}))
    _, v2 = client.search_videos("q")
    assert v2.view_count is None and v2.comment_count is None


@pytest.mark.parametrize("stats_body", [{}, {"items": None}, {"items": "x"}])
def test_youtube_unusable_stats_body_degrades_counts_to_none(youtube, stats_body):
    client, _ = youtube(_resp(body=SEARCH_OK), _resp(body=stats_body))
    assert all(v.view_count is None for v in client.search_videos("q"))


@pytest.mark.parametrize("published", [None, 5, "garbage", "2026-13-45T00:00:00Z"])
def test_youtube_bad_or_missing_published_at_falls_back_to_retrieved_at(youtube, published):
    body = {"items": [{"id": {"videoId": "v1"}, "snippet": {"title": "t", "publishedAt": published}}]}
    client, _ = youtube(_resp(body=body), _resp(body={"items": []}))
    (v,) = client.search_videos("q")
    assert v.published_at == v.retrieved_at


def test_youtube_skips_items_without_a_video_id_or_snippet(youtube):
    body = {"items": ["junk", {"id": "str", "snippet": {}}, {"id": {"channelId": "c"}, "snippet": {}},
                      {"id": {"videoId": "v9"}}, {"id": {"videoId": "ok"}, "snippet": {"title": "t"}}]}
    client, rec = youtube(_resp(body=body), _resp(body={"items": []}))
    vids = client.search_videos("q")
    assert [v.video_id for v in vids] == ["ok"]
    assert rec.calls[1][1]["params"]["id"] == "ok"


def test_youtube_missing_snippet_fields_default_to_empty_strings(youtube):
    client, _ = youtube(_resp(body={"items": [{"id": {"videoId": "v"}, "snippet": {}}]}), _resp(body={"items": []}))
    (v,) = client.search_videos("q")
    assert (v.title, v.channel_title, v.thumbnail_url) == ("", "", "")


# ---------------------------------------------------------------- YouTube: comments
def test_youtube_top_comments_request_and_parsing(youtube):
    body = {"items": [
        {"snippet": {"topLevelComment": {"snippet": {"textDisplay": "  great  "}}}},
        {"snippet": {"topLevelComment": {"snippet": {"textDisplay": "   "}}}},
        {"snippet": {"topLevelComment": {"snippet": {}}}}, {"snippet": "x"}, "junk",
    ]}
    client, rec = youtube(_resp(body=body))
    assert client.top_comments_for("v1", max_comments=5) == ["great"]
    assert rec.calls[0][0].endswith("/commentThreads")
    assert rec.calls[0][1]["params"] == {"part": "snippet", "videoId": "v1", "maxResults": 5, "order": "relevance",
                                         "textFormat": "plainText", "key": KEY}


def test_youtube_comments_failure_degrades_to_empty_never_raises(youtube):
    for item in (_resp(403, {"error": {"message": "commentsDisabled"}}), httpx.ReadTimeout("t"), _resp(raw=b"junk")):
        client, _ = youtube(item)
        assert client.top_comments_for("v1") == []


def test_youtube_comments_non_list_items_is_empty(youtube):
    client, _ = youtube(_resp(body={"items": "x"}))
    assert client.top_comments_for("v1") == []


# ---------------------------------------------------------------- YouTube: errors
@pytest.mark.parametrize("status", [400, 403, 429, 500, 503])
def test_youtube_search_non_2xx_incl_quota_exceeded_raises_unavailable(youtube, status):
    client, rec = youtube(_resp(status, {"error": {"errors": [{"reason": "quotaExceeded"}]}}))
    with pytest.raises(yt.YoutubeUnavailable):
        client.search_videos("q")
    assert len(rec.calls) == 1  # no stats call after a failed search


@pytest.mark.parametrize("exc", [httpx.ReadTimeout("t"), httpx.ConnectError("c")])
def test_youtube_transport_errors_raise_unavailable(youtube, exc):
    client, _ = youtube(exc)
    with pytest.raises(yt.YoutubeUnavailable):
        client.search_videos("q")


@pytest.mark.parametrize("raw", [b"junk", b"[1]", b"null"])
def test_youtube_malformed_or_non_object_body_raises_unavailable(youtube, raw):
    client, _ = youtube(_resp(raw=raw))
    with pytest.raises(yt.YoutubeUnavailable):
        client.search_videos("q")


@pytest.mark.parametrize("body", [{}, {"items": None}, {"items": {}}])
def test_youtube_search_without_items_list_raises_unavailable(youtube, body):
    client, _ = youtube(_resp(body=body))
    with pytest.raises(yt.YoutubeUnavailable, match="items"):
        client.search_videos("q")


def test_youtube_stats_call_failure_propagates_after_a_successful_search(youtube):
    """Pinned CURRENT behaviour: a failing batched stats call fails the whole search (it does not
    degrade to counts-None)."""
    client, _ = youtube(_resp(body=SEARCH_OK), _resp(500, {}))
    with pytest.raises(yt.YoutubeUnavailable):
        client.search_videos("q")


def test_youtube_error_messages_never_contain_the_api_key(youtube):
    client, _ = youtube(httpx.ReadTimeout("slow"))
    with pytest.raises(yt.YoutubeUnavailable) as err:
        client.search_videos("q")
    assert KEY not in str(err.value)
