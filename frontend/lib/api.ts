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
  affectedSkuCountUnavailable: string | null;
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

// --- PI agent test harness (backend/src/backend/api/v1/pi.py) -----------------------
// `niche_brief` CRUD and `pi.discover`/`pi.supplier_lookup` responses are hand-built
// camelCase dicts (`services/pi_actions.py`'s `pi_run_result_to_dict`/
// `supplier_lookup_result_to_dict`), matching CFO's convention above. `pi.report`
// (`pi_report_to_dict`) is the one deviation worth flagging: its `candidates`/
// `unavailable` payload is `json_safe(...)` over RAW DATABASE ROWS from
// `product_candidate`/`product_review_insight`/`supplier_lead` — those stay
// **snake_case**, unlike every other response on this page, because `json_safe` only
// converts UUID/datetime/Decimal values, never re-keys the dict. The types below name
// that split explicitly so it's never mistaken for an inconsistency to "fix".

/** `POST/PUT /pi/niche-briefs*`, `GET /pi/niche-briefs*` — raw `niche_brief` row via
 * `niche_brief_repo`, `json_safe`'d only (snake_case, see module note above). */
export type PiNicheBrief = {
  id: string;
  tenant_id: string;
  status: "DRAFT" | "READY" | "ARCHIVED";
  category_text: string | null;
  budget_paise: number | null;
  target_price_min_paise: number | null;
  target_price_max_paise: number | null;
  marketplaces: string[] | null;
  constraints: Record<string, unknown> | null;
  created_by: string;
  created_at: string;
  readied_at: string | null;
};

/** `POST /pi/discover` response — `pi_actions.pi_run_result_to_dict`, camelCase. */
export type PiRunResult = {
  runId: string;
  agentRunId: string;
  status: string;
  candidateIds: string[];
  shortlistedCandidateIds: string[];
  partialReason: string | null;
  failedReason: string | null;
};

/** One `score_explanation.signals[]` entry — `discovery/ranking.py`'s `SignalContribution`
 * / `discovery/shortlist_scoring.py`'s matching dict shape. Named every time, including
 * UNAVAILABLE signals with their reason (§0d) — never a bare number. */
export type PiSignalContribution = {
  signal: string;
  status: "AVAILABLE" | "UNAVAILABLE";
  points: number | string;
  max_points: number;
  reason: string;
};

export type PiScoreExplanation = {
  signals: PiSignalContribution[];
  summary: string;
};

export type PiWebPriceSignal =
  | { status: "UNAVAILABLE"; reason: string }
  | {
      status: "AVAILABLE";
      average_paise: number;
      range_low_paise: number;
      range_high_paise: number;
      sample_count: number;
      most_recent_mention: string | null;
      disclaimer: string;
    };

export type PiEngagementSignal =
  | { status: "UNAVAILABLE"; reason: string }
  | { status: "AVAILABLE"; video_count: number; view_count: number | null; comment_count: number | null; source: string };

export type PiDemandSignal = { status: "UNAVAILABLE"; reason: string };

/** Raw `product_candidate` row (`product_candidate_repo`), snake_case — see module note.
 * `opportunity_label` is always the fixed `'CANDIDATE_OPPORTUNITY'` string server-side
 * (§0a) — the UI must never render any other word ("trending"/"bestseller") for it. */
export type PiCandidate = {
  id: string;
  tenant_id: string;
  run_id: string;
  candidate_title: string;
  title_length: number | null;
  title_structure: Record<string, unknown> | null;
  keyword_themes: Record<string, unknown> | null;
  observed_category: string | null;
  category_confidence: string | null;
  image_url: string | null;
  image_source_url: string | null;
  demand_signal: PiDemandSignal | null;
  engagement_signal: PiEngagementSignal | null;
  web_price_signal: PiWebPriceSignal | null;
  source_diversity: number;
  proxy_score: string | null;
  proxy_state: "COMPUTED" | "UNAVAILABLE";
  proxy_basis: Record<string, unknown>;
  score_explanation: PiScoreExplanation;
  opportunity_label: "CANDIDATE_OPPORTUNITY";
  candidate_marketplaces: string[] | null;
  source_urls: { url: string; fetched_at: string }[];
  capture_status: string;
  confidence: string;
  /** Added 2026-10-01 — `estimate_product_feasibility` wiring (PI build plan §6.7). A
   * price/fee-spread range from Brain 1, never a margin claim while `feasibility_cogs_basis`
   * is "UNKNOWN" (always true today — no supplier-quote mechanism exists in PI yet). */
  feasibility_status: "COMPUTED" | "UNAVAILABLE";
  feasibility_estimate_ref: string | null;
  feasibility_low_paise: number | null;
  feasibility_high_paise: number | null;
  feasibility_cogs_basis: "STATED" | "UNKNOWN" | null;
  feasibility_assumptions: string[] | null;
  feasibility_unavailable_reason: string | null;
};

