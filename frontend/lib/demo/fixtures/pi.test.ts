import { describe, expect, it } from "vitest";
import { demoRespond } from "@/lib/demo/respond";
import type { PiCase } from "@/lib/piShowcase";
import { PI_SAMPLE_RUN_IDS } from "./pi";

// Sample-data fixtures only: no responseContracts.json entry exists for /pi/research, so the shapes are pinned by the TypeScript types and these checks.
const get = <T,>(path: string) => demoRespond<T>(path);

describe("PI sample data", () => {
  it("lists three saved runs, one pinned, newest first by completion", () => {
    const out = get<{ items: { runId: string; pinned: boolean; topProducts: unknown[] }[] }>("/api/v1/pi/research");
    expect(out.handled && out.body.items.map((i) => i.runId)).toEqual(PI_SAMPLE_RUN_IDS);
    expect(out.handled && out.body.items.filter((i) => i.pinned)).toHaveLength(1);
    expect(out.handled && out.body.items.every((i) => i.topProducts.length === 3)).toBe(true);
  });

  it("returns each report with five products, honest gaps and no hotlinked images", () => {
    for (const id of PI_SAMPLE_RUN_IDS) {
      const out = get<PiCase>(`/api/v1/pi/research/${id}`);
      expect(out.handled).toBe(true);
      if (!out.handled) continue;
      expect(out.body.products).toHaveLength(5);
      expect(out.body.unavailable.length).toBeGreaterThan(0);
      for (const p of out.body.products) {
        expect(p.candidate.image_url).toBeNull();
        expect(p.recommendation.gaps).toBeDefined();
        for (const l of p.supplierLeads) expect(l.contact?.published_price?.disclaimer).toMatch(/Not a quote/);
      }
    }
  });

  it("shows CFO figures only where a confirmed quote exists, and a named gap elsewhere", () => {
    const a = get<PiCase>(`/api/v1/pi/research/${PI_SAMPLE_RUN_IDS[0]}`);
    const b = get<PiCase>(`/api/v1/pi/research/${PI_SAMPLE_RUN_IDS[1]}`);
    if (!a.handled || !b.handled) throw new Error("not handled");
    expect(a.body.products[0].financials.some((f) => f.display && f.status === "COMPLETE")).toBe(true);
    expect(a.body.products[0].financials.some((f) => f.status === "UNAVAILABLE" && f.reason)).toBe(true);
    expect(b.body.products.every((p) => p.financials.length === 0)).toBe(true);
  });

  it("answers an unknown report with a plain 404, and leaves pin/unpin unhandled", () => {
    expect(() => get("/api/v1/pi/research/00000000-0000-4000-8000-000000000000")).toThrow(/not part of the sample data/);
    expect(() => demoRespond("/api/v1/pi/research/x/pin", { method: "POST" })).toThrow(/nothing is saved/);
  });
});
