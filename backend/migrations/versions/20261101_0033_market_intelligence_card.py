"""CEO chat: the market-intelligence card (CMO 3.0 M10) may ride on a CEO ANSWER.

Widens `investigation_message_choices_shape` so an ANSWER may carry a `MARKET_INTELLIGENCE` card next to the existing kinds. The card is data only: marketplace news items and opportunities read from the seller's own saved market-trend reports (each with its cited sources, dates, freshness and relevance to their products), or the statement that there is nothing saved. It holds no image bytes and records nothing by itself.

Revision ID: 20261101_0033
Revises: 20261031_0032
Create Date: 2026-11-01
"""
from __future__ import annotations

from alembic import op

revision = "20261101_0033"
down_revision = "20261031_0032"
branch_labels = None
depends_on = None

_OLD = "('CANDIDATE_PICK', 'PICK', 'PREVIEW', 'READINESS', 'LISTING', 'LISTING_HISTORY', 'LISTING_PERFORMANCE', 'IMAGE_QUALITY')"
_NEW = "('CANDIDATE_PICK', 'PICK', 'PREVIEW', 'READINESS', 'LISTING', 'LISTING_HISTORY', 'LISTING_PERFORMANCE', 'IMAGE_QUALITY', 'MARKET_INTELLIGENCE')"
_SHAPE = """
ALTER TABLE investigation_message DROP CONSTRAINT IF EXISTS investigation_message_choices_shape;
ALTER TABLE investigation_message ADD CONSTRAINT investigation_message_choices_shape
  CHECK (choices IS NULL OR (jsonb_typeof(choices) = 'object' AND role = 'CEO'
         AND (kind = 'CLARIFICATION' OR (kind = 'ANSWER' AND choices ->> 'kind' IN {kinds}))));
"""


def upgrade() -> None:
    op.execute(_SHAPE.format(kinds=_NEW))


def downgrade() -> None:
    """No message is deleted. FORCE RLS hides every tenant's rows from the migration role, so existing market-intelligence cards cannot be cleared here; the older constraint is therefore added NOT VALID: it is
    enforced for every new or changed row (no new market-intelligence card can be stored) and is not checked against rows that already exist. Upgrading again recreates the constraint fully validated."""
    op.execute(_SHAPE.format(kinds=_OLD).rstrip().rstrip(";") + " NOT VALID;")
