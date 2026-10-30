"""CEO chat: the listing-preview card (CMO 3.0 M4) may ride on a CEO ANSWER.

Widens `investigation_message_choices_shape` so an ANSWER may carry a `PREVIEW` card next to the existing `CANDIDATE_PICK` / `PICK` cards. The card is data only (titles, scores, cut-off
text, labels); it holds no image bytes and no price, rating or sales figure. A CLARIFICATION may still carry any card object.

Revision ID: 20261030_0025
Revises: 20261021_0024
Create Date: 2026-10-30
"""
from __future__ import annotations

from alembic import op

revision = "20261030_0025"
down_revision = "20261021_0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE investigation_message DROP CONSTRAINT IF EXISTS investigation_message_choices_shape;
        ALTER TABLE investigation_message ADD CONSTRAINT investigation_message_choices_shape
          CHECK (choices IS NULL OR (jsonb_typeof(choices) = 'object' AND role = 'CEO'
                 AND (kind = 'CLARIFICATION' OR (kind = 'ANSWER' AND choices ->> 'kind' IN ('CANDIDATE_PICK', 'PICK', 'PREVIEW')))));
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE investigation_message SET choices = NULL WHERE kind = 'ANSWER' AND choices ->> 'kind' = 'PREVIEW';
        ALTER TABLE investigation_message DROP CONSTRAINT IF EXISTS investigation_message_choices_shape;
        ALTER TABLE investigation_message ADD CONSTRAINT investigation_message_choices_shape
          CHECK (choices IS NULL OR (jsonb_typeof(choices) = 'object' AND role = 'CEO'
                 AND (kind = 'CLARIFICATION' OR (kind = 'ANSWER' AND choices ->> 'kind' IN ('CANDIDATE_PICK', 'PICK')))));
        """
    )
