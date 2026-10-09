"""investigation_message.choices: the structured options of a CEO clarification (decision card)

Spec §6.32 (2026-10-10). A CEO message of kind CLARIFICATION may carry a `choices` object: the slot being asked about, the pending intent (route, key and the
slots already understood, so a choice or a typed "Other" can resume it with NO model call), and the options (recommended first, alternatives, then "Other").
Options are built by code from real data; the model writes nothing here. The column is nullable and only a CEO CLARIFICATION message may carry it. The
history stays append-only: whether a card has been answered is derived from the next turn, never by editing the message.

Revision ID: 20261010_0009
Revises: 20261009_0008
Create Date: 2026-10-10
"""
from __future__ import annotations

from alembic import op

revision = "20261010_0009"
down_revision = "20261009_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE investigation_message ADD COLUMN choices jsonb;")
    op.execute(
        "ALTER TABLE investigation_message ADD CONSTRAINT investigation_message_choices_shape "
        "CHECK (choices IS NULL OR (jsonb_typeof(choices) = 'object' AND role = 'CEO' AND kind = 'CLARIFICATION'));"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE investigation_message DROP CONSTRAINT IF EXISTS investigation_message_choices_shape;")
    op.execute("ALTER TABLE investigation_message DROP COLUMN IF EXISTS choices;")
