import type { CiSummary, DataRequestItem, DigestSubscription, Layer1Alert, Layer1AlertsResponse, MarketOverview, MetricResult } from "@/lib/api";
import type { CiCandidate, CiChange, CiCompetitor, CiEventRow, CiFinding, CiPending, CiReviewInsight, CiWorkspace, EngineCell } from "@/lib/ciWorkspace";
import type { DemoRoute } from "../respond";
import { isoDaysAgo } from "./dates";

/** SAMPLE data for Competitor Intelligence and the Action Center: a fictional kitchen-storage seller ("Sample Home Goods"). Every figure is typed by hand.
 * Nothing here is computed, and nothing is a real competitor (all links are example.test). A mix of states is kept on purpose: some prices are verified from a
 * screenshot, some wait for the seller to confirm, some have no evidence at all, so the page reads honestly. */

const P1 = "demo-product-airtight-set";
const P2 = "demo-product-steel-bottle";

const cell = (valuePaise: number, ref: string): EngineCell => ({ valuePaise, engineResultRef: ref, isAvailable: true, unavailableReason: null });
const noCell = (ref: string, reason: string): EngineCell => ({ valuePaise: null, engineResultRef: ref, isAvailable: false, unavailableReason: reason });

const competitors = (): CiCompetitor[] => [
  {
    id: "demo-comp-1", findingId: "demo-find-1", label: "Kitchen Kraft 5-piece airtight set", marketplace: "AMAZON", identityMatch: "MATCHED", relationshipClass: "SAME_PRODUCT",
    relevanceBand: "HIGH", relevanceScore: 92, relevanceProvisional: false, evidenceDate: isoDaysAgo(1), freshness: "FRESH", priceStatus: "VERIFIED",
    listedPricePaise: 79900, availability: "IN_STOCK", ratingValue: "4.3", ratingCount: 2180, deltaPct: "-8.0", deltaDirection: "DECREASE", openQuestions: 0,
    effectivePrice: { effective: cell(74900, "demo:engine:eff-1"), buyerTotal: cell(74900, "demo:engine:buy-1"), deliveryChargePaise: 0, offers: [{ kind: "COUPON", amountPaise: 5000, conditional: false }], excludedOffers: [] },
  },
  {
    id: "demo-comp-2", findingId: "demo-find-2", label: "FreshLock steel containers (set of 4)", marketplace: "FLIPKART", identityMatch: "MATCHED", relationshipClass: "DIRECT_COMPETITOR",
    relevanceBand: "HIGH", relevanceScore: 85, relevanceProvisional: false, evidenceDate: isoDaysAgo(2), freshness: "FRESH", priceStatus: "VERIFIED",
    listedPricePaise: 69900, availability: "IN_STOCK", ratingValue: "4.1", ratingCount: 960, deltaPct: "4.5", deltaDirection: "INCREASE", openQuestions: 0,
    effectivePrice: { effective: cell(66900, "demo:engine:eff-2"), buyerTotal: cell(69900, "demo:engine:buy-2"), deliveryChargePaise: 3000, offers: [{ kind: "BANK_OFFER", amountPaise: 3000, conditional: true }], excludedOffers: [{ kind: "BANK_OFFER", reason: "needs a specific card" }] },
  },
  {
    id: "demo-comp-3", findingId: null, label: "HomeNest storage jars (6 pcs)", marketplace: "MEESHO", identityMatch: "LIKELY", relationshipClass: "DIRECT_COMPETITOR",
    relevanceBand: "MEDIUM", relevanceScore: 71, relevanceProvisional: true, evidenceDate: isoDaysAgo(3), freshness: "FRESH", priceStatus: "UNVERIFIED",
    listedPricePaise: 44900, availability: "IN_STOCK", ratingValue: "3.9", ratingCount: 410, deltaPct: null, deltaDirection: null, openQuestions: 2,
    effectivePrice: { effective: noCell("demo:engine:eff-3", "DELIVERY_CHARGE_NOT_OBSERVED"), buyerTotal: noCell("demo:engine:buy-3", "DELIVERY_CHARGE_NOT_OBSERVED"), deliveryChargePaise: null, offers: [], excludedOffers: [] },
  },
  {
    id: "demo-comp-4", findingId: "demo-find-4", label: "ChefMate premium jar set", marketplace: "AMAZON", identityMatch: "MATCHED", relationshipClass: "VARIANT",
    relevanceBand: "MEDIUM", relevanceScore: 64, relevanceProvisional: false, evidenceDate: isoDaysAgo(11), freshness: "STALE", priceStatus: "VERIFIED",
    listedPricePaise: 89900, availability: "LOW_STOCK", ratingValue: "4.5", ratingCount: 3320, deltaPct: null, deltaDirection: null, openQuestions: 0,
    effectivePrice: { effective: cell(89900, "demo:engine:eff-4"), buyerTotal: cell(89900, "demo:engine:buy-4"), deliveryChargePaise: 0, offers: [], excludedOffers: [] },
  },
  {
    id: "demo-comp-5", findingId: null, label: "UrbanPantry pantry organiser", marketplace: "FLIPKART", identityMatch: null, relationshipClass: "FUNCTIONAL_ALTERNATIVE",
    relevanceBand: "LOW", relevanceScore: 41, relevanceProvisional: true, evidenceDate: null, freshness: "UNAVAILABLE", priceStatus: "UNAVAILABLE",
    listedPricePaise: null, availability: null, ratingValue: null, ratingCount: null, deltaPct: null, deltaDirection: null, openQuestions: 1,
    effectivePrice: null,
  },
  {
    id: "demo-comp-6", findingId: "demo-find-6", label: "SteelSip insulated bottle 750 ml", marketplace: "AMAZON", identityMatch: "MATCHED", relationshipClass: "SAME_PRODUCT",
    relevanceBand: "HIGH", relevanceScore: 88, relevanceProvisional: false, evidenceDate: isoDaysAgo(4), freshness: "FRESH", priceStatus: "VERIFIED",
    listedPricePaise: 54900, availability: "IN_STOCK", ratingValue: "4.4", ratingCount: 5120, deltaPct: null, deltaDirection: null, openQuestions: 0,
    effectivePrice: { effective: cell(54900, "demo:engine:eff-6"), buyerTotal: cell(54900, "demo:engine:buy-6"), deliveryChargePaise: 0, offers: [], excludedOffers: [] },
  },
];

