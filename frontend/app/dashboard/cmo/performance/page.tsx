"use client";

import { useAuth } from "@clerk/nextjs";
import { useMemo } from "react";
import { PerformanceDashboard } from "@/components/cmo/performance/PerformanceDashboard";
import { DashboardShell } from "@/components/dashboard/DashboardShell";
import { createPerformanceApi } from "@/lib/cmoPerformance";

export default function CmoPerformancePage() {
  const { getToken } = useAuth();
  const api = useMemo(() => createPerformanceApi(() => getToken()), [getToken]);
  return (
    <DashboardShell title="Listing performance" subtitle="From the reports you import: impressions, clicks, orders and conversion, and what was observed around each listing version. Nothing is estimated.">
      <PerformanceDashboard api={api} />
    </DashboardShell>
  );
}
