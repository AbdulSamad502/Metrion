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
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from competitor_intelligence.evidence.extraction import ExtractedField, ExtractionFailed, ExtractionResult
from competitor_intelligence.evidence.image_store import ImageNotFound, ImageStore
from competitor_intelligence.evidence.ollama_client import OllamaClient, OllamaUnavailable

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
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _parse_rupees_to_paise(value: object) -> int | None:
    if value is None:
        return None
    try:
        rupees = Decimal(str(value).replace(",", "").replace("₹", "").strip())
    except (InvalidOperation, ValueError):
        return None
    return int((rupees * 100).to_integral_value())


def _parse_rating(value: object) -> str | None:
    try:
        rating = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None
    if rating < 0 or rating > 5:
        return None
    return str(rating)


def _parse_rating_count(value: object) -> int | None:
    digits = re.sub(r"[^\d]", "", str(value)) if value is not None else ""
    return int(digits) if digits else None


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

    def extract(self, image_ref: str) -> ExtractionResult | ExtractionFailed:
        try:
            image_bytes = self.image_store.read(image_ref)
        except ImageNotFound as exc:
            return ExtractionFailed(reason=str(exc))

        try:
            raw = self.ollama.generate(model=self.model, prompt=_PROMPT, image_bytes=image_bytes)
        except OllamaUnavailable as exc:
            return ExtractionFailed(reason=str(exc))

        parsed = _extract_json_object(raw)
        if parsed is None:
            return ExtractionFailed(reason="model response did not contain a parseable JSON object")

        fields = _fields_from_model_json(parsed)
        if not fields:
            return ExtractionFailed(reason="model reported no legible fields in this screenshot")
        return ExtractionResult(fields=fields)
