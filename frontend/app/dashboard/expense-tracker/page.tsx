"use client";

import { useAuth } from "@clerk/nextjs";
import { DashboardShell } from "@/components/dashboard/DashboardShell";
import { ExpenseTrackerSection } from "@/components/cfo/sections/ExpenseTrackerSection";
import "@/components/overview/overview.css";
import "@/components/cfo/cfo-skin.css";
import { PAGE_COPY } from "@/lib/navigation";

/** The Expense Tracker as its own tool. Part of the CFO's data, not an agent: it records expenses and budgets and reads back what the backend stores. */
export default function ExpenseTrackerPage() {
  const { getToken } = useAuth();
  return (
    <DashboardShell {...PAGE_COPY["expense-tracker"]}>
      <div className="ov cfo-skin">
        <header className="ov-head ov-rise">
          <div>
            <h2 className="ov-h">Where your money goes</h2>
            <p className="ov-body" style={{ marginTop: 4 }}>Log expenses and keep each category inside a budget.</p>
          </div>
        </header>
        <div className="cfo-stack">
          <ExpenseTrackerSection getToken={getToken} />
        </div>
      </div>
    </DashboardShell>
  );
}
