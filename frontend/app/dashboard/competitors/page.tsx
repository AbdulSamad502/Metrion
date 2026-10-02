"use client";

import { DashboardShell } from "@/components/dashboard/DashboardShell";
import { CompetitorWorkspace } from "@/components/ci/CompetitorWorkspace";

export default function CompetitorsPage() {
  return (
    <DashboardShell
      title="Competitors"
      subtitle="Tracked competitor prices, evidence you provide, and what changed"
    >
      <CompetitorWorkspace />
    </DashboardShell>
  );
}
