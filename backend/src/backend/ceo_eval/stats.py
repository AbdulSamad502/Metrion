"""Evaluation statistics for spec §6.18 (criteria approved 2026-10-10).

A metric passes only when the ONE-SIDED 95% Wilson lower bound of its rate is >= 90% on at least 100 hold-out cases. An observed rate alone is never a pass.
Pure functions, no model, no database; measurement code (floats are fine here, nothing here is money).
"""

from __future__ import annotations

import hashlib
from math import sqrt

Z_ONE_SIDED_95 = 1.6448536269514722
BAR = 0.90
MIN_HOLDOUT_CASES = 100
HOLDOUT_PERCENT = 30  # spec §6.18: 70% development / 30% locked hold-out


def wilson_lower(k: int, n: int, z: float = Z_ONE_SIDED_95) -> float | None:
    if n <= 0:
        return None
    p, d = k / n, 1 + z * z / n
    return (p + z * z / (2 * n) - z * sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / d


def wilson_upper(k: int, n: int, z: float = Z_ONE_SIDED_95) -> float | None:
    if n <= 0:
        return None
    p, d = k / n, 1 + z * z / n
    return (p + z * z / (2 * n) + z * sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / d


def split_of(case_id: str) -> str:
    """Stable 70/30 split by the case id alone, so a case never moves between development and hold-out when fixtures grow."""
    bucket = int(hashlib.sha256(case_id.encode("utf-8")).hexdigest()[:8], 16) % 100
    return "holdout" if bucket < HOLDOUT_PERCENT else "dev"


def verdict_lower(k: int, n: int) -> str:
    """PASS / FAIL for a rate that must be high (routing, recall, grounded). INSUFFICIENT_N below the hold-out floor: never a pass."""
    if n < MIN_HOLDOUT_CASES:
        return "INSUFFICIENT_N"
    lb = wilson_lower(k, n)
    return "PASS" if lb is not None and lb >= BAR else "FAIL"


def verdict_upper(k: int, n: int, ceiling: float = 1 - BAR) -> str:
    """PASS / FAIL for a rate that must be low (over-clarify <= 10%): the upper bound must stay under the ceiling."""
    if n < MIN_HOLDOUT_CASES:
        return "INSUFFICIENT_N"
    ub = wilson_upper(k, n)
    return "PASS" if ub is not None and ub <= ceiling else "FAIL"


def block(pairs: list[tuple[str, bool, str]], *, kind: str = "lower") -> dict[str, object]:
    """`pairs` = (case_id, counted, family). Returns counts per split, the hold-out Wilson bound, template-family counts and the verdict."""
    out: dict[str, object] = {}
    for name in ("dev", "holdout"):
        sel = [(c, ok, fam) for c, ok, fam in pairs if split_of(c) == name]
        out[name] = {"k": sum(ok for _, ok, _ in sel), "n": len(sel), "families": len({fam or c for c, _, fam in sel})}
    hk, hn = out["holdout"]["k"], out["holdout"]["n"]  # type: ignore[index]
    out["all"] = {"k": sum(ok for _, ok, _ in pairs), "n": len(pairs)}
    out["holdout_lower"] = wilson_lower(hk, hn)  # type: ignore[arg-type]
    out["holdout_upper"] = wilson_upper(hk, hn)  # type: ignore[arg-type]
    out["verdict"] = verdict_upper(hk, hn) if kind == "upper" else verdict_lower(hk, hn)  # type: ignore[arg-type]
    return out
