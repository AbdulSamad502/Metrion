import { ApiError } from "@/lib/api";
import type {
  AnalyzeGstLinesResponse,
  AnomalyCheckResponse,
  BatchSizeResponse,
  BudgetStatus,
  CashReconciliationResponse,
  CfoPreviewResponse,
  ExpenseListResponse,
  FundingReadinessResponse,
  GstLookupResponse,
  GstPeriodSummaryResponse,
  ImportComponent,
  ImportDetail,
  ImportRow,
  ImportSummary,
  LandedCostResponse,
  MetricResult,
  PeriodComparisonResponse,
  PeriodPnlMetricResult,
  PeriodPnlResponse,
  PricingCurveResponse,
  ReconcileResponse,
  SupplierRankingResponse,
} from "@/lib/api";
import type { DemoRoute } from "../respond";
import { isoDaysAgo, monthBounds } from "./dates";

/** SAMPLE data for Profit & Finance: a fictional kitchen-storage seller, "Sample Home Goods", on Amazon, Flipkart and Meesho. Every figure below is a
 * hand-written constant in integer paise (₹1 = 100 paise); nothing is added, multiplied or derived in code, and the totals were checked by hand.
 * Request bodies are ignored: a sample answer never depends on what was typed. Writes (expenses, budget, goal, uploads, accepting a GST rate) are not
 * handled here, so they report that nothing is saved. */

const ref = (name: string) => `sample:${name}`;

const metric = (
  name: string,
  metricCode: string,
  valuePaise: number | null,
  confidence: string,
  calculationBasis: string,
  asOfDate: string | null,
  unavailableReason: string | null = null,
): MetricResult => ({
  engineResultRef: ref(name),
  metricCode,
  valuePaise,
  isAvailable: unavailableReason === null,
  confidence,
  calculationBasis,
  unavailableReason,
  asOfDate,
});

const pnlMoney = (...a: Parameters<typeof metric>): PeriodPnlMetricResult => ({ ...metric(...a), valueFraction: null });

const pct = (name: string, metricCode: string, valueFraction: string, confidence: string, calculationBasis: string, asOfDate: string): PeriodPnlMetricResult => ({
  ...metric(name, metricCode, null, confidence, calculationBasis, asOfDate),
  valueFraction,
});

// --- Imports ------------------------------------------------------------------------------------------------------------------------------------

const id = (n: string) => `sample-import-${n}`;

const SUMMARIES: ImportSummary[] = [
  { reportFileId: id("amz-settlement"), ingestionRunId: "sample-run-1", filename: "Amazon_Settlement_V2_last-month.csv", marketplace: "AMAZON", reportCategory: "SETTLEMENT", adapter: "amazon-settlement", adapterVersion: "v2", uploadedAt: isoDaysAgo(6), status: "VALIDATED", counts: { read: 7, accepted: 6, rejected: 1, duplicate: 0, persisted: 6 } },
  { reportFileId: id("amz-tax"), ingestionRunId: "sample-run-2", filename: "Amazon_MTR_B2C_last-month.csv", marketplace: "AMAZON", reportCategory: "TAX", adapter: "amazon-mtr", adapterVersion: "v1", uploadedAt: isoDaysAgo(6), status: "VALIDATED", counts: { read: 6, accepted: 6, rejected: 0, duplicate: 0, persisted: 6 } },
  { reportFileId: id("fk-settlement"), ingestionRunId: "sample-run-3", filename: "Flipkart_Settlement_last-month.xlsx", marketplace: "FLIPKART", reportCategory: "SETTLEMENT", adapter: "flipkart-settlement", adapterVersion: "v1", uploadedAt: isoDaysAgo(8), status: "VALIDATED", counts: { read: 6, accepted: 6, rejected: 0, duplicate: 0, persisted: 6 } },
  { reportFileId: id("fk-tax"), ingestionRunId: "sample-run-4", filename: "Flipkart_GST_Sales_last-month.xlsx", marketplace: "FLIPKART", reportCategory: "TAX", adapter: "flipkart-gst", adapterVersion: "v1", uploadedAt: isoDaysAgo(8), status: "VALIDATED", counts: { read: 6, accepted: 6, rejected: 0, duplicate: 0, persisted: 6 } },
  { reportFileId: id("msh-settlement"), ingestionRunId: "sample-run-5", filename: "Meesho_Payments_last-month.csv", marketplace: "MEESHO", reportCategory: "SETTLEMENT", adapter: "meesho-payments", adapterVersion: "v1", uploadedAt: isoDaysAgo(11), status: "VALIDATED", counts: { read: 6, accepted: 6, rejected: 0, duplicate: 0, persisted: 6 } },
  { reportFileId: id("msh-orders"), ingestionRunId: "sample-run-6", filename: "Meesho_Orders_two-months-ago.csv", marketplace: "MEESHO", reportCategory: "ORDER_STATUS", adapter: "meesho-orders", adapterVersion: "v1", uploadedAt: isoDaysAgo(40), status: "SUPERSEDED", counts: { read: 6, accepted: 6, rejected: 0, duplicate: 3, persisted: 3 } },
];

