import { ApiError } from "@/lib/api";
import type { PiCase, PiFinancial, PiHistoryItem, PiProduct, PiReviewInsight, PiSupplierLead } from "@/lib/piShowcase";
import type { DemoRoute } from "../respond";
import { isoDaysAgo } from "./dates";

/** SAMPLE Product Intelligence research for a fictional kitchen-storage seller ("Sample Home Goods"). Every product, supplier, source and figure is made up.
 * Money is integer paise written by hand; scores and displays are literal strings. Nothing here is computed. Supplier prices are the supplier's own page, never a quote. */

const RUN_A = "5a1c0e11-2b3d-4f60-8a71-0c9d2e4b6f01";
const RUN_B = "5a1c0e11-2b3d-4f60-8a71-0c9d2e4b6f02";
const RUN_C = "5a1c0e11-2b3d-4f60-8a71-0c9d2e4b6f03";

type Spec = {
  title: string;
  category: string;
  proxy: string;
  final: string;
  webAvg: number | null;
  sources: number;
  videos: number;
  views: number;
  comments: number;
  why: string[];
  pros: string[];
  cons: string[];
  split: { positive: string; negative: string };
  supplier: { name: string; locality: string; phone: string | null; low: number; high: number; unit: string } | null;
  spread: { low: number; high: number } | null;
  gaps: string[];
  financials?: PiFinancial[];
};

const SAMPLE_IMAGES: [string, string][] = [["Stainless steel airtight", "container"], ["Borosilicate glass", "jars"], ["Collapsible silicone", "boxes"], ["Rotating spice", "rack"], ["Under-sink", "basket"], ["Double-wall steel lunch", "lunchbox"], ["3-tier stainless", "tiffin"], ["Insulated bag", "bag"], ["Kids 4-compartment", "plate"], ["Vacuum insulated", "flask"], ["Wall-mounted spice", "shelf"], ["Magnetic spice", "tins"], ["Tiered stainless", "dabba"], ["Glass spice bottles", "bottles"], ["Over-the-door", "doorrack"]];
/** Fake product pictures (drawn locally, not photographs) so the layout can be judged with images. Real runs carry hotlinked, attributed photos. */
function sampleImage(title: string): string | null {
  const hit = SAMPLE_IMAGES.find(([k]) => title.startsWith(k));
  return hit ? `/demo-products/${hit[1]}.svg` : null;
}

const DEMAND_REASON = "Search-demand data is not available in this plan.";

function supplierLead(runKey: string, rank: number, s: NonNullable<Spec["supplier"]>, days: number): PiSupplierLead {
  return {
    id: `sample-lead-${runKey}-${rank}`,
    supplier_name: s.name,
    source: "INDIAMART_LOOKUP",
    locality: s.locality,
    source_url: `https://suppliers.example.test/${runKey}/${rank}`,
    fetched_at: isoDaysAgo(days),
    evidence_fields: ["supplier_name", "locality", "published_price"],
    contact: {
      phone: s.phone,
      website: `https://suppliers.example.test/${runKey}/${rank}`,
      moq: s.phone ? { published: true } : null,
      published_price: {
        low_paise: s.low,
        high_paise: s.high,
        sample_count: 3,
        unit: s.unit,
        source_url: `https://suppliers.example.test/${runKey}/${rank}`,
        captured_at: isoDaysAgo(days),
        disclaimer: "Price published on the supplier's own page. Not a quote.",
      },
    },
  };
}

