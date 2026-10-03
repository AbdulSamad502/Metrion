"""The extraction schema (spec §6.2, P6 decision 7) - CLOSED.

`cmo-vision-v1` has exactly these six observable fields. Notable features are excluded (too open-ended to
ground copy on). Weight, dimensions, price, rating, certification, category and vertical are not in the
schema and can therefore never be emitted; the parser drops anything else. Names for colour / material /
size / brand match the catalog vocabulary (`catalog.attributes`) so a trusted observation answers those
questions; `product_type` and `visible_text` are observations only.
"""

from __future__ import annotations

SCHEMA_VERSION = "cmo-vision-v1"
SUPPORTED_SCHEMA_VERSIONS = frozenset({SCHEMA_VERSION})

ATTRIBUTE_NAMES: tuple[str, ...] = ("color", "material", "size", "brand", "product_type", "visible_text")

# Technical bounds (implementation limits, not business rules): a longer reply or value is refused, never truncated.
MAX_RESPONSE_CHARS = 20_000
MAX_VALUE_CHARS = 200

# Words a model uses for "I can't tell"; recognised as an explicit UNKNOWN (linguistic data, not a fact).
UNKNOWN_SENTINELS = frozenset({"unknown", "n/a", "na", "none", "null", "not visible", "not determinable", "unclear", "not applicable"})
