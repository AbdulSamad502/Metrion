"use client";

import { PAGE_COPY } from "@/lib/navigation";
import { CmoWorkspace } from "@/components/cmo/CmoWorkspace";
import { DashboardShell } from "@/components/dashboard/DashboardShell";

export default function CmoPage() {
  return (
    <DashboardShell {...PAGE_COPY["cmo"]}>
      <CmoWorkspace />
    </DashboardShell>
  );
}
