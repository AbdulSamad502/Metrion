"""Shared mean/variance/bounded-precision-square-root helpers used by z_score.py and
period_over_period_delta.py — docs/specs/anomaly-detection.md §6.3.

`Fraction` throughout except for the one irrational intermediate (a standard deviation),
which is computed via `Decimal` at a fixed, documented precision (B9). `DECIMAL_SQRT_PRECISION
= 28` significant digits is the exact value the spec suggests ("e.g. 28 significant digits",
§6.3) — chosen here as the concrete, documented constant. No `float` appears anywhere in this
module.
"""

from __future__ import annotations

from decimal import Decimal, localcontext
from fractions import Fraction
from typing import Sequence

# Bounded precision for the standard deviation's square root — the ONE irrational
# intermediate either method touches (§6.3, B9). Fixed and documented, never float.
DECIMAL_SQRT_PRECISION = 28


def _fraction_to_decimal(value: Fraction, precision: int) -> Decimal:
    with localcontext() as ctx:
        ctx.prec = precision
        return Decimal(value.numerator) / Decimal(value.denominator)


def mean_and_sample_variance(baseline: Sequence[Fraction]) -> tuple[Fraction, Fraction]:
    """`mean = sum(baseline) / k`; `variance = sum((x - mean)^2) / (k - 1)` — sample
    variance, exact `Fraction` arithmetic throughout. Callers are responsible for ensuring
    `k >= 2` (both methods' minimum-series-length floors guarantee this; see §6.2)."""
    k = len(baseline)
    total = sum(baseline, Fraction(0))
    mean = total / k
    variance = sum(((x - mean) ** 2 for x in baseline), Fraction(0)) / (k - 1)
    return mean, variance


def decimal_stdev(variance: Fraction, precision: int = DECIMAL_SQRT_PRECISION) -> Decimal:
    """`sqrt(variance)` via bounded-precision `Decimal` (§6.3) — never `float`. Callers must
    have already confirmed `variance != 0` (the zero-variance guard, §6.3/AC3); this function
    does not itself guard against it, since `Decimal(0).sqrt()` is well-defined (`0`) but a
    zero-variance baseline is a structurally different, named outcome (`AnomalyZeroVariance`)
    the caller returns instead of ever reaching this call."""
    with localcontext() as ctx:
        ctx.prec = precision
        return _fraction_to_decimal(variance, precision).sqrt()


def z_score_value(point: Fraction, mean: Fraction, stdev: Decimal, precision: int = DECIMAL_SQRT_PRECISION) -> Fraction:
    """`(point - mean) / stdev`, computed within the same bounded `Decimal` precision as
    `stdev` itself (the division inherits the sqrt step's bound — the numerator is exact but
    the denominator is not), then converted back to an exact `Fraction` (a finite decimal
    converts to `Fraction` losslessly, so no further precision is lost at this step)."""
    with localcontext() as ctx:
        ctx.prec = precision
        numerator = _fraction_to_decimal(point - mean, precision)
        z = numerator / stdev
    return Fraction(z)