const fee = (code: string, amountPaise: number, taxAmountPaise: number | null, ratePct: string | null): ImportComponent => ({ kind: "FEE", code, side: "DEBIT", amountPaise, taxAmountPaise, ratePct });
const tax = (code: string, amountPaise: number, ratePct: string): ImportComponent => ({ kind: "TAX", code, side: "DEBIT", amountPaise, taxAmountPaise: null, ratePct });

const settle = (n: number, order: string, settlementId: string, grossSettlementAmountPaise: number, daysAgo: number, components: ImportComponent[]): ImportRow => ({
  settlementLineId: `sample-sl-${settlementId}-${n}`, sourceRowNumber: n, confidence: "VERIFIED", currency: "INR", orderRef: order, lineRef: `${order}-1`, settlementId, grossSettlementAmountPaise,
  settlementDate: isoDaysAgo(daysAgo), documentType: "SETTLEMENT", components,
});

const sale = (n: number, order: string, sku: string, itemTitle: string, quantity: number, gross: number, taxable: number, invoice: number, daysAgo: number, hsnSac: string, components: ImportComponent[]): ImportRow => ({
  salesLineId: `sample-sale-${order}`, sourceRowNumber: n, confidence: "VERIFIED", currency: "INR", orderRef: order, lineRef: `${order}-1`, invoiceRef: `INV-${order.slice(-5)}`, sku, itemTitle, hsnSac, quantity,
  grossItemAmountPaise: gross, taxableAmountPaise: taxable, totalInvoiceAmountPaise: invoice, orderDate: isoDaysAgo(daysAgo), invoiceDate: isoDaysAgo(daysAgo), documentType: "INVOICE", transactionType: "SHIPMENT", supplyType: "INTRA", components,
});

const AMZ_SETTLEMENT: ImportRow[] = [
  settle(1, "404-1102345-8800121", "AMZ-S-2201", 43120, 12, [fee("REFERRAL_FEE", 7500, 1350, "15.00"), fee("CLOSING_FEE", 2000, 360, null), fee("SHIPPING_FEE", 4500, 810, null)]),
  settle(2, "404-1102388-1930044", "AMZ-S-2201", 82350, 12, [fee("REFERRAL_FEE", 14400, 2592, "15.00"), fee("CLOSING_FEE", 2000, 360, null), fee("SHIPPING_FEE", 5400, 972, null)]),
  settle(3, "404-1103011-5521098", "AMZ-S-2201", 31870, 11, [fee("REFERRAL_FEE", 5400, 972, "15.00"), fee("CLOSING_FEE", 2000, 360, null)]),
  settle(4, "404-1103420-7719630", "AMZ-S-2202", 61290, 10, [fee("REFERRAL_FEE", 10800, 1944, "15.00"), fee("CLOSING_FEE", 2000, 360, null), fee("SHIPPING_FEE", 4900, 882, null)]),
  settle(5, "404-1104002-3344771", "AMZ-S-2202", 24960, 9, [fee("REFERRAL_FEE", 4500, 810, "15.00"), fee("CLOSING_FEE", 2000, 360, null)]),
  settle(6, "404-1104377-9082215", "AMZ-S-2202", 53740, 8, [fee("REFERRAL_FEE", 9600, 1728, "15.00"), fee("CLOSING_FEE", 2000, 360, null), fee("SHIPPING_FEE", 4700, 846, null)]),
];

const AMZ_TAX: ImportRow[] = [
  sale(1, "404-1102345-8800121", "SS-CONT-500", "Steel Storage Container 500 ml, set of 3", 1, 59900, 50763, 59900, 14, "7323", [tax("IGST", 9137, "18.00")]),
  sale(2, "404-1102388-1930044", "SS-CONT-1000", "Steel Storage Container 1 L, set of 3", 1, 99900, 84661, 99900, 14, "7323", [tax("IGST", 15239, "18.00")]),
  sale(3, "404-1103011-5521098", "SS-LUNCH-2", "Insulated Lunch Box, 2 tier", 1, 44900, 38051, 44900, 13, "3924", [tax("IGST", 6849, "18.00")]),
  sale(4, "404-1103420-7719630", "SS-CONT-1000", "Steel Storage Container 1 L, set of 3", 1, 99900, 84661, 99900, 12, "7323", [tax("IGST", 15239, "18.00")]),
  sale(5, "404-1104002-3344771", "SS-SPICE-6", "Spice Rack, 6 jars", 1, 34900, 29576, 34900, 11, "3924", [tax("IGST", 5324, "18.00")]),
  sale(6, "404-1104377-9082215", "SS-CONT-500", "Steel Storage Container 500 ml, set of 3", 1, 59900, 50763, 59900, 10, "7323", [tax("IGST", 9137, "18.00")]),
];

