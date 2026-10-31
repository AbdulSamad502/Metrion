/** CMO 3.0 M8: the seller's imported performance reports, the dashboard and the confirmations behind a before/after view of a saved listing version. Every number arrives from the backend
 * (deterministic, from the seller's own imported rows); this module only formats whole numbers for display. Nothing here estimates, sums or compares a figure. No call uses an AI credit. */

import { apiFetch, apiFetchForm } from "@/lib/api";

type GetToken = () => Promise<string | null>;
const BASE = "/api/v1/cmo/performance";
export const PERFORMANCE_PAGE = "/dashboard/cmo/performance"; // linked by constant so the read-only showcase page carries no CMO route text

export type MetricKey = "impressions" | "clicks" | "orders" | "units" | "sales" | "ctr" | "cvr";
export const METRIC_KEYS: MetricKey[] = ["impressions", "clicks", "ctr", "orders", "cvr", "units", "sales"];
export const METRIC_LABEL: Record<MetricKey, string> = { impressions: "Impressions", clicks: "Clicks", ctr: "Click-through rate", orders: "Orders", cvr: "Conversion rate", units: "Units sold", sales: "Sales" };
export type MetricState = "AVAILABLE" | "NOT_ASSESSED" | "UNAVAILABLE";
export type Metric = { state: MetricState; value: number | null; reason: string | null };
export type Summary = { periodStart: string; periodEnd: string; days: number; coveredDays: number; complete: boolean; metrics: Record<MetricKey, Metric> };
export type Comparison = Record<MetricKey, { state: "NOT_ASSESSED"; reason: string } | { state: "AVAILABLE"; previous: number; current: number; difference: number; relativeBp: number | null; direction: "UP" | "DOWN" | "SAME" }>;
export type Evidence = { metric: MetricKey; label: string; previous: string; current: string; previousPeriod: string; currentPeriod: string };
export type RouteAction = { kind: "TITLE" | "CONTENT" | "KEYWORDS" | "REVISE"; route: string; label: string; ask: string; draft?: string | null; product?: string; marketplace?: string };
export type Insight = { kind: string; what: string; evidence: Evidence[]; whyItMatters: string; nextStep: string; action: RouteAction | null; limits: string[]; measured: boolean; explanation: string };
export type TrendPoint = { date: string } & Record<MetricKey, number | null>;
export type ImportRow = { id: string; marketplace: string; sourceName: string; periodStart: string; periodEnd: string; rowsSaved: number; rowsSkipped: number; metrics: string[]; importedAt: string };
export type DashboardProduct = { sku: string; name: string; marketplaces: string[]; linked: string[] };
export type Dashboard = {
  filters: { marketplace: string | null; sku: string | null; start: string; end: string }; aiCredits: 0; products: DashboardProduct[]; marketplaces: string[];
  dataSpan: { lastImportAt: string | null; first: string | null; last: string | null }; source: string; current: Summary; previous: Summary; comparison: Comparison; trend: TrendPoint[];
  insights: Insight[]; needs: string[]; limits: string[]; imports: ImportRow[]; never: string;
};
export type MappingVersion = { versionId: string; number: number; createdAt: string; wentLiveOn: string | null; confirmedAt: string | null };
export type MappingItem = {
  sku: string; product: string; marketplace: string; reportSku: string | null; linkConfirmedAt: string | null; versions: MappingVersion[]; status: "COMPLETE" | "NEEDS_CONFIRMATION"; missing: string[];
  history: { links: { reportSku: string; confirmedAt: string }[]; golives: { versionId: string; wentLiveOn: string; confirmedAt: string }[] };
};
export type Mappings = { items: MappingItem[]; windowDays: number | null; windowSetBy: "YOU" | "OPERATOR" | null; windowBounds: [number, number]; missing: string[]; hasImports: boolean; aiCredits: 0 };
export type SkuCandidate = { reportSku: string; reportTitle: string | null; rows: number; firstOrder: string | null; lastOrder: string | null };
export type VersionRow = {
  versionId: string; number: number; createdAt: string; source: string; changedSection: string | null; wentLiveOn: string | null; state: "NOT_ASSESSED" | "INCOMPARABLE" | "OBSERVED_COMPARABLE"; needs: string[]; reasons: string[];
  note?: string; previous?: Summary; following?: Summary; comparison?: Comparison; observations?: string[]; insights?: Insight[]; attribution?: "NOT_ATTRIBUTED";
};
export type MetricVals = Record<"impressions" | "clicks" | "orders" | "units" | "sales", number | null>;
export type PerfLine = { lineId: string; importId: string; marketplace: string; reportSku: string; date: string; original: MetricVals; effective: MetricVals; corrected: boolean; correctionId: string | null; voided: boolean; sourceName: string; importedAt: string };
export type LinesPage = { marketplace: string; reportSku: string | null; start: string; end: string; total: number; limit: number; offset: number; hasMore: boolean; lines: PerfLine[]; note: string; aiCredits: 0 };
export type CorrectionRow = { id: string; lineId: string; importId: string; sourceName: string; marketplace: string; reportSku: string; date: string; previous: MetricVals; corrected: MetricVals; voided: boolean; changed: string[]; reason: string; supersedes: string | null; by: string; at: string };
export type CorrectionHistory = { corrections: CorrectionRow[]; limit: number; offset: number; hasMore: boolean; aiCredits: 0; note: string };
export type CorrectionResult = { corrected: true; correctionId: string; at: string; lineId: string; voided: boolean; changed: string[]; previous: MetricVals; now: MetricVals; original: MetricVals; message: string; aiCredits: 0 };
export type VersionAnalysis = { total?: number; limit?: number | null; offset?: number; hasMore?: boolean; order?: "asc" | "desc"; sku: string; marketplace: string; product: string; source: string; windowDays: number | null; windowSetBy: string | null; linked: string | null; versions: VersionRow[]; needs: string[]; aiCredits: 0 };
export type ImportIssue = { row: number; message: string };
export type ImportPreview = {
  sha256: string; fileName: string; marketplace: string; ok: boolean; errors: ImportIssue[]; errorCount: number; warnings: string[]; metrics: string[]; ignoredColumns: string[]; rowCount: number;
  period: { start: string; end: string; days: number } | null; newRows: number; duplicateRows: number; conflicts: ImportIssue[]; conflictCount?: number; sample: Record<string, string>[];
  alreadyImported: { importedAt: string; fileName: string; periodStart: string; periodEnd: string } | null; canImport: boolean; aiCredits: 0;
};
export type ImportResult = { imported: true; importId: string; importedAt: string; marketplace: string; rowsSaved: number; rowsSkipped: number; period: { start: string; end: string; days: number }; metrics: string[]; message: string };

