/** Typed READ client for the Product Intelligence showcase (/api/v1/pi/research*, docs/specs/ceo-pi-research-flow.md §5.2, §5.4).
 *
 * The PI page only shows research the CEO already ran and saved. Every function here is a `GET`, except pin/unpin, which flip a flag on an existing saved
 * report. There is nothing here that starts research, saves a brief or looks up suppliers (that is only ever done through the CEO chat), and nothing computes a
 * figure: every number is stored by the backend and rendered as it arrives. Money is integer paise, formatted without floats. */

import { apiFetch } from "@/lib/api";

export type GetToken = () => Promise<string | null>;
export type Marketplace = "AMAZON" | "FLIPKART" | "MEESHO";

export type PiBriefEcho = {
  category?: string | null;
  budgetPaise?: number | null;
  targetPriceMinPaise?: number | null;
  targetPriceMaxPaise?: number | null;
  marketplaces?: string[] | null;
};

export type PiHistoryItem = {
  runId: string;
  status: string;
  pinned: boolean;
  pinnedAt: string | null;
  completedAt: string | null;
  category: string | null;
  budgetPaise: number | null;
  targetPriceMinPaise: number | null;
  targetPriceMaxPaise: number | null;
  marketplaces: string[] | null;
  caseSaved: boolean;
  topProducts: { candidateId: string; title: string | null; finalScore: string | null }[];
};

/** A unit price the supplier's own page states: a published fact with its source, never a quote and never used by the CFO. */
export type PiPublishedPrice = { low_paise: number; high_paise: number; sample_count: number; unit: string; source_url: string | null; captured_at: string; disclaimer: string };

/** One CFO result the CEO attached to a product: a verified figure (display text resolved by the CEO from its engine reference) or a named gap. */
export type PiFinancial = {
  kind: "ENGINE" | "GAP";
  authoritative: boolean;
  leg_key: string;
  label: string;
  display: string | null;
  status: "COMPLETE" | "UNAVAILABLE";
  reason?: string;
  as_of?: string | null;
  note?: string | null;
};

export type PiSupplierLead = {
  id?: string;
  supplier_name: string;
  source: string; // GOOGLE_PLACES | TAVILY | INDIAMART_LOOKUP
  contact: { phone?: string | null; website?: string | null; moq?: unknown; published_price?: PiPublishedPrice | null } | null;
  locality: string | null;
  source_url: string | null;
  fetched_at?: string | null;
  evidence_fields?: string[];
};

export type PiReviewInsight = {
  insight_source_type: string; // YOUTUBE_COMMENTARY | WEB_EDITORIAL
  insight_state: string;
  sentiment_split: Record<string, string> | null;
  positive_themes: Record<string, number> | string[] | null;
  complaint_themes: Record<string, number> | string[] | null;
  reviews_considered: number | null;
};

export type PiCandidate = {
  id: string;
  candidate_title: string;
  observed_category: string | null;
  image_url: string | null;
  image_source_url: string | null;
  proxy_score: string | null;
  web_price_signal: { status: string; average_paise?: number; range_low_paise?: number; range_high_paise?: number; sample_count?: number; most_recent_mention?: string | null; disclaimer?: string } | null;
  candidate_marketplaces: string[] | null;
  source_urls: { url?: string; source?: string; fetched_at?: string }[] | null;
  source_diversity?: number | null;
  engagement_signal?: { status: string; video_count?: number; view_count?: number; comment_count?: number; source?: string; reason?: string } | null;
  demand_signal?: { status: string; reason?: string } | null;
  score_explanation?: { signals?: { signal: string; status: string; points: number | string; max_points: number; reason: string }[]; summary?: string } | null;
  feasibility_status: string | null;
  feasibility_low_paise: number | null;
  feasibility_high_paise: number | null;
  feasibility_cogs_basis: string | null;
  feasibility_unavailable_reason: string | null;
};

export type PiRecommendation = {
  candidate_id: string;
  rank: number;
  title: string | null;
  final_score: string | null;
  final_score_state: string;
  why_ranked: string[];
  pros: string[];
  cons: string[];
  supplier_option: PiSupplierLead | null;
  gaps: string[];
  note: string;
};

export type PiProduct = {
  rank: number;
  candidate: PiCandidate;
  reviewInsights: PiReviewInsight[];
  supplierLeads: PiSupplierLead[];
  bestSupplierLeadId: string | null;
  finalScore: string | null;
  finalScoreState: string;
  recommendation: PiRecommendation;
  financials: PiFinancial[];
};

export type PiCase = {
  runId: string;
  status: string;
  pinned: boolean;
  pinnedAt: string | null;
  completedAt: string | null;
  caseSaved: boolean;
  brief: PiBriefEcho;
  products: PiProduct[];
  overall: { candidate_id: string; title: string | null; final_score: string | null; reason: string; note: string } | null;
  cfoRefs: { candidate_id: string; kind: string; ref: string; leg_key: string; status: string }[];
  gaps: string[];
  unavailable: { field: string; reason: string }[];
  investigationId: string | null;
};

