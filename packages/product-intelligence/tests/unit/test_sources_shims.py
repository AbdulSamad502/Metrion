"""7c: the old `product_intelligence.sources.*` import paths are shims that ARE the market_signals
modules (same object), so isinstance/except clauses and module state (rate-limit semaphores) are shared."""

import importlib

import pytest

NAMES = ["tavily_client", "youtube_client", "cache", "rate_limiter"]


@pytest.mark.parametrize("name", NAMES)
def test_shim_module_is_the_market_signals_module(name):
    old = importlib.import_module(f"product_intelligence.sources.{name}")
    new = importlib.import_module(f"market_signals.{name}")
    assert old is new


def test_exception_classes_are_shared_across_both_paths():
    from market_signals.tavily_client import TavilyUnavailable as New
    from product_intelligence.sources.tavily_client import TavilyUnavailable as Old

    assert Old is New


def test_patching_through_the_old_path_affects_the_real_limiter(monkeypatch):
    from market_signals import rate_limiter as real
    from product_intelligence.sources import rate_limiter as old

    monkeypatch.setattr(old, "DEFAULT_MAX_CONCURRENT_BY_SOURCE", {"x": 1})
    assert real.DEFAULT_MAX_CONCURRENT_BY_SOURCE == {"x": 1}


def test_from_import_of_the_package_attribute_returns_the_same_object():
    from product_intelligence.sources import youtube_client as via_package

    import market_signals.youtube_client as real

    assert via_package is real