const FK_SETTLEMENT: ImportRow[] = [
  settle(1, "OD330021456", "FK-S-9101", 38750, 14, [fee("COMMISSION_FEE", 5400, 972, "10.00"), fee("FIXED_FEE", 2000, 360, null), fee("SHIPPING_FEE", 4100, 738, null)]),
  settle(2, "OD330022780", "FK-S-9101", 55420, 13, [fee("COMMISSION_FEE", 8000, 1440, "10.00"), fee("FIXED_FEE", 2000, 360, null), fee("SHIPPING_FEE", 4800, 864, null)]),
  settle(3, "OD330023911", "FK-S-9101", 27990, 12, [fee("COMMISSION_FEE", 3900, 702, "10.00"), fee("FIXED_FEE", 2000, 360, null)]),
  settle(4, "OD330025004", "FK-S-9102", 71600, 10, [fee("COMMISSION_FEE", 10000, 1800, "10.00"), fee("FIXED_FEE", 2000, 360, null), fee("SHIPPING_FEE", 5200, 936, null)]),
  settle(5, "OD330026338", "FK-S-9102", 33210, 9, [fee("COMMISSION_FEE", 4500, 810, "10.00"), fee("FIXED_FEE", 2000, 360, null)]),
  settle(6, "OD330027655", "FK-S-9102", 46880, 7, [fee("COMMISSION_FEE", 6400, 1152, "10.00"), fee("FIXED_FEE", 2000, 360, null), fee("SHIPPING_FEE", 4400, 792, null)]),
];

const FK_TAX: ImportRow[] = [
  sale(1, "OD330021456", "SS-CONT-500", "Steel Storage Container 500 ml, set of 3", 1, 54900, 46525, 54900, 16, "7323", [tax("IGST", 8375, "18.00")]),
  sale(2, "OD330022780", "SS-LUNCH-2", "Insulated Lunch Box, 2 tier", 1, 79900, 67712, 79900, 15, "3924", [tax("IGST", 12188, "18.00")]),
  sale(3, "OD330023911", "SS-SPICE-6", "Spice Rack, 6 jars", 1, 39900, 33814, 39900, 14, "3924", [tax("IGST", 6086, "18.00")]),
  sale(4, "OD330025004", "SS-CONT-1000", "Steel Storage Container 1 L, set of 3", 1, 99900, 84661, 99900, 12, "7323", [tax("IGST", 15239, "18.00")]),
  sale(5, "OD330026338", "SS-CONT-500", "Steel Storage Container 500 ml, set of 3", 1, 54900, 46525, 54900, 11, "7323", [tax("IGST", 8375, "18.00")]),
  sale(6, "OD330027655", "SS-LUNCH-2", "Insulated Lunch Box, 2 tier", 1, 79900, 67712, 79900, 9, "3924", [tax("IGST", 12188, "18.00")]),
];

const MSH_SETTLEMENT: ImportRow[] = [
  settle(1, "MSH-7710021", "MSH-P-501", 31900, 15, [fee("COMMISSION_FEE", 0, null, "0.00"), fee("SHIPPING_FEE", 5900, 1062, null)]),
  settle(2, "MSH-7710144", "MSH-P-501", 28900, 14, [fee("COMMISSION_FEE", 0, null, "0.00"), fee("SHIPPING_FEE", 5900, 1062, null)]),
  settle(3, "MSH-7710390", "MSH-P-501", 34900, 12, [fee("COMMISSION_FEE", 0, null, "0.00"), fee("SHIPPING_FEE", 6500, 1170, null)]),
  settle(4, "MSH-7710812", "MSH-P-502", 29900, 10, [fee("COMMISSION_FEE", 0, null, "0.00"), fee("SHIPPING_FEE", 5900, 1062, null)]),
  settle(5, "MSH-7711056", "MSH-P-502", 36900, 8, [fee("COMMISSION_FEE", 0, null, "0.00"), fee("SHIPPING_FEE", 6500, 1170, null)]),
  settle(6, "MSH-7711320", "MSH-P-502", 27900, 6, [fee("COMMISSION_FEE", 0, null, "0.00"), fee("SHIPPING_FEE", 5900, 1062, null)]),
];

