"""resolve_recognition_state — deterministic-engine.md §5.1, AC12.

RECOGNISED | REALIZED | UNAVAILABLE. Amazon reports RECOGNISED today because its settlement
match keys are unverified against a real export (C3) — not because the report family doesn't
exist (§5.1). This is a hard rule (AC12: "Amazon figures report RECOGNISED, never REALIZED"),
so it is owned by a function here, not left to caller discretion.
"""

from __future__ import annotations

from calc_engine.types import RecognitionState

_AMAZON = "AMAZON"


def resolve_recognition_state(marketplace: str, settlement_data_present: bool) -> RecognitionState:
    """AC12: Amazon can never resolve to REALIZED, regardless of what settlement data claims
    to be present, until its settlement match keys are validated against a real export (C3)."""
    if marketplace == _AMAZON:
        return RecognitionState.RECOGNISED
    if settlement_data_present:
        return RecognitionState.REALIZED
    return RecognitionState.RECOGNISED
