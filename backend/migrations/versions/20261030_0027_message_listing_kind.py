"""CEO chat: the full-listing card (CMO 3.0 M6) may ride on a CEO ANSWER.

Widens `investigation_message_choices_shape` so an ANSWER may carry a `LISTING` card next to `CANDIDATE_PICK`, `PICK`, `PREVIEW` and `READINESS`. The card is data only (the listing sections, the
keyword map, the audit findings, competitor evidence rows and the separately labelled states); it holds no image bytes and no search, demand, marketplace-approval, ranking or sales figure.

Revision ID: 20261030_0027
Revises: 20261030_0026
Create Date: 2026-10-30
"""
from __future__ import annotations

from alembic import op

revision = "20261030_0027"
down_revision = "20261030_0026"
branch_labels = None
depends_on = None

_OLD = "('CANDIDATE_PICK', 'PICK', 'PREVIEW', 'READINESS')"
_NEW = "('CANDIDATE_PICK', 'PICK', 'PREVIEW', 'READINESS', 'LISTING')"
_SHAPE = """
ALTER TABLE investigation_message DROP CONSTRAINT IF EXISTS investigation_message_choices_shape;
ALTER TABLE investigation_message ADD CONSTRAINT investigation_message_choices_shape
  CHECK (choices IS NULL OR (jsonb_typeof(choices) = 'object' AND role = 'CEO'
         AND (kind = 'CLARIFICATION' OR (kind = 'ANSWER' AND choices ->> 'kind' IN {kinds}))));
"""


def upgrade() -> None:
    op.execute(_SHAPE.format(kinds=_NEW))


def downgrade() -> None:
    op.execute("UPDATE investigation_message SET choices = NULL WHERE kind = 'ANSWER' AND choices ->> 'kind' = 'LISTING';")
    op.execute(_SHAPE.format(kinds=_OLD))
