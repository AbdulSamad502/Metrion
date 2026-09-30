"""Google Places API (New) client — PI build plan §2. **Cost-bounding split enforced at the
call site**, not assumed here: `search_place_ids` uses only the free/uncapped-tier fields
(`id`, `displayName`) and is safe to call for the full post-Stage-1 shortlist;
`enrich_place` reads the paid Pro-tier fields (phone/website/address) and must only be called
by `direct_path/pi_supplier_lookup.py` for the final top-5 candidates the seller explicitly
requested — this module itself does not enforce that cap, it only keeps the two calls
separate so a caller *can* enforce it (module docstring is the contract; the actual
enforcement lives in `pi_supplier_lookup.py`, per the plan's own instruction).

Uses Places API (New) Text Search (`POST https://places.googleapis.com/v1/places:searchText`)
and Place Details (`GET https://places.googleapis.com/v1/places/{place_id}`), both gated by a
`X-Goog-FieldMask` header — the New API requires an explicit field mask on every request, and
the field mask is exactly what separates the free ID-only tier from the paid enrichment tier.
`GOOGLE_PLACES_API_KEY` env var, no default.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

import httpx

_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
_DETAILS_URL = "https://places.googleapis.com/v1/places/{place_id}"


class PlacesUnavailable(Exception):
    """The Places API could not be reached, timed out, or returned a non-2xx response — never
    a reason to fabricate a supplier lead."""


@dataclass(frozen=True, slots=True)
class PlaceIdResult:
    """Free/uncapped-tier result — id + display name only, no contact/address fields."""

    place_id: str
    display_name: str
    retrieved_at: datetime


@dataclass(frozen=True, slots=True)
class PlaceDetails:
    """Paid Pro-tier enrichment — only fetched for the final top-5 (call-site enforced)."""

    place_id: str
    display_name: str
    phone: str | None
    website: str | None
    formatted_address: str | None
    retrieved_at: datetime


class PlacesClient(Protocol):
    def search_place_ids(self, query: str, *, max_results: int = 10) -> list[PlaceIdResult]: ...

    def enrich_place(self, place_id: str) -> PlaceDetails | None: ...


class HttpPlacesClient:
    def __init__(self, *, api_key: str, timeout_seconds: float = 10.0) -> None:
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds

    def search_place_ids(self, query: str, *, max_results: int = 10) -> list[PlaceIdResult]:
        retrieved_at = datetime.now(timezone.utc)
        try:
            response = httpx.post(
                _SEARCH_URL,
                headers={
                    "X-Goog-Api-Key": self._api_key,
                    "X-Goog-FieldMask": "places.id,places.displayName",
                    "Content-Type": "application/json",
                },
                json={"textQuery": query, "maxResultCount": max_results},
                timeout=self._timeout_seconds,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise PlacesUnavailable(f"Places searchText request failed: {exc}") from exc

        try:
            body: dict[str, Any] = response.json()
        except ValueError as exc:
            raise PlacesUnavailable("Places searchText response was not valid JSON") from exc

        places = body.get("places")
        if not isinstance(places, list):
            return []

        results: list[PlaceIdResult] = []
        for entry in places:
            if not isinstance(entry, dict):
                continue
            place_id = entry.get("id")
            display_name = entry.get("displayName", {})
            name_text = display_name.get("text") if isinstance(display_name, dict) else None
            if isinstance(place_id, str) and isinstance(name_text, str):
                results.append(PlaceIdResult(place_id=place_id, display_name=name_text, retrieved_at=retrieved_at))
        return results

    def enrich_place(self, place_id: str) -> PlaceDetails | None:
        retrieved_at = datetime.now(timezone.utc)
        try:
            response = httpx.get(
                _DETAILS_URL.format(place_id=place_id),
                headers={
                    "X-Goog-Api-Key": self._api_key,
                    "X-Goog-FieldMask": "id,displayName,nationalPhoneNumber,websiteUri,formattedAddress",
                },
                timeout=self._timeout_seconds,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise PlacesUnavailable(f"Places details request failed for {place_id}: {exc}") from exc

        try:
            body: dict[str, Any] = response.json()
        except ValueError as exc:
            raise PlacesUnavailable("Places details response was not valid JSON") from exc

        display_name = body.get("displayName", {})
        name_text = display_name.get("text") if isinstance(display_name, dict) else None
        if not isinstance(name_text, str):
            return None

        return PlaceDetails(
            place_id=str(body.get("id", place_id)),
            display_name=name_text,
            phone=body.get("nationalPhoneNumber") if isinstance(body.get("nationalPhoneNumber"), str) else None,
            website=body.get("websiteUri") if isinstance(body.get("websiteUri"), str) else None,
            formatted_address=body.get("formattedAddress") if isinstance(body.get("formattedAddress"), str) else None,
            retrieved_at=retrieved_at,
        )
