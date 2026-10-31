/** CMO 3.0 M10: market opportunities and marketplace news for the seller's own products. Every item, source, date, freshness, relevance and recommendation arrives from the backend, read from the seller's
 * SAVED market-trend reports and own product details. This module only types it and calls the read-only routes. It searches nothing, invents nothing, and uses no AI credit. */

import { apiFetch } from "@/lib/api";

type GetToken = () => Promise<string | null>;
const BASE = "/api/v1/cmo/market-intelligence";
export const MARKET_PAGE = "/dashboard/cmo/market"; // linked by constant so the read-only showcase page carries no CMO route text

export type Marketplace = "AMAZON" | "FLIPKART" | "MEESHO";
export const MP_LABEL: Record<Marketplace, string> = { AMAZON: "Amazon", FLIPKART: "Flipkart", MEESHO: "Meesho" };
export type Freshness = "FRESH" | "RECENT" | "STALE" | "DATE_UNKNOWN";
export type Level = "HIGH" | "MEDIUM" | "LOW" | "NOT_ASSESSED";
export type Strength = "STRONG" | "MODERATE" | "WEAK" | "NOT_ASSESSED";
export type MarketSource = { url: string; title: string | null; publishedAt: string | null; retrievedAt: string | null; sourceClass: string | null };
export type Affect = { sku: string; name: string; level: Level; sharedTerms: string[]; marketplaces: Marketplace[]; reason: string };
export type Relevance = { level: Level; reason: string; affects: Affect[] };
export type Step = { agent: "YOU" | "PI" | "CMO" | "CFO"; text: string; ask?: string };
export type NewsItem = {
  id: string; headline: string; summary: string; newsKind: string | null; marketplaces: Marketplace[]; sources: MarketSource[]; publishedAt: string | null; ageDays: number | null; freshness: Freshness; isStale: boolean;
  officialSource: boolean; sourceNote: string; impact: string; relevance: Relevance; reportId: string; reportDate: string; seenInReports: number; independentSources: number | null; corroboration: string | null;
  limitation: string | null; recommendations: Step[];
};
export type Opportunity = {
  id: string; title: string; section: string; kind: string; relevance: Relevance; rank: number; rankedBecause: string; evidenceStrength: Strength; evidenceStrengthWhy: string; limitation: string | null;
  observed: { label: string; summary: string; sources: MarketSource[]; independentSources: number | null; freshestPublishedAt: string | null; freshness: Freshness; ageDays: number | null; reportId: string; reportDate: string; seenInReports: number };
  possible: { label: string; text: string }; demand: { state: "UNAVAILABLE"; note: string }; recommendations: Step[];
};
export type MarketOverview = {
  state: "OK" | "STALE_REPORTS" | "NO_REPORT"; message: string | null; latestReportAt: string | null; reportCount: number; news: NewsItem[]; opportunities: Opportunity[]; newsWithoutMarketplace: number;
  filters: { sku: string | null; marketplace: Marketplace | null }; products: { sku: string; name: string; marketplaces: Marketplace[] }[]; marketplaces: Marketplace[]; today: string;
  freshnessRules: { freshDays: number; recentDays: number; reportStaleDays: number }; notes: string[]; aiCredits: 0;
};

/** The card the CEO chat shows (CMO 3.0 M10). */
export type MarketCard = {
  kind: "MARKET_INTELLIGENCE"; view: "NEWS" | "CHANGED" | "OPPORTUNITIES" | "FOCUS" | "AFFECTS" | "ACTION" | "NO_REPORT" | "CLARIFY" | "REFUSED"; page: string; aiCredits: 0; investigationId?: string; message?: string; question?: string;
  options?: { label: string; marketplace?: string }[]; state?: MarketOverview["state"]; latestReportAt?: string | null; reportCount?: number; news?: NewsItem[]; opportunities?: Opportunity[];
  moreNews?: number; moreOpportunities?: number; notes?: string[]; focusId?: string; filter?: { marketplace: string | null };
};
export const isMarketCard = (c: unknown): c is MarketCard => !!c && typeof c === "object" && (c as { kind?: unknown }).kind === "MARKET_INTELLIGENCE" && typeof (c as { view?: unknown }).view === "string";

const DRAFTS: Record<string, string> = { OPPORTUNITIES: "Find opportunities for my products", NEWS: "Show latest marketplace news", FOCUS: "Which opportunities should I focus on?", AFFECTS: "How does this news affect my products?", ACTION: "What should I do about this update?" };
/** The hub's chat-bar draft for a hand-off from the market page: only a known kind (and, for CHANGED, a known marketplace) gives a fixed sentence, so a URL cannot put arbitrary text in the chat bar. */
export function marketDraftFromParams(ask: string | null, kind: string | null, mp: string | null): string | null {
  if (ask !== "market" || !kind) return null;
  if (kind === "CHANGED") return mp && mp in MP_LABEL ? `What has changed on ${MP_LABEL[mp as Marketplace]}?` : null;
  return DRAFTS[kind] ?? null;
}
export const marketHandoff = (kind: string, mp?: string | null): string => `/dashboard/ceo-hub?${new URLSearchParams({ ask: "market", kind, ...(mp ? { mp } : {}) }).toString()}`;

export type MarketApi = ReturnType<typeof createMarketApi>;
export function createMarketApi(getToken: GetToken) {
  const q = (o: Record<string, string | null | undefined>) => {
    const p = new URLSearchParams();
    for (const [k, v] of Object.entries(o)) if (v) p.set(k, v);
    return p.toString();
  };
  return { overview: async (f: { sku?: string | null; marketplace?: string | null }): Promise<MarketOverview> => apiFetch(`${BASE}?${q(f)}`, await getToken()) };
}

export function marketError(e: unknown): string {
  const d = (e as { detail?: unknown })?.detail as { detail?: string } | string | undefined;
  if (typeof d === "string") return d;
  if (d && typeof d === "object" && typeof d.detail === "string") return d.detail;
  return "That did not work. Nothing was changed.";
}

export const FRESH_WORD: Record<Freshness, string> = { FRESH: "● FRESH", RECENT: "◐ RECENT", STALE: "○ STALE", DATE_UNKNOWN: "? DATE UNKNOWN" };
export const LEVEL_WORD: Record<Level, string> = { HIGH: "HIGH", MEDIUM: "MEDIUM", LOW: "LOW", NOT_ASSESSED: "NOT ASSESSED" };
export const STRENGTH_WORD: Record<Strength, string> = { STRONG: "STRONG", MODERATE: "MODERATE", WEAK: "WEAK", NOT_ASSESSED: "NOT ASSESSED" };
