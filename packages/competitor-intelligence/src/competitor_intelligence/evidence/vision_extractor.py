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
  "title": "the title of the MAIN product this page is about, verbatim (the large heading beside the product photos, next to the price and Buy button). IGNORE sponsored banners, ads, 'AD' strips, 'similar products' and recommendation rows: their titles are other products. Omit this key if the main title is not visible",
  "description": "product description text, if visible",
  "bullets": ["bullet point 1", "bullet point 2"],
  "seller_name": "the seller/store name, if visible",
  "observed_category": "the product category as displayed (breadcrumb or label), if visible",
  "listed_price": "the current selling price in rupees, as a plain decimal number, e.g. 999.00",
  "mrp": "the MRP/list price in rupees if a separate strikethrough price is shown",
  "visible_discount": "a discount ONLY when the page states it as a rupee amount, for example 'Save ₹100'. A percentage such as '-39%' is NOT a rupee amount and is already part of the listed price: omit this key for it",
  "delivery_charge": "the delivery/shipping charge in rupees as a plain number, or the word FREE if free delivery is stated",
  "offers": [{"kind": "COUPON or BANK_OFFER or OTHER", "amount": "rupees off as a plain number, if stated", "condition": "the condition text if the offer needs one (a card, a first order, a minimum spend)"}],
  "rating": "the star rating out of 5, as a decimal number, e.g. 4.3",
  "rating_count": "the number of ratings/reviews, as a plain integer, e.g. 1234",
  "availability": "the stock status text exactly as shown for the MAIN product, e.g. 'In stock' or 'Currently unavailable'. A single colour or size marked out of stock does not make the product unavailable. Omit this key if no stock text is shown"
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
    if value is None or isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return None  # a list or an object is not a number: str() of {"a": 1} would otherwise read as 1
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


def _parse_delivery(value: object) -> int | None:
    """A stated delivery charge in paise. "FREE" (or "free delivery") is an observed zero; an absent or unreadable value is None — never zero, because a missing delivery
    charge is not free delivery (deterministic-engine.md 5.15.2 rule 1)."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str) and re.search(r"(?i)\bfree\b", value):
        return 0
    return _parse_rupees_to_paise(value)


MAX_OFFERS = 5


def _parse_offers(value: object) -> list[dict[str, object]]:
    """The offers a screenshot showed, as plain records. `amount_paise` is kept only when one number was stated; a `condition` marks the offer as conditional (it is then
    never subtracted from a price). Anything not a list of objects is absent. The text kept is short and structural, never a copy of the listing's marketing copy."""
    if not isinstance(value, list):
        return []
    out: list[dict[str, object]] = []
    for item in value[:MAX_OFFERS]:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "OTHER").strip().upper()
        kind = kind if kind in ("COUPON", "BANK_OFFER") else "OTHER"
        amount = _parse_rupees_to_paise(item.get("amount"))
        condition = item.get("condition")
        condition_text = " ".join(str(condition).split())[:120] if isinstance(condition, str) and condition.strip() else None
        if amount is None and condition_text is None:
            continue  # nothing usable was read
        out.append({"kind": kind, "amount_paise": amount if amount and amount > 0 else None, "condition_text": condition_text})
    return out


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


def _fields_from_model_json(parsed: dict[str, object], *, validate: bool = True) -> tuple[ExtractedField, ...]:
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

    delivery = _parse_delivery(parsed.get("delivery_charge"))
    if delivery is not None:
        fields.append(ExtractedField("delivery_charge_paise", delivery))
    offers = _parse_offers(parsed.get("offers"))
    if offers:
        fields.append(ExtractedField("offers", offers))

    rating = _parse_rating(parsed.get("rating"))
    if rating is not None and Decimal(rating) != 0:  # a printed rating of 0 stars does not exist: the model writes 0 for "not shown" (measured), so it is absent, never stored as a value
        fields.append(ExtractedField("rating", rating))

    rating_count = _parse_rating_count(parsed.get("rating_count"))
    if rating_count:  # 0 is the same placeholder; "no ratings yet" is simply no rating_count
        fields.append(ExtractedField("rating_count", rating_count))

    availability = _normalize_availability(parsed.get("availability"))
    if availability is not None:
        fields.append(ExtractedField("availability", availability))

    return _drop_unsupported(tuple(fields), parsed)[0] if validate else tuple(fields)