const candidates = (): CiCandidate[] => [
  { id: "demo-cand-1", title: "PureStore glass jar set", url: "https://pure.example.test/jars", identityNote: "Same capacity and lid type as your set", marketplace: "AMAZON", tier: "RECOMMENDED", identityMatch: "LIKELY", relationshipClass: "DIRECT_COMPETITOR", relevanceBand: "HIGH", relevanceScore: 80, relevanceProvisional: true, sellerDecision: "NONE", evidenceStatus: "AWAITING_EVIDENCE" },
  { id: "demo-cand-2", title: "DailyKeep kitchen canisters", url: "https://dailykeep.example.test/canisters", identityNote: null, marketplace: "FLIPKART", tier: "ANALYZED", identityMatch: null, relationshipClass: "FUNCTIONAL_ALTERNATIVE", relevanceBand: "MEDIUM", relevanceScore: 58, relevanceProvisional: true, sellerDecision: "NONE", evidenceStatus: "AWAITING_EVIDENCE" },
  { id: "demo-cand-3", title: "Brightway plastic container 10-pack", url: "https://brightway.example.test/10pack", identityNote: "Different material", marketplace: "MEESHO", tier: "RAW", identityMatch: null, relationshipClass: "UNKNOWN", relevanceBand: null, relevanceScore: null, relevanceProvisional: null, sellerDecision: "NONE", evidenceStatus: "AWAITING_EVIDENCE" },
];

const changes = (): CiChange[] => [
  { competitorId: "demo-comp-1", findingId: "demo-find-1", label: "Kitchen Kraft 5-piece airtight set", marketplace: "AMAZON", kind: "PRICE", deltaPaise: -6900, deltaPct: "-8.0", direction: "DECREASE", availabilityChange: null, occurredAt: isoDaysAgo(1), evidenceDate: isoDaysAgo(1) },
  { competitorId: "demo-comp-2", findingId: "demo-find-2", label: "FreshLock steel containers (set of 4)", marketplace: "FLIPKART", kind: "PRICE", deltaPaise: 3000, deltaPct: "4.5", direction: "INCREASE", availabilityChange: null, occurredAt: isoDaysAgo(2), evidenceDate: isoDaysAgo(2) },
  { competitorId: "demo-comp-4", findingId: "demo-find-4", label: "ChefMate premium jar set", marketplace: "AMAZON", kind: "AVAILABILITY", deltaPaise: 0, deltaPct: "0", direction: "NONE", availabilityChange: "IN_STOCK_TO_LOW_STOCK", occurredAt: isoDaysAgo(11), evidenceDate: isoDaysAgo(11) },
];

