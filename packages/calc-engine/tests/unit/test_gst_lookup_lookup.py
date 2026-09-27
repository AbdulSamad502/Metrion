"""`gst_applicability_lookup`'s composition logic (§8.4.1) against FAKE `GstFetcher`/
`LlmProvider` implementations only — no real network or LLM call anywhere in this file, per
the checkpoint's own non-goal ("do not make this checkpoint depend on live external
reachability"). Mirrors `competitor_intelligence`'s own fake-injection discipline.
"""

from __future__ import annotations

from datetime import datetime, timezone
from fractions import Fraction
from uuid import uuid4

from calc_engine.gst_lookup.allowlist import TIER_1, tier_for_host
from calc_engine.gst_lookup.fetcher import FetchError, RawPage
from calc_engine.gst_lookup.known_pages import KnownPage
from calc_engine.gst_lookup.lookup import gst_applicability_lookup
from calc_engine.gst_lookup.types import GstLookupNoMatch, GstLookupQuery, GstLookupResult

_NOW = datetime(2026, 9, 25, tzinfo=timezone.utc)

_TIER1_URL = "https://gst.gov.in/rates/electronics"  # gst.gov.in is a real Tier-1 host.
_TIER2_URL = "https://busy.in/gst-rates/stationery/"  # a real Tier-2 host.

_TIER1_PAGE = KnownPage(
    domain="gst.gov.in", category="electronics", url=_TIER1_URL, source_title="GST Portal"
)
_TIER2_PAGE = KnownPage(
    domain="busy.in", category="stationery", url=_TIER2_URL, source_title="Busy stationery rates"
)


class FakeFetcher:
    """Injected in place of `HttpxGstFetcher` — never touches the network."""

    def __init__(self, responses: dict[str, RawPage | FetchError]) -> None:
        self._responses = responses

    def fetch(self, url: str) -> RawPage | FetchError:
        return self._responses.get(url, FetchError(reason="not stubbed for this test"))


class FakeLlmProvider:
    """Injected in place of a real `LlmProvider`. Keyed by the `source_url` substring that
    `build_extraction_prompt` embeds in every prompt it builds, so a fake can respond
    differently per fetched page without inspecting the whole prompt text."""

    def __init__(self, responses_by_url: dict[str, str]) -> None:
        self._responses_by_url = responses_by_url
        self.prompts_seen: list[str] = []

    def complete(self, *, model: str, prompt: str) -> str:
        self.prompts_seen.append(prompt)
        for url, response in self._responses_by_url.items():
            if url in prompt:
                return response
        return "MATCH: NO\n"


def test_tier_1_before_tier_2_ordering_is_real() -> None:
    assert tier_for_host(_TIER1_URL) == TIER_1
    assert tier_for_host(_TIER2_URL) != TIER_1


def test_successful_tier_1_match_returns_genuine_result() -> None:
    fetcher = FakeFetcher(
        {
            _TIER1_URL: RawPage(
                url=_TIER1_URL,
                status_code=200,
                body="Mobile phones and telephone sets (HSN 8517) attract GST at 18%.",
                fetched_at=_NOW,
            )
        }
    )
    llm = FakeLlmProvider(
        {_TIER1_URL: "MATCH: YES\nRATE_PCT: 18\nHSN: 8517\nCATEGORY: mobile phones\nAMBIGUOUS: NO\n"}
    )

    result = gst_applicability_lookup(
        GstLookupQuery(product_title="Mobile phone", category="electronics"),
        fetcher=fetcher,
        llm=llm,
        tenant_id=uuid4(),
        computed_at=_NOW,
        model="test-model",
        known_pages=(_TIER1_PAGE, _TIER2_PAGE),
    )

    assert isinstance(result, GstLookupResult)
    assert result.source_url == _TIER1_URL
    assert result.likely_rate_pct == Fraction(18)
    assert result.likely_hsn == "8517"
    assert result.retrieved_at == _NOW
    assert result.ambiguity_note is None


def test_falls_through_to_tier_2_when_tier_1_fetch_fails() -> None:
    fetcher = FakeFetcher(
        {
            _TIER1_URL: FetchError(reason="timeout"),
            _TIER2_URL: RawPage(
                url=_TIER2_URL,
                status_code=200,
                body="Pens, markers and highlighters (HSN 9608) attract GST at 18%.",
                fetched_at=_NOW,
            ),
        }
    )
    llm = FakeLlmProvider(
        {_TIER2_URL: "MATCH: YES\nRATE_PCT: 18\nHSN: 9608\nCATEGORY: pens\nAMBIGUOUS: NO\n"}
    )

    result = gst_applicability_lookup(
        GstLookupQuery(product_title="Gel pen", category="stationery"),
        fetcher=fetcher,
        llm=llm,
        tenant_id=uuid4(),
        computed_at=_NOW,
        model="test-model",
        known_pages=(_TIER1_PAGE, _TIER2_PAGE),
    )

    assert isinstance(result, GstLookupResult)
    assert result.source_url == _TIER2_URL
    assert result.likely_rate_pct == Fraction(18)


