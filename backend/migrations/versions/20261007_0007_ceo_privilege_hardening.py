"""ceo privilege hardening: the app role can no longer delete CEO history or rewrite findings

B1 privilege audit (2026-10-07). `docker/postgres-init/02-roles.sql` runs ALTER DEFAULT PRIVILEGES so metrion_app
receives SELECT/INSERT/UPDATE/DELETE on every table the migration role creates; a table is therefore deletable by the
application unless its migration REVOKEs. 0006 revoked DELETE on the three new tables only. This migration closes the
remaining CEO-owned gaps (all created by 0002, before the CEO was built):

* `investigation_finding`: evidence is append-only - SELECT, INSERT only (no UPDATE, no DELETE). A finding keeps the
  provenance it was written with (spec Q23); no repository code path updates one.
* `investigation_message`, `investigation`, `agent_run`: DELETE revoked. Conversation history, the investigation
  record and the run audit are never removed by the application (an investigation is ARCHIVED, never deleted). UPDATE
  is kept: messages get `turn_id`, investigations change status, runs complete.

Deliberately NOT touched here (other owners; reported in docs/planning/ceo-build-status.md): auth_audit,
metered_event, metric_result, leak_finding, ingestion_run, whatsapp_message and the rest of the tables listed in
`tests/integration/test_privilege_boundary.py::KNOWN_APP_DELETABLE`.

Revision ID: 20261007_0007
Revises: 20261007_0006
Create Date: 2026-10-07
"""
from __future__ import annotations

from alembic import op

revision = "20261007_0007"
down_revision = "20261007_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        REVOKE UPDATE, DELETE ON investigation_finding FROM metrion_app;
        REVOKE DELETE ON investigation_message FROM metrion_app;
        REVOKE DELETE ON investigation FROM metrion_app;
        REVOKE DELETE ON agent_run FROM metrion_app;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        GRANT UPDATE ON investigation_finding TO metrion_app;
        GRANT DELETE ON investigation_message, investigation, agent_run TO metrion_app;
        """
    )
