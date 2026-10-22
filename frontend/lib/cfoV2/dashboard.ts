import type { CellFigure, FigureData, FilterParams } from "./types";

/** Response shapes of the CFO 2.0 dashboard read routes (backend/src/backend/services/cfo_dashboard.py). Every money value is a server-formatted display string. */
export type Refusal = { status: "REFUSED"; code: string; message: string };

export type CoverageRow = {
  metricId: string;
  marketplace: string;
  included: boolean;
  sharePct: string | null;
  thresholdPct: string | null;
  reason: string | null;
  excludedLineCount: number | null;
  excludedBasis: string | null;
  excludedAmountDisplay: string | null;
};

export type OverviewResponse = {
  status: "ANSWERED";
  dataVersion: number;
  cached: boolean;
  generatedAt: string;
  kpis: FigureData[];
  operatingProfitState: "UNAVAILABLE" | "PROVISIONAL" | "FINAL" | null;
  urgentActions: { text: string }[];
  coverage: CoverageRow[];
  labels: string[];
  canAdjust: boolean;
};

export type MarketplaceRow = { key: string; marketplace: string; grossSales: CellFigure; nrr: CellFigure; contributionProfit: CellFigure; margin: CellFigure };
export type SkuRow = { key: string; sku: string; grossSales: CellFigure; nrr: CellFigure; contributionProfit: CellFigure };
export type MarketplacesResponse = { status: "ANSWERED"; items: MarketplaceRow[]; dataVersion: number; coverage: CoverageRow[]; generatedAt: string };
export type SkusResponse = { status: "ANSWERED"; items: SkuRow[]; page: number; pageSize: number; total: number; pageCount: number; dataVersion: number; generatedAt: string; truncated: boolean };

export type TrendPoint = { label: string; plot: number | null; display: string | null; status: CellFigure["status"] };
export type TrendResponse = { status: "ANSWERED"; points: TrendPoint[]; dataVersion: number; generatedAt: string };

export type BridgeResponse = {
  status: "ANSWERED";
  reconciles?: boolean;
  bridge: { deltaDisplay: string; otherDisplay: string; otherRef: string | null; drivers: { metricId: string; deltaDisplay: string; ref: string | null }[] } | null;
  reasons?: (string | null)[];
  dataRequests?: string[];
};

export type CashResponse = { status: "ANSWERED"; figures: FigureData[]; dataRequests: string[]; coverage: CoverageRow[]; generatedAt: string; note: string };
export type PayableRow = { id: string; amount: CellFigure; dueDate: string | null; supplierRef: string | null; poRef: string | null };
export type PayablesResponse = { status: "ANSWERED"; items: PayableRow[]; generatedAt: string };

export type LeakRow = {
  id: string;
  marketplace: string;
  category: string;
  severity: string;
  amount: CellFigure;
  affectedLines: number;
  sku: string | null;
  ageDays: number;
  claimWindowDays: number | null;
  windowStatus: string | null;
  claimState: string;
  engineResultRef: string;
  withheld: boolean;
  withheldReason: string | null;
};
export type LeakResponse = { status: "ANSWERED"; items: LeakRow[]; page: number; pageSize: number; total: number; pageCount: number; generatedAt: string; note: string };

export type AlertItem = { id: string; agent: string; kind: string; subject: string; text: string; trustLabel: string; createdAt: string };
export type AlertsResponse = { status: "ANSWERED"; items: AlertItem[]; generatedAt: string };

/** The period every dashboard view is asked for: the filters' own dates, or the current calendar month's bounds supplied by the page (the page owns "today"). */
export type Period = { start: string; end: string };

export function periodQuery(f: FilterParams, fallback: Period): string {
  const q = new URLSearchParams({ period_start: f.from ?? fallback.start, period_end: f.to ?? fallback.end });
  if (f.marketplace !== "ALL") q.set("marketplace", f.marketplace);
  return q.toString();
}

export const isRefusal = (r: unknown): r is Refusal => typeof r === "object" && r !== null && (r as { status?: string }).status === "REFUSED";

/** Claim states in the order a seller reports them, with plain labels (Metrion files nothing; these are the seller's own reports). */
export const CLAIM_STATE_LABEL: Record<string, string> = {
  NEW: "New",
  ACKNOWLEDGED: "Acknowledged",
  CLAIM_DRAFTED: "Claim text drafted",
  SELLER_REPORTED_RAISED: "You reported it raised",
  SELLER_REPORTED_RESOLVED: "You reported it resolved",
  DISMISSED: "Dismissed",
};
export const NEXT_CLAIM_STEPS: Record<string, string[]> = {
  NEW: ["ACKNOWLEDGED", "DISMISSED"],
  ACKNOWLEDGED: ["SELLER_REPORTED_RAISED", "DISMISSED"],
  CLAIM_DRAFTED: ["SELLER_REPORTED_RAISED", "DISMISSED"],
  SELLER_REPORTED_RAISED: ["SELLER_REPORTED_RESOLVED", "DISMISSED"],
};
