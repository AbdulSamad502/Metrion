"""Compatibility shim: this module IS `market_signals.youtube_client` (same module object, so classes,
exceptions and module state are shared). The code lives in packages/market-signals."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from market_signals import youtube_client as _real

if TYPE_CHECKING:
    from market_signals.youtube_client import *  # noqa: F403

sys.modules[__name__] = _real
