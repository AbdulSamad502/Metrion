"""The real vision-extraction implementation — replaces `UnimplementedVisionExtractor` at
the composition root. Extracts exactly the fields `competitor_snapshot` stores (§5): no
field this module cannot name a spec column for is ever emitted.

Design constraints this module exists to honour:
  - C15 (local-only): reaches only a caller-supplied Ollama host, via `OllamaClient` (never
    a hosted provider — there is no code path here that could reach one).
  - Never fabricate (the hard rule, and §5.3 rule 1/E3/E12b specifically): a field the model
    doesn't confidently report, or that fails to parse into its stored type, is *omitted*
    from the result — never defaulted, guessed, or coerced into a plausible-looking value.
    An empty or malformed model response degrades this screenshot's contribution toward
    `PENDING_MANUAL_ENTRY`/`PARTIAL` (existing `evidence/merge.py` logic), exactly the same
    outcome as an illegible screenshot (E12b).
  - The model performs recognition only; every unit conversion (rupees -> paise) and every
    enum normalization (free-text availability -> `Availability`) happens in plain
    deterministic Python below, never inside the prompt or trusted from the model's own
    arithmetic (MN8's "models classify, code computes" principle, applied here too even
    though this is extraction rather than aggregation).
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from competitor_intelligence.evidence.extraction import ExtractedField, ExtractionFailed, ExtractionResult
from competitor_intelligence.evidence.image_store import ImageNotFound, ImageStore
from competitor_intelligence.evidence.ollama_client import OllamaClient, OllamaUnavailable

logger = logging.getLogger(__name__)

# Exactly the columns `competitor_snapshot` (§5) can store from a listing screenshot —
# `variant_key` is deliberately excluded: its derivation is an open production-validation
# blocker (V7, "not yet validated"), so this extractor never guesses at it; it stays a
# manual/seller-supplied field only.
_STRING_FIELDS = ("title", "description", "seller_name", "observed_category")
_PRICE_FIELDS_RUPEES = {
    "listed_price": "listed_price_paise",
    "mrp": "mrp_paise",
    "visible_discount": "visible_discount_paise",
}

_PROMPT = """You are reading a single screenshot of a product listing page from an Indian \
e-commerce marketplace (Amazon.in, Flipkart, or Meesho). Report ONLY what is legibly visible \
in this exact image. Do not guess, infer, or fill in anything you cannot actually read.

Respond with ONLY a single JSON object (no other text) with these keys — omit any key you \
cannot confidently read from the image, do not include it with a null or empty value:

{
  "title": "the product title, verbatim, if visible",
  "description": "product description text, if visible",
  "bullets": ["bullet point 1", "bullet point 2"],
  "seller_name": "the seller/store name, if visible",
  "observed_category": "the product category as displayed (breadcrumb or label), if visible",
  "listed_price": "the current selling price in rupees, as a plain decimal number, e.g. 999.00",
  "mrp": "the MRP/list price in rupees if a separate strikethrough price is shown",
  "visible_discount": "the discount amount in rupees if explicitly shown (not the price itself)",
  "rating": "the star rating out of 5, as a decimal number, e.g. 4.3",
  "rating_count": "the number of ratings/reviews, as a plain integer, e.g. 1234",
  "availability": "the stock status text exactly as shown, e.g. 'In stock' or 'Currently unavailable'"
}

