"use client";

import { useAuth } from "@clerk/nextjs";
import { useState } from "react";
import { ErrorNotice } from "@/components/ui/ErrorNotice";
import { apiFetch } from "@/lib/api";
import { friendlyApiError } from "@/lib/apiErrors";
import { STATUS_TEXT, isActive, type JobView } from "@/lib/cfoV2/ingest";
import { useJob } from "@/lib/cfoV2/useJob";
import { HeldRows } from "./HeldRows";
import { QualityReport } from "./QualityReport";

/** One upload's live status: what stage it is in, rows read (a determinate bar only when the server knows the total), a cancel while it is active, the plain reason if
 * it failed, and the quality report once it is done. Progress never moves backwards. */
export function JobProgress({ jobId, initial, onConfirmMapping, onRetry, onManualMap }: { jobId: string; initial?: JobView | null; onConfirmMapping?: (job: JobView) => void; onRetry?: () => void; onManualMap?: (job: JobView) => void }) {
  const { getToken } = useAuth();
  const { job, error, status, reload } = useJob(jobId, initial);
  const [cancelError, setCancelError] = useState<string | null>(null);

  if (status === "loading" || !job) {
    return error ? <ErrorNotice message={error} onRetry={reload} /> : <p role="status">Checking on your upload…</p>;
  }

  const cancel = async () => {
    setCancelError(null);
    try {
      await apiFetch(`/api/v1/cfo/jobs/${job.jobId}/cancel`, await getToken(), { method: "POST" });
      reload();
    } catch (e) {
      setCancelError(friendlyApiError(e, "Could not cancel this upload"));
    }
  };

  const active = isActive(job.status);
  return (
    <section aria-label="Upload progress" className="flex flex-col gap-3">
      <div role="status" aria-live="polite" className="t-body">
        {STATUS_TEXT[job.status]}
        {job.progressRows > 0 && ` · ${job.progressRows} rows read`}
      </div>
      {active &&
        job.status !== "AWAITING_MAPPING_CONFIRMATION" &&
        (job.totalRowsEstimate ? (
          <progress aria-label="Rows read" value={job.progressRows} max={job.totalRowsEstimate} className="w-full" />
        ) : (
          <progress aria-label="Reading your file" className="w-full" />
        ))}
      {job.status === "AWAITING_MAPPING_CONFIRMATION" && (
        <div className="flex flex-col gap-2">
          <p className="t-body">Metrion proposed what each column means. Nothing is saved until you confirm it.</p>
          {onConfirmMapping && (
            <button type="button" onClick={() => onConfirmMapping(job)}>
              Review the columns
            </button>
          )}
        </div>
      )}
      {error && <ErrorNotice message={error} onRetry={reload} />}
      {cancelError && <ErrorNotice message={cancelError} />}
      {active && (
        <button type="button" onClick={cancel}>
          Cancel upload
        </button>
      )}
      {job.status === "FAILED" && (
        <div className="flex flex-col gap-2">
          <ErrorNotice message={job.errorDetail ?? "This file could not be read."} />
          {onManualMap && (job.errorCode === "MAPPING_PROPOSAL_FAILED" || job.errorCode === "NO_MATCHING_FORMAT") && (
            <button type="button" onClick={() => onManualMap(job)}>
              Map the columns yourself
            </button>
          )}
          {onRetry && (
            <button type="button" onClick={onRetry}>
              Upload again
            </button>
          )}
        </div>
      )}
      {job.status === "CANCELLED" && <p className="t-body">Cancelled. Nothing from this file was saved.</p>}
      {job.status === "DONE" && job.qualityReport && <QualityReport report={job.qualityReport} />}
      {job.status === "DONE" && (job.qualityReport?.rows?.held_total ?? 0) > 0 && <HeldRows jobId={job.jobId} />}
    </section>
  );
}