function build(runKey: string, days: number, specs: Spec[]): PiProduct[] {
  return specs.map((s, i) => {
    const rank = i + 1;
    const id = `sample-cand-${runKey}-${rank}`;
    const lead = s.supplier ? supplierLead(runKey, rank, s.supplier, days) : null;
    const insights: PiReviewInsight[] = [
      {
        insight_source_type: "YOUTUBE_COMMENTARY",
        insight_state: "AVAILABLE",
        sentiment_split: s.split,
        positive_themes: s.pros,
        complaint_themes: s.cons,
        reviews_considered: 140,
      },
      {
        insight_source_type: "WEB_EDITORIAL",
        insight_state: "AVAILABLE",
        sentiment_split: null,
        positive_themes: s.pros.slice(0, 2),
        complaint_themes: s.cons.slice(0, 1),
        reviews_considered: 12,
      },
    ];
    return {
      rank,
      candidate: {
        id,
        candidate_title: s.title,
        observed_category: s.category,
        image_url: sampleImage(s.title),
        image_source_url: "https://images.example.test/sample-photo",
        proxy_score: s.proxy,
        web_price_signal: s.webAvg === null
          ? { status: "UNAVAILABLE" }
          : { status: "AVAILABLE", average_paise: s.webAvg, sample_count: 4, most_recent_mention: isoDaysAgo(days + 2), disclaimer: "Prices mentioned on web pages. Not verified." },
        candidate_marketplaces: ["AMAZON", "FLIPKART"],
        source_urls: [
          { url: `https://reviews.example.test/${runKey}/${rank}`, source: "web", fetched_at: isoDaysAgo(days) },
          { url: `https://videos.example.test/${runKey}/${rank}`, source: "youtube", fetched_at: isoDaysAgo(days) },
          { url: `https://blog.example.test/${runKey}/${rank}`, source: "web", fetched_at: isoDaysAgo(days) },
        ],
        source_diversity: s.sources,
        engagement_signal: { status: "AVAILABLE", video_count: s.videos, view_count: s.views, comment_count: s.comments, source: "youtube" },
        demand_signal: { status: "UNAVAILABLE", reason: DEMAND_REASON },
        score_explanation: {
          summary: "Stage 1 proxy score from public web signal.",
          signals: [
            { signal: "source.diversity", status: "AVAILABLE", points: "18.00", max_points: 25, reason: `${s.sources} independent sources mention this product.` },
            { signal: "youtube.engagement", status: "AVAILABLE", points: "20.00", max_points: 30, reason: "Several videos with active comment threads." },
            { signal: "search.demand", status: "UNAVAILABLE", points: "0", max_points: 25, reason: DEMAND_REASON },
          ],
        },
        feasibility_status: s.spread ? "COMPUTED" : "UNAVAILABLE",
        feasibility_low_paise: s.spread?.low ?? null,
        feasibility_high_paise: s.spread?.high ?? null,
        feasibility_cogs_basis: s.spread ? "ESTIMATE_BEFORE_PRODUCT_COST" : null,
        feasibility_unavailable_reason: s.spread ? null : "Needs a price band from the seller",
      },
      reviewInsights: insights,
      supplierLeads: lead ? [lead] : [],
      bestSupplierLeadId: lead?.id ?? null,
      finalScore: s.final,
      finalScoreState: "COMPUTED",
      financials: s.financials ?? [],
      recommendation: {
        candidate_id: id,
        rank,
        title: s.title,
        final_score: s.final,
        final_score_state: "COMPUTED",
        why_ranked: s.why,
        pros: s.pros,
        cons: s.cons,
        supplier_option: lead,
        gaps: s.gaps,
        note: "Opportunity candidate from public web signal. Not a purchase instruction.",
      },
    };
  });
}

const QUOTE_FIN: PiFinancial[] = [
  { kind: "ENGINE", authoritative: true, leg_key: "cfo.landed_cost", label: "Landed cost per unit", display: "₹218.40", status: "COMPLETE", as_of: isoDaysAgo(2), note: "From your confirmed supplier quote" },
  { kind: "ENGINE", authoritative: true, leg_key: "cfo.batch_size", label: "Units to buy (budget ceiling)", display: "640 units", status: "COMPLETE", as_of: isoDaysAgo(2), note: "A budget ceiling, not a forecast" },
  { kind: "GAP", authoritative: false, leg_key: "cfo.net_margin", label: "Net margin", display: null, status: "UNAVAILABLE", reason: "Needs a selling price after fees and tax", as_of: null },
];

