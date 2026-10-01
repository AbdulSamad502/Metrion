"""product_candidate feasibility columns — closes a real gap found during the 2026-10-01
quality pass: `calc_engine.api.estimate_product_feasibility` was built and unit-tested
(PI build plan §1) but had no caller anywhere in PI, so a discovered candidate never carried
any feasibility/profitability figure at all — the exact thing a seller needs to decide
whether a candidate is worth pursuing.

Denormalized snapshot columns, not a cross-package foreign key — `product_feasibility_estimate`
lives in calc-engine's own Postgres schema/alembic history (`20260929_0012_product_feasibility_estimate.py`),
a separate migration chain from this package's. `feasibility_estimate_ref` still carries full
provenance back to that row (the project's "every displayed figure cites an estimate_ref"
hard rule) — it is just not an enforced FK, the same posture `metric_result`/`engine_result_ref`
references already take everywhere else in this codebase when crossing a package boundary.

Revision ID: 20261001_0001
Revises: 20260930_0001
Create Date: 2026-10-01
"""
from __future__ import annotations

from alembic import op

revision = "20261001_0001"
down_revision = "20260930_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE product_candidate
          ADD COLUMN feasibility_status text not null default 'UNAVAILABLE',
          -- COMPUTED | UNAVAILABLE — UNAVAILABLE until a feasibility estimate is actually
          -- computed for this candidate (e.g. no target price band on the niche_brief, or
          -- fee resolution failed outright); never silently absent, matches this package's
          -- own confidence-vocabulary discipline elsewhere.
          ADD COLUMN feasibility_estimate_ref uuid,
          -- calc_engine.product_feasibility_estimate.id (estimate_ref) — see module
          -- docstring for why this is a plain UUID, not an enforced cross-package FK.
          ADD COLUMN feasibility_low_paise bigint,
          ADD COLUMN feasibility_high_paise bigint,
          ADD COLUMN feasibility_cogs_basis text,
          -- STATED | UNKNOWN (deterministic-engine.md §5.13.2 rule 6) — NULL only when
          -- feasibility_status = 'UNAVAILABLE'.
          ADD COLUMN feasibility_assumptions jsonb,
          ADD COLUMN feasibility_unavailable_reason text;
        ALTER TABLE product_candidate
          ADD CONSTRAINT product_candidate_feasibility_status_check
          CHECK (feasibility_status IN ('COMPUTED', 'UNAVAILABLE'));
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE product_candidate
          DROP CONSTRAINT IF EXISTS product_candidate_feasibility_status_check,
          DROP COLUMN IF EXISTS feasibility_status,
          DROP COLUMN IF EXISTS feasibility_estimate_ref,
          DROP COLUMN IF EXISTS feasibility_low_paise,
          DROP COLUMN IF EXISTS feasibility_high_paise,
          DROP COLUMN IF EXISTS feasibility_cogs_basis,
          DROP COLUMN IF EXISTS feasibility_assumptions,
          DROP COLUMN IF EXISTS feasibility_unavailable_reason;
        """
    )
