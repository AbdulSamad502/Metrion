/** The Profit Calculator's wire contract and form-to-request mapping (docs/specs/calculator.md §14).
 *
 * The page collects what the seller types and renders what `POST /api/v1/cfo/pnl-scenario` returns; the engine (Brain 1) does all the arithmetic.
 * An input is one of: nothing entered (EMPTY, never zero), explicitly not applicable (a confirmed zero) or a value. Money, rates and counts travel
 * as integer STRINGS so no amount is ever rounded by a JavaScript number. The response is a hypothetical estimate: it has an `estimateRef`, never an
 * `engineResultRef`, and is never merged with verified CFO results. */

import { activeFeeFields, type PnlFulfilment, type PnlMarketplace } from "@/lib/pnlFeeFields";
import { countToDigits, percentToBps, rupeesToPaise, type Parsed } from "@/lib/pnlText";

// ---- response ------------------------------------------------------------------------------------------------------------------------

export type PnlStatus = "incomplete" | "provisional" | "estimate";
export type PnlLine = { id: string; label: string; group: string; amount: string };
export type PnlView = { revenue: string; lines: PnlLine[]; contribution: string; operatingExpenses: string | null; operatingProfit: string | null };
export type PnlCount = { num: string; den: string; text: string; exact: boolean };
export type PnlLineShare = { id: string; label: string; group: string; amount: string; shareBps: string };
/** A slice of the "where each rupee goes" chart. `startBps` / `endBps` are positions on 0..10000 given by the server, so the page draws without arithmetic. */
export type PnlSegment = PnlLineShare & { startBps: string; endBps: string };
export type PnlBreakdown = {
  lines: PnlLineShare[];
  profitShareBps: string;
  segments: PnlSegment[] | null;
  chartUnavailableReason: string | null;
  topCosts: PnlLineShare[];
};
export type PnlSolution = {
  target: { kind: "breakeven" | "margin"; bps: string; basis: "contribution" | "operating" };
  outcome: "price" | "always" | "unreachable" | "unavailable";
  price: string | null;
  ranges: { from: string; to: string | null }[];
  excludesMissingCosts: boolean;
  reason: string | null;
};
export type PnlScenarioResponse = {
  kind: "hypothetical_estimate";
  verification: "unverified_estimate";
  persisted: false;
  estimateRef: string;
  formulaVersion: string;
  status: PnlStatus;
  isExample: boolean;
  issues: { code: string; severity: "blocking" | "missing" | "info"; message: string; field: string | null }[];
  missingCosts: string[];
  assumptions: { code: string; label: string }[];
  scopeNote: string | null;
  noKeptOrders: boolean;
  orders: { placed: PnlCount; kept: PnlCount; rto: PnlCount; returned: PnlCount } | null;
  perKept: PnlView | null;
  perPlaced: PnlView | null;
  monthly: PnlView | null;
  metrics: {
    contributionMarginBps: string | null; operatingMarginBps: string | null; effectiveFeeBps: string | null; acosBps: string | null; tacosBps: string | null;
    roasBps: string | null; breakEvenRoasBps: string | null; maxCac: string | null; gstRecoveredPerKept: string | null; gstRecoveredMonthly: string | null;
  } | null;
  breakdown: PnlBreakdown | null;
  solutions: PnlSolution[];
};

// ---- form ----------------------------------------------------------------------------------------------------------------------------

/** One typed number. Blank and not-applicable-off means "not entered"; it is never read as zero. */
export type PnlField = { text: string; na: boolean };
export const BLANK: PnlField = { text: "", na: false };

export type PnlFeeEntry = PnlField & { refund: PnlField };
export type PnlRecoveryForm = { sellable: PnlField; damaged: PnlField };

export type PnlForm = {
  marketplace: PnlMarketplace;
  fulfilment: PnlFulfilment;
  mode: "quick" | "detailed";
  gstStatus: "registered_itc" | "registered_no_itc" | "unregistered";
  sellingPrice: PnlField;
  gstRate: PnlField;
  productCost: PnlField;
  purchaseGstRate: PnlField;
  servicesGstRate: PnlField;
  packaging: PnlField;
  fees: Record<string, PnlFeeEntry>;
  monthlyOrders: PnlField;
  rto: PnlField;
  returns: PnlField;
  rtoRecovery: PnlRecoveryForm;
  returnRecovery: PnlRecoveryForm;
  salvage: PnlField;
  adSpend: PnlField;
  adRevenue: PnlField;
  operatingExpenses: PnlField;
  wantBreakeven: boolean;
  targetMargin: PnlField;
};

