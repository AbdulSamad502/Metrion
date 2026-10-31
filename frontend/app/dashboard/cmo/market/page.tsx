"use client";

import { useAuth } from "@clerk/nextjs";
import { useMemo } from "react";
import { MarketDashboard } from "@/components/cmo/market/MarketDashboard";
import { DashboardShell } from "@/components/dashboard/DashboardShell";
import { createMarketApi } from "@/lib/cmoMarket";

export default function CmoMarketPage() {
  const { getToken } = useAuth();
  const api = useMemo(() => createMarketApi(() => getToken()), [getToken]);
  return (
    <DashboardShell title="Market opportunities and news" subtitle="Marketplace news and opportunities from the market-trend reports you saved, related to your own products. Nothing new is searched and nothing is invented.">
      <MarketDashboard api={api} />
    </DashboardShell>
  );
}
