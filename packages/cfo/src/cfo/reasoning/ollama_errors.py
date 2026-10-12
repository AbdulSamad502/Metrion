"""Ollama failure text that is safe to show a seller or write to a log: what happened, in words. Never the library's own message (it carries the request URL, and on Windows raw
OS error text such as `[WinError 10061]`). A 404 means the requested model is not installed, and says so. Identical in cfo, competitor_intelligence, product_intelligence and
backend (a unit test compares them)."""

from __future__ import annotations

import httpx


def describe_ollama_error(exc: BaseException, model: str) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        if exc.response.status_code == 404:
            return f"the model '{model}' is not installed on the local model server"
        return f"the local model server answered HTTP {exc.response.status_code}"
    if isinstance(exc, httpx.TimeoutException):
        return "the local model server did not answer in time"
    if isinstance(exc, httpx.TransportError):
        return "the local model server could not be reached"
    return f"unexpected {type(exc).__name__}"
