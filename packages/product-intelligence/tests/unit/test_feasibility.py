"""discovery/feasibility.py — the one cross-package call PI makes into calc_engine.
`config_repo`/`product_feasibility_estimate_repo` are monkeypatched (no live Postgres);
`estimate_product_feasibility` itself runs for real (pure, DB-free)."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from calc_engine.repositories import config_repo, product_feasibility_estimate_repo

from product_intelligence.discovery.feasibility import compute_candidate_feasibility

_NOW = datetime(2026, 10, 1, tzinfo=timezone.utc)
_TENANT_ID = uuid4()


def _brief(**overrides) -> dict:
    base = {
        "marketplaces": ["FLIPKART"],
        "category_text": "running shoes",
        "budget_paise": 5_000_000,
        "target_price_min_paise": 90_000,
        "target_price_max_paise": 199_900,
    }
    base.update(overrides)
    return base


def _candidate(**overrides) -> dict:
    base = {"candidate_title": "Acme Runner Pro", "observed_category": None, "source_urls": [{"url": "https://a.com/1"}]}
    base.update(overrides)
    return base


@pytest.fixture(autouse=True)
def _patch_save(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(product_feasibility_estimate_repo, "save", lambda tenant_id, estimate: estimate.id)


def test_computed_when_all_inputs_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        config_repo,
        "resolve_fee_reference",
        lambda tenant_id, *, marketplace, category, fee_type, as_of_date: {
            "rate_pct": Decimal("10"), "rate_low_pct": None, "rate_high_pct": None, "source": "test", "confidence": "VERIFIED", "version": 1
        },
    )
    outcome = compute_candidate_feasibility(_TENANT_ID, niche_brief=_brief(), candidate=_candidate(), now=_NOW)

    assert outcome.status == "COMPUTED"
    assert outcome.cogs_basis == "UNKNOWN"
    assert outcome.low_paise is not None and outcome.high_paise is not None
    assert outcome.estimate_ref is not None


def test_unavailable_when_no_marketplace_selected() -> None:
    outcome = compute_candidate_feasibility(
        _TENANT_ID, niche_brief=_brief(marketplaces=[]), candidate=_candidate(), now=_NOW
    )
    assert outcome.status == "UNAVAILABLE"
    assert "marketplace" in outcome.unavailable_reason


def test_unavailable_when_no_category_resolvable() -> None:
    outcome = compute_candidate_feasibility(
        _TENANT_ID, niche_brief=_brief(category_text=None), candidate=_candidate(observed_category=None), now=_NOW
    )
    assert outcome.status == "UNAVAILABLE"
    assert "category" in outcome.unavailable_reason


def test_unavailable_when_no_budget_stated() -> None:
    outcome = compute_candidate_feasibility(
        _TENANT_ID, niche_brief=_brief(budget_paise=None), candidate=_candidate(), now=_NOW
    )
    assert outcome.status == "UNAVAILABLE"
    assert "budget" in outcome.unavailable_reason


def test_unavailable_when_no_target_price_band() -> None:
    outcome = compute_candidate_feasibility(
        _TENANT_ID,
        niche_brief=_brief(target_price_min_paise=None, target_price_max_paise=None),
        candidate=_candidate(),
        now=_NOW,
    )
    assert outcome.status == "UNAVAILABLE"
    assert "target price" in outcome.unavailable_reason


def test_malformed_fee_reference_degrades_to_unavailable_never_crashes_the_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bug-hunt regression (2026-10-01): `resolve_fee_or_unavailable` deliberately raises
    `ValueError` when a `fee_reference` row exists but all three rate fields are NULL — a
    malformed config row (realistic operational data drift), not a programming error.
    Previously this propagated uncaught through `compute_candidate_feasibility`, aborting the
    whole discovery run for every niche_brief in that category until manually fixed. Must now
    degrade to `UNAVAILABLE` with a named reason, same as every other missing-data gap."""
    monkeypatch.setattr(
        config_repo,
        "resolve_fee_reference",
        lambda tenant_id, *, marketplace, category, fee_type, as_of_date: {
            "rate_pct": None, "rate_low_pct": None, "rate_high_pct": None, "source": "test", "confidence": "VERIFIED", "version": 1
        },
    )

    outcome = compute_candidate_feasibility(_TENANT_ID, niche_brief=_brief(), candidate=_candidate(), now=_NOW)

    assert outcome.status == "UNAVAILABLE"
    assert "malformed" in outcome.unavailable_reason
    assert outcome.estimate_ref is None


def test_fee_reference_not_found_still_computes_a_widened_estimate(monkeypatch: pytest.MonkeyPatch) -> None:
    """A missing fee_reference row (the common, honest "not yet configured" case) is NOT the
    same as a malformed one — it degrades to a widened estimate (Brain-1's own rule 2),
    never UNAVAILABLE, and never raises."""
    monkeypatch.setattr(
        config_repo,
        "resolve_fee_reference",
        lambda tenant_id, *, marketplace, category, fee_type, as_of_date: None,
    )

    outcome = compute_candidate_feasibility(_TENANT_ID, niche_brief=_brief(), candidate=_candidate(), now=_NOW)

    assert outcome.status == "COMPUTED"
    assert outcome.cogs_basis == "UNKNOWN"
