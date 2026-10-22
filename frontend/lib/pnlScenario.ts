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

/** One price band of a fee: "up to ₹ upTo" (blank on the last band, which has no upper limit) and the rate or amount charged in it. */
export type PnlBand = { upTo: string; rate: string };
/** A fee entry: the single typed amount (or its tri-state), what share of it is refunded on returns, an optional price-band schedule and the price it is charged on. */
export type PnlFeeEntry = PnlField & {
  refund: PnlField;
  useTiers: boolean;
  tierMode: "whole" | "marginal";
  bands: PnlBand[];
  basis: "" | "price_incl_gst" | "price_excl_gst";
};
export const newFeeEntry = (): PnlFeeEntry => ({ ...BLANK, refund: BLANK, useTiers: false, tierMode: "whole", bands: [{ upTo: "", rate: "" }, { upTo: "", rate: "" }], basis: "" });
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
  targetBasis: "contribution" | "operating";
  /** True while the form holds the fictional example numbers. They are not real marketplace rates; the result carries a standing label until Reset. */
  isExample: boolean;
};

export function emptyForm(marketplace: PnlMarketplace = "amazon"): PnlForm {
  return {
    marketplace, fulfilment: "easy_ship", mode: "detailed", gstStatus: "registered_itc",
    sellingPrice: BLANK, gstRate: BLANK, productCost: BLANK, purchaseGstRate: BLANK, servicesGstRate: BLANK, packaging: BLANK, fees: {},
    monthlyOrders: BLANK, rto: BLANK, returns: BLANK,
    rtoRecovery: { sellable: BLANK, damaged: BLANK }, returnRecovery: { sellable: BLANK, damaged: BLANK }, salvage: BLANK,
    adSpend: BLANK, adRevenue: BLANK, operatingExpenses: BLANK,
    wantBreakeven: true, targetMargin: BLANK, targetBasis: "contribution", isExample: false,
  };
}

/** The "Try with example numbers" form: made-up figures to show how the calculator works. They are NOT marketplace rates and are labelled as examples
 * everywhere they appear (`isExample` is sent so the result says so too). Fee rates differ by marketplace only so each fee field has something to show. */
export function exampleForm(marketplace: PnlMarketplace = "amazon", mode: PnlForm["mode"] = "quick"): PnlForm {
  const fee = (text: string): PnlFeeEntry => ({ ...newFeeEntry(), text });
  const fees: Record<string, PnlFeeEntry> =
    marketplace === "amazon" ? { referral: fee("10"), closing: fee("20"), shipping: fee("55") }
    : marketplace === "flipkart" ? { commission: fee("9"), fixed_fee: fee("10"), shipping: fee("60") }
    : { commission: fee("0"), shipping: fee("65"), other: fee("0") };
  const t = (text: string): PnlField => ({ text, na: false });
  return {
    ...emptyForm(marketplace), mode, isExample: true, fees,
    sellingPrice: t("1199"), gstRate: t("18"), productCost: t("450"), monthlyOrders: t("300"), rto: t("8"), returns: t("5"),
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
    const refund = take(`fee.${def.id}.refund`, f.refund, "percent");
    const basis = def.unit === "percent" && f.basis !== "" ? { basis: f.basis } : {};
    if (f.useTiers && def.tierable) {
      const bands: { up_to: string | null; amount: string }[] = [];
      f.bands.forEach((row, i) => {
        const last = i === f.bands.length - 1;
        const rate = PARSERS[kind](row.rate);
        if (row.rate.trim() === "" || !rate.ok) errors[`fee.${def.id}.band.${i}.rate`] = row.rate.trim() === "" ? "Enter the rate for this band." : (rate as { reason: string }).reason;
        let upTo: string | null = null;
        if (!last) {
          const limit = rupeesToPaise(row.upTo);
          if (row.upTo.trim() === "" || !limit.ok) errors[`fee.${def.id}.band.${i}.upTo`] = row.upTo.trim() === "" ? "Enter the price this band goes up to." : (limit as { reason: string }).reason;
          else upTo = limit.value;
        }
        if (rate.ok) bands.push({ up_to: upTo, amount: rate.value });
      });
      if (!Object.keys(errors).some((k) => k.startsWith(`fee.${def.id}.band.`))) {
        fees[def.id] = { amount: { state: "set", value: { kind: "tiers", mode: f.tierMode, bands } }, refund_bps: refund, ...basis };
      }
      continue;
    }
    const amount = entryOf(f, kind);
    if ("error" in amount) {
      errors[`fee.${def.id}`] = amount.error;
      continue;
    }
    const value = amount.entry.state === "set" ? { kind: "single", amount: amount.entry.value } : null;
    fees[def.id] = { amount: value ? { state: "set", value } : { state: amount.entry.state }, refund_bps: refund, ...basis };
  }

  const targets: Record<string, unknown>[] = [];
  if (form.wantBreakeven) targets.push({ kind: "breakeven" });
  if (form.targetMargin.text.trim() !== "") {
    const m = percentToBps(form.targetMargin.text);
    if (!m.ok) errors.targetMargin = m.reason;
    else if (m.value === "10000") errors.targetMargin = "A target margin must be below 100%.";
    else targets.push({ kind: "margin", bps: m.value, basis: form.targetBasis });
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
    is_example: form.isExample,
  };
  return Object.keys(errors).length > 0 ? { ok: false, errors } : { ok: true, body };
}

