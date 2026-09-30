"""Classification/extraction-only local Ollama pass that pulls specific product names
(brand + model) mentioned inside a raw Tavily/YouTube result's own text — discovery
precision fix (2026-09-30).

**Why this exists:** live testing showed that after the previous grouping fix
(`discovery/candidate_synthesis.py`'s real-title/Jaccard-grouping pass), most discovered
"candidates" were still generic review-roundup article titles — "The 10 Best Running Shoes
for Men in 2026" — not actual distinct products. That's because a raw Tavily/YouTube result
was treated as describing exactly one candidate idea, keyed by its own title, even though a
roundup article's *content* actually names several distinct specific products (e.g. "Nike
Pegasus 41", "Asics Novablast 4"). This module's only job is to list the specific product
names literally named in a piece of text, so `candidate_synthesis.py` can turn each one into
its own candidate seed instead of losing them inside one generic roundup title.

Per `CLAUDE.md`'s hard rule ("LLMs explain numbers, they never compute them") and this
package's own MN8/§6.5 discipline ("models classify, code computes"), this module never asks
the model for a count, a score, or a ranking — the model returns a **plain list of short
strings and nothing else**. All grouping, counting, deduplication and source attribution
stays in `candidate_synthesis.py`, in plain deterministic code — this module never touches
`calc_engine` and never produces a number of any kind.

**The model is explicitly instructed to return only products it finds literally named in the
text — never to invent, infer, or guess a plausible-sounding product it doesn't see stated.**
An empty list (nothing named) is a normal, expected, non-error outcome — a Reddit thread with
no specific product mentioned should, and often does, extract nothing; callers must not treat
an empty list as a failure to work around.

Same local-Ollama-call shape as `review_insight/text_extraction.py` (plain `/api/generate`,
no `images` field) — reused, not reinvented; same `OLLAMA_HOST`-pointed, local-only posture
(C15). This module's return contract deliberately differs from `text_extraction.py`'s
Result/Failed dataclass pair: `ProductExtractionUnavailable` is *raised*, not returned,
because the caller (`candidate_synthesis.py`) needs a simple try/except per raw result to
decide "extraction-first grouping" vs. "similarity-based fallback" for that one result, not a
Result object it has to unwrap on every call site.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Protocol


class ProductExtractionClient(Protocol):
    def extract_products(self, text: str, *, category_text: str) -> list[str]: ...


class ProductExtractionUnavailable(Exception):
    """The local Ollama model server could not be reached, timed out, returned a non-2xx
    response, or its response could not be parsed into the expected shape — never a reason to
    fabricate a product name. Callers must degrade to the whole-source-title fallback path,
    never crash the run (module docstring; same convention as `text_extraction.py`'s
    `OllamaTextUnavailable`)."""


_PROMPT_TEMPLATE = """You are reading a piece of text about {category_label}. List ONLY the \
specific product names (brand + model, e.g. "Nike Pegasus 41", "Asics Novablast 4") that are \
EXPLICITLY, LITERALLY named in the text below.

Rules — follow exactly:
- Only list a product if its brand and model are actually written in the text below.
- NEVER invent, infer, or guess a plausible-sounding product that is not literally present \
in the text.
- Do NOT rank, score, count, or say which is "best" — return a plain list only, in any order.
- If the text does not literally name any specific product, return an empty list. An empty \
list is the correct answer when nothing is named — do not force an entry.

Respond with ONLY a single JSON object (no other text, no explanation):

{{"products": ["<product name>", ...]}}

Text:
{text}"""


def _build_prompt(text: str, *, category_text: str) -> str:
    category_label = category_text.strip() if category_text and category_text.strip() else "a product category"
    return _PROMPT_TEMPLATE.format(category_label=category_label, text=text)


def _extract_json_object(text: str) -> dict[str, object] | None:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _parse_products(raw: object) -> list[str]:
    """Plain list of short strings only — no score, no ranking, no number of any kind
    attached (module docstring). Anything that isn't a non-empty string entry is dropped
    rather than coerced, since a malformed entry is not a product name."""
    if not isinstance(raw, list):
        return []
    products: list[str] = []
    for entry in raw:
        if not isinstance(entry, str):
            continue
        cleaned = re.sub(r"\s+", " ", entry.strip().strip("\"'").strip())
        if cleaned:
            products.append(cleaned)
    return products


@dataclass(frozen=True, slots=True)
class OllamaProductExtractionClient:
    """The real client. `host`/`model` point at a local-only Ollama instance (`OLLAMA_HOST`
    env var, same convention as `OllamaTextInsightExtractor`) — C15 (local-only derivation)
    holds structurally, same reasoning as `evidence/ollama_client.py`'s own docstring."""

    host: str
    model: str
    timeout_seconds: float = 90.0

    def extract_products(self, text: str, *, category_text: str) -> list[str]:
        if not text or not text.strip():
            return []

        import httpx

        prompt = _build_prompt(text, category_text=category_text)
        try:
            response = httpx.post(
                f"{self.host}/api/generate",
                # think=False: confirmed via live testing against real Tavily content — a
                # reasoning model's <think> trace pushed response time past a 60s timeout on
                # typical local hardware, silently turning every real extraction into a
                # timeout that then got recorded identically to "no product found," masking a
                # technical failure as a real negative result (exactly what CLAUDE.md's eval
                # guidance warns against). Disabling it dropped the same real call from a 120s+
                # timeout to ~2-50s depending on content length, with correct results.
                json={"model": self.model, "prompt": prompt, "stream": False, "think": False},
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ProductExtractionUnavailable(f"Ollama request failed: {exc}") from exc

        body = response.json()
        raw_text = body.get("response")
        if not isinstance(raw_text, str):
            raise ProductExtractionUnavailable("Ollama response had no 'response' text field")

        parsed = _extract_json_object(raw_text)
        if parsed is None:
            raise ProductExtractionUnavailable("model response did not contain a parseable JSON object")

        return _parse_products(parsed.get("products"))


class UnimplementedProductExtractionClient:
    """Safe default for any composition root not yet configured with a real client, and for
    tests to inject a fake in its place — mirrors `UnimplementedTextInsightExtractor`."""

    def extract_products(self, text: str, *, category_text: str) -> list[str]:
        raise NotImplementedError(
            "No product extraction client wired — inject a fake ProductExtractionClient for "
            "tests, or configure OllamaProductExtractionClient at the composition root."
        )


def extract_product_mentions(text: str, *, category_text: str, client: ProductExtractionClient) -> list[str]:
    """Thin, testable entry point `candidate_synthesis.py` calls once per raw Tavily
    result/YouTube video — delegates to `client` and propagates `ProductExtractionUnavailable`
    unchanged so the caller decides its own fallback (module docstring); never swallows the
    exception itself, and never modifies what the model returned beyond `client`'s own
    parsing (no scoring, ranking or numeric value ever attached here)."""
    if not text or not text.strip():
        return []
    return client.extract_products(text, category_text=category_text)