export type PiClient = {
  history(): Promise<{ items: PiHistoryItem[] }>;
  report(runId: string): Promise<PiCase>;
  pin(runId: string): Promise<{ runId: string; pinned: boolean }>;
  unpin(runId: string): Promise<{ runId: string; pinned: boolean }>;
};

const BASE = "/api/v1/pi/research";

export function createPiClient(getToken: GetToken): PiClient {
  const call = async <T>(path: string, init?: RequestInit): Promise<T> => apiFetch<T>(path, await getToken(), init);
  return {
    history: () => call(BASE),
    report: (runId) => call(`${BASE}/${encodeURIComponent(runId)}`),
    pin: (runId) => call(`${BASE}/${encodeURIComponent(runId)}/pin`, { method: "POST" }),
    unpin: (runId) => call(`${BASE}/${encodeURIComponent(runId)}/unpin`, { method: "POST" }),
  };
}

export function explainPiError(e: unknown): { message: string; missing: boolean } {
  const status = (e as { status?: number } | null)?.status;
  if (status === 404) return { message: "This report is no longer in your history.", missing: true };
  if (status === 403) return { message: "Your role does not include Product Intelligence.", missing: false };
  return { message: "We could not load this section. Check your connection and try again.", missing: false };
}

/** Integer paise -> "₹1,56,000" (Indian digit grouping, no floats). Missing is "Unavailable", never zero. */
export function formatPaise(paise: number | null | undefined): string {
  if (paise === null || paise === undefined || !Number.isFinite(paise)) return "Unavailable";
  const negative = paise < 0;
  const abs = Math.abs(Math.trunc(paise));
  const rupees = Math.trunc(abs / 100);
  const rest = abs % 100;
  const digits = String(rupees);
  const head = digits.slice(0, -3);
  const tail = digits.slice(-3);
  const grouped = head ? `${head.replace(/\B(?=(\d{2})+(?!\d))/g, ",")},${tail}` : tail;
  return `${negative ? "-" : ""}₹${grouped}${rest ? `.${String(rest).padStart(2, "0")}` : ""}`;
}

export function themeNames(t: Record<string, number> | string[] | null | undefined): string[] {
  if (!t) return [];
  if (Array.isArray(t)) return t.map(String);
  return Object.entries(t).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).map(([k]) => k);
}

export const SOURCE_LABEL: Record<string, string> = {
  GOOGLE_PLACES: "Google Places listing",
  TAVILY: "Web search lead (not verified)",
  INDIAMART_LOOKUP: "IndiaMART lookup",
};

export function safeHref(u: string | null | undefined): string | null {
  return u && /^https?:\/\//i.test(u) ? u : null;
}

export function imageDomain(sourceUrl: string | null | undefined): string {
  if (!sourceUrl) return "unknown source";
  try {
    return new URL(sourceUrl).hostname;
  } catch {
    return "unknown source";
  }
}

/** The research evidence behind one product, read from the saved candidate row: independent source domains with links, video engagement, the demand signal's status and the
 * per-signal score breakdown. A signal the research could not obtain is returned as `missing` with its reason, never dropped or shown as zero. */
export type PiEvidence = {
  sources: { domain: string; url: string; kind: string }[];
  independentSources: number | null;
  engagement: { videos: number | null; views: number | null; comments: number | null } | null;
  engagementMissing: string | null;
  demandMissing: string | null;
  signals: { signal: string; status: string; points: string; max: number; reason: string }[];
};

export function evidenceOf(c: PiCandidate): PiEvidence {
  const seen = new Set<string>();
  const sources: PiEvidence["sources"] = [];
  for (const s of c.source_urls ?? []) {
    const url = safeHref(s.url ?? null);
    if (!url) continue;
    const domain = imageDomain(url);
    if (seen.has(domain)) continue;
    seen.add(domain);
    sources.push({ domain, url, kind: s.source === "youtube" ? "Video" : "Web" });
  }
  const eng = c.engagement_signal;
  const available = eng?.status === "AVAILABLE";
  return {
    sources,
    independentSources: c.source_diversity ?? null,
    engagement: available ? { videos: eng.video_count ?? null, views: eng.view_count ?? null, comments: eng.comment_count ?? null } : null,
    engagementMissing: available ? null : (eng?.reason ?? "No video engagement was found for this product."),
    demandMissing: c.demand_signal?.status === "UNAVAILABLE" ? (c.demand_signal.reason ?? "Search-demand data is not available.") : null,
    signals: (c.score_explanation?.signals ?? []).map((x) => ({ signal: x.signal.replace(/[._]/g, " "), status: x.status, points: String(x.points), max: x.max_points, reason: x.reason })),
  };
}
