import type { Comparison, CorrectionHistory, Dashboard, LinesPage, MappingItem, Mappings, MetricKey, MetricVals, PerfLine, Summary, TrendPoint, VersionAnalysis } from "@/lib/cmoPerformance";
import type { Compliance, ImagePage, ImageProducts, Report, StoredImage } from "@/lib/cmoImages";
import type { MarketOverview, NewsItem, Opportunity } from "@/lib/cmoMarket";
import type { DemoRoute } from "../respond";
import { dateDaysAgo, isoDaysAgo } from "./dates";

/** SAMPLE data for the three CMO workspace pages (listing performance, product images, market opportunities and news), for the fictional seller "Sample Home Goods". Every figure, score, source and
 * sentence below is written here by hand as an illustration. Nothing is measured, imported or researched; the real pages never show any of it. The one thing computed here is a daily split of a written
 * total, so the daily rows add up to the totals shown beside them. */

const query = (m: RegExpMatchArray) => new URL(m.input ?? "", "http://sample.test").searchParams;

// ------------------------------------------------------------------------------------------------ listing performance
const PRODUCT = "Steel Container Set, 6 pieces";
const REPORT_SKU = "SHG-KC6-AMZ";
const DAYS = 30;
/** Split a written total over the 30 days by fixed weights (largest remainder), so the days always add up to the total. */
const split = (total: number, weights: number[]): number[] => {
  const w = weights.reduce((a, b) => a + b, 0);
  const out = weights.map((x) => Math.floor((total * x) / w));
  const order = weights.map((x, i) => ({ i, r: (total * x) % w })).sort((a, b) => b.r - a.r || a.i - b.i);
  let left = total - out.reduce((a, b) => a + b, 0);
  for (const { i } of order) {
    if (left <= 0) break;
    out[i] += 1;
    left -= 1;
  }
  return out;
};
const TRAFFIC = [9, 10, 8, 9, 11, 12, 10, 9, 10, 8, 9, 11, 13, 12, 10, 9, 10, 9, 10, 12, 13, 14, 12, 10, 11, 10, 12, 14, 15, 13];
const BUYING = [8, 9, 9, 8, 10, 12, 11, 8, 9, 9, 8, 10, 12, 13, 9, 8, 9, 10, 9, 12, 14, 15, 11, 9, 10, 10, 12, 14, 16, 13];
const CUR = { impressions: 48200, clicks: 1180, orders: 96, units: 118, sales: 11264000 };
const PREV = { impressions: 41500, clicks: 905, orders: 71, units: 85, sales: 8312500 };
const rateBp = (a: number, b: number) => Math.floor((a * 10000) / b);
const impressions = split(CUR.impressions, TRAFFIC);
const clicks = split(CUR.clicks, TRAFFIC);
const orders = split(CUR.orders, BUYING);
const units = split(CUR.units, BUYING);
const sales = split(CUR.sales, BUYING);

const summary = (v: typeof CUR, start: number, end: number): Summary => ({
  periodStart: dateDaysAgo(start), periodEnd: dateDaysAgo(end), days: DAYS, coveredDays: DAYS, complete: true,
  metrics: {
    impressions: { state: "AVAILABLE", value: v.impressions, reason: null }, clicks: { state: "AVAILABLE", value: v.clicks, reason: null },
    ctr: { state: "AVAILABLE", value: rateBp(v.clicks, v.impressions), reason: null }, orders: { state: "AVAILABLE", value: v.orders, reason: null },
    cvr: { state: "AVAILABLE", value: rateBp(v.orders, v.clicks), reason: null }, units: { state: "AVAILABLE", value: v.units, reason: null }, sales: { state: "AVAILABLE", value: v.sales, reason: null },
  },
});
const diff = (a: number, b: number, rel: boolean) => ({ state: "AVAILABLE" as const, previous: b, current: a, difference: a - b, relativeBp: rel ? Math.floor((Math.abs(a - b) * 10000) / b) * (a < b ? -1 : 1) : null, direction: (a === b ? "SAME" : a > b ? "UP" : "DOWN") as "UP" | "DOWN" | "SAME" });
const comparison = (cur: typeof CUR, prev: typeof CUR): Comparison => ({
  impressions: diff(cur.impressions, prev.impressions, true), clicks: diff(cur.clicks, prev.clicks, true), ctr: diff(rateBp(cur.clicks, cur.impressions), rateBp(prev.clicks, prev.impressions), false),
  orders: diff(cur.orders, prev.orders, true), cvr: diff(rateBp(cur.orders, cur.clicks), rateBp(prev.orders, prev.clicks), false), units: diff(cur.units, prev.units, true), sales: diff(cur.sales, prev.sales, true),
});
const trend = (): TrendPoint[] => impressions.map((imp, i) => ({
  date: dateDaysAgo(DAYS - 1 - i), impressions: imp, clicks: clicks[i], ctr: imp > 0 ? rateBp(clicks[i], imp) : null, orders: orders[i], cvr: clicks[i] > 0 ? rateBp(orders[i], clicks[i]) : null, units: units[i], sales: sales[i],
}));

