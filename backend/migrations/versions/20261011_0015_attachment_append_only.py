"""investigation_attachment: make it genuinely append-only for the app role

0010 documented the table as append-only (`GRANT SELECT, INSERT`) but, as 0007 explains, `docker/postgres-init/02-roles.sql`
runs ALTER DEFAULT PRIVILEGES so metrion_app already holds SELECT/INSERT/UPDATE/DELETE on every table the migration role
creates; a GRANT cannot narrow that, only a REVOKE can. This migration revokes UPDATE and DELETE so an attachment (evidence
of what the seller showed the CEO) can be neither rewritten nor removed by the application.

Revision ID: 20261011_0015
Revises: 20261010_0014
Create Date: 2026-10-10
"""
from __future__ import annotations

from alembic import op

revision = "20261011_0015"
down_revision = "20261010_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("REVOKE UPDATE, DELETE ON investigation_attachment FROM metrion_app;")


def downgrade() -> None:
    # Restores the pre-0015 state (the default-privilege grant), as 0007's downgrade does.
    op.execute("GRANT UPDATE, DELETE ON investigation_attachment TO metrion_app;")
