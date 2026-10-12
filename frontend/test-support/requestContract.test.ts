import { afterEach, describe, expect, it, vi } from "vitest";
import { checkRequest, findRoute } from "./requestContract";

const post = (path: string, body: unknown) => checkRequest("POST", `http://localhost:8000${path}`, JSON.stringify(body));
const CASH = "/api/v1/cfo/cash-reconciliation";
const good = { marketplace: "FLIPKART", period_start: "2026-09-01", period_end: "2026-09-30", as_of_date: "2026-09-30" };

describe("the request contract exported from the backend", () => {
  it("accepts a request the backend accepts", () => {
    expect(post(CASH, good)).toEqual([]);
  });

  it("rejects a missing required field, naming it", () => {
    const rest: Record<string, string> = { ...good };
    delete rest.marketplace;
    expect(post(CASH, rest).join(" ")).toContain('missing required "marketplace"');
  });

  it("rejects a field the backend does not have (a typo the backend would silently ignore)", () => {
    expect(post(CASH, { ...good, asOfDate: "2026-09-30" }).join(" ")).toContain('no field "asOfDate"');
  });

  it("rejects a wrong type", () => {
    expect(post(CASH, { ...good, marketplace: 5 }).join(" ")).toMatch(/expected string, got integer/);
  });

  it("rejects a value outside an enum or pattern", () => {
    expect(post("/api/v1/cfo/pnl-for-tenant", { period_start: "2026-09-01", period_end: "2026-09-30", as_of_date: "2026-09-30", recognition_state: "SOMETIMES" }).join(" ")).toContain("does not match");
  });

  it("rejects a route and method the backend does not serve", () => {
    expect(post("/api/v1/cfo/made-up", {}).join(" ")).toContain("not a route the backend serves");
    expect(checkRequest("DELETE", "http://localhost:8000/api/v1/cfo/data-requests", undefined).join(" ")).toContain("not a route");
  });

  it("checks query parameters: undeclared ones and missing required ones", () => {
    expect(checkRequest("GET", "http://localhost:8000/api/v1/ci/alerts?days=14", undefined)).toEqual([]);
    expect(checkRequest("GET", "http://localhost:8000/api/v1/ci/alerts?dayz=14", undefined).join(" ")).toContain('"dayz" is not a parameter');
    expect(checkRequest("GET", "http://localhost:8000/api/v1/cfo/line-status-override", undefined).join(" ")).toContain('"sales_line_id" is required');
  });

  it("ignores anything that is not the backend API", () => {
    expect(checkRequest("GET", "https://example.com/x", undefined)).toEqual([]);
  });

  it("matches path templates", () => {
    expect(findRoute("POST", "/api/v1/ceo/findings/7c1d3e50-0000-4000-8000-000000000000/forget")?.key).toBe("POST /api/v1/ceo/findings/{finding_id}/forget");
  });
});

describe("the guard on a stubbed fetch", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("refuses a request the backend would refuse, and passes one it would accept through to the mock", async () => {
    const mock = vi.fn(async () => new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", mock);
    await expect(fetch(`http://localhost:8000${CASH}`, { method: "POST", body: JSON.stringify({ marketplace: "X" }) })).rejects.toThrow(/CONTRACT: .*missing required/);
    expect(mock).not.toHaveBeenCalled();
    await fetch(`http://localhost:8000${CASH}`, { method: "POST", body: JSON.stringify(good) });
    expect(mock).toHaveBeenCalledTimes(1);
  });
});
