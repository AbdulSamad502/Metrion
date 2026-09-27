"""`resolve_gst_rate_for_sku` — OP13's three-tier GST rate-resolution order, composed for real
(deterministic-engine.md §7.2.1 `gst_rate_override` tier 0, §8.2.2 `hsn_gst_reference` tier 2,
cfo-agent.md C5/§6.6/OP13). Pure unit tests — `manual_adjustment_repo.
active_adjustments_for_target` and `config_repo.resolve_hsn_gst_reference` are monkeypatched to
fakes, never touching a real database, mirroring `test_accept_gst_lookup_result.py`'s own
monkeypatch-the-repository-function discipline.

Covers:
1. Tier 0 (`gst_rate_override`) wins outright even when `observed_rate_pct` (tier 1) is also
   supplied.
2. Tier 1 (observed) used when no ACTIVE override exists.
3. Tier 2 (`hsn_gst_reference`) used when neither tier 0 nor tier 1 has anything, and an
   `hsn_code` is supplied.
4. The explicit `GstRateUnresolved` "next step is a GST Applicability Lookup" outcome when
   nothing resolves.
5. Tier 2 is never attempted (resolver not even called) when `hsn_code` is `None`.
6. Tier 0's `effective_from` date gate: a future-dated override is skipped, falling through
   to tier 1/2; a past-or-today-dated override is still used; the "no override at all"
   behaviour is unchanged.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from fractions import Fraction

from backend.services import cfo_actions
from backend.services.cfo_actions import (
    GstRateUnresolved,
    ResolvedGstRate,
    resolve_gst_rate_for_sku,
)

_AS_OF = date(2026, 9, 26)


def _install_fake_active_adjustments_for_target(monkeypatch, rows: list[dict[str, object]]) -> None:
    def fake(tenant_id: uuid.UUID, *, target_type: str, target_ref: str, field: str) -> list[dict[str, object]]:
        assert target_type == "SKU"
        assert field == "gst_rate_override"
        return rows

    monkeypatch.setattr(cfo_actions.manual_adjustment_repo, "active_adjustments_for_target", fake)


def _install_fake_resolve_hsn_gst_reference(monkeypatch, row: dict[str, object] | None, calls: list[str]) -> None:
    def fake(tenant_id: uuid.UUID, *, hsn_code: str, as_of_date: date) -> dict[str, object] | None:
        calls.append(hsn_code)
        return row

    monkeypatch.setattr(cfo_actions.config_repo, "resolve_hsn_gst_reference", fake)


def test_tier0_override_wins_even_when_observed_rate_also_available(monkeypatch) -> None:
    tenant_id = uuid.uuid4()
    override_id = uuid.uuid4()
    lookup_id = uuid.uuid4()
    _install_fake_active_adjustments_for_target(
        monkeypatch,
        [
            {
                "id": override_id,
                "value": {
                    "rate_pct": "18.0000",
                    "hsn": "8517",
                    "category": "mobile phones",
                    "gst_lookup_result_id": str(lookup_id),
                    "effective_from": "2026-09-01",
                },
            }
        ],
    )
    hsn_calls: list[str] = []
    _install_fake_resolve_hsn_gst_reference(monkeypatch, None, hsn_calls)

    result = resolve_gst_rate_for_sku(
        tenant_id,
        sku="SKU-1",
        hsn_code="8517",
        observed_rate_pct=Fraction("12"),  # deliberately different — must be ignored
        as_of_date=_AS_OF,
    )

    assert isinstance(result, ResolvedGstRate)
    assert result.source_tier == "OVERRIDE"
    assert result.rate_pct == Fraction("18")
    assert result.confidence == "MANUAL"
    assert result.manual_adjustment_id == override_id
    assert result.gst_lookup_result_id == lookup_id
    assert hsn_calls == []  # tier 2 never even attempted


def test_tier1_observed_used_when_no_override_exists(monkeypatch) -> None:
    tenant_id = uuid.uuid4()
    _install_fake_active_adjustments_for_target(monkeypatch, [])
    hsn_calls: list[str] = []
    _install_fake_resolve_hsn_gst_reference(monkeypatch, None, hsn_calls)

    result = resolve_gst_rate_for_sku(
        tenant_id,
        sku="SKU-1",
        hsn_code="8517",
        observed_rate_pct=Fraction("12"),
        as_of_date=_AS_OF,
    )

    assert isinstance(result, ResolvedGstRate)
    assert result.source_tier == "OBSERVED"
    assert result.rate_pct == Fraction("12")
    assert result.confidence == "PROVISIONAL"
    assert hsn_calls == []  # tier 1 satisfied it, tier 2 never attempted


def test_tier2_hsn_reference_used_when_tier0_and_tier1_both_miss(monkeypatch) -> None:
    tenant_id = uuid.uuid4()
    _install_fake_active_adjustments_for_target(monkeypatch, [])
    hsn_calls: list[str] = []
    _install_fake_resolve_hsn_gst_reference(
        monkeypatch,
        {
            "hsn_code": "8517",
            "description": "Mobile phones and telephone sets",
            "rate_pct": Decimal("18.0000"),
            "source_url": "https://getswipe.in/blog/article/telephone-gst-rate-hsn-code-8517",
            "source_title": "GST 2.0 rate reform",
            "retrieved_at": None,
            "effective_from": date(2025, 9, 22),
            "effective_to": None,
            "version": 1,
            "confidence": "PROVISIONAL",
        },
        hsn_calls,
    )

    result = resolve_gst_rate_for_sku(
        tenant_id,
        sku="SKU-1",
        hsn_code="85171200",
        observed_rate_pct=None,
        as_of_date=_AS_OF,
    )

    assert isinstance(result, ResolvedGstRate)
    assert result.source_tier == "HSN_REFERENCE"
    assert result.rate_pct == Fraction("18")
    assert result.confidence == "PROVISIONAL"
    assert result.hsn_code_matched == "8517"
    assert result.hsn_reference_source_url == "https://getswipe.in/blog/article/telephone-gst-rate-hsn-code-8517"
    assert hsn_calls == ["85171200"]


def test_no_match_anywhere_returns_explicit_unresolved_outcome(monkeypatch) -> None:
    tenant_id = uuid.uuid4()
    _install_fake_active_adjustments_for_target(monkeypatch, [])
    hsn_calls: list[str] = []
    _install_fake_resolve_hsn_gst_reference(monkeypatch, None, hsn_calls)

    result = resolve_gst_rate_for_sku(
        tenant_id,
        sku="SKU-1",
        hsn_code="9999",
        observed_rate_pct=None,
        as_of_date=_AS_OF,
    )

    assert isinstance(result, GstRateUnresolved)
    assert result.sku == "SKU-1"
    assert result.hsn_code == "9999"
    assert "GST Applicability Lookup" in result.reason
    assert hsn_calls == ["9999"]


def test_tier0_future_dated_override_is_skipped_falls_through_to_tier1(monkeypatch) -> None:
    tenant_id = uuid.uuid4()
    override_id = uuid.uuid4()
    _install_fake_active_adjustments_for_target(
        monkeypatch,
        [
            {
                "id": override_id,
                "value": {
                    "rate_pct": "18.0000",
                    "hsn": "8517",
                    "category": "mobile phones",
                    "gst_lookup_result_id": None,
                    "effective_from": "2026-10-01",  # after _AS_OF (2026-09-26)
                },
            }
        ],
    )
    hsn_calls: list[str] = []
    _install_fake_resolve_hsn_gst_reference(monkeypatch, None, hsn_calls)

    result = resolve_gst_rate_for_sku(
        tenant_id,
        sku="SKU-1",
        hsn_code="8517",
        observed_rate_pct=Fraction("12"),
        as_of_date=_AS_OF,
    )

    assert isinstance(result, ResolvedGstRate)
    assert result.source_tier == "OBSERVED"
    assert result.rate_pct == Fraction("12")


def test_tier0_future_dated_override_falls_through_to_tier2_when_no_observed_rate(monkeypatch) -> None:
    tenant_id = uuid.uuid4()
    override_id = uuid.uuid4()
    _install_fake_active_adjustments_for_target(
        monkeypatch,
        [
            {
                "id": override_id,
                "value": {
                    "rate_pct": "18.0000",
                    "hsn": "8517",
                    "category": "mobile phones",
                    "gst_lookup_result_id": None,
                    "effective_from": "2026-10-01",  # after _AS_OF
                },
            }
        ],
    )
    hsn_calls: list[str] = []
    _install_fake_resolve_hsn_gst_reference(monkeypatch, None, hsn_calls)

    result = resolve_gst_rate_for_sku(
        tenant_id,
        sku="SKU-1",
        hsn_code="8517",
        observed_rate_pct=None,
        as_of_date=_AS_OF,
    )

    assert isinstance(result, GstRateUnresolved)
    assert hsn_calls == ["8517"]  # tier 0 had nothing usable, tier 2 genuinely attempted


def test_tier0_override_effective_today_is_still_used(monkeypatch) -> None:
    tenant_id = uuid.uuid4()
    override_id = uuid.uuid4()
    _install_fake_active_adjustments_for_target(
        monkeypatch,
        [
            {
                "id": override_id,
                "value": {
                    "rate_pct": "18.0000",
                    "hsn": "8517",
                    "category": "mobile phones",
                    "gst_lookup_result_id": None,
                    "effective_from": _AS_OF.isoformat(),  # effective exactly today
                },
            }
        ],
    )
    hsn_calls: list[str] = []
    _install_fake_resolve_hsn_gst_reference(monkeypatch, None, hsn_calls)

    result = resolve_gst_rate_for_sku(
        tenant_id,
        sku="SKU-1",
        hsn_code="8517",
        observed_rate_pct=Fraction("12"),
        as_of_date=_AS_OF,
    )

    assert isinstance(result, ResolvedGstRate)
    assert result.source_tier == "OVERRIDE"
    assert result.rate_pct == Fraction("18")
    assert result.manual_adjustment_id == override_id
    assert hsn_calls == []


def test_tier0_override_effective_in_past_is_still_used(monkeypatch) -> None:
    tenant_id = uuid.uuid4()
    override_id = uuid.uuid4()
    _install_fake_active_adjustments_for_target(
        monkeypatch,
        [
            {
                "id": override_id,
                "value": {
                    "rate_pct": "18.0000",
                    "hsn": "8517",
                    "category": "mobile phones",
                    "gst_lookup_result_id": None,
                    "effective_from": "2026-01-01",  # well before _AS_OF
                },
            }
        ],
    )
    hsn_calls: list[str] = []
    _install_fake_resolve_hsn_gst_reference(monkeypatch, None, hsn_calls)

    result = resolve_gst_rate_for_sku(
        tenant_id,
        sku="SKU-1",
        hsn_code="8517",
        observed_rate_pct=Fraction("12"),
        as_of_date=_AS_OF,
    )

    assert isinstance(result, ResolvedGstRate)
    assert result.source_tier == "OVERRIDE"
    assert result.rate_pct == Fraction("18")


def test_no_override_at_all_behaviour_unchanged(monkeypatch) -> None:
    tenant_id = uuid.uuid4()
    _install_fake_active_adjustments_for_target(monkeypatch, [])
    hsn_calls: list[str] = []
    _install_fake_resolve_hsn_gst_reference(monkeypatch, None, hsn_calls)

    result = resolve_gst_rate_for_sku(
        tenant_id,
        sku="SKU-1",
        hsn_code="8517",
        observed_rate_pct=Fraction("12"),
        as_of_date=_AS_OF,
    )

    assert isinstance(result, ResolvedGstRate)
    assert result.source_tier == "OBSERVED"
    assert result.rate_pct == Fraction("12")


def test_tier2_never_attempted_when_hsn_code_is_none(monkeypatch) -> None:
    tenant_id = uuid.uuid4()
    _install_fake_active_adjustments_for_target(monkeypatch, [])
    hsn_calls: list[str] = []
    _install_fake_resolve_hsn_gst_reference(monkeypatch, None, hsn_calls)

    result = resolve_gst_rate_for_sku(
        tenant_id,
        sku="SKU-1",
        hsn_code=None,
        observed_rate_pct=None,
        as_of_date=_AS_OF,
    )

    assert isinstance(result, GstRateUnresolved)
    assert hsn_calls == []  # no HSN code, no lookup attempted — never a guessed code
