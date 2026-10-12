"use client";

import { PAGE_COPY } from "@/lib/navigation";
import { DashboardShell } from "@/components/dashboard/DashboardShell";
import { CompetitorWorkspace } from "@/components/ci/CompetitorWorkspace";

export default function CompetitorsPage() {
  return (
    <DashboardShell
      {...PAGE_COPY["competitors"]}
    >
      <CompetitorWorkspace />
    </DashboardShell>
  );
}
