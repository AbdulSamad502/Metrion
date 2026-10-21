"""Explicit data-completeness states (deterministic-engine.md §5.17.1, cfo-unified-financials.md U10).

Every Phase 2a result carries one of these. Only `COMPLETE` may be presented as a confirmed actual; a figure that rests on
excluded rows, unconfirmed seller input, or an estimate must say so, and a missing input is `UNAVAILABLE`, never zero.
"""

from __future__ import annotations

from enum import Enum


class Completeness(str, Enum):
    COMPLETE = "COMPLETE"  # every input present and confirmed
    PARTIAL = "PARTIAL"  # some inputs were excluded and are counted/listed
    PROVISIONAL = "PROVISIONAL"  # rests on unconfirmed seller input (e.g. an unclassified expense)
    ESTIMATED = "ESTIMATED"  # an estimate, never a measured actual
    UNAVAILABLE = "UNAVAILABLE"  # a required input is missing

    @property
    def is_confirmed_actual(self) -> bool:
        return self is Completeness.COMPLETE