const MSH_ORDERS: ImportRow[] = [
  sale(1, "MSH-7610020", "SS-SPICE-6", "Spice Rack, 6 jars", 1, 29900, 25339, 29900, 52, "3924", []),
  sale(2, "MSH-7610233", "SS-LUNCH-2", "Insulated Lunch Box, 2 tier", 1, 34900, 29576, 34900, 50, "3924", []),
  sale(3, "MSH-7610488", "SS-CONT-500", "Steel Storage Container 500 ml, set of 3", 1, 39900, 33814, 39900, 47, "7323", []),
];

const DETAILS: Record<string, { lineKind: ImportDetail["lineKind"]; rows: ImportRow[]; rejected: ImportDetail["rejected"] }> = {
  [id("amz-settlement")]: {
    lineKind: "SETTLEMENT_LINE",
    rows: AMZ_SETTLEMENT,
    rejected: { count: 1, diagnosticsPersisted: true, findingsTotal: 1, findings: [{ ruleId: "ROW_MISSING_ORDER_REF", severity: "WARNING", message: "Row 7 has no order reference, so it was not saved.", sourceRowNumber: 7 }] },
  },
  [id("amz-tax")]: { lineKind: "SALES_LINE", rows: AMZ_TAX, rejected: { count: 0, diagnosticsPersisted: true, findingsTotal: 0, findings: [] } },
  [id("fk-settlement")]: { lineKind: "SETTLEMENT_LINE", rows: FK_SETTLEMENT, rejected: { count: 0, diagnosticsPersisted: true, findingsTotal: 0, findings: [] } },
  [id("fk-tax")]: { lineKind: "SALES_LINE", rows: FK_TAX, rejected: { count: 0, diagnosticsPersisted: true, findingsTotal: 0, findings: [] } },
  [id("msh-settlement")]: { lineKind: "SETTLEMENT_LINE", rows: MSH_SETTLEMENT, rejected: { count: 0, diagnosticsPersisted: true, findingsTotal: 0, findings: [] } },
  [id("msh-orders")]: { lineKind: "SALES_LINE", rows: MSH_ORDERS, rejected: { count: 0, diagnosticsPersisted: true, findingsTotal: 0, findings: [] } },
};

function importDetail(reportFileId: string): ImportDetail {
  const summary = SUMMARIES.find((s) => s.reportFileId === reportFileId);
  const detail = DETAILS[reportFileId];
  if (!summary || !detail) throw new ApiError(404, "This import is not part of the sample data.");
  return {
    ...summary,
    lineKind: detail.lineKind,
    rows: detail.rows,
    pagination: { limit: 50, offset: 0, total: detail.rows.length },
    rejected: detail.rejected,
    originalCsv: { available: false, reason: "Sample data: no original file was uploaded." },
  };
}

// --- Period P&L, comparison, funding -----------------------------------------------------------------------------------------------------------------

const lastMonthEnd = () => monthBounds(1).end;

const PNL = (): PeriodPnlResponse => ({
  nrr: pnlMoney("pnl-nrr", "NET_REALIZED_REVENUE", 48632000, "VERIFIED", "NetRealizedRevenue (§5.5): settled sales across Amazon, Flipkart and Meesho for the period, after returns", lastMonthEnd()),
  contributionProfit: pnlMoney("pnl-contribution", "CONTRIBUTION_PROFIT", 10797000, "PROVISIONAL", "ContributionProfit (§5.8): net realized revenue less cost of goods (seller-entered), marketplace fees, shipping and ad spend", lastMonthEnd()),
  marginPct: pct("pnl-margin", "CONTRIBUTION_MARGIN_PCT", "22.20", "PROVISIONAL", "Contribution profit as a share of net realized revenue", lastMonthEnd()),
  feeRatioPct: pct("pnl-fee-ratio", "FEE_RATIO_PCT", "14.60", "VERIFIED", "Marketplace fees as a share of net realized revenue", lastMonthEnd()),
  returnRatePct: pct("pnl-return-rate", "RETURN_RATE_PCT", "6.80", "VERIFIED", "Returned units as a share of shipped units", lastMonthEnd()),
  marketplaceFeeFlags: [],
  dataRequestId: null,
  advertisingEntered: false,
  advertisingCostsPaise: null,
});

const COMPARISON = (): PeriodComparisonResponse => ({
  delta: metric("cmp-delta", "PERIOD_OVER_PERIOD_DELTA", 1121000, "PROVISIONAL", "Contribution profit, last month minus the month before", lastMonthEnd()),
  narration: "Contribution profit rose by ₹11,210.00 compared with the month before. The engine's figures behind this are the two contribution profit results listed above; this sentence only describes them.",
  dataRequestId: null,
});

