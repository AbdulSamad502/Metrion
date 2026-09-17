"""resolve_document_date() fallback chain — deterministic-engine.md §6, confirmed decision.

Named per the approved plan so this is the one place to fix if the confirmed fallback
ordering (invoice_date -> dispatch_date -> order_date) is ever revisited.
"""

from __future__ import annotations

from datetime import date

import pytest

from calc_engine.dates import resolve_document_date


def test_document_date_assumption_pending_confirmation():
    invoice, dispatch, order = date(2026, 8, 1), date(2026, 7, 28), date(2026, 7, 25)

    assert resolve_document_date(invoice, dispatch, order) == invoice
    assert resolve_document_date(None, dispatch, order) == dispatch
    assert resolve_document_date(None, None, order) == order


def test_all_none_raises():
    with pytest.raises(ValueError):
        resolve_document_date(None, None, None)
