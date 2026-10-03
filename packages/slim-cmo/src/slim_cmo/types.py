"""Shared vocabulary — slim-cmo-agent.md §5, §6.

Every enum here mirrors a CHECK constraint in `migrations/versions/20261003_0001_cmo_tables.py`.
Migrations hard-code their literals (a migration is an immutable historical statement and
must not import mutable application code), so `tests/integration/test_schema_constraints.py`
asserts this module and the database agree value-for-value — drift fails the build rather
than surfacing as a runtime IntegrityError.
"""

from __future__ import annotations

from enum import Enum


class Marketplace(str, Enum):
    AMAZON = "AMAZON"
    FLIPKART = "FLIPKART"
    MEESHO = "MEESHO"


class OutputType(str, Enum):
    """`cmo_generation.output_type` — one row per artefact delivered (§5, §8.1.1)."""

    TITLE_SET = "TITLE_SET"
    LISTING_COPY = "LISTING_COPY"
    DESCRIPTION = "DESCRIPTION"
    BULLETS = "BULLETS"
    KEYWORDS = "KEYWORDS"
    BACKEND_TERMS = "BACKEND_TERMS"
    HASHTAGS = "HASHTAGS"
    CATALOG_ANSWER = "CATALOG_ANSWER"
    TREND_REPORT = "TREND_REPORT"


# Artefacts that are written for exactly one marketplace and must therefore carry one (§6.4).
MARKETPLACE_SCOPED_OUTPUT_TYPES: frozenset[OutputType] = frozenset(
    {
        OutputType.TITLE_SET,
        OutputType.LISTING_COPY,
        OutputType.DESCRIPTION,
        OutputType.BULLETS,
        OutputType.KEYWORDS,
        OutputType.BACKEND_TERMS,
    }
)

# Artefacts generated against a seller-approved (or seller-supplied) title (§6.4 rule 4, AC10).
GROUNDED_OUTPUT_TYPES: frozenset[OutputType] = frozenset(
    {
        OutputType.LISTING_COPY,
        OutputType.DESCRIPTION,
        OutputType.BULLETS,
        OutputType.KEYWORDS,
        OutputType.BACKEND_TERMS,
    }
)

# Artefacts validated against a `format_constraint` row, which must therefore be cited (AC5).
CONSTRAINT_BOUND_OUTPUT_TYPES: frozenset[OutputType] = frozenset(
    {OutputType.TITLE_SET} | GROUNDED_OUTPUT_TYPES
)


class InputMode(str, Enum):
    INDEPENDENT = "INDEPENDENT"
    CEO_BROKERED_CI = "CEO_BROKERED_CI"


class GenerationStatus(str, Enum):
    """Only `COMPLETE` consumes a unit (§8.3)."""

    COMPLETE = "COMPLETE"
    FAILED = "FAILED"


class GroundingBasis(str, Enum):
    APPROVED_TITLE = "APPROVED_TITLE"
    SELLER_SUPPLIED_TITLE = "SELLER_SUPPLIED_TITLE"


class AttributeBasis(str, Enum):
    """§6.5 — the five labels every catalog attribute carries. The vision model may only ever
    emit `IMAGE_OBSERVED` or `UNKNOWN`; the database enforces that on `product_image_analysis`."""

    SELLER_PROVIDED = "SELLER_PROVIDED"
    IMAGE_OBSERVED = "IMAGE_OBSERVED"
    SOURCE_DERIVED = "SOURCE_DERIVED"
    ESTIMATED = "ESTIMATED"
    UNKNOWN = "UNKNOWN"


class TrustState(str, Enum):
    """§6.2.1 — image-derived attributes are `UNVERIFIED_HINT` until a recorded evaluation
    passes for the exact (provider, model, schema_version)."""

    UNVERIFIED_HINT = "UNVERIFIED_HINT"
    EVAL_PASSED = "EVAL_PASSED"


class ImageAnalysisState(str, Enum):
    COMPLETE = "COMPLETE"
    DEGRADED = "DEGRADED"
    FAILED = "FAILED"


class ImageAssetStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PURGED = "PURGED"


class SellerFactType(str, Enum):
    CATEGORY = "CATEGORY"
    BRAND = "BRAND"
    ATTRIBUTE = "ATTRIBUTE"
    NICHE = "NICHE"
    TARGET_PRICE = "TARGET_PRICE"
    FREE_TEXT = "FREE_TEXT"


class NicheTermOrigin(str, Enum):
    SELLER_STATED = "SELLER_STATED"
    CATALOG_DERIVED = "CATALOG_DERIVED"
    SELLER_FACT = "SELLER_FACT"


class NicheTermStatus(str, Enum):
    SUGGESTED = "SUGGESTED"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"


class ConstraintRowKind(str, Enum):
    """C13 — production reads `VERIFIED` rows only; `TEST_FIXTURE` rows exist for tests."""

    VERIFIED = "VERIFIED"
    TEST_FIXTURE = "TEST_FIXTURE"


class CountRule(str, Enum):
    """How a marketplace counts characters in a length limit (verified per marketplace, spec
    §6.3). `UTF16_CODE_UNITS` is the conservative reading (an emoji counts 2); `CODE_POINTS`
    counts each Unicode code point once. Grapheme-cluster counting is not supported until a
    marketplace is verified to need it."""

    UTF16_CODE_UNITS = "UTF16_CODE_UNITS"
    CODE_POINTS = "CODE_POINTS"


class TrendSection(str, Enum):
    """The five *researched* sections of a trend report (§6.8.2). Sections 6
    (interpretation) and 7 (evidence) are derived, not researched, and are stored in their
    own columns."""

    NICHE = "NICHE"
    MARKET_NEWS = "MARKET_NEWS"
    REPORTED_TACTICS = "REPORTED_TACTICS"
    NEW_PRODUCTS_BUZZ = "NEW_PRODUCTS_BUZZ"
    ADJACENT = "ADJACENT"