# A third rule, cross-checking price and MRP against a printed "NN% off", was MEASURED and removed: on real llava replies it discarded as many correct values as wrong ones (4 correct, 11 wrong
# on the candidate-prompt replies) and left the share of reported prices that were right unchanged, because the MRP it leans on is itself mostly misread. A check that removes
# right and wrong values alike only hides errors. (scripts/vision_price_eval, docs/evaluation/ci-vision-eval-2026-10-11.md)
# "price_gt_mrp" (the selling price cannot exceed the list price: drop both) is IMPLEMENTED but NOT ADOPTED. Re-audited against the labelled replies it never fired (0 of the 3 baseline and 0 of
# the 20 candidate replies that reported both fields), so it has no measured benefit; and its failure mode is the one that retired the percent rule: when it does fire, the MRP is the field the
# model misreads most (18 of 32 on the candidate prompt), so it would discard a correct price along with a wrong MRP. Enable it per call (`rules=`) only after labelled data shows a benefit.
OPTIONAL_RULES: frozenset[str] = frozenset({"price_gt_mrp"})
ALL_RULES: frozenset[str] = frozenset({"discount"})


def _drop_unsupported(
    fields: tuple[ExtractedField, ...], parsed: dict[str, object], rules: frozenset[str] = ALL_RULES
) -> tuple[tuple[ExtractedField, ...], tuple[str, ...]]:
    """Deterministic consistency checks between values that must agree if they were really read. A value the screenshot cannot support is OMITTED (it then degrades toward
    PENDING_MANUAL_ENTRY like an illegible screenshot), never kept as a plausible-looking number. Nothing is repaired or guessed: when two reads disagree and it cannot be
    told which is wrong, both are dropped."""
    by_name = {f.field_name: f.value for f in fields}
    drop: set[str] = set()
    price, mrp, discount = by_name.get("listed_price_paise"), by_name.get("mrp_paise"), by_name.get("visible_discount_paise")
    if "discount" in rules and discount is not None and (discount <= 0 or (price is not None and discount >= price)):
        drop.add("visible_discount_paise")  # a saving of nothing, or of at least the whole price, is not a reading
    if "price_gt_mrp" in rules and price is not None and mrp is not None and price > mrp:
        drop.update(("listed_price_paise", "mrp_paise"))  # the selling price cannot exceed the list price: one of them is misread and which one is unknown
    return tuple(f for f in fields if f.field_name not in drop), tuple(sorted(drop))


@dataclass(frozen=True, slots=True)
class ReplyAnalysis:
    """What one model reply supports, and what validation REFUSED to keep. `suppressed` names every field the consistency checks removed, so a dropped value is never invisible:
    the extractor logs it against the screenshot, and the evaluation reports whether each suppressed value was right or wrong."""

    fields: tuple[ExtractedField, ...]
    suppressed: tuple[str, ...]
    unvalidated: tuple[ExtractedField, ...]  # the same reply parsed WITHOUT the consistency checks (for measurement only; never stored)


def analyse_reply(reply: str) -> ReplyAnalysis | None:
    """None when the reply holds no parseable JSON object. The single entry point the extractor and the evaluation scripts share, so what is measured is what runs."""
    parsed = _extract_json_object(reply)
    if parsed is None:
        return None
    unvalidated = _fields_from_model_json(parsed, validate=False)
    kept, dropped = _drop_unsupported(unvalidated, parsed)
    return ReplyAnalysis(kept, dropped, unvalidated)


def fields_from_reply(reply: str) -> tuple[ExtractedField, ...] | None:
    """The fields one model reply supports, or None when it holds no parseable object or no supported field (an extraction failure)."""
    analysis = analyse_reply(reply)
    return (analysis.fields or None) if analysis is not None else None


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

        analysis = analyse_reply(raw)
        if analysis is None:
            return self._failed(image_ref, "model response did not contain a parseable JSON object")
        if analysis.suppressed:  # visible, never silent: a value the checks refused to keep is recorded against this screenshot
            logger.warning("CI vision extraction for %s: kept no value for %s (the reads were inconsistent or a placeholder)", image_ref, ", ".join(analysis.suppressed))
        if not analysis.fields:
            return self._failed(image_ref, "model reported no legible fields in this screenshot")
        return ExtractionResult(fields=analysis.fields)
