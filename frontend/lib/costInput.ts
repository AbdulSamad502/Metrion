/** The seller's three explicit states for a cost input (spec ceo 6.12 "Never invent an input", 6.33, Q31): an amount, "none (0), I confirm", or "unknown".
 * A cost field has NO default: until one of the three is chosen the form is not ready, so a zero can never be sent by omission.
 *
 * Money is parsed from the typed text with integer arithmetic only: no floating point is involved, so ₹1.005-style inputs are rejected rather than rounded. */

export type CostMode = "" | "amount" | "none" | "unknown";
export type CostChoice = { mode: CostMode; amount: string; reason: string };

export const EMPTY_COST: CostChoice = { mode: "", amount: "", reason: "" };

const RUPEES = /^(\d{1,12})(?:\.(\d{1,2}))?$/;

/** "1,299.50" -> 129950; null when it is not a plain non-negative rupee amount with at most two decimals. Exact: no float. */
export function rupeesToPaise(text: string): number | null {
  const m = RUPEES.exec(text.trim().replace(/,/g, ""));
  if (!m) return null;
  const paise = Number(m[1]) * 100 + Number((m[2] ?? "").padEnd(2, "0"));
  return Number.isSafeInteger(paise) ? paise : null;
}

/** A whole count typed as digits ("100"), or null. Empty text is null too: callers decide whether blank is allowed. */
export function parseCount(text: string): number | null {
  const t = text.trim();
  return /^\d{1,9}$/.test(t) ? Number(t) : null;
}

export function costReady(c: CostChoice): boolean {
  if (c.mode === "amount") return rupeesToPaise(c.amount) !== null;
  return c.mode === "none" || c.mode === "unknown";
}

/** The API shape for one cost: an amount in paise (0 only when the seller chose "none (0), I confirm" or typed it), or null = unknown with the seller's reason.
 * Throws if the choice is not ready: callers check `costReady` first, so an unanswered field can never become a zero. */
export function costToApi(c: CostChoice): { paise: number | null; reason: string | null } {
  if (!costReady(c)) throw new Error("cost input not answered");
  if (c.mode === "unknown") return { paise: null, reason: c.reason.trim() || null };
  if (c.mode === "none") return { paise: 0, reason: null };
  return { paise: rupeesToPaise(c.amount), reason: null };
}
