"""The Profit Calculator form's fee fields (`frontend/lib/pnlFeeFields.ts`) must be exactly the fee fields the engine has (`calc_engine.formulas.pnl_scenario.fields`).

Both hold labels and shapes only, never a rate (calculator.md N4). If they drift, the form would offer a fee the API rejects or hide one the engine reports as
missing; this fails first. Compared: id, label, unit, what a fee is charged on, whether it is in Quick mode, which Amazon fulfilment methods show it and whether it can have price bands. The form's help text is the
frontend's own."""

from __future__ import annotations

import dataclasses
import re
from pathlib import Path

from calc_engine.formulas.pnl_scenario import MARKETPLACE_FIELDS

TS = Path(__file__).resolve().parents[3] / "frontend" / "lib" / "pnlFeeFields.ts"
_ROW = re.compile(
    r'\{ id: "(?P<id>\w+)", label: "(?P<label>[^"]+)", unit: "(?P<unit>\w+)", chargedOn: "(?P<charged>\w+)", quick: (?P<quick>true|false), fulfilment: (?P<ful>null|\[[^\]]*\])'
)


def _frontend() -> dict[str, list[tuple]]:
    text = TS.read_text(encoding="utf-8")
    out: dict[str, list[tuple]] = {}
    current = None
    for line in text.splitlines():
        head = re.match(r"\s{2}(amazon|flipkart|meesho): \[", line)
        if head:
            current = head.group(1)
            out[current] = []
            continue
        m = _ROW.search(line)
        if m and current:
            ful = None if m["ful"] == "null" else tuple(re.findall(r'"(\w+)"', m["ful"]))
            tier = re.search(r"tierable: (true|false) \}", line)
            out[current].append((m["id"], m["label"], m["unit"], m["charged"], m["quick"] == "true", ful, bool(tier) and tier.group(1) == "true"))
    return out


def test_the_form_offers_exactly_the_engines_fee_fields() -> None:
    fe = _frontend()
    assert set(fe) == set(MARKETPLACE_FIELDS)
    for marketplace, defs in MARKETPLACE_FIELDS.items():
        engine = [(d.id, d.label, d.unit, d.charged_on, d.quick, d.amazon_fulfilment, d.tierable) for d in defs]
        assert fe[marketplace] == engine, marketplace


def test_no_rate_or_amount_is_stored_in_either_place() -> None:
    text = TS.read_text(encoding="utf-8")
    assert not re.search(r"(rate|default|amount|bps|paise)\s*:\s*\d", text, re.I)
    for defs in MARKETPLACE_FIELDS.values():
        for d in defs:
            for f in dataclasses.fields(d):
                value = getattr(d, f.name)
                assert not (isinstance(value, (int, float)) and not isinstance(value, bool)), f"{d.id}.{f.name} holds a number"
