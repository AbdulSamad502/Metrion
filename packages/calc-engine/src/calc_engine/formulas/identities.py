"""identities.py — accounting identity checks the CFO planner's validator relies on (deterministic-engine.md §5.17).

The validator (cfo-query-planner.md V-ACC-2) must confirm that per-marketplace results add up to
the consolidated result *exactly*. Summing money is Brain 1's job, never the CFO package's, so
the check lives here and the validator only calls it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from fractions import Fraction


@dataclass(frozen=True, slots=True)
class AdditivityCheck:
    ok: bool
    sum_of_parts_paise: int | None  # None when a part is unavailable (cannot be summed honestly)
    whole_paise: int | None
    difference_paise: int | None  # whole - sum(parts); None when not comparable
    unavailable_parts: tuple[str, ...]


def check_additive(parts: Mapping[str, int | None], whole: int | None) -> AdditivityCheck:
    """`Σ parts == whole`, exactly (0 paise tolerance). An unavailable part, or an unavailable
    whole alongside available parts, is *not* `ok`: partial coverage must be disclosed, never
    silently summed."""
    unavailable = tuple(sorted(k for k, v in parts.items() if v is None))
    if unavailable or whole is None:
        # Not comparable: the caller must disclose which marketplace/part is missing. The only
        # "ok" case is the vacuous one (no parts and no whole at all).
        return AdditivityCheck(
            ok=not parts and whole is None,
            sum_of_parts_paise=None,
            whole_paise=whole,
            difference_paise=None,
            unavailable_parts=unavailable,
        )
    total = sum(v for v in parts.values() if v is not None)
    return AdditivityCheck(
        ok=total == whole,
        sum_of_parts_paise=total,
        whole_paise=whole,
        difference_paise=whole - total,
        unavailable_parts=(),
    )


def unexplained_share(delta: int, other: int) -> Fraction | None:
    """`|other| / |delta|` as an exact Fraction — how much of a profit movement the bridge's named
    drivers failed to explain (cfo-query-planner.md V-ACC-3 `LOW_EXPLAINABILITY`). `None` when the
    movement itself is zero (nothing to explain; not a ratio of 0/0)."""
    if delta == 0:
        return None
    return Fraction(abs(other), abs(delta))
