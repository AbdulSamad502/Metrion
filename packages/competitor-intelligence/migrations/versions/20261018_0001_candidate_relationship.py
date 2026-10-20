"""CP2: ci_candidate.relationship_class / relationship_basis (spec §5.7, §6.27.1, C43).

Identity (`identity_match`) and competitive relationship are separate attributes; this adds the
second without touching the first. Existing rows default to UNKNOWN — never back-filled with a
guess (C25).

Revision ID: 20261018_0001
Revises: 20260922_0002
Create Date: 2026-10-18
"""
from __future__ import annotations

from alembic import op

revision = "20261018_0001"
down_revision = "20260922_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE ci_candidate ADD COLUMN relationship_class text NOT NULL DEFAULT 'UNKNOWN';")
    op.execute("ALTER TABLE ci_candidate ADD COLUMN relationship_basis jsonb NOT NULL DEFAULT '{}'::jsonb;")
    op.execute(
        "ALTER TABLE ci_candidate ADD CONSTRAINT ci_candidate_relationship_class_chk CHECK "
        "(relationship_class IN ('SAME_PRODUCT','VARIANT','DIRECT_COMPETITOR','FUNCTIONAL_ALTERNATIVE','UNRELATED','UNKNOWN'));"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE ci_candidate DROP CONSTRAINT IF EXISTS ci_candidate_relationship_class_chk;")
    op.execute("ALTER TABLE ci_candidate DROP COLUMN IF EXISTS relationship_basis;")
    op.execute("ALTER TABLE ci_candidate DROP COLUMN IF EXISTS relationship_class;")
