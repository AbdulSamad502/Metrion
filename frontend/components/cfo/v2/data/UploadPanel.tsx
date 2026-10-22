"use client";

import { useAuth } from "@clerk/nextjs";
import { useState } from "react";
import { ErrorNotice } from "@/components/ui/ErrorNotice";
import { friendlyApiError } from "@/lib/apiErrors";
import { REPORT_KINDS, marketplaceFor, uploadReport, type JobView, type ReportKind } from "@/lib/cfoV2/ingest";

const MARKETPLACES = [
  { value: "AMAZON", label: "Amazon" },
  { value: "FLIPKART", label: "Flipkart" },
  { value: "MEESHO", label: "Meesho" },
] as const;

/** Choose what the file is, pick it, upload. The file streams to the server; the server answers 202 with the job to follow. An expense file belongs to the business, so the
 * marketplace choice is hidden for it. Metrion reads files you upload; it never connects to a marketplace account. */
export function UploadPanel({ onStarted }: { onStarted: (job: JobView) => void }) {
  const { getToken } = useAuth();
  const [kind, setKind] = useState<ReportKind>("SETTLEMENT");
  const [marketplace, setMarketplace] = useState<string>("MEESHO");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      onStarted(await uploadReport(await getToken(), file, { marketplace: marketplaceFor(kind, marketplace), kind }));
      setFile(null);
    } catch (e) {
      setError(friendlyApiError(e, "The upload could not be started"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form
      aria-label="Upload a report"
      className="flex flex-col gap-3"
      onSubmit={(e) => {
        e.preventDefault();
        void submit();
      }}
    >
      <label className="flex flex-col gap-1 t-meta">
        What is this file?
        <select value={kind} onChange={(e) => setKind(e.target.value as ReportKind)}>
          {REPORT_KINDS.map((k) => (
            <option key={k.value} value={k.value}>
              {k.label}
            </option>
          ))}
        </select>
      </label>
      {kind !== "EXPENSE" && (
        <label className="flex flex-col gap-1 t-meta">
          Marketplace
          <select value={marketplace} onChange={(e) => setMarketplace(e.target.value)}>
            {MARKETPLACES.map((m) => (
              <option key={m.value} value={m.value}>
                {m.label}
              </option>
            ))}
          </select>
        </label>
      )}
      <label className="flex flex-col gap-1 t-meta">
        File (.csv or .xlsx)
        <input type="file" accept=".csv,.xlsx" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
      </label>
      {error && <ErrorNotice message={error} />}
      <button type="submit" disabled={!file || busy}>
        {busy ? "Uploading…" : "Upload"}
      </button>
    </form>
  );
}
