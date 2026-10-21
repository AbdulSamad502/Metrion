"""profit_bridge.py — why Contribution Profit moved between two periods (deterministic-engine.md §5.17).

`ΔCP = CP_B − CP_A = ΔNRR − ΔCOGS − ΔFees − ΔLogistics − ΔAds − ΔReturnRTOLoss − ΔOtherAllocated`

Pure integer arithmetic over already-computed component figures (paise). No I/O, no clock, no
LLM. Each driver is the signed *effect on Contribution Profit* of that component's movement, so
the drivers add up to the change in Contribution Profit by construction; any remainder is
returned as `other` and must be zero — a nonzero `other` means a component feeding
Contribution Profit is missing from the bridge, which is a defect, not something to hide.

A component that is unavailable in either period makes the whole bridge `Unavailable` (a
missing input is never zero): a driver we cannot measure is not a driver of zero.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from calc_engine.types import Unavailable

# component code -> sign of its effect on Contribution Profit (engine §5.8). Fixed, not configurable:
# these are the definition of Contribution Profit, not a tunable coefficient.
BRIDGE_COMPONENTS: tuple[tuple[str, int], ...] = (
    ("NET_REALIZED_REVENUE", 1),
    ("COGS", -1),
    ("MARKETPLACE_FEES", -1),
    ("SHIPPING_LOGISTICS", -1),
    ("ADVERTISING_COSTS", -1),
    ("RETURN_RTO_LOSSES", -1),
    ("OTHER_ALLOCATED_COSTS", -1),
)


@dataclass(frozen=True, slots=True)
class BridgeDriver:
    component_code: str
    effect_paise: int  # signed effect on Contribution Profit of this component's movement A -> B


@dataclass(frozen=True, slots=True)
class ProfitBridge:
    delta_paise: int  # CP_B - CP_A
    drivers: tuple[BridgeDriver, ...]  # ranked by |effect| descending, ties by component_code
    other_paise: int  # delta - sum(drivers); must be 0 for a complete bridge
    reconciles: bool  # other_paise == 0


def profit_bridge(
    *,
    cp_a: int | None,
    cp_b: int | None,
    components_a: Mapping[str, int | None],
    components_b: Mapping[str, int | None],
) -> ProfitBridge | Unavailable:
    """Bridge from period A (earlier) to period B (later). Component values are the cost/revenue
    *magnitudes* as the engine reports them (costs positive); this function applies the signs."""
    if cp_a is None or cp_b is None:
        side = "period A" if cp_a is None else "period B"
        return Unavailable(reason=f"Contribution Profit is unavailable for {side}", missing_inputs=("CONTRIBUTION_PROFIT",))

    missing: list[str] = []
    effects: list[BridgeDriver] = []
    for code, sign in BRIDGE_COMPONENTS:
        a = components_a.get(code)
        b = components_b.get(code)
        if a is None or b is None:
            missing.append(code)
            continue
        effects.append(BridgeDriver(component_code=code, effect_paise=sign * (b - a)))
    if missing:
        return Unavailable(
            reason="components unavailable in at least one period: " + ", ".join(missing),
            missing_inputs=tuple(missing),
        )

    delta = cp_b - cp_a
    explained = sum(d.effect_paise for d in effects)
    other = delta - explained
    ranked = tuple(sorted(effects, key=lambda d: (-abs(d.effect_paise), d.component_code)))
    return ProfitBridge(delta_paise=delta, drivers=ranked, other_paise=other, reconciles=other == 0)
