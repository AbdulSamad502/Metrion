/** Thin fetch wrapper for the FastAPI backend. Every call attaches the Clerk session
 * token as a bearer token — the backend's `require_auth()` (auth.md §7.1) verifies it
 * server-side; nothing here is a security boundary of its own. */

export const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

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
  /** Has the first-run business-details step been finished (business-profile.md D4)? Only `false` sends a member to it. */
  profileComplete?: boolean;
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

// --- CFO agent test harness (backend/src/backend/api/v1/cfo.py) ---------------------
// Every type below matches that file's hand-built response dicts exactly (camelCase
// keys) — request bodies sent to these routes stay snake_case, matching the Pydantic
// models that file defines (never camelCased on the way out).

/** Feature 1 — `PUT /cfo/expenses` response. */
export type ManualAdjustmentIdResponse = { manualAdjustmentId: string };

/** One row from `GET /cfo/expenses` (`_expense_entry_to_dict`). */
export type ExpenseEntry = {
  manualAdjustmentId: string;
  category: string;
  amountPaise: number;
  targetType: string;
  targetRef: string;
  createdAt: string;
  createdBy: string;
  reason: string | null;
};

export type ExpenseListResponse = { entries: ExpenseEntry[]; totalPaise: number };

/** `GET /cfo/expenses/budget-status` — `noBudgetSet: true` is a real, distinguished
 * outcome (never a fabricated zero ceiling); `budgetPaise`/`remainingPaise` are `null`
 * only in that case. */
export type BudgetStatus = {
  category: string;
  periodStart: string;
  periodEnd: string;
  spentPaise: number;
  noBudgetSet: boolean;
  budgetPaise: number | null;
  remainingPaise: number | null;
  exceeded: boolean;
  manualAdjustmentId: string | null;
};

/** `POST /cfo/gst/analyze-lines` — one row per line, `_gst_line_result_to_dict`. Never a
 * period total (see that route's own docstring). */
export type GstLineResult = {
  lineRef: string;
  normalizedExclusivePaise: number | null;
  isAvailable: boolean;
  unavailableReason: string | null;
  ratePlausibilityMatched: boolean | null;
  ratePlausibilitySeverity: string | null;
  disclaimer: string;
};

export type AnalyzeGstLinesResponse = { lines: GstLineResult[] };

/** `POST /cfo/pricing`, `/landed-cost`, `/suppliers/rank`, `/funding-readiness`,
 * `/batch-size`, `/gst/period-summary` all reuse this exact shape
 * (`_pricing_metric_result_to_dict`) — byte-identical to `MetricResult` above, kept as a
 * separate alias only so call sites reading this file can see which routes share it. */
export type PricingMetricResult = MetricResult;

/** `POST /cfo/cash-reconciliation` (`post_cash_reconciliation`): cash really received from settlement rows; expected cash, variance and TDS are
 * not available from any adapter today and come back with `isAvailable: false` and a reason. */
export type CashReconciliationResponse = {
  cashReceived: PricingMetricResult;
  cashExpected: PricingMetricResult;
  cashVariance: PricingMetricResult;
  tcsCollected: PricingMetricResult;
  tdsDeducted: PricingMetricResult;
  settledWithinLagCount: number;
  unsettledBeyondLagCount: number;
  datesMissingCount: number;
};

/** `POST /cfo/pnl` — every one of the six is this shape, `_period_pnl_metric_result_to_dict`
 * (`MetricResult` + `valueFraction`, populated INSTEAD OF `valuePaise` for percentage
 * metrics like `CONTRIBUTION_MARGIN_PCT`, never alongside it). */
export type PeriodPnlMetricResult = MetricResult & { valueFraction: string | null };

export type PeriodPnlResponse = {
  nrr: PeriodPnlMetricResult;
  contributionProfit: PeriodPnlMetricResult;
  marginPct: PeriodPnlMetricResult;
  feeRatioPct: PeriodPnlMetricResult;
  returnRatePct: PeriodPnlMetricResult;
  marketplaceFeeFlags: string[];
  dataRequestId: string | null;
};

export type GstPeriodSummaryResponse = { results: MetricResult[]; disclaimer: string };

