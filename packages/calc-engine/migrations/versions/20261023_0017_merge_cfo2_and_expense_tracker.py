"""Merge the two migration lines that grew from 20260929_0012 in parallel.

CFO 2.0 (this branch): 20261021_0013 ... 20261022_0018 (expense ledger/classes, ads, cash, claims, cost arbitration, held rows).
Expense tracker (partner): 20261016_0013 ... 20261023_0016 (event-sourced expense ledger, templates, assignments).
The two touch different tables; this revision only joins the heads so there is one linear history from here on.

Revision ID: 20261023_0017
Revises: 20261022_0018, 20261023_0016
Create Date: 2026-10-23
"""
from __future__ import annotations

revision = "20261023_0017"
down_revision = ("20261022_0018", "20261023_0016")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
