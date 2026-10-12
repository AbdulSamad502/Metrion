"use client";

import { useCallback, useEffect, useState } from "react";
import { categoryLabel, ImportViewer } from "@/components/cfo/ImportViewer";
import { Card, CardCta } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorNotice } from "@/components/ui/ErrorNotice";
import { LoadingState } from "@/components/ui/LoadingState";
import { Section } from "@/components/ui/Section";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { apiFetch, type ImportSummary, type UploadOutcome } from "@/lib/api";
import { friendlyApiError } from "@/lib/apiErrors";

function statusBadge(s: ImportSummary) {
  if (s.status === "VALIDATED") return <StatusBadge tone="accent" dot>Ingested</StatusBadge>;
  if (s.status === "FAILED" || s.status === "MISMATCHED") return <StatusBadge tone="negative" dot>{s.status.toLowerCase()}</StatusBadge>;
  if (s.status === "SUPERSEDED") return <StatusBadge tone="neutral" dot>Superseded</StatusBadge>;
  if (s.status === null) return <StatusBadge tone="warning" dot>No ingestion run</StatusBadge>;
  return <StatusBadge tone="warning" dot>{s.status.toLowerCase()}</StatusBadge>;
}

/** Import history: every report this workspace has uploaded, with what Metrion actually persisted.
 * Each import is a real control — it opens the viewer for that report. A byte-identical re-upload is
 * not a new import: it is surfaced here as "Duplicate — existing import detected" and opens the
 * existing report. */
export function ImportHistory({
  getToken,
  refreshTick,
  lastUpload,
}: {
  getToken: () => Promise<string | null>;
  refreshTick: number;
  lastUpload: UploadOutcome | null;
}) {
  const [imports, setImports] = useState<ImportSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [viewing, setViewing] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      setImports(await apiFetch<ImportSummary[]>("/api/v1/cfo/imports", await getToken()));
    } catch (e) {
      setError(friendlyApiError(e, "Could not reach the backend"));
    }
  }, [getToken]);

  useEffect(() => {
    (async () => {
      await load();
    })();
  }, [load, refreshTick]);

  return (
    <Section title="Import history" hint="What Metrion saved from each uploaded file" panel={false}>
      {lastUpload?.duplicate && (
        <div className="mb-4">
          <Card variant="elevated" onClick={() => setViewing(lastUpload.reportFileId)} ariaLabel={`View existing import of ${lastUpload.filename}`}>
            <div className="flex flex-wrap items-center gap-3 p-4">
              <StatusBadge tone="warning" dot>Duplicate</StatusBadge>
              <div className="min-w-0 flex-1">
                <div className="t-card-title break-all" style={{ color: "var(--text-1)" }}>
                  {lastUpload.filename}
                </div>
                <div className="t-meta" style={{ color: "var(--text-5)" }}>
                  Existing import detected — this exact file was already uploaded, so nothing was ingested again.
                </div>
              </div>
              <CardCta>View existing</CardCta>
            </div>
          </Card>
        </div>
      )}

      {error ? (
        <ErrorNotice message={error} onRetry={() => void load()} />
      ) : imports === null ? (
        <LoadingState lines={4} label="Loading import history" />
      ) : imports.length === 0 ? (
        <div className="mt-panel">
          <EmptyState
            icon="dot"
            title="No imports yet"
            description="Upload a marketplace report above. Each file you upload appears here with how many rows were read, accepted and saved."
          />
        </div>
      ) : (
        <ul className="m-0 grid list-none grid-cols-1 gap-3 p-0 xl:grid-cols-2">
          {imports.map((i) => {
            const c = i.counts;
            return (
              <li key={i.reportFileId}>
                <Card
                  onClick={() => setViewing(i.reportFileId)}
                  selected={viewing === i.reportFileId}
                  className="h-full"
                  ariaLabel={`View import ${i.filename}`}
                >
                  <div className="flex h-full flex-col gap-3 p-4">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="mt-eyebrow">
                          {i.marketplace} {categoryLabel(i.reportCategory)}
                        </div>
                        <div className="t-card-title mt-1 break-all" style={{ color: "var(--text-1)" }}>
                          {i.filename}
                        </div>
                        <div className="t-meta mt-0.5" style={{ color: "var(--text-5)" }}>
                          {i.adapter ?? "No adapter run"} · {new Date(i.uploadedAt).toLocaleDateString()}
                        </div>
                      </div>
                      {statusBadge(i)}
                    </div>
                    <div className="mt-auto flex items-end justify-between gap-3">
                      <div>
                        <div className="t-metric" style={{ color: "var(--text-1)" }}>
                          {c.accepted ?? "—"}
                          <span className="t-body-sm" style={{ color: "var(--text-5)", fontWeight: 500, letterSpacing: 0 }}>
                            {" "}
                            / {c.read ?? "—"} accepted
                          </span>
                        </div>
                        <div className="t-meta" style={{ color: c.rejected ? "var(--warning)" : "var(--text-5)" }}>
                          {c.rejected ?? "—"} rejected · {c.duplicate ?? "—"} duplicates
                        </div>
                      </div>
                      <CardCta>View</CardCta>
                    </div>
                  </div>
                </Card>
              </li>
            );
          })}
        </ul>
      )}

      <ImportViewer reportFileId={viewing} onClose={() => setViewing(null)} getToken={getToken} />
    </Section>
  );
}