const reviewInsights = (): CiReviewInsight[] => [
  { competitorId: "demo-comp-1", findingId: "demo-find-3", label: "Kitchen Kraft 5-piece airtight set", complaintThemes: [{ theme: "lids crack after a few months" }, { theme: "smell of plastic when new" }], positiveThemes: [{ theme: "good size range" }, { theme: "stacks neatly" }], reviewsConsidered: 48, confidence: "MEDIUM", insightState: "FROM_PASTED_REVIEWS", evidenceDate: isoDaysAgo(5) },
  { competitorId: "demo-comp-6", findingId: "demo-find-6", label: "SteelSip insulated bottle 750 ml", complaintThemes: [{ theme: "paint chips on the cap" }], positiveThemes: [{ theme: "keeps water cold all day" }, { theme: "does not leak" }], reviewsConsidered: 36, confidence: "MEDIUM", insightState: "FROM_PASTED_REVIEWS", evidenceDate: isoDaysAgo(6) },
];

const pending = (): CiPending[] => [
  { id: "demo-pend-1", field: "Delivery charge for HomeNest storage jars", reason: "The screenshot does not show a delivery charge, so the buyer total cannot be worked out.", competitorId: "demo-comp-3", createdAt: isoDaysAgo(3), expiresAt: isoDaysAgo(-4) },
  { id: "demo-pend-2", field: "Price on UrbanPantry pantry organiser", reason: "No screenshot has been shared for this competitor yet.", competitorId: "demo-comp-5", createdAt: isoDaysAgo(8), expiresAt: isoDaysAgo(-2) },
];

const events = (): CiEventRow[] => [
  { id: "demo-ev-1", type: "ALERT_RAISED", occurredAt: isoDaysAgo(1), objectType: "competitor", objectId: "demo-comp-1", detail: {} },
  { id: "demo-ev-2", type: "EVIDENCE_RECEIVED", occurredAt: isoDaysAgo(1), objectType: "competitor", objectId: "demo-comp-1", detail: {} },
  { id: "demo-ev-3", type: "EVIDENCE_RECEIVED", occurredAt: isoDaysAgo(2), objectType: "competitor", objectId: "demo-comp-2", detail: {} },
  { id: "demo-ev-4", type: "FIELD_CONFIRMATION_REQUESTED", occurredAt: isoDaysAgo(3), objectType: "competitor", objectId: "demo-comp-3", detail: {} },
  { id: "demo-ev-5", type: "FIELD_CONFIRMED", occurredAt: isoDaysAgo(4), objectType: "competitor", objectId: "demo-comp-6", detail: {} },
  { id: "demo-ev-6", type: "COMPETITOR_ADDED", occurredAt: isoDaysAgo(9), objectType: "competitor", objectId: "demo-comp-5", detail: {} },
  { id: "demo-ev-7", type: "DISCOVERY_RUN_COMPLETED", occurredAt: isoDaysAgo(9), objectType: null, objectId: null, detail: {} },
];