/** A card the CEO chat shows for a performance question (CMO 3.0 M8). Only the fields a view needs are present; the card never carries a figure the backend did not compute from the seller's reports. */
export type PerformanceCard = { kind: "LISTING_PERFORMANCE"; view: string; page: string; aiCredits: 0; investigationId?: string; question?: string; options?: { label: string }[]; message?: string;
  dashboard?: unknown; tiles?: { key: string; label: string; value: string; change: string }[]; notShown?: string[]; period?: { start: string; end: string; covered: number; days: number; source: string }; ranking?: unknown; analysis?: unknown; missing?: string[]; proposal?: Record<string, string | number>; replaces?: string | null; current?: number | null; product?: string; action?: RouteAction };
export const isPerformanceCard = (c: unknown): c is PerformanceCard => !!c && typeof c === "object" && (c as { kind?: unknown }).kind === "LISTING_PERFORMANCE" && typeof (c as { view?: unknown }).view === "string";

// ------------------------------------------------------------------------------------------------ one-click hand-off to the existing CMO workflows
/** The sentence each hand-off puts in the CEO chat bar (the seller presses send; nothing runs on arrival). Mirrors `slim_cmo.history.metrics.HANDOFF`; each is answered by existing free CMO code. */
const MP_WORD: Record<string, string> = { AMAZON: "Amazon", FLIPKART: "Flipkart", MEESHO: "Meesho" };
const HANDOFF: Record<RouteAction["kind"], string> = {
  TITLE: "What should I improve next in my {product} listing on {marketplace}?",
  KEYWORDS: "What should I improve next in my {product} listing on {marketplace}?",
  CONTENT: "What questions will buyers ask about my {product}?",
  REVISE: "Show my latest {product} listing on {marketplace}",
};
export function handoffHref(a: RouteAction): string | null {
  if (!a.draft || !a.product || !a.marketplace) return null;
  return `/dashboard/ceo-hub?${new URLSearchParams({ ask: "cmo", kind: a.kind, about: a.product, mp: a.marketplace }).toString()}`;
}
/** The inverse, for the hub: only a known kind and marketplace give a draft, so a URL cannot put arbitrary text in the chat bar. */
export function cmoDraftFromParams(ask: string | null, kind: string | null, about: string | null, mp: string | null): string | null {
  if (ask !== "cmo" || !kind || !(kind in HANDOFF) || !about?.trim() || about.length > 120 || !mp || !(mp in MP_WORD)) return null;
  return HANDOFF[kind as RouteAction["kind"]].replace("{product}", about.trim()).replace("{marketplace}", MP_WORD[mp]);
}

