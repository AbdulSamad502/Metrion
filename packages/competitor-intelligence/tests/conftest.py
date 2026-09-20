"""Shared pytest fixtures.

FakeFetcher/FakeParser are for the retired-but-reserved scraping seam (`capture/fetcher.py`,
`capture/parser.py`) — kept in case that code is ever revived behind a licensed data vendor.
FakeVisionExtractor is for the current evidence pipeline (`evidence/extraction.py`). Neither
fake can reach a real network or a real model: both answer from an in-memory dict, and
nothing under tests/ ever constructs `HttpxFetcher` or a real vision model client.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import pytest

from competitor_intelligence.capture.fetcher import FetchError, RawPage
from competitor_intelligence.capture.parser import ParseError, ParsedListing
from competitor_intelligence.evidence.extraction import ExtractionFailed, ExtractionResult


@dataclass
class FakeFetcher:
    """Answers from an in-memory map of url -> RawPage | FetchError. Records every url it
    was asked to fetch, so tests can assert it was (or wasn't) called."""

    responses: dict[str, RawPage | FetchError] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)

    def fetch(self, url: str) -> RawPage | FetchError:
        self.calls.append(url)
        if url not in self.responses:
            return FetchError(reason="no fixture registered for this url")
        return self.responses[url]


@dataclass
class FakeParser:
    """Answers from an in-memory map of RawPage.url -> ParsedListing | ParseError."""

    responses: dict[str, ParsedListing | ParseError] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)

    def parse(self, page: RawPage, marketplace) -> ParsedListing | ParseError:
        self.calls.append(page.url)
        if page.url not in self.responses:
            return ParseError(reason="no fixture registered for this page")
        return self.responses[page.url]


def make_raw_page(url: str, *, fetched_at: datetime, body: str = "<html/>") -> RawPage:
    return RawPage(url=url, status_code=200, body=body, fetched_at=fetched_at)


@pytest.fixture
def fake_fetcher() -> FakeFetcher:
    return FakeFetcher()


@pytest.fixture
def fake_parser() -> FakeParser:
    return FakeParser()


@dataclass
class FakeVisionExtractor:
    """Answers from an in-memory map of image_ref -> ExtractionResult | ExtractionFailed.
    Records every image_ref it was asked to extract."""

    responses: dict[str, ExtractionResult | ExtractionFailed] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)

    def extract(self, image_ref: str) -> ExtractionResult | ExtractionFailed:
        self.calls.append(image_ref)
        if image_ref not in self.responses:
            return ExtractionFailed(reason="no fixture registered for this image_ref")
        return self.responses[image_ref]


@pytest.fixture
def fake_extractor() -> FakeVisionExtractor:
    return FakeVisionExtractor()
