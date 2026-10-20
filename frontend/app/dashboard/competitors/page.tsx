"use client";

import { useAuth } from "@clerk/nextjs";
import { useMemo } from "react";
import { PAGE_COPY } from "@/lib/navigation";
import { DashboardShell } from "@/components/dashboard/DashboardShell";
import { CiDashboard, type CiClient } from "@/components/ci/CiDashboard";
import { apiFetch, type MarketOverview } from "@/lib/api";
import type { CiWorkspace } from "@/lib/ciWorkspace";

export default function CompetitorsPage() {
  const { getToken } = useAuth();
  const client = useMemo<CiClient>(
    () => ({
      workspace: async (productId) =>
        apiFetch<CiWorkspace>(`/api/v1/ci/workspace${productId ? `?product_id=${encodeURIComponent(productId)}` : ""}`, await getToken()),
      market: async (productId) => apiFetch<MarketOverview>(`/api/v1/ci/market-overview/${encodeURIComponent(productId)}`, await getToken()),
    }),
    [getToken],
  );
  return (
    <DashboardShell {...PAGE_COPY["competitors"]}>
      <CiDashboard client={client} />
    </DashboardShell>
  );
}