const products = [
  { sku: "SHG-KC-6", name: PRODUCT, marketplaces: ["AMAZON", "FLIPKART"], linked: ["AMAZON"] },
  { sku: "SHG-GJ-4", name: "Glass Jar Set with Bamboo Lids, 4 pieces", marketplaces: ["AMAZON"], linked: [] },
  { sku: "SHG-LB-1", name: "Steel Lunch Box, double wall", marketplaces: ["AMAZON", "MEESHO"], linked: [] },
];
const evidence = (metric: MetricKey, label: string, p: string, c: string) => ({ metric, label, previous: p, current: c, previousPeriod: `${dateDaysAgo(59)} to ${dateDaysAgo(30)}`, currentPeriod: `${dateDaysAgo(29)} to ${dateDaysAgo(0)}` });

function dashboard(m: RegExpMatchArray): Dashboard & { correctedRecords: number } {
  const q = query(m);
  return {
    filters: { marketplace: q.get("marketplace"), sku: q.get("sku"), start: dateDaysAgo(29), end: dateDaysAgo(0) }, aiCredits: 0, products, marketplaces: ["AMAZON", "FLIPKART", "MEESHO"],
    dataSpan: { lastImportAt: isoDaysAgo(1), first: dateDaysAgo(59), last: dateDaysAgo(0) }, source: "Sample: imported Amazon Business Report, SHG-KC6-AMZ (sample file)",
    current: summary(CUR, 29, 0), previous: summary(PREV, 59, 30), comparison: comparison(CUR, PREV), trend: trend(), correctedRecords: 1,
    insights: [
      { kind: "CTR_UP", what: "Click-through rate rose from 2.18% to 2.44% on the Steel Container Set (Amazon).",
        evidence: [evidence("ctr", "Click-through rate", "2.18%", "2.44%"), evidence("clicks", "Clicks", "905", "1,180")],
        whyItMatters: "More of the people who saw the listing opened it. The new title went live inside this window, so it may be one reason (possible, not measured).",
        nextStep: "Keep the current title and watch the next period before changing it again.", action: { kind: "TITLE", route: "cmo.title", label: "Review the title", ask: "What should I improve next in my Steel Container Set listing on Amazon?", draft: "x", product: PRODUCT, marketplace: "AMAZON" },
        limits: ["Two periods are compared. This does not show that the title caused the change."], measured: true, explanation: "Sample insight written by hand." },
      { kind: "CVR_FLAT", what: "Conversion stayed near 8% while clicks grew by about a third.", evidence: [evidence("cvr", "Conversion rate", "7.84%", "8.13%")],
        whyItMatters: "Visitors are buying at about the same rate, so the extra traffic turned into extra orders (possible, not measured).", nextStep: "Check the main image and the first bullet; they are what a visitor sees first.",
        action: { kind: "CONTENT", route: "cmo.content", label: "Ask what buyers ask", ask: "What questions will buyers ask about my Steel Container Set?", draft: "x", product: PRODUCT, marketplace: "AMAZON" },
        limits: ["Season, price, stock and advertising also move these figures."], measured: true, explanation: "Sample insight written by hand." },
    ],
    needs: [], limits: ["This compares two periods. It does not show that anything you changed caused the difference, and other things (season, price, stock, advertising, competitors) also move these figures.", "1 imported record is corrected; the numbers use the corrected value and the imported value is kept."],
    imports: [
      { id: "sample-import-2", marketplace: "AMAZON", sourceName: "sample-business-report-recent.csv", periodStart: dateDaysAgo(29), periodEnd: dateDaysAgo(0), rowsSaved: 30, rowsSkipped: 0, metrics: ["impressions", "clicks", "orders", "units", "sales"], importedAt: isoDaysAgo(1) },
      { id: "sample-import-1", marketplace: "AMAZON", sourceName: "sample-business-report-earlier.csv", periodStart: dateDaysAgo(59), periodEnd: dateDaysAgo(30), rowsSaved: 30, rowsSkipped: 0, metrics: ["impressions", "clicks", "orders", "units", "sales"], importedAt: isoDaysAgo(31) },
    ],
    never: "Metrion never estimates a number it was not given, and never says a listing change caused a result.",
  };
}

