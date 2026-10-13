/** Typed READ client for the CMO showcase (/api/v1/cmo/showcase/*, docs/specs/ceo-cmo-delegation.md §6.9).
 *
 * The showcase is read-only: every function here is a `GET`, except `recordUsage`, the one approved telemetry write (CD14), which is
 * fire-and-forget (failures are ignored and never block the seller). There is nothing here that generates, approves, uploads or
 * writes to a marketplace, and nothing computes a figure: char/byte counts come from the API as stored. */

import { apiFetch } from "@/lib/api";

export type Marketplace = "AMAZON" | "FLIPKART" | "MEESHO";
export const MARKETPLACES: { id: Marketplace; label: string }[] = [
  { id: "AMAZON", label: "Amazon" },
  { id: "FLIPKART", label: "Flipkart" },
  { id: "MEESHO", label: "Meesho" },
];
export type GetToken = () => Promise<string | null>;

export type Origin = { investigationId: string | null; turnId: string | null; kind: "CEO_CHAT" | "PRE_CHAT_WORKFLOW" };

export type ShowcaseProduct = {
  sku: string;
  label: string;
  lastGeneratedAt: string;
  counts: Partial<Record<Marketplace, number>>;
};

export type TrendFinding = {
  text: string;
  sourceName: string;
  sourceUrl: string | null;
  publishedAt: string | null;
  retrievedAt: string | null;
  corroboration: string | null;
  sources?: { name: string | null; url: string | null; publishedAt: string | null; retrievedAt: string | null }[];
};
export type TrendReport = {
  generationId: string;
  createdAt: string;
  status: string;
  nicheTerms: string[];
  sections: { name: string; state: string; findings: TrendFinding[] }[];
  interpretationLabel: string | null;
  evidenceRef: string | null;
};

export type TitleUsage = { copied?: number; markedUsed?: number; generated?: number; viewed?: number; since?: string | null };
export type ShowcaseTitle = {
  generationId: string;
  optionId: string;
  rank: number | null;
  titleText: string;
  charCount: number;
  maxChars: number | null; // null = the verified source states no limit
  constraint: { sourceUrl: string | null; verifiedAt: string | null } | null;
  approved: { approvalId: string; approvedAt: string; editedBySeller: boolean } | null;
  sku: string;
  productLabel: string;
  marketplace: Marketplace;
  generatedAt: string;
  origin: Origin;
  usage: TitleUsage | null;
};
export type TitlesPage = {
  items: ShowcaseTitle[];
  usage: { available: boolean; basis: "RECORDED_EVENTS" | null; since: string | null; reason?: "NOT_CONFIGURED" | "NO_USAGE_RECORDED" };
  nextCursor?: string | null;
};

export type CopyPack = {
  generationId: string;
  marketplace: Marketplace;
  sku: string;
  productLabel: string;
  groundedOn: { approvalId: string | null; titleText: string; basis: string };
  bullets: { text: string; chars: number; max: number | null }[];
  description: { text: string; chars: number; max: number | null };
  backendTerms: { text: string; bytes: number; maxBytes: number | null } | null;
  generatedAt: string;
  origin: Origin;
  labels: string[];
};

export type HashtagSet = { generationId: string; sku: string; productLabel: string; hashtags: string[]; generatedAt: string; origin: Origin };

/** Counts derived from stored deterministic validation only; an entry is omitted by the server when not stored (§6.8-4). */
export type ComplianceSummary = { counts?: { label: string; count: number; basis: string }[] };

export type UsageKind = "VIEWED" | "COPIED" | "MARKED_USED";
export type UsageEvent = { generationId: string; optionId?: string; resultPart?: string; kind: UsageKind; surface: "DASHBOARD" };

export type TitleFilters = { marketplace: Marketplace; sku?: string; q?: string; view: "recent" | "frequent"; approvedOnly?: boolean };
export type PackFilters = { marketplace: Marketplace; sku?: string; q?: string };

export type ShowcaseClient = {
  products(q?: string): Promise<{ items: ShowcaseProduct[] }>;
  trends(): Promise<{ items: TrendReport[]; nextCursor?: string | null }>;
  titles(f: TitleFilters): Promise<TitlesPage>;
  copyPacks(f: PackFilters): Promise<{ items: CopyPack[] }>;
  hashtags(f: { sku?: string; q?: string }): Promise<{ items: HashtagSet[] }>;
  compliance(f: { sku?: string; marketplace?: Marketplace }): Promise<ComplianceSummary>;
  /** Fire-and-forget: never rejects, never blocks. */
  recordUsage(e: UsageEvent): void;
};

const BASE = "/api/v1/cmo/showcase";

function qs(params: Record<string, string | boolean | undefined>): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === "" || v === false) continue;
    sp.set(k, String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
}

export function createShowcaseClient(getToken: GetToken): ShowcaseClient {
  const get = async <T>(path: string): Promise<T> => apiFetch<T>(path, await getToken());
  return {
    products: (q) => get(`${BASE}/products` + qs({ q })),
    trends: () => get(`${BASE}/trends`),
    titles: (f) => get(`${BASE}/titles` + qs({ marketplace: f.marketplace, sku: f.sku, q: f.q, view: f.view, approvedOnly: f.approvedOnly })),
    copyPacks: (f) => get(`${BASE}/copy-packs` + qs({ marketplace: f.marketplace, sku: f.sku, q: f.q })),
    hashtags: (f) => get(`${BASE}/hashtags` + qs({ sku: f.sku, q: f.q })),
    compliance: (f) => get(`${BASE}/compliance` + qs({ sku: f.sku, marketplace: f.marketplace })),
    recordUsage: (e) => {
      void (async () => {
        try {
          const token = await getToken();
          await fetch(`${process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000"}${BASE}/usage-events`, {
            method: "POST",
            headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
            body: JSON.stringify(e),
          });
        } catch {
          /* telemetry only: a failure is ignored by design (CD14) */
        }
      })();
    },
  };
}

/** The fixture is a local visual aid only. `process.env.NODE_ENV` is inlined by Next, so in a production build this is `false` and the
 * fixture module is never reachable. */
export const FIXTURE_ALLOWED = process.env.NODE_ENV !== "production";

export type ShowcaseProblem = { message: string; notConfigured: boolean };
export function explainShowcaseError(e: unknown): ShowcaseProblem {
  const status = (e as { status?: number } | null)?.status;
  if (status === 503) return { message: "The library is not configured yet. Ask the CEO, or try again later.", notConfigured: true };
  if (status === 404) return { message: "The saved-results library is not available yet.", notConfigured: true };
  if (status === 403) return { message: "Your role does not include marketing results.", notConfigured: false };
  return { message: "We could not load this section. Check your connection and try again.", notConfigured: false };
}
