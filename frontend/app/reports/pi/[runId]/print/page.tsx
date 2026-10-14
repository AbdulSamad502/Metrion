"use client";

import { useMemo } from "react";
import { useAuth } from "@clerk/nextjs";
import { useParams } from "next/navigation";
import { PiReportPrint } from "@/components/pi/PiReportPrint";
import { createPiClient } from "@/lib/piShowcase";

/** Print / Save-as-PDF page of one saved Product Intelligence report. Deliberately outside `/dashboard`: no sidebar or header, so the printout is the report only.
 * It reads the same tenant-scoped saved-report endpoint as the dashboard (another tenant's id is a 404) and starts nothing. */
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export default function PrintPage() {
  const { getToken } = useAuth();
  const params = useParams<{ runId: string }>();
  const client = useMemo(() => createPiClient(() => getToken()), [getToken]);
  const runId = String(params.runId ?? "");
  if (!UUID.test(runId)) return <p role="alert" style={{ padding: 24 }}>This report link is not valid.</p>;
  return <PiReportPrint client={client} runId={runId} />;
}