const ver = (id: string, number: number, created: number, live: number | null) => ({ versionId: id, number, createdAt: isoDaysAgo(created), wentLiveOn: live === null ? null : dateDaysAgo(live), confirmedAt: live === null ? null : isoDaysAgo(live) });
const mappings = (): Mappings => ({
  items: [
    { sku: "SHG-KC-6", product: PRODUCT, marketplace: "AMAZON", reportSku: REPORT_SKU, linkConfirmedAt: isoDaysAgo(20), versions: [ver("sample-v1", 1, 44, 42), ver("sample-v2", 2, 20, 18)], status: "COMPLETE", missing: [],
      history: { links: [{ reportSku: REPORT_SKU, confirmedAt: isoDaysAgo(20) }], golives: [{ versionId: "sample-v1", wentLiveOn: dateDaysAgo(42), confirmedAt: isoDaysAgo(41) }, { versionId: "sample-v2", wentLiveOn: dateDaysAgo(18), confirmedAt: isoDaysAgo(17) }] } },
    { sku: "SHG-GJ-4", product: "Glass Jar Set with Bamboo Lids, 4 pieces", marketplace: "AMAZON", reportSku: null, linkConfirmedAt: null, versions: [ver("sample-v3", 1, 12, null)], status: "NEEDS_CONFIRMATION",
      missing: ["which report SKU is this listing", "the date version 1 went live"], history: { links: [], golives: [] } },
  ] as MappingItem[],
  windowDays: 14, windowSetBy: "YOU", windowBounds: [7, 90], missing: [], hasImports: true, aiCredits: 0,
});

const vals = (i: number): MetricVals => ({ impressions: impressions[i], clicks: clicks[i], orders: orders[i], units: units[i], sales: sales[i] });
const CORRECTED_AT = 3; // the sample correction is on the row 3 days from the newest
const lineRows = (): PerfLine[] => impressions.map((_, k) => {
  const i = DAYS - 1 - k; // newest first
  const fixed = k === CORRECTED_AT;
  return { lineId: `sample-line-${k}`, importId: "sample-import-2", marketplace: "AMAZON", reportSku: REPORT_SKU, date: dateDaysAgo(k), original: fixed ? { ...vals(i), clicks: (vals(i).clicks ?? 0) + 12 } : vals(i), effective: vals(i), corrected: fixed,
    correctionId: fixed ? "sample-correction-1" : null, voided: false, sourceName: "sample-business-report-recent.csv", importedAt: isoDaysAgo(1) };
});
const lines = (m: RegExpMatchArray): LinesPage => {
  const q = query(m);
  const limit = Number(q.get("limit") ?? 25);
  const offset = Number(q.get("offset") ?? 0);
  const all = lineRows();
  return { marketplace: q.get("marketplace") ?? "AMAZON", reportSku: q.get("report_sku"), start: dateDaysAgo(29), end: dateDaysAgo(0), total: all.length, limit, offset, hasMore: offset + limit < all.length, lines: all.slice(offset, offset + limit),
    note: "A blank value means the report did not carry it. It is kept blank, never treated as zero.", aiCredits: 0 };
};
const correctionHistory = (): CorrectionHistory => ({
  corrections: [{ id: "sample-correction-1", lineId: `sample-line-${CORRECTED_AT}`, importId: "sample-import-2", sourceName: "sample-business-report-recent.csv", marketplace: "AMAZON", reportSku: REPORT_SKU, date: dateDaysAgo(CORRECTED_AT),
    previous: lineRows()[CORRECTED_AT].original, corrected: lineRows()[CORRECTED_AT].effective, voided: false, changed: ["clicks"], reason: "The report double-counted a test click burst; the seller's own dashboard shows the lower number.", supersedes: null, by: "Sample seller", at: isoDaysAgo(1, 14) }],
  limit: 25, offset: 0, hasMore: false, aiCredits: 0, note: "Every correction is kept with the value before, the value after, the reason and who made it. The imported value is never changed.",
});
const versions = (): VersionAnalysis => ({
  total: 2, limit: 25, offset: 0, hasMore: false, order: "asc", sku: "SHG-KC-6", marketplace: "AMAZON", product: PRODUCT, source: "Sample: imported Amazon Business Report", windowDays: 14, windowSetBy: "YOU", linked: REPORT_SKU, needs: [], aiCredits: 0,
  versions: [
    { versionId: "sample-v1", number: 1, createdAt: isoDaysAgo(44), source: "First complete listing", changedSection: null, wentLiveOn: dateDaysAgo(42), state: "NOT_ASSESSED", needs: [], reasons: ["There are no imported days before this version went live, so there is nothing to compare it with."] },
    { versionId: "sample-v2", number: 2, createdAt: isoDaysAgo(20), source: "Title rewritten", changedSection: "title", wentLiveOn: dateDaysAgo(18), state: "OBSERVED_COMPARABLE", needs: [], reasons: [],
      note: "The same 14 days before and after the date you confirmed. This shows what was observed, not what caused it.", previous: summary(PREV, 32, 19), following: summary(CUR, 17, 4), comparison: comparison(CUR, PREV),
      observations: ["Click-through rate was higher in the 14 days after this version went live than in the 14 days before.", "Orders were higher in the 14 days after."], insights: [], attribution: "NOT_ATTRIBUTED" },
  ],
});
const skuCandidates = () => ({ candidates: [
  { reportSku: REPORT_SKU, reportTitle: "Sample Home Goods Steel Container Set 6 pcs", rows: 60, firstOrder: dateDaysAgo(59), lastOrder: dateDaysAgo(0) },
  { reportSku: "SHG-GJ4-AMZ", reportTitle: "Sample Home Goods Glass Jar Set 4 pcs", rows: 44, firstOrder: dateDaysAgo(59), lastOrder: dateDaysAgo(2) },
  { reportSku: "SHG-LB1-AMZ", reportTitle: "Sample Home Goods Steel Lunch Box", rows: 31, firstOrder: dateDaysAgo(45), lastOrder: dateDaysAgo(1) },
], note: "These are the SKUs that appear in your own imported reports. Choose the one that is this product." });

