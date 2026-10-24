import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { ciRoutes } from "./ci";

const contracts = JSON.parse(readFileSync(join(process.cwd(), "test-support/responseContracts.json"), "utf8")) as Record<string, unknown>;
const SAMPLE_PATH: Record<string, string> = {
  "/api/v1/ci/summary": "/api/v1/ci/summary",
  "/api/v1/ci/workspace": "/api/v1/ci/workspace",
  "/api/v1/ci/alerts": "/api/v1/ci/alerts?days=14",
  "/api/v1/ci/digest/subscription": "/api/v1/ci/digest/subscription",
  "/api/v1/cfo/data-requests": "/api/v1/cfo/data-requests",
  "/api/v1/ci/market-overview": "/api/v1/ci/market-overview/demo-product-airtight-set",
};
/** Contract files mark optional keys with "~" or "?" and the pattern is an example shape; compare top-level key names only. */
const keys = (v: unknown): string[] => (v && typeof v === "object" && !Array.isArray(v) ? Object.keys(v).map((k) => k.replace(/[~?]$/, "")).sort() : Array.isArray(v) && v[0] && typeof v[0] === "object" ? Object.keys(v[0]).map((k) => k.replace(/[~?]$/, "")).sort() : []);

describe("sample data: Competitor Intelligence and Action Center", () => {
  for (const [route, path] of Object.entries(SAMPLE_PATH)) {
    it(`${route} answers with an object or array`, () => {
      const r = ciRoutes.find((x) => x.method === "GET" && x.match.test(path));
      expect(r, `a route for ${path}`).toBeDefined();
      const body = r!.reply(path.match(r!.match) as RegExpMatchArray, undefined);
      expect(body !== null && typeof body === "object").toBe(true);
      const contract = contracts[`GET ${route}`];
      if (contract) expect(keys(Array.isArray(body) ? body : body)).toEqual(keys(contract));
    });
  }

  it("every alert is a threshold-breached one, like the real alert endpoint, and the requests are all OPEN", () => {
    const a = ciRoutes.find((x) => x.match.test("/api/v1/ci/alerts?days=14"))!.reply([] as never, undefined) as { alerts: { thresholdBreached: boolean }[] };
    expect(a.alerts.length).toBeGreaterThanOrEqual(3);
    expect(a.alerts.every((x) => x.thresholdBreached)).toBe(true);
    const d = ciRoutes.find((x) => x.match.test("/api/v1/cfo/data-requests"))!.reply([] as never, undefined) as { status: string }[];
    expect(d.every((x) => x.status === "OPEN")).toBe(true);
  });

  it("the workspace follows the product asked for and keeps honest mixed states", () => {
    const r = ciRoutes.find((x) => x.match.test("/api/v1/ci/workspace?product_id=demo-product-steel-bottle"))!;
    const ws = r.reply("/api/v1/ci/workspace?product_id=demo-product-steel-bottle".match(r.match) as RegExpMatchArray, undefined) as { selectedProductId: string; competitors: unknown[] };
    expect(ws.selectedProductId).toBe("demo-product-steel-bottle");
    const base = ciRoutes.find((x) => x.match.test("/api/v1/ci/workspace"))!.reply("/api/v1/ci/workspace".match(r.match) as RegExpMatchArray, undefined) as { competitors: { priceStatus: string }[] };
    expect(new Set(base.competitors.map((c) => c.priceStatus)).size).toBeGreaterThan(1);
  });
});