const findings = (): CiFinding[] => [
  { id: "demo-find-1", type: "PRICE_CHANGE", competitorId: "demo-comp-1", freshness: "FRESH", confidence: "HIGH", sellerConfirmation: "NOT_REQUIRED", sampleSize: null, evidenceCount: 2, createdAt: isoDaysAgo(1),
    payload: { label: "Kitchen Kraft 5-piece airtight set", direction: "DECREASE", deltaPct: "-8.0", fromPricePaise: 86800, toPricePaise: 79900, evidenceDate: isoDaysAgo(1) } },
  { id: "demo-find-2", type: "PRICE_CHANGE", competitorId: "demo-comp-2", freshness: "FRESH", confidence: "HIGH", sellerConfirmation: "NOT_REQUIRED", sampleSize: null, evidenceCount: 1, createdAt: isoDaysAgo(2),
    payload: { label: "FreshLock steel containers (set of 4)", direction: "INCREASE", deltaPct: "4.5", fromPricePaise: 66900, toPricePaise: 69900, evidenceDate: isoDaysAgo(2) } },
  { id: "demo-find-3", type: "REVIEW_THEME", competitorId: "demo-comp-1", freshness: "FRESH", confidence: "MEDIUM", sellerConfirmation: "NOT_REQUIRED", sampleSize: 48, evidenceCount: 1, createdAt: isoDaysAgo(5),
    payload: { label: "Kitchen Kraft 5-piece airtight set", complaintThemes: [{ theme: "lids crack after a few months" }, { theme: "smell of plastic when new" }], evidenceDate: isoDaysAgo(5) } },
  { id: "demo-find-4", type: "AVAILABILITY_CHANGE", competitorId: "demo-comp-4", freshness: "STALE", confidence: "MEDIUM", sellerConfirmation: "NOT_REQUIRED", sampleSize: null, evidenceCount: 1, createdAt: isoDaysAgo(11),
    payload: { label: "ChefMate premium jar set", availabilityChange: "IN_STOCK_TO_LOW_STOCK", evidenceDate: isoDaysAgo(11) } },
  { id: "demo-find-5", type: "FRESHNESS", competitorId: "demo-comp-4", freshness: "STALE", confidence: "HIGH", sellerConfirmation: "NOT_REQUIRED", sampleSize: null, evidenceCount: 1, createdAt: isoDaysAgo(2),
    payload: { label: "ChefMate premium jar set", evidenceDate: isoDaysAgo(11) } },
  { id: "demo-find-6", type: "REVIEW_THEME", competitorId: "demo-comp-6", freshness: "FRESH", confidence: "MEDIUM", sellerConfirmation: "NOT_REQUIRED", sampleSize: 36, evidenceCount: 1, createdAt: isoDaysAgo(6),
    payload: { label: "SteelSip insulated bottle 750 ml", complaintThemes: [{ theme: "paint chips on the cap" }], evidenceDate: isoDaysAgo(6) } },
];

const workspace = (productId: string | null): CiWorkspace => {
  const selected = productId === P2 ? P2 : P1;
  const all = competitors();
  const rows = selected === P2 ? all.filter((c) => c.id === "demo-comp-6") : all.filter((c) => c.id !== "demo-comp-6");
  return {
    asOf: isoDaysAgo(0, 9),
    products: [{ productId: P1, title: "Airtight kitchen container set (5 pc)" }, { productId: P2, title: "Insulated steel bottle 750 ml" }],
    selectedProductId: selected,
    watchlist: { limit: 10, used: 6, free: 4 },
    kpis: { trackedCount: 6, verifiedCount: 4, needsEvidenceCount: 2, importantChangeCount: 3, reviewInsightCount: 2, pendingQuestionCount: 2 },
    competitors: rows,
    candidates: selected === P1 ? candidates() : [],
    reviewInsights: reviewInsights(),
    changes: changes(),
    pendingConfirmations: pending(),
    events: events(),
    findings: findings(),
    lastDiscovery: { status: "COMPLETE", partialReason: null, failedReason: null, provider: "web search", finishedAt: isoDaysAgo(9), rawCandidateCount: 14 },
  };
};

const band = (code: string, key: string, valuePaise: number): MetricResult => ({
  engineResultRef: `demo:engine:band-${key.toLowerCase()}`, metricCode: code, valuePaise, isAvailable: true, confidence: "MEDIUM",
  calculationBasis: `PriceBand ${key} from 5 competitors with a verified price (sample)`, unavailableReason: null, asOfDate: isoDaysAgo(1).slice(0, 10),
});
const market = (productId: string): MarketOverview => ({
  productId, trackedCompetitorCount: 6, minCompetitorsRequired: 3,
  rows: [band("PRICE_BAND_Q1", "Q1", 66900), band("PRICE_BAND_Q3", "Q3", 79900), band("PRICE_BAND_TYPICAL_LOW", "TYPICAL_LOW", 59900), band("PRICE_BAND_TYPICAL_HIGH", "TYPICAL_HIGH", 89900)],
});

