"""CFO 2.0 Phase 3 finalization — ledger cost arbitration (docs/specs/cfo-expense-ledger.md D5 / AC-L8, cfo-phase3-scope.md AD4).

expense_class_assignment.allocated_component   which cost pool a ledger entry classed ALLOCATED_COST belongs to (advertising | packaging | storage | logistics | other).
                                               Required exactly when the class is ALLOCATED_COST; nothing else may carry it.
cost_owner_choice                              now arbitrates every pool component, a marketplace or the whole account ("ALL"), and a third source (LEDGER).

Why: the seller's hand-entered costs may live in the Expense Tracker's pools or in the ledger — never both for the same component and period, or the cost would be
subtracted twice. The cost-ownership choice is how the seller says which one is right.

Revision ID: 20261022_0017
Revises: 20261022_0016
Create Date: 2026-10-22
"""
from __future__ import annotations

from alembic import op

revision = "20261022_0017"
down_revision = "20261022_0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE expense_class_assignment ADD COLUMN allocated_component text;
        ALTER TABLE expense_class_assignment ADD CONSTRAINT expense_class_assignment_component_check
          CHECK (allocated_component IS NULL OR allocated_component IN ('ADVERTISING','PACKAGING','STORAGE','LOGISTICS','OTHER'));
        ALTER TABLE expense_class_assignment ADD CONSTRAINT expense_class_assignment_component_scope_check
          CHECK ((allocated_component IS NOT NULL) = (class = 'ALLOCATED_COST'));
        """
    )
    op.execute(
        """
        ALTER TABLE cost_owner_choice DROP CONSTRAINT cost_owner_choice_component_check;
        ALTER TABLE cost_owner_choice ADD CONSTRAINT cost_owner_choice_component_check
          CHECK (component IN ('ADVERTISING','PACKAGING','STORAGE','LOGISTICS','OTHER'));
        ALTER TABLE cost_owner_choice DROP CONSTRAINT cost_owner_choice_owner_check;
        ALTER TABLE cost_owner_choice ADD CONSTRAINT cost_owner_choice_owner_check CHECK (owner IN ('REPORT','POOL','LEDGER'));
        ALTER TABLE cost_owner_choice DROP CONSTRAINT cost_owner_choice_market_check;
        ALTER TABLE cost_owner_choice ADD CONSTRAINT cost_owner_choice_market_check CHECK (marketplace IN ('AMAZON','FLIPKART','MEESHO','ALL'));
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE cost_owner_choice DROP CONSTRAINT cost_owner_choice_market_check;
        ALTER TABLE cost_owner_choice ADD CONSTRAINT cost_owner_choice_market_check CHECK (marketplace IN ('AMAZON','FLIPKART','MEESHO'));
        ALTER TABLE cost_owner_choice DROP CONSTRAINT cost_owner_choice_owner_check;
        ALTER TABLE cost_owner_choice ADD CONSTRAINT cost_owner_choice_owner_check CHECK (owner IN ('REPORT','POOL'));
        ALTER TABLE cost_owner_choice DROP CONSTRAINT cost_owner_choice_component_check;
        ALTER TABLE cost_owner_choice ADD CONSTRAINT cost_owner_choice_component_check CHECK (component IN ('ADVERTISING'));
        ALTER TABLE expense_class_assignment DROP CONSTRAINT expense_class_assignment_component_scope_check;
        ALTER TABLE expense_class_assignment DROP CONSTRAINT expense_class_assignment_component_check;
        ALTER TABLE expense_class_assignment DROP COLUMN allocated_component;
        """
    )
