import type { PresentationFigure } from "@/lib/ceo";

/** Everything here is presentation only. The backend's strings are shown as they arrive; the helpers below read them to
 *  size a bar or pick a word, and never produce a figure that is displayed. */

/** A backend money string ("₹142,860.00", "−₹3,210.00") read as a plain number, ONLY to size a bar. Not shown anywhere. */
export function weight(value: string | null | undefined): number | null {
  if (!value) return null;
  const negative = /^[-−(]/.test(value.trim());
  const cleaned = value.replace(/[^\d.]/g, "");
  if (!cleaned) return null;
  const n = Number(cleaned);
  if (!Number.isFinite(n)) return null;
  return negative ? -n : n;
}

export const isNegative = (value: string) => /^[-−(]/.test(value.trim());

export type FlowShares = { fees: number; profit: number; rest: number };

/** Widths (0..1, summing to 1) for "where the revenue went". Null whenever the three figures cannot honestly be drawn together:
 *  a missing or unreadable figure, a loss, or fees and profit that together exceed revenue. */
export function flowShares(revenue: string | undefined, fees: string | undefined, profit: string | undefined): FlowShares | null {
  const r = weight(revenue);
  const f = weight(fees);
  const p = weight(profit);
  if (r === null || f === null || p === null || r <= 0 || f < 0 || p <= 0) return null;
  if (f + p > r) return null;
  return { fees: f / r, profit: p / r, rest: 1 - f / r - p / r };
}

/** "0.xx" of a goal reached, for a meter. Null unless both figures are readable and positive. */
export function goalShare(profit: string | undefined, goal: string | undefined): number | null {
  const p = weight(profit);
  const g = weight(goal);
  if (p === null || g === null || p < 0 || g <= 0) return null;
  return Math.min(1, p / g);
}

export type Band = "GOOD" | "WATCH" | "AT_RISK";
export function bandOf(text: string | null | undefined): Band | null {
  const t = (text ?? "").toUpperCase().replace(/[\s-]+/g, "_");
  if (t.startsWith("AT_RISK")) return "AT_RISK";
  if (t.startsWith("WATCH")) return "WATCH";
  if (t.startsWith("GOOD")) return "GOOD";
  return null;
}
export const BAND_WORD: Record<Band, string> = { GOOD: "Good", WATCH: "Watch", AT_RISK: "At risk" };
export const BAND_TONE: Record<Band, "good" | "warn" | "bad"> = { GOOD: "good", WATCH: "warn", AT_RISK: "bad" };

/** "Contribution margin band" -> "Contribution margin" */
export const plainBandLabel = (label: string) => label.replace(/\s+band$/i, "");

export type Leak = { title: string; where: string; severity: "High" | "Medium" | "Low" | null; amount: string; key: string };
const LEAK = /^([A-Z][A-Z_]+)\s+[—-]\s+([A-Za-z ]+?)(?:\s+\(SKU\s+([^)]+)\))?\s*(?:\[([A-Za-z]+)\])?$/;
const sentence = (s: string) => s.toLowerCase().replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
export function readLeak(f: PresentationFigure): Leak {
  const m = LEAK.exec(f.label.trim());
  const key = `${f.ref.kind}-${f.ref.id}-${f.label}`;
  if (!m) return { title: f.label, where: "", severity: null, amount: f.value, key };
  const sev = (m[4] ?? "").toLowerCase();
  const severity = sev === "high" ? "High" : sev === "medium" ? "Medium" : sev === "low" ? "Low" : null;
  const marketplace = sentence(m[2].trim());
  return { title: sentence(m[1]), where: [marketplace, m[3]].filter(Boolean).join(" · "), severity, amount: f.value, key };
}

const REGISTER: Record<string, string> = {
  VERIFIED: "Verified from your reports",
  DERIVED: "Calculated from verified figures",
  MANUAL: "Entered by you",
  ESTIMATE: "Estimate",
  UNAVAILABLE: "Not available",
};
export const registerWords = (register: string) => REGISTER[register.toUpperCase()] ?? register.toLowerCase().replace(/_/g, " ");
export const registerShort = (register: string) => (register.toUpperCase() === "VERIFIED" ? "Verified" : register.toUpperCase() === "DERIVED" ? "Calculated" : register.toUpperCase() === "MANUAL" ? "Yours" : register.toUpperCase() === "ESTIMATE" ? "Estimate" : registerWords(register));

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
/** "2026-09-01" -> "1 Sep". Reads the calendar date as written, so no time zone can move it. */
export function dayLabel(iso: string | null | undefined): string | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso ?? "");
  if (!m) return null;
  return `${Number(m[3])} ${MONTHS[Number(m[2]) - 1]}`;
}
/** "2026-09-01/2026-09-30" -> "1 Sep – 30 Sep" */
export function periodLabel(period: string | null | undefined): string | null {
  if (!period) return null;
  const [a, b] = period.split("/");
  const x = dayLabel(a);
  const y = dayLabel(b);
  return x && y ? `${x} – ${y}` : x ?? null;
}
/** Whole days a "start/end" period spans, to know whether a monthly goal can honestly be set beside it. */
export function periodDays(period: string | null | undefined): number | null {
  if (!period) return null;
  const [a, b] = period.split("/");
  const x = Date.parse(`${a}T00:00:00Z`);
  const y = Date.parse(`${b}T00:00:00Z`);
  return Number.isNaN(x) || Number.isNaN(y) ? null : Math.round((y - x) / 86_400_000) + 1;
}