const FUNDING = (): FundingReadinessResponse => ({
  contributionProfitHistory: [
    metric("fund-m1", "CONTRIBUTION_PROFIT", 10797000, "PROVISIONAL", "Contribution profit, 1 month ago", monthBounds(1).end),
    metric("fund-m2", "CONTRIBUTION_PROFIT", 9676000, "PROVISIONAL", "Contribution profit, 2 months ago", monthBounds(2).end),
    metric("fund-m3", "CONTRIBUTION_PROFIT", 8943000, "VERIFIED", "Contribution profit, 3 months ago", monthBounds(3).end),
    metric("fund-m4", "CONTRIBUTION_PROFIT", 7820000, "VERIFIED", "Contribution profit, 4 months ago", monthBounds(4).end),
    metric("fund-m5", "CONTRIBUTION_PROFIT", null, "PROVISIONAL", "Contribution profit, 5 months ago", monthBounds(5).end, "No settlement report was uploaded for this month."),
    metric("fund-m6", "CONTRIBUTION_PROFIT", 6590000, "VERIFIED", "Contribution profit, 6 months ago", monthBounds(6).end),
  ],
  trend: [metric("fund-trend", "PERIOD_OVER_PERIOD_DELTA", 1854000, "PROVISIONAL", "Contribution profit, 1 month ago less 3 months ago", lastMonthEnd())],
  gaps: [{ kind: "MISSING_PERIOD", period: monthBounds(5).start.slice(0, 7), reason: "No settlement report was uploaded for this month, so it is left out of the history instead of counted as zero." }],
  deferredSections: [
    { name: "Bank statement cross-check", reason: "Metrion does not read bank statements yet.", blockedOn: null },
    { name: "GST filing history", reason: "Metrion's GST view is indicative and is not a filing record.", blockedOn: null },
  ],
  dataRequestId: null,
});

// --- Pricing, landed cost, suppliers, batch size -----------------------------------------------------------------------------------------------------

const PRICING: PricingCurveResponse = {
  curve: [
    metric("price-399", "MARGIN_AT_PRICE", 8875, "DERIVED", "Margin per unit at ₹399.00 (after fees, shipping and landed cost)", null),
    metric("price-449", "MARGIN_AT_PRICE", 13125, "DERIVED", "Margin per unit at ₹449.00 (after fees, shipping and landed cost)", null),
    metric("price-499", "MARGIN_AT_PRICE", 17375, "DERIVED", "Margin per unit at ₹499.00 (after fees, shipping and landed cost)", null),
    metric("price-549", "MARGIN_AT_PRICE", 21625, "DERIVED", "Margin per unit at ₹549.00 (after fees, shipping and landed cost)", null),
    metric("price-599", "MARGIN_AT_PRICE", 25875, "DERIVED", "Margin per unit at ₹599.00 (after fees, shipping and landed cost)", null),
  ],
  dataRequestId: null,
};

const LANDED: LandedCostResponse = {
  result: metric("landed-cost", "LANDED_COST_PER_UNIT", 21240, "MANUAL", "LandedCost: supplier quote ₹168.00 + freight ₹22.40 + duty and GST ₹22.00 per unit (seller-entered quote)", null),
  dataRequestId: null,
};

const SUPPLIERS: SupplierRankingResponse = {
  ranked: [
    { result: metric("sup-1", "LANDED_COST_PER_UNIT", 21240, "MANUAL", "Landed cost per unit for this quote", null), supplierName: "Moradabad Steelware Co", reliabilityNote: "Delivered the last two batches on time (seller note).", paymentTerms: "30% advance, 70% on dispatch", leadTimeDays: 12, moq: 200 },
    { result: metric("sup-2", "LANDED_COST_PER_UNIT", 22650, "MANUAL", "Landed cost per unit for this quote", null), supplierName: "Pune Kitchenware Traders", reliabilityNote: null, paymentTerms: "50% advance, 50% on delivery", leadTimeDays: 9, moq: 100 },
    { result: metric("sup-3", "LANDED_COST_PER_UNIT", 23980, "MANUAL", "Landed cost per unit for this quote", null), supplierName: "Vapi Containers Pvt Ltd", reliabilityNote: "One late batch in the last year (seller note).", paymentTerms: "Full payment on order", leadTimeDays: 15, moq: 500 },
  ],
  quarantined: [{ adjustmentId: "sample-quote-4", supplierName: "Rajkot Metal Works", reason: "The quote has no unit price, so it cannot be ranked." }],
  isSingleQuote: false,
  dataRequestId: null,
};

