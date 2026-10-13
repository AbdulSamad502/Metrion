/** DEV-ONLY SAMPLE DATA for local visual checks (`/dashboard/cmo?fixture=1`). Not real, not from any seller, never loaded in a production
 * build (the page imports this only behind `FIXTURE_ALLOWED`, and shows a "SAMPLE DATA" banner whenever it is active). */
import type { CopyPack, HashtagSet, Marketplace, ShowcaseClient, ShowcaseTitle, TrendReport } from "@/lib/cmoShowcase";

const origin = { investigationId: null, turnId: null, kind: "CEO_CHAT" as const };
const mk = (marketplace: Marketplace, max: number, n: number, text: string, approved: boolean): ShowcaseTitle => ({
  generationId: `sample-gen-${marketplace}`, optionId: `sample-opt-${marketplace}-${n}`, rank: n, titleText: text, charCount: text.length, maxChars: max,
  constraint: { sourceUrl: "https://example.invalid/sample", verifiedAt: "2026-10-01T00:00:00Z" },
  approved: approved ? { approvalId: "sample-approval", approvedAt: "2026-10-10T09:00:00Z", editedBySeller: false } : null,
  sku: "SAMPLE-SKU-1", productLabel: "Sample Steel Bottle", marketplace, generatedAt: "2026-10-10T08:00:00Z", origin, usage: null,
});
const titles: Record<Marketplace, ShowcaseTitle[]> = {
  AMAZON: [mk("AMAZON", 200, 1, "Sample Steel Water Bottle 1 Litre Insulated, Leak-proof Lid, BPA Free", true), mk("AMAZON", 200, 2, "Sample Insulated Bottle for Gym and Office, Sample Option Two", false)],
  FLIPKART: [mk("FLIPKART", 150, 1, "Sample Steel Bottle 1 L Insulated Leak-proof", false)],
  MEESHO: [mk("MEESHO", 100, 1, "Sample Steel Bottle 1 L", false)],
};
const bulletTexts = ["SAMPLE BULLET ONE: sample text only.", "SAMPLE BULLET TWO: sample text only.", "SAMPLE BULLET THREE: sample text only.", "SAMPLE BULLET FOUR: sample text only.", "SAMPLE BULLET FIVE: sample text only."];
const pack = (marketplace: Marketplace): CopyPack => ({
  generationId: `sample-gen-${marketplace}`, marketplace, sku: "SAMPLE-SKU-1", productLabel: "Sample Steel Bottle",
  groundedOn: { approvalId: "sample-approval", titleText: titles[marketplace][0].titleText, basis: "Seller-approved title" },
  bullets: bulletTexts.map((text) => ({ text, chars: text.length, max: 250 })),
  description: { text: "Sample description text. This is not real product copy.", chars: 55, max: 2000 },
  backendTerms: marketplace === "AMAZON" ? { text: "sample bottle steel insulated", bytes: 29, maxBytes: 249 } : null,
  generatedAt: "2026-10-10T08:05:00Z", origin, labels: ["Grounded in the approved title"],
});
const trends: TrendReport[] = [{
  generationId: "sample-trend", createdAt: "2026-10-12T06:00:00Z", status: "COMPLETE", nicheTerms: ["sample niche"],
  sections: [{ name: "Market news", state: "OK", findings: [
    { text: "SAMPLE headline one (not a real news item).", sourceName: "Sample Source", sourceUrl: "https://example.invalid/a", publishedAt: "2026-10-11T00:00:00Z", retrievedAt: "2026-10-12T06:00:00Z", corroboration: "Single source" },
    { text: "SAMPLE headline two (publication date deliberately missing).", sourceName: "Sample Source 2", sourceUrl: null, publishedAt: null, retrievedAt: "2026-10-12T06:00:00Z", corroboration: null },
  ] }],
  interpretationLabel: "Interpretation, not a forecast", evidenceRef: "sample-evidence-ref",
}];
const tags: HashtagSet[] = [{ generationId: "sample-gen-AMAZON", sku: "SAMPLE-SKU-1", productLabel: "Sample Steel Bottle", hashtags: ["#SampleTag", "#NotRealData"], generatedAt: "2026-10-10T08:10:00Z", origin }];

export const fixtureClient: ShowcaseClient = {
  products: async () => ({ items: [{ sku: "SAMPLE-SKU-1", label: "Sample Steel Bottle", lastGeneratedAt: "2026-10-10T08:00:00Z", counts: { AMAZON: 1, FLIPKART: 1, MEESHO: 1 } }] }),
  trends: async () => ({ items: trends }),
  titles: async (f) => ({
    items: f.view === "frequent" ? [] : titles[f.marketplace].filter((t) => (!f.approvedOnly || t.approved) && (!f.q || t.titleText.toLowerCase().includes(f.q.toLowerCase()))),
    usage: { available: false, basis: null, since: null },
  }),
  copyPacks: async (f) => ({ items: [pack(f.marketplace)] }),
  hashtags: async () => ({ items: tags }),
  compliance: async () => ({ counts: [{ label: "Titles within the stored character limit", count: 4, basis: "Stored constraint check (sample)" }] }),
  recordUsage: () => {},
};
