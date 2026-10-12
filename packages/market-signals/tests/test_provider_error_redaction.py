"""A provider failure must never carry the API key (the YouTube key travels in the URL query string, and httpx puts the whole URL in its error message)."""

from __future__ import annotations

import httpx
import pytest

from market_signals import tavily_client, youtube_client
from market_signals.errors import describe

KEY = "AIzaSyTHIS_IS_A_SECRET_KEY_123"


def _status_error(code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://www.googleapis.com/youtube/v3/search", params={"q": "steel bottle", "key": KEY})
    try:
        httpx.Response(code, request=request).raise_for_status()
    except httpx.HTTPStatusError as exc:
        return exc
    raise AssertionError("no error")


def test_the_library_message_really_does_contain_the_key():  # why this module exists
    assert KEY in str(_status_error(403))


@pytest.mark.parametrize("code", [400, 403, 429, 500])
def test_describe_a_status_error_has_the_code_and_no_url(code):
    text = describe(_status_error(code))
    assert str(code) in text and KEY not in text and "http" not in text.lower().replace("http " + str(code), "")


@pytest.mark.parametrize("exc,expected", [(httpx.ConnectTimeout("t"), "in time"), (httpx.ConnectError("[WinError 10061] refused"), "could not be reached"), (RuntimeError("boom key=" + KEY), "RuntimeError")])
def test_describe_other_errors(exc, expected):
    text = describe(exc)
    assert expected in text and KEY not in text and "WinError" not in text


def test_youtube_client_error_never_contains_the_key(monkeypatch):
    def boom(*a, **k):
        raise _status_error(403)

    monkeypatch.setattr(youtube_client.httpx, "get", boom)
    with pytest.raises(youtube_client.YoutubeUnavailable) as caught:
        youtube_client.HttpYoutubeClient(api_key=KEY).search_videos("steel bottle")
    assert KEY not in str(caught.value) and "key=" not in str(caught.value)
    assert caught.value.__suppress_context__ or caught.value.__cause__ is None  # the key-bearing original is not chained into logs


def test_tavily_client_error_never_contains_the_key(monkeypatch):
    def boom(*a, **k):
        raise httpx.ConnectError("[WinError 10061] connection refused " + KEY)

    monkeypatch.setattr(tavily_client.httpx, "post", boom)
    with pytest.raises(tavily_client.TavilyUnavailable) as caught:
        tavily_client.HttpTavilyClient(api_key=KEY).search("steel bottle")
    assert KEY not in str(caught.value) and "WinError" not in str(caught.value)
