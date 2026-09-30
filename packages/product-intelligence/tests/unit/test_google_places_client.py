"""supplier/google_places_client.py — free-tier id-only search vs. paid-tier enrichment field
mask split. All HTTP calls mocked; no live network call in this unit test."""

from __future__ import annotations

import httpx
import pytest

from product_intelligence.supplier.google_places_client import HttpPlacesClient, PlacesUnavailable


class _FakeResponse:
    def __init__(self, json_body: dict, status_code: int = 200) -> None:
        self._json_body = json_body
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=None, response=None)  # type: ignore[arg-type]

    def json(self) -> dict:
        return self._json_body


def test_search_place_ids_uses_free_tier_field_mask(monkeypatch: pytest.MonkeyPatch) -> None:
    captured_headers: dict = {}

    def _fake_post(url, *, headers, json, timeout):
        captured_headers.update(headers)
        return _FakeResponse({"places": [{"id": "p1", "displayName": {"text": "Acme Supplier"}}]})

    monkeypatch.setattr(httpx, "post", _fake_post)

    client = HttpPlacesClient(api_key="fake-key")
    results = client.search_place_ids("wireless earbuds supplier")

    assert len(results) == 1
    assert results[0].place_id == "p1"
    assert results[0].display_name == "Acme Supplier"
    assert captured_headers["X-Goog-FieldMask"] == "places.id,places.displayName"
    assert "nationalPhoneNumber" not in captured_headers["X-Goog-FieldMask"]


def test_enrich_place_uses_paid_tier_field_mask_with_contact_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    captured_headers: dict = {}

    def _fake_get(url, *, headers, timeout):
        captured_headers.update(headers)
        return _FakeResponse(
            {
                "id": "p1",
                "displayName": {"text": "Acme Supplier"},
                "nationalPhoneNumber": "+91-9999999999",
                "websiteUri": "https://acme.example.com",
                "formattedAddress": "123 Industrial Estate, Mumbai",
            }
        )

    monkeypatch.setattr(httpx, "get", _fake_get)

    client = HttpPlacesClient(api_key="fake-key")
    details = client.enrich_place("p1")

    assert details is not None
    assert details.phone == "+91-9999999999"
    assert details.website == "https://acme.example.com"
    assert "nationalPhoneNumber" in captured_headers["X-Goog-FieldMask"]
    assert "websiteUri" in captured_headers["X-Goog-FieldMask"]


def test_search_place_ids_raises_places_unavailable_on_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(*args, **kwargs):
        raise httpx.ConnectError("timeout")

    monkeypatch.setattr(httpx, "post", _raise)
    client = HttpPlacesClient(api_key="fake-key")

    with pytest.raises(PlacesUnavailable):
        client.search_place_ids("query")


def test_search_place_ids_returns_empty_list_when_no_places_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(httpx, "post", lambda *a, **kw: _FakeResponse({}))
    client = HttpPlacesClient(api_key="fake-key")
    assert client.search_place_ids("query") == []


def test_search_place_ids_skips_malformed_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        httpx,
        "post",
        lambda *a, **kw: _FakeResponse({"places": [{"id": "p1"}, {"displayName": {"text": "no id"}}]}),
    )
    client = HttpPlacesClient(api_key="fake-key")
    results = client.search_place_ids("query")
    assert results == []


def test_enrich_place_returns_none_when_no_display_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: _FakeResponse({"id": "p1"}))
    client = HttpPlacesClient(api_key="fake-key")
    assert client.enrich_place("p1") is None
