"""CEO chat: the listing-history card (CMO 3.0 M7) may ride on a CEO ANSWER.

Widens `investigation_message_choices_shape` so an ANSWER may carry a `LISTING_HISTORY` card next to `CANDIDATE_PICK`, `PICK`, `PREVIEW`, `READINESS` and `LISTING`. The card is data only: the saved
versions of a listing, the exact differences between two of them, the saved audits and evidence-based suggestions, or one short question about which product or version is meant. It holds no image
bytes and no search, demand, marketplace-approval, ranking, sales or performance figure.

Revision ID: 20261031_0030
Revises: 20261031_0029
Create Date: 2026-10-31
"""
from __future__ import annotations

from alembic import op

revision = "20261031_0030"
down_revision = "20261031_0029"
branch_labels = None
depends_on = None

_OLD = "('CANDIDATE_PICK', 'PICK', 'PREVIEW', 'READINESS', 'LISTING')"
_NEW = "('CANDIDATE_PICK', 'PICK', 'PREVIEW', 'READINESS', 'LISTING', 'LISTING_HISTORY')"
_SHAPE = """
ALTER TABLE investigation_message DROP CONSTRAINT IF EXISTS investigation_message_choices_shape;
ALTER TABLE investigation_message ADD CONSTRAINT investigation_message_choices_shape
  CHECK (choices IS NULL OR (jsonb_typeof(choices) = 'object' AND role = 'CEO'
         AND (kind = 'CLARIFICATION' OR (kind = 'ANSWER' AND choices ->> 'kind' IN {kinds}))));
"""


def upgrade() -> None:
    op.execute(_SHAPE.format(kinds=_NEW))


def downgrade() -> None:
    """No message is deleted. FORCE RLS hides every tenant's rows from the migration role, so existing history cards cannot be cleared here; the older constraint is therefore added NOT VALID: it
    is enforced for every new or changed row (no new history card can be stored) and is not checked against rows that already exist. Upgrading again recreates the constraint fully validated."""
    op.execute(_SHAPE.format(kinds=_OLD).rstrip().rstrip(";") + " NOT VALID;")
