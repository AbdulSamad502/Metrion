"""CI V3: give the application role back write access to the seller's own alert-preference columns of ci_tenant_config.

`20261012_0018` made ci_tenant_config SELECT-only for the application role (least privilege) and says the migration that builds a feature re-grants what it needs.
The CEO now saves the seller's own quiet hours and price-change threshold (CI spec C42, section 6.26), so exactly those columns are writable, and nothing else: the
retention, discovery and watchlist-limit settings (including `max_active_competitors`) stay read-only, so a seller cannot raise their own limit.

This runs after every package migration, so the grant survives the revoke in 0018 on a fresh database (the same grant in the competitor-intelligence package runs earlier).

Least privilege (the privilege-boundary guard caught these): the four new CI tables the application never deletes from are no longer deletable by it.

Revision ID: 20261014_0021
Revises: 20261013_0020
Create Date: 2026-10-19
"""

from __future__ import annotations

from alembic import op

revision = "20261014_0021"
down_revision = "20261013_0020"
branch_labels = None
depends_on = None


# The application never deletes from these: findings and confirmation questions are history (expired or answered, never removed), alert state and held alerts are closed by status.
NOT_DELETABLE = ("ci_finding", "ci_info_request", "ci_alert_state", "ci_held_alert")


def upgrade() -> None:
    for table in NOT_DELETABLE:
        op.execute(f"REVOKE DELETE, TRUNCATE ON {table} FROM metrion_app")
    op.execute("GRANT INSERT (tenant_id, quiet_hours_start, quiet_hours_end, quiet_hours_tz, price_threshold_pct, updated_by, updated_at) ON ci_tenant_config TO metrion_app")
    op.execute("GRANT UPDATE (quiet_hours_start, quiet_hours_end, quiet_hours_tz, price_threshold_pct, updated_by, updated_at) ON ci_tenant_config TO metrion_app")


def downgrade() -> None:
    for table in NOT_DELETABLE:
        op.execute(f"GRANT DELETE ON {table} TO metrion_app")
    op.execute("REVOKE INSERT (tenant_id, quiet_hours_start, quiet_hours_end, quiet_hours_tz, price_threshold_pct, updated_by, updated_at) ON ci_tenant_config FROM metrion_app")
    op.execute("REVOKE UPDATE (quiet_hours_start, quiet_hours_end, quiet_hours_tz, price_threshold_pct, updated_by, updated_at) ON ci_tenant_config FROM metrion_app")
