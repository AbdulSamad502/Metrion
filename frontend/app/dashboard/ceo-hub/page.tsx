"use client";

import { DashboardShell } from "@/components/dashboard/DashboardShell";
import { CeoHub } from "@/components/ceo/hub/CeoHubWorkspace";

export default function CeoHubPage() {
  return (
    <DashboardShell title="CEO Hub" subtitle="Ask anything. The CEO answers, or hands it to the right agent.">
      <div className="mt-content">
        <CeoHub />
      </div>
    </DashboardShell>
  );
}