const BATCH: BatchSizeResponse = {
  // The engine carries a unit COUNT in `valuePaise` for this metric (see compute_metric.py); the basis text says so, exactly as the real response does.
  result: metric("batch", "BATCH_CONSTRAINED_QUANTITY", 470, "MANUAL", "BudgetConstrainedQuantity: budget ₹1,00,000.00 ÷ landed cost ₹212.40 per unit, rounded down. A unit COUNT, not paise. Budget and MOQ only, no sales velocity.", null),
  landedCostResult: metric("batch-landed", "LANDED_COST_PER_UNIT", 21240, "MANUAL", "Landed cost per unit used for this estimate", null),
  velocityStatus: "OBSERVED",
  observedUnitsSold: 312,
  velocityUnavailableReason: null,
  referenceQuantity: 380,
  referenceQuantityBasis: "units sold over the last 60 days",
  referenceQuantityCaveatApplies: true,
  referenceQuantityCaveat: "The last 60 days include a festive sale, so this reference quantity may be higher than a normal two months.",
  leadTimeDays: 12,
  moq: 200,
  dataRequestId: null,
};

// --- Leaks, preview, anomaly, cash -------------------------------------------------------------------------------------------------------------------

const RECONCILE: ReconcileResponse = {
  reconciliationRunId: "sample-recon-run-1",
  findings: [
    { leakFindingId: "sample-leak-1", leakCategory: "FEE_OVERCHARGE", severity: "HIGH", windowStatus: "OPEN", amountPaise: 184200, marketplace: "AMAZON", engineResultRef: ref("leak-1") },
    { leakFindingId: "sample-leak-2", leakCategory: "RETURN_NOT_CREDITED", severity: "MEDIUM", windowStatus: "CLOSING_SOON", amountPaise: 96500, marketplace: "FLIPKART", engineResultRef: ref("leak-2") },
    { leakFindingId: "sample-leak-3", leakCategory: "SHORT_SETTLEMENT", severity: "MEDIUM", windowStatus: "OPEN", amountPaise: 41800, marketplace: "MEESHO", engineResultRef: ref("leak-3") },
    { leakFindingId: "sample-leak-4", leakCategory: "TCS_TDS_MISMATCH", severity: "LOW", windowStatus: "UNKNOWN", amountPaise: 12700, marketplace: "AMAZON", engineResultRef: ref("leak-4") },
  ],
  matchCount: 148,
  exceptionCount: 4,
  ambiguousMatchCount: 2,
  datesMissingCount: 0,
};

const PREVIEW: CfoPreviewResponse = {
  headlineTotalPaise: 335200,
  headlineEngineResultRef: ref("leak-total"),
  affectedSkuCount: 3,
  affectedSkuCountUnavailable: false,
  revealedFinding: { leakFindingId: "sample-leak-1", leakCategory: "FEE_OVERCHARGE", severity: "HIGH", windowStatus: "OPEN", amountPaise: 184200, marketplace: "AMAZON", engineResultRef: ref("leak-1"), sku: "SS-CONT-1000" },
  lockedFindingsCount: 3,
};

const flag = (idn: string, method: string, fired: boolean, severity: string | null, score: string): AnomalyCheckResponse["methods"][number]["flag"] => ({
  id: `sample-flag-${idn}`, metric: "CONTRIBUTION_MARGIN_PCT", targetRef: "ACCOUNT", period: "monthly", method, decoratesEngineResultRef: ref("pnl-margin"), sourceEngineResultRefs: [ref("pnl-margin")],
  score, fired, severity, dataConfidence: "PROVISIONAL", seriesLength: 6, minSeriesLengthRequired: 4, configVersion: "sample", formulaVersion: `${method}.v1`, asOfDate: lastMonthEnd(), computedAt: isoDaysAgo(0),
});

const ANOMALY: AnomalyCheckResponse = {
  targetRef: "ACCOUNT",
  metric: "CONTRIBUTION_MARGIN_PCT",
  seriesLength: 6,
  methods: [
    { method: "Z_SCORE", flag: flag("z", "Z_SCORE", false, null, "0.91"), insufficientHistory: null, zeroVariance: null, configurationGap: null },
    { method: "PERCENTILE_THRESHOLD", flag: flag("p", "PERCENTILE_THRESHOLD", true, "MEDIUM", "0.93"), insufficientHistory: null, zeroVariance: null, configurationGap: null },
    {
      method: "PERIOD_OVER_PERIOD_DELTA",
      flag: null,
      insufficientHistory: { metric: "CONTRIBUTION_MARGIN_PCT", method: "PERIOD_OVER_PERIOD_DELTA", targetRef: "ACCOUNT", seriesLength: 6, minSeriesLengthRequired: 8, reason: "Needs 8 months of history; 6 months are saved." },
      zeroVariance: null,
      configurationGap: null,
    },
  ],
  narration: "Contribution margin sits within its usual range on one method and above the 90th percentile of its own history on another. This describes the flags above; it does not add a figure.",
};

