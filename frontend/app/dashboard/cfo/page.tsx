"use client";

import { PAGE_COPY } from "@/lib/navigation";
import { DashboardShell } from "@/components/dashboard/DashboardShell";
import { FinanceDashboard } from "@/components/cfo/FinanceDashboard";

/** Profit & Finance: a read-only page of saved results. Working things out happens in the CEO chat; the older forms live at /dashboard/cfo/tools. */
export default function CfoPage() {
  return (
    <DashboardShell {...PAGE_COPY["cfo"]}>
      <FinanceDashboard />
    </DashboardShell>
  );
}
