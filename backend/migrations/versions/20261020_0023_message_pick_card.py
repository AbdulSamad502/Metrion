"""CEO chat: an ANSWER message may carry the competitor pick card (owner decision 2026-10-20).

`investigation_message.choices` was only allowed on a CLARIFICATION. The top-matches list the CEO shows after a competitor search carries a CANDIDATE_PICK card (check boxes the seller ticks,
then saves). The shape check is widened by exactly that one case: a CEO ANSWER whose card says `kind = 'CANDIDATE_PICK'`.

Revision ID: 20261020_0023
Revises: 20261020_0022
Create Date: 2026-10-20
"""
from __future__ import annotations

from alembic import op

revision = "20261020_0023"
down_revision = "20261020_0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE investigation_message DROP CONSTRAINT IF EXISTS investigation_message_choices_shape;
        ALTER TABLE investigation_message ADD CONSTRAINT investigation_message_choices_shape
          CHECK (choices IS NULL OR (jsonb_typeof(choices) = 'object' AND role = 'CEO'
                 AND (kind = 'CLARIFICATION' OR (kind = 'ANSWER' AND choices ->> 'kind' = 'CANDIDATE_PICK'))));
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE investigation_message SET choices = NULL WHERE kind = 'ANSWER' AND choices IS NOT NULL;
        ALTER TABLE investigation_message DROP CONSTRAINT IF EXISTS investigation_message_choices_shape;
        ALTER TABLE investigation_message ADD CONSTRAINT investigation_message_choices_shape
          CHECK (choices IS NULL OR (jsonb_typeof(choices) = 'object' AND role = 'CEO' AND kind = 'CLARIFICATION'));
        """
    )
