import { describe, expect, it } from "vitest";
import contracts from "@/test-support/responseContracts.json";
import { ApiError } from "@/lib/api";
import { demoRespond } from "../respond";
import { cfoRoutes } from "./cfo";

/** Is `value` shaped like the committed contract? A key ending in "~" (nullable) or "?" (may be absent) in the contract is optional. Every other contract key must be present, and no key may exist that the contract does not list. */
function sameShape(contract: unknown, value: unknown, at: string, problems: string[]): void {
  if (Array.isArray(contract)) {
    if (!Array.isArray(value)) return void problems.push(`${at}: expected an array`);
    for (const item of value) sameShape(contract[0], item, `${at}[]`, problems);
    return;
  }
  if (contract && typeof contract === "object") {
    if (!value || typeof value !== "object") return void problems.push(`${at}: expected an object`);
    const c = contract as Record<string, unknown>;
    const v = value as Record<string, unknown>;
    const names = new Map(Object.keys(c).map((k) => [k.replace(/[~?]$/, ""), k]));
    for (const [name, key] of names) {
      if (!(name in v) && !/[~?]$/.test(key)) problems.push(`${at}.${name}: missing`);
      else if (name in v && v[name] !== null && v[name] !== undefined) sameShape(c[key], v[name], `${at}.${name}`, problems);
    }
    for (const k of Object.keys(v)) if (!names.has(k)) problems.push(`${at}.${k}: not in the contract`);
  }
}

// One representative request per route: the sample reply never depends on the body.
const SAMPLE_REQUESTS: { method: "GET" | "POST"; path: string }[] = [
  { method: "GET", path: "/api/v1/cfo/imports" },
  { method: "GET", path: "/api/v1/cfo/imports/sample-import-amz-settlement?limit=50&offset=0" },
  { method: "GET", path: "/api/v1/cfo/imports/sample-import-msh-orders?limit=50&offset=0" },
  { method: "GET", path: "/api/v1/cfo/expenses" },
  { method: "GET", path: "/api/v1/cfo/expenses?category=packaging" },
  { method: "GET", path: "/api/v1/cfo/expenses/budget-status?category=packaging&period_start=2026-09-01&period_end=2026-09-30" },
  { method: "GET", path: "/api/v1/cfo/expenses/budget-status?category=storage&period_start=2026-09-01&period_end=2026-09-30" },
  { method: "GET", path: "/api/v1/cfo/seller-goal" },
  ...["pnl", "period-comparison", "funding-readiness", "pricing", "landed-cost", "suppliers/rank", "batch-size", "reconcile", "preview", "anomaly-check", "cash-reconciliation", "gst/analyze-lines", "gst/period-summary", "gst-lookup"].map((p) => ({ method: "POST" as const, path: `/api/v1/cfo/${p}` })),
];

describe("CFO sample data", () => {
  it("answers every route it declares, and each declared route is exercised here", () => {
    for (const r of cfoRoutes) {
      const hit = SAMPLE_REQUESTS.some((q) => q.method === r.method && r.match.test(q.path));
      expect(hit, `${r.method} ${r.match}`).toBe(true);
    }
    for (const q of SAMPLE_REQUESTS) {
      const out = demoRespond(q.path, { method: q.method });
      expect(out.handled, `${q.method} ${q.path}`).toBe(true);
    }
  });

  it("has the same keys as the committed response contract wherever there is one", () => {
    const table = contracts as Record<string, unknown>;
    let checked = 0;
    for (const q of SAMPLE_REQUESTS) {
      const key = `${q.method} ${q.path.split("?")[0]}`;
      if (!(key in table)) continue;
      const out = demoRespond(q.path, { method: q.method });
      const problems: string[] = [];
      if (out.handled) sameShape(table[key], out.body, key, problems);
      expect(problems, key).toEqual([]);
      checked += 1;
    }
    expect(checked).toBeGreaterThanOrEqual(11);
  });

  it("never hands a real-looking id or reference: every engine reference starts with 'sample:'", () => {
    const text = JSON.stringify(SAMPLE_REQUESTS.filter((q) => q.method === "POST").map((q) => demoRespond(q.path, { method: "POST" })));
    const refs = [...text.matchAll(/"engineResultRef":"([^"]*)"/g)].map((m) => m[1]);
    expect(refs.length).toBeGreaterThan(20);
    for (const r of refs) expect(r.startsWith("sample:")).toBe(true);
  });

  it("keeps honest gaps: some results are provisional or unavailable with a stated reason, never a made-up zero", () => {
    const cash = demoRespond<{ cashExpected: { isAvailable: boolean; valuePaise: number | null; unavailableReason: string | null } }>("/api/v1/cfo/cash-reconciliation", { method: "POST" });
    if (!cash.handled) throw new Error("not handled");
    expect(cash.body.cashExpected).toMatchObject({ isAvailable: false, valuePaise: null });
    expect(cash.body.cashExpected.unavailableReason).toBeTruthy();
    const pnl = demoRespond<{ contributionProfit: { confidence: string } }>("/api/v1/cfo/pnl", { method: "POST" });
    if (!pnl.handled) throw new Error("not handled");
    expect(pnl.body.contributionProfit.confidence).toBe("PROVISIONAL");
  });

  it("budget status follows the category asked for, with a distinguished 'no budget set'", () => {
    const get = (c: string) => {
      const o = demoRespond<{ category: string; noBudgetSet: boolean; budgetPaise: number | null; exceeded: boolean }>(`/api/v1/cfo/expenses/budget-status?category=${c}&period_start=2026-09-01&period_end=2026-09-30`);
      if (!o.handled) throw new Error("not handled");
      return o.body;
    };
    expect(get("storage")).toMatchObject({ category: "storage", noBudgetSet: true, budgetPaise: null });
    expect(get("packaging")).toMatchObject({ category: "packaging", noBudgetSet: false, exceeded: true });
  });

  it("an unknown import is a plain 404, and writes stay unhandled (so they report that nothing is saved)", () => {
    expect(() => demoRespond("/api/v1/cfo/imports/not-a-sample")).toThrow(ApiError);
    for (const [method, path] of [["PUT", "/api/v1/cfo/expenses"], ["PUT", "/api/v1/cfo/expenses/budget"], ["PUT", "/api/v1/cfo/seller-goal"], ["POST", "/api/v1/cfo/gst-lookup/accept"]] as const) {
      expect(() => demoRespond(path, { method }), `${method} ${path}`).toThrow(/nothing is saved/);
    }
  });

  it("does not take over the data-requests list or the Profit Calculator", () => {
    expect(cfoRoutes.some((r) => r.match.test("/api/v1/cfo/data-requests"))).toBe(false);
    expect(demoRespond("/api/v1/cfo/pnl-scenario", { method: "POST" }).handled).toBe(false);
  });
});
