"use client";

import { useAuth } from "@clerk/nextjs";
import { useSearchParams } from "next/navigation";
import { Suspense, useMemo } from "react";
import { ImagesDashboard } from "@/components/cmo/images/ImagesDashboard";
import { DashboardShell } from "@/components/dashboard/DashboardShell";
import { createImagesApi } from "@/lib/cmoImages";

function Images() {
  const { getToken } = useAuth();
  const params = useSearchParams();
  const api = useMemo(() => createImagesApi(() => getToken()), [getToken]);
  return <ImagesDashboard api={api} initialSku={params.get("sku") ?? ""} initialMarketplace={params.get("marketplace") ?? "AMAZON"} />;
}

export default function CmoImagesPage() {
  return (
    <DashboardShell title="Product images" subtitle="Upload your own product pictures and see how clear, well lit, well framed and consistent they are, and what to improve. Free; nothing is edited or published.">
      <Suspense fallback={null}>
        <Images />
      </Suspense>
    </DashboardShell>
  );
}