Return ONLY the JSON object."""


def _extract_json_object(text: str) -> dict[str, object] | None:
    """The first complete JSON object in the model's reply. Small vision models often wrap the object in a markdown fence or add a sentence before or after it (sometimes
    containing braces of its own), so this scans for a balanced object rather than assuming the reply starts and ends with one."""
    decoder = json.JSONDecoder()
    index = text.find("{")
    while index != -1:
        try:
            parsed, _ = decoder.raw_decode(text, index)
        except json.JSONDecodeError:
            index = text.find("{", index + 1)
            continue
        if isinstance(parsed, dict):
            return parsed
        index = text.find("{", index + 1)
    return None


_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
_CURRENCY_NOISE = re.compile(r"(?i)(?:₹|\brs\.?|\binr\b|\bmrp\b|m\.r\.p\.?|/-)")


def _single_number(value: object) -> Decimal | None:
    """The one number in a model-reported value ("₹1,299.00", "Rs. 999", "999/-", 4.3), or None. A value with two different numbers ("₹999 ₹1,499") is ambiguous and is
    not guessed at; text with no number, bare NaN/Infinity and booleans are absent, never zero."""
    if value is None or isinstance(value, bool):
        return None
    text = _CURRENCY_NOISE.sub(" ", str(value))
    found = {m.replace(",", "") for m in _NUMBER.findall(text)}
    if len(found) != 1:
        return None
    try:
        number = Decimal(next(iter(found)))
    except InvalidOperation:
        return None
    return number if number.is_finite() else None


def _parse_rupees_to_paise(value: object) -> int | None:
    rupees = _single_number(value)
    return int((rupees * 100).to_integral_value()) if rupees is not None else None


def _parse_rating(value: object) -> str | None:
    text = str(value).strip() if value is not None else ""
    text = re.sub(r"(?i)\s*(?:out of|/)\s*5(?:\.0+)?\b.*$|\s*stars?\b.*$", "", text)  # "4.3 out of 5", "4.3/5", "4.3 stars" -> "4.3"
    rating = _single_number(text)
    if rating is None or rating < 0 or rating > 5:
        return None
    return str(rating)


def _parse_rating_count(value: object) -> int | None:
    """A whole number of ratings ("1,234", "1234 ratings"). A abbreviated count ("1.2K", "3L") cannot be turned into an exact count, so it is absent rather than
    approximated, and so is anything holding two different numbers."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, float):
        return int(value) if value.is_integer() and value >= 0 else None
    text = str(value).strip()
    if re.search(r"\d\s*[kKlLmM]\b|\d\.\d", text):
        return None
    number = _single_number(text)
    return int(number) if number is not None and number >= 0 and number == number.to_integral_value() else None


def _normalize_availability(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    out_of_stock_markers = ("out of stock", "currently unavailable", "unavailable", "sold out")
    in_stock_markers = ("in stock", "available", "add to cart", "buy now")
    if any(marker in text for marker in out_of_stock_markers):
        return "OUT_OF_STOCK"
    if any(marker in text for marker in in_stock_markers):
        return "IN_STOCK"
    return "UNKNOWN"


def _fields_from_model_json(parsed: dict[str, object]) -> tuple[ExtractedField, ...]:
    fields: list[ExtractedField] = []

    for name in _STRING_FIELDS:
        value = parsed.get(name)
        if isinstance(value, str) and value.strip():
            fields.append(ExtractedField(name, value.strip()))

    bullets = parsed.get("bullets")
    if isinstance(bullets, list):
        cleaned = [b.strip() for b in bullets if isinstance(b, str) and b.strip()]
        if cleaned:
            fields.append(ExtractedField("bullets", cleaned))

    for model_key, field_name in _PRICE_FIELDS_RUPEES.items():
        paise = _parse_rupees_to_paise(parsed.get(model_key))
        if paise is not None:
            fields.append(ExtractedField(field_name, paise))

    rating = _parse_rating(parsed.get("rating"))
    if rating is not None:
        fields.append(ExtractedField("rating", rating))

    rating_count = _parse_rating_count(parsed.get("rating_count"))
    if rating_count is not None:
        fields.append(ExtractedField("rating_count", rating_count))

    availability = _normalize_availability(parsed.get("availability"))
    if availability is not None:
        fields.append(ExtractedField("availability", availability))

    return tuple(fields)


@dataclass(frozen=True, slots=True)
class OllamaVisionExtractor:
    """Wired at the composition root (`backend/agents/ceo_hub.py`) with a real
    `HttpOllamaClient` + `LocalDiskImageStore`; tests inject fakes for both, so no test ever
    reaches a real model or the real filesystem."""

    image_store: ImageStore
    ollama: OllamaClient
    model: str

    @staticmethod
    def _failed(image_ref: str, reason: str) -> ExtractionFailed:
        # The snapshot only records that extraction failed (EXTRACTED / EXTRACTION_FAILED); without this line a model timeout, an unreachable model server, a reply that
        # was not JSON and an illegible screenshot are indistinguishable once the capture shows PENDING_MANUAL_ENTRY.
        logger.warning("CI vision extraction failed for %s: %s", image_ref, reason)
        return ExtractionFailed(reason=reason)

    def extract(self, image_ref: str) -> ExtractionResult | ExtractionFailed:
        try:
            image_bytes = self.image_store.read(image_ref)
        except ImageNotFound as exc:
            return self._failed(image_ref, str(exc))

        try:
            raw = self.ollama.generate(model=self.model, prompt=_PROMPT, image_bytes=image_bytes)
        except OllamaUnavailable as exc:
            return self._failed(image_ref, str(exc))

        parsed = _extract_json_object(raw)
        if parsed is None:
            return self._failed(image_ref, "model response did not contain a parseable JSON object")

        fields = _fields_from_model_json(parsed)
        if not fields:
            return self._failed(image_ref, "model reported no legible fields in this screenshot")
        return ExtractionResult(fields=fields)