const CASH: CashReconciliationResponse = {
  cashReceived: metric("cash-received", "CASH_RECEIVED", 45872000, "VERIFIED", "CashReceived: settlement amounts credited in the period", lastMonthEnd()),
  cashExpected: metric("cash-expected", "CASH_EXPECTED", null, "PROVISIONAL", "CashExpected: needs an expected-settlement figure from the report", lastMonthEnd(), "None of the uploaded report types provides expected cash yet."),
  cashVariance: metric("cash-variance", "CASH_VARIANCE", null, "PROVISIONAL", "CashVariance: expected cash less cash received", lastMonthEnd(), "Cash expected is not available, so the variance cannot be calculated."),
  tcsCollected: metric("cash-tcs", "TCS_COLLECTED", 380100, "VERIFIED", "TCS collected by the marketplaces in the period", lastMonthEnd()),
  tdsDeducted: metric("cash-tds", "TDS_DEDUCTED", null, "PROVISIONAL", "TDS deducted by the marketplaces", lastMonthEnd(), "No uploaded report type records TDS yet."),
  settledWithinLagCount: 142,
  unsettledBeyondLagCount: 6,
  datesMissingCount: 0,
};

// --- GST ---------------------------------------------------------------------------------------------------------------------------------------------

const GST_DISCLAIMER = "Indicative management summary. Not a GST return. Not filing-grade. Verify with your tax professional.";

const GST_LINES: AnalyzeGstLinesResponse = {
  lines: [
    { lineRef: "SS-CONT-500", normalizedExclusivePaise: 50763, isAvailable: true, unavailableReason: null, ratePlausibilityMatched: true, ratePlausibilitySeverity: null, disclaimer: GST_DISCLAIMER },
    { lineRef: "SS-LUNCH-2", normalizedExclusivePaise: 38051, isAvailable: true, unavailableReason: null, ratePlausibilityMatched: false, ratePlausibilitySeverity: "MEDIUM", disclaimer: GST_DISCLAIMER },
    { lineRef: "SS-SPICE-6", normalizedExclusivePaise: null, isAvailable: false, unavailableReason: "No rate was given for this line, so it cannot be normalised.", ratePlausibilityMatched: null, ratePlausibilitySeverity: null, disclaimer: GST_DISCLAIMER },
  ],
};

const GST_SUMMARY = (): GstPeriodSummaryResponse => ({
  results: [metric("gst-summary", "GST_PERIOD_SUMMARY", 2314500, "DERIVED", "Indicative output GST on the sales lines supplied for the period", lastMonthEnd())],
  disclaimer: GST_DISCLAIMER,
});

const GST_LOOKUP: GstLookupResponse = {
  result: {
    id: "sample-gst-lookup-1",
    queryText: "Stainless steel kitchen storage container",
    sku: null,
    queryHsn: null,
    likelyRatePct: "18.00",
    likelyHsn: "7323",
    likelyCategory: "Table, kitchen or other household articles of iron or steel",
    ambiguityNote: "A plastic-lidded version may fall under HSN 3924 instead; check which applies to your product.",
    alternatives: [{ ratePct: "18.00", hsn: "3924", category: "Household articles of plastics" }],
    sourceUrl: "https://example.org/sample-gst-rate-source",
    sourceTitle: "Sample cited source (not a real page)",
    retrievedAt: isoDaysAgo(0),
    status: "PROVISIONAL",
    disclaimer: GST_DISCLAIMER,
  },
  noMatch: null,
  fromCache: false,
};

// --- Expenses and goal -------------------------------------------------------------------------------------------------------------------------------

const expense = (n: number, category: string, amountPaise: number, daysAgo: number, reason: string | null) => ({
  manualAdjustmentId: `sample-expense-${n}`, category, amountPaise, targetType: "ACCOUNT", targetRef: "default", createdAt: isoDaysAgo(daysAgo), createdBy: "sample-user", reason,
});

