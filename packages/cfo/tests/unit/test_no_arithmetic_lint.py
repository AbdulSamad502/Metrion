"""AST lint (AC1/T44-style): no arithmetic operator (`+ - * /` and their augmented forms) is
ever applied to a `Paise`/`paise`-named variable anywhere in CFO's own code — `packages/cfo/
src/cfo/`, plus the new backend integration files (`cfo_actions.py`, `api/v1/cfo.py`,
`ceo_hub.py`'s CFO dispatch functions). Money arithmetic lives exclusively in
`calc_engine` (CLAUDE.md hard rule) — this module never re-derives or recomputes a figure.

Detection heuristic: an `ast.BinOp`/`ast.AugAssign` with `+ - * /` (or `//`, `%`) where
either operand is a Name/Attribute whose identifier contains "paise" (case-insensitive) —
the same convention `Paise`-typed variables use throughout this codebase
(`amount_paise`, `value_paise`, `cogs_per_unit` -> paise int, etc).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
CFO_SRC = REPO_ROOT / "packages" / "cfo" / "src" / "cfo"
BACKEND_FILES = [
    REPO_ROOT / "backend" / "src" / "backend" / "services" / "cfo_actions.py",
    REPO_ROOT / "backend" / "src" / "backend" / "api" / "v1" / "cfo.py",
    REPO_ROOT / "backend" / "src" / "backend" / "agents" / "ceo_hub.py",
]

_ARITH_OPS = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow)


def _is_paise_named(node: ast.expr) -> bool:
    if isinstance(node, ast.Name):
        return "paise" in node.id.lower()
    if isinstance(node, ast.Attribute):
        return "paise" in node.attr.lower()
    return False


class _ArithmeticOnPaiseVisitor(ast.NodeVisitor):
    def __init__(self, file_path: Path) -> None:
        self.file_path = file_path
        self.violations: list[str] = []

    def visit_BinOp(self, node: ast.BinOp) -> None:  # noqa: N802
        if isinstance(node.op, _ARITH_OPS) and (_is_paise_named(node.left) or _is_paise_named(node.right)):
            self.violations.append(
                f"{self.file_path}:{node.lineno}: arithmetic on a paise-named operand ({ast.dump(node.op)})"
            )
        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:  # noqa: N802
        if isinstance(node.op, _ARITH_OPS) and _is_paise_named(node.target):
            self.violations.append(f"{self.file_path}:{node.lineno}: augmented arithmetic assignment on a paise-named target")
        self.generic_visit(node)


def _check_file(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    visitor = _ArithmeticOnPaiseVisitor(path)
    visitor.visit(tree)
    return visitor.violations


def _all_target_files() -> list[Path]:
    files = sorted(CFO_SRC.rglob("*.py")) if CFO_SRC.exists() else []
    files.extend(p for p in BACKEND_FILES if p.exists())
    return files


@pytest.mark.parametrize("path", _all_target_files(), ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_no_arithmetic_on_paise_named_variable(path: Path) -> None:
    violations = _check_file(path)
    assert violations == [], "\n".join(violations)


def test_target_file_set_is_non_empty() -> None:
    """Guardrail: if the glob/paths above stop matching anything (e.g. a rename), this test
    fails loudly instead of the whole lint silently checking zero files."""
    assert len(_all_target_files()) >= 5
