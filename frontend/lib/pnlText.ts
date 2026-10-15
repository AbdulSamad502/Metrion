/** Text <-> integer-string helpers for the Profit Calculator. Everything here is STRING handling: no arithmetic, no float, no rounding. The calculator's
 * numbers are produced by the backend engine (calculator.md N2); the browser only turns what the seller typed into the integer strings the API takes
 * (paise, basis points, counts) and turns the API's integer strings back into readable text. A value too long or oddly shaped to be a plain amount is
 * refused, never rounded or "fixed". */

export type Parsed = { ok: true; value: string } | { ok: false; reason: string };

const trimZeros = (digits: string): string => digits.replace(/^0+(?=\d)/, "");
// At most 11 rupee digits (Rs 99,99,99,99,999): the same ceiling the API enforces, so a value the form accepts is never refused for size.
const RUPEES = /^(\d{1,11})(?:\.(\d{1,2}))?$/;
const PERCENT = /^(\d{1,3})(?:\.(\d{1,2}))?$/;
const COUNT = /^\d{1,9}$/;

/** "1,180.50" -> "118000" (paise). Rupees with at most two decimals; no sign, exponent or rounding. */
export function rupeesToPaise(text: string): Parsed {
  const m = RUPEES.exec(text.trim().replace(/[₹,\s]/g, ""));
  if (!m) return { ok: false, reason: "Enter rupees with at most two decimals, for example 49.50." };
  return { ok: true, value: trimZeros(m[1] + (m[2] ?? "").padEnd(2, "0")) };
}

/** "12.5" or "12.5%" -> "1250" (basis points). 0 to 100 with at most two decimals. */
export function percentToBps(text: string): Parsed {
  const m = PERCENT.exec(text.trim().replace(/[%\s]/g, ""));
  if (!m) return { ok: false, reason: "Enter a percentage with at most two decimals, for example 12.5." };
  const bps = trimZeros(m[1] + (m[2] ?? "").padEnd(2, "0"));
  // Same-length digit strings compare correctly as text; 10000 bps is 100%.
  if (bps.length > 5 || (bps.length === 5 && bps > "10000")) return { ok: false, reason: "A percentage cannot be more than 100." };
  return { ok: true, value: bps };
}

/** "1,200" -> "1200". Whole numbers only. */
export function countToDigits(text: string): Parsed {
  const t = text.trim().replace(/,/g, "");
  if (!COUNT.test(t)) return { ok: false, reason: "Enter a whole number." };
  return { ok: true, value: trimZeros(t) };
}

/** Indian digit grouping of a plain digit string: "1234567" -> "12,34,567". */
function groupIndian(digits: string): string {
  if (digits.length <= 3) return digits;
  const last3 = digits.slice(-3);
  let rest = digits.slice(0, -3);
  const parts: string[] = [];
  while (rest.length > 2) {
    parts.unshift(rest.slice(-2));
    rest = rest.slice(0, -2);
  }
  if (rest) parts.unshift(rest);
  return `${parts.join(",")},${last3}`;
}

const isInt = (s: string): boolean => /^-?\d+$/.test(s);

/** An integer paise string -> "₹12,34,567.89" (with "−" for a negative). Anything that is not an integer string is shown as unavailable rather than guessed. */
export function formatPaise(paise: string | null | undefined): string {
  if (paise == null || !isInt(paise)) return "Not available";
  const negative = paise.startsWith("-");
  const digits = (negative ? paise.slice(1) : paise).padStart(3, "0");
  const rupees = groupIndian(trimZeros(digits.slice(0, -2)));
  return `${negative ? "−" : ""}₹${rupees}.${digits.slice(-2)}`;
}

/** An integer basis-point string -> "49.20%". */
export function formatBps(bps: string | null | undefined): string {
  if (bps == null || !isInt(bps)) return "Not available";
  const negative = bps.startsWith("-");
  const digits = (negative ? bps.slice(1) : bps).padStart(3, "0");
  return `${negative ? "−" : ""}${groupIndian(trimZeros(digits.slice(0, -2)))}.${digits.slice(-2)}%`;
}

/** ROAS arrives in basis points (10000 = 1.00x). Shown exactly: at least two decimals, up to four, never rounded. */
export function formatRoas(bps: string | null | undefined): string {
  if (bps == null || !/^\d+$/.test(bps)) return "Not available";
  const digits = bps.padStart(5, "0");
  const whole = groupIndian(trimZeros(digits.slice(0, -4)));
  const fraction = digits.slice(-4).replace(/0+$/, "").padEnd(2, "0");
  return `${whole}.${fraction}x`;
}

/** An integer paise string -> the rupee text a seller would type into a price field ("14014" -> "140.14", "14000" -> "140"). String handling only; the
 * result is read back by `rupeesToPaise`. Returns "" for anything that is not a non-negative integer string. */
export function paiseToInputText(paise: string | null | undefined): string {
  if (paise == null || !/^\d+$/.test(paise)) return "";
  const digits = paise.padStart(3, "0");
  const rupees = trimZeros(digits.slice(0, -2));
  const fraction = digits.slice(-2);
  return fraction === "00" ? rupees : `${rupees}.${fraction}`;
}
