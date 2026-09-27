"""AST lint (AC3-style, adapted from `packages/calc-engine/scripts/lint_no_float.py`): no
`float` literal or `float()` call appears anywhere under `packages/cfo/src/cfo/` in a
money-adjacent path. Money in this codebase uses `Paise` (int) and `Fraction` exclusively —
float must never appear in any calculation path.

Unlike `calc_engine` (a pure money-calculation package with zero legitimate float use, so its
own lint has no allowlist at all), CFO also contains ordinary infrastructure plumbing — e.g.
`OllamaLlmProvider.timeout_seconds`, an HTTP client timeout in seconds, never a money value,
never touched by any calculation. A narrow, explicit, line-scoped allowlist below is the
honest way to keep this lint meaningful rather than either failing on non-money config or
silently widening the ban's scope past what CLAUDE.md actually requires ("No floats in any
calculation path"). Every entry must name exactly why it is not money-adjacent.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC_ROOT = Path(__file__).resolve().parents[2] / "src" / "cfo"

# (relative path, line number) -> reason it is not money-adjacent. Adding an entry here must
# be accompanied by a one-line justification; this is not a general escape hatch.
_ALLOWED_NON_MONEY_FLOATS: dict[tuple[str, int], str] = {
    ("reasoning/ollama_provider.py", 37): "OllamaLlmProvider.timeout_seconds — an HTTP client timeout, never a money value",
}


class _FloatUseVisitor(ast.NodeVisitor):
    def __init__(self, file_path: Path) -> None:
        self.file_path = file_path
        self.violations: list[str] = []

    def visit_Constant(self, node: ast.Constant) -> None:  # noqa: N802
        if isinstance(node.value, float):
            self.violations.append(f"{self.file_path}:{node.lineno}: float literal {node.value!r}")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        if isinstance(node.func, ast.Name) and node.func.id == "float":
            self.violations.append(f"{self.file_path}:{node.lineno}: float() call")
        self.generic_visit(node)


def _check_file(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    visitor = _FloatUseVisitor(path)
    visitor.visit(tree)
    return visitor.violations


def _all_cfo_src_files() -> list[Path]:
    return sorted(SRC_ROOT.rglob("*.py")) if SRC_ROOT.exists() else []


def test_src_root_exists_and_is_non_empty() -> None:
    assert SRC_ROOT.exists(), f"expected {SRC_ROOT} to exist"
    assert len(_all_cfo_src_files()) >= 5


@pytest.mark.parametrize("path", _all_cfo_src_files(), ids=lambda p: str(p.relative_to(SRC_ROOT)))
def test_no_float_usage(path: Path) -> None:
    rel = path.relative_to(SRC_ROOT).as_posix()
    violations = _check_file(path)
    unallowed = [
        v for v in violations
        if not any(
            f":{line}:" in v and rel == allowed_rel
            for (allowed_rel, line) in _ALLOWED_NON_MONEY_FLOATS
        )
    ]
    assert unallowed == [], "\n".join(unallowed)


def test_allowlist_entries_are_still_accurate() -> None:
    """Guardrail: if a float literal moves lines or is removed, the allowlist above must be
    kept in sync rather than silently becoming a dead/no-op entry."""
    for (rel_path, line), reason in _ALLOWED_NON_MONEY_FLOATS.items():
        path = SRC_ROOT / rel_path
        assert path.exists(), f"allowlisted file {rel_path} no longer exists ({reason})"
        violations = _check_file(path)
        assert any(f":{line}:" in v for v in violations), (
            f"expected a float violation at {rel_path}:{line} ({reason}) — allowlist entry is stale"
        )
