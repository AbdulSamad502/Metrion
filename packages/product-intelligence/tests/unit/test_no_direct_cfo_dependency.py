"""PI never calls CFO (docs/specs/ceo-pi-research-flow.md C2, AC5): no module in this package imports the CFO package, the backend's CFO services/routes or the
CEO. CFO results reach a research case only as references the CEO attaches."""

from __future__ import annotations

import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "product_intelligence"
FORBIDDEN = re.compile(r"^\s*(?:from|import)\s+(?:cfo\b|backend\b)", re.MULTILINE)


def test_no_pi_module_imports_cfo_or_the_backend() -> None:
    offenders = [str(p.relative_to(SRC)) for p in SRC.rglob("*.py") if FORBIDDEN.search(p.read_text(encoding="utf-8"))]
    assert offenders == []