export type PeriodComparisonResponse = {
  delta: MetricResult | null;
  narration: string | null;
  dataRequestId: string | null;
};

export type LandedCostResponse = { result: MetricResult | null; dataRequestId: string | null };

export type RankedSupplierQuote = {
  result: MetricResult;
  supplierName: string | null;
  reliabilityNote: string | null;
  paymentTerms: string | null;
  leadTimeDays: number | null;
  moq: number | null;
};

export type QuarantinedSupplierQuote = {
  adjustmentId: string;
  supplierName: string | null;
  reason: string;
};

export type SupplierRankingResponse = {
  ranked: RankedSupplierQuote[];
  quarantined: QuarantinedSupplierQuote[];
  isSingleQuote: boolean;
  dataRequestId: string | null;
};

export type FundingReadinessGap = { kind: string; period: string | null; reason: string };
export type DeferredSection = { name: string; reason: string; blockedOn: string | null };

export type FundingReadinessResponse = {
  contributionProfitHistory: MetricResult[];
  trend: MetricResult[];
  gaps: FundingReadinessGap[];
  deferredSections: DeferredSection[];
  dataRequestId: string | null;
};

export type BatchSizeResponse = {
  result: MetricResult | null;
  landedCostResult: MetricResult | null;
  velocityStatus: string;
  observedUnitsSold: number | null;
  velocityUnavailableReason: string | null;
  referenceQuantity: number | null;
  referenceQuantityBasis: string | null;
  referenceQuantityCaveatApplies: boolean;
  referenceQuantityCaveat: string | null;
  leadTimeDays: number | null;
  moq: number | null;
  dataRequestId: string | null;
};

export type LeakFinding = {
  leakFindingId: string;
  leakCategory: string;
  severity: string;
  windowStatus: string;
  amountPaise: number;
  marketplace: string;
  engineResultRef: string;
};

export type ReconcileResponse = {
  reconciliationRunId: string;
  findings: LeakFinding[];
  matchCount: number;
  exceptionCount: number;
  ambiguousMatchCount: number;
  datesMissingCount: number;
};

export type CfoPreviewFinding = LeakFinding & { sku: string | null };

export type CfoPreviewResponse = {
  headlineTotalPaise: number | null;
  headlineEngineResultRef: string | null;
  affectedSkuCount: number | null;
  /** The backend sends a boolean (`CfoPreviewOutcome.affected_sku_count_unavailable`): true means findings exist but none says which SKU it belongs to. It is never text. */
  affectedSkuCountUnavailable: boolean;
  revealedFinding: CfoPreviewFinding | null;
  lockedFindingsCount: number;
};

/** `POST /cfo/anomaly-check` — `_anomaly_flag_to_dict`. */
export type AnomalyFlag = {
  id: string;
  metric: string;
  targetRef: string;
  period: string;
  method: string;
  decoratesEngineResultRef: string;
  sourceEngineResultRefs: string[];
  score: string;
  fired: boolean;
  severity: string | null;
  dataConfidence: string;
  seriesLength: number;
  minSeriesLengthRequired: number;
  configVersion: string;
  formulaVersion: string;
  asOfDate: string;
  computedAt: string;
};

export type AnomalyMethodOutcome = {
  method: string;
  flag: AnomalyFlag | null;
  insufficientHistory: {
    metric: string;
    method: string;
    targetRef: string;
    seriesLength: number;
    minSeriesLengthRequired: number;
    reason: string;
  } | null;
  zeroVariance: { metric: string; method: string; targetRef: string; seriesLength: number; reason: string } | null;
  configurationGap: { metric: string; method: string; targetRef: string; reason: string } | null;
};

export type AnomalyCheckResponse = {
  targetRef: string;
  metric: string;
  seriesLength: number;
  methods: AnomalyMethodOutcome[];
  narration?: string;
};

/** `POST /cfo/gst-lookup` — `_gst_lookup_result_to_dict` / `_gst_lookup_no_match_to_dict`. */
export type GstLookupAlternative = { ratePct: string | null; hsn: string | null; category: string | null };