// ------------------------------------------------------------------------------------------------ product images
const SHOTS = [["FRONT", "front view"], ["BACK", "back view"], ["SIDE", "side view"], ["ANGLE", "angled view"], ["DETAIL", "close-up detail"], ["SIZE", "size or dimensions visual"], ["USAGE", "in-use or lifestyle view"], ["PACKAGING", "packaging view"], ["OTHER", "other view"]].map(([key, label]) => ({ key, label }));
const LIMITS = { maxImages: 12, maxFilesPerRequest: 6 };
const imageProducts = (): ImageProducts => ({
  products: [
    { sku: "SHG-KC-6", name: PRODUCT, sets: [{ marketplace: "AMAZON", images: 4 }, { marketplace: "FLIPKART", images: 2 }, { marketplace: "MEESHO", images: 0 }] },
    { sku: "SHG-GJ-4", name: "Glass Jar Set with Bamboo Lids, 4 pieces", sets: [{ marketplace: "AMAZON", images: 0 }, { marketplace: "FLIPKART", images: 0 }, { marketplace: "MEESHO", images: 0 }] },
    { sku: "SHG-LB-1", name: "Steel Lunch Box, double wall", sets: [{ marketplace: "AMAZON", images: 0 }, { marketplace: "FLIPKART", images: 0 }, { marketplace: "MEESHO", images: 0 }] },
  ], marketplaces: ["AMAZON", "FLIPKART", "MEESHO"], shotTypes: SHOTS, limits: LIMITS,
});
const SET: [string, "PRIMARY" | "SECONDARY", string, number, number][] = [["front", "PRIMARY", "FRONT", 1600, 1600], ["angle", "SECONDARY", "ANGLE", 1500, 1500], ["detail", "SECONDARY", "DETAIL", 900, 900], ["usage", "SECONDARY", "USAGE", 1200, 1600]];
const stored = (n: number): StoredImage[] => SET.slice(0, n).map(([id, role, shot, w, h], i) => ({ assetId: `sample-img-${id}`, role, shotType: shot, position: i + 1, widthPx: w, heightPx: h, sha256: `sample${i}`.padEnd(64, "0"), fileUrl: `/sample-image/${id}`, assignedAt: isoDaysAgo(6 - i) }));
const dims = (c: number, l: number, v: number | null, o: number | null, b: number | null) => ({ clarity: c, lighting: l, visibility: v, composition: o, background: b });
const REPORT: Report = {
  method: "Fixed measurements over your own pictures (sample). No AI model reads them.", scoreState: "COMPLETE", score: 78, maxScore: 100, pointsEarned: 78, pointsAssessable: 100,
  dimensions: [
    { key: "clarity", label: "Image clarity", max: 20, state: "ASSESSED", earned: 17, assessableMax: 20, percent: 85, reason: null },
    { key: "lighting", label: "Lighting and exposure", max: 15, state: "ASSESSED", earned: 13, assessableMax: 15, percent: 87, reason: null },
    { key: "visibility", label: "Product visibility", max: 20, state: "ASSESSED", earned: 17, assessableMax: 20, percent: 85, reason: null },
    { key: "composition", label: "Composition and cropping", max: 15, state: "ASSESSED", earned: 11, assessableMax: 15, percent: 73, reason: null },
    { key: "background", label: "Background quality", max: 15, state: "ASSESSED", earned: 12, assessableMax: 15, percent: 80, reason: null },
    { key: "set", label: "Image-set consistency and coverage", max: 15, state: "ASSESSED", earned: 8, assessableMax: 15, percent: 53, reason: null },
  ],
  images: [
    { imageNumber: 1, imageId: "sample-img-front", role: "PRIMARY", shotType: "FRONT", widthPx: 1600, heightPx: 1600, dimensions: dims(92, 88, 90, 86, 94), notAssessed: {}, overlayCheck: "NONE_FOUND", overlayCheckConfidence: "LOW" },
    { imageNumber: 2, imageId: "sample-img-angle", role: "SECONDARY", shotType: "ANGLE", widthPx: 1500, heightPx: 1500, dimensions: dims(84, 90, 82, 78, 80), notAssessed: {}, overlayCheck: "NONE_FOUND", overlayCheckConfidence: "LOW" },
    { imageNumber: 3, imageId: "sample-img-detail", role: "SECONDARY", shotType: "DETAIL", widthPx: 900, heightPx: 900, dimensions: dims(64, 72, 70, null, null), notAssessed: { composition: "A close-up is not expected to show the whole product.", background: "Not applicable to a close-up." }, overlayCheck: "NONE_FOUND", overlayCheckConfidence: "LOW" },
    { imageNumber: 4, imageId: "sample-img-usage", role: "SECONDARY", shotType: "USAGE", widthPx: 1200, heightPx: 1600, dimensions: dims(80, 62, 66, null, null), notAssessed: { background: "A lifestyle picture has a scene, not a plain background." }, overlayCheck: "POSSIBLE_OVERLAY", overlayCheckConfidence: "LOW" },
  ],
  duplicateCheck: { state: "CHECKED", reason: null, pairs: [{ images: [1, 2], verdict: "NOT_ASSESSED", hashDistanceOf64: 11, colourDifference: 18, sameKindOfShot: false, reason: "They show different angles, so they are not counted as a repeat." }] },
  findings: [
    { imageNumber: 3, imageId: "sample-img-detail", role: "SECONDARY", shotType: "DETAIL", code: "BELOW_ZOOM_SIZE", severity: "MEDIUM", problem: "The image is under 1000 pixels on its long side", whyItMatters: "Larger images stay sharp when a buyer zooms in.", recommendation: "If you have the original, upload it at 1000 pixels or more on the long side.", evidence: { longSidePx: 900 }, isMarketplaceRequirement: false },
    { imageNumber: 4, imageId: "sample-img-usage", role: "SECONDARY", shotType: "USAGE", code: "TOO_DARK", severity: "MEDIUM", problem: "The product looks too dark", whyItMatters: "Buyers cannot judge colour or finish in a dark picture.", recommendation: "Shoot in even, brighter light or add a soft light source; avoid back-lighting.", evidence: { exposureMean: 62 }, isMarketplaceRequirement: false },
    { imageNumber: null, imageId: null, role: null, shotType: null, code: "SET_LACKS_SIZE", severity: "LOW", problem: "No picture shows the size of the set", whyItMatters: "Buyers of storage products often check whether the set fits their shelf.", recommendation: "Add a picture with a ruler or a hand for scale.", evidence: {}, isMarketplaceRequirement: false },
  ],
  missingShots: [{ code: "MISSING_SIZE", shotType: "SIZE", problem: "A size or dimensions picture would help", whyItMatters: "It answers the most common question before it is asked.", recommendation: "Add a picture that shows the size with a ruler or a hand for scale.", isMarketplaceRequirement: false }],
  notes: ["Sample report written by hand."],
};
const COMPLIANCE = (mp: "AMAZON" | "FLIPKART" | "MEESHO"): Compliance => ({ status: "NOT_ASSESSED", marketplace: mp, message: "No verified official image rule is recorded for this marketplace, so nothing is checked against marketplace requirements.", notAssessed: "Background colour, aspect ratio, file size, overlay and text rules, and category-specific image rules are NOT_ASSESSED: no verified official rule for them is recorded.", checks: [] });
function imagePage(m: RegExpMatchArray): ImagePage {
  const q = query(m);
  const sku = q.get("sku") ?? "SHG-KC-6";
  const mp = (q.get("marketplace") ?? "AMAZON") as "AMAZON" | "FLIPKART" | "MEESHO";
  const p = imageProducts().products.find((x) => x.sku === sku) ?? imageProducts().products[0];
  const n = p.sets.find((s) => s.marketplace === mp)?.images ?? 0;
  const images = stored(n);
  return {
    product: { sku: p.sku, name: p.name }, marketplace: mp, images, compliance: COMPLIANCE(mp), shotTypes: SHOTS, limits: LIMITS,
    review: n === 4 ? { reviewId: "sample-review-2", createdAt: isoDaysAgo(2), report: { ...REPORT, product: { sku: p.sku, name: p.name }, marketplace: mp }, isCurrent: true } : null,
    history: n === 4 ? [{ id: "sample-review-2", createdAt: isoDaysAgo(2), scoreState: "COMPLETE", score: 78, imageCount: 4, method: "fixed measurements" }, { id: "sample-review-1", createdAt: isoDaysAgo(9), scoreState: "COMPLETE", score: 64, imageCount: 3, method: "fixed measurements" }] : [],
    assignmentHistory: images.map((im, i) => ({ assetId: im.assetId, role: im.role, shotType: im.shotType, position: i + 1, at: im.assignedAt })),
    notes: ["Image quality is separate from marketplace compliance and from listing readiness.", "Nothing is edited, replaced or published; recommendations are advice."],
  };
}

