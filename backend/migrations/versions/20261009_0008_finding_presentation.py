"""investigation_finding.presentation: the display snapshot of what the seller was shown

B5 (spec §5, R7 as amended, §6.27). The Hub's right-hand panel must show each specialist's actual response — labelled, formatted figures,
engine-classified bands, named gaps — and it must survive a page reload exactly as it was shown. A finding therefore carries a
`presentation` snapshot written ONCE at insert: display strings copied from values that were resolved through their provenance refs, plus
the refs themselves. It is never a value the CEO computed (the numbers were produced by Brain 1/2 and the specialists; the CEO only formats a
stored value for display, with the same formatter every other CEO figure uses), and it cannot be rewritten: `investigation_finding` is
append-only for the application role (migration 0007 revoked UPDATE and DELETE), so there is no later code path that edits a snapshot.

Nullable: findings written before this migration, and findings written by callers that do not present, carry none; the API then shows the
refs-only view exactly as before.

Revision ID: 20261009_0008
Revises: 20261007_0007
Create Date: 2026-10-09
"""
from __future__ import annotations

from alembic import op

revision = "20261009_0008"
down_revision = "20261007_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE investigation_finding ADD COLUMN presentation jsonb;")
    op.execute(
        "ALTER TABLE investigation_finding ADD CONSTRAINT investigation_finding_presentation_is_object "
        "CHECK (presentation IS NULL OR jsonb_typeof(presentation) = 'object');"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE investigation_finding DROP CONSTRAINT IF EXISTS investigation_finding_presentation_is_object;")
    op.execute("ALTER TABLE investigation_finding DROP COLUMN IF EXISTS presentation;")