/** Entries total ₹86,450.00 = 3850000 + 1200000 + 642000 + 980000 + 1425000 + 230000 + 318000 (checked by hand; the total below is typed, not summed). */
const EXPENSES: ExpenseListResponse = {
  entries: [
    expense(1, "advertising", 3850000, 3, "Amazon sponsored products, this month"),
    expense(2, "advertising", 1200000, 9, "Flipkart ads"),
    expense(3, "packaging", 642000, 5, "Bubble wrap and boxes, 2 rolls"),
    expense(4, "storage", 980000, 12, "Warehouse rent share"),
    expense(5, "logistics", 1425000, 6, "Return pickups"),
    expense(6, "other", 230000, 7, "Petrol for delivery run"),
    expense(7, "packaging", 318000, 15, "Branded stickers"),
  ],
  totalPaise: 8645000,
};

const BUDGETS: Record<string, { spent: number; budget: number | null; remaining: number | null; exceeded: boolean }> = {
  advertising: { spent: 5050000, budget: 5500000, remaining: 450000, exceeded: false },
  packaging: { spent: 960000, budget: 800000, remaining: -160000, exceeded: true },
  storage: { spent: 980000, budget: null, remaining: null, exceeded: false },
  logistics: { spent: 1425000, budget: 1500000, remaining: 75000, exceeded: false },
  other: { spent: 230000, budget: null, remaining: null, exceeded: false },
};

function budgetStatus(path: string): BudgetStatus {
  const q = new URLSearchParams(path.split("?")[1] ?? "");
  const category = (q.get("category") ?? "advertising").toLowerCase();
  const b = BUDGETS[category] ?? BUDGETS.advertising;
  return {
    category,
    periodStart: q.get("period_start") ?? monthBounds(0).start,
    periodEnd: q.get("period_end") ?? monthBounds(0).end,
    spentPaise: b.spent,
    noBudgetSet: b.budget === null,
    budgetPaise: b.budget,
    remainingPaise: b.remaining,
    exceeded: b.exceeded,
    manualAdjustmentId: b.budget === null ? null : `sample-budget-${category}`,
  };
}

export const cfoRoutes: DemoRoute[] = [
  { method: "GET", match: /^\/api\/v1\/cfo\/imports(\?.*)?$/, reply: () => SUMMARIES },
  { method: "GET", match: /^\/api\/v1\/cfo\/imports\/([^?/]+)(\?.*)?$/, reply: (m) => importDetail(decodeURIComponent(m[1])) },
  { method: "GET", match: /^\/api\/v1\/cfo\/expenses(\?.*)?$/, reply: () => EXPENSES },
  { method: "GET", match: /^\/api\/v1\/cfo\/expenses\/budget-status(\?.*)?$/, reply: (m) => budgetStatus(m.input ?? "") },
  { method: "GET", match: /^\/api\/v1\/cfo\/seller-goal(\?.*)?$/, reply: () => ({ targetMarginPct: "25", priorityCategory: "Kitchen storage", note: "Hold margin above 25% while growing Flipkart." }) },
  { method: "POST", match: /^\/api\/v1\/cfo\/pnl(\?.*)?$/, reply: () => PNL() },
  { method: "POST", match: /^\/api\/v1\/cfo\/period-comparison(\?.*)?$/, reply: () => COMPARISON() },
  { method: "POST", match: /^\/api\/v1\/cfo\/funding-readiness(\?.*)?$/, reply: () => FUNDING() },
  { method: "POST", match: /^\/api\/v1\/cfo\/pricing(\?.*)?$/, reply: () => PRICING },
  { method: "POST", match: /^\/api\/v1\/cfo\/landed-cost(\?.*)?$/, reply: () => LANDED },
  { method: "POST", match: /^\/api\/v1\/cfo\/suppliers\/rank(\?.*)?$/, reply: () => SUPPLIERS },
  { method: "POST", match: /^\/api\/v1\/cfo\/batch-size(\?.*)?$/, reply: () => BATCH },
  { method: "POST", match: /^\/api\/v1\/cfo\/reconcile(\?.*)?$/, reply: () => RECONCILE },
  { method: "POST", match: /^\/api\/v1\/cfo\/preview(\?.*)?$/, reply: () => PREVIEW },
  { method: "POST", match: /^\/api\/v1\/cfo\/anomaly-check(\?.*)?$/, reply: () => ANOMALY },
  { method: "POST", match: /^\/api\/v1\/cfo\/cash-reconciliation(\?.*)?$/, reply: () => CASH },
  { method: "POST", match: /^\/api\/v1\/cfo\/gst\/analyze-lines(\?.*)?$/, reply: () => GST_LINES },
  { method: "POST", match: /^\/api\/v1\/cfo\/gst\/period-summary(\?.*)?$/, reply: () => GST_SUMMARY() },
  { method: "POST", match: /^\/api\/v1\/cfo\/gst-lookup(\?.*)?$/, reply: () => GST_LOOKUP },
];
