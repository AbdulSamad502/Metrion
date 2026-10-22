/** The Expense Tracker's recurring templates, CSV import and accountant export (kickoff S4b, S5a, S5b). The page only collects what is typed or chosen and shows what the
 * backend returns: amounts stay integer-paise strings (parsed by `rupeesToPaise`, shown by `formatPaise`), every duplicate decision and every change comes from the server,
 * and nothing is added up here. Imported and materialised entries always arrive as "pending review" and count only after the seller confirms them. */

import { API_BASE, ApiError, apiFetch, apiFetchForm } from "@/lib/api";
import { rupeesToPaise } from "@/lib/pnlText";
import type { Getter } from "@/lib/expenseLedger";

const BASE = "/api/v1/cfo/expense-ledger";

// ---- templates -------------------------------------------------------------------------------------------------------------------

export type TemplateKind = "MONTHLY" | "AMORTIZED" | "PER_ORDER" | "PER_UNIT";
export type ExpenseTemplate = {
  templateKey: string; version: number; kind: TemplateKind; vendor: string | null; description: string | null; category: string; categoryLabel: string;
  costClass: string; treatment: string; amountPaise: string | number | null; ratePaise: string | number | null; amortizationMonths: number | null; startMonth: string | null;
  channelScope: string | null; sku: string | null; effectiveFrom: string; effectiveTo: string | null; ended: boolean;
};
export type MaterialiseResponse = { created: string[]; alreadyMaterialised: number; skipped: { templateKey: string; reason: string }[] };

export const KIND_LABEL: Record<TemplateKind, string> = { MONTHLY: "Every month", AMORTIZED: "Spread over months", PER_ORDER: "Per order", PER_UNIT: "Per unit" };
export const SKIP_REASON_LABEL: Record<string, string> = {
  ORDERS_UNAVAILABLE: "Some sales lines are missing what the order count needs (their cancellation status or order id), so no amount is made up.",
  UNITS_UNAVAILABLE: "Some sales lines are missing what the unit count needs (their cancellation, return or RTO status), so no amount is made up.",
  NO_ORDERS_IN_PERIOD: "There are no sales lines for that month, so there is nothing to count. This is not a zero.",
  MONTH_NOT_FINISHED: "The month has not finished, so its count is not final. It is made after the month ends.",
  AMORTIZATION_INVALID: "The number of months is not valid.",
};

export type TemplateForm = { kind: TemplateKind; category: string; vendor: string; amount: string; rate: string; months: string; effectiveFrom: string };
export type BuiltTemplate = { ok: true; body: Record<string, unknown> } | { ok: false; error: string };

export function buildTemplateBody(f: TemplateForm): BuiltTemplate {
  if (!f.category) return { ok: false, error: "Choose a category." };
  if (!f.effectiveFrom) return { ok: false, error: "Choose when it starts." };
  const body: Record<string, unknown> = { kind: f.kind, category: f.category, effective_from: f.effectiveFrom };
  if (f.vendor.trim()) body.vendor = f.vendor.trim();
  if (f.kind === "MONTHLY" || f.kind === "AMORTIZED") {
    const amount = rupeesToPaise(f.amount);
    if (!amount.ok) return { ok: false, error: amount.reason };
    body.amount_paise = amount.value;
  } else {
    const rate = rupeesToPaise(f.rate);
    if (!rate.ok) return { ok: false, error: rate.reason };
    body.rate_paise = rate.value;
  }
  if (f.kind === "AMORTIZED") {
    const months = f.months.trim();
    if (!/^[1-9][0-9]{0,2}$/.test(months)) return { ok: false, error: "Enter the number of months as a whole number, for example 12." };
    body.amortization_months = JSON.parse(months) as number; // digits only, so this is the whole number itself (no number parsing helper is used on money)
  }
  return { ok: true, body };
}