/** Raw `product_review_insight` row (`product_review_insight_repo`), snake_case.
 * `insight_source_type` is required precisely so this is never presented as a bare
 * "review" — always render it qualified ("viewer commentary" / "web commentary", §0b). */
export type PiReviewInsight = {
  id: string;
  tenant_id: string;
  candidate_id: string;
  insight_source_type: "YOUTUBE_COMMENTARY" | "WEB_EDITORIAL";
  sentiment_split: Record<string, unknown> | null;
  rating_distribution: Record<string, unknown> | null;
  complaint_themes: Record<string, number> | null;
  positive_themes: Record<string, number> | null;
  summarised_patterns: Record<string, unknown> | null;
  reviews_considered: number | null;
  confidence: string;
  derivation_method: string;
  insight_state: string;
  degraded_reason: string | null;
  source_url: string;
  fetched_at: string;
  derived_at: string;
};

/** Raw `supplier_lead` row (`supplier_lead_repo`), snake_case. There is no top-level
 * `moq` column — MOQ (when known) lives inside `contact.moq` as
 * `{unit_price_paise, quantity}`; render "MOQ not published — contact supplier to
 * confirm" whenever `contact?.moq` is absent, per the plan. */
export type PiSupplierLead = {
  id: string;
  tenant_id: string;
  run_id: string;
  candidate_id: string | null;
  supplier_name: string;
  source: "GOOGLE_PLACES" | "TAVILY" | "INDIAMART_LOOKUP";
  contact: { phone?: string; website?: string; moq?: { unit_price_paise: number; quantity: number } } | null;
  locality: string | null;
  distance_km: string | null;
  category_match: string | null;
  source_url: string | null;
  fetched_at: string;
};

/** `POST /pi/supplier-lookup` response — `pi_actions.supplier_lookup_result_to_dict`,
 * camelCase, one entry per requested candidate. */
export type PiSupplierLookupResult = {
  candidateId: string;
  leadIds: string[];
  degradedReason: string | null;
};

export type PiSupplierLookupResponse = { agentRunId: string; results: PiSupplierLookupResult[] };

/** One `GET /pi/report/{run_id}` candidate entry — `direct_path/pi_report.py`'s
 * `render_report`, `json_safe`'d verbatim (snake_case keys inside `candidate`/
 * `review_insights`/`supplier_leads`, camelCase only for the two Stage-4 fields that are
 * this module's own dict literals... actually those are also snake_case, see below). */
export type PiReportCandidateEntry = {
  candidate: PiCandidate;
  review_insights: PiReviewInsight[];
  supplier_leads: PiSupplierLead[];
  final_score: string | null;
  final_score_state: "COMPUTED" | "UNAVAILABLE";
  final_score_explanation: PiScoreExplanation | null;
};

/** `GET /pi/report/{run_id}` — `pi_actions.pi_report_to_dict`. Top level (`runId`? — no:
 * `runId`→`run_id` is NOT camelCased here either, `pi_report_to_dict` builds this dict by
 * hand but reuses `json_safe` for the nested rows only; the hand-built keys themselves
 * (`runId`, `status`, `candidates`, `unavailable`) ARE camelCase — only the nested row
 * contents inside `candidates[]` stay snake_case). */
export type PiReport = {
  runId: string;
  status: string;
  candidates: PiReportCandidateEntry[];
  unavailable: { field: string; reason: string }[];
};
