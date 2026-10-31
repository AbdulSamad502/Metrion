"""CMO 3.0 M6 (N-05t): an explicit seller approval of a title the seller TYPED, recorded without a title-set generation.

`cmo_title_approval.generation_id` was NOT NULL because every approval used to be a choice from (or an edit of) a title set the CMO generated. A typed title has no such set, and a synthetic one
would be an invented generation. The smallest safe change:

* `generation_id` becomes nullable;
* `title_source` ('GENERATED' for every existing row, 'SELLER_TYPED' for the new kind) keeps the two kinds distinguishable;
* `sku` and `marketplace` (NULL for generated approvals, which take them from their generation) say what a typed approval is for;
* one CHECK ties the kinds together: a GENERATED approval still has its generation and no sku/marketplace of its own; a SELLER_TYPED approval has no generation and no option, was
  worded by the seller (`edited_by_seller`), and names its product and marketplace.

The composite foreign keys (tenant_id, generation_id) / (tenant_id, option_id) / (generation_id, option_id) are MATCH SIMPLE, so a NULL generation skips them; nothing about generated approvals changes.
Table grants (SELECT, INSERT for the application role), FORCE RLS and the tenant policy are untouched; no existing row is rewritten (the new columns default / stay NULL).

Downgrade REFUSES (nothing half-applied) while any SELLER_TYPED approval exists: those rows are never deleted by a migration. FORCE RLS hides rows from the migration role, so the refusal is
produced by making `generation_id` NOT NULL again, which validates every row regardless of RLS.

Revision ID: 20261031_0008
Revises: 20261030_0007
Create Date: 2026-10-31
"""
from __future__ import annotations

from alembic import op

revision = "20261031_0008"
down_revision = "20261030_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE cmo_title_approval ALTER COLUMN generation_id DROP NOT NULL;
        ALTER TABLE cmo_title_approval ADD COLUMN title_source text NOT NULL DEFAULT 'GENERATED';
        ALTER TABLE cmo_title_approval ADD COLUMN sku text;
        ALTER TABLE cmo_title_approval ADD COLUMN marketplace text;
        ALTER TABLE cmo_title_approval ADD CONSTRAINT cmo_title_approval_source_check CHECK (
          (title_source = 'GENERATED' AND generation_id IS NOT NULL AND sku IS NULL AND marketplace IS NULL)
          OR
          (title_source = 'SELLER_TYPED' AND generation_id IS NULL AND option_id IS NULL AND edited_by_seller
             AND sku IS NOT NULL AND length(btrim(sku)) > 0 AND marketplace IN ('AMAZON', 'FLIPKART', 'MESHO'))
        );
        CREATE INDEX cmo_title_approval_typed_idx ON cmo_title_approval (tenant_id, sku, marketplace, approved_at DESC) WHERE title_source = 'SELLER_TYPED';
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
          ALTER TABLE cmo_title_approval ALTER COLUMN generation_id SET NOT NULL;
        EXCEPTION WHEN not_null_violation THEN
          RAISE EXCEPTION 'cannot downgrade: approvals of seller-typed titles exist in cmo_title_approval and are never deleted by a migration';
        END $$;
        DROP INDEX IF EXISTS cmo_title_approval_typed_idx;
        ALTER TABLE cmo_title_approval DROP CONSTRAINT IF EXISTS cmo_title_approval_source_check;
        ALTER TABLE cmo_title_approval DROP COLUMN IF EXISTS marketplace;
        ALTER TABLE cmo_title_approval DROP COLUMN IF EXISTS sku;
        ALTER TABLE cmo_title_approval DROP COLUMN IF EXISTS title_source;
        """
    )
