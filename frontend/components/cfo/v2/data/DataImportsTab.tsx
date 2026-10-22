"use client";

import { useState } from "react";
import { ImportHistory } from "@/components/cfo/ImportHistory";
import type { JobView } from "@/lib/cfoV2/ingest";
import { JobProgress } from "./JobProgress";
import { ManualMapping } from "./ManualMapping";
import { MappingReview } from "./MappingReview";
import { UploadPanel } from "./UploadPanel";

/** Data & Imports (D1): upload, follow the job live, read the quality report. The import history below is the existing, real component. */
export function DataImportsTab({ getToken }: { getToken: () => Promise<string | null> }) {
  const [job, setJob] = useState<JobView | null>(null);
  const [tick, setTick] = useState(0);
  const [reviewing, setReviewing] = useState(false);
  const [manual, setManual] = useState(false);
  return (
    <div className="flex flex-col gap-7">
      {job && manual ? (
        <ManualMapping
          jobId={job.jobId}
          onProposed={(next) => {
            setManual(false);
            setJob(next);
            setReviewing(true);
          }}
        />
      ) : job && reviewing ? (
        <MappingReview jobId={job.jobId} onConfirmed={() => setReviewing(false)} />
      ) : job ? (
        <JobProgress
          key={job.jobId}
          jobId={job.jobId}
          initial={job}
          onConfirmMapping={() => setReviewing(true)}
          onManualMap={() => setManual(true)}
          onRetry={() => {
            setJob(null);
            setReviewing(false);
            setManual(false);
            setTick((n) => n + 1);
          }}
        />
      ) : (
        <UploadPanel
          onStarted={(j) => {
            setJob(j);
            setTick((n) => n + 1);
          }}
        />
      )}
      <ImportHistory getToken={getToken} refreshTick={tick} lastUpload={null} />
    </div>
  );
}
