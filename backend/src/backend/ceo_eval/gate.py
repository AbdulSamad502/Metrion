"""Re-export: the gate now lives in `backend.ceo.composition_gate` (production). Behaviour unchanged."""

from backend.ceo.composition_gate import (  # noqa: F401
    MARKER_RE, NUMERAL_CODES, GateReport, Violation, check_composition, markers_in, numeral_violations, strip_markers,
)
