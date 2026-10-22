import { API_BASE, ApiError } from "@/lib/api";

/** Ingestion job contracts (backend/src/backend/services/cfo_ingestion.py `job_view`). Row counts are whole numbers shown as they come; nothing here formats money. */
export const ACTIVE_STATES = ["QUEUED", "PROFILING", "AWAITING_MAPPING_CONFIRMATION", "PARSING", "VALIDATING", "COMMITTING"] as const;
export const TERMINAL_STATES = ["DONE", "FAILED", "CANCELLED"] as const;
export type JobStatus = (typeof ACTIVE_STATES)[number] | (typeof TERMINAL_STATES)[number];

export type QualityReport = {
  marketplace?: string;
  rows?: Record<string, number>;
  findings_by_rule?: Record<string, number>;
  needs_seller?: string[];
  confidence?: string;
};

export type JobView = {
  jobId: string;
  reportFileId: string;
  status: JobStatus;
  reportKind: string;
  adapterId: string | null;
  mappingId: string | null;
  progressRows: number;
  totalRowsEstimate: number | null;
  errorCode: string | null;
  errorDetail: string | null;
  outcome: Record<string, unknown> | null;
  attempt: number;
  createdAt: string | null;
  startedAt: string | null;
  finishedAt: string | null;
  heartbeatAt: string | null;
  qualityReport?: QualityReport;
};

export const isActive = (s: JobStatus): boolean => (ACTIVE_STATES as readonly string[]).includes(s);

export const STATUS_TEXT: Record<JobStatus, string> = {
  QUEUED: "Waiting to start",
  PROFILING: "Looking at your file",
  AWAITING_MAPPING_CONFIRMATION: "Waiting for you to confirm the columns",
  PARSING: "Reading rows",
  VALIDATING: "Checking rows",
  COMMITTING: "Saving",
  DONE: "Finished",
  FAILED: "Could not be read",
  CANCELLED: "Cancelled",
};

export const REPORT_KINDS = [
  { value: "SALES", label: "Sales / orders" },
  { value: "SETTLEMENT", label: "Settlement / payments" },
  { value: "ADVERTISING", label: "Advertising" },
  { value: "EXPENSE", label: "Business expenses" },
] as const;
export type ReportKind = (typeof REPORT_KINDS)[number]["value"];

/** An expense file belongs to the business, so its marketplace is fixed; every other kind belongs to one marketplace. */
export const marketplaceFor = (kind: ReportKind, chosen: string): string => (kind === "EXPENSE" ? "ALL" : chosen);

export async function uploadReport(token: string | null, file: File, p: { marketplace: string; kind: ReportKind; adapterId?: string }): Promise<JobView> {
  const q = new URLSearchParams({ marketplace: marketplaceFor(p.kind, p.marketplace), report_kind: p.kind });
  if (p.adapterId) q.set("adapter_id", p.adapterId);
  const body = new FormData();
  body.append("file", file);
  const res = await fetch(`${API_BASE}/api/v1/cfo/uploads?${q.toString()}`, { method: "POST", headers: token ? { Authorization: `Bearer ${token}` } : undefined, body });
  const json: unknown = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(res.status, (json as { detail?: unknown } | null)?.detail ?? res.statusText);
  return json as JobView;
}

/** Poll interval: 1 s while the job is moving, backing off to 5 s once it has been quiet for a while. A pure function of how many polls saw no progress. */
export const pollDelayMs = (quietPolls: number): number => (quietPolls < 5 ? 1000 : quietPolls < 15 ? 2500 : 5000);
