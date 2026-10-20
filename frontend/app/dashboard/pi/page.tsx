"use client";

import { Suspense, useMemo } from "react";
import { useAuth } from "@clerk/nextjs";
import { useSearchParams } from "next/navigation";
import { PAGE_COPY } from "@/lib/navigation";
import { DashboardShell } from "@/components/dashboard/DashboardShell";
import { PiShowcase } from "@/components/pi/PiShowcase";
import { createPiClient } from "@/lib/piShowcase";

/** The Product Intelligence page is a read-only showcase of research the CEO already ran and saved (docs/specs/ceo-pi-research-flow.md C1). Research is started
 * only in the CEO chat; there is no form and no run control here. `?run=<id>` opens that saved report (the CEO's "View Detailed Research" link). */
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function Showcase() {
  const { getToken } = useAuth();
  const run = useSearchParams().get("run");
  const client = useMemo(() => createPiClient(() => getToken()), [getToken]);
  return <PiShowcase client={client} initialRunId={run && UUID.test(run) ? run : null} />;
}

export default function PiPage() {
  return (
    <DashboardShell {...PAGE_COPY["products"]}>
      <Suspense fallback={null}>
        <Showcase />
      </Suspense>
    </DashboardShell>
  );
}
