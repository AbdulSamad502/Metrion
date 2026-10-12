"""Classification-only local Ollama pass over YouTube top comments + Tavily-fetched web
article snippets — PI build plan §2/§0b. TEXT input this time (not screenshots/vision, CI's
`review_insight/extraction.py`/`ollama_extractor.py` pattern), which is why this module talks
to Ollama's plain `/api/generate` (no `images` field) rather than reusing CI's
`evidence.ollama_client.OllamaClient` Protocol, whose `generate()` signature mandates
`image_bytes`.

Per MN8/§6.5 ("models classify, code computes"), this module's job stops at
classification — a sentiment label and short theme tags per text. Turning those labels into
proportions/ratios is `aggregate.py`'s job, in plain deterministic `Fraction` code, never
here and never inside a prompt.

**`insight_source_type` is assigned by the caller of `extract()`, never inferred by the
model** — every call is scoped to exactly one of `YOUTUBE_COMMENTARY` | `WEB_EDITORIAL`
(§0b), so a `YOUTUBE_COMMENTARY` batch and a `WEB_EDITORIAL` batch are never combined into one
extraction call, and their outputs are never merged before that tag is attached.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Protocol, Sequence
from product_intelligence.ollama_errors import describe_ollama_error

SENTIMENTS = ("POSITIVE", "NEGATIVE", "NEUTRAL")
SOURCE_TYPES = ("YOUTUBE_COMMENTARY", "WEB_EDITORIAL")


@dataclass(frozen=True, slots=True)
class TextObservation:
    """One text's classification — never a reproduction of the text itself (same C7/C9
    discipline as CI's `ReviewObservation`: no raw comment/article corpus ever leaves this
    module in the return value)."""

    sentiment: str  # one of SENTIMENTS
    themes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TextExtractionResult:
    insight_source_type: str  # YOUTUBE_COMMENTARY | WEB_EDITORIAL
    observations: tuple[TextObservation, ...]


@dataclass(frozen=True, slots=True)
class TextExtractionFailed:
    insight_source_type: str
    reason: str


class TextInsightExtractor(Protocol):
    def extract(
        self, texts: Sequence[str], *, insight_source_type: str
    ) -> TextExtractionResult | TextExtractionFailed: ...


class OllamaTextUnavailable(Exception):
    """The local Ollama model server could not be reached, timed out, or returned a non-2xx
    response — never a reason to fabricate a classification. Treated as extraction failure,
    same terms as CI's `OllamaUnavailable`."""


_PROMPT_TEMPLATE = """You are classifying short pieces of text about a candidate product \
opportunity ({source_label}). For EACH numbered text below, classify its overall sentiment \
and assign short theme tags — do not quote or reproduce the text.

Respond with ONLY a single JSON object (no other text):

{{
  "items": [
    {{"sentiment": "POSITIVE" | "NEGATIVE" | "NEUTRAL", "themes": ["short-theme-tag", ...]}}
  ]
}}

"items" must have exactly {count} entries, in the same order as the numbered texts. Theme \
tags must be short (1-3 words), lowercase, generic categories like "build quality", \
"battery life", "value for money", "shipping" — never a direct quote from the text. If a \
text is not meaningfully about the product (spam, unrelated), classify it "NEUTRAL" with an \
empty themes list.

Texts:
{numbered_texts}"""

_SOURCE_LABELS = {
    "YOUTUBE_COMMENTARY": "YouTube viewer comments",
    "WEB_EDITORIAL": "web article excerpts",
}


def _build_prompt(texts: Sequence[str], *, insight_source_type: str) -> str:
    numbered = "\n".join(f"{i + 1}. {text}" for i, text in enumerate(texts))
    return _PROMPT_TEMPLATE.format(
        source_label=_SOURCE_LABELS.get(insight_source_type, insight_source_type),
        count=len(texts),
        numbered_texts=numbered,
    )


def _extract_json_object(text: str) -> dict[str, object] | None:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _parse_items(raw: object) -> tuple[TextObservation, ...]:
    if not isinstance(raw, list):
        return ()
    observations: list[TextObservation] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        sentiment = str(entry.get("sentiment", "")).strip().upper()
        if sentiment not in SENTIMENTS:
            continue
        themes_raw = entry.get("themes", [])
        themes = (
            tuple(t.strip().lower() for t in themes_raw if isinstance(t, str) and t.strip())
            if isinstance(themes_raw, list)
            else ()
        )
        observations.append(TextObservation(sentiment=sentiment, themes=themes))
    return tuple(observations)


class UnimplementedTextInsightExtractor:
    """Safe default for any composition root not yet configured with a real extractor, and
    for tests to inject a fake in its place — mirrors CI's `UnimplementedReviewVisionExtractor`."""

    def extract(
        self, texts: Sequence[str], *, insight_source_type: str
    ) -> TextExtractionResult | TextExtractionFailed:
        raise NotImplementedError(
            "No text insight extractor wired — inject a fake TextInsightExtractor for tests, "
            "or configure OllamaTextInsightExtractor at the composition root."
        )


@dataclass(frozen=True, slots=True)
class OllamaTextInsightExtractor:
    """The real extractor. `host`/`model` point at a local-only Ollama instance
    (`OLLAMA_HOST` env var, same convention as CI/CFO) — C15 (local-only derivation) holds
    structurally, same reasoning as `evidence/ollama_client.py`'s own docstring."""

    host: str
    model: str
    timeout_seconds: float = 90.0

    def extract(
        self, texts: Sequence[str], *, insight_source_type: str
    ) -> TextExtractionResult | TextExtractionFailed:
        if insight_source_type not in SOURCE_TYPES:
            raise ValueError(f"insight_source_type must be one of {SOURCE_TYPES}, got {insight_source_type!r}")
        if not texts:
            return TextExtractionFailed(insight_source_type=insight_source_type, reason="no texts to classify")

        import httpx

        prompt = _build_prompt(texts, insight_source_type=insight_source_type)
        try:
            response = httpx.post(
                f"{self.host}/api/generate",
                # think=False: a reasoning model (e.g. qwen3) otherwise emits a long <think>
                # trace before every answer — confirmed via live testing to push response time
                # past a 60s timeout on typical local hardware, which then silently degrades
                # every call to "unavailable" rather than actually classifying anything.
                json={"model": self.model, "prompt": prompt, "stream": False, "think": False},
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            return TextExtractionFailed(insight_source_type=insight_source_type, reason=f"Ollama request failed: {describe_ollama_error(exc, self.model)}")

        body = response.json()
        raw_text = body.get("response")
        if not isinstance(raw_text, str):
            return TextExtractionFailed(
                insight_source_type=insight_source_type, reason="Ollama response had no 'response' text field"
            )

        parsed = _extract_json_object(raw_text)
        if parsed is None:
            return TextExtractionFailed(
                insight_source_type=insight_source_type, reason="model response did not contain a parseable JSON object"
            )

        observations = _parse_items(parsed.get("items"))
        if not observations:
            return TextExtractionFailed(
                insight_source_type=insight_source_type, reason="model reported no classifiable items"
            )
        return TextExtractionResult(insight_source_type=insight_source_type, observations=observations)