const alertOf = (id: string, label: string, direction: "INCREASE" | "DECREASE", deltaPct: string, message: string, fact: string, implication: string, question: string, daysAgo: number): Layer1Alert => ({
  priceEventId: id, competitorUrlId: `demo-url-${id}`, competitorLabel: label, findingType: "PRICE_CHANGE", direction, deltaPct, availabilityChange: null, thresholdBreached: true, message, createdAt: isoDaysAgo(daysAgo),
  handoff: { findingId: `demo-alert-find-${id}`, findingType: "PRICE_CHANGE", validatedFact: [{ fact, confidence: "MEDIUM", capturedAt: isoDaysAgo(daysAgo), isStale: false }], evidenceRefs: [], competitorRefs: [], implication, suggestedAction: { targetAgent: "CFO", suggestedQuestion: question }, createdAt: isoDaysAgo(daysAgo), createdBy: "sample" },
});
const alerts = (): Layer1AlertsResponse => ({
  since: isoDaysAgo(14), until: isoDaysAgo(0),
  alerts: [
    alertOf("a1", "Kitchen Kraft 5-piece airtight set", "DECREASE", "-8.0", "Kitchen Kraft cut its price by 8.0%", "Listed price fell from ₹868.00 to ₹799.00", "Your set now sits above this competitor's price. Your margin at your current price is unchanged.", "What is my margin if I match Kitchen Kraft's new price?", 1),
    alertOf("a2", "FreshLock steel containers (set of 4)", "INCREASE", "4.5", "FreshLock raised its price by 4.5%", "Listed price rose from ₹669.00 to ₹699.00", "A competitor moved up, which may leave room in your price band.", "How much room do I have to raise my price?", 2),
    alertOf("a3", "SteelSip insulated bottle 750 ml", "DECREASE", "-6.2", "SteelSip cut its price by 6.2%", "Listed price fell from ₹585.00 to ₹549.00", "Your bottle is now priced above the closest same-product competitor.", "Compare my bottle price with SteelSip", 6),
    alertOf("a4", "ChefMate premium jar set", "INCREASE", "5.3", "ChefMate raised its price by 5.3%", "Listed price rose from ₹854.00 to ₹899.00", "The premium end of the band moved up.", "Where does my set sit in the price band now?", 12),
  ],
});

const dataRequests = (): DataRequestItem[] => [
  { id: "demo-req-1", requestedField: "Packaging cost per unit for the airtight set", reason: "Needed to work out contribution profit for this product", blockingMetric: "Contribution profit", status: "OPEN", createdAt: isoDaysAgo(2) },
  { id: "demo-req-2", requestedField: "GST rate for the insulated steel bottle", reason: "The GST on this product is not in your uploaded reports", blockingMetric: "GST on sales", status: "OPEN", createdAt: isoDaysAgo(4) },
  { id: "demo-req-3", requestedField: "Supplier quote for the 5-piece set", reason: "Needed to estimate landed cost", blockingMetric: "Landed cost", status: "OPEN", createdAt: isoDaysAgo(7) },
];

const summary = (): CiSummary => ({ trackedCompetitors: 6, lastResearchAt: isoDaysAgo(1, 9), recentPriceEvents7d: 3, pendingManualEntry: 2, staleCompetitors: 1 });
const digest = (): DigestSubscription => ({ frequency: "WEEKLY", channel: "IN_APP", enabled: true, lastSentAt: null, isDefault: true });

export const ciRoutes: DemoRoute[] = [
  { method: "GET", match: /^\/api\/v1\/ci\/summary$/, reply: () => summary() },
  { method: "GET", match: /^\/api\/v1\/ci\/workspace(\?|$)/, reply: (m) => workspace(decodeURIComponent((m.input ?? "").split("product_id=")[1] ?? "") || null) },
  { method: "GET", match: /^\/api\/v1\/ci\/market-overview\/([^/?]+)$/, reply: (m) => market(decodeURIComponent(m[1])) },
  { method: "GET", match: /^\/api\/v1\/ci\/alerts(\?|$)/, reply: () => alerts() },
  { method: "GET", match: /^\/api\/v1\/ci\/digest\/subscription$/, reply: () => digest() },
  { method: "GET", match: /^\/api\/v1\/cfo\/data-requests$/, reply: () => dataRequests() },
];
