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

// --- Checkpoint 1: price-positioning / repricing scenario ----------------------------

export type MetricResult = {
  engineResultRef: string;
  metricCode: string;
  valuePaise: number | null;
  isAvailable: boolean;
  confidence: string;
  calculationBasis: string | null;
  unavailableReason: string | null;
  asOfDate: string | null;
};

export type PriceScenarioResult = {
  pricePositioning: MetricResult[];
  repricingScenario: MetricResult | null;
};

export type RunLinkage = {
  parent: { id: string; agentId: string; triggerType: string; triggerRef: string; parentRunId: string | null; status: string };
  children: { id: string; agentId: string; triggerType: string; triggerRef: string; status: string }[];
};

// --- Checkpoint 2: seller-product profile (§5.5, C31) --------------------------------

/** Matches `backend/api/v1/ci.py::_seller_product_to_dict` exactly. `fieldSource` keys are
 * the plain (snake_case) field names as produced by `merge_seller_product` — "title",
 * "category", "price_paise", "attributes", "keywords", "fulfillment_type" — not camelCased,
 * because the backend serializes that map's keys verbatim. `reviewCount`/`rating` are always
 * null and never appear in `fieldSource` (C31, §5.5.2) — out of this form's scope. */
export type SellerProduct = {
  productId: string;
  title: string | null;
  category: string | null;
  pricePaise: number | null;
  attributes: { key: string; value: string }[] | null;
  keywords: string[] | null;
  fulfillmentType: string | null;
  reviewCount: number | null;
  rating: number | null;
  lastUpdated: string | null;
  fieldSource: Record<string, "CANONICAL_DERIVED" | "SELLER_ENTERED">;
};

/** Checkpoint 5 — matches `backend/api/v1/ci.py::post_discovery_run`'s response exactly. */
export type DiscoveryRunStart = {
  discoveryRunId: string;
  status: string;
  rawCandidateCount: number;
  analyzedCandidateCount: number;
  recommendedCandidateIds: string[];
  uncertainCandidateIds: string[];
  partialReason: string | null;
  failedReason: string | null;
};

/** One candidate's relevance breakdown — §6.14.3 requires the band never render without its
 * full per-axis breakdown, so `breakdownLine` (server-built) is always present alongside the
 * raw per-axis maps for anyone who wants to render axes individually. */
export type CandidateRelevance = {
  band: "HIGH" | "MEDIUM" | "LOW";
  totalScore: number;
  isProvisional: boolean;
  axisScores: Record<string, number>;
  axisStates: Record<string, "KNOWN" | "UNKNOWN" | "CONFLICTED">;
  axisRationale: Record<string, string | null>;
  breakdownLine: string;
};

/** Matches `backend/api/v1/ci.py::_candidate_to_dict` exactly. `identityMatch`/`relevance`/
 * `evidenceStatus` are three separately-visible attributes (§6.14.5) — never render them as
 * one collapsed score. */
export type Candidate = {
  id: string;
  candidateUrl: string;
  marketplace: string | null;
  origin: "DISCOVERED" | "MANUAL_URL" | "PROMOTED_BY_SELLER";
  tier: "RAW" | "ANALYZED" | "RECOMMENDED";
  identityMatch: "EXACT_MATCH" | "LIKELY_VARIANT" | "UNCERTAIN" | "NOT_A_MATCH" | null;
  identityMatchBasis: Record<string, unknown> | null;
  sellerDecision: "NONE" | "APPROVED" | "REJECTED";
  evidenceStatus: "AWAITING_EVIDENCE" | "EVIDENCE_BACKED";
  competitorUrlId: string | null;
  relevance: CandidateRelevance | null;
};

/** Checkpoint 6 — matches `backend/api/v1/ci.py::get_market_overview`'s response exactly.
 * `rows` are real `MetricResult`s from `compute_price_band` (deterministic-engine.md
 * §5.15.1) — this type never carries a locally-computed quartile/fence/outlier value. */
export type MarketOverview = {
  productId: string;
  trackedCompetitorCount: number;
  minCompetitorsRequired: number;
  rows: MetricResult[];
};

/** Checkpoint 6 — matches `backend/api/v1/ci.py::get_competitor_comparison`'s response
 * exactly (competitor-intelligence-agent.md §6.19's four-bucket framing). */
export type ComparisonEntry = {
  field: string;
  state: "KNOWN" | "UNKNOWN";
  detail: string;
  caveat: string | null;
};

export type ComparisonResult =
  | { available: false; reason: string }
  | {
      available: true;
      competitorUrlId: string;
      snapshotId: string;
      listingGaps: ComparisonEntry[];
      productStrengths: ComparisonEntry[];
      productWeaknesses: ComparisonEntry[];
      differentiationOpportunities: ComparisonEntry[];
    };

/** Matches `backend/api/v1/ci.py::get_discovery_run`'s response exactly — the three §6.15
 * visibility tiers (Recommended / Other analyzed / Unanalyzed), nothing hidden. */
export type DiscoveryRunDetail = {
  discoveryRunId: string;
  status: string;
  partialReason: string | null;
  failedReason: string | null;
  rawCandidateCount: number;
  analyzedCandidateCount: number;
  recommended: Candidate[];
  otherAnalyzed: Candidate[];
  unanalyzed: Candidate[];
};