export type GstLookupResult = {
  id: string;
  queryText: string;
  sku: string | null;
  queryHsn: string | null;
  likelyRatePct: string | null;
  likelyHsn: string | null;
  likelyCategory: string | null;
  ambiguityNote: string | null;
  alternatives: GstLookupAlternative[];
  sourceUrl: string | null;
  sourceTitle: string | null;
  retrievedAt: string;
  status: string;
  disclaimer: string;
};

export type GstLookupNoMatch = { queryText: string; attemptedUrls: string[]; reason: string };

export type GstLookupResponse = {
  result: GstLookupResult | null;
  noMatch: GstLookupNoMatch | null;
  fromCache: boolean;
};

export type PricingCurveResponse = { curve: MetricResult[]; dataRequestId: string | null };

/** `GET /cfo/data-requests`. */
export type DataRequestItem = {
  id: string;
  requestedField: string;
  reason: string | null;
  blockingMetric: string | null;
  status: string;
  createdAt: string;
};

// --- Notifications feed: real alert sources only (no notification service exists) ---------
// `GET /ci/alerts?days=N` — Layer 1 observational alerts (competitor-intelligence-agent.md §6.17),
// `alerts/layer1.py::layer1_alert_to_dict`. NOTE: the backend stamps the price fact inside
// `handoff.validatedFact` with confidence "HIGH" even for a vision-extracted price (spec open
// question Q18) — the UI therefore never renders that confidence as "verified"; see
// `components/ui/EvidenceStateBadge.tsx`.

export type Layer1Alert = {
  priceEventId: string;
  competitorUrlId: string;
  competitorLabel: string;
  findingType: "PRICE_CHANGE" | "AVAILABILITY_CHANGE" | "LISTING_GAP" | "REVIEW_THEME" | "DIFFERENTIATION_OPPORTUNITY" | "MARKET_POSITION";
  direction: "INCREASE" | "DECREASE" | null;
  deltaPct: string | null;
  availabilityChange: string | null;
  thresholdBreached: boolean;
  message: string;
  createdAt: string;
  handoff: {
    findingId: string;
    findingType: string;
    validatedFact: { fact: string; confidence: string; capturedAt: string; isStale: boolean }[];
    evidenceRefs: string[];
    competitorRefs: string[];
    implication: string;
    suggestedAction: { targetAgent: string; suggestedQuestion: string } | null;
    createdAt: string;
    createdBy: string;
  };
};

export type Layer1AlertsResponse = { since: string; until: string; alerts: Layer1Alert[] };

// --- CFO import viewer (GET /cfo/imports, /cfo/imports/{id}) — persisted data only ----------

export type ImportCounts = {
  read: number | null;
  accepted: number | null;
  rejected: number | null;
  /** Accepted rows skipped as natural-key duplicates of an earlier import. */
  duplicate: number | null;
  /** Lines actually persisted for this import. */
  persisted: number;
};

export type ImportSummary = {
  reportFileId: string;
  ingestionRunId: string | null;
  filename: string;
  marketplace: string;
  reportCategory: string;
  adapter: string | null;
  adapterVersion: string | null;
  uploadedAt: string;
  status: string | null;
  counts: ImportCounts;
};

export type ImportComponent = {
  kind: string;
  code: string;
  side: string;
  amountPaise: number;
  taxAmountPaise: number | null;
  ratePct: string | null;
};

/** One persisted line. Sales lines carry `salesLineId`; settlement lines carry `settlementLineId`.
 * Every other field is a real persisted column and may be null. */
export type ImportRow = {
  salesLineId?: string;
  settlementLineId?: string;
  sourceRowNumber: number;
  confidence: string;
  currency: string;
  components: ImportComponent[];
  [field: string]: unknown;
};

export type ImportDetail = ImportSummary & {
  lineKind: "SALES_LINE" | "SETTLEMENT_LINE";
  rows: ImportRow[];
  pagination: { limit: number; offset: number; total: number };
  rejected: {
    count: number | null;
    diagnosticsPersisted: boolean;
    findingsTotal: number;
    findings: { ruleId: string; severity: string; message: string; sourceRowNumber: number | null }[];
  };
  originalCsv: { available: boolean; reason: string };
};

/** What `POST /cfo/ingest` returned, plus the filename the browser sent (the API does not echo it). */
export type UploadOutcome = { reportFileId: string; duplicate: boolean; filename: string };