def test_genuine_no_match_produces_gst_lookup_no_match() -> None:
    fetcher = FakeFetcher(
        {
            _TIER1_URL: RawPage(url=_TIER1_URL, status_code=200, body="Irrelevant content.", fetched_at=_NOW),
            _TIER2_URL: RawPage(url=_TIER2_URL, status_code=200, body="Also irrelevant.", fetched_at=_NOW),
        }
    )
    llm = FakeLlmProvider({})  # every prompt falls through to the fake's default "MATCH: NO".

    result = gst_applicability_lookup(
        GstLookupQuery(product_title="An obscure item with no known page"),
        fetcher=fetcher,
        llm=llm,
        tenant_id=uuid4(),
        computed_at=_NOW,
        model="test-model",
        known_pages=(_TIER1_PAGE, _TIER2_PAGE),
    )

    assert isinstance(result, GstLookupNoMatch)
    assert set(result.attempted_urls) == {_TIER1_URL, _TIER2_URL}
    assert result.reason == "NO_RELIABLE_SOURCE_FOUND"


def test_every_fetch_failing_is_handled_gracefully_not_crashing() -> None:
    fetcher = FakeFetcher(
        {
            _TIER1_URL: FetchError(reason="timeout"),
            _TIER2_URL: FetchError(reason="http 500", status_code=500),
        }
    )
    llm = FakeLlmProvider({})

    result = gst_applicability_lookup(
        GstLookupQuery(product_title="Anything"),
        fetcher=fetcher,
        llm=llm,
        tenant_id=uuid4(),
        computed_at=_NOW,
        model="test-model",
        known_pages=(_TIER1_PAGE, _TIER2_PAGE),
    )

    assert isinstance(result, GstLookupNoMatch)
    # The LLM is never even called when every fetch fails.
    assert llm.prompts_seen == []


def test_malformed_llm_response_treated_as_no_match_not_a_crash() -> None:
    fetcher = FakeFetcher(
        {
            _TIER1_URL: RawPage(url=_TIER1_URL, status_code=200, body="Some page text.", fetched_at=_NOW),
        }
    )
    llm = FakeLlmProvider({_TIER1_URL: "this is not the expected format at all"})

    result = gst_applicability_lookup(
        GstLookupQuery(product_title="Anything"),
        fetcher=fetcher,
        llm=llm,
        tenant_id=uuid4(),
        computed_at=_NOW,
        model="test-model",
        known_pages=(_TIER1_PAGE,),
    )

    assert isinstance(result, GstLookupNoMatch)


def test_ambiguous_match_populates_ambiguity_note_and_alternatives() -> None:
    fetcher = FakeFetcher(
        {
            _TIER2_URL: RawPage(
                url=_TIER2_URL,
                status_code=200,
                body="Toys (HSN 9503): non-electronic 5%, electronic/battery-operated 18%.",
                fetched_at=_NOW,
            )
        }
    )
    llm = FakeLlmProvider(
        {
            _TIER2_URL: (
                "MATCH: YES\n"
                "RATE_PCT: 5\n"
                "HSN: 9503\n"
                "CATEGORY: non-electronic toys\n"
                "AMBIGUOUS: YES\n"
                "AMBIGUITY_NOTE: Same HSN 9503 also covers electronic toys at 18%.\n"
                "ALTERNATIVE: rate_pct=18; hsn=9503; category=electronic toys\n"
            )
        }
    )

    result = gst_applicability_lookup(
        GstLookupQuery(product_title="Wooden toy car", category="toys"),
        fetcher=fetcher,
        llm=llm,
        tenant_id=uuid4(),
        computed_at=_NOW,
        model="test-model",
        known_pages=(_TIER2_PAGE,),
    )

    assert isinstance(result, GstLookupResult)
    assert result.ambiguity_note is not None
    assert len(result.alternatives) == 1
    assert result.alternatives[0]["rate_pct"] == Fraction(18)
    assert result.alternatives[0]["hsn"] == "9503"
