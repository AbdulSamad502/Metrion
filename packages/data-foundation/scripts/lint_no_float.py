"""AST lint: fail if a `float` literal or float() call appears anywhere under src/data_foundation/.

Same rule as packages/calc-engine/scripts/lint_no_float.py, copied rather than imported so
each package's CI check is self-contained. This package never computes a financial total, but
every money field it touches (gross_item_amount, taxable_amount, component amounts) stays int
paise end to end — the rupees->paise conversion in adapters/base.py uses Decimal exclusively.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parent.parent / "src" / "data_foundation"


class FloatUseVisitor(ast.NodeVisitor):
    def __init__(self, file_path: Path) -> None:
        self.file_path = file_path
        self.violations: list[str] = []

    def visit_Constant(self, node: ast.Constant) -> None:  # noqa: N802 (ast visitor naming)
        if isinstance(node.value, float):
            self.violations.append(f"{self.file_path}:{node.lineno}: float literal {node.value!r}")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        if isinstance(node.func, ast.Name) and node.func.id == "float":
            self.violations.append(f"{self.file_path}:{node.lineno}: float() call")
        self.generic_visit(node)


def check_file(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    visitor = FloatUseVisitor(path)
    visitor.visit(tree)
    return visitor.violations


def main() -> int:
    violations: list[str] = []
    for path in sorted(SRC_ROOT.rglob("*.py")):
        violations.extend(check_file(path))

    if violations:
        print("lint_no_float: FAILED — float usage found under src/data_foundation/:")
        for v in violations:
            print(f"  {v}")
        return 1

    print(f"lint_no_float: OK — no float usage found under {SRC_ROOT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
