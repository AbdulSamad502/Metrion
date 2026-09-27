"""metric_result.value_fraction_numerator / value_fraction_denominator — additive columns
closing E3's real, named schema gap (docs/specs/anomaly-detection.md §6.1 `MARGIN_PCT`;
docs/specs/deterministic-engine.md §9's own `metric_result` table).

**Why this migration exists.** `compute_contribution_margin_pct`
(`calc_engine.api.compute_metric`) is the engine's first percentage-valued `MetricResult`
(`ContributionMargin% = ContributionProfit / NetRealizedRevenue * 100`, deterministic-
engine.md line 352) — its value is a `fractions.Fraction`, never `Paise`. Before this
migration, `metric_result.value_paise bigint` was the ONLY numeric column on this table
(`20260917_0001_engine_tables.py`), and `compute_batch_constrained_quantity`
(`calc_engine/api/compute_metric.py`, cfo-agent.md §6.12) had already forced an honest, but
narrower, version of this same shape mismatch by reusing `value_paise` to carry a unit COUNT
(exact, lossless — an integer fits a `bigint` exactly). A `Fraction` percentage does NOT fit
that same trick without loss or misrepresentation: scaling it into an integer (e.g. basis
points) would silently pick a rounding/precision convention `MetricResult.value_paise`'s own
"paise" unit never promised, which CLAUDE.md's "no floats, no silent misrepresentation of a
unit" discipline forbids explicitly (see this checkpoint's own report for the full reasoning).

**The fix is narrow and additive**, per this checkpoint's own instructions: two new NULLABLE
`bigint` columns storing a `Fraction`'s `numerator`/`denominator` exactly (arbitrary-precision
Python `Fraction` values reduced to lowest terms fit a `bigint` in every case this codebase
will ever encounter — a percentage or ratio, never an astronomically large numerator).
`value_paise` is untouched, remains `NULL` only when `is_available = false` for every
pre-existing paise-valued metric, and is simply also `NULL` for a Fraction-valued metric like
`CONTRIBUTION_MARGIN_PCT` (never populated with a scaled/misrepresented paise-shaped number).
Exactly one of `value_paise` or `value_fraction_numerator` is populated for any available
result — never both, never neither (enforced at the Python dataclass-construction call site in
`compute_metric.py`, not by a DB constraint, mirroring how `recognition_state`/`confidence`
are Python-enforced enums, not Postgres `CHECK` constraints, elsewhere in this same table).

Revision ID: 20260925_0006
Revises: 20260925_0005
Create Date: 2026-09-25
"""
from __future__ import annotations

from alembic import op

revision = "20260925_0006"
down_revision = "20260925_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE metric_result
          ADD COLUMN value_fraction_numerator   bigint,  -- Fraction.numerator; NULL for paise-valued/unavailable results
          ADD COLUMN value_fraction_denominator  bigint;  -- Fraction.denominator (always > 0); NULL exactly when numerator is NULL
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE metric_result
          DROP COLUMN IF EXISTS value_fraction_numerator,
          DROP COLUMN IF EXISTS value_fraction_denominator;
        """
    )
