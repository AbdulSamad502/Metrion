/** Thin fetch wrapper for the FastAPI backend. Every call attaches the Clerk session
 * token as a bearer token — the backend's `require_auth()` (auth.md §7.1) verifies it
 * server-side; nothing here is a security boundary of its own. */

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: unknown,
  ) {
    super(typeof detail === "string" ? detail : `Request failed with ${status}`);
  }
}

export async function apiFetch<T>(
  path: string,
  token: string | null,
  init?: RequestInit,
): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      ...(init?.headers ?? {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      "Content-Type": "application/json",
    },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new ApiError(res.status, body?.detail ?? res.statusText);
  }
  return res.json() as Promise<T>;
}

/** Like apiFetch, but for multipart/form-data (file uploads) — apiFetch always forces a
 * JSON Content-Type, which breaks a multipart boundary header. Used only by the evidence
 * upload endpoint (Step 4). */
export async function apiFetchForm<T>(path: string, token: string | null, formData: FormData): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    body: formData,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new ApiError(res.status, body?.detail ?? res.statusText);
  }
  return res.json() as Promise<T>;
}

export type SessionResponse = {
  appUserId: string;
  emailVerified: boolean;
  tenantId: string | null;
  membershipStatus: string | null;
  role: string | null;
  onboardingState: "PENDING_EMAIL_VERIFICATION" | "PENDING_ONBOARDING" | "ACTIVE";
};

// --- Step 4: CEO Hub / Competitor Intelligence ---------------------------------------

export type AgentStatus = { id: string; name: string; status: "CONNECTED" | "NOT_CONNECTED" };

export type CompetitorUrl = {
  id: string;
  marketplace: string;
  url: string;
  label: string | null;
  linkedSku: string | null;
  status: string;
  tags: string[];
  createdAt: string;
};

export type CiSummary = {
  trackedCompetitors: number;
  lastResearchAt: string | null;
  recentPriceEvents7d: number;
  pendingManualEntry: number;
  staleCompetitors: number;
};

// --- Step 5: snapshot history, price/listing change detection, handoff, digest -------

export type SnapshotHistoryItem = {
  id: string;
  capturedAt: string;
  isStale: boolean;
  captureStatus: string;
  confidence: string;
  title: string | null;
  listedPricePaise: number | null;
  visibleDiscountPaise: number | null;
  availability: string | null;
  variantKey: string | null;
};

export type PriceEventItem = {
  id: string;
  deltaPaise: number;
  deltaPct: string;
  direction: string;
  availabilityChange: string | null;
  thresholdBreached: boolean;
  alertEligible: boolean;
  createdAt: string;
};

export type ListingDiffResult =
  | { available: false; reason: string }
  | {
      available: true;
      priorSnapshotId: string;
      currentSnapshotId: string;
      changedFields: { fieldName: string; priorValue: unknown; currentValue: unknown }[];
    };

export type CiHandoffPayload = {
  competitorUrlId: string;
  marketplace: string;
  label: string | null;
  tags: string[];
  snapshotId: string;
  capturedAt: string;
  isStale: boolean;
  captureStatus: string;
  confidence: string;
  listedPricePaise: number | null;
  availability: string | null;
  sourceUrl: string;
};

export type DigestEntry = {
  competitorUrlId: string;
  label: string | null;
  priceIncreaseCount: number;
  priceDecreaseCount: number;
  availabilityChangeCount: number;
  thresholdBreachedCount: number;
};

export type DigestPreview = {
  since: string;
  until: string;
  competitorsWithActivity: number;
  entries: DigestEntry[];
};

export type DigestSubscription = {
  frequency: "NONE" | "DAILY" | "WEEKLY";
  channel: string;
  enabled: boolean;
  lastSentAt: string | null;
  isDefault: boolean;
};

export type ResearchNowResult = {
  ceoAgentRunId: string;
  ci: {
    agentRunId: string;
    ciCaptureRunId: string;
    researchSessionId: string;
    status: string;
    snapshotId: string | null;
    captureStatus: string | null;
    priceEventId: string | null;
  };
};

export type RunLinkage = {
  parent: { id: string; agentId: string; triggerType: string; triggerRef: string; parentRunId: string | null; status: string };
  children: { id: string; agentId: string; triggerType: string; triggerRef: string; status: string }[];
};