const A: Spec[] = [
  { title: "Stainless steel airtight kitchen container set, 6 pieces", category: "Kitchen storage", proxy: "74.00", final: "86.00", webAvg: 129900, sources: 5, videos: 14, views: 182000, comments: 2310,
    why: ["Mentioned by 5 independent sources", "Strong video engagement with active comments", "A supplier lead publishes its price"],
    pros: ["tight seal", "does not hold odours", "stacks neatly"], cons: ["lids are hard to open when new"], split: { positive: "78%", negative: "22%" },
    supplier: { name: "Sample Metalware Traders", locality: "Moradabad", phone: "+91 90000 00001", low: 18500, high: 21000, unit: "piece" },
    spread: { low: 38000, high: 52000 }, gaps: ["Search-demand data is not available"], financials: QUOTE_FIN },
  { title: "Borosilicate glass storage jars with bamboo lids, set of 4", category: "Kitchen storage", proxy: "69.00", final: "81.00", webAvg: 99900, sources: 4, videos: 9, views: 96000, comments: 1180,
    why: ["Mentioned by 4 independent sources", "Steady commentary across videos"],
    pros: ["looks good on a counter", "easy to clean"], cons: ["bamboo lids warp if washed in water", "glass can chip"], split: { positive: "71%", negative: "29%" },
    supplier: { name: "Sample Glassworks", locality: "Firozabad", phone: null, low: 14000, high: 16500, unit: "set" },
    spread: { low: 29000, high: 41000 }, gaps: ["No supplier phone number was published"] },
  { title: "Collapsible silicone food storage boxes, 3 sizes", category: "Kitchen storage", proxy: "63.00", final: "75.00", webAvg: 79900, sources: 3, videos: 6, views: 41000, comments: 520,
    why: ["Growing video interest", "Light to ship"],
    pros: ["saves cupboard space", "light weight"], cons: ["thin lids", "stains from curry"], split: { positive: "66%", negative: "34%" },
    supplier: { name: "Sample Polymers", locality: "Vapi", phone: "+91 90000 00003", low: 9000, high: 12000, unit: "set" },
    spread: null, gaps: ["Needs a price band from the seller"] },
  { title: "Rotating spice rack organiser, 16 jars", category: "Kitchen storage", proxy: "58.00", final: "70.00", webAvg: 149900, sources: 3, videos: 5, views: 28000, comments: 340,
    why: ["Popular in kitchen-makeover videos"], pros: ["fits small kitchens", "good gift"], cons: ["spinning base wobbles", "jars are small"], split: { positive: "62%", negative: "38%" },
    supplier: null, spread: { low: 45000, high: 63000 }, gaps: ["No supplier lead was found for this product"] },
  { title: "Under-sink pull-out storage basket", category: "Kitchen storage", proxy: "52.00", final: "64.00", webAvg: null, sources: 2, videos: 3, views: 12000, comments: 140,
    why: ["Mentioned by 2 sources"], pros: ["uses dead space"], cons: ["fitting takes time", "rails rust in humid kitchens"], split: { positive: "55%", negative: "45%" },
    supplier: { name: "Sample Fittings Co", locality: "Pune", phone: "+91 90000 00005", low: 22000, high: 22000, unit: "piece" },
    spread: null, gaps: ["No web price mention was found", "Needs a price band from the seller"] },
];