// ---- what-if comparison ----------------------------------------------------------------------------------------------------------------

/** The engine's what-if-minus-base changes (`POST /api/v1/cfo/pnl-scenario-compare`). A change is null when either side had no figure for it, never zero. */
export type PnlComparison = { perKeptChange: string | null; perPlacedChange: string | null; monthlyChange: string | null; marginChangeBps: string | null };
export type PnlCompareResponse = { kind: "hypothetical_comparison"; persisted: false; base: PnlScenarioResponse; whatIf: PnlScenarioResponse; comparison: PnlComparison };

/** The five values the seller may try: blank keeps the current number. Typed text only; nothing here is read as a number by the page. */
export type WhatIfOverrides = { price: string; cost: string; rto: string; ret: string; ads: string };
export const NO_OVERRIDES: WhatIfOverrides = { price: "", cost: "", rto: "", ret: "", ads: "" };

const OVERRIDE_FIELD: Record<keyof WhatIfOverrides, keyof PnlForm> = { price: "sellingPrice", cost: "productCost", rto: "rto", ret: "returns", ads: "adSpend" };

/** The compare request: the current form as the base, and the same form with the typed values replaced as the variant. The current scenario is never changed. */
export function buildCompareRequest(form: PnlForm, ov: WhatIfOverrides): { ok: true; body: Record<string, unknown> } | { ok: false; errors: Record<string, string> } {
  const touched = (Object.keys(ov) as (keyof WhatIfOverrides)[]).filter((k) => ov[k].trim() !== "" && !(k === "ads" && form.mode === "quick"));
  if (touched.length === 0) return { ok: false, errors: { _form: "Type a new value for at least one box." } };
  const variant: PnlForm = { ...form };
  for (const k of touched) (variant as Record<string, unknown>)[OVERRIDE_FIELD[k]] = { text: ov[k], na: false };
  const base = buildRequest(form);
  if (!base.ok) return { ok: false, errors: { _form: "Fix the highlighted inputs above first." } };
  const what = buildRequest(variant);
  if (!what.ok) {
    const errors: Record<string, string> = {};
    for (const k of touched) {
      const message = what.errors[OVERRIDE_FIELD[k] as string];
      if (message) errors[k] = message;
    }
    return { ok: false, errors: Object.keys(errors).length > 0 ? errors : { _form: "The changed values could not be read." } };
  }
  return { ok: true, body: { base: { ...base.body, targets: [] }, what_if: { ...what.body, targets: [] } } };
}
