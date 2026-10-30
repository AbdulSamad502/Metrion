import { describe, expect, it } from "vitest";
import { demoRespond } from "@/lib/demo/respond";
import type { CopyPack, ComplianceSummary, HashtagSet, ShowcaseProduct, ShowcaseTitle, TitlesPage, TrendReport } from "@/lib/cmoShowcase";

// Sample-data fixtures only: no responseContracts.json entry exists for /cmo/showcase, so the shapes are pinned by the TypeScript types and these checks.
const get = <T,>(path: string): T => {
  const out = demoRespond<T>(path);
  if (!out.handled) throw new Error(`not handled: ${path}`);
  return out.body;
};
const B = "/api/v1/cmo/showcase";

describe("CMO sample data", () => {
  it("lists three products with per-marketplace counts that match the titles served", () => {
    const { items } = get<{ items: ShowcaseProduct[] }>(`${B}/products`);
    expect(items).toHaveLength(3);
    for (const p of items) {
      for (const mp of ["AMAZON", "FLIPKART", "MEESHO"] as const) {
        const t = get<TitlesPage>(`${B}/titles?marketplace=${mp}&sku=${p.sku}&view=recent`);
        expect(t.items).toHaveLength(p.counts[mp] ?? -1);
      }
    }
  });

  it("serves titles whose stored character count is their length and within the stated limit, with approved ones marked", () => {
    const t = get<TitlesPage>(`${B}/titles?marketplace=AMAZON&view=recent`);
    expect(t.items.length).toBeGreaterThan(0);
    for (const x of t.items as ShowcaseTitle[]) {
      expect(x.charCount).toBe(x.titleText.length);
      expect(x.charCount).toBeLessThanOrEqual(x.maxChars ?? Infinity);
    }
    expect(get<TitlesPage>(`${B}/titles?marketplace=AMAZON&approvedOnly=true`).items.every((x) => x.approved)).toBe(true);
    expect(get<TitlesPage>(`${B}/titles?marketplace=AMAZON&view=frequent`).items.every((x) => x.usage?.copied || x.usage?.markedUsed)).toBe(true);
  });

  it("serves copy packs, hashtags, trends and a compliance summary", () => {
    const packs = get<{ items: CopyPack[] }>(`${B}/copy-packs?marketplace=AMAZON`).items;
    expect(packs).toHaveLength(3);
    for (const c of packs) {
      expect(c.bullets).toHaveLength(5);
      expect(c.description.chars).toBe(c.description.text.length);
      expect(c.backendTerms?.bytes).toBe(c.backendTerms?.text.length);
    }
    expect(get<{ items: CopyPack[] }>(`${B}/copy-packs?marketplace=FLIPKART`).items.every((c) => c.backendTerms === null)).toBe(true);
    expect(get<{ items: HashtagSet[] }>(`${B}/hashtags`).items).toHaveLength(3);
    expect(get<{ items: TrendReport[] }>(`${B}/trends`).items.length).toBeGreaterThan(0);
    expect(get<ComplianceSummary>(`${B}/compliance`).counts?.length).toBeGreaterThan(0);
  });

  it("leaves the usage-event write alone (it is a plain fetch, not part of sample data)", () => {
    expect(() => demoRespond(`${B}/usage-events`, { method: "POST" })).toThrow(/nothing is saved/);
  });
});
