/** CFO 2.0 dashboard contracts (docs/specs/cfo-dashboard-implementation.md §3–4). The dashboard renders what the server sends: money arrives as a display string
 * formatted by the backend and is never parsed, summed or re-formatted here. */

export type Completeness = "COMPLETE" | "PARTIAL" | "PROVISIONAL" | "ESTIMATED" | "UNAVAILABLE";
export type FigureRegister = "VERIFIED" | "DERIVED" | "MANUAL" | "ESTIMATE" | "UNAVAILABLE";
export type AdSpendStatus = "VERIFIED_ZERO" | "KNOWN_SPEND" | "MISSING_COVERAGE" | "UNKNOWN";

export type FigureSource = { kind: string; label: string; refId?: string | null };
export type FigureExclusion = { reason: string; count: number; amountDisplay?: string | null };
export type FigureMissingInput = { field: string; why: string; dataRequestId?: string | null };

/** One displayed figure with everything a seller needs to trust it (or to see why they cannot). */
export type FigureData = {
  label: string;
  valueDisplay: string | null; // null when unavailable — never rendered as 0
  completeness: Completeness;
  register: FigureRegister;
  source: FigureSource[];
  lastUpdated: string | null;
  asOfDate: string | null;
  periodCoverage: string | null;
  engineResultRef?: string | null;
  estimateRef?: string | null;
  formulaVersion?: string | null;
  exclusions: FigureExclusion[];
  missingInputs: FigureMissingInput[];
  statusNotes: string[];
  adSpendStatus?: AdSpendStatus | null;
  unavailableReason?: string | null;
};

/** A money cell in a table: the server's display string and state, nothing to compute. */
export type CellFigure = { display: string | null; status: Completeness };

export type Page<T> = { items: T[]; page: number; pageSize: number; total: number; pageCount: number; dataVersion: string; generatedAt: string };

export type MarketplaceFilter = "ALL" | "AMAZON" | "FLIPKART" | "MEESHO";
export const MARKETPLACE_FILTERS: readonly MarketplaceFilter[] = ["ALL", "AMAZON", "FLIPKART", "MEESHO"];

export type FilterParams = { from: string | null; to: string | null; marketplace: MarketplaceFilter; sku: string };
export type SortDir = "asc" | "desc";
