"""`analyze_gst_lines` — cfo-agent.md §6.6 line-level GST analysis. Pure unit tests;
`config_repo.gst_slabs_effective_on` and (for the new `resolve_unobserved_rates` path)
`manual_adjustment_repo.active_adjustments_for_target` / `config_repo.resolve_hsn_gst_reference`
are monkeypatched to fakes, never touching a real database.

Covers:
1. Pre-existing behaviour is completely unchanged when `resolve_unobserved_rates` is not passed
   (defaults `False`) — a line with no observed rate stays unresolvable exactly as before this
   checkpoint, and none of the new `resolved_rate_*`/`gst_rate_unresolved_reason` fields are
   populated.
2. When `resolve_unobserved_rates=True` and the line carries a `sku`/`hsn_code`, a tier-2
   `hsn_gst_reference` hit is used to normalize the line, and the result records which tier
   supplied the rate.
3. When `resolve_unobserved_rates=True` but nothing resolves, the line still falls through to
   the same "unresolvable" path as before, with `gst_rate_unresolved_reason` additionally naming
   the GST Applicability Lookup as the next step.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from fractions import Fraction

from backend.services import cfo_actions
from backend.services.cfo_actions import GstLineInput, analyze_gst_lines

_AS_OF = date(2026, 9, 26)


def _install_empty_slabs(monkeypatch) -> None:
    monkeypatch.setattr(cfo_actions.config_repo, "gst_slabs_effective_on", lambda tenant_id, *, as_of_date: [])


def _install_no_override(monkeypatch) -> None:
    monkeypatch.setattr(
        cfo_actions.manual_adjustment_repo,
        "active_adjustments_for_target",
        lambda tenant_id, *, target_type, target_ref, field: [],
    )


def test_resolve_unobserved_rates_default_false_is_unchanged(monkeypatch) -> None:
    tenant_id = uuid.uuid4()
    _install_empty_slabs(monkeypatch)

    lines = [
        GstLineInput(line_ref="L1", listed_paise=11800, basis="INCLUSIVE", rate_pct=None, sku="SKU-1", hsn_code="8517")
    ]
    results = analyze_gst_lines(tenant_id, lines, as_of_date=_AS_OF)

    assert len(results) == 1
    result = results[0]
    assert result.is_available is False
    assert result.unavailable_reason is not None
    assert result.resolved_rate_source_tier is None
    assert result.resolved_rate_confidence is None
    assert result.gst_rate_unresolved_reason is None


def test_resolve_unobserved_rates_true_uses_hsn_reference_tier(monkeypatch) -> None:
    tenant_id = uuid.uuid4()
    _install_empty_slabs(monkeypatch)
    _install_no_override(monkeypatch)
    monkeypatch.setattr(
        cfo_actions.config_repo,
        "resolve_hsn_gst_reference",
        lambda tenant_id, *, hsn_code, as_of_date: {
            "hsn_code": "8517",
            "description": "Mobile phones",
            "rate_pct": Decimal("18.0000"),
            "source_url": "https://example.test/8517",
            "source_title": "test",
            "retrieved_at": None,
            "effective_from": date(2025, 9, 22),
            "effective_to": None,
            "version": 1,
            "confidence": "PROVISIONAL",
        },
    )

    lines = [
        GstLineInput(
            line_ref="L1", listed_paise=11800, basis="INCLUSIVE", rate_pct=None, sku="SKU-1", hsn_code="8517"
        )
    ]
    results = analyze_gst_lines(tenant_id, lines, as_of_date=_AS_OF, resolve_unobserved_rates=True)

    assert len(results) == 1
    result = results[0]
    assert result.is_available is True
    assert result.normalized_exclusive_paise == 10000  # 11800 * 100 / 118
    assert result.resolved_rate_source_tier == "HSN_REFERENCE"
    assert result.resolved_rate_confidence == "PROVISIONAL"
    assert result.gst_rate_unresolved_reason is None


def test_resolve_unobserved_rates_true_still_unresolvable_when_no_tier_matches(monkeypatch) -> None:
    tenant_id = uuid.uuid4()
    _install_empty_slabs(monkeypatch)
    _install_no_override(monkeypatch)
    monkeypatch.setattr(
        cfo_actions.config_repo, "resolve_hsn_gst_reference", lambda tenant_id, *, hsn_code, as_of_date: None
    )

    lines = [
        GstLineInput(
            line_ref="L1", listed_paise=11800, basis="INCLUSIVE", rate_pct=None, sku="SKU-1", hsn_code="9999"
        )
    ]
    results = analyze_gst_lines(tenant_id, lines, as_of_date=_AS_OF, resolve_unobserved_rates=True)

    assert len(results) == 1
    result = results[0]
    assert result.is_available is False
    assert result.resolved_rate_source_tier is None
    assert result.gst_rate_unresolved_reason is not None
    assert "GST Applicability Lookup" in result.gst_rate_unresolved_reason


def test_observed_rate_still_used_directly_when_present(monkeypatch) -> None:
    """A line that already has an observed rate_pct never consults the composer at all —
    tier 1 precedence, unchanged from before this checkpoint."""
    tenant_id = uuid.uuid4()
    _install_empty_slabs(monkeypatch)

    def _fail_if_called(*args, **kwargs):
        raise AssertionError("active_adjustments_for_target should not be called for an already-observed rate")

    monkeypatch.setattr(cfo_actions.manual_adjustment_repo, "active_adjustments_for_target", _fail_if_called)

    lines = [
        GstLineInput(line_ref="L1", listed_paise=11800, basis="INCLUSIVE", rate_pct=Fraction("18"), sku="SKU-1")
    ]
    results = analyze_gst_lines(tenant_id, lines, as_of_date=_AS_OF, resolve_unobserved_rates=True)

    assert results[0].is_available is True
    assert results[0].normalized_exclusive_paise == 10000
    assert results[0].resolved_rate_source_tier is None
