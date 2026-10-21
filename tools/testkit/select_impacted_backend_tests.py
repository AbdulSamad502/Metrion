"""Risk-based selection of backend tests for a CFO 2.0 phase gate (reproducible, rule-based — not a judgement call).

WHY: the backend suite is ~7,500 database-heavy tests and 69% are CEO conversation tests. Running all of it after every phase costs hours and mostly
re-tests code a CFO change cannot reach. The COMPLETE suite stays the mandatory gate before any merge or push (`--all`); this tool picks what must run
at a phase gate, by explicit rules, so the choice can be reviewed and repeated.

Two kinds of test, treated differently because their cost differs by orders of magnitude:
  U  UNIT tests (`backend/tests/unit`, ~5,000, no database, seconds): ALWAYS ALL run. Cheap, so there is nothing to save by guessing.
  I  INTEGRATION tests (`backend/tests/integration`, ~2,450, real Postgres, the slow part): a file is SELECTED when any of these holds
     (each file's reasons are printed):
       R1 DEPENDENCY   its source REFERENCES code the CFO 2.0 work touches, by an actual dependency, not a word: the CFO routes or services
                       (`api.v1 import cfo`, `/api/v1/cfo`, `cfo_actions`, `cfo_ingestion`, `cfo_imports`), the CEO's CFO dispatch (`dispatch_cfo`),
                       the data and engine packages (`data_foundation`, `calc_engine`, `from cfo`), or a table CFO 2.0 writes or migrates
                       (`report_file`, `sales_line`, `settlement_line`, `manual_adjustment`, `ingestion_job`, `column_mapping`,
                       `cfo_read_model_version`, `expense_class_map`).
       R2 CROSS-CUTTING its file name is an infrastructure surface any change can disturb: auth, permission, privilege, least privilege, RLS,
                       isolation, entitlement, request limits / body, frontend origin, config / env, migration, health, every_route (the guards that
                       cover every route, including new ones), tenant, clerk, accounting, engine.
       R3 CHANGED      the test file itself changed against the base branch.
     Everything else is EXCLUDED with the reason "no dependency on CFO code or shared surfaces". Nothing is silently dropped: the report lists
     every excluded file and its test count.

USAGE
    python tools/testkit/select_impacted_backend_tests.py --report <out.md> [--base main] [--list <files.txt>]
    python tools/testkit/select_impacted_backend_tests.py --all      # prints every backend test file (the full-suite gate)
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TESTS = REPO / "backend" / "tests"

DEPENDENCY = re.compile(
    r"api\.v1 import cfo|api\.v1\.cfo|/api/v1/cfo|cfo_actions|cfo_ingestion|cfo_imports|cfo_mapping|dispatch_cfo|from cfo\b|import cfo\b|data_foundation|calc_engine"
    r"|report_file|sales_line|settlement_line|manual_adjustment|ingestion_job|column_mapping|cfo_read_model_version|expense_class_map",
    re.IGNORECASE,
)
CROSS_CUTTING = re.compile(
    r"auth|permission|privilege|least|rls|isolation|entitle|request_limit|request_body|frontend_origin|config|env|migration|health|every_route|tenant|clerk|accounting|engine",
    re.IGNORECASE,
)


def test_files() -> list[Path]:
    return sorted(p for p in TESTS.rglob("test_*.py"))


def changed_test_files(base: str) -> set[str]:
    try:
        out = subprocess.check_output(["git", "diff", "--name-only", f"{base}...HEAD", "--", "backend/tests"], cwd=REPO, text=True, stderr=subprocess.DEVNULL)
    except Exception:  # noqa: BLE001
        return set()
    return {Path(line).as_posix() for line in out.splitlines() if line.strip()}


def count_tests(path: Path) -> int:
    """A cheap, collection-free count: top-level and class test functions (parametrisation is not expanded)."""
    return len(re.findall(r"^\s*(?:async\s+)?def test_", path.read_text(encoding="utf-8", errors="replace"), re.MULTILINE))


def select(base: str) -> tuple[list[tuple[Path, list[str]]], list[Path]]:
    changed = changed_test_files(base)
    chosen: list[tuple[Path, list[str]]] = []
    excluded: list[Path] = []
    for f in test_files():
        rel = f.relative_to(REPO).as_posix()
        reasons: list[str] = []
        text = f.read_text(encoding="utf-8", errors="replace")
        if "/unit/" in f.as_posix():
            reasons.append("U unit test (always runs)")
        hit = DEPENDENCY.search(text)
        if hit and "/integration/" in f.as_posix():
            reasons.append(f"R1 dependency ('{hit.group(0).lower()}')")
        if CROSS_CUTTING.search(f.name) and "/integration/" in f.as_posix():
            reasons.append("R2 cross-cutting")
        if rel in changed:
            reasons.append("R3 changed in this branch")
        (chosen.append((f, reasons)) if reasons else excluded.append(f))
    return chosen, excluded


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default="main")
    ap.add_argument("--report", type=Path)
    ap.add_argument("--list", type=Path, help="write the selected file paths, one per line, for pytest")
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()

    if args.all:
        for f in test_files():
            print(f.relative_to(REPO / "backend").as_posix())
        return 0

    chosen, excluded = select(args.base)
    if args.list:
        args.list.write_text("\n".join(f.relative_to(REPO / "backend").as_posix() for f, _ in chosen) + "\n", encoding="utf-8")
    sel_n = sum(count_tests(f) for f, _ in chosen)
    exc_n = sum(count_tests(f) for f in excluded)
    print(f"selected {len(chosen)} files (~{sel_n} test functions) · excluded {len(excluded)} files (~{exc_n}) · parametrisation not expanded")
    if args.report:
        L = ["# Backend test selection for the CFO 2.0 phase gate", "", "Generated by `tools/testkit/select_impacted_backend_tests.py` — rules R1-R3 are in that file's docstring. "
             "The complete suite remains the mandatory gate before any merge or push.", "",
             f"- Selected: **{len(chosen)} files, ~{sel_n} test functions** · Excluded: **{len(excluded)} files, ~{exc_n}** (function counts do not expand parametrisation).", "",
             "## Selected", "", "| File | Test functions | Why |", "|---|---:|---|"]
        for f, reasons in chosen:
            L.append(f"| `{f.relative_to(REPO / 'backend').as_posix()}` | {count_tests(f)} | {'; '.join(reasons)} |")
        L += ["", "## Excluded (no CFO / shared-surface reference)", "", "| File | Test functions |", "|---|---:|"]
        for f in excluded:
            L.append(f"| `{f.relative_to(REPO / 'backend').as_posix()}` | {count_tests(f)} |")
        args.report.write_text("\n".join(L) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