export async function loadTemplates(getToken: Getter): Promise<{ templates: ExpenseTemplate[] }> {
  return apiFetch(`${BASE}/templates`, await getToken());
}
export async function createTemplate(getToken: Getter, body: Record<string, unknown>): Promise<{ templateKey: string; version: number }> {
  return apiFetch(`${BASE}/templates`, await getToken(), { method: "POST", body: JSON.stringify(body) });
}
export async function materialise(getToken: Getter, throughMonth: string): Promise<MaterialiseResponse> {
  return apiFetch(`${BASE}/templates/materialise`, await getToken(), { method: "POST", body: JSON.stringify({ through_month: throughMonth }) });
}
export type RefundTemplateResponse = { templateKey: string; remainingFrom: string; remainingMonths: number; remainingPaise: string };
export const REFUND_REASON_LABEL: Record<string, string> = {
  NO_REMAINING_SCHEDULE: "No month of this schedule is left, so there is nothing to reduce. Record the refund on the entry it belongs to instead.",
  REFUND_EXCEEDS_REMAINING: "The refund is more than what is left to spread.",
  AMORTIZATION_INVALID: "This schedule cannot be reduced.",
};

/** A refund of a spread-over-months expense reduces what is left from the refund month on; past months and the entries already made are not restated. The amount is rupees,
 * sent as an integer-paise string; the re-spread is the backend's. */
export function buildTemplateRefundBody(date: string, amount: string): BuiltTemplate {
  if (!date) return { ok: false, error: "Choose the date of the refund." };
  const parsed = rupeesToPaise(amount);
  if (!parsed.ok) return { ok: false, error: parsed.reason };
  if (parsed.value === "0") return { ok: false, error: "A refund must be more than zero." };
  return { ok: true, body: { effective_date: date, amount_paise: parsed.value } };
}
export async function refundTemplate(getToken: Getter, key: string, body: Record<string, unknown>): Promise<RefundTemplateResponse> {
  return apiFetch(`${BASE}/templates/${key}/refund`, await getToken(), { method: "POST", body: JSON.stringify(body) });
}
export async function endTemplate(getToken: Getter, key: string, effectiveTo: string): Promise<{ templateKey: string; version: number }> {
  return apiFetch(`${BASE}/templates/${key}/end`, await getToken(), { method: "POST", body: JSON.stringify({ effective_to: effectiveTo }) });
}

// ---- CSV import --------------------------------------------------------------------------------------------------------------------

export type ImportStatus = "OK" | "ERROR" | "DUPLICATE" | "PROBABLE_MATCH";
export type ImportRow = {
  row: number; status: ImportStatus; errors: string[]; note: string | null; matchedExpenseIds: string[]; date: string | null; vendor: string | null;
  description: string | null; category: string | null; amountPaise: number | null; sourceId: string | null; channel: string | null;
};
export type ImportSummary = {
  fileSha256: string; rowCount: number; counts: Record<ImportStatus, number>; fileErrors: string[]; rows: ImportRow[];
  created?: string[]; alreadyImported?: number; state?: string;
};

export const STATUS_LABEL: Record<ImportStatus, string> = {
  OK: "Ready", ERROR: "Has a problem", DUPLICATE: "Already in the ledger (skipped)", PROBABLE_MATCH: "Looks like an existing entry (kept, flagged)",
};

/** Preview writes nothing; commit writes the accepted rows as pending review. The file is sent as it is and is never kept by Metrion. */
export async function importFile(getToken: Getter, file: File, commit: boolean, skipInvalid: boolean): Promise<ImportSummary> {
  const form = new FormData();
  form.append("file", file);
  const query = commit && skipInvalid ? "?skip_invalid=true" : "";
  return apiFetchForm<ImportSummary>(`${BASE}/import/${commit ? "commit" : "preview"}${query}`, await getToken(), form);
}

// ---- downloads ---------------------------------------------------------------------------------------------------------------------

/** Fetches a CSV (the import template or the accountant export) with the session token and hands it to the browser as a file. Nothing is kept. */
export async function downloadCsv(getToken: Getter, path: string, filename: string): Promise<void> {
  const token = await getToken();
  const res = await fetch(`${API_BASE}${BASE}${path}`, { headers: token ? { Authorization: `Bearer ${token}` } : undefined });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new ApiError(res.status, body?.detail ?? res.statusText);
  }
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
