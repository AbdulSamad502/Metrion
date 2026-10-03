"""The no-float lint (CLAUDE.md: no floats in any calculation path) — prove it actually catches
what it claims to, and that the package itself is clean."""

from __future__ import annotations

import importlib.util
import pathlib

import pytest

_SCRIPT = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "lint_no_float.py"
_spec = importlib.util.spec_from_file_location("slim_cmo_lint_no_float", _SCRIPT)
assert _spec and _spec.loader
lint = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lint)


@pytest.mark.parametrize(
    "source",
    ["x = 1.5\n", "x = float('2')\n", "def f():\n    return 0.0\n", "y = [1, 2.25]\n"],
)
def test_lint_flags_float_literals_and_calls(tmp_path, source):
    path = tmp_path / "bad.py"
    path.write_text(source, encoding="utf-8")
    assert lint.check_file(path), f"expected a violation for {source!r}"


@pytest.mark.parametrize("source", ["x = 1\n", "from decimal import Decimal\nx = Decimal('1.5')\n", "x = 3 // 2\n"])
def test_lint_accepts_integer_and_decimal_code(tmp_path, source):
    path = tmp_path / "ok.py"
    path.write_text(source, encoding="utf-8")
    assert lint.check_file(path) == []


def test_slim_cmo_source_contains_no_floats():
    violations = []
    for path in sorted(lint.SRC_ROOT.rglob("*.py")):
        violations.extend(lint.check_file(path))
    assert violations == []
