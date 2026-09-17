"""Shared pytest fixtures."""

from __future__ import annotations

import pytest

from calc_engine.types import Bearer


def make_bearer_resolver(mapping: dict[tuple[str, str], Bearer]):
    """A plain dict-backed BearerResolver for tests — production wiring resolves this from
    discount_bearer_config (deterministic-engine.md §5.3), not a dict."""

    def resolver(marketplace: str, component_code: str) -> Bearer:
        return mapping.get((marketplace, component_code), Bearer.UNKNOWN)

    return resolver


@pytest.fixture
def empty_bearer_resolver():
    return make_bearer_resolver({})