const B: Spec[] = [
  { title: "Double-wall steel lunch box with leak-proof lid", category: "Lunch boxes", proxy: "72.00", final: "84.00", webAvg: 109900, sources: 5, videos: 11, views: 143000, comments: 1650,
    why: ["Mentioned by 5 independent sources", "Strong commentary"], pros: ["keeps food warm", "no plastic smell"], cons: ["heavy for children"], split: { positive: "75%", negative: "25%" },
    supplier: { name: "Sample Steelcraft", locality: "Rajkot", phone: "+91 90000 00006", low: 16000, high: 19000, unit: "piece" }, spread: { low: 31000, high: 44000 }, gaps: [] },
  { title: "3-tier stainless tiffin carrier", category: "Lunch boxes", proxy: "66.00", final: "78.00", webAvg: 89900, sources: 4, videos: 8, views: 77000, comments: 900,
    why: ["Mentioned by 4 sources"], pros: ["classic and durable", "easy to carry"], cons: ["handle loosens over time"], split: { positive: "70%", negative: "30%" },
    supplier: { name: "Sample Utensils House", locality: "Jamnagar", phone: null, low: 13000, high: 15500, unit: "piece" }, spread: { low: 25000, high: 36000 }, gaps: ["No supplier phone number was published"] },
  { title: "Insulated bag with two steel containers", category: "Lunch boxes", proxy: "60.00", final: "72.00", webAvg: 119900, sources: 3, videos: 5, views: 30000, comments: 410,
    why: ["Office-lunch demand in videos"], pros: ["bag included", "keeps shape"], cons: ["bag zip is weak"], split: { positive: "64%", negative: "36%" },
    supplier: { name: "Sample Carry Goods", locality: "Mumbai", phone: "+91 90000 00008", low: 20000, high: 24000, unit: "set" }, spread: null, gaps: ["Needs a price band from the seller"] },
  { title: "Kids 4-compartment steel plate lunch box", category: "Lunch boxes", proxy: "55.00", final: "66.00", webAvg: 69900, sources: 2, videos: 4, views: 19000, comments: 260,
    why: ["Mentioned by 2 sources"], pros: ["good size for portions"], cons: ["lid does not seal fully"], split: { positive: "58%", negative: "42%" },
    supplier: null, spread: null, gaps: ["No supplier lead was found for this product", "Needs a price band from the seller"] },
  { title: "Vacuum insulated food jar, 500 ml", category: "Lunch boxes", proxy: "50.00", final: "61.00", webAvg: 129900, sources: 2, videos: 3, views: 15000, comments: 190,
    why: ["Mentioned by 2 sources"], pros: ["keeps soup hot for hours"], cons: ["narrow mouth is hard to clean"], split: { positive: "60%", negative: "40%" },
    supplier: { name: "Sample Thermoware", locality: "Delhi", phone: "+91 90000 00010", low: 21000, high: 26000, unit: "piece" }, spread: null, gaps: ["Needs a price band from the seller"] },
];

const C: Spec[] = [
  { title: "Wall-mounted spice shelf, bamboo", category: "Spice storage", proxy: "61.00", final: "73.00", webAvg: 89900, sources: 3, videos: 5, views: 33000, comments: 380,
    why: ["Mentioned by 3 sources"], pros: ["easy to fit", "looks tidy"], cons: ["bamboo scratches"], split: { positive: "68%", negative: "32%" },
    supplier: { name: "Sample Woodworks", locality: "Saharanpur", phone: "+91 90000 00011", low: 11000, high: 14000, unit: "piece" }, spread: { low: 22000, high: 31000 }, gaps: [] },
  { title: "Magnetic spice tins with clear lids, set of 12", category: "Spice storage", proxy: "57.00", final: "69.00", webAvg: 109900, sources: 3, videos: 4, views: 21000, comments: 250,
    why: ["Mentioned by 3 sources"], pros: ["see contents at a glance"], cons: ["magnets weak on thin fridge doors"], split: { positive: "63%", negative: "37%" },
    supplier: null, spread: null, gaps: ["No supplier lead was found for this product"] },
  { title: "Tiered stainless steel masala dabba", category: "Spice storage", proxy: "54.00", final: "65.00", webAvg: 79900, sources: 2, videos: 3, views: 14000, comments: 170,
    why: ["Mentioned by 2 sources"], pros: ["traditional and sturdy"], cons: ["small spoons are easy to lose"], split: { positive: "59%", negative: "41%" },
    supplier: { name: "Sample Brassware", locality: "Aligarh", phone: null, low: 8500, high: 10000, unit: "piece" }, spread: null, gaps: ["No supplier phone number was published"] },
  { title: "Glass spice bottles with shaker lids, set of 8", category: "Spice storage", proxy: "49.00", final: "60.00", webAvg: null, sources: 2, videos: 2, views: 8000, comments: 90,
    why: ["Mentioned by 2 sources"], pros: ["good for gifting"], cons: ["lids crack"], split: { positive: "52%", negative: "48%" },
    supplier: null, spread: null, gaps: ["No supplier lead was found for this product", "No web price mention was found"] },
  { title: "Over-the-door spice rack, 4 tiers", category: "Spice storage", proxy: "44.00", final: "55.00", webAvg: 59900, sources: 2, videos: 2, views: 6000, comments: 70,
    why: ["Mentioned by 2 sources"], pros: ["no drilling"], cons: ["door will not close on some cupboards"], split: { positive: "50%", negative: "50%" },
    supplier: null, spread: null, gaps: ["No supplier lead was found for this product"] },
];

