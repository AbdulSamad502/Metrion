"use client";

import { useAuth } from "@clerk/nextjs";
import { DashboardShell } from "@/components/dashboard/DashboardShell";
import { ExpenseTracker } from "@/components/expenses/ExpenseTracker";
import { PAGE_COPY } from "@/lib/navigation";

/** The dedicated Expense Tracker dashboard under Profit & Finance (Round 9, R9-1). The page only displays what the backend returns: every total is the engine's
 * and carries its result reference; nothing here computes money. */
export default function ExpensesPage() {
  return (
    <DashboardShell {...PAGE_COPY["cfo-expenses"]}>
      <Workspace />
    </DashboardShell>
  );
}

function Workspace() {
  const { getToken } = useAuth();
  return <ExpenseTracker getToken={() => getToken()} />;
}
