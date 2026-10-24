"""The Profit & Finance forms offer a marketplace choice (`frontend/components/cfo/primitives.tsx`, `MARKETPLACE_OPTIONS`) instead of a free-text box.

That choice must be exactly the marketplaces the system supports, or the form would hide a valid value or offer one the engine refuses. Three independent sources must agree:
  * the data-foundation adapters: every stored `sales_line` / `settlement_line` row takes its marketplace from the adapter that parsed it;
  * the reconciliation engine's join-key table: `reconcile()` and `cash_reconciliation()` raise for any other marketplace (and for a different case, e.g. "meesho");
  * the frontend options themselves, with the exact upper-case ids the routes already received.
Test-only: it changes no behaviour."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from calc_engine.api import cash_reconciliation as cash_module
from calc_engine.api import reconcile as reconcile_module
from data_foundation.adapters.registry import ADAPTER_REGISTRY

TS = Path(__file__).resolve().parents[3] / "frontend" / "components" / "cfo" / "primitives.tsx"


def _frontend_options() -> list[tuple[str, str]]:
    text = TS.read_text(encoding="utf-8")
    block = re.search(r"export const MARKETPLACE_OPTIONS = \[(.*?)\];", text, re.S)
    assert block, "MARKETPLACE_OPTIONS not found in primitives.tsx"
    return re.findall(r'\{ value: "([A-Z]+)", label: "([^"]+)" \}', block.group(1))


def test_the_form_choices_are_exactly_the_marketplaces_the_adapters_store():
    stored = {a.marketplace for a in ADAPTER_REGISTRY.values()}
    assert {value for value, _ in _frontend_options()} == stored == {"AMAZON", "FLIPKART", "MEESHO"}


def test_the_form_choices_are_exactly_the_marketplaces_the_engine_can_reconcile():
    ids = {value for value, _ in _frontend_options()}
    assert ids == set(reconcile_module._JOIN_KEY_FIELD)
    assert ids == set(cash_module._JOIN_KEY_FIELD)


def test_the_choices_are_sent_as_the_same_upper_case_ids_with_plain_labels():
    assert _frontend_options() == [("AMAZON", "Amazon"), ("FLIPKART", "Flipkart"), ("MEESHO", "Meesho")]


@pytest.mark.parametrize("module", [reconcile_module, cash_module])
@pytest.mark.parametrize("value", ["meesho", "Meesho", "MYNTRA", ""])
def test_the_engine_refuses_anything_else_so_the_old_free_text_box_could_only_produce_errors(module, value):
    """What the free-text box allowed that the dropdown now prevents: a typo, a different case or an unknown name reaches the engine and is refused."""
    import datetime
    import inspect
    import uuid

    fn = module.reconcile if module is reconcile_module else module.cash_reconciliation
    kw = {p: None for p in inspect.signature(fn).parameters}
    kw.update(marketplace=value, tenant_id=uuid.uuid4(), period_start=datetime.date(2026, 9, 1), period_end=datetime.date(2026, 9, 30),
              as_of_date=datetime.date(2026, 9, 30), computed_at=datetime.datetime.now(datetime.timezone.utc))
    with pytest.raises(ValueError, match="no join-key mapping"):
        fn(**kw)
