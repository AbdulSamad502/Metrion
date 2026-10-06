"use client";

import { CmoWorkspace } from "@/components/cmo/CmoWorkspace";
import { DashboardShell } from "@/components/dashboard/DashboardShell";

export default function CmoPage() {
  return (
    <DashboardShell title="Marketing" subtitle="Titles, listing copy, catalog answers and market research — for you to copy, never published for you">
      <CmoWorkspace />
    </DashboardShell>
  );
}