// ------------------------------------------------------------------------------------------------ formatting (whole numbers only)
const group = (n: number): string => {
  const s = String(Math.abs(Math.trunc(n)));
  return s.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
};
function rupees(paise: number): string {
  const sign = paise < 0 ? "-" : "";
  const a = Math.abs(paise);
  const r = Math.floor(a / 100);
  const s = String(r);
  const head = s.length > 3 ? s.slice(0, -3).replace(/\B(?=(\d{2})+(?!\d))/g, ",") + "," + s.slice(-3) : s;
  return `${sign}₹${head}.${String(a % 100).padStart(2, "0")}`;
}
const rate = (bp: number): string => `${bp < 0 ? "-" : ""}${Math.floor(Math.abs(bp) / 100)}.${String(Math.abs(bp) % 100).padStart(2, "0")}%`;
export const formatMetric = (k: MetricKey, v: number): string => (k === "sales" ? rupees(v) : k === "ctr" || k === "cvr" ? rate(v) : (v < 0 ? "-" : "") + group(v));
/** A difference in words and a mark (never colour alone). Rates are percentage points; counts also carry the relative change when the earlier value was above zero. */
export function describeChange(k: MetricKey, c: Comparison[MetricKey]): string {
  if (c.state !== "AVAILABLE") return "Not assessed";
  if (c.difference === 0) return "● Same as the previous period";
  const up = c.difference > 0;
  const abs = k === "ctr" || k === "cvr" ? `${Math.floor(Math.abs(c.difference) / 100)}.${String(Math.abs(c.difference) % 100).padStart(2, "0")} points` : formatMetric(k, Math.abs(c.difference));
  const rel = c.relativeBp === null ? "" : ` (${up ? "+" : "-"}${Math.floor(Math.abs(c.relativeBp) / 100)}.${String(Math.abs(c.relativeBp) % 100).padStart(2, "0")}%)`;
  return `${up ? "▲ Up" : "▼ Down"} ${abs}${rel} from the previous period`;
}

