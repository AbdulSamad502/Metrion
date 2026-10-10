"""agent_memory: make "append-only for the app role" true at the grant level

Migration 20261010_0011 granted SELECT, INSERT to metrion_app, but the cluster's default privileges had already given that role full DML on new tables, so the role could
still UPDATE and DELETE rows (found while building the shared findings ledger). A correction is a new row that supersedes the old one and forgetting is a FORGOTTEN row, so
nothing needs UPDATE or DELETE: they are revoked here and a test pins it.

Revision ID: 20261010_0014
Revises: 20261010_0013
Create Date: 2026-10-10
"""
from __future__ import annotations

from alembic import op

revision = "20261010_0014"
down_revision = "20261010_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("REVOKE ALL ON agent_memory FROM metrion_app; GRANT SELECT, INSERT ON agent_memory TO metrion_app;")


def downgrade() -> None:
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON agent_memory TO metrion_app;")
