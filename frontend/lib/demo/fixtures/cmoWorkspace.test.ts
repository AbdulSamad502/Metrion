import { describe, expect, it } from "vitest";
import { demoRespond } from "@/lib/demo/respond";
import type { CorrectionHistory, Dashboard, LinesPage, Mappings, VersionAnalysis } from "@/lib/cmoPerformance";
import type { ImagePage, ImageProducts } from "@/lib/cmoImages";
import type { MarketOverview } from "@/lib/cmoMarket";
import { sampleImageUrl } from "@/lib/demo/sampleImage";

// Sample-data fixtures for the three CMO workspace pages: shapes are pinned by the TypeScript types and these checks.
const get = <T,>(path: string): T => {
  const out = demoRespond<T>(path);
  if (!out.handled) throw new Error(`not handled: ${path}`);
  return out.body;
};
const P = "/api/v1/cmo/performance";

describe("CMO workspace sample data: performance", () => {
  it("serves a complete dashboard whose daily rows add up to the written totals and whose rates match their counts", () => {
    const d = get<Dashboard>(`${P}/dashboard?`);
    const sum = (k: "impressions" | "clicks" | "orders" | "units" | "sales") => d.trend.reduce((a, p) => a + (p[k] ?? 0), 0);
    for (const k of ["impressions", "clicks", "orders", "units", "sales"] as const) expect(sum(k)).toBe(d.current.metrics[k].value);
    expect(d.trend).toHaveLength(30);
    expect(d.current.metrics.ctr.value).toBe(Math.floor((1180 * 10000) / 48200));
    expect(d.aiCredits).toBe(0);
    expect(d.insights.length).toBeGreaterThan(0);
    for (const i of d.insights) expect(i.limits.length).toBeGreaterThan(0);
  });

  it("serves lines, a correction that keeps the imported value, mappings and versions that agree with each other", () => {
    const l = get<LinesPage>(`${P}/lines?marketplace=AMAZON&limit=10&offset=0`);
    expect(l.lines).toHaveLength(10);
    expect(l.total).toBe(30);
    expect(get<LinesPage>(`${P}/lines?marketplace=AMAZON&limit=10&offset=20`).hasMore).toBe(false);
    const fixed = l.lines.filter((x) => x.corrected);
    expect(fixed).toHaveLength(1);
    expect(fixed[0].original.clicks).not.toBe(fixed[0].effective.clicks);
    const h = get<CorrectionHistory>(`${P}/correction-history`);
    expect(h.corrections[0].lineId).toBe(fixed[0].lineId);
    const m = get<Mappings>(`${P}/mappings`);
    expect(m.items.map((i) => i.status)).toEqual(["COMPLETE", "NEEDS_CONFIRMATION"]);
    const v = get<VersionAnalysis>(`${P}/versions?sku=SHG-KC-6&marketplace=AMAZON`);
    expect(v.versions.map((x) => x.state)).toEqual(["NOT_ASSESSED", "OBSERVED_COMPARABLE"]);
    expect(v.versions[1].attribution).toBe("NOT_ATTRIBUTED");
  });
});

describe("CMO workspace sample data: images and market", () => {
  it("lists products whose picture counts match the pages served, with one reviewed set and compliance NOT_ASSESSED", () => {
    const list = get<ImageProducts>("/api/v1/cmo/product-images/products");
    for (const p of list.products) for (const s of p.sets) expect(get<ImagePage>(`/api/v1/cmo/product-images?sku=${p.sku}&marketplace=${s.marketplace}`).images).toHaveLength(s.images);
    const page = get<ImagePage>("/api/v1/cmo/product-images?sku=SHG-KC-6&marketplace=AMAZON");
    expect(page.review?.report.score).toBe(78);
    expect(page.review?.report.dimensions.reduce((a, d) => a + (d.earned ?? 0), 0)).toBe(78);
    expect(page.compliance.status).toBe("NOT_ASSESSED");
    expect(page.images.filter((i) => i.role === "PRIMARY")).toHaveLength(1);
    expect(get<ImagePage>("/api/v1/cmo/product-images?sku=SHG-GJ-4&marketplace=AMAZON").review).toBeNull();
    expect(sampleImageUrl(page.images[0].fileUrl)).toMatch(/^data:image\/svg\+xml/);
  });

  it("serves news and opportunities with sources and dates, demand always unavailable, and filters by marketplace and product", () => {
    const all = get<MarketOverview>("/api/v1/cmo/market-intelligence?");
    expect(all.state).toBe("OK");
    expect(all.news.length).toBeGreaterThan(2);
    expect(all.news.find((n) => n.freshness === "DATE_UNKNOWN")?.publishedAt).toBeNull();
    expect(all.news.every((n) => n.sources.length > 0 && n.sources.every((s) => s.url.startsWith("https://")))).toBe(true);
    for (const o of all.opportunities) expect(o.demand.state).toBe("UNAVAILABLE");
    expect(get<MarketOverview>("/api/v1/cmo/market-intelligence?marketplace=FLIPKART").news.map((n) => n.marketplaces)).toEqual([["FLIPKART"]]);
    expect(get<MarketOverview>("/api/v1/cmo/market-intelligence?sku=SHG-GJ-4").opportunities).toEqual([]);
  });
});
