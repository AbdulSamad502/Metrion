"""CEO chat: the buyer-questions / listing-readiness card (CMO 3.0 M5) may ride on a CEO ANSWER.

Widens `investigation_message_choices_shape` so an ANSWER may carry a `READINESS` card next to `CANDIDATE_PICK`, `PICK` and `PREVIEW`. The card is data only (questions with the seller's own
answers and their sources, checklist items, points, statuses, verdicts); it holds no image bytes and no search, demand, marketplace-approval or sales figure.

Revision ID: 20261030_0026
Revises: 20261030_0025
Create Date: 2026-10-30
"""
from __future__ import annotations

from alembic import op

revision = "20261030_0026"
down_revision = "20261030_0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE investigation_message DROP CONSTRAINT IF EXISTS investigation_message_choices_shape;
        ALTER TABLE investigation_message ADD CONSTRAINT investigation_message_choices_shape
          CHECK (choices IS NULL OR (jsonb_typeof(choices) = 'object' AND role = 'CEO'
                 AND (kind = 'CLARIFICATION' OR (kind = 'ANSWER' AND choices ->> 'kind' IN ('CANDIDATE_PICK', 'PICK', 'PREVIEW', 'READINESS')))));
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE investigation_message SET choices = NULL WHERE kind = 'ANSWER' AND choices ->> 'kind' = 'READINESS';
        ALTER TABLE investigation_message DROP CONSTRAINT IF EXISTS investigation_message_choices_shape;
        ALTER TABLE investigation_message ADD CONSTRAINT investigation_message_choices_shape
          CHECK (choices IS NULL OR (jsonb_typeof(choices) = 'object' AND role = 'CEO'
                 AND (kind = 'CLARIFICATION' OR (kind = 'ANSWER' AND choices ->> 'kind' IN ('CANDIDATE_PICK', 'PICK', 'PREVIEW')))));
        """
    )