// ------------------------------------------------------------------------------------------------ market opportunities and news
const rel = (level: "HIGH" | "MEDIUM" | "LOW" | "NOT_ASSESSED", reason: string, mp: ("AMAZON" | "FLIPKART" | "MEESHO")[], terms: string[]) =>
  ({ level, reason, affects: level === "NOT_ASSESSED" || level === "LOW" ? [] : [{ sku: "SHG-KC-6", name: PRODUCT, level, sharedTerms: terms, marketplaces: mp, reason }] });
const src = (url: string, title: string, days: number | null, cls: string) => ({ url, title, publishedAt: days === null ? null : isoDaysAgo(days), retrievedAt: isoDaysAgo(4), sourceClass: cls });
const NEWS: NewsItem[] = [
  { id: "sample-r2:n1", headline: "Sample: Amazon India updates its return window for home and kitchen", summary: "Sample note: the return window for some home and kitchen items changes. Read the source before acting.", newsKind: "POLICY", marketplaces: ["AMAZON"],
    sources: [src("https://sell.example.test/amazon/returns", "Returns policy update (sample)", 6, "OFFICIAL_MARKETPLACE")], publishedAt: dateDaysAgo(6), ageDays: 6, freshness: "FRESH", isStale: false, officialSource: true, sourceNote: "From an official marketplace source (sample).",
    impact: "A policy or rules update. It may change what you can list or how. Read the source and check your seller account before changing any listing.", relevance: rel("HIGH", "It concerns Amazon and your steel container set is sold there.", ["AMAZON"], ["steel", "container"]),
    reportId: "sample-r2", reportDate: dateDaysAgo(4), seenInReports: 2, independentSources: 1, corroboration: "SINGLE_SOURCE", limitation: null,
    recommendations: [{ agent: "YOU", text: "Open the source and read it yourself." }, { agent: "CMO", text: "Check your listing text for return wording.", ask: "Show my latest Steel Container Set listing on Amazon" }] },
  { id: "sample-r2:n2", headline: "Sample: Flipkart changes a referral fee band for kitchen storage", summary: "Sample note: a fee band for kitchen storage is revised. Check your own fee settings.", newsKind: "FEE", marketplaces: ["FLIPKART"],
    sources: [src("https://seller.example.test/flipkart/fees", "Fee notice (sample)", 21, "OFFICIAL_MARKETPLACE")], publishedAt: dateDaysAgo(21), ageDays: 21, freshness: "RECENT", isStale: false, officialSource: true, sourceNote: "From an official marketplace source (sample).",
    impact: "A fee update. It may change your costs. Check your fee settings and landed cost before changing a price.", relevance: rel("MEDIUM", "It concerns Flipkart, where your steel container set is listed.", ["FLIPKART"], ["kitchen"]),
    reportId: "sample-r2", reportDate: dateDaysAgo(4), seenInReports: 1, independentSources: 1, corroboration: "SINGLE_SOURCE", limitation: null,
    recommendations: [{ agent: "YOU", text: "Open the source and read it yourself." }, { agent: "CFO", text: "Check the margin after the new fee.", ask: "What is my profit by product?" }] },
  { id: "sample-r1:n3", headline: "Sample: Meesho opens a new seller programme for home products", summary: "Sample note: a programme for home sellers is announced; the date it started is not stated.", newsKind: "SELLER_PROGRAM", marketplaces: ["MEESHO"],
    sources: [src("https://supplier.example.test/meesho/programme", "Programme page (sample)", null, "OFFICIAL_MARKETPLACE")], publishedAt: null, ageDays: null, freshness: "DATE_UNKNOWN", isStale: false, officialSource: true, sourceNote: "From an official marketplace source (sample). It states no date.",
    impact: "A seller-programme update. It may open or close a programme you can join. Check eligibility in your seller account.", relevance: rel("NOT_ASSESSED", "Meesho is not a marketplace you have a saved listing on.", ["MEESHO"], []),
    reportId: "sample-r1", reportDate: dateDaysAgo(18), seenInReports: 1, independentSources: 1, corroboration: "SINGLE_SOURCE", limitation: "The source states no date, so it is not called fresh.",
    recommendations: [{ agent: "YOU", text: "Open the source and read it yourself." }] },
  { id: "sample-r1:n4", headline: "Sample: Festive season shopping starts earlier this year", summary: "Sample note: several outlets expect festive shopping to start earlier.", newsKind: "SEASONAL", marketplaces: [],
    sources: [src("https://news.example.test/festive", "Festive outlook (sample)", 75, "THIRD_PARTY")], publishedAt: dateDaysAgo(75), ageDays: 75, freshness: "STALE", isStale: true, officialSource: false, sourceNote: "From a third-party news source (sample); not an official announcement.",
    impact: "A seasonal or event update. It may change when buyers shop. Check the dates in your seller account before planning stock or promotions.", relevance: rel("LOW", "It names no marketplace and shares no words with your products.", [], []),
    reportId: "sample-r1", reportDate: dateDaysAgo(18), seenInReports: 1, independentSources: 1, corroboration: "SINGLE_SOURCE", limitation: "This item is old; check it is still true.",
    recommendations: [{ agent: "YOU", text: "Open the source and read it yourself." }] },
];
const DEMAND = { state: "UNAVAILABLE" as const, note: "Metrion holds no search-volume, sales or demand data for this topic, so none is shown." };
const OPPS: Opportunity[] = [
  { id: "sample-r2:o1", title: "Sample: Plastic-free kitchen storage for gifting", section: "ADJACENT", kind: "Adjacent topic", relevance: rel("HIGH", "It mentions steel containers, which you sell.", ["AMAZON", "FLIPKART"], ["steel", "container"]), rank: 1,
    rankedBecause: "Ranked by relevance to your products, then evidence strength, then freshness, with no score or forecast.", evidenceStrength: "MODERATE", evidenceStrengthWhy: "Reported by more than one independent source.", limitation: null,
    observed: { label: "What the saved sources reported (verified as reported, not as true)", summary: "Sample note: gifting articles feature plastic-free kitchen sets.", sources: [src("https://news.example.test/gift-a", "Gifting guide (sample)", 8, "THIRD_PARTY"), src("https://blog.example.test/gift-b", "Home blog (sample)", 12, "THIRD_PARTY")], independentSources: 2, freshestPublishedAt: dateDaysAgo(8), freshness: "FRESH", ageDays: 8, reportId: "sample-r2", reportDate: dateDaysAgo(4), seenInReports: 1 },
    possible: { label: "A possible explanation (not measured)", text: "Corroboration describes how widely attention is reported. It is not evidence of demand, sales or profit." }, demand: DEMAND,
    recommendations: [{ agent: "PI", text: "Research whether a gifting bundle exists.", ask: "Find product ideas I could sell" }, { agent: "CMO", text: "Mention the material in your title.", ask: "What should I improve next in my Steel Container Set listing on Amazon?" }, { agent: "CFO", text: "Check the margin of a bundle.", ask: "What is my profit by product?" }] },
  { id: "sample-r2:o2", title: "Sample: Airtight storage for monsoon freshness", section: "NICHE", kind: "Your niche", relevance: rel("MEDIUM", "It mentions airtight storage.", ["AMAZON"], ["airtight"]), rank: 2,
    rankedBecause: "Ranked by relevance to your products, then evidence strength, then freshness, with no score or forecast.", evidenceStrength: "WEAK", evidenceStrengthWhy: "Reported by a single source.", limitation: "One source only; treat it as a lead to check.",
    observed: { label: "What the saved sources reported (verified as reported, not as true)", summary: "Sample note: a seller forum thread discusses moisture-proof lids.", sources: [src("https://forum.example.test/threads/9", "Seller forum (sample)", 30, "THIRD_PARTY")], independentSources: 1, freshestPublishedAt: dateDaysAgo(30), freshness: "RECENT", ageDays: 30, reportId: "sample-r1", reportDate: dateDaysAgo(18), seenInReports: 1 },
    possible: { label: "A possible explanation (not measured)", text: "Corroboration describes how widely attention is reported. It is not evidence of demand, sales or profit." }, demand: DEMAND,
    recommendations: [{ agent: "CMO", text: "Check whether your bullets mention the lids.", ask: "Show my latest Steel Container Set listing on Amazon" }] },
];
function marketOverview(m: RegExpMatchArray): MarketOverview {
  const q = query(m);
  const mp = q.get("marketplace") as "AMAZON" | "FLIPKART" | "MEESHO" | null;
  const sku = q.get("sku");
  const news = NEWS.filter((n) => (!mp || n.marketplaces.includes(mp)) && (!sku || n.relevance.affects.some((a) => a.sku === sku) || n.relevance.level === "NOT_ASSESSED"));
  const opps = OPPS.filter((o) => (!mp || o.relevance.affects.some((a) => a.marketplaces.includes(mp))) && (!sku || o.relevance.affects.some((a) => a.sku === sku))).map((o, i) => ({ ...o, rank: i + 1 }));
  return { state: "OK", message: null, latestReportAt: dateDaysAgo(4), reportCount: 2, news, opportunities: opps, newsWithoutMarketplace: mp ? NEWS.filter((n) => n.marketplaces.length === 0).length : 0, filters: { sku, marketplace: mp },
    products: products.map((p) => ({ sku: p.sku, name: p.name, marketplaces: p.marketplaces as ("AMAZON" | "FLIPKART" | "MEESHO")[] })), marketplaces: ["AMAZON", "FLIPKART", "MEESHO"], today: dateDaysAgo(0), freshnessRules: { freshDays: 14, recentDays: 60, reportStaleDays: 30 },
    notes: ["Everything here comes from your own saved market-trend reports and your product details. Metrion searched nothing new and invented nothing.", "Corroboration describes how widely attention is reported. It is not demand, sales or profit; demand is UNAVAILABLE.", "Metrion never changes a marketplace listing or setting."], aiCredits: 0 };
}

const P = "/api/v1/cmo/performance";
export const cmoWorkspaceRoutes: DemoRoute[] = [
  { method: "GET", match: new RegExp(`^${P}/dashboard(\\?.*)?$`), reply: (m) => dashboard(m) },
  { method: "GET", match: new RegExp(`^${P}/mappings$`), reply: () => mappings() },
  { method: "GET", match: new RegExp(`^${P}/versions(\\?.*)?$`), reply: () => versions() },
  { method: "GET", match: new RegExp(`^${P}/lines(\\?.*)?$`), reply: (m) => lines(m) },
  { method: "GET", match: new RegExp(`^${P}/correction-history(\\?.*)?$`), reply: () => correctionHistory() },
  { method: "GET", match: new RegExp(`^${P}/sku-candidates(\\?.*)?$`), reply: () => skuCandidates() },
  { method: "GET", match: /^\/api\/v1\/cmo\/product-images\/products$/, reply: () => imageProducts() },
  { method: "GET", match: /^\/api\/v1\/cmo\/product-images\?.*$/, reply: (m) => imagePage(m) },
  { method: "GET", match: /^\/api\/v1\/cmo\/market-intelligence(\?.*)?$/, reply: (m) => marketOverview(m) },
];
