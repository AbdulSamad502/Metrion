"""F2 (expense-tracker.md; engine spec §9.2, Round 6): `is_trial = true` results never reach a seller-facing read.

This is the guard test: it scans every Python source under `backend/src` and `packages/*/src` for a SQL read of
`metric_result` (`FROM metric_result` / `JOIN metric_result`) and FAILS if the statement does not filter trial rows
(`is_trial = false`, `NOT is_trial`, or the repository's `include_trial` parameter form). A new read path added without the
exclusion fails this test. An internal read that genuinely needs trial rows must carry the explicit marker
`-- trial-read-ok: <reason>` inside the statement.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
_READ = re.compile(r"\b(?:FROM|JOIN)\s+metric_result\b", re.I)
_FILTER = re.compile(r"is_trial\s*=\s*false|NOT\s+is_trial|\bis_trial\s+IS\s+FALSE|:include_trial", re.I)
_OPT_OUT = re.compile(r"--\s*trial-read-ok:", re.I)


def _sources() -> list[Path]:
    roots = [REPO / "backend" / "src", *sorted((REPO / "packages").glob("*/src"))]
    return [p for root in roots if root.exists() for p in root.rglob("*.py")]


def _statement_after(text: str, start: int) -> str:
    """From the match to the end of the SQL string literal (the next triple quote or closing quote+paren)."""
    tail = text[start : start + 900]
    for stop in ('"""', '")', '"),'):
        i = tail.find(stop, 1)
        if i != -1:
            return tail[:i]
    return tail


def test_every_metric_result_read_excludes_trial_rows():
    reads: list[str] = []
    problems: list[str] = []
    for path in _sources():
        text = path.read_text(encoding="utf-8")
        for m in _READ.finditer(text):
            stmt = _statement_after(text, m.start())
            where = f"{path.relative_to(REPO)}:{text.count(chr(10), 0, m.start()) + 1}"
            reads.append(where)
            if _OPT_OUT.search(stmt):
                continue
            if not _FILTER.search(stmt):
                problems.append(where)
    assert reads, "the scan found no metric_result reads at all — the guard itself is broken"
    assert not problems, "seller-facing metric_result reads without the is_trial exclusion: " + ", ".join(problems)


def test_the_known_read_paths_are_all_seen_by_the_scan():
    seen = {p.split(":")[0].replace("\\", "/") for p in [str(x) for x in _known()]}
    assert "packages/calc-engine/src/calc_engine/repositories/metric_result_repo.py" in seen
    assert "backend/src/backend/repositories/shared_finding_repo.py" in seen


def _known() -> list[str]:
    out = []
    for path in _sources():
        text = path.read_text(encoding="utf-8")
        if _READ.search(text):
            out.append(str(path.relative_to(REPO)))
    return out
