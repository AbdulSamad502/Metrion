"""CEO chat: a persisted, monotonic order for investigation messages.

`created_at` is stamped by the application once per turn, so a seller's message and the CEO's reply to it can carry the identical timestamp. Ordering such a tie by the random `id` could place
the CEO's open question BEFORE the seller's message that came first, and the seller's next answer was then sent to the intent classifier instead of the open question. `seq` is an identity
column: the database assigns it in insertion order, so `ORDER BY created_at, seq` is deterministic and chronological. Existing rows receive their numbers in physical (insertion) order when the
column is added; nothing else changes. The column is assigned by the database only (GENERATED ALWAYS), so no writer can set it.

Revision ID: 20261031_0029
Revises: 20261030_0028
Create Date: 2026-10-31
"""
from __future__ import annotations

from alembic import op

revision = "20261031_0029"
down_revision = "20261030_0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE investigation_message ADD COLUMN seq bigint GENERATED ALWAYS AS IDENTITY;")
    op.execute("CREATE INDEX investigation_message_order_idx ON investigation_message (investigation_id, created_at, seq);")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS investigation_message_order_idx;")
    op.execute("ALTER TABLE investigation_message DROP COLUMN IF EXISTS seq;")
