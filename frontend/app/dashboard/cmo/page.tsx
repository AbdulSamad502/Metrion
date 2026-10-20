"use client";

import { Suspense, useEffect, useMemo, useState } from "react";
import { useAuth } from "@clerk/nextjs";
import { useSearchParams } from "next/navigation";
import { PAGE_COPY } from "@/lib/navigation";
import { ShowcaseDashboard } from "@/components/cmo/ShowcaseDashboard";
import { DashboardShell } from "@/components/dashboard/DashboardShell";
import { createShowcaseClient, FIXTURE_ALLOWED, type ShowcaseClient } from "@/lib/cmoShowcase";

function Showcase() {
  const { getToken } = useAuth();
  const wantsSample = useSearchParams().get("fixture") === "1";
  const [fixture, setFixture] = useState<ShowcaseClient | null>(null);
  useEffect(() => {
    // Dev-only: the NODE_ENV check is inlined by Next, so this import (and the fixture module) is dropped from production builds.
    if (process.env.NODE_ENV !== "production" && wantsSample) void import("@/lib/cmoShowcaseFixture").then((m) => setFixture(m.fixtureClient));
  }, [wantsSample]);
  const live = useMemo(() => createShowcaseClient(() => getToken()), [getToken]);
  if (FIXTURE_ALLOWED && wantsSample) return fixture ? <ShowcaseDashboard client={fixture} sample /> : null;
  return <ShowcaseDashboard client={live} />;
}

export default function CmoPage() {
  return (
    <DashboardShell {...PAGE_COPY["cmo"]}>
      <Suspense fallback={null}>
        <Showcase />
      </Suspense>
    </DashboardShell>
  );
}
