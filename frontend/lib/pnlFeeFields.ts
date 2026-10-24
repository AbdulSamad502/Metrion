/** The fee FIELDS each marketplace has, with labels and what each is charged on. Labels only: this file holds NO rate and NO amount (calculator.md N4: the
 * seller types every fee). It mirrors `calc_engine.formulas.pnl_scenario.fields`; `backend/tests/unit/test_pnl_fee_fields_parity.py` fails if the two drift.
 * One entry per line on purpose (that test reads this file). */

export type PnlMarketplace = "amazon" | "flipkart" | "meesho";
export type PnlFulfilment = "easy_ship" | "seller_flex" | "fba" | "self_ship";
export type PnlFeeField = { id: string; label: string; unit: "percent" | "flat"; chargedOn: "shipped" | "kept" | "rto_return"; quick: boolean; fulfilment: PnlFulfilment[] | null; help: string; tierable: boolean };

export const PNL_MARKETPLACES: { id: PnlMarketplace; label: string }[] = [
  { id: "amazon", label: "Amazon India" },
  { id: "flipkart", label: "Flipkart" },
  { id: "meesho", label: "Meesho" },
];

export const PNL_FULFILMENT: { id: PnlFulfilment; label: string }[] = [
  { id: "easy_ship", label: "Easy Ship" },
  { id: "seller_flex", label: "Seller Flex" },
  { id: "fba", label: "Fulfilled by Amazon (FBA)" },
  { id: "self_ship", label: "Self-ship" },
];

export const PNL_FEE_FIELDS: Record<PnlMarketplace, PnlFeeField[]> = {
  amazon: [
    { id: "referral", label: "Referral fee", unit: "percent", chargedOn: "shipped", quick: true, fulfilment: null, help: "Entered as a percentage of the price, excluding GST on the fee. Find it in your fee preview or a settlement report.", tierable: true },
    { id: "closing", label: "Closing fee", unit: "flat", chargedOn: "shipped", quick: true, fulfilment: null, help: "Fixed fee per order, excluding GST. Mark it not applicable if you are not charged one.", tierable: true },
    { id: "shipping", label: "Shipping / weight-handling fee", unit: "flat", chargedOn: "shipped", quick: true, fulfilment: ["easy_ship", "seller_flex", "self_ship"], help: "Per-order shipping charge for your weight and zone, excluding GST. For self-ship, your courier cost.", tierable: false },
    { id: "fba_fulfilment", label: "FBA fulfilment fee", unit: "flat", chargedOn: "shipped", quick: true, fulfilment: ["fba"], help: "Per-unit FBA pick-and-pack and weight handling, excluding GST.", tierable: false },
    { id: "reverse", label: "Return / RTO handling fee", unit: "flat", chargedOn: "rto_return", quick: false, fulfilment: null, help: "Charged per returned or RTO order, excluding GST.", tierable: false },
    { id: "other", label: "Other per-order fee", unit: "flat", chargedOn: "shipped", quick: false, fulfilment: null, help: "Any other charge per order, excluding GST.", tierable: false },
  ],
  flipkart: [
    { id: "commission", label: "Commission", unit: "percent", chargedOn: "shipped", quick: true, fulfilment: null, help: "Entered as a percentage of the price, excluding GST on the fee. Check your settlement report or rate card.", tierable: true },
    { id: "fixed_fee", label: "Fixed fee", unit: "flat", chargedOn: "shipped", quick: true, fulfilment: null, help: "Fixed fee per order, excluding GST. Mark it not applicable if you are not charged one.", tierable: true },
    { id: "collection_fee", label: "Collection / payment fee", unit: "percent", chargedOn: "shipped", quick: false, fulfilment: null, help: "Payment or COD collection fee as a percentage of the price, excluding GST.", tierable: false },
    { id: "shipping", label: "Shipping fee", unit: "flat", chargedOn: "shipped", quick: true, fulfilment: null, help: "Forward shipping per order for your weight and zone, excluding GST.", tierable: false },
    { id: "reverse", label: "Reverse shipping fee", unit: "flat", chargedOn: "rto_return", quick: false, fulfilment: null, help: "Charged per returned or RTO order, excluding GST.", tierable: false },
    { id: "other", label: "Other per-order fee", unit: "flat", chargedOn: "shipped", quick: false, fulfilment: null, help: "Any other charge per order, excluding GST.", tierable: false },
  ],
  meesho: [
    { id: "commission", label: "Commission", unit: "percent", chargedOn: "shipped", quick: true, fulfilment: null, help: "Entered as a percentage of the price, excluding GST. Mark it not applicable if your plan has none.", tierable: true },
    { id: "shipping", label: "Shipping charge", unit: "flat", chargedOn: "shipped", quick: true, fulfilment: null, help: "Shipping deducted per order for your weight, excluding GST.", tierable: false },
    { id: "reverse", label: "Return / RTO shipping charge", unit: "flat", chargedOn: "rto_return", quick: false, fulfilment: null, help: "Charged per returned or RTO order, excluding GST.", tierable: false },
    { id: "other", label: "Other platform fee", unit: "flat", chargedOn: "shipped", quick: true, fulfilment: null, help: "Any other per-order platform charge, excluding GST.", tierable: false },
  ],
};

/** The fee fields shown for a marketplace, Amazon fulfilment method and mode. */
export function activeFeeFields(marketplace: PnlMarketplace, fulfilment: PnlFulfilment, mode: "quick" | "detailed"): PnlFeeField[] {
  return PNL_FEE_FIELDS[marketplace].filter((f) => (f.fulfilment === null || (marketplace === "amazon" && f.fulfilment.includes(fulfilment))) && (mode === "detailed" || f.quick));
}
