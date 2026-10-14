"use client";

import { Suspense } from "react";
import { PAGE_COPY } from "@/lib/navigation";
import { DashboardShell } from "@/components/dashboard/DashboardShell";
import { CeoHub } from "@/components/ceo/hub/CeoHubWorkspace";

export default function CeoHubPage() {
  return (
    <DashboardShell {...PAGE_COPY["ceo-hub"]}>
      <div className="h-full w-full">
        <Suspense fallback={null}>
          <CeoHub />
        </Suspense>
      </div>
    </DashboardShell>
  );
}