function report(runId: string, runKey: string, daysAgo: number, status: string, pinned: boolean, category: string, specs: Spec[], overallReason: string, partialGaps: string[]): PiCase {
  const products = build(runKey, daysAgo, specs);
  return {
    runId,
    status,
    pinned,
    pinnedAt: pinned ? isoDaysAgo(daysAgo - 1) : null,
    completedAt: isoDaysAgo(daysAgo),
    caseSaved: true,
    brief: { category, budgetPaise: 15000000, targetPriceMinPaise: 99900, targetPriceMaxPaise: 199900, marketplaces: ["AMAZON", "FLIPKART"] },
    products,
    overall: { candidate_id: products[0].candidate.id, title: products[0].candidate.candidate_title, final_score: specs[0].final, reason: overallReason, note: "Opportunity candidate from public web signal. Not a purchase instruction." },
    cfoRefs: runKey === "a"
      ? [
          { candidate_id: products[0].candidate.id, kind: "ENGINE_RESULT", ref: "sample-engine-ref-landed-cost", leg_key: "cfo.landed_cost", status: "COMPLETE" },
          { candidate_id: products[0].candidate.id, kind: "ENGINE_RESULT", ref: "sample-engine-ref-batch-size", leg_key: "cfo.batch_size", status: "COMPLETE" },
        ]
      : [],
    gaps: partialGaps,
    unavailable: [
      { field: "verified_buyer_reviews", reason: "Metrion has no marketplace access: commentary comes from videos and web pages, not verified buyers." },
      { field: "search_demand", reason: DEMAND_REASON },
      { field: "sales_rank", reason: "Opportunity candidates are not verified sales rankings." },
    ],
    investigationId: null,
  };
}

const REPORTS: Record<string, PiCase> = {
  [RUN_A]: report(RUN_A, "a", 3, "COMPLETE", true, "kitchen storage containers", A, "highest combined score (86.00/100) across proxy score, viewer/web commentary sentiment and supplier availability", ["Only 5 candidates had enough public signal"]),
  [RUN_B]: report(RUN_B, "b", 12, "COMPLETE", false, "steel lunch boxes", B, "highest combined score (84.00/100) across proxy score, viewer/web commentary sentiment and supplier availability", []),
  [RUN_C]: report(RUN_C, "c", 30, "PARTIAL", false, "spice storage", C, "highest combined score (73.00/100) across proxy score, viewer/web commentary sentiment and supplier availability", ["Part of the research could not finish: some sources did not respond"]),
};

const history = (): { items: PiHistoryItem[] } => ({
  items: Object.values(REPORTS).map((c) => ({
    runId: c.runId,
    status: c.status,
    pinned: c.pinned,
    pinnedAt: c.pinnedAt,
    completedAt: c.completedAt,
    category: c.brief.category ?? null,
    budgetPaise: c.brief.budgetPaise ?? null,
    targetPriceMinPaise: c.brief.targetPriceMinPaise ?? null,
    targetPriceMaxPaise: c.brief.targetPriceMaxPaise ?? null,
    marketplaces: c.brief.marketplaces ?? null,
    caseSaved: c.caseSaved,
    topProducts: c.products.slice(0, 3).map((p) => ({ candidateId: p.candidate.id, title: p.candidate.candidate_title, finalScore: p.finalScore })),
  })),
});

/** Pin and unpin (POST) are writes, so they stay unhandled and report that nothing is saved. */
export const piRoutes: DemoRoute[] = [
  { method: "GET", match: /^\/api\/v1\/pi\/research(\?.*)?$/, reply: () => history() },
  {
    method: "GET",
    match: /^\/api\/v1\/pi\/research\/([^/?]+)(\?.*)?$/,
    reply: (m) => {
      const found = REPORTS[decodeURIComponent(m[1])];
      if (!found) throw new ApiError(404, "This saved report is not part of the sample data.");
      return found;
    },
  },
];

export const PI_SAMPLE_RUN_IDS = [RUN_A, RUN_B, RUN_C];