// ------------------------------------------------------------------------------------------------ client
export type PerformanceApi = ReturnType<typeof createPerformanceApi>;
export function createPerformanceApi(getToken: GetToken) {
  const q = (o: Record<string, string | null | undefined>) => {
    const p = new URLSearchParams();
    for (const [k, v] of Object.entries(o)) if (v) p.set(k, v);
    return p.toString();
  };
  const post = async <T>(path: string, body: unknown): Promise<T> => apiFetch<T>(BASE + path, await getToken(), { method: "POST", body: JSON.stringify(body) });
  const upload = async <T>(path: string, file: File, fields: Record<string, string>): Promise<T> => {
    const form = new FormData();
    form.append("file", file);
    for (const [k, v] of Object.entries(fields)) form.append(k, v);
    return apiFetchForm<T>(BASE + path, await getToken(), form);
  };
  return {
    dashboard: async (f: { marketplace?: string | null; sku?: string | null; start?: string | null; end?: string | null }): Promise<Dashboard> => apiFetch(`${BASE}/dashboard?${q(f)}`, await getToken()),
    mappings: async (): Promise<Mappings> => apiFetch(`${BASE}/mappings`, await getToken()),
    versions: async (sku: string, marketplace: string, page?: { limit?: number; offset?: number; order?: "asc" | "desc" }): Promise<VersionAnalysis> =>
      apiFetch(`${BASE}/versions?${q({ sku, marketplace, limit: page?.limit ? String(page.limit) : undefined, offset: page?.offset ? String(page.offset) : undefined, order: page?.order })}`, await getToken()),
    lines: async (f: { marketplace: string; reportSku?: string | null; start?: string | null; end?: string | null; limit?: number; offset?: number }): Promise<LinesPage> =>
      apiFetch(`${BASE}/lines?${q({ marketplace: f.marketplace, report_sku: f.reportSku, start: f.start, end: f.end, limit: f.limit ? String(f.limit) : undefined, offset: f.offset ? String(f.offset) : undefined })}`, await getToken()),
    correctionHistory: async (f: { marketplace?: string | null; reportSku?: string | null; limit?: number; offset?: number }): Promise<CorrectionHistory> =>
      apiFetch(`${BASE}/correction-history?${q({ marketplace: f.marketplace, report_sku: f.reportSku, limit: f.limit ? String(f.limit) : undefined, offset: f.offset ? String(f.offset) : undefined })}`, await getToken()),
    correct: (b: { lineId: string; changes: Record<string, string | null>; void: boolean; reason: string; expectedCorrectionId: string | null }) =>
      post<CorrectionResult>("/corrections", { line_id: b.lineId, changes: b.changes, void: b.void, reason: b.reason, expected_correction_id: b.expectedCorrectionId }),
    candidates: async (marketplace: string): Promise<{ candidates: SkuCandidate[]; note: string }> => apiFetch(`${BASE}/sku-candidates?${q({ marketplace })}`, await getToken()),
    previewImport: (file: File, marketplace: string): Promise<ImportPreview> => upload("/import/preview", file, { marketplace }),
    importReport: (file: File, marketplace: string, sha256: string): Promise<ImportResult> => upload("/import", file, { marketplace, expected_sha256: sha256 }),
    linkSku: (b: { sku: string; marketplace: string; reportSku: string; replace?: boolean }) => post<{ linked: true; previous: string | null; message: string }>("/sku-link", { sku: b.sku, marketplace: b.marketplace, report_sku: b.reportSku, replace: !!b.replace }),
    confirmGoLive: (b: { generationId: string; wentLiveOn: string; replace?: boolean }) => post<{ recorded: true; previous: string | null; message: string }>("/golive", { generation_id: b.generationId, went_live_on: b.wentLiveOn, replace: !!b.replace }),
    setWindow: (days: number) => post<{ days: number; message: string }>("/window", { days }),
  };
}

/** The plain sentence for a failed request. A 409 on a statement means an earlier one exists and the seller must choose to replace it. */
export function performanceError(e: unknown): { message: string; code?: string } {
  const d = (e as { detail?: unknown })?.detail as { detail?: { code?: string; detail?: string } | string; code?: string } | string | undefined;
  const inner = typeof d === "object" && d ? (typeof d.detail === "object" && d.detail ? d.detail : d) : undefined;
  const msg = inner && typeof inner === "object" && "detail" in inner && typeof inner.detail === "string" ? inner.detail : typeof d === "string" ? d : undefined;
  return { message: msg ?? "That did not work. Nothing was changed.", code: inner && typeof inner === "object" && "code" in inner ? (inner.code as string) : undefined };
}