export function emptyForm(marketplace: PnlMarketplace = "amazon"): PnlForm {
  return {
    marketplace, fulfilment: "easy_ship", mode: "detailed", gstStatus: "registered_itc",
    sellingPrice: BLANK, gstRate: BLANK, productCost: BLANK, purchaseGstRate: BLANK, servicesGstRate: BLANK, packaging: BLANK, fees: {},
    monthlyOrders: BLANK, rto: BLANK, returns: BLANK,
    rtoRecovery: { sellable: BLANK, damaged: BLANK }, returnRecovery: { sellable: BLANK, damaged: BLANK }, salvage: BLANK,
    adSpend: BLANK, adRevenue: BLANK, operatingExpenses: BLANK,
    wantBreakeven: true, targetMargin: BLANK,
  };
}

type Entry = { state: "empty" } | { state: "na" } | { state: "set"; value: string };
type Kind = "money" | "percent" | "count";
const PARSERS: Record<Kind, (t: string) => Parsed> = { money: rupeesToPaise, percent: percentToBps, count: countToDigits };

function entryOf(f: PnlField, kind: Kind): { entry: Entry } | { error: string } {
  if (f.na) return { entry: { state: "na" } };
  if (f.text.trim() === "") return { entry: { state: "empty" } };
  const p = PARSERS[kind](f.text);
  return p.ok ? { entry: { state: "set", value: p.value } } : { error: p.reason };
}

export type PnlRequestResult = { ok: true; body: Record<string, unknown> } | { ok: false; errors: Record<string, string> };

/** The API request for a form, or the per-field errors that stop it. Nothing is guessed: an unreadable number blocks the request instead of being
 * dropped or treated as zero, and a blank field is sent as `empty`. */
export function buildRequest(form: PnlForm): PnlRequestResult {
  const errors: Record<string, string> = {};
  const take = (key: string, f: PnlField, kind: Kind): Entry => {
    const r = entryOf(f, kind);
    if ("error" in r) {
      errors[key] = r.error;
      return { state: "empty" };
    }
    return r.entry;
  };
  const registered = form.gstStatus !== "unregistered";
  const quick = form.mode === "quick";

  const fees: Record<string, unknown> = {};
  for (const def of activeFeeFields(form.marketplace, form.fulfilment, form.mode)) {
    const f = form.fees[def.id];
    if (!f) continue;
    const kind: Kind = def.unit === "percent" ? "percent" : "money";
    const amount = entryOf(f, kind);
    if ("error" in amount) {
      errors[`fee.${def.id}`] = amount.error;
      continue;
    }
    const refund = take(`fee.${def.id}.refund`, f.refund, "percent");
    const value = amount.entry.state === "set" ? { kind: "single", amount: amount.entry.value } : null;
    fees[def.id] = { amount: value ? { state: "set", value } : { state: amount.entry.state }, refund_bps: refund };
  }

  const targets: Record<string, unknown>[] = [];
  if (form.wantBreakeven) targets.push({ kind: "breakeven" });
  if (form.targetMargin.text.trim() !== "") {
    const m = percentToBps(form.targetMargin.text);
    if (!m.ok) errors.targetMargin = m.reason;
    else if (m.value === "10000") errors.targetMargin = "A target margin must be below 100%.";
    else targets.push({ kind: "margin", bps: m.value });
  }

  const body = {
    marketplace: form.marketplace,
    mode: form.mode,
    amazon_fulfilment: form.fulfilment,
    gst_status: form.gstStatus,
    selling_price: take("sellingPrice", form.sellingPrice, "money"),
    gst_rate_bps: registered ? take("gstRate", form.gstRate, "percent") : { state: "empty" },
    product_cost: take("productCost", form.productCost, "money"),
    purchase_gst_rate_bps: registered ? take("purchaseGstRate", form.purchaseGstRate, "percent") : { state: "empty" },
    services_gst_rate_bps: take("servicesGstRate", form.servicesGstRate, "percent"),
    packaging_cost: quick ? { state: "empty" } : take("packaging", form.packaging, "money"),
    fees,
    monthly_orders: take("monthlyOrders", form.monthlyOrders, "count"),
    rto_bps: take("rto", form.rto, "percent"),
    return_bps: take("returns", form.returns, "percent"),
    rto_recovery: { sellable_bps: take("rtoSellable", form.rtoRecovery.sellable, "percent"), damaged_bps: take("rtoDamaged", form.rtoRecovery.damaged, "percent") },
    return_recovery: { sellable_bps: take("returnSellable", form.returnRecovery.sellable, "percent"), damaged_bps: take("returnDamaged", form.returnRecovery.damaged, "percent") },
    salvage_bps: take("salvage", form.salvage, "percent"),
    ad_spend: quick ? { state: "empty" } : take("adSpend", form.adSpend, "money"),
    ad_revenue: quick ? { state: "empty" } : take("adRevenue", form.adRevenue, "money"),
    operating_expenses: quick ? { state: "empty" } : take("operatingExpenses", form.operatingExpenses, "money"),
    targets,
  };
  return Object.keys(errors).length > 0 ? { ok: false, errors } : { ok: true, body };
}
