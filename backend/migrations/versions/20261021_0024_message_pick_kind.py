"""CEO chat: the generic pick card (check boxes / radio buttons) may ride on a CEO ANSWER (owner decision 2026-10-21).

Widens `investigation_message_choices_shape` from the single `CANDIDATE_PICK` ANSWER case (20261020_0023) to the general `PICK` card the CI conversation uses for categories, tracked
competitors, screenshots and search results. A CLARIFICATION may still carry any card object.

Revision ID: 20261021_0024
Revises: 20261020_0023
Create Date: 2026-10-21
"""
from __future__ import annotations

from alembic import op

revision = "20261021_0024"
down_revision = "20261020_0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE investigation_message DROP CONSTRAINT IF EXISTS investigation_message_choices_shape;
        ALTER TABLE investigation_message ADD CONSTRAINT investigation_message_choices_shape
          CHECK (choices IS NULL OR (jsonb_typeof(choices) = 'object' AND role = 'CEO'
                 AND (kind = 'CLARIFICATION' OR (kind = 'ANSWER' AND choices ->> 'kind' IN ('CANDIDATE_PICK', 'PICK')))));
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE investigation_message SET choices = NULL WHERE kind = 'ANSWER' AND choices ->> 'kind' = 'PICK';
        ALTER TABLE investigation_message DROP CONSTRAINT IF EXISTS investigation_message_choices_shape;
        ALTER TABLE investigation_message ADD CONSTRAINT investigation_message_choices_shape
          CHECK (choices IS NULL OR (jsonb_typeof(choices) = 'object' AND role = 'CEO'
                 AND (kind = 'CLARIFICATION' OR (kind = 'ANSWER' AND choices ->> 'kind' = 'CANDIDATE_PICK'))));
        """
    )
