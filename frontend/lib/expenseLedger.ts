// Types, request builders and display labels for the Expense Tracker dashboard (docs/specs/expense-tracker.md; Round 9, route /dashboard/cfo/expenses).
//
// No money arithmetic lives here or in the components: totals come from the backend (the engine feed, with an engineResultRef, AC17), amounts the seller types
// are parsed to integer-paise STRINGS by `rupeesToPaise` and sent as strings, and money is shown with `formatPaise` (string handling only).
import { apiFetch } from "@/lib/api";
import { formatPaise, rupeesToPaise } from "@/lib/pnlText";

export type ReviewState = "draft" | "pending_review" | "confirmed" | "voided";
export type PaymentStatus = "unpaid" | "partially_paid" | "paid" | "unknown";

export type ExpenseRecord = {
  id: string;
  effectiveDate: string;
  vendor: string | null;
  description: string | null;
  category: string;
  categoryLabel: string;
  costClass: string;
  treatment: string;
  amountPaise: number;
  channelScope: string | null;
  sku: string | null;
  origin: string;
  sourceValidated: boolean;
  identifier: string | null;
  sourceReference: string | null;
  correctsExpenseId: string | null;
  refundOfExpenseId: string | null;
  recurring: boolean;
  createdAt: string | null;
  reviewState: ReviewState;
  reviewReason: string | null;
  paymentStatus: PaymentStatus | null;
  paidAmountPaise: number | null;
  history?: { seq: number; kind: string; reviewState: string | null; paymentStatus: string | null; paidAmountPaise: number | null; reason: string | null; createdAt: string | null }[];
};

export type ExpenseListResponse = { records: ExpenseRecord[]; total: number; limit: number; offset: number };

export type CategoryInfo = { id: string; label: string; costClass: string; treatment: string };
export type LedgerMeta = {
  categories: CategoryInfo[];
  costClasses: string[];
  treatments: string[];
  channelTags: string[];
  reviewStates: ReviewState[];
  paymentStatuses: PaymentStatus[];
  limits: { amountMaxPaise: number; vendorMax: number; descriptionMax: number; reasonMax: number; pageSizeDefault: number; pageSizeMax: number };
};

type Figure = { paise: number; engineResultRef: string; asOfDate: string | null };
export type SummaryResponse = {
  periodStart: string;
  periodEnd: string;
  asOfDate: string | null;
  watermark: string;
  expenseTotal: Figure;
  includingUnresolved: Figure;
  recurringTotal: Figure;
  reviewQueue: { amountPaise: number; engineResultRef: string; asOfDate: string | null; items: { expenseId: string; reason: string; amountPaise: number }[] };
  byCostClass: (Figure & { costClass: string })[];
  byCategory: (Figure & { category: string; label: string })[];
  notEntered: string[];
  gaps: string[];
};

export const BASE = "/api/v1/cfo/expense-ledger";

export const REVIEW_LABEL: Record<ReviewState, string> = { draft: "Draft", pending_review: "Pending review", confirmed: "Confirmed", voided: "Voided" };
export const PAYMENT_LABEL: Record<PaymentStatus, string> = { unpaid: "Unpaid", partially_paid: "Partly paid", paid: "Paid", unknown: "Payment unknown" };
export const COST_CLASS_LABEL: Record<string, string> = { ADVERTISING: "Advertising", STORAGE: "Storage", OVERHEAD: "Overhead", DIRECT: "Direct costs" };
export const REVIEW_REASON_LABEL: Record<string, string> = {
  PENDING_REVIEW: "Waiting for review",
  UNMAPPED_IDENTIFIER: "SKU not found in your catalog",
  UNKNOWN_COST_CLASS: "Cost class not recognised",
  UNKNOWN_TREATMENT: "Treatment not recognised",
};

/** Money for display: integer paise (a JSON number or string) -> "₹1,25,000.00" or "−₹400.00". */
export function money(paise: number | string | null | undefined): string {
  return paise == null ? "Not available" : formatPaise(String(paise));
}

export type FormValues = {
  effectiveDate: string;
  category: string;
  amount: string; // rupees as typed
  vendor: string;
  description: string;
  costClass: string; // "" = the category's default
  channelScope: string; // "" = business-wide
  state: "draft" | "pending_review" | "confirmed";
};

export type BuiltBody = { ok: true; body: Record<string, unknown> } | { ok: false; error: string };

/** The create / correct request body. The amount is parsed to an integer-paise string by `rupeesToPaise`; nothing is rounded or defaulted. */
export function buildContentBody(v: FormValues, extra: Record<string, unknown> = {}): BuiltBody {
  if (!v.effectiveDate) return { ok: false, error: "Choose the date of the expense." };
  if (!v.category) return { ok: false, error: "Choose a category." };
  const amount = rupeesToPaise(v.amount);
  if (!amount.ok) return { ok: false, error: amount.reason };
  const body: Record<string, unknown> = { effective_date: v.effectiveDate, category: v.category, amount_paise: amount.value, ...extra };
  if (v.vendor.trim()) body.vendor = v.vendor.trim();
  if (v.description.trim()) body.description = v.description.trim();
  if (v.costClass) body.cost_class = v.costClass;
  if (v.channelScope) body.channel_scope = v.channelScope;
  return { ok: true, body };
}

/** A refund or credit note is entered as a positive amount and sent as a negative integer-paise string. */
export function buildRefundBody(date: string, amount: string, description: string): BuiltBody {
  if (!date) return { ok: false, error: "Choose the date of the refund." };
  const parsed = rupeesToPaise(amount);
  if (!parsed.ok) return { ok: false, error: parsed.reason };
  if (parsed.value === "0") return { ok: false, error: "A refund must be more than zero." };
  const body: Record<string, unknown> = { effective_date: date, amount_paise: `-${parsed.value}` };
  if (description.trim()) body.description = description.trim();
  return { ok: true, body };
}

export type Getter = () => Promise<string | null>;

export async function loadMeta(getToken: Getter): Promise<LedgerMeta> {
  return apiFetch<LedgerMeta>(`${BASE}/categories`, await getToken());
}

export async function loadSummary(getToken: Getter, periodStart: string, periodEnd: string): Promise<SummaryResponse> {
  return apiFetch<SummaryResponse>(`${BASE}/summary`, await getToken(), { method: "POST", body: JSON.stringify({ period_start: periodStart, period_end: periodEnd }) });
}

export type ListFilters = { category?: string; reviewState?: string; paymentStatus?: string; dateFrom?: string; dateTo?: string; includeVoided?: boolean; offset?: number; limit?: number };

export async function loadList(getToken: Getter, f: ListFilters): Promise<ExpenseListResponse> {
  const q = new URLSearchParams();
  if (f.category) q.set("category", f.category);
  if (f.reviewState) q.set("review_state", f.reviewState);
  if (f.paymentStatus) q.set("payment_status", f.paymentStatus);
  if (f.dateFrom) q.set("date_from", f.dateFrom);
  if (f.dateTo) q.set("date_to", f.dateTo);
  if (f.includeVoided) q.set("include_voided", "true");
  if (f.offset) q.set("offset", String(f.offset));
  if (f.limit) q.set("limit", String(f.limit));
  const qs = q.toString();
  return apiFetch<ExpenseListResponse>(`${BASE}${qs ? `?${qs}` : ""}`, await getToken());
}

export async function post<T = { expenseId: string }>(getToken: Getter, path: string, body: unknown): Promise<T> {
  return apiFetch<T>(`${BASE}${path}`, await getToken(), { method: "POST", body: JSON.stringify(body) });
}
