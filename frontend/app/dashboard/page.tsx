"use client";

import { PAGE_COPY } from "@/lib/navigation";
import { DashboardShell } from "@/components/dashboard/DashboardShell";
import { Overview } from "@/components/overview/Overview";

/** The post-auth landing screen. Every figure comes from a saved result the backend presented (`/ceo/state/health`, `/ci/summary`,
 * the shared notifications feed, `/ceo-hub/agents`); nothing is computed here. Where data does not exist the page says so. */
export default function DashboardPage() {
  return (
    <DashboardShell {...PAGE_COPY["overview"]}>
      <Overview />
    </DashboardShell>
  );
}
