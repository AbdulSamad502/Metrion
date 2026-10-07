"""Deterministic placeholder substitution — the harness's reference of spec §6.5 ("code substitutes each placeholder").

Used to prove the round trip on fixtures and to render example answers in the report. The model never sees the substituted
values, and nothing here is arithmetic: it is a lookup of an already-formatted string by token.
"""

from __future__ import annotations

import re

from backend.ceo_eval.composer import Evidence
from backend.ceo_eval.gate import MARKER_RE


def render(text: str, ev: Evidence) -> str:
    table: dict[str, str] = {f.token: f.value for f in ev.figures}
    table.update({t: msg for t, msg in ev.gaps})
    table.update({t: body for t, _, body in ev.verbatim})
    table.update({t: body for t, _, body in ev.disclaimers})
    table.update({t: f"[Run: {label}]" for t, _, label in ev.offers})
    table.update({t: f"[Add {agent}]" for t, agent in ev.attach})

    def sub(m: re.Match[str]) -> str:
        return table.get(m.group(1), m.group(0))

    return MARKER_RE.sub(sub, text)

