"""Compatibility shim: this module IS `market_signals.rate_limiter` (same module object, so classes,
exceptions and module state are shared). The code lives in packages/market-signals."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from market_signals import rate_limiter as _real

if TYPE_CHECKING:
    from market_signals.rate_limiter import *  # noqa: F403

sys.modules[__name__] = _real
